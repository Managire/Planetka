#!/usr/bin/env python3
"""Hermetic Final Animation gate (UI render path).

Purpose:
- validate the same Final Animation operator/render-window path users run
- run without network using bundled fallback textures
- require both EEVEE and CYCLES in the current Blender build
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS

import addon_utils
import bpy


TAG = "[Planetka Final Animation Gate]"
SURFACE_OBJECT_NAME = "Planetka Earth Surface"
POLL_INTERVAL_SEC = 0.5
CASE_TIMEOUT_SEC = 240.0
STATE = {
    "started": False,
    "scene": None,
    "props": None,
    "state_module": None,
    "animation_tools": None,
    "cases": [],
    "case_index": -1,
    "current": None,
    "temp_dirs": [],
}

_FIXTURE_TILE_IDS = (
    "x000_y000_z180_d720",
    "x180_y000_z180_d720",
    "x000_y000_z180_d360",
    "x180_y000_z180_d360",
    "x000_y000_z180_d180",
    "x180_y000_z180_d180",
)


def _log(message):
    print(f"{TAG} {message}", flush=True)


def _fail(message):
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _assert(condition, message):
    if not condition:
        _fail(message)


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
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _enable_module():
    candidates = _unique(
        [
            os.environ.get("PLANETKA_MODULE"),
            "bl_ext.user_default.Planetka",
            "bl_ext.user_default.planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            loaded, _loaded_default = addon_utils.check(mod)
            if not bool(loaded):
                continue
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue

    parent_dir = os.path.dirname(_REPO_ROOT)
    package_name = os.path.basename(_REPO_ROOT)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
        module = importlib.import_module(package_name)
        if hasattr(module, "register"):
            try:
                module.unregister()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            module.register()
        if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
            _log(f"Enabled addon package from package path: {package_name}")
            return package_name
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    _fail(f"Could not enable Planetka module. Tried: {', '.join(candidates)}")


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.Planetka.{submodule_name}",
            f"bl_ext.user_default.planetka.{submodule_name}",
            f"Planetka.{submodule_name}",
            f"planetka.{submodule_name}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    _fail(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")



def _purge_existing_planetka_data():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for coll in list(bpy.data.collections):
        if coll.name.startswith("Planetka"):
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


def _make_texture_source_tree(base_dir):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    fallback = Path(_addon_root()) / "Resources" / "Fallback Images"
    rules = (
        ("S2", "S2_", ".exr", "ocean_pixel_final_20.exr"),
        ("EL", "EL_", ".exr", "black_pixel_20.exr"),
        ("WT", "WT_", ".exr", "blue_pixel_20.exr"),
    )
    for folder_name, prefix, ext, source_name in rules:
        source = fallback / source_name
        _assert(source.is_file(), f"Missing bundled fallback texture sample: {source}")
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        for tile_id in _FIXTURE_TILE_IDS:
            shutil.copyfile(source, folder / f"{prefix}{tile_id}{ext}")
        shutil.copyfile(source, folder / f"{prefix}x000_y000_z360_d360{ext}")
        shutil.copyfile(source, folder / f"{prefix}x180_y000_z180_d180{ext}")
    (base / "PO").mkdir(parents=True, exist_ok=True)


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current
    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj
    camera_data = bpy.data.cameras.new("Planetka Final Gate Camera")
    camera_obj = bpy.data.objects.new("Planetka Final Gate Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _drain_queued_resolve(state_module, scene, timeout_sec=12.0):
    runtime_status_fn = getattr(state_module, "get_resolve_runtime_status", None)
    pump_fn = getattr(state_module, "_resolve_pump_timer", None)
    stop_fn = getattr(state_module, "stop_resolve", None)
    start = time.monotonic()
    last_status = {}
    while True:
        if callable(pump_fn):
            try:
                pump_fn()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                _fail("Queued resolve pump raised an unexpected exception.")
        if callable(runtime_status_fn):
            try:
                last_status = dict(runtime_status_fn(scene) or {})
            except TOOL_RECOVERABLE_EXCEPTIONS:
                last_status = {}
        running = bool(last_status.get("running", False))
        active_count = int(last_status.get("active_count", 0) or 0)
        code = str(last_status.get("code", "") or "")
        if not running and active_count <= 0 and code in {"", "IDLE"}:
            return
        if time.monotonic() - start > float(timeout_sec):
            if callable(stop_fn):
                try:
                    stop_fn()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
            _fail(f"Queued resolve did not complete in time: {last_status}")
        time.sleep(0.05)


def _available_render_engines(scene):
    render = getattr(scene, "render", None)
    if render is None:
        return set()
    current_engine = str(getattr(render, "engine", "") or "")
    engines = set()
    try:
        prop = render.bl_rna.properties["engine"]
        engines.update(str(item.identifier) for item in prop.enum_items)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    except (RuntimeError, TypeError, ValueError, AttributeError, KeyError):
        pass
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            render.engine = candidate
            if str(getattr(render, "engine", "") or "") == candidate:
                engines.add(candidate)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    try:
        if current_engine:
            render.engine = current_engine
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return set(engines)


def _configure_engine(scene, engine_id):
    scene.render.engine = str(engine_id)
    scene.render.resolution_x = 640
    scene.render.resolution_y = 360
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    if str(engine_id).upper() == "CYCLES":
        cycles = getattr(scene, "cycles", None)
        if cycles is not None:
            try:
                cycles.device = "CPU"
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            try:
                cycles.samples = 1
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            try:
                cycles.use_adaptive_sampling = True
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            try:
                cycles.adaptive_threshold = 0.25
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
    else:
        eevee = getattr(scene, "eevee", None)
        if eevee is not None and hasattr(eevee, "taa_render_samples"):
            try:
                eevee.taa_render_samples = 1
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass


def _timer_fail(message):
    _log(f"FAIL: {message}")
    if sys.exc_info()[0] is not None:
        traceback.print_exc()
    _cleanup_temp_dirs()
    os._exit(1)


def _cleanup_temp_dirs():
    for path in list(STATE.get("temp_dirs", ()) or ()):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
    STATE["temp_dirs"] = []


def _render_job_running():
    try:
        is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
        if callable(is_job_running):
            return bool(is_job_running("RENDER"))
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    return False


def _final_animation_active(state_module):
    fn = getattr(state_module, "is_final_animation_render_active", None)
    if not callable(fn):
        return False
    try:
        return bool(fn())
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _rendered_frames(output_dir):
    return sorted(Path(output_dir).glob("*.png"))


def _start_final_animation_case(scene, props, animation_tools, engine_id, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.png"):
        try:
            old_file.unlink()
        except OSError:
            pass

    _configure_engine(scene, engine_id)
    props.show_earth_preview = False
    props.texture_quality_mode = "FULL"
    props.anim_camera_preset = "ZOOM"
    props.anim_frame_start = 1
    props.anim_frame_end = 3
    props.anim_end_altitude_km = 25000.0
    props.anim_zoom_rotate_degrees = 0.0
    props.anim_motion_curve = "LINEAR"
    props.nav_altitude_km = 30000.0
    props.nav_tilt_deg = 65.0
    apply_result = bpy.ops.planetka.navigation_apply_shot()
    _assert("FINISHED" in apply_result, f"navigation_apply_shot failed before {engine_id} render: {apply_result}")

    frame_start, frame_end = animation_tools.apply_cinematic_preview(scene, props)
    frame_start = int(frame_start)
    frame_end = int(frame_end)
    scene.use_preview_range = False
    scene.frame_start = int(frame_start)
    scene.frame_end = int(frame_end)
    scene.frame_set(int(frame_start))
    scene.render.filepath = str(output_dir / f"{str(engine_id).lower()}_")

    result = bpy.ops.planetka.animation_render('INVOKE_DEFAULT', confirmed=True)
    _assert(
        "RUNNING_MODAL" in result or "FINISHED" in result,
        f"Final Animation Render did not start for {engine_id}: {result}",
    )

    expected_frames = int(max(0, frame_end - frame_start + 1))
    _log(f"{engine_id}: started UI Final Animation Render ({expected_frames} frame files expected)")
    return {
        "engine_id": str(engine_id),
        "output_dir": output_dir,
        "expected_frames": expected_frames,
        "started_at": time.monotonic(),
        "seen_active": False,
        "invoke_result": list(result),
    }


def _start_next_case():
    try:
        previous_index = int(STATE.get("case_index", -1))
    except (TypeError, ValueError):
        previous_index = -1
    STATE["case_index"] = previous_index + 1
    index = int(STATE["case_index"])
    cases = list(STATE.get("cases", ()) or ())
    if index >= len(cases):
        _log("PASS: Final Animation UI gate passed.")
        _cleanup_temp_dirs()
        bpy.ops.wm.quit_blender()
        return None

    case = dict(cases[index] or {})
    STATE["current"] = _start_final_animation_case(
        STATE["scene"],
        STATE["props"],
        STATE["animation_tools"],
        case["engine_id"],
        case["output_dir"],
    )
    return float(POLL_INTERVAL_SEC)


def _poll_current_case():
    current = dict(STATE.get("current") or {})
    if not current:
        return _start_next_case()

    state_module = STATE["state_module"]
    output_dir = Path(current["output_dir"])
    expected_frames = int(current.get("expected_frames", 0) or 0)
    frame_count = len(_rendered_frames(output_dir))
    active = _final_animation_active(state_module)
    running = _render_job_running()
    if active or running:
        current["seen_active"] = True
        STATE["current"] = current
        return float(POLL_INTERVAL_SEC)

    if frame_count >= expected_frames > 0:
        _log(f"{current['engine_id']}: PASS ({frame_count} frame files)")
        STATE["current"] = None
        return _start_next_case()

    started_at = float(current.get("started_at", time.monotonic()) or time.monotonic())
    if (not bool(current.get("seen_active"))) and (time.monotonic() - started_at) < 10.0:
        return float(POLL_INTERVAL_SEC)

    if (time.monotonic() - started_at) > float(CASE_TIMEOUT_SEC):
        _timer_fail(
            f"{current['engine_id']}: Final Animation UI render timed out "
            f"({frame_count}/{expected_frames} frame files)."
        )
    else:
        _timer_fail(
            f"{current['engine_id']}: Final Animation UI render stopped before expected output "
            f"({frame_count}/{expected_frames} frame files)."
        )
    return None


def _tick():
    try:
        if not bool(STATE.get("started", False)):
            STATE["started"] = True
            return float(POLL_INTERVAL_SEC)
        return _poll_current_case()
    except SystemExit as exc:
        _cleanup_temp_dirs()
        code = getattr(exc, "code", 1)
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = 1
        os._exit(code if code != 0 else 1)
    except Exception as exc:
        _timer_fail(f"unexpected exception: {exc}")
    return None


def main():
    if bool(getattr(bpy.app, "background", False)):
        _fail("Final Animation gate must run in Blender UI mode, not --background.")

    temp_dirs = []
    try:
        module_name = _enable_module()
        extension_prefs = _import_submodule(module_name, "extension_prefs")
        state = _import_submodule(module_name, "state")
        animation_tools = _import_submodule(module_name, "animation_tools")
        r2_source = _import_submodule(module_name, "r2_source")

        _purge_existing_planetka_data()
        scene = bpy.context.scene
        _ensure_active_camera(scene)
        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        source_root = tempfile.mkdtemp(prefix="planetka_final_gate_source_")
        temp_dirs.append(source_root)
        _make_texture_source_tree(source_root)
        prefs.texture_base_path = source_root

        output_root = tempfile.mkdtemp(prefix="planetka_final_gate_output_")
        temp_dirs.append(output_root)

        result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in result, f"Create Earth failed with result: {result}")
        _drain_queued_resolve(state, scene)

        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing after Create Earth.")
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "Planetka scene properties are missing.")

        engines = _available_render_engines(scene)
        eevee_engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
        _assert(eevee_engine in engines, f"Eevee engine is not available in this Blender build: {sorted(engines)}")
        _assert("CYCLES" in engines, f"Cycles engine is not available in this Blender build: {sorted(engines)}")

        STATE["scene"] = scene
        STATE["props"] = props
        STATE["state_module"] = state
        STATE["animation_tools"] = animation_tools
        STATE["temp_dirs"] = list(temp_dirs)
        STATE["cases"] = [
            {"engine_id": eevee_engine, "output_dir": os.path.join(output_root, "eevee")},
            {"engine_id": "CYCLES", "output_dir": os.path.join(output_root, "cycles")},
        ]
        bpy.app.timers.register(_tick, first_interval=0.1, persistent=False)
        _log("Final Animation UI gate scheduled.")
        temp_dirs = []
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        _log(f"FAIL: unexpected exception: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
    except Exception as exc:
        _log(f"FAIL: unexpected exception: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        for path in temp_dirs:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


if __name__ == "__main__":
    main()
