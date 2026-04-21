# 3d-converter

Convert any 3D model to **GLB** and **USDZ** for Web AR delivery.

Produces both formats needed for the `<model-viewer>` web component:
- **GLB** — Android / WebXR / desktop viewers
- **USDZ** — iOS AR Quick Look (Safari)

## Quick start

```bash
# Install prerequisites (Blender + gltfpack)
bash install.sh

# Convert a model to GLB + USDZ
python convert.py model.fbx -o output/

# With meshopt compression
python convert.py model.obj -o output/ --compress meshopt
```

## Supported input formats

| Format | Extensions |
|--------|-----------|
| Wavefront OBJ | `.obj` |
| Autodesk FBX | `.fbx` |
| glTF / GLB | `.gltf`, `.glb` |
| STL | `.stl` |
| PLY | `.ply` |
| USD | `.usd`, `.usda`, `.usdc`, `.usdz` |
| Blender | `.blend` |

## Options

```
python convert.py INPUT -o OUTPUT_DIR [options]

Required:
  INPUT                 Input 3D model file
  -o, --output-dir      Output directory

Optional:
  --stem NAME           Output filename (default: input filename)
  --formats FMT         Comma-separated: glb,usdz (default: glb,usdz)
  --compress METHOD     GLB compression: meshopt or draco
  --simplify RATIO      Simplification ratio (0.0-1.0, e.g. 0.9 = 90% quality)
  --usdz-max-texture N  Max texture dimension for USDZ export (e.g. 2048)
  --blender PATH        Path to Blender executable
```

## Examples

```bash
# Basic conversion
python convert.py chair.fbx -o output/

# GLB only with Draco compression
python convert.py model.obj -o output/ --formats glb --compress draco

# USDZ only with texture downscaling
python convert.py scan.glb -o output/ --formats usdz --usdz-max-texture 1024

# Full pipeline: both formats, meshopt, simplification, texture cap
python convert.py assembly.fbx -o output/ \
    --compress meshopt --simplify 0.9 --usdz-max-texture 2048
```

## Web AR usage

Use with [model-viewer](https://modelviewer.dev/) for cross-platform AR:

```html
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0/model-viewer.min.js"></script>

<model-viewer
  src="model.glb"
  ios-src="model.usdz"
  ar
  ar-modes="webxr scene-viewer quick-look"
  camera-controls
  style="width: 100%; height: 400px;">
</model-viewer>
```

## Prerequisites

- **Blender >= 4.1** (5.x recommended) — 3D import/export engine
- **gltfpack** (optional) — GLB compression via meshopt or Draco
- **Python >= 3.10** — CLI wrapper only; Blender ships its own Python

Run `bash install.sh` to install everything automatically on Ubuntu/Debian.

## How it works

1. **Blender** runs headless (`--background`) to import the source model and export to GLB and/or USDZ
2. **gltfpack** (optional) post-processes the GLB for mesh compression (meshopt/Draco) and optional simplification
3. USDZ textures are downscaled inside Blender before export if `--usdz-max-texture` is set

No Python dependencies beyond the standard library are required for the CLI.

## GLB compression notes

| Method | Extension | Compatibility | Size |
|--------|-----------|--------------|------|
| meshopt | `EXT_meshopt_compression` | three.js, Babylon.js, model-viewer | Smallest |
| draco | `KHR_draco_mesh_compression` | Widest support | Slightly larger |
| none | — | Universal | Largest |

## USDZ notes

- USDZ is a zero-compression zip archive (by design, for memory-mapped access)
- The only size lever is texture resolution — use `--usdz-max-texture` to cap it
- Blender's native USD export produces AR Quick Look-compatible USDZ files

## License

MIT
