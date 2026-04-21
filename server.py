"""HTTP wrapper around convert.py for on-demand GLB -> USDZ conversion.

Endpoints:
    POST   /jobs                 multipart upload { file: GLB, modelId?, versionNumber? }
                                 -> { jobId, statusUrl, resultUrl }
    GET    /jobs/{id}            -> { status, stage, message?, error? }
    GET    /jobs/{id}.usdz       -> binary USDZ with correct MIME
    DELETE /jobs/{id}            cleans up the job's temp dir

Run:
    uvicorn server:app --host 0.0.0.0 --port 8787 --reload
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

SCRIPT_DIR = Path(__file__).resolve().parent
CONVERT_PY = SCRIPT_DIR / "convert.py"
JOBS_ROOT = Path(os.environ.get("USDZ_JOBS_ROOT", "/tmp/usdz-jobs"))
JOBS_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
CONVERT_TIMEOUT_SECONDS = 10 * 60
JOB_TTL_SECONDS = 60 * 60


def resolve_blender() -> Optional[str]:
    """Locate Blender across platforms. Returns a path or None to let
    convert.py's own lookup try (which covers PATH + typical Linux locations).

    Order: BLENDER env var → shutil.which → macOS app-bundle paths.
    """
    explicit = os.environ.get("BLENDER")
    if explicit and Path(explicit).exists():
        return explicit
    if shutil.which("blender"):
        return shutil.which("blender")
    mac_candidates = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "/opt/homebrew/bin/blender",
    ]
    for c in mac_candidates:
        if Path(c).exists():
            return c
    return None


BLENDER_PATH = resolve_blender()


@dataclass
class Job:
    id: str
    workdir: Path
    status: str = "queued"            # queued | running | done | error
    stage: Optional[str] = None       # import | export | compress
    message: Optional[str] = None
    error: Optional[str] = None
    output_path: Optional[Path] = None
    created_at: float = field(default_factory=time.time)


jobs: dict[str, Job] = {}
jobs_lock = asyncio.Lock()


app = FastAPI(title="3d-converter service")

# Allow direct iPhone access as a fallback if the Vite proxy isn't used.
# The proxied path (same-origin to the Vite dev server) doesn't need CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def classify_stage(line: str) -> Optional[str]:
    """Map a stdout line from convert.py/Blender to a UI-friendly stage."""
    s = line.strip()
    low = s.lower()
    if "importing" in low or "loading" in low and ".glb" in low:
        return "import"
    if "export" in low and "usd" in low:
        return "export"
    if "packaging" in low or "gltfpack" in low or "writing" in low:
        return "compress"
    return None


async def normalize_with_gltfpack(input_glb: Path) -> Optional[Path]:
    """Run the GLB through gltfpack to strip EXT_meshopt_compression (and any
    other encodings Blender's glTF importer lacks support for). Returns the
    normalized path on success, or None if gltfpack isn't available or the
    pass fails (caller falls through to the raw input)."""
    gltfpack = shutil.which("gltfpack")
    if not gltfpack:
        return None
    out = input_glb.with_name("input.normalized.glb")
    try:
        proc = await asyncio.create_subprocess_exec(
            gltfpack, "-i", str(input_glb), "-o", str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await proc.communicate()
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
    except Exception:
        pass
    return None


async def run_convert(job: Job, input_glb: Path) -> None:
    """Spawn convert.py and update the job record as output streams in."""
    job.status = "running"
    job.stage = "import"
    job.message = "Normalizing GLB..."

    source = await normalize_with_gltfpack(input_glb) or input_glb

    cmd = [
        sys.executable,
        str(CONVERT_PY),
        str(source),
        "-o", str(job.workdir),
        "--stem", input_glb.stem,
        "--formats", "usdz",
    ]
    if BLENDER_PATH:
        cmd.extend(["--blender", BLENDER_PATH])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        job.status = "error"
        job.error = f"Failed to launch converter: {e}"
        return

    stderr_tail: list[str] = []

    async def drain_stdout():
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            stage = classify_stage(line)
            if stage:
                job.stage = stage
            job.message = line[:200] if line else job.message

    async def drain_stderr():
        assert proc.stderr
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            if line:
                stderr_tail.append(line)
                if len(stderr_tail) > 40:
                    stderr_tail.pop(0)

    try:
        await asyncio.wait_for(
            asyncio.gather(drain_stdout(), drain_stderr(), proc.wait()),
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        proc.kill()
        job.status = "error"
        job.error = f"Conversion timed out after {CONVERT_TIMEOUT_SECONDS}s"
        return

    if proc.returncode != 0:
        job.status = "error"
        job.error = "\n".join(stderr_tail[-10:]) or f"convert.py exited {proc.returncode}"
        return

    # convert.py writes <stem>.usdz; our stem is input_glb.stem.
    output = job.workdir / f"{input_glb.stem}.usdz"
    if not output.exists():
        # Fallback: pick up any .usdz in the workdir.
        candidates = list(job.workdir.glob("*.usdz"))
        if not candidates:
            job.status = "error"
            job.error = "Conversion finished but no USDZ file was produced"
            return
        output = candidates[0]

    job.output_path = output
    job.status = "done"
    job.stage = None
    job.message = None


@app.post("/jobs")
async def create_job(
    file: UploadFile = File(...),
    modelId: Optional[str] = Form(None),
    versionNumber: Optional[str] = Form(None),
):
    if not file.filename or not file.filename.lower().endswith(".glb"):
        raise HTTPException(400, detail="Upload must be a .glb file")

    job_id = uuid.uuid4().hex
    workdir = JOBS_ROOT / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    input_glb = workdir / "input.glb"

    # Stream to disk with a size cap.
    written = 0
    with open(input_glb, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                out.close()
                shutil.rmtree(workdir, ignore_errors=True)
                raise HTTPException(413, detail="Upload exceeds max size")
            out.write(chunk)

    if modelId:
        (workdir / "modelId.txt").write_text(f"{modelId}\nversion={versionNumber or ''}\n")

    job = Job(id=job_id, workdir=workdir)
    async with jobs_lock:
        jobs[job_id] = job

    asyncio.create_task(run_convert(job, input_glb))

    return {
        "jobId": job_id,
        "statusUrl": f"/jobs/{job_id}",
        "resultUrl": f"/jobs/{job_id}.usdz",
    }


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    return JSONResponse({
        "status": job.status,
        "stage": job.stage,
        "message": job.message,
        "error": job.error,
    })


@app.get("/jobs/{job_id}.usdz")
async def get_result(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.status != "done" or not job.output_path or not job.output_path.exists():
        raise HTTPException(404, detail=f"Result not ready (status={job.status})")

    return FileResponse(
        job.output_path,
        media_type="model/vnd.usdz+zip",
        headers={
            "Content-Disposition": f'inline; filename="{job.output_path.name}"',
            "Cache-Control": "no-store",
        },
    )


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    async with jobs_lock:
        job = jobs.pop(job_id, None)
    if job:
        shutil.rmtree(job.workdir, ignore_errors=True)
    return {"ok": True}


async def reaper():
    while True:
        await asyncio.sleep(5 * 60)
        now = time.time()
        async with jobs_lock:
            stale = [jid for jid, j in jobs.items() if now - j.created_at > JOB_TTL_SECONDS]
            for jid in stale:
                j = jobs.pop(jid, None)
                if j:
                    shutil.rmtree(j.workdir, ignore_errors=True)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(reaper())
