"""Profile Planetka resolve timing for Preview, Balanced, and Full Quality.

Run from Blender:
  /Applications/Blender5.0.app/Contents/MacOS/Blender --background \
    --python tools/planetka_resolve_timing_gate.py

The script reuses the current authenticated Blender profile unless
PLANETKA_AUTH_PAYLOAD or PLANETKA_API_KEY is supplied.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import traceback

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
    create_earth_and_wait,
    enable_module,
    ensure_authenticated,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    log,
    output_session,
    purge_planetka_data,
    search_place,
    set_navigation,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Resolve Timing]"
QUERY = os.environ.get("PLANETKA_TIMING_PLACE", "Singapore")
ITERATIONS = int(float(os.environ.get("PLANETKA_TIMING_ITERATIONS", "3") or 3))
QUALITY_MODES = ("PREVIEW", "BALANCED", "FULL")


def _round_ms(value):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def _numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _summarize(records):
    keys = (
        "wall_ms",
        "last_resolve_ms",
        "resolve_assets_ms",
        "resolve_tile_select_ms",
        "resolve_stream_ms",
        "resolve_download_ms",
        "resolve_download_thread_ms",
        "resolve_mesh_ms",
        "resolve_shader_ms",
        "resolve_post_ms",
        "resolve_unaccounted_ms",
        "resolve_downloaded_mb",
        "resolve_textures_mb",
        "last_tile_count",
    )
    summary = {}
    for key in keys:
        values = [_numeric(record.get(key), 0.0) for record in records]
        if not values:
            continue
        summary[key] = {
            "avg": _round_ms(statistics.mean(values)),
            "min": _round_ms(min(values)),
            "max": _round_ms(max(values)),
        }
    return summary


def _read_diag(diag_module, scene):
    raw = dict(diag_module.read_diagnostics(scene) or {})
    return {
        "last_resolve_ms": _round_ms(raw.get("last_resolve_ms")),
        "last_tile_count": int(_numeric(raw.get("last_tile_count"), 0)),
        "last_fallback_count": int(_numeric(raw.get("last_fallback_count"), 0)),
        "resolve_assets_ms": _round_ms(raw.get("resolve_assets_ms")),
        "resolve_tile_select_ms": _round_ms(raw.get("resolve_tile_select_ms")),
        "resolve_stream_ms": _round_ms(raw.get("resolve_stream_ms")),
        "resolve_download_ms": _round_ms(raw.get("resolve_download_ms")),
        "resolve_download_thread_ms": _round_ms(raw.get("resolve_download_thread_ms")),
        "resolve_mesh_ms": _round_ms(raw.get("resolve_mesh_ms")),
        "resolve_shader_ms": _round_ms(raw.get("resolve_shader_ms")),
        "resolve_post_ms": _round_ms(raw.get("resolve_post_ms")),
        "resolve_unaccounted_ms": _round_ms(raw.get("resolve_unaccounted_ms")),
        "resolve_downloaded_mb": round(_numeric(raw.get("resolve_downloaded_mb"), 0.0), 3),
        "resolve_textures_mb": round(_numeric(raw.get("resolve_textures_mb"), 0.0), 3),
        "resolve_required_mpp_m": round(_numeric(raw.get("resolve_required_mpp_m"), 0.0), 3),
        "resolve_safety_state": str(raw.get("resolve_safety_state") or ""),
        "view_latitude_deg": round(_numeric(raw.get("view_latitude_deg"), 0.0), 6),
        "view_longitude_deg": round(_numeric(raw.get("view_longitude_deg"), 0.0), 6),
        "view_altitude_km": round(_numeric(raw.get("view_altitude_km"), 0.0), 3),
    }


def main():
    started = time.time()
    session_dir = output_session("planetka_resolve_timing")
    report_path = session_dir / "planetka_resolve_timing_report.json"
    payload = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_dir": str(session_dir),
        "query": QUERY,
        "iterations": ITERATIONS,
        "records": {},
        "summary": {},
    }

    try:
        base_module = enable_module(required_planetka_attr="add_earth")
        auth = import_submodule(base_module, "auth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        geonames = import_submodule(base_module, "geonames_db")
        state = import_submodule(base_module, "state")
        diagnostics = import_submodule(base_module, "diagnostics")

        prefs = extension_prefs.get_prefs()
        payload["account"] = ensure_authenticated(
            auth,
            prefs,
            payload_path=str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip(),
            api_key=str(os.environ.get("PLANETKA_API_KEY") or "").strip(),
            api_key_path=str(os.environ.get("PLANETKA_API_KEY_PATH") or "").strip(),
        )
        wait_for_geonames_ready(geonames)

        scene = bpy.context.scene
        purge_planetka_data()
        ensure_camera(scene, name="Planetka Timing Camera")
        ensure_standard_world(scene)
        prefs.texture_base_path = "planetka-remote"

        log(TAG, "Creating Earth.")
        payload["create_earth_status"] = create_earth_and_wait(state, scene)
        props = getattr(scene, "planetka", None)
        if props is None:
            raise E2EError("scene.planetka is unavailable.")

        selected = search_place(
            props,
            state,
            geonames,
            QUERY,
            country_hint=COUNTRY_HINT_BY_CITY.get(QUERY),
        )
        set_navigation(
            props,
            state,
            nav_altitude_km=120.0,
            nav_azimuth_deg=28.0,
            nav_tilt_deg=42.0,
            nav_roll_deg=0.0,
        )
        payload["selected_place"] = selected

        for mode in QUALITY_MODES:
            mode_records = []
            log(TAG, f"Profiling {mode}.")
            for iteration in range(ITERATIONS):
                before = time.perf_counter()
                result = bpy.ops.planetka.set_texture_quality_and_resolve(texture_quality_mode=mode)
                wall_ms = (time.perf_counter() - before) * 1000.0
                if "FINISHED" not in result:
                    raise E2EError(f"{mode} resolve failed: {result}")
                runtime_status = state.get_resolve_runtime_status(scene)
                diag = _read_diag(diagnostics, scene)
                record = {
                    "iteration": iteration + 1,
                    "operator_result": list(result),
                    "wall_ms": _round_ms(wall_ms),
                    "runtime_status": dict(runtime_status or {}),
                    **diag,
                }
                mode_records.append(record)
                log(
                    TAG,
                    (
                        f"{mode} {iteration + 1}/{ITERATIONS}: "
                        f"wall={record['wall_ms']:.1f}ms "
                        f"resolve={record['last_resolve_ms']:.1f}ms "
                        f"stream={record['resolve_stream_ms']:.1f}ms "
                        f"mesh={record['resolve_mesh_ms']:.1f}ms "
                        f"shader={record['resolve_shader_ms']:.1f}ms "
                        f"tiles={record['last_tile_count']}"
                    ),
                )
            payload["records"][mode] = mode_records
            payload["summary"][mode] = _summarize(mode_records)

        payload["status"] = "ok"
        payload["elapsed_sec"] = round(time.time() - started, 3)
        write_json(report_path, payload)
        log(TAG, f"PASS: report={report_path}")
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
        write_json(report_path, payload)
        log(TAG, f"FAIL: {exc}")
        raise SystemExit(1)
    except (E2EError, RuntimeError, TypeError, ValueError) as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
        write_json(report_path, payload)
        log(TAG, f"FAIL: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
