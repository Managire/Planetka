#!/usr/bin/env python3
"""UI-mode Create Earth queued-resolve regression test.

Purpose:
- exercise the real default Create Earth path
- do not call explicit Resolve operator after Create Earth
- verify queued resolve settles back to IDLE and writes a non-zero tile count

Run:
  /Applications/Blender5.0.app/Contents/MacOS/Blender --python \
    tools/planetka_create_earth_ui_queued_resolve_test.py
"""

from __future__ import annotations

import importlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback

import addon_utils
import bpy

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

TAG = "[Planetka UI Queued Resolve Test]"
REPORT_PATH = os.path.join(tempfile.gettempdir(), "planetka_ui_queued_resolve_test_report.json")
STATE = {
    "started": False,
    "start_time": None,
    "error": "",
    "statuses": [],
    "base_module_name": "",
    "temp_source": "",
}
TIMEOUT_SEC = 12.0


def _log(message):
    print(f"{TAG} {message}")


def _write_report(ok, extra=None):
    payload = {
        "ok": bool(ok),
        "error": str(STATE.get("error", "") or ""),
        "statuses": list(STATE.get("statuses", []) or []),
        "elapsed_sec": round(time.time() - float(STATE.get("start_time") or time.time()), 3) if STATE.get("started") else 0.0,
    }
    if isinstance(extra, dict):
        payload.update(extra)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    _log(f"Report: {REPORT_PATH}")


def _fail(message, extra=None):
    STATE["error"] = str(message)
    _log(f"FAIL: {message}")
    _write_report(False, extra=extra)
    _cleanup_temp_source()
    bpy.ops.wm.quit_blender()
    return None


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _addon_root():
    return _REPO_ROOT


def _enable_module():
    candidates = _unique([
        os.environ.get("PLANETKA_MODULE"),
        "bl_ext.user_default.planetka",
        "bl_ext.user_default.Planetka",
        "Planetka",
        "planetka",
    ])
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            loaded, _loaded_default = addon_utils.check(mod)
            if not bool(loaded):
                continue
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue

    addon_root = _addon_root()
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    module = importlib.import_module(package_name)
    if hasattr(module, "register"):
        try:
            module.unregister()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        module.register()
    return package_name


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique([
        f"{base_module_name}.{submodule_name}" if base_module_name else None,
        f"bl_ext.user_default.planetka.{submodule_name}",
        f"bl_ext.user_default.Planetka.{submodule_name}",
        f"Planetka.{submodule_name}",
        f"planetka.{submodule_name}",
    ])
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    raise RuntimeError(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _make_texture_source_tree(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    fallback = os.path.join(_addon_root(), "Resources", "Fallback Images")
    rules = (
        ("S2", "S2_", ".exr", "ocean_pixel_final_20.exr"),
        ("EL", "EL_", ".exr", "black_pixel_20.exr"),
        ("WT", "WT_", ".exr", "blue_pixel_20.exr"),
    )
    for folder_name, prefix, ext, source_name in rules:
        source = os.path.join(fallback, source_name)
        if not os.path.isfile(source):
            raise RuntimeError(f"Missing bundled fallback texture sample: {source}")
        folder = os.path.join(base_dir, folder_name)
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(source, os.path.join(folder, f"{prefix}x000_y000_z360_d360{ext}"))
        shutil.copyfile(source, os.path.join(folder, f"{prefix}x180_y000_z180_d180{ext}"))
    os.makedirs(os.path.join(base_dir, "PO"), exist_ok=True)


def _cleanup_temp_source():
    path = str(STATE.get("temp_source") or "").strip()
    if not path:
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    STATE["temp_source"] = ""


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current
    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj
    camera_data = bpy.data.cameras.new("Planetka UI Queue Camera")
    camera_obj = bpy.data.objects.new("Planetka UI Queue Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _purge_existing_planetka_data():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for coll in list(bpy.data.collections):
        if not coll.name.startswith("Planetka"):
            continue
        for scene in bpy.data.scenes:
            try:
                if coll in scene.collection.children:
                    scene.collection.children.unlink(coll)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        try:
            bpy.data.collections.remove(coll)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

    for material in list(bpy.data.materials):
        if material.name.startswith("Planetka"):
            try:
                bpy.data.materials.remove(material, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for node_group in list(bpy.data.node_groups):
        if node_group.name.startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _start_test():
    try:
        base_module_name = _enable_module()
        STATE["base_module_name"] = base_module_name
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        state = _import_submodule(base_module_name, "state")

        prefs = extension_prefs.get_prefs()
        if prefs is None:
            return _fail("Planetka preferences unavailable")

        temp_source = tempfile.mkdtemp(prefix="planetka_ui_queue_")
        STATE["temp_source"] = temp_source
        _make_texture_source_tree(temp_source)
        prefs.texture_base_path = temp_source

        scene = bpy.context.scene
        _ensure_active_camera(scene)
        _purge_existing_planetka_data()
        props = scene.planetka
        props.auto_resolve = True
        props.show_earth_preview = False

        result = bpy.ops.planetka.add_earth()
        if "FINISHED" not in result:
            return _fail(f"Create Earth failed with result: {result}")

        STATE["started"] = True
        STATE["start_time"] = time.time()
        _log("Create Earth returned FINISHED; waiting for queued resolve to finalize.")
        return 0.25
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        traceback.print_exc()
        return _fail(str(exc))
    except Exception as exc:
        traceback.print_exc()
        return _fail(str(exc))


def _poll_test():
    try:
        state = _import_submodule(STATE.get("base_module_name"), "state")
        scene = bpy.context.scene
        status = dict(state.get_resolve_runtime_status(scene) or {})
        status["elapsed_sec"] = round(time.time() - float(STATE.get("start_time") or time.time()), 3)
        status["last_tile_count"] = int(scene.get("planetka_last_manual_resolve_tile_count", 0) or 0)
        status["surface_exists"] = bpy.data.objects.get("Planetka Earth Surface") is not None
        STATE["statuses"].append(status)

        if (
            str(status.get("code", "") or "IDLE") == "IDLE"
            and not bool(status.get("running", False))
            and int(status.get("pending_count", 0) or 0) <= 0
            and int(status.get("last_tile_count", 0) or 0) > 0
            and bool(status.get("surface_exists", False))
        ):
            _log("PASS: queued Create Earth resolve completed and returned to IDLE.")
            _write_report(True)
            _cleanup_temp_source()
            bpy.ops.wm.quit_blender()
            return None

        elapsed = time.time() - float(STATE.get("start_time") or time.time())
        if elapsed > float(TIMEOUT_SEC):
            return _fail(
                f"Queued Create Earth resolve timed out: {status}",
                extra={
                    "last_status": status,
                },
            )
        return 0.25
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        traceback.print_exc()
        return _fail(str(exc))
    except Exception as exc:
        traceback.print_exc()
        return _fail(str(exc))


def _timer_main():
    if not STATE["started"]:
        return _start_test()
    return _poll_test()


bpy.app.timers.register(_timer_main, first_interval=0.5)
