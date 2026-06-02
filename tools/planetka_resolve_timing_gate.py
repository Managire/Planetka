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
        "resolve_post_delete_ms": _round_ms(raw.get("resolve_post_delete_ms")),
        "resolve_post_mark_ms": _round_ms(raw.get("resolve_post_mark_ms")),
        "resolve_post_preview_ms": _round_ms(raw.get("resolve_post_preview_ms")),
        "resolve_cloud_optimize_ms": _round_ms(raw.get("resolve_cloud_optimize_ms")),
        "resolve_cloud_optimize_optimized": int(_numeric(raw.get("resolve_cloud_optimize_optimized"), 0)),
        "resolve_cloud_optimize_failed": int(_numeric(raw.get("resolve_cloud_optimize_failed"), 0)),
        "resolve_unaccounted_ms": _round_ms(raw.get("resolve_unaccounted_ms")),
        "resolve_downloaded_mb": round(_numeric(raw.get("resolve_downloaded_mb"), 0.0), 3),
        "resolve_textures_mb": round(_numeric(raw.get("resolve_textures_mb"), 0.0), 3),
        "resolve_required_mpp_m": round(_numeric(raw.get("resolve_required_mpp_m"), 0.0), 3),
        "resolve_safety_state": str(raw.get("resolve_safety_state") or ""),
        "view_latitude_deg": round(_numeric(raw.get("view_latitude_deg"), 0.0), 6),
        "view_longitude_deg": round(_numeric(raw.get("view_longitude_deg"), 0.0), 6),
        "view_altitude_km": round(_numeric(raw.get("view_altitude_km"), 0.0), 3),
    }


def _wait_for_queued_resolve(state_module, scene, *, timeout_sec=90.0, sleep_sec=0.025):
    runtime_fn = getattr(state_module, "get_resolve_runtime_status", None)
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
    if not callable(runtime_fn):
        return {
            "settled": False,
            "error": "runtime status unavailable",
            "status_durations_ms": {},
            "status_sequence": [],
            "final_status": {},
        }

    started = time.perf_counter()
    last_tick = started
    last_code = None
    durations = {}
    sequence = []
    final_status = {}

    try:
        while True:
            if callable(pump_fn):
                pump_fn()

            now = time.perf_counter()
            try:
                status = dict(runtime_fn(scene) or {})
            except TOOL_RECOVERABLE_EXCEPTIONS:
                status = {}
            code = str(status.get("code", "") or "IDLE")
            if last_code is not None:
                durations[last_code] = durations.get(last_code, 0.0) + max(0.0, now - last_tick)
            if code != last_code:
                sequence.append({
                    "code": code,
                    "at_ms": _round_ms((now - started) * 1000.0),
                    "text": str(status.get("text", "") or ""),
                    "pending_count": int(_numeric(status.get("pending_count"), 0)),
                    "running": bool(status.get("running", False)),
                })
            last_code = code
            last_tick = now
            final_status = status

            running = bool(status.get("running", False))
            pending_count = int(_numeric(status.get("pending_count"), 0))
            if not running and pending_count <= 0 and code in {"", "IDLE", "MONITORING"}:
                return {
                    "settled": True,
                    "elapsed_ms": _round_ms((now - started) * 1000.0),
                    "status_durations_ms": {key: _round_ms(value * 1000.0) for key, value in durations.items()},
                    "status_sequence": sequence,
                    "final_status": final_status,
                }
            if (now - started) > float(timeout_sec):
                if callable(stop_fn):
                    try:
                        stop_fn()
                    except TOOL_RECOVERABLE_EXCEPTIONS:
                        pass
                return {
                    "settled": False,
                    "error": "timeout",
                    "elapsed_ms": _round_ms((now - started) * 1000.0),
                    "status_durations_ms": {key: _round_ms(value * 1000.0) for key, value in durations.items()},
                    "status_sequence": sequence,
                    "final_status": final_status,
                }
            time.sleep(float(max(0.005, sleep_sec)))
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        return {
            "settled": False,
            "error": str(exc),
            "elapsed_ms": _round_ms((time.perf_counter() - started) * 1000.0),
            "status_durations_ms": {key: _round_ms(value * 1000.0) for key, value in durations.items()},
            "status_sequence": sequence,
            "final_status": final_status,
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
                enqueue_wall_ms = (time.perf_counter() - before) * 1000.0
                if "FINISHED" not in result:
                    raise E2EError(f"{mode} resolve failed: {result}")
                queued = _wait_for_queued_resolve(state, scene)
                if not bool(queued.get("settled", False)):
                    raise E2EError(f"{mode} queued resolve did not settle: {queued}")
                runtime_status = dict(queued.get("final_status", {}) or {})
                diag = _read_diag(diagnostics, scene)
                record = {
                    "iteration": iteration + 1,
                    "operator_result": list(result),
                    "wall_ms": _round_ms(float(queued.get("elapsed_ms", 0.0) or 0.0)),
                    "enqueue_wall_ms": _round_ms(enqueue_wall_ms),
                    "queued_status_durations_ms": dict(queued.get("status_durations_ms", {}) or {}),
                    "queued_status_sequence": list(queued.get("status_sequence", ()) or ()),
                    "runtime_status": dict(runtime_status or {}),
                    **diag,
                }
                mode_records.append(record)
                log(
                    TAG,
                    (
                        f"{mode} {iteration + 1}/{ITERATIONS}: "
                        f"enqueue={record['enqueue_wall_ms']:.1f}ms "
                        f"queued={record['wall_ms']:.1f}ms "
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
