#!/usr/bin/env python3
"""Hermetic Final Animation gate (background-safe).

Purpose:
- directly validate Final Animation segment flow (plan -> resolve -> render)
- run without network using bundled fallback textures
- cover EEVEE and CYCLES when available in the current Blender build
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
            "bl_ext.user_default.planetka",
            "bl_ext.user_default.Planetka",
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
    _fail(f"Could not enable Planetka module. Tried: {', '.join(candidates)}")


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.planetka.{submodule_name}",
            f"bl_ext.user_default.Planetka.{submodule_name}",
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
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
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
        pending_count = int(last_status.get("pending_count", 0) or 0)
        code = str(last_status.get("code", "") or "")
        if not running and pending_count <= 0 and code in {"", "IDLE"}:
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
    try:
        prop = render.bl_rna.properties["engine"]
        return {str(item.identifier) for item in prop.enum_items}
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return set()
    except (RuntimeError, TypeError, ValueError, AttributeError, KeyError):
        return set()


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


def _make_render_operator_proxy(animation_tools):
    cls = animation_tools.PLANETKA_OT_AnimationRender
    op = type("FinalGateRenderProxy", (), {})()
    for name in (
        "_is_render_job_running",
        "_read_render_heartbeat",
        "_get_selected_texture_quality_mode",
        "_resolve_segment_frame",
        "_is_eevee_render_engine",
        "_enforce_eevee_bump_only_for_segment",
        "_enforce_cycles_simple_subdivision_for_segment",
        "_launch_segment_render",
    ):
        fn = getattr(cls, name, None)
        if callable(fn):
            setattr(op, name, fn.__get__(op, op.__class__))
    setattr(op, "report", lambda *_args, **_kwargs: None)
    return op


def _run_final_animation_case(scene, props, state_module, animation_tools, engine_id, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.png"):
        try:
            old_file.unlink()
        except OSError:
            pass

    _configure_engine(scene, engine_id)
    props.auto_resolve = False
    props.show_earth_preview = False
    props.texture_quality_mode = "FULL"
    props.anim_camera_preset = "ZOOM"
    props.anim_frame_start = 1
    props.anim_frame_end = 3
    props.anim_end_altitude_km = 80.0
    props.anim_zoom_rotate_degrees = 0.0
    props.anim_motion_curve = "LINEAR"
    props.nav_altitude_km = 30.0
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

    planner = animation_tools._plan_animation_segments(
        scene,
        frame_start,
        frame_end,
        frame_step=1,
        texture_quality_mode_override="FULL",
    )
    segments = list(getattr(planner, "segments", ()) or ())
    _assert(segments, f"No Final Animation segments were produced for engine {engine_id}.")

    op = _make_render_operator_proxy(animation_tools)
    op._scene = scene
    op._props = props
    op._segments = list(segments)
    op._segment_index = 0
    op._active_segment = None
    op._state = "IDLE"
    op._render_seen_active = False
    op._render_launch_time = 0.0
    op._render_launch_wall_time = 0.0
    op._segment_failures = []

    for idx, segment in enumerate(segments):
        segment = dict(segment or {})
        seg_start = int(segment.get("start", frame_start))
        seg_end = int(segment.get("end", seg_start))
        op._segment_index = int(idx)
        op._active_segment = segment

        # Mirror simplified modal loop: force-terminate deferred/queued resolve before each segment resolve.
        try:
            state_module.stop_auto_resolve_download_pipeline()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

        ok, message = op._resolve_segment_frame(seg_start, tiles_override=segment.get("tiles", ()))
        _assert(ok, f"Resolve failed for segment {idx + 1} ({seg_start:04d}-{seg_end:04d}): {message}")
        op._enforce_eevee_bump_only_for_segment()
        op._enforce_cycles_simple_subdivision_for_segment()
        ok, message = op._launch_segment_render(segment, invoke_ui=False)
        _assert(ok, f"Render launch failed for segment {idx + 1} ({seg_start:04d}-{seg_end:04d}): {message}")

        for frame in range(seg_start, seg_end + 1):
            frame_path = str(bpy.path.abspath(scene.render.frame_path(frame=int(frame))) or "").strip()
            _assert(frame_path and os.path.isfile(frame_path), f"Missing rendered frame {frame:04d} for {engine_id}.")

    total_frames = int(frame_end - frame_start + 1)
    rendered_frames = sorted(output_dir.glob("*.png"))
    _assert(len(rendered_frames) >= total_frames, f"Expected >= {total_frames} frames for {engine_id}, got {len(rendered_frames)}.")
    _log(f"{engine_id}: PASS ({len(segments)} segments, {len(rendered_frames)} frame files)")


def main():
    temp_dirs = []
    try:
        module_name = _enable_module()
        extension_prefs = _import_submodule(module_name, "extension_prefs")
        state = _import_submodule(module_name, "state")
        animation_tools = _import_submodule(module_name, "animation_tools")

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

        _run_final_animation_case(
            scene,
            props,
            state,
            animation_tools,
            eevee_engine,
            os.path.join(output_root, "eevee"),
        )

        if "CYCLES" in engines:
            _run_final_animation_case(
                scene,
                props,
                state,
                animation_tools,
                "CYCLES",
                os.path.join(output_root, "cycles"),
            )
        else:
            _log("CYCLES not available in this Blender build; skipping Cycles Final Animation gate.")

        _log("PASS: Final Animation gate passed.")
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
