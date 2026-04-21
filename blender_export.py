"""Blender-side import/export script for 3d-converter.

Invoked by the CLI as:
    blender --background --factory-startup \
        --python blender_export.py -- \
        --input <path> --output-dir <path> --stem <name> \
        [--formats glb,usdz] [--usdz-max-texture 2048]

Everything after `--` is this script's argv.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"AKR:{msg}", flush=True)


def mesh_objects() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def clear_scene() -> None:
    """Remove all default objects."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in list(bpy.data.meshes):
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in list(bpy.data.materials):
        if block.users == 0:
            bpy.data.materials.remove(block)


def import_model(filepath: str) -> None:
    ext = Path(filepath).suffix.lower().lstrip(".")
    log(f"[import] {ext.upper()} from {filepath}")

    if ext == "blend":
        bpy.ops.wm.open_mainfile(filepath=filepath)
    elif ext == "obj":
        bpy.ops.wm.obj_import(filepath=filepath)
    elif ext == "fbx":
        if hasattr(bpy.ops.wm, "fbx_import"):
            bpy.ops.wm.fbx_import(filepath=filepath)
        else:
            bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext in ("gltf", "glb"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == "stl":
        bpy.ops.wm.stl_import(filepath=filepath)
    elif ext == "ply":
        bpy.ops.wm.ply_import(filepath=filepath)
    elif ext in ("usd", "usda", "usdc", "usdz"):
        bpy.ops.wm.usd_import(filepath=filepath)
    else:
        raise ValueError(f"Unsupported format: {ext}")

    meshes = mesh_objects()
    verts = sum(len(o.data.vertices) for o in meshes)
    faces = sum(len(o.data.polygons) for o in meshes)
    log(f"[import] {len(meshes)} meshes, {verts:,} verts, {faces:,} faces")


# ---------------------------------------------------------------------------
# texture downscaling (for USDZ)
# ---------------------------------------------------------------------------

def downscale_textures(max_px: int) -> dict[str, tuple[int, int]]:
    """Scale images to max_px on longest side. Returns originals for restore."""
    originals: dict[str, tuple[int, int]] = {}
    for img in bpy.data.images:
        if img.type != "IMAGE" or not img.has_data:
            continue
        w, h = img.size[0], img.size[1]
        if max(w, h) <= max_px:
            continue
        originals[img.name] = (w, h)
        ratio = max_px / max(w, h)
        new_w, new_h = max(1, int(w * ratio)), max(1, int(h * ratio))
        img.scale(new_w, new_h)
        log(f"[texture] {img.name}: {w}x{h} -> {new_w}x{new_h}")
    return originals


def restore_textures(originals: dict[str, tuple[int, int]]) -> None:
    for name, (w, h) in originals.items():
        img = bpy.data.images.get(name)
        if img:
            img.scale(w, h)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def select_all_meshes() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects():
        obj.select_set(True)


def export_glb(filepath: str) -> None:
    log(f"[export] GLB -> {filepath}")
    select_all_meshes()
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        use_selection=True,
        export_format="GLB",
        export_apply=True,
        export_yup=True,
    )
    size = Path(filepath).stat().st_size
    log(f"[export] GLB done: {size:,} bytes")


def export_usdz(filepath: str, max_texture: int | None = None) -> None:
    log(f"[export] USDZ -> {filepath}")
    select_all_meshes()

    originals: dict[str, tuple[int, int]] = {}
    if max_texture:
        originals = downscale_textures(max_texture)

    bpy.ops.wm.usd_export(filepath=filepath, selected_objects_only=True)

    if originals:
        restore_textures(originals)

    size = Path(filepath).stat().st_size
    log(f"[export] USDZ done: {size:,} bytes")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--stem", required=True)
    ap.add_argument("--formats", default="glb,usdz")
    ap.add_argument("--usdz-max-texture", type=int, default=0)
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    formats = [f.strip() for f in args.formats.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"success": False, "outputs": {}}

    try:
        clear_scene()
        import_model(args.input)

        if "glb" in formats:
            glb_path = str(out_dir / f"{args.stem}.glb")
            export_glb(glb_path)
            result["outputs"]["glb"] = glb_path

        if "usdz" in formats:
            usdz_path = str(out_dir / f"{args.stem}.usdz")
            max_tex = args.usdz_max_texture or None
            export_usdz(usdz_path, max_texture=max_tex)
            result["outputs"]["usdz"] = usdz_path

        result["success"] = True

    except Exception as e:
        import traceback
        log(f"[error] {type(e).__name__}: {e}")
        log(traceback.format_exc())
        result["error"] = f"{type(e).__name__}: {e}"

    print(f"AKR_RESULT:{json.dumps(result)}", flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
