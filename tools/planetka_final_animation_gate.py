#!/usr/bin/env python3
"""Hermetic Final Animation gate for Blender Required Gate.

Runs a short Final Animation flow for EEVEE and Cycles in background mode using
local fallback textures only.
"""

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
    configure_cycles,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    enable_module,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    list_pngs,
    purge_planetka_data,
)


TAG = "[Planetka Final Animation Gate]"
FALLBACK_DIR = Path(_REPO_ROOT) / "Resources" / "Fallback Images"


def _log(message):
    print(f"{TAG} {message}", flush=True)


def _assert(condition, message):
    if not condition:
        raise E2EError(str(message))


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
        _assert(source.is_file(), f"Missing fallback texture sample: {source}")
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, folder / f"{prefix}x000_y000_z360_d360.exr")
        shutil.copyfile(source, folder / f"{prefix}x180_y000_z180_d180.exr")
    (base / "PO").mkdir(parents=True, exist_ok=True)


def _wait_segment_render_completion(op, segment, timeout_sec=240.0):
    started = time.monotonic()
    seen_active = False
    while True:
        running = bool(op._is_render_job_running())
        if running:
            seen_active = True
            op._render_seen_active = True
        else:
            elapsed = float(time.monotonic() - float(op._render_launch_time or started))
            if (not seen_active) and elapsed < 0.75:
                time.sleep(0.05)
                continue
            break
        if (time.monotonic() - started) >= float(max(5.0, timeout_sec)):
            raise E2EError("Render segment did not finish before timeout.")
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        time.sleep(0.1)

    if not bool(op._segment_outputs_complete(segment, min_mtime=op._render_launch_wall_time)):
        raise E2EError("Render segment completed without expected output frames.")


def _run_short_final_animation_case(animation_tools, scene, props, engine_label, output_dir):
    _assert(scene is not None and props is not None, "Scene context unavailable.")
    ensure_camera(scene, name=f"Planetka {engine_label} Camera")
    ensure_standard_world(scene)
    scene.use_preview_range = False
    scene.frame_start = 1
    scene.frame_end = 3
    scene.frame_set(1)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    props.auto_resolve = False
    props.texture_quality_mode = "PREVIEW"
    props.anim_camera_preset = "ZOOM"
    props.anim_motion_curve = "LINEAR"
    props.anim_frame_start = 1
    props.anim_frame_end = 3
    props.anim_end_altitude_km = 2500.0
    props.anim_zoom_rotate_degrees = 0.0
    props.nav_longitude_deg = 0.0
    props.nav_latitude_deg = 0.0
    props.nav_altitude_km = 6000.0
    props.nav_azimuth_deg = 0.0
    props.nav_tilt_deg = 0.0
    props.nav_roll_deg = 0.0
    props.nav_focal_length_mm = 50.0

    start_frame, end_frame = animation_tools.apply_cinematic_preview(scene, props)
    segment_plan = animation_tools._plan_animation_segments(
        scene,
        int(start_frame),
        int(end_frame),
        frame_step=1,
        texture_quality_mode_override="PREVIEW",
    )
    segments = list(segment_plan.segments or ())
    _assert(bool(segments), f"{engine_label}: no animation segments generated.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_png_output(
        scene,
        output_prefix=output_dir / f"{engine_label.lower()}_",
        resolution_x=320,
        resolution_y=180,
        resolution_percentage=100,
    )

    op = animation_tools.PLANETKA_OT_AnimationRenderHeadless()
    op._scene = scene
    op._props = props
    op._segments = list(segments)

    for index, segment in enumerate(segments, start=1):
        seg_start = int(segment.get("start", 1))
        seg_end = int(segment.get("end", seg_start))
        _log(f"{engine_label}: segment {index}/{len(segments)} resolve {seg_start:04d}-{seg_end:04d}")
        ok, message = op._resolve_segment_frame(seg_start, tiles_override=segment.get("tiles", ()))
        _assert(bool(ok), f"{engine_label}: segment resolve failed: {message}")
        op._enforce_eevee_bump_only_for_segment()
        op._enforce_cycles_simple_subdivision_for_segment()
        op._render_seen_active = False
        op._render_launch_time = time.monotonic()
        ok, message = op._launch_segment_render(segment, invoke_ui=False)
        _assert(bool(ok), f"{engine_label}: segment render launch failed: {message}")
        _wait_segment_render_completion(op, segment, timeout_sec=240.0)

    expected_frames = max(0, int(end_frame) - int(start_frame) + 1)
    rendered = list_pngs(output_dir)
    _assert(
        int(len(rendered)) >= int(expected_frames),
        (
            f"{engine_label}: expected at least {expected_frames} rendered frame(s), "
            f"got {len(rendered)}."
        ),
    )
    _log(f"{engine_label}: rendered {len(rendered)} frame(s) for {expected_frames} expected frame(s).")


def main():
    temp_dirs = []
    started = time.time()
    try:
        base_module = enable_module(required_planetka_attr="add_earth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        state_module = import_submodule(base_module, "state")
        animation_tools = import_submodule(base_module, "animation_tools")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        source_root = tempfile.mkdtemp(prefix="planetka_final_anim_source_")
        output_root = tempfile.mkdtemp(prefix="planetka_final_anim_renders_")
        temp_dirs.extend([source_root, output_root])
        _make_texture_source_tree(source_root)
        prefs.texture_base_path = str(source_root)

        purge_planetka_data()
        scene = bpy.context.scene
        ensure_camera(scene, name="Planetka Final Animation Gate Camera")
        ensure_standard_world(scene)
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "scene.planetka is unavailable.")

        create_earth_and_wait(state_module, scene)

        configure_eevee(scene)
        _run_short_final_animation_case(
            animation_tools,
            scene,
            props,
            "EEVEE",
            Path(output_root) / "eevee",
        )

        configure_cycles(scene)
        _run_short_final_animation_case(
            animation_tools,
            scene,
            props,
            "CYCLES",
            Path(output_root) / "cycles",
        )

        elapsed = time.time() - started
        _log(f"PASS in {elapsed:.2f}s")
        return 0
    except Exception as exc:
        _log(f"FAIL: {exc}")
        traceback.print_exc()
        return 1
    finally:
        for path in temp_dirs:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
