"""
Build a manual replay .blend from a Planetka stress report.

Environment variables:
  PLANETKA_REPORT_JSON   Absolute path to report json (required)
  PLANETKA_OUTPUT_BLEND  Absolute path to output .blend (required)
  PLANETKA_MODULE        Optional addon module name (default: bl_ext.user_default.Planetka)
"""

import importlib
import json
import os
import random
import sqlite3
import sys
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

import addon_utils
import bpy


def _enable_addon():
    candidates = [
        os.environ.get("PLANETKA_MODULE", "").strip(),
        "bl_ext.user_default.Planetka",
        "Planetka",
        "planetka",
    ]
    for mod in [m for m in candidates if m]:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    return ""


def _import_submodule(base_mod, sub):
    candidates = []
    if base_mod:
        candidates.append(f"{base_mod}.{sub}")
    candidates.extend(
        [
            f"bl_ext.user_default.Planetka.{sub}",
            f"Planetka.{sub}",
            f"planetka.{sub}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    raise RuntimeError(f"Could not import submodule '{sub}'")


def _safe_marker_name(name):
    value = str(name or "").strip() or "Location"
    return value[:60]


def _lookup_place(geonames_module, label):
    text = str(label or "").strip()
    if not text:
        return None
    place = geonames_module.get_place_by_display(text)
    if isinstance(place, dict):
        return place

    # Fuzzy fallback for labels containing locale/diacritic variants.
    # Example input: "Satyāmangala, IN"
    name_part = text
    country_hint = ""
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if parts:
            name_part = parts[0]
        if len(parts) >= 2:
            country_hint = parts[-1].upper()
    try:
        candidates = geonames_module.search_places(name_part, max_results=50) or []
    except TOOL_RECOVERABLE_EXCEPTIONS:
        candidates = []
    for item in candidates:
        try:
            candidate_label = str(item[0] or "").strip()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
        if not candidate_label:
            continue
        if country_hint and not candidate_label.upper().endswith(f", {country_hint}"):
            continue
        place = geonames_module.get_place_by_display(candidate_label)
        if isinstance(place, dict):
            return place
    # Last attempt without country filter.
    for item in candidates:
        try:
            candidate_label = str(item[0] or "").strip()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
        if not candidate_label:
            continue
        place = geonames_module.get_place_by_display(candidate_label)
        if isinstance(place, dict):
            return place
    return None


def _sample_place_records_from_geonames(geonames_module, count, seed):
    geonames_module.load_geonames_database()
    db_path = str(getattr(geonames_module, "_INDEX_DB_PATH", "") or "").strip()
    if not db_path or not os.path.isfile(db_path):
        return []

    rng = random.Random(int(seed))
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT MIN(geonameid), MAX(geonameid) FROM places")
        row = cursor.fetchone()
        if not row or row[0] is None or row[1] is None:
            return []
        min_id = int(row[0])
        max_id = int(row[1])

        sampled = []
        used = set()
        attempts = 0
        max_attempts = max(5000, int(count) * 50)
        while len(sampled) < int(count) and attempts < max_attempts:
            attempts += 1
            probe = rng.randint(min_id, max_id)
            cursor.execute(
                """
                SELECT geonameid, name, country_code, latitude, longitude
                FROM places
                WHERE geonameid >= ?
                ORDER BY geonameid ASC
                LIMIT 1
                """,
                (probe,),
            )
            item = cursor.fetchone()
            if not item:
                continue
            name = str(item[1] or "").strip()
            country = str(item[2] or "").strip().upper()
            if not name:
                continue
            try:
                lat = float(item[3])
                lon = float(item[4])
            except TOOL_RECOVERABLE_EXCEPTIONS:
                continue
            display = f"{name}, {country}" if country else name
            if display in used:
                continue
            used.add(display)
            sampled.append(
                {
                    "display": display,
                    "latitude": lat,
                    "longitude": lon,
                }
            )
        return sampled
    finally:
        connection.close()


def _apply_nav(props, state_module, lon, lat, alt, heading, tilt, roll, focal):
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_longitude_deg = float(lon)
        props.nav_latitude_deg = float(lat)
        props.nav_altitude_km = float(max(0.0, alt))
        props.nav_azimuth_deg = float(heading)
        props.nav_tilt_deg = float(tilt)
        props.nav_roll_deg = float(roll)
        props.nav_focal_length_mm = float(focal)
    finally:
        state_module.resume_navigation_shot_updates()
    result = bpy.ops.planetka.navigation_apply_shot()
    if "FINISHED" not in result:
        raise RuntimeError(f"navigation_apply_shot failed: {result}")


def _keyframe_camera(camera, frame):
    bpy.context.scene.frame_set(int(frame))
    camera.keyframe_insert(data_path="location", frame=int(frame))
    if str(getattr(camera, "rotation_mode", "")) == "QUATERNION":
        camera.keyframe_insert(data_path="rotation_quaternion", frame=int(frame))
    else:
        camera.keyframe_insert(data_path="rotation_euler", frame=int(frame))
    cam_data = getattr(camera, "data", None)
    if cam_data is not None:
        cam_data.keyframe_insert(data_path="lens", frame=int(frame))


def _keyframe_nav_props(props, frame):
    for path in (
        "nav_longitude_deg",
        "nav_latitude_deg",
        "nav_altitude_km",
        "nav_azimuth_deg",
        "nav_tilt_deg",
        "nav_roll_deg",
        "nav_focal_length_mm",
        "sunlight_longitude_deg",
        "sunlight_seasonal_tilt_deg",
        "sunlight_strength",
    ):
        try:
            props.keyframe_insert(data_path=path, frame=int(frame))
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass


def main():
    report_path = str(os.environ.get("PLANETKA_REPORT_JSON") or "").strip()
    out_blend = str(os.environ.get("PLANETKA_OUTPUT_BLEND") or "").strip()
    if not report_path or not os.path.isfile(report_path):
        raise RuntimeError(f"PLANETKA_REPORT_JSON missing or not found: {report_path}")
    if not out_blend:
        raise RuntimeError("PLANETKA_OUTPUT_BLEND is required")
    os.makedirs(os.path.dirname(out_blend), exist_ok=True)

    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    cases = [c for c in list(report.get("cases") or []) if bool(c.get("ok"))]
    if not cases:
        raise RuntimeError("No successful cases in report")

    base_mod = _enable_addon()
    if not base_mod:
        raise RuntimeError("Could not enable Planetka addon")
    geonames_module = _import_submodule(base_mod, "geonames_db")
    state_module = _import_submodule(base_mod, "state")
    extension_prefs = _import_submodule(base_mod, "extension_prefs")
    auth_module = _import_submodule(base_mod, "auth")

    prefs = extension_prefs.get_prefs()
    auth_device_id = str(os.environ.get("PLANETKA_AUTH_DEVICE_ID") or "").strip()
    if auth_device_id:
        try:
            prefs.auth_device_id = auth_device_id
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
    if not bool(auth_module.is_authenticated(prefs)):
        api_key = str(os.environ.get("PLANETKA_AUTH_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("PLANETKA_AUTH_API_KEY required when no active Planetka session exists")
        auth_module.connect_with_api_key(api_key, prefs=prefs)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_current = 1
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080

    create_result = bpy.ops.planetka.add_earth()
    if "FINISHED" not in create_result:
        raise RuntimeError(f"Create Earth failed: {create_result}")
    try:
        bpy.ops.planetka.set_background_black()
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    props = scene.planetka
    props.auto_resolve = False
    props.texture_quality_mode = "FULL"
    try:
        bpy.ops.planetka.sunlight_preset(preset="MID_MORNING")
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        raise RuntimeError("No active camera after Create Earth")

    # Clear old markers.
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)

    failures = []

    report_seed = int(report.get("seed") or 20260408)
    report_count = int(report.get("random_place_count_requested") or len(cases) or 0)
    sampled_records = _sample_place_records_from_geonames(geonames_module, report_count, report_seed)
    sampled_by_case = {idx + 1: rec for idx, rec in enumerate(sampled_records)}
    frame = 1
    for case in cases:
        label = str(case.get("selected_place") or case.get("label") or "").strip()
        case_num = int(case.get("case") or frame)
        sampled = sampled_by_case.get(case_num)
        if sampled:
            place = {
                "longitude": sampled.get("longitude"),
                "latitude": sampled.get("latitude"),
                "display_name": sampled.get("display"),
            }
            if not label:
                label = str(sampled.get("display") or "").strip()
        else:
            place = _lookup_place(geonames_module, label) if label else None
        if not isinstance(place, dict):
            failures.append({"case": case.get("case"), "label": label, "reason": "place_lookup_failed"})
            continue

        lon = float(place.get("longitude", 0.0))
        lat = float(place.get("latitude", 0.0))
        alt = float(case.get("altitude_km", 400.0))
        heading = float(case.get("heading_deg", 0.0))
        tilt = float(case.get("tilt_deg", 25.0))
        roll = float(case.get("roll_deg", 0.0))
        focal = float(case.get("focal_mm", 50.0))

        try:
            _apply_nav(props, state_module, lon, lat, alt, heading, tilt, roll, focal)
        except TOOL_RECOVERABLE_EXCEPTIONS as exc:
            failures.append({"case": case.get("case"), "label": label, "reason": f"apply_failed:{exc}"})
            continue

        _keyframe_camera(camera, frame)
        _keyframe_nav_props(props, frame)
        scene.timeline_markers.new(_safe_marker_name(label), frame=int(frame))
        frame += 1

    if frame <= 1:
        raise RuntimeError("No frames keyed")

    scene.frame_start = 1
    scene.frame_end = frame - 1
    scene.frame_current = 1

    text = bpy.data.texts.new("planetka_keyed_report_info.txt")
    text.write(f"Report: {report_path}\n")
    text.write(f"Output: {out_blend}\n")
    text.write(f"Frames keyed: {frame - 1}\n")
    text.write(f"Failures: {len(failures)}\n")
    for item in failures[:200]:
        text.write(json.dumps(item, ensure_ascii=False) + "\n")

    bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=False, copy=False)
    print(
        f"[Planetka keyed blend] done: {out_blend} frames={frame - 1} failures={len(failures)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        print(f"[Planetka keyed blend] ERROR: {exc}", flush=True)
        raise
