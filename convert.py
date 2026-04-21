#!/usr/bin/env python3
"""3d-converter — convert any 3D model to GLB + USDZ for Web AR.

Usage:
    python convert.py INPUT -o OUTPUT_DIR [options]

Examples:
    python convert.py model.fbx -o output/
    python convert.py model.obj -o output/ --compress meshopt --simplify 0.9
    python convert.py model.glb -o output/ --formats glb,usdz --usdz-max-texture 1024
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BLENDER_SCRIPT = SCRIPT_DIR / "blender_export.py"


# ---------------------------------------------------------------------------
# Blender subprocess
# ---------------------------------------------------------------------------

def find_blender(explicit: str | None = None) -> str:
    """Locate the Blender binary."""
    if explicit:
        return explicit
    # Common locations
    for candidate in ["blender", "/usr/bin/blender", "/snap/bin/blender",
                       "/opt/blender/blender"]:
        if shutil.which(candidate):
            return candidate
    print("ERROR: Blender not found. Install it or pass --blender <path>.",
          file=sys.stderr)
    sys.exit(1)


def run_blender(
    blender: str,
    input_path: Path,
    output_dir: Path,
    stem: str,
    formats: str,
    usdz_max_texture: int,
) -> dict:
    """Run the Blender export script and return the result dict."""
    cmd = [
        blender,
        "--background",
        "--factory-startup",
        "--python", str(BLENDER_SCRIPT),
        "--",
        "--input", str(input_path),
        "--output-dir", str(output_dir),
        "--stem", stem,
        "--formats", formats,
        "--usdz-max-texture", str(usdz_max_texture),
    ]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )

    tail: list[str] = []
    stderr_lines: list[str] = []

    def drain_stderr():
        assert proc.stderr
        for line in proc.stderr:
            stderr_lines.append(line.rstrip())

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    assert proc.stdout
    for line in proc.stdout:
        line = line.rstrip("\n")
        tail.append(line)
        if len(tail) > 200:
            tail.pop(0)
        if line.startswith("AKR:"):
            print(line[4:].lstrip(), flush=True)

    proc.wait()
    t.join(timeout=5)

    # Extract result JSON
    for line in reversed(tail):
        if line.startswith("AKR_RESULT:"):
            try:
                return json.loads(line[len("AKR_RESULT:"):].strip())
            except json.JSONDecodeError:
                pass

    if proc.returncode != 0:
        err = "\n".join(stderr_lines[-10:]) or "\n".join(tail[-10:])
        return {"success": False, "error": f"Blender exited {proc.returncode}: {err}"}

    return {"success": False, "error": "No result from Blender"}


# ---------------------------------------------------------------------------
# gltfpack post-processing
# ---------------------------------------------------------------------------

def run_gltfpack(
    input_glb: Path,
    output_glb: Path,
    method: str,
    simplify: float | None,
) -> dict:
    """Run gltfpack on a GLB file."""
    gltfpack = shutil.which("gltfpack")
    if not gltfpack:
        print("WARNING: gltfpack not found, skipping compression.", file=sys.stderr)
        if input_glb != output_glb:
            shutil.copyfile(input_glb, output_glb)
        return {"compressed": False, "reason": "gltfpack not installed"}

    args = [gltfpack, "-i", str(input_glb), "-o", str(output_glb)]

    if method == "meshopt":
        args.append("-cc")
    elif method == "draco":
        args.append("-cf")

    if simplify is not None:
        args.extend(["-si", f"{simplify:.4f}"])

    print(f"[gltfpack] {method} compression...", flush=True)
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"WARNING: gltfpack failed: {res.stderr.strip()}", file=sys.stderr)
        if input_glb != output_glb:
            shutil.copyfile(input_glb, output_glb)
        return {"compressed": False, "error": res.stderr.strip()}

    in_size = input_glb.stat().st_size
    out_size = output_glb.stat().st_size
    ratio = (1 - out_size / in_size) * 100 if in_size > 0 else 0
    print(f"[gltfpack] {in_size:,} -> {out_size:,} bytes ({ratio:.1f}% reduction)",
          flush=True)
    return {
        "compressed": True,
        "method": method,
        "input_bytes": in_size,
        "output_bytes": out_size,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert any 3D model to GLB + USDZ for Web AR.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python convert.py model.fbx -o output/
  python convert.py model.obj -o output/ --compress meshopt
  python convert.py scene.blend -o output/ --formats usdz --usdz-max-texture 1024
  python convert.py model.glb -o output/ --compress meshopt --simplify 0.9
        """,
    )
    ap.add_argument("input", type=Path, help="Input 3D model file")
    ap.add_argument("-o", "--output-dir", type=Path, required=True,
                    help="Output directory")
    ap.add_argument("--stem", default=None,
                    help="Output filename stem (default: input filename)")
    ap.add_argument("--formats", default="glb,usdz",
                    help="Comma-separated output formats (default: glb,usdz)")
    ap.add_argument("--compress", default=None, choices=["meshopt", "draco"],
                    help="GLB compression method via gltfpack")
    ap.add_argument("--simplify", type=float, default=None,
                    help="Simplification ratio for gltfpack (e.g. 0.9 = 90%% quality)")
    ap.add_argument("--usdz-max-texture", type=int, default=0,
                    help="Max texture dimension for USDZ (e.g. 2048)")
    ap.add_argument("--blender", default=None,
                    help="Path to Blender executable")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        return 1

    blender = find_blender(args.blender)
    stem = args.stem or args.input.stem
    formats_list = [f.strip().lower() for f in args.formats.split(",")]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # If compressing GLB, Blender exports to a temp file first.
    use_gltfpack = args.compress and "glb" in formats_list
    if use_gltfpack:
        blender_glb_stem = stem + ".pre-pack"
    else:
        blender_glb_stem = stem

    # Blender always writes to the final stem for USDZ (no post-processing).
    # For GLB with compression, it writes to .pre-pack.glb.
    blender_stem = blender_glb_stem if use_gltfpack else stem

    print(f"Input:   {args.input}")
    print(f"Output:  {args.output_dir}/")
    print(f"Formats: {', '.join(formats_list)}")
    if args.compress:
        print(f"Compress: {args.compress}")
    print()

    # Step 1: Blender import + export
    # For USDZ, Blender writes directly to <stem>.usdz.
    # For GLB with compression, Blender writes to <stem>.pre-pack.glb.
    # We need separate stems if both are requested with compression.
    blender_formats = ",".join(formats_list)
    result = run_blender(
        blender=blender,
        input_path=args.input.resolve(),
        output_dir=args.output_dir.resolve(),
        stem=stem if not use_gltfpack else stem,
        formats=blender_formats,
        usdz_max_texture=args.usdz_max_texture,
    )

    if not result.get("success"):
        print(f"\nERROR: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    # Step 2: gltfpack compression on GLB
    if use_gltfpack:
        glb_raw = args.output_dir / f"{stem}.glb"
        glb_final = args.output_dir / f"{stem}.glb"
        glb_prepack = args.output_dir / f"{stem}.pre-pack.glb"

        if glb_raw.exists():
            # Rename raw to .pre-pack, then compress to final
            glb_raw.rename(glb_prepack)
            pack_result = run_gltfpack(glb_prepack, glb_final, args.compress, args.simplify)
        else:
            pack_result = {"compressed": False, "error": "GLB not found"}

    # Summary
    print("\n--- Output ---")
    for fmt in formats_list:
        out_file = args.output_dir / f"{stem}.{fmt}"
        if out_file.exists():
            size_mb = out_file.stat().st_size / (1024 * 1024)
            print(f"  {out_file.name:30s}  {size_mb:8.2f} MB")
        else:
            print(f"  {stem}.{fmt:10s}  MISSING")

    # Keep .pre-pack.glb for reference if compression was used
    if use_gltfpack:
        prepack = args.output_dir / f"{stem}.pre-pack.glb"
        if prepack.exists():
            size_mb = prepack.stat().st_size / (1024 * 1024)
            print(f"  {prepack.name:30s}  {size_mb:8.2f} MB  (uncompressed)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
