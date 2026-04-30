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
import subprocess
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
from mathutils import Vector  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402


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


def _analyze_render_image_cv2(path):
    image_path = Path(str(path))
    if not image_path.is_file():
        raise E2EError(f"Rendered image does not exist: {image_path}")

    python_bin = shutil.which("python3") or sys.executable
    script = r"""
import cv2
import json
import sys

path = sys.argv[1]
img = cv2.imread(path, cv2.IMREAD_COLOR)
if img is None:
    raise RuntimeError(f"cv2.imread failed: {path}")

height = int(img.shape[0])
width = int(img.shape[1])
pixel_count = max(1, width * height)
step = max(1, pixel_count // 30000)

sampled = 0
black_count = 0
pink_count = 0
lum_sum = 0.0
max_lum = 0.0

for i in range(0, pixel_count, step):
    y = i // width
    x = i % width
    b8, g8, r8 = img[y, x]
    r = float(r8) / 255.0
    g = float(g8) / 255.0
    b = float(b8) / 255.0
    lum = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
    lum_sum += lum
    max_lum = max(max_lum, lum)
    if lum <= 0.01:
        black_count += 1
    if r >= 0.80 and b >= 0.80 and g <= 0.22 and abs(r - b) <= 0.20:
        pink_count += 1
    sampled += 1

avg_lum = lum_sum / max(1, sampled)
black_ratio = black_count / max(1, sampled)
pink_ratio = pink_count / max(1, sampled)
mostly_black = (avg_lum <= 0.02 and max_lum <= 0.08) or (black_ratio >= 0.995)
pink_corrupt = pink_ratio >= 0.005

print(json.dumps({
    "path": str(path),
    "width": int(width),
    "height": int(height),
    "samples": int(sampled),
    "avg_luminance": round(avg_lum, 6),
    "max_luminance": round(max_lum, 6),
    "black_ratio": round(black_ratio, 6),
    "pink_ratio": round(pink_ratio, 6),
    "mostly_black": bool(mostly_black),
    "pink_corrupt": bool(pink_corrupt),
    "analyzer": "opencv_external",
}))
"""
    result = subprocess.run(
        [python_bin, "-c", script, str(image_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if int(result.returncode) != 0:
        stderr = str(result.stderr or "").strip()
        raise E2EError(f"OpenCV image analysis failed for {image_path}: {stderr or result.returncode}")
    payload = json.loads(str(result.stdout or "{}").strip() or "{}")
    if not isinstance(payload, dict):
        raise E2EError(f"OpenCV image analysis returned invalid JSON for {image_path}")
    return payload


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


def _camera_facing_earth(scene, earth_root):
    camera = getattr(scene, "camera", None)
    if camera is None or earth_root is None:
        return True
    to_earth = Vector(earth_root.matrix_world.translation) - Vector(camera.matrix_world.translation)
    if to_earth.length <= 1e-9:
        return True
    cam_forward = -(camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0)))
    score = float(cam_forward.normalized().dot(to_earth.normalized()))
    return score >= 0.10


def _earth_projection_metrics(scene, earth_root, radius_bu):
    camera = getattr(scene, "camera", None)
    if camera is None or earth_root is None:
        return {"ok": False, "reason": "missing_camera_or_root"}
    if radius_bu <= 0.0:
        return {"ok": False, "reason": "invalid_radius"}

    center = Vector(earth_root.matrix_world.translation)
    camera_pos = Vector(camera.matrix_world.translation)
    to_earth = center - camera_pos
    distance = float(to_earth.length)
    if distance <= 1e-9:
        return {"ok": False, "reason": "zero_distance"}

    resolution_scale = float(max(1.0, float(getattr(scene.render, "resolution_percentage", 100) or 100) / 100.0))
    width = max(1.0, float(getattr(scene.render, "resolution_x", 1920) or 1920) * resolution_scale)
    height = max(1.0, float(getattr(scene.render, "resolution_y", 1080) or 1080) * resolution_scale)

    cam_data = getattr(camera, "data", None)
    fov_x = float(getattr(cam_data, "angle_x", 0.0) or 0.0)
    if fov_x <= 1e-6:
        fov_x = float(getattr(cam_data, "angle", 0.0) or 0.0)
    if fov_x <= 1e-6:
        return {"ok": False, "reason": "invalid_fov"}

    focal_px = (width * 0.5) / max(1e-6, math.tan(fov_x * 0.5))
    radius_px = float(focal_px * float(radius_bu) / max(1e-6, distance))
    ndc = world_to_camera_view(scene, camera, center)
    ndc_x = float(getattr(ndc, "x", 0.0))
    ndc_y = float(getattr(ndc, "y", 0.0))
    ndc_z = float(getattr(ndc, "z", 0.0))

    margin_u = radius_px / width
    margin_v = radius_px / height
    in_frame = (
        ndc_z > 0.0
        and ndc_x >= (0.0 - margin_u)
        and ndc_x <= (1.0 + margin_u)
        and ndc_y >= (0.0 - margin_v)
        and ndc_y <= (1.0 + margin_v)
    )
    return {
        "ok": True,
        "radius_bu": round(float(radius_bu), 6),
        "distance_bu": round(distance, 6),
        "distance_to_radius_ratio": round(distance / max(1e-9, float(radius_bu)), 6),
        "width_px": int(round(width)),
        "height_px": int(round(height)),
        "radius_px": round(radius_px, 6),
        "ndc_x": round(ndc_x, 6),
        "ndc_y": round(ndc_y, 6),
        "ndc_z": round(ndc_z, 6),
        "in_frame": bool(in_frame),
    }


def _projection_is_acceptable(metrics):
    if not metrics or not bool(metrics.get("ok")):
        return False
    if not bool(metrics.get("in_frame", False)):
        return False
    ndc_x = float(metrics.get("ndc_x", 0.5) or 0.5)
    ndc_y = float(metrics.get("ndc_y", 0.5) or 0.5)
    # Guard against pathological acceptances where center is far away from frame
    # but huge radius margin made in_frame evaluate True.
    if ndc_x < -0.25 or ndc_x > 1.25 or ndc_y < -0.25 or ndc_y > 1.25:
        return False
    # Camera must be safely outside the sphere (avoid near-center/inside states).
    if float(metrics.get("distance_to_radius_ratio", 0.0) or 0.0) < 1.05:
        return False
    # Prevent tiny/dot renders that look like black or unresolved previews.
    if float(metrics.get("radius_px", 0.0) or 0.0) < 24.0:
        return False
    return True


def _get_sunlight_object():
    for obj in tuple(getattr(bpy.data, "objects", ()) or ()):
        if str(getattr(obj, "type", "")) != "LIGHT":
            continue
        light_data = getattr(obj, "data", None)
        if str(getattr(light_data, "type", "")) != "SUN":
            continue
        name = str(getattr(obj, "name", "") or "")
        if "planetka" in name.lower() or "sun" in name.lower():
            return obj
    return None


def _sunlight_view_score(scene, earth_root):
    camera = getattr(scene, "camera", None)
    sun_obj = _get_sunlight_object()
    if camera is None or earth_root is None or sun_obj is None:
        return None

    center = Vector(earth_root.matrix_world.translation)
    cam_pos = Vector(camera.matrix_world.translation)
    view_dir = cam_pos - center
    if view_dir.length <= 1e-9:
        return None
    view_dir = view_dir.normalized()

    # Sun rays direction in world (where photons travel towards the scene).
    sun_ray_dir = -(sun_obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0)))
    if sun_ray_dir.length <= 1e-9:
        return None
    # Direction from Earth center towards Sun.
    sun_from_center = (-sun_ray_dir).normalized()
    return float(view_dir.dot(sun_from_center))


def _set_navigation_random(props, state_module, scene, earth_root, rng):
    chosen = None
    for _ in range(12):
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
        try:
            bpy.context.view_layer.update()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

        chosen = {
            "altitude_km": round(altitude_km, 6),
            "heading_deg": round(heading_deg, 6),
            "tilt_deg": round(tilt_deg, 6),
            "roll_deg": round(roll_deg, 6),
            "focal_mm": round(focal_mm, 6),
        }
        if _camera_facing_earth(scene, earth_root):
            return chosen
    return chosen or {}


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
        # Keep random Earth transform broad enough for stress while preserving scene legibility.
        loc_span = max(1.0, radius_value * 0.5)
        root.location = (
            float(rng.uniform(-loc_span, loc_span)),
            float(rng.uniform(-loc_span, loc_span)),
            float(rng.uniform(-loc_span, loc_span)),
        )
        root.rotation_euler = (
            math.radians(float(rng.uniform(-25.0, 25.0))),
            math.radians(float(rng.uniform(-25.0, 25.0))),
            math.radians(float(rng.uniform(-25.0, 25.0))),
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


def _wait_runtime_idle(state_module, scene, timeout_sec=90.0, sleep_sec=0.05):
    deadline = time.monotonic() + float(max(1.0, timeout_sec))
    last_status = {}
    while time.monotonic() < deadline:
        last_status = dict(get_runtime_status(state_module, scene) or {})
        running = bool(last_status.get("running", False))
        pending_count = int(last_status.get("pending_count", 0) or 0)
        code = str(last_status.get("code", "") or "")
        if (not running) and pending_count <= 0 and code in {"", "IDLE", "MONITORING"}:
            return last_status
        time.sleep(float(max(0.01, sleep_sec)))
    raise E2EError(f"Resolve runtime did not become idle in time: {last_status}")


def _apply_safe_visibility_baseline(props, state_module, scene, earth_root, rng):
    props.earth_radius_bu = 6378.0
    if earth_root is not None:
        earth_root.location = (0.0, 0.0, 0.0)
        earth_root.rotation_euler = (0.0, 0.0, 0.0)

    # Deterministic, camera-friendly navigation baseline.
    heading_deg = float(rng.uniform(0.0, 360.0))
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_altitude_km = 180.0
        props.nav_azimuth_deg = heading_deg
        props.nav_tilt_deg = 22.0
        props.nav_roll_deg = 0.0
        props.nav_focal_length_mm = 45.0
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)
    try:
        bpy.context.view_layer.update()
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    preset = "EARLY_MORNING"
    result = bpy.ops.planetka.sunlight_preset(preset=preset)
    return {
        "earth_radius_bu": 6378.0,
        "earth_transform_mode": "safe_forced",
        "earth_root_present": bool(earth_root is not None),
        "earth_root_location": [0.0, 0.0, 0.0],
        "earth_root_rotation_deg": [0.0, 0.0, 0.0],
        "altitude_km": 180.0,
        "heading_deg": round(heading_deg, 6),
        "tilt_deg": 22.0,
        "roll_deg": 0.0,
        "focal_mm": 45.0,
        "sunlight_preset": preset,
        "sunlight_result": list(result),
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

                props.show_earth_preview = False
                props.texture_quality_mode = "FULL"
                case_payload.update(_configure_engine_and_resolution(scene, props, rng, case_id))

                root = bpy.data.objects.get(str(getattr(asset_builder, "PLANETKA_ROOT_OBJECT_NAME", "Planetka Root")))
                geometry_attempts = 0
                accepted_projection = {}
                accepted_transform = {}
                accepted_nav = {}
                accepted_sunlight_preset = "EARLY_MORNING"
                accepted_sunlight_result = []
                while geometry_attempts < 32:
                    geometry_attempts += 1
                    transform_payload = _apply_random_earth_transform(props, root, rng)
                    nav_payload = _set_navigation_random(props, state_module, scene, root, rng)
                    sun_preset, sun_result = _apply_sunlight(rng)
                    try:
                        bpy.context.view_layer.update()
                    except TOOL_RECOVERABLE_EXCEPTIONS:
                        pass
                    projection = _earth_projection_metrics(scene, root, _safe_float(transform_payload.get("earth_radius_bu"), 0.0))
                    daylight_score = _sunlight_view_score(scene, root)
                    sunlight_ok = "FINISHED" in list(sun_result)
                    if _projection_is_acceptable(projection) and sunlight_ok and (daylight_score is None or daylight_score >= -0.10):
                        accepted_transform = dict(transform_payload)
                        accepted_nav = dict(nav_payload or {})
                        accepted_projection = dict(projection or {})
                        accepted_sunlight_preset = str(sun_preset)
                        accepted_sunlight_result = list(sun_result)
                        accepted_projection["daylight_score"] = (
                            round(float(daylight_score), 6) if daylight_score is not None else None
                        )
                        break

                if not accepted_transform:
                    case_payload["warnings"].append("projection_acceptance_failed")
                    baseline = _apply_safe_visibility_baseline(props, state_module, scene, root, rng)
                    accepted_transform = {
                        "earth_radius_bu": baseline["earth_radius_bu"],
                        "earth_transform_mode": baseline["earth_transform_mode"],
                        "earth_root_present": baseline["earth_root_present"],
                        "earth_root_location": baseline["earth_root_location"],
                        "earth_root_rotation_deg": baseline["earth_root_rotation_deg"],
                    }
                    accepted_nav = {
                        "altitude_km": baseline["altitude_km"],
                        "heading_deg": baseline["heading_deg"],
                        "tilt_deg": baseline["tilt_deg"],
                        "roll_deg": baseline["roll_deg"],
                        "focal_mm": baseline["focal_mm"],
                    }
                    accepted_sunlight_preset = str(baseline["sunlight_preset"])
                    accepted_sunlight_result = list(baseline["sunlight_result"])
                    accepted_projection = dict(
                        _earth_projection_metrics(scene, root, _safe_float(baseline.get("earth_radius_bu"), 6378.0))
                        or {}
                    )
                    daylight_score = _sunlight_view_score(scene, root)
                    accepted_projection["daylight_score"] = (
                        round(float(daylight_score), 6) if daylight_score is not None else None
                    )

                case_payload.update(accepted_transform)
                case_payload.update(accepted_nav)
                case_payload["projection_metrics"] = accepted_projection
                case_payload["geometry_attempts"] = int(geometry_attempts)
                case_payload["sunlight_preset"] = accepted_sunlight_preset
                case_payload["sunlight_result"] = accepted_sunlight_result

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
                _wait_runtime_idle(state_module, scene, timeout_sec=120.0)
                props.show_earth_preview = False
                props.texture_quality_mode = "FULL"
                # Re-apply the accepted preset immediately before rendering.
                sunlight_result = bpy.ops.planetka.sunlight_preset(preset=accepted_sunlight_preset)
                case_payload["sunlight_result"] = list(sunlight_result)
                if "FINISHED" not in sunlight_result:
                    case_payload["warnings"].append("sunlight_preset_failed")
                try:
                    bpy.context.view_layer.update()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
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
                analysis = {}
                try:
                    analysis = _analyze_render_image_cv2(render_path)
                except Exception as analysis_exc:  # noqa: BLE001
                    case_payload["warnings"].append(
                        f"image_analysis_cv2_failed:{analysis_exc.__class__.__name__}"
                    )
                case_payload["image_analysis"] = dict(analysis or {})

                # Treat "black image" as near-total black corruption only.
                # Legitimate space-heavy frames can be mostly dark.
                mostly_black = bool(analysis.get("mostly_black", False))
                max_lum = _safe_float(analysis.get("max_luminance"), 1.0)
                avg_lum = _safe_float(analysis.get("avg_luminance"), 1.0)
                black_ratio = _safe_float(analysis.get("black_ratio"), 0.0)
                black_corrupt = bool(
                    analysis
                    and mostly_black
                    and max_lum <= 0.01
                    and avg_lum <= 0.002
                    and black_ratio >= 0.995
                )
                pink_corrupt = bool(analysis and analysis.get("pink_corrupt", False))
                if black_corrupt or pink_corrupt:
                    recovered = False
                    case_payload["warnings"].append("render_visual_corruption_detected")
                    try:
                        baseline = _apply_safe_visibility_baseline(props, state_module, scene, root, rng)
                        case_payload["recovery_baseline"] = dict(baseline)
                        props.show_earth_preview = False
                        props.texture_quality_mode = "FULL"
                        resolve_textures(
                            state_module,
                            scene,
                            scope_mode="CAMERA",
                            texture_quality_mode="FULL",
                            defer_download=False,
                        )
                        _wait_runtime_idle(state_module, scene, timeout_sec=120.0)
                        try:
                            bpy.ops.planetka.sunlight_preset(preset=str(baseline.get("sunlight_preset", "EARLY_MORNING")))
                        except TOOL_RECOVERABLE_EXCEPTIONS:
                            pass
                        recovery_started = time.perf_counter()
                        render_still(scene, render_path)
                        case_payload["render_recovery_ms"] = round((time.perf_counter() - recovery_started) * 1000.0, 3)
                        recovery_analysis = _analyze_render_image_cv2(render_path)
                        case_payload["image_analysis_recovery"] = dict(recovery_analysis or {})
                        rb_black = bool(recovery_analysis.get("mostly_black", False))
                        rb_max = _safe_float(recovery_analysis.get("max_luminance"), 1.0)
                        rb_avg = _safe_float(recovery_analysis.get("avg_luminance"), 1.0)
                        rb_ratio = _safe_float(recovery_analysis.get("black_ratio"), 0.0)
                        rb_black_corrupt = bool(
                            rb_black
                            and rb_max <= 0.01
                            and rb_avg <= 0.002
                            and rb_ratio >= 0.995
                        )
                        rb_pink_corrupt = bool(recovery_analysis.get("pink_corrupt", False))
                        if not rb_black_corrupt and not rb_pink_corrupt:
                            recovered = True
                            analysis = recovery_analysis
                            case_payload["image_analysis"] = dict(recovery_analysis or {})
                            case_payload["warnings"].append("render_visual_corruption_recovered")
                    except Exception as recovery_exc:  # noqa: BLE001
                        case_payload["warnings"].append(f"render_recovery_failed:{recovery_exc.__class__.__name__}")

                    if not recovered:
                        case_payload["errors"].append("render_visual_corruption")
                        capture = _capture_error_artifacts(scene, case_payload, errors_dir)
                        case_payload["error_artifacts"] = capture
                        _log(
                            f"ERROR case={case_id} visual corruption "
                            f"(black_corrupt={black_corrupt} pink_corrupt={pink_corrupt})"
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
