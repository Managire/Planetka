"""Short Planetka end-to-end Blender test.

Recommended usage:
  Reuse current authenticated Blender profile:
    /Applications/Blender5.0.app/Contents/MacOS/Blender --background \
      --python tools/planetka_e2e_short.py

  Clean session with API key bootstrap:
    PLANETKA_AUTH_DEVICE_ID=1de81a60-831d-4aac-9e66-e86af91a900b \
    PLANETKA_API_KEY_PATH=/absolute/path/to/api_key.json \
    /Applications/Blender5.0.app/Contents/MacOS/Blender --factory-startup --background \
      --python tools/planetka_e2e_short.py

What it covers:
- enable addon
- verify authenticated cloud account
- Create Earth
- Place Search
- Navigation + Sunlight
- Preview/Balanced/Full resolves
- Quick Preview animation prep
- short 4-frame EEVEE render to /Volumes/SSDA/Renders
- JSON report with image-analysis checks
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

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS

import bpy

from planetka_e2e_common import (
    COUNTRY_HINT_BY_CITY,
    E2EError,
    analyze_png_directory,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    enable_module,
    ensure_authenticated,
    ensure_camera,
    import_submodule,
    log,
    output_session,
    purge_planetka_data,
    render_animation,
    resolve_textures,
    search_place,
    set_navigation,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Short E2E]"
ANIMATION_FRAME_COUNT = 4
ANIMATION_QUERY = "Singapore"


def _fail(report_path, payload, message):
    payload["status"] = "error"
    payload["error"] = str(message)
    write_json(report_path, payload)
    log(TAG, f"FAIL: {message}")
    raise SystemExit(1)


def main():
    started = time.time()
    session_dir = output_session("planetka_e2e_short")
    frames_dir = session_dir / "quick_preview_eevee_frames"
    report_path = session_dir / "planetka_e2e_short_report.json"
    payload = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_dir": str(session_dir),
        "frames_dir": str(frames_dir),
        "coverage": {},
        "renders": {},
        "notes": [],
    }

    try:
        base_module = enable_module(required_planetka_attr="add_earth")
        auth = import_submodule(base_module, "auth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        geonames = import_submodule(base_module, "geonames_db")
        state = import_submodule(base_module, "state")

        prefs = extension_prefs.get_prefs()
        auth_info = ensure_authenticated(
            auth,
            prefs,
            payload_path=str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip(),
            api_key=str(os.environ.get("PLANETKA_API_KEY") or "").strip(),
            api_key_path=str(os.environ.get("PLANETKA_API_KEY_PATH") or "").strip(),
        )
        wait_for_geonames_ready(geonames)

        scene = bpy.context.scene
        purge_planetka_data()
        ensure_camera(scene, name="Planetka Short E2E Camera")
        prefs.texture_base_path = "planetka-remote"

        payload["coverage"]["account"] = auth_info
        payload["coverage"]["engine"] = configure_eevee(scene)
        configure_png_output(
            scene,
            output_prefix=frames_dir / "frame_",
            resolution_x=640,
            resolution_y=360,
            resolution_percentage=100,
        )
        scene.frame_start = 1
        scene.frame_end = ANIMATION_FRAME_COUNT
        log(TAG, "Environment ready; starting Create Earth.")

        create_status = create_earth_and_wait(state, scene)
        payload["coverage"]["create_earth"] = create_status
        log(TAG, "Create Earth completed; starting place search and resolves.")

        props = getattr(scene, "planetka", None)
        if props is None:
            raise E2EError("scene.planetka is unavailable.")

        selected_place = search_place(
            props,
            state,
            geonames,
            ANIMATION_QUERY,
            country_hint=COUNTRY_HINT_BY_CITY.get(ANIMATION_QUERY),
        )
        set_navigation(
            props,
            state,
            nav_altitude_km=120.0,
            nav_azimuth_deg=28.0,
            nav_tilt_deg=42.0,
            nav_roll_deg=0.0,
        )
        bpy.ops.planetka.sunlight_preset(preset="LATE_AFTERNOON")
        payload["coverage"]["place_search"] = {
            "query": ANIMATION_QUERY,
            "selected": selected_place,
        }

        resolve_results = {}
        for quality in ("PREVIEW", "BALANCED", "FULL"):
            op_result = bpy.ops.planetka.set_texture_quality_and_resolve(texture_quality_mode=quality)
            if "FINISHED" not in op_result:
                raise E2EError(f"Texture quality resolve failed for {quality}: {op_result}")
            resolve_results[quality.lower()] = {
                "operator_result": list(op_result),
                "runtime_status": state.get_resolve_runtime_status(scene),
                "tile_count": int(getattr(scene, "get", lambda *_args, **_kwargs: 0)("planetka_last_manual_resolve_tile_count", 0) or 0),
            }
        payload["coverage"]["quality_resolves"] = resolve_results
        log(TAG, "Preview/Balanced/Full resolve sweep completed.")

        props.anim_camera_preset = "ORBIT"
        props.anim_frame_start = 1
        props.anim_frame_end = ANIMATION_FRAME_COUNT
        props.anim_motion_curve = "EASE_IN_OUT"
        props.anim_orbit_degrees = 40.0
        props.anim_prepare_max_segments = 8
        props.anim_prepare_max_textures_mb = 1024.0

        make_ready_result = bpy.ops.planetka.animation_make_ready()
        if "FINISHED" not in make_ready_result:
            raise E2EError(f"animation_make_ready failed: {make_ready_result}")
        payload["coverage"]["quick_preview_make_ready"] = list(make_ready_result)
        log(TAG, "Quick Preview prepared; starting 4-frame EEVEE animation render.")

        render_animation(
            scene,
            output_prefix=frames_dir / "frame_",
            frame_start=1,
            frame_end=ANIMATION_FRAME_COUNT,
        )
        log(TAG, "Animation render completed; analyzing frames.")
        sequence_analysis = analyze_png_directory(frames_dir, max_samples=ANIMATION_FRAME_COUNT)
        payload["renders"]["quick_preview_eevee"] = sequence_analysis

        log(TAG, "Frame analysis completed; clearing prepared animation state.")
        clear_result = bpy.ops.planetka.animation_clear_prepared()
        if "FINISHED" not in clear_result:
            raise E2EError(f"animation_clear_prepared failed: {clear_result}")
        payload["coverage"]["quick_preview_clear"] = list(clear_result)
        log(TAG, "Prepared animation state cleared; writing report.")

        if sequence_analysis.get("has_mostly_black"):
            raise E2EError("Short E2E render produced a mostly-black frame.")
        if sequence_analysis.get("has_pink_corrupt"):
            raise E2EError("Short E2E render produced pink/missing-texture corruption.")

        payload["status"] = "ok"
        payload["elapsed_sec"] = round(time.time() - started, 3)
        write_json(report_path, payload)
        log(TAG, f"PASS: report={report_path}")
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        payload["traceback"] = traceback.format_exc()
        _fail(report_path, payload, exc)
    except (E2EError, RuntimeError, TypeError, ValueError) as exc:
        payload["traceback"] = traceback.format_exc()
        _fail(report_path, payload, exc)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - hard stop for unexpected failures.
        payload["traceback"] = traceback.format_exc()
        _fail(report_path, payload, exc)


if __name__ == "__main__":
    main()
