#!/usr/bin/env python3
"""Planetka dual-engine E2E matrix using three real backend accounts.

Accounts are read from /tmp/planetka_test_accounts_keys.json and must contain:
{
  "free@planetka.io": {"plan": "free", "api_key": "pka_..."},
  "personal@planetka.io": {"plan": "personal", "api_key": "pka_..."},
  "commercial@planetka.io":  {"plan": "commercial",  "api_key": "pka_..."}
}
"""

from __future__ import annotations

import importlib
import json
import os
import random
import re
import time
import traceback
from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

import addon_utils
import bpy

TAG = "[Planetka Tier Dual E2E]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"
DEFAULT_KEYS_FILE = "/tmp/planetka_test_accounts_keys.json"

MILAN = {"name": "Milan", "lat": 45.4642, "lon": 9.19}
AUCKLAND = {"name": "Auckland", "lat": -36.8485, "lon": 174.7633}
CHRISTCHURCH = {"name": "Christchurch", "lat": -43.5321, "lon": 172.6362}
WELLINGTON = {"name": "Wellington", "lat": -41.2865, "lon": 174.7762}

CAPITAL_QUERIES = [
    "Tokyo", "Seoul", "Beijing", "Bangkok", "Singapore", "Jakarta", "Kuala Lumpur", "Manila",
    "Hanoi", "Phnom Penh", "Vientiane", "Naypyidaw", "Kathmandu", "New Delhi", "Islamabad",
    "Dhaka", "Colombo", "Riyadh", "Abu Dhabi", "Doha", "Kuwait City", "Muscat", "Amman",
    "Jerusalem", "Ankara", "Athens", "Sofia", "Bucharest", "Belgrade", "Budapest", "Vienna",
    "Prague", "Warsaw", "Berlin", "Amsterdam", "Brussels", "Paris", "Madrid", "Lisbon",
    "Dublin", "London", "Oslo", "Stockholm", "Helsinki", "Copenhagen", "Reykjavik", "Bern",
    "Rome", "Zagreb", "Ljubljana", "Bratislava", "Vilnius", "Riga", "Tallinn", "Minsk",
    "Kyiv", "Moscow", "Tbilisi", "Yerevan", "Baku", "Cairo", "Algiers", "Tunis", "Tripoli",
    "Rabat", "Dakar", "Accra", "Lagos", "Abuja", "Nairobi", "Addis Ababa", "Kampala", "Kigali",
    "Dar es Salaam", "Dodoma", "Windhoek", "Gaborone", "Harare", "Lusaka", "Maputo", "Luanda",
    "Pretoria", "Cape Town", "Canberra", "Wellington", "Suva", "Port Moresby", "Ottawa",
    "Washington", "Mexico City", "Havana", "Santo Domingo", "San Jose", "Panama City", "Bogota",
    "Quito", "Lima", "Santiago", "Buenos Aires", "Montevideo", "Asuncion", "La Paz", "Brasilia",
]


def _log(msg: str) -> None:
    print(f"{TAG} {msg}")


def _enable_module() -> str:
    candidates = [
        os.environ.get("PLANETKA_MODULE"),
        "bl_ext.user_default.Planetka",
        "Planetka",
        "planetka",
    ]
    for mod in [c for c in candidates if c]:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    raise RuntimeError("Could not enable Planetka addon module")


def _import_submodule(base_module_name: str, submodule_name: str):
    candidates = [
        f"{base_module_name}.{submodule_name}" if base_module_name else None,
        f"bl_ext.user_default.Planetka.{submodule_name}",
        f"Planetka.{submodule_name}",
        f"planetka.{submodule_name}",
    ]
    for mod in [c for c in candidates if c]:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    raise RuntimeError(f"Could not import {submodule_name}")


def _purge_planetka_data():
    for obj in list(bpy.data.objects):
        if str(obj.name).startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    for collection in list(bpy.data.collections):
        if str(collection.name).startswith("Planetka"):
            try:
                bpy.data.collections.remove(collection)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    for material in list(bpy.data.materials):
        if str(material.name).startswith("Planetka"):
            try:
                bpy.data.materials.remove(material)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    for mesh in list(bpy.data.meshes):
        if str(mesh.name).startswith("Planetka"):
            try:
                bpy.data.meshes.remove(mesh)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    for image in list(bpy.data.images):
        if str(image.name).startswith("Planetka"):
            try:
                bpy.data.images.remove(image)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
    for node_group in list(bpy.data.node_groups):
        if str(node_group.name).startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _ensure_camera(scene):
    camera = getattr(scene, "camera", None)
    if camera and getattr(camera, "type", None) == "CAMERA":
        return camera
    for obj in scene.objects:
        if getattr(obj, "type", None) == "CAMERA":
            scene.camera = obj
            return obj
    data = bpy.data.cameras.new("Camera")
    obj = bpy.data.objects.new("Camera", data)
    scene.collection.objects.link(obj)
    scene.camera = obj
    return obj


def _configure_render(scene, engine: str):
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    desired = "CYCLES" if engine.upper() == "CYCLES" else ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else "BLENDER_EEVEE")
    scene.render.engine = desired


def _reset_queued_resolve_pipeline(state_module):
    try:
        stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
        if callable(stop_fn):
            stop_fn()
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass


def _drain_resolve_pipeline(state_module, timeout_sec=45.0):
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    busy_fn = getattr(state_module, "_is_resolve_pipeline_busy", None)
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    while time.monotonic() < deadline:
        is_busy = False
        try:
            if callable(busy_fn):
                is_busy = bool(busy_fn())
        except TOOL_RECOVERABLE_EXCEPTIONS:
            is_busy = False
        if not is_busy:
            return
        try:
            if callable(pump_fn):
                pump_fn()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        time.sleep(0.05)


def _resolve_now(state_module=None, retries=3):
    last_error = None
    for _ in range(max(1, int(retries))):
        if state_module is not None:
            _drain_resolve_pipeline(state_module)
        try:
            return bpy.ops.planetka.load_textures(skip_render_compatibility=True, defer_download=False)
        except RuntimeError as exc:
            last_error = exc
            if "PKA-RES-002" in str(exc):
                if state_module is not None:
                    _drain_resolve_pipeline(state_module, timeout_sec=8.0)
                time.sleep(0.2)
                continue
            raise
    if last_error is not None:
        raise last_error
    return {'CANCELLED'}


def _set_navigation(props, state_module, lat, lon, altitude_km, heading_deg=0.0, tilt_deg=45.0, roll_deg=0.0):
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_latitude_deg = float(lat)
        props.nav_longitude_deg = float(lon)
        props.nav_altitude_km = float(altitude_km)
        props.nav_azimuth_deg = float(heading_deg)
        props.nav_tilt_deg = float(tilt_deg)
        props.nav_roll_deg = float(roll_deg)
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)


def _parse_tile_d_values(tiles):
    values = []
    for tile in (tiles or []):
        match = re.search(r"_d(\d{3})", str(tile))
        if match:
            values.append(int(match.group(1)))
    return values


def _render_still(scene, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)


def _apply_place_search(props, geonames_module, query_text: str):
    options = geonames_module.search_places(query_text, max_results=10)
    if not options:
        return None
    display = str(options[0][0])
    props.nav_city_search = display
    return display


def _connect_account(auth_module, prefs, email: str, api_key: str, expected_plan: str):
    auth_module.clear_auth_session(prefs=prefs, state="logged_out", status_message="")
    auth_module.connect_with_api_key(api_key, prefs=prefs)
    connected_email = str(auth_module.get_connected_email(prefs) or "").strip().lower()
    if connected_email != email.lower():
        raise RuntimeError(f"Connected email mismatch: expected={email} got={connected_email}")
    tier = str(auth_module.get_account_tier(prefs) or "").strip().lower()
    if tier != expected_plan:
        raise RuntimeError(f"Connected tier mismatch for {email}: expected={expected_plan} got={tier}")


def main():
    started = time.time()
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    keys_file = str(os.environ.get("PLANETKA_TEST_KEYS_FILE") or DEFAULT_KEYS_FILE).strip()
    random_seed = int(os.environ.get("PLANETKA_TIER_E2E_SEED") or "20260416")
    rng = random.Random(random_seed)

    os.makedirs(render_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    session_prefix = f"planetka_tier_dual_{stamp}"
    report_path = os.path.join(render_dir, f"{session_prefix}_report.json")

    with open(keys_file, "r", encoding="utf-8") as handle:
        key_data = json.load(handle)

    accounts = [
        ("free@planetka.io", "free"),
        ("personal@planetka.io", "personal"),
        ("commercial@planetka.io", "commercial"),
    ]
    for email, plan in accounts:
        if email not in key_data:
            raise RuntimeError(f"Missing account in keys file: {email}")
        if str(key_data[email].get("plan", "")).lower() != plan:
            raise RuntimeError(f"Plan mismatch in keys file for {email}")

    report = {
        "ok": True,
        "started_at": stamp,
        "seed": random_seed,
        "keys_file": keys_file,
        "scenarios": [],
        "errors": [],
        "elapsed_sec": None,
    }

    try:
        base_module = _enable_module()
        auth_module = _import_submodule(base_module, "auth")
        extension_prefs = _import_submodule(base_module, "extension_prefs")
        state_module = _import_submodule(base_module, "state")
        geonames_module = _import_submodule(base_module, "geonames_db")

        prefs = extension_prefs.get_prefs()
        if prefs is None:
            raise RuntimeError("Planetka prefs unavailable")

        for engine in ("EEVEE", "CYCLES"):
            for email, plan in accounts:
                _log(f"--- Engine={engine} Account={email} Plan={plan} ---")
                entry = {
                    "engine": engine,
                    "email": email,
                    "plan": plan,
                    "checks": [],
                    "renders": [],
                    "animation_frames": 0,
                }

                _connect_account(auth_module, prefs, email=email, api_key=str(key_data[email]["api_key"]), expected_plan=plan)

                scene = bpy.context.scene
                _purge_planetka_data()
                _configure_render(scene, engine)
                _ensure_camera(scene)
                _reset_queued_resolve_pipeline(state_module)

                create_result = bpy.ops.planetka.add_earth()
                if "FINISHED" not in create_result:
                    raise RuntimeError(f"Create Earth failed engine={engine} account={email}: {create_result}")
                _drain_resolve_pipeline(state_module, timeout_sec=30.0)

                props = scene.planetka
                props.auto_resolve = False
                props.show_earth_preview = True

                # Commercial account global Full Quality checks.
                if plan == "commercial":
                    _set_navigation(props, state_module, MILAN["lat"], MILAN["lon"], 30.0, heading_deg=12.0, tilt_deg=55.0, roll_deg=2.0)
                    props.texture_quality_mode = "FULL"
                    full_result = _resolve_now(state_module=state_module)
                    entry["checks"].append({
                        "name": "commercial_milan_full_allowed",
                        "passed": "FINISHED" in full_result,
                        "result": list(full_result),
                    })
                    milan_full_path = os.path.join(render_dir, f"{session_prefix}_{engine.lower()}_commercial_milan_full.png")
                    _render_still(scene, milan_full_path)
                    entry["renders"].append(milan_full_path)
                else:
                    entry["checks"].append({
                        "name": "non_commercial_global_full_checks_skipped",
                        "passed": True,
                    })

                # Global sample stills at 30 km using the best allowed mode per tier.
                props.texture_quality_mode = "FULL" if plan == "commercial" else ("BALANCED" if plan == "personal" else "PREVIEW")
                sample_quality = str(props.texture_quality_mode).lower()
                for city in (AUCKLAND, CHRISTCHURCH, WELLINGTON):
                    _set_navigation(
                        props,
                        state_module,
                        city["lat"],
                        city["lon"],
                        30.0,
                        heading_deg=rng.uniform(-20, 20),
                        tilt_deg=50.0,
                        roll_deg=rng.uniform(-5, 5),
                    )
                    result = _resolve_now(state_module=state_module)
                    if "FINISHED" not in result:
                        raise RuntimeError(f"{plan} sample resolve failed for {city['name']} ({engine}): {result}")
                    out_path = os.path.join(
                        render_dir,
                        f"{session_prefix}_{engine.lower()}_{plan}_{city['name'].lower().replace(' ', '_')}_30km_{sample_quality}.png",
                    )
                    _render_still(scene, out_path)
                    entry["renders"].append(out_path)
                entry["animation_frames"] = 0

                # Commercial-only 100 random place renders in FULL quality
                if plan == "commercial":
                    sampled = rng.sample(CAPITAL_QUERIES, 100)
                    for idx, query in enumerate(sampled, start=1):
                        selected = _apply_place_search(props, geonames_module, query)
                        if not selected:
                            continue
                        altitude = rng.uniform(30.0, 200.0)
                        tilt = rng.uniform(45.0, 70.0)
                        heading = rng.uniform(-45.0, 45.0)
                        roll = rng.uniform(-15.0, 15.0)
                        props.texture_quality_mode = "FULL"
                        _set_navigation(
                            props,
                            state_module,
                            float(props.nav_latitude_deg),
                            float(props.nav_longitude_deg),
                            altitude,
                            heading_deg=heading,
                            tilt_deg=tilt,
                            roll_deg=roll,
                        )
                        result = _resolve_now(state_module=state_module)
                        if "FINISHED" not in result:
                            raise RuntimeError(f"Commercial random resolve failed idx={idx} query={query} ({engine}): {result}")
                        out_path = os.path.join(render_dir, f"{session_prefix}_{engine.lower()}_commercial_random_full_{idx:03d}.png")
                        _render_still(scene, out_path)
                        entry["renders"].append(out_path)

                report["scenarios"].append(entry)

    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        report["ok"] = False
        report["errors"].append(str(exc))
        traceback.print_exc()

    report["elapsed_sec"] = round(time.time() - started, 3)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True)

    _log(f"Report: {report_path}")
    _log(f"OK={report['ok']} elapsed={report['elapsed_sec']}s")

    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
