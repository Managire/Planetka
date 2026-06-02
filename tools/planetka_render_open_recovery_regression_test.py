#!/usr/bin/env python3
"""Regression test: render animation, reopen scene, and verify queued recovery resolve completes."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from planetka_e2e_common import (
    E2EError,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    drain_queued_resolve,
    enable_module,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    purge_planetka_data,
    read_scene_last_resolve_error,
    write_json,
)


TAG = "[Planetka Render Open Recovery Regression]"
REPORT_PATH = Path(tempfile.gettempdir()) / "planetka_render_open_recovery_regression_report.json"
FALLBACK_DIR = Path(_REPO_ROOT) / "Resources" / "Fallback Images"
_PLANETKA_PREFIXES = {"S2", "EL", "WT", "PO"}


def _log(message):
    print(f"{TAG} {message}", flush=True)


def _assert(condition, message):
    if not condition:
        raise E2EError(str(message))


def _is_planetka_tile_image(image):
    if image is None:
        return False
    name = str(getattr(image, "name", "") or "").strip()
    raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
    if str(name).split("_", 1)[0].upper() in _PLANETKA_PREFIXES:
        return True
    lowered = raw_path.replace("\\", "/").lower()
    if "/planetka_cache/" in lowered:
        return True
    if any(f"/{prefix.lower()}/" in lowered for prefix in _PLANETKA_PREFIXES):
        return True
    return False


def _image_prefix(image):
    name = str(getattr(image, "name", "") or "").strip()
    prefix = str(name).split("_", 1)[0].upper()
    if prefix in _PLANETKA_PREFIXES:
        return prefix
    raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").replace("\\", "/").lower()
    for candidate in _PLANETKA_PREFIXES:
        if f"/{candidate.lower()}/" in raw_path:
            return candidate
    return "S2"


def _make_texture_source_tree(base_dir):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    rules = (
        ("S2", "S2_", "ocean_pixel_final_20.exr"),
        ("EL", "EL_", "black_pixel_20.exr"),
        ("WT", "WT_", "blue_pixel_20.exr"),
    )
    for folder_name, prefix, source_name in rules:
        source = FALLBACK_DIR / source_name
        _assert(source.is_file(), f"Missing fallback sample: {source}")
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, folder / f"{prefix}x000_y000_z360_d360.exr")
        shutil.copyfile(source, folder / f"{prefix}x180_y000_z180_d180.exr")
    (base / "PO").mkdir(parents=True, exist_ok=True)


def _mark_planetka_images_missing(missing_root, images=None):
    target_root = Path(missing_root)
    forced = 0
    image_iter = list(images) if images is not None else list(getattr(bpy.data, "images", ()))
    for image in image_iter:
        if not _is_planetka_tile_image(image):
            continue
        if getattr(image, "packed_file", None) is not None:
            continue
        raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
        prefix = _image_prefix(image)
        ext = str(Path(raw_path).suffix or "").strip()
        if not ext:
            ext = ".tif" if prefix == "PO" else ".exr"
        file_name = str(Path(raw_path).name or "").strip()
        if not file_name:
            file_name = f"{prefix}_forced_missing_{forced:04d}{ext}"
        missing_path = target_root / prefix / file_name
        try:
            image.source = "FILE"
        except Exception:
            pass
        try:
            image.filepath_raw = str(missing_path)
            image.filepath = str(missing_path)
        except Exception:
            continue
        forced += 1
    return int(forced)


def _count_missing_planetka_tile_images(images=None):
    missing = 0
    image_iter = list(images) if images is not None else list(getattr(bpy.data, "images", ()))
    for image in image_iter:
        if not _is_planetka_tile_image(image):
            continue
        if getattr(image, "packed_file", None) is not None:
            continue
        raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
        if not raw_path:
            continue
        try:
            abs_path = str(bpy.path.abspath(raw_path) or "").strip()
        except Exception:
            abs_path = raw_path
        if abs_path and not os.path.isfile(abs_path):
            missing += 1
    return int(missing)


def _collect_image_nodes(node_tree, out, visited):
    if node_tree is None:
        return
    tree_id = id(node_tree)
    if tree_id in visited:
        return
    visited.add(tree_id)
    nodes = getattr(node_tree, "nodes", None)
    if nodes is None:
        return
    for node in nodes:
        if str(getattr(node, "bl_idname", "") or "") == "ShaderNodeTexImage":
            image = getattr(node, "image", None)
            if _is_planetka_tile_image(image):
                out.append(image)
            continue
        if str(getattr(node, "type", "") or "") == "GROUP":
            _collect_image_nodes(getattr(node, "node_tree", None), out, visited)


def _active_planetka_tile_images():
    earth = bpy.data.objects.get("Planetka Earth Surface")
    materials = []
    if earth is not None:
        for slot in getattr(earth, "material_slots", ()) or ():
            mat = getattr(slot, "material", None)
            if mat is not None:
                materials.append(mat)
    if not materials:
        mat = bpy.data.materials.get("Planetka Earth Material")
        if mat is not None:
            materials.append(mat)
    images = []
    seen = set()
    for material in materials:
        _collect_image_nodes(getattr(material, "node_tree", None), images, set())
    active = []
    for image in images:
        ident = id(image)
        if ident in seen:
            continue
        seen.add(ident)
        active.append(image)
    return tuple(active)


def _operator_ok(result):
    try:
        return "FINISHED" in result
    except Exception:
        return False


def main():
    started = time.time()
    report = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "forced_missing_before_save": 0,
        "missing_before_save": 0,
        "missing_after_open": 0,
        "post_open_status": {},
        "last_resolve_error": "",
        "last_manual_tile_count": 0,
    }
    temp_dirs = []
    preserve_temp = str(os.environ.get("PLANETKA_PRESERVE_TMP") or "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        base_module = enable_module(required_planetka_attr="add_earth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        state = import_submodule(base_module, "state")
        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        source_root = tempfile.mkdtemp(prefix="planetka_render_open_source_")
        temp_dirs.append(source_root)
        _make_texture_source_tree(source_root)
        prefs.texture_base_path = source_root

        work_root = tempfile.mkdtemp(prefix="planetka_render_open_work_")
        temp_dirs.append(work_root)
        render_dir = Path(work_root) / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)
        blend_path = Path(work_root) / "render_open_recovery_target.blend"

        purge_planetka_data()
        scene = bpy.context.scene
        ensure_camera(scene, name="Planetka Render Open Recovery Camera")
        ensure_standard_world(scene)
        configure_eevee(scene)
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "scene.planetka unavailable.")
        props.show_earth_preview = False

        create_earth_and_wait(state, scene)

        scene.frame_start = 1
        scene.frame_end = 1
        scene.frame_current = 1
        configure_png_output(
            scene,
            output_prefix=render_dir / "preopen",
            resolution_x=640,
            resolution_y=360,
            resolution_percentage=100,
        )
        animation_result = bpy.ops.render.render(animation=True, use_viewport=False)
        _assert(_operator_ok(animation_result), f"Animation render failed: {animation_result}")

        active_before_save = _active_planetka_tile_images()
        _assert(active_before_save, "No active Planetka tile images were found before save.")
        forced_missing = _mark_planetka_images_missing(
            Path(work_root) / "forced_missing" / "planetka_cache",
            images=active_before_save,
        )
        _assert(forced_missing > 0, "No Planetka tile images were forced to missing paths before save.")
        report["forced_missing_before_save"] = int(forced_missing)
        report["missing_before_save"] = int(_count_missing_planetka_tile_images(active_before_save))
        _assert(report["missing_before_save"] > 0, "Forced missing cache paths were not detected before reopen.")

        save_result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=False)
        _assert(_operator_ok(save_result), f"Save mainfile failed: {save_result}")
        _assert(blend_path.is_file(), f"Saved blend file missing: {blend_path}")

        open_result = bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        _assert(_operator_ok(open_result), f"Open mainfile failed: {open_result}")

        base_module = enable_module(required_planetka_attr="add_earth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        state = import_submodule(base_module, "state")
        scene = bpy.context.scene
        post_status = dict(drain_queued_resolve(state, scene, timeout_sec=120.0, sleep_sec=0.05) or {})
        report["post_open_status"] = post_status

        last_error = str(read_scene_last_resolve_error(scene) or "").strip()
        report["last_resolve_error"] = last_error
        _assert(not last_error, f"Queued recovery resolve failed after reopen: {last_error}")

        report["last_manual_tile_count"] = int(scene.get("planetka_last_manual_resolve_tile_count", 0) or 0)
        _assert(report["last_manual_tile_count"] > 0, "Queued recovery resolve did not report loaded tile count.")

        active_after_open = _active_planetka_tile_images()
        report["missing_after_open"] = int(_count_missing_planetka_tile_images(active_after_open))
        report["global_missing_after_open"] = int(_count_missing_planetka_tile_images())
        _assert(
            report["missing_after_open"] == 0,
            f"Active Planetka cache images remain missing after reopen recovery: {report['missing_after_open']}",
        )

        configure_png_output(
            scene,
            output_prefix=render_dir / "postopen",
            resolution_x=640,
            resolution_y=360,
            resolution_percentage=100,
        )
        still_result = bpy.ops.render.render(write_still=True, use_viewport=False)
        _assert(_operator_ok(still_result), f"Post-reopen still render failed: {still_result}")

        report["status"] = "ok"
        report["elapsed_sec"] = round(time.time() - started, 3)
        write_json(REPORT_PATH, report)
        _log(f"PASS: report written to {REPORT_PATH}")
        return 0
    except Exception as exc:
        traceback.print_exc()
        report["status"] = "failed"
        report["error"] = str(exc or "unknown")
        report["elapsed_sec"] = round(time.time() - started, 3)
        write_json(REPORT_PATH, report)
        _log(f"FAIL: {report['error']}")
        _log(f"Report: {REPORT_PATH}")
        return 1
    finally:
        if not preserve_temp:
            for path in temp_dirs:
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
