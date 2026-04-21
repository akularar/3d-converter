# 3d-converter

Standalone CLI tool that converts any Blender-supported 3D model into
**glTF/GLB** and **USDZ** for Web AR delivery (Android + iOS).

## How it works

Two-layer architecture:

1. **CLI layer** (`convert.py`) — argument parsing, Blender subprocess
   orchestration, gltfpack post-processing. Pure Python, no `bpy`.
2. **Blender script** (`blender_export.py`) — runs inside headless Blender
   via `blender --background --python blender_export.py -- <args>`.
   Imports the source model, optionally downscales textures, and exports
   to GLB + USDZ.

Communication: CLI passes args after `--` to the Blender script. Blender
writes output files directly; CLI then optionally runs gltfpack on the
GLB for meshopt/Draco compression.

## Supported input formats

Anything Blender 5.x can import:
- **OBJ** (Wavefront) — `bpy.ops.wm.obj_import()`
- **FBX** (Autodesk) — `bpy.ops.wm.fbx_import()` or `import_scene.fbx`
- **glTF/GLB** — `bpy.ops.import_scene.gltf()`
- **STL** — `bpy.ops.wm.stl_import()`
- **PLY** — `bpy.ops.wm.ply_import()`
- **USD/USDA/USDC/USDZ** — `bpy.ops.wm.usd_import()`
- **BLEND** — opened directly via `bpy.ops.wm.open_mainfile()`

## Output formats

- **GLB** (binary glTF) — primary web format, optionally compressed with
  gltfpack (meshopt or Draco)
- **USDZ** — iOS AR Quick Look format; zero-compression zip by spec,
  texture downscaling is the main size lever

## gltfpack compression

When gltfpack is installed and `--compress` is passed:
- `meshopt` (default): EXT_meshopt_compression + KHR_mesh_quantization
- `draco`: KHR_draco_mesh_compression (wider compatibility, slightly less
  efficient)
- Simplification via `--simplify 0.9` (retain 90% quality)

## USDZ texture downscaling

`--usdz-max-texture 2048` scales all textures to 2048px max dimension
before USDZ export, then restores originals so GLB keeps full resolution.

## Usage examples

```bash
# Basic: convert FBX to GLB + USDZ
python convert.py model.fbx -o output/

# With meshopt compression + texture downscaling
python convert.py model.obj -o output/ --compress meshopt --usdz-max-texture 1024

# GLB only (skip USDZ)
python convert.py model.glb -o output/ --formats glb

# USDZ only
python convert.py model.fbx -o output/ --formats usdz

# Custom Blender path
python convert.py model.fbx -o output/ --blender /opt/blender/blender
```

## Prerequisites

Run `bash install.sh` to install everything, or manually:
- **Blender >= 4.1** (5.x recommended)
- **gltfpack** (optional, for compression) — from meshoptimizer releases
- **Python >= 3.10** (only for the CLI wrapper; Blender has its own Python)

## File structure

```
3d-converter/
├── convert.py          # CLI entry point
├── blender_export.py   # Blender-side import/export script
├── install.sh          # Installs Blender + gltfpack
├── CLAUDE.md           # This file
└── README.md           # User-facing docs
```
