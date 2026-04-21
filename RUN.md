# Running the converter as an HTTP service

`server.py` wraps `convert.py` behind a FastAPI app so a browser (or any HTTP
client) can request GLB → USDZ conversions on demand. Used by the Akular
`web-akular/model-tester` app for iOS AR Quick Look support.

## Setup

### macOS

```bash
# 1. Blender (install.sh is Debian-only; on Mac grab the cask)
brew install --cask blender        # installs to /Applications/Blender.app
# optional: brew install gltfpack   # for GLB compression, not used for USDZ-only

# 2. Python deps in a venv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi "uvicorn[standard]" python-multipart
```

**Blender binary note:** on macOS the binary isn't on PATH. `server.py` auto-
detects `/Applications/Blender.app/Contents/MacOS/Blender` and passes it to
`convert.py` via `--blender`. Override with `export BLENDER=/custom/path`.

### Linux (Debian/Ubuntu)

```bash
bash install.sh                    # Blender + gltfpack to /usr/local/bin
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi "uvicorn[standard]" python-multipart
```

## Run

```bash
source .venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8787 --reload
```

Binding `0.0.0.0` lets the iPhone reach it directly over LAN. The Vite dev
server in the model-tester app proxies `/api/convert` → `127.0.0.1:8787` by
default, so when running everything on the same machine you don't need LAN.

## Endpoints

| Method | Path              | Purpose                                             |
|--------|-------------------|-----------------------------------------------------|
| POST   | `/jobs`           | multipart upload `file=<.glb>` → `{ jobId }`        |
| GET    | `/jobs/{id}`      | `{ status, stage, message?, error? }`               |
| GET    | `/jobs/{id}.usdz` | streams the USDZ with `model/vnd.usdz+zip`          |
| DELETE | `/jobs/{id}`      | drop the job and remove its temp dir                |

Jobs live in `/tmp/usdz-jobs/<id>/` (override with `USDZ_JOBS_ROOT`) and are
reaped after 1 hour.

## Smoke test

```bash
# Any GLB will do — grab one with curl or from an existing project.
curl -F file=@sample.glb http://127.0.0.1:8787/jobs
# → {"jobId":"abc123",...}

# Poll until status is "done"
curl http://127.0.0.1:8787/jobs/abc123

# Fetch the result
curl -o out.usdz http://127.0.0.1:8787/jobs/abc123.usdz
file out.usdz                      # should report "Zip archive data"
```

On macOS you can double-click `out.usdz` to preview with Quick Look — a good
sanity check that the file is valid.

## End-to-end iPhone test

The frontend piece lives in a sibling repo (`web-akular/apps/model-tester`).
The iPhone hits the Vite dev server over HTTPS; Vite proxies `/api/convert/*`
to this service. See that app's setup; this service just needs to be running.
