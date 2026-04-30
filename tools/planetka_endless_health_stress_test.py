"""
Planetka endless health stress test (prepared for repeated operational use).

This script is designed to run indefinitely until manually stopped.
It exercises a broad random mix of Planetka resolve/render settings and logs failures.

Flow:
1) Authenticate and validate commercial account session.
2) Remove default scene (when possible), then Create Earth.
3) Endless randomized loop:
   - random place search
   - random navigation/camera settings
   - randomized Earth radius + optional randomized Planetka Root transform
   - sunlight preset: EARLY_MORNING or LATE_AFTERNOON
   - resolve in FULL quality and wait for settle
   - render PNG in HD or 4K
   - render engine randomly EEVEE or Cycles CPU
   - validate output (pink/mostly-black checks)
4) Save all renders to /Volumes/SSDA/Renders/Stress-Test by default.
5) On visual corruption, save artifacts into /Volumes/SSDA/Renders/Stress-Test/Errors.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_endless_health_stress_test.py

Optional env:
  PLANETKA_MODULE=<module-name>
  PLANETKA_AUTH_PAYLOAD=/abs/path/auth_payload.json
  PLANETKA_API_KEY=<api-key>
  PLANETKA_API_KEY_PATH=/abs/path/api_key.json
  PLANETKA_STRESS_ROOT=/Volumes/SSDA/Renders/Stress-Test
  PLANETKA_STRESS_EXPECTED_EMAIL=commercial@planetka.io
  PLANETKA_STRESS_MAX_CASES=0     # 0 = infinite
  PLANETKA_STRESS_SEED=<int>      # optional fixed seed
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import sqlite3
import sys
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from planetka_e2e_common import (  # noqa: E402
    E2EError,
    analyze_render_image,
    configure_eevee,
    configure_png_output,
    enable_module,
    ensure_authenticated,
    get_runtime_status,
    import_submodule,
    read_scene_last_resolve_error,
    render_still,
    resolve_textures,
    wait_for_geonames_ready,
)
from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS  # noqa: E402

import bpy  # noqa: E402


TAG = "[Planetka Endless Stress]"
DEFAULT_STRESS_ROOT = "/Volumes/SSDA/Renders/Stress-Test"
DEFAULT_EXPECTED_EMAIL = "commercial@planetka.io"
EARTH_RADIUS_CHOICES = (2.0, 600.0, 6378.0)
SUNLIGHT_CHOICES = ("EARLY_MORNING", "LATE_AFTERNOON")
RESOLUTION_CHOICES = (
    ("HD", 1920, 1080),
    ("4K", 3840, 2160),
)


def _log(message):
    print(f"{TAG} {message}", flush=True)


def _to_jsonable(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_jsonable(v) for v in value]
        return str(value)


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(_to_jsonable(payload), handle, indent=2, ensure_ascii=True)


def _append_jsonl(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(_to_jsonable(payload), ensure_ascii=True) + "\n")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _open_places_connection(geonames_module):
    wait_for_geonames_ready(geonames_module, timeout_sec=240.0)
    db_path = str(getattr(geonames_module, "_INDEX_DB_PATH", "") or "").strip()
    if not db_path or not os.path.isfile(db_path):
        raise E2EError(f"GeoNames DB path missing: {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    cursor = connection.cursor()
    cursor.execute("SELECT MIN(geonameid), MAX(geonameid) FROM places")
    row = cursor.fetchone()
    if not row or row[0] is None or row[1] is None:
        raise E2EError("GeoNames places table is empty.")
    return connection, db_path, int(row[0]), int(row[1])


def _sample_random_place_record(connection, min_id, max_id, rng, recently_used):
    cursor = connection.cursor()
    attempts = 0
    while attempts < 200:
        attempts += 1
        probe_id = rng.randint(int(min_id), int(max_id))
        cursor.execute(
            """
            SELECT geonameid, name, country_code, latitude, longitude
            FROM places
            WHERE geonameid >= ?
            ORDER BY geonameid ASC
            LIMIT 1
            """,
            (probe_id,),
        )
        row = cursor.fetchone()
        if not row:
            continue
        name = str(row[1] or "").strip()
        country = str(row[2] or "").strip().upper()
        if not name:
            continue
        display = f"{name}, {country}" if country else name
        if display in recently_used:
            continue
        return {
            "geonameid": int(row[0]),
            "display": display,
            "name": name,
            "country_code": country,
            "latitude": _safe_float(row[3], 0.0),
            "longitude": _safe_float(row[4], 0.0),
        }
    raise E2EError("Could not sample a random place after repeated attempts.")


def _apply_place(props, state_module, geonames_module, place_record):
    display = str((place_record or {}).get("display", "") or "").strip()
    if not display:
        raise E2EError("Place record missing display name.")

    props.nav_city_search = display
    selected_name = ""
    for _ in range(24):
        try:
            bpy.context.view_layer.update()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        selected_name = str(getattr(props, "nav_city_selected_name", "") or "").strip()
        if selected_name:
            return selected_name, "search"
        time.sleep(0.05)

    # Deterministic fallback via direct coordinates if async search callback lags.
    lon = _safe_float(place_record.get("longitude"), 0.0)
    lat = _safe_float(place_record.get("latitude"), 0.0)
    props.nav_longitude_deg = lon
    props.nav_latitude_deg = lat
    state_module.update_navigation_shot(props, bpy.context)
    fallback_name = str(display)
    return fallback_name, "direct_coords_fallback"


def _set_navigation_random(props, state_module, rng):
    altitude_km = float(rng.uniform(30.0, 800.0))
    heading_deg = float(rng.uniform(0.0, 360.0))
    tilt_deg = float(rng.uniform(-75.0, 75.0))
    roll_deg = float(rng.uniform(-25.0, 25.0))
    focal_mm = float(rng.uniform(30.0, 60.0))

    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_altitude_km = altitude_km
        props.nav_azimuth_deg = heading_deg
        props.nav_tilt_deg = tilt_deg
        props.nav_roll_deg = roll_deg
        props.nav_focal_length_mm = focal_mm
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)

    return {
        "altitude_km": round(altitude_km, 6),
        "heading_deg": round(heading_deg, 6),
        "tilt_deg": round(tilt_deg, 6),
        "roll_deg": round(roll_deg, 6),
        "focal_mm": round(focal_mm, 6),
    }


def _apply_random_earth_transform(props, root, rng):
    radius_value = float(rng.choice(EARTH_RADIUS_CHOICES))
    props.earth_radius_bu = radius_value

    mode = str(rng.choice(("zero", "random")))
    if root is None:
        return {
            "earth_radius_bu": radius_value,
            "earth_transform_mode": mode,
            "earth_root_present": False,
        }

    if mode == "zero":
        root.location = (0.0, 0.0, 0.0)
        root.rotation_euler = (0.0, 0.0, 0.0)
    else:
        loc_span = max(100.0, radius_value * 2.0)
        root.location = (
            float(rng.uniform(-loc_span, loc_span)),
            float(rng.uniform(-loc_span, loc_span)),
            float(rng.uniform(-loc_span, loc_span)),
        )
        root.rotation_euler = (
            math.radians(float(rng.uniform(-180.0, 180.0))),
            math.radians(float(rng.uniform(-180.0, 180.0))),
            math.radians(float(rng.uniform(-180.0, 180.0))),
        )

    return {
        "earth_radius_bu": radius_value,
        "earth_transform_mode": mode,
        "earth_root_present": True,
        "earth_root_location": [round(float(v), 6) for v in tuple(root.location)],
        "earth_root_rotation_deg": [
            round(math.degrees(float(root.rotation_euler[0])), 6),
            round(math.degrees(float(root.rotation_euler[1])), 6),
            round(math.degrees(float(root.rotation_euler[2])), 6),
        ],
    }


def _configure_cycles_cpu(scene, props):
    scene.render.engine = "CYCLES"
    cycles = getattr(scene, "cycles", None)
    if cycles is None:
        raise E2EError("Cycles settings unavailable.")

    # Requested stress settings for Cycles CPU.
    try:
        cycles.device = "CPU"
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    for attr_name, value in (
        ("use_adaptive_sampling", True),
        ("noise_threshold", 0.05),
        ("adaptive_threshold", 0.05),
        ("adaptive_min_samples", 2),
        ("use_denoising", False),
        ("use_preview_denoising", False),
        ("dicing_rate", 1.25),
        ("offscreen_dicing_scale", 4.0),
    ):
        if hasattr(cycles, attr_name):
            try:
                setattr(cycles, attr_name, value)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    try:
        view_layer_cycles = getattr(getattr(bpy.context, "view_layer", None), "cycles", None)
        if view_layer_cycles is not None and hasattr(view_layer_cycles, "use_denoising"):
            view_layer_cycles.use_denoising = False
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    if props is not None:
        if hasattr(props, "anim_render_dicing_rate"):
            try:
                props.anim_render_dicing_rate = 1.25
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        if hasattr(props, "anim_render_offscreen_scale"):
            try:
                props.anim_render_offscreen_scale = 4.0
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _configure_engine_and_resolution(scene, props, rng, case_id):
    engine_mode = str(rng.choice(("EEVEE", "CYCLES_CPU")))
    res_label, res_x, res_y = rng.choice(RESOLUTION_CHOICES)

    if engine_mode == "EEVEE":
        resolved_engine = configure_eevee(scene)
    else:
        _configure_cycles_cpu(scene, props)
        resolved_engine = "CYCLES"

    configure_png_output(
        scene,
        output_prefix=case_id,
        resolution_x=int(res_x),
        resolution_y=int(res_y),
        resolution_percentage=100,
    )
    scene.render.film_transparent = False

    return {
        "engine_mode": engine_mode,
        "resolved_engine": str(resolved_engine),
        "resolution_label": str(res_label),
        "resolution_x": int(res_x),
        "resolution_y": int(res_y),
    }


def _apply_sunlight(rng):
    preset = str(rng.choice(SUNLIGHT_CHOICES))
    result = bpy.ops.planetka.sunlight_preset(preset=preset)
    return preset, list(result)


def _capture_error_artifacts(scene, case_payload, errors_dir: Path):
    errors_dir.mkdir(parents=True, exist_ok=True)
    case_id = str(case_payload.get("case_id", "case_unknown"))
    render_path = str(case_payload.get("render_path", "") or "").strip()

    copied_render_path = ""
    if render_path and os.path.isfile(render_path):
        target_png = errors_dir / f"{case_id}.png"
        try:
            shutil.copy2(render_path, target_png)
            copied_render_path = str(target_png)
        except OSError:
            copied_render_path = ""

    blend_path = errors_dir / f"{case_id}.blend"
    blend_saved = False
    try:
        result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True, check_existing=False)
        blend_saved = "FINISHED" in result
    except TOOL_RECOVERABLE_EXCEPTIONS:
        blend_saved = False
    except (RuntimeError, TypeError, ValueError):
        blend_saved = False

    artifact_payload = dict(case_payload)
    artifact_payload["error_capture_saved_render"] = copied_render_path
    artifact_payload["error_capture_saved_blend"] = str(blend_path) if blend_saved else ""
    artifact_payload["error_capture_saved_blend_ok"] = bool(blend_saved)
    _write_json(errors_dir / f"{case_id}.json", artifact_payload)

    return {
        "saved_render_path": copied_render_path,
        "saved_blend_path": str(blend_path) if blend_saved else "",
        "saved_blend_ok": bool(blend_saved),
    }


def main():
    stress_root = Path(str(os.environ.get("PLANETKA_STRESS_ROOT") or DEFAULT_STRESS_ROOT).strip())
    errors_dir = stress_root / "Errors"
    expected_email = str(
        os.environ.get("PLANETKA_STRESS_EXPECTED_EMAIL") or DEFAULT_EXPECTED_EMAIL
    ).strip().lower()
    max_cases = max(0, _safe_int(os.environ.get("PLANETKA_STRESS_MAX_CASES"), 0))

    seed_env = str(os.environ.get("PLANETKA_STRESS_SEED") or "").strip()
    if seed_env:
        seed = int(seed_env)
    else:
        seed = int.from_bytes(os.urandom(8), byteorder="big", signed=False)
    rng = random.Random(seed)

    stress_root.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    run_started = time.time()
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"stress_{run_ts}_{seed & 0xFFFFFFFF:08x}"
    events_path = stress_root / f"{run_id}_events.jsonl"
    summary_path = stress_root / f"{run_id}_summary.json"
    latest_summary_path = stress_root / "stress_latest_summary.json"

    _log(f"Run id={run_id} seed={seed}")
    _log(f"Output root: {stress_root}")
    _log(f"Errors dir: {errors_dir}")
    _log("Preparing addon and account session...")

    base_module = enable_module(required_planetka_attr="add_earth")
    auth = import_submodule(base_module, "auth")
    extension_prefs = import_submodule(base_module, "extension_prefs")
    state_module = import_submodule(base_module, "state")
    geonames_module = import_submodule(base_module, "geonames_db")
    diagnostics_module = import_submodule(base_module, "diagnostics")
    asset_builder = import_submodule(base_module, "asset_builder")

    prefs = extension_prefs.get_prefs()
    auth_info = ensure_authenticated(
        auth,
        prefs,
        payload_path=str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip(),
        api_key=str(os.environ.get("PLANETKA_API_KEY") or "").strip(),
        api_key_path=str(os.environ.get("PLANETKA_API_KEY_PATH") or "").strip(),
    )
    email = str(auth_info.get("email", "") or "").strip().lower()
    tier = str(auth_info.get("account_tier", "") or "").strip().lower()
    plan = str(auth_info.get("plan_code", "") or "").strip().lower()
    commercial_allowed = bool(auth_info.get("commercial_use_allowed", False))

    if expected_email and email != expected_email:
        raise E2EError(f"Account mismatch: expected={expected_email} got={email}")
    if tier != "commercial" or plan != "commercial" or not commercial_allowed:
        raise E2EError(
            f"Account tier is not commercial: tier={tier} plan={plan} commercial_use_allowed={commercial_allowed}"
        )
    _log(f"Authenticated: email={email} tier={tier} plan={plan}")

    scene = bpy.context.scene
    props = getattr(scene, "planetka", None)
    if props is None:
        raise E2EError("Planetka scene properties are missing.")

    # Requested startup flow.
    if hasattr(bpy.ops.planetka, "remove_default_scene") and bpy.ops.planetka.remove_default_scene.poll():
        remove_result = bpy.ops.planetka.remove_default_scene()
        _log(f"remove_default_scene result={set(remove_result)}")
    else:
        _log("remove_default_scene skipped (scene is not pristine default startup).")

    props.auto_resolve = False
    props.show_earth_preview = False
    props.texture_quality_mode = "FULL"
    if hasattr(prefs, "texture_base_path"):
        prefs.texture_base_path = "planetka-remote"

    create_result = bpy.ops.planetka.add_earth()
    if "FINISHED" not in create_result:
        raise E2EError(f"Create Earth failed: {create_result}")
    _log("Create Earth finished.")

    connection = None
    db_path = ""
    min_id = 0
    max_id = 0
    try:
        connection, db_path, min_id, max_id = _open_places_connection(geonames_module)
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        raise

    recent_place_window = []
    recent_place_set = set()
    max_recent_places = 5000
    case_index = 0
    pass_count = 0
    fail_count = 0
    warnings_count = 0
    fatal_errors = []
    seen_signatures = set()

    try:
        while True:
            if max_cases > 0 and case_index >= max_cases:
                _log(f"Reached PLANETKA_STRESS_MAX_CASES={max_cases}; stopping.")
                break

            case_index += 1
            case_started = time.time()
            case_id = f"{run_id}_{case_index:07d}"
            case_payload = {
                "case_id": case_id,
                "case_index": int(case_index),
                "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(case_started)),
                "ok": False,
                "warnings": [],
                "errors": [],
            }

            try:
                place_record = _sample_random_place_record(
                    connection,
                    min_id=min_id,
                    max_id=max_id,
                    rng=rng,
                    recently_used=recent_place_set,
                )
                display = str(place_record.get("display", ""))
                case_payload["place_display"] = display
                case_payload["place_geonameid"] = int(place_record.get("geonameid", 0))

                selected_name, place_apply_mode = _apply_place(props, state_module, geonames_module, place_record)
                case_payload["selected_place"] = str(selected_name)
                case_payload["place_apply_mode"] = str(place_apply_mode)
                if str(place_apply_mode) != "search":
                    case_payload["warnings"].append("place_search_callback_delayed")

                root = bpy.data.objects.get(str(getattr(asset_builder, "PLANETKA_ROOT_OBJECT_NAME", "Planetka Root")))
                case_payload.update(_apply_random_earth_transform(props, root, rng))

                nav_payload = _set_navigation_random(props, state_module, rng)
                case_payload.update(nav_payload)

                sunlight_preset, sunlight_result = _apply_sunlight(rng)
                case_payload["sunlight_preset"] = sunlight_preset
                case_payload["sunlight_result"] = sunlight_result
                if "FINISHED" not in sunlight_result:
                    case_payload["warnings"].append("sunlight_preset_failed")

                props.texture_quality_mode = "FULL"

                case_payload.update(_configure_engine_and_resolution(scene, props, rng, case_id))
                engine_tag = "eevee" if "EEVEE" in str(case_payload.get("resolved_engine", "")).upper() else "cycles_cpu"
                res_label = str(case_payload.get("resolution_label", "HD")).lower()
                render_path = stress_root / f"{case_id}_{engine_tag}_{res_label}.png"
                configure_png_output(
                    scene,
                    output_prefix=render_path,
                    resolution_x=int(case_payload["resolution_x"]),
                    resolution_y=int(case_payload["resolution_y"]),
                    resolution_percentage=100,
                )
                scene.render.filepath = str(render_path)
                case_payload["render_path"] = str(render_path)

                signature = (
                    case_payload.get("place_geonameid"),
                    case_payload.get("earth_radius_bu"),
                    case_payload.get("earth_transform_mode"),
                    case_payload.get("engine_mode"),
                    case_payload.get("resolution_label"),
                    round(_safe_float(case_payload.get("altitude_km")), 3),
                    round(_safe_float(case_payload.get("heading_deg")), 3),
                    round(_safe_float(case_payload.get("tilt_deg")), 3),
                    round(_safe_float(case_payload.get("roll_deg")), 3),
                    round(_safe_float(case_payload.get("focal_mm")), 3),
                )
                if signature in seen_signatures:
                    case_payload["warnings"].append("duplicate_case_signature")
                else:
                    seen_signatures.add(signature)
                    if len(seen_signatures) > 50000:
                        # bound memory in very long runs
                        seen_signatures = set(list(seen_signatures)[-25000:])

                resolve_started = time.perf_counter()
                resolve_textures(
                    state_module,
                    scene,
                    scope_mode="CAMERA",
                    texture_quality_mode="FULL",
                    defer_download=False,
                )
                case_payload["resolve_wall_ms"] = round((time.perf_counter() - resolve_started) * 1000.0, 3)

                runtime_status = get_runtime_status(state_module, scene)
                diag = diagnostics_module.read_diagnostics(scene)
                scene_resolve_error = read_scene_last_resolve_error(scene)

                case_payload["runtime_status"] = dict(runtime_status or {})
                case_payload["diagnostics"] = dict(diag or {})
                case_payload["scene_last_resolve_error"] = str(scene_resolve_error or "")

                if scene_resolve_error:
                    case_payload["warnings"].append("scene_last_resolve_error_set")
                if str(diag.get("resolve_error", "") or "").strip():
                    case_payload["warnings"].append("diagnostics_resolve_error_set")
                status_code = str(runtime_status.get("code", "") or "")
                if status_code and status_code not in {"IDLE", "MONITORING"}:
                    case_payload["warnings"].append(f"resolve_runtime_status_{status_code}")

                render_started = time.perf_counter()
                render_still(scene, render_path)
                case_payload["render_ms"] = round((time.perf_counter() - render_started) * 1000.0, 3)
                analysis = analyze_render_image(render_path)
                case_payload["image_analysis"] = dict(analysis or {})

                mostly_black = bool(analysis.get("mostly_black", False))
                pink_corrupt = bool(analysis.get("pink_corrupt", False))
                if mostly_black or pink_corrupt:
                    case_payload["errors"].append("render_visual_corruption")
                    capture = _capture_error_artifacts(scene, case_payload, errors_dir)
                    case_payload["error_artifacts"] = capture
                    _log(
                        f"ERROR case={case_id} visual corruption "
                        f"(mostly_black={mostly_black} pink_corrupt={pink_corrupt})"
                    )

                # Track recently used places to minimize repeats in long runs.
                if display:
                    recent_place_window.append(display)
                    recent_place_set.add(display)
                    if len(recent_place_window) > max_recent_places:
                        old = recent_place_window.pop(0)
                        recent_place_set.discard(old)

                case_payload["ok"] = len(case_payload["errors"]) == 0
            except Exception as exc:
                case_payload["errors"].append(str(exc))
                case_payload["traceback"] = traceback.format_exc()
                _log(f"ERROR case={case_id}: {exc}")
                # Capture state for resolve/render exceptions too.
                try:
                    capture = _capture_error_artifacts(scene, case_payload, errors_dir)
                    case_payload["error_artifacts"] = capture
                except Exception as capture_exc:  # noqa: BLE001
                    case_payload.setdefault("warnings", []).append(
                        f"error_artifact_capture_failed:{capture_exc}"
                    )
                case_payload["ok"] = False

            case_finished = time.time()
            case_payload["ended_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(case_finished))
            case_payload["elapsed_sec"] = round(case_finished - case_started, 3)
            _append_jsonl(events_path, case_payload)

            if case_payload["ok"]:
                pass_count += 1
            else:
                fail_count += 1
            warnings_count += len(case_payload.get("warnings", ()))

            if case_payload["ok"]:
                _log(
                    f"PASS case={case_index} place={case_payload.get('selected_place', '')} "
                    f"engine={case_payload.get('engine_mode')} res={case_payload.get('resolution_label')} "
                    f"resolve_ms={case_payload.get('resolve_wall_ms')} render_ms={case_payload.get('render_ms')}"
                )
            else:
                _log(
                    f"FAIL case={case_index} place={case_payload.get('selected_place', '')} "
                    f"errors={case_payload.get('errors')}"
                )

            summary = {
                "run_id": run_id,
                "seed": int(seed),
                "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(run_started)),
                "updated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(case_finished)),
                "duration_sec": round(case_finished - run_started, 3),
                "stress_root": str(stress_root),
                "events_jsonl": str(events_path),
                "errors_dir": str(errors_dir),
                "account": {
                    "email": email,
                    "tier": tier,
                    "plan": plan,
                    "commercial_use_allowed": commercial_allowed,
                },
                "geo_db_path": db_path,
                "counts": {
                    "cases_total": int(case_index),
                    "cases_passed": int(pass_count),
                    "cases_failed": int(fail_count),
                    "warnings_total": int(warnings_count),
                },
                "fatal_errors": list(fatal_errors),
            }
            _write_json(summary_path, summary)
            _write_json(latest_summary_path, summary)
    except KeyboardInterrupt:
        _log("Stopped by user (KeyboardInterrupt).")
    except Exception as exc:  # noqa: BLE001
        fatal_errors.append(str(exc))
        _log(f"FATAL: {exc}")
        _log(traceback.format_exc())
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        ended = time.time()
        final_summary = {
            "run_id": run_id,
            "seed": int(seed),
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(run_started)),
            "ended_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended)),
            "duration_sec": round(ended - run_started, 3),
            "stress_root": str(stress_root),
            "events_jsonl": str(events_path),
            "errors_dir": str(errors_dir),
            "account": {
                "email": email if "email" in locals() else "",
                "tier": tier if "tier" in locals() else "",
                "plan": plan if "plan" in locals() else "",
            },
            "counts": {
                "cases_total": int(case_index),
                "cases_passed": int(pass_count),
                "cases_failed": int(fail_count),
                "warnings_total": int(warnings_count),
            },
            "fatal_errors": list(fatal_errors),
        }
        _write_json(summary_path, final_summary)
        _write_json(latest_summary_path, final_summary)
        _log(
            f"Run finished: total={case_index} passed={pass_count} failed={fail_count} "
            f"warnings={warnings_count}"
        )
        _log(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
