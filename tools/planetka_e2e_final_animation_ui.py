"""Dedicated clean-session UI final animation E2E runner.

Used by the overnight UI suite to run Final Animation cases in a fresh Blender
process, avoiding long-session contamination from earlier destructive phases.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import bpy

from planetka_e2e_common import (
    DEFAULT_PLACE_QUERIES,
    E2EError,
    analyze_png_directory,
    configure_cycles,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    enable_module,
    ensure_authenticated,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    list_pngs,
    log,
    purge_planetka_data,
    search_place,
    set_navigation,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Final Animation UI]"
SHORT_WAIT_SEC = 0.25

CASE = json.loads(str(os.environ.get("PLANETKA_E2E_FINAL_CASE_JSON") or "{}"))
OUTPUT_DIR = Path(str(os.environ.get("PLANETKA_E2E_FINAL_OUTPUT_DIR") or "")).expanduser()
REPORT_PATH = Path(str(os.environ.get("PLANETKA_E2E_FINAL_REPORT_PATH") or "")).expanduser()
TIMEOUT_SEC = float(os.environ.get("PLANETKA_E2E_FINAL_TIMEOUT_SEC") or "1800")

STATE = {
    "started": False,
    "invoke_result": [],
    "selected_place": "",
    "engine": {},
    "auth": {},
    "expected_frame_start": 1,
    "expected_frame_end": 1,
    "expected_frames": 0,
    "start_time": time.time(),
    "deadline": time.time() + TIMEOUT_SEC,
}


def _write_report(payload):
    write_json(REPORT_PATH, payload)


def _fail(message):
    payload = {
        "status": "error",
        "error": str(message),
        "traceback": traceback.format_exc(),
        "case": CASE,
        "output_dir": str(OUTPUT_DIR),
    }
    _write_report(payload)
    log(TAG, f"FAIL: {message}")
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    return None


def _configure_engine(scene, engine_name):
    if str(engine_name).upper() == "CYCLES":
        return configure_cycles(scene)
    return {"engine": configure_eevee(scene)}


def _search_and_frame(props, state_module, geonames_module, query, country_hint=None, nav=None, sunlight_preset="NOON"):
    ensure_camera(bpy.context.scene, name="Planetka Final Animation Camera")
    selected = ""
    if str(query or "").strip():
        selected = search_place(
            props,
            state_module,
            geonames_module,
            query,
            country_hint=country_hint,
        )
    if nav:
        set_navigation(props, state_module, **dict(nav))
        apply_result = bpy.ops.planetka.navigation_apply_shot()
        if "FINISHED" not in apply_result:
            raise E2EError(f"navigation_apply_shot failed during final animation setup: {apply_result}")
        clip_result = bpy.ops.planetka.auto_adjust_clipping()
        if "FINISHED" not in clip_result and "CANCELLED" not in clip_result:
            raise E2EError(f"auto_adjust_clipping failed during final animation setup: {clip_result}")
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    bpy.ops.planetka.sunlight_preset(preset=str(sunlight_preset or "NOON"))
    for _ in range(3):
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        time.sleep(0.05)
    return selected or str(query or "").strip()


def _prepare_animation_case(props, state_module, geonames_module, case):
    scene = bpy.context.scene
    frames = int(case.get("frames", 6))
    try:
        scene.use_preview_range = False
        scene.frame_start = 1
        scene.frame_end = max(1, int(frames))
        scene.frame_set(1)
        bpy.context.view_layer.update()
    except Exception:
        pass
    props.anim_frame_start = 1
    props.anim_frame_end = frames
    props.anim_motion_curve = str(case.get("motion_curve", "EASE_IN_OUT"))
    props.anim_render_preset = str(case.get("render_preset", "SPEED"))
    if case.get("preset") == "A_TO_B":
        props.anim_camera_preset = "A_TO_B"
        view_a = dict(case.get("view_a") or {})
        view_b = dict(case.get("view_b") or {})
        _search_and_frame(
            props,
            state_module,
            geonames_module,
            view_a.get("query", DEFAULT_PLACE_QUERIES[0]),
            country_hint=view_a.get("country_hint"),
            nav=view_a.get("nav"),
            sunlight_preset=view_a.get("sunlight_preset", "NOON"),
        )
        bpy.ops.planetka.animation_save_view(slot="A")
        _search_and_frame(
            props,
            state_module,
            geonames_module,
            view_b.get("query", DEFAULT_PLACE_QUERIES[1]),
            country_hint=view_b.get("country_hint"),
            nav=view_b.get("nav"),
            sunlight_preset=view_b.get("sunlight_preset", "SUNSET"),
        )
        bpy.ops.planetka.animation_save_view(slot="B")
        return ""

    props.anim_camera_preset = str(case.get("preset", "ORBIT"))
    selected = _search_and_frame(
        props,
        state_module,
        geonames_module,
        case.get("query", DEFAULT_PLACE_QUERIES[0]),
        country_hint=case.get("country_hint"),
        nav=case.get("nav"),
        sunlight_preset=case.get("sunlight_preset", "MID_AFTERNOON"),
    )
    if props.anim_camera_preset == "ORBIT":
        props.anim_orbit_degrees = float(case.get("orbit_degrees", 45.0))
        props.anim_circle_direction = str(case.get("circle_direction", "CLOCKWISE"))
    if props.anim_camera_preset == "ZOOM":
        props.anim_end_altitude_km = float(case.get("end_altitude_km", 40.0))
        props.anim_zoom_rotate_degrees = float(case.get("zoom_rotate_degrees", 0.0))
    return selected


def _tick():
    try:
        if not STATE["started"]:
            if not REPORT_PATH:
                raise E2EError("PLANETKA_E2E_FINAL_REPORT_PATH is missing.")
            if not OUTPUT_DIR:
                raise E2EError("PLANETKA_E2E_FINAL_OUTPUT_DIR is missing.")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            base_module = enable_module(required_planetka_attr="add_earth")
            auth = import_submodule(base_module, "auth")
            extension_prefs = import_submodule(base_module, "extension_prefs")
            geonames = import_submodule(base_module, "geonames_db")
            state_module = import_submodule(base_module, "state")
            wait_for_geonames_ready(geonames)

            prefs = extension_prefs.get_prefs()
            auth_payload_path = str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip()
            STATE["auth"] = ensure_authenticated(auth, prefs, payload_path=auth_payload_path)

            scene = bpy.context.scene
            props = getattr(scene, "planetka", None)
            if props is None:
                raise E2EError("scene.planetka is unavailable.")

            purge_planetka_data()
            if hasattr(bpy.ops.planetka, "remove_default_scene") and bpy.ops.planetka.remove_default_scene.poll():
                bpy.ops.planetka.remove_default_scene()
            ensure_camera(scene, name="Planetka Final Animation Camera")
            ensure_standard_world(scene)
            bpy.ops.planetka.set_background_black()
            prefs.texture_base_path = "planetka-remote"
            create_earth_and_wait(state_module, scene)

            props.show_earth_preview = False
            props.auto_resolve = True
            props.debug_logging = False
            props.texture_quality_mode = "PREVIEW"
            props.anim_render_persistent_data = bool(CASE.get("render_persistent_data", True))

            STATE["engine"] = _configure_engine(scene, CASE.get("engine", "EEVEE"))
            STATE["selected_place"] = _prepare_animation_case(props, state_module, geonames, CASE)

            configure_png_output(
                scene,
                output_prefix=OUTPUT_DIR / "frame_",
                resolution_x=960,
                resolution_y=540,
                resolution_percentage=100,
            )
            result = bpy.ops.planetka.animation_render('INVOKE_DEFAULT', confirmed=True)
            if "RUNNING_MODAL" not in result and "FINISHED" not in result:
                raise E2EError(f"Final Animation Render did not start: {result}")

            STATE["invoke_result"] = list(result)
            STATE["expected_frame_start"] = int(getattr(scene, "frame_start", 1) or 1)
            STATE["expected_frame_end"] = int(getattr(scene, "frame_end", STATE["expected_frame_start"]) or STATE["expected_frame_start"])
            STATE["expected_frames"] = max(0, int(STATE["expected_frame_end"]) - int(STATE["expected_frame_start"]) + 1)
            STATE["started"] = True
            return 0.5

        expected_frames = int(STATE.get("expected_frames", 0) or 0)
        frame_count = len(list_pngs(OUTPUT_DIR)) if OUTPUT_DIR.exists() else 0
        running = False
        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if callable(is_job_running):
                running = bool(is_job_running("RENDER"))
        except Exception:
            running = False

        if frame_count >= expected_frames > 0 and not running:
            analysis = analyze_png_directory(OUTPUT_DIR, max_samples=min(6, expected_frames))
            payload = {
                "status": "ok",
                "case": CASE,
                "selected_place": STATE["selected_place"],
                "engine": STATE["engine"],
                "auth": STATE["auth"],
                "output_dir": str(OUTPUT_DIR),
                "invoke_result": STATE["invoke_result"],
                "expected_frame_start": int(STATE["expected_frame_start"]),
                "expected_frame_end": int(STATE["expected_frame_end"]),
                "expected_frames": int(STATE["expected_frames"]),
                "render": analysis,
            }
            _write_report(payload)
            log(TAG, f"PASS: report={REPORT_PATH}")
            bpy.ops.wm.quit_blender()
            return None

        if time.time() > STATE["deadline"]:
            raise E2EError(
                f"Final Animation Render timed out ({frame_count}/{expected_frames} frames)."
            )
        return 0.5
    except Exception as exc:
        return _fail(exc)


bpy.app.timers.register(_tick, first_interval=0.5)
