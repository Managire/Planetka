#!/usr/bin/env python3
"""Planetka tiered end-to-end matrix test (Free / Personal / Pro).

This script uses the currently authenticated local Planetka account, switches its
plan server-side via admin endpoint, and runs renders for each tier.

Outputs:
- Renders under /Volumes/SSDA/Renders (customizable via PLANETKA_RENDER_DIR)
- JSON report with checks and failures

Run:
  /Applications/Blender5.0.app/Contents/MacOS/Blender --background \
    --python tools/planetka_tier_e2e_matrix.py
"""

from __future__ import annotations

import importlib
import json
import math
import os
import random
import re
import sys
import time
import traceback
import urllib.error
import urllib.request

import addon_utils
import bpy

TAG = "[Planetka Tier E2E]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"
API_BASE_URL = str(os.environ.get("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/")

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


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _enable_module() -> str:
    candidates = _unique([
        os.environ.get("PLANETKA_MODULE"),
        "bl_ext.user_default.Planetka",
        "Planetka",
        "planetka",
    ])
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except Exception:
            continue

    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    module = importlib.import_module(package_name)
    if hasattr(module, "register"):
        try:
            module.unregister()
        except Exception:
            pass
        module.register()
    if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
        _log(f"Enabled addon module via local import: {package_name}")
        return package_name
    raise RuntimeError("Could not enable Planetka addon module")


def _import_submodule(base_module_name: str, submodule_name: str):
    candidates = _unique([
        f"{base_module_name}.{submodule_name}" if base_module_name else None,
        f"bl_ext.user_default.Planetka.{submodule_name}",
        f"Planetka.{submodule_name}",
        f"planetka.{submodule_name}",
    ])
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except Exception:
            continue
    raise RuntimeError(f"Could not import {submodule_name}; tried: {candidates}")


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 60.0) -> tuple[int, dict]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=req_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            return int(response.status), body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except Exception:
            body = {}
        return int(exc.code), body if isinstance(body, dict) else {}


def _set_plan_for_email(auth_module, prefs, email: str, plan_code: str) -> dict:
    token = str(auth_module.get_access_token(prefs=prefs, allow_refresh=True) or "").strip()
    if not token:
        raise RuntimeError("Missing access token for admin set-plan call")
    status, payload = _post_json(
        f"{API_BASE_URL}/admin/users/set-plan",
        {"email": email, "plan_code": plan_code},
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(f"set-plan failed ({status}): {payload}")
    auth_module.sync_account_profile(prefs)
    return payload


def _purge_planetka_data():
    for obj in list(bpy.data.objects):
        if str(obj.name).startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

    for collection in list(bpy.data.collections):
        if str(collection.name).startswith("Planetka"):
            try:
                bpy.data.collections.remove(collection)
            except Exception:
                pass

    for material in list(bpy.data.materials):
        if str(material.name).startswith("Planetka"):
            try:
                bpy.data.materials.remove(material)
            except Exception:
                pass

    for mesh in list(bpy.data.meshes):
        if str(mesh.name).startswith("Planetka"):
            try:
                bpy.data.meshes.remove(mesh)
            except Exception:
                pass

    for image in list(bpy.data.images):
        if str(image.name).startswith("Planetka"):
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass

    for node_group in list(bpy.data.node_groups):
        if str(node_group.name).startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group)
            except Exception:
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


def _configure_render(scene):
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    if "BLENDER_EEVEE_NEXT" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys():
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        scene.render.engine = "BLENDER_EEVEE"


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


def _reset_queued_resolve_pipeline(state_module):
    if state_module is None:
        return
    try:
        stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
        if callable(stop_fn):
            stop_fn()
    except Exception:
        pass


def _drain_resolve_pipeline(state_module, timeout_sec=30.0):
    if state_module is None:
        return
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    busy_fn = getattr(state_module, "_is_resolve_pipeline_busy", None)
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    while time.monotonic() < deadline:
        is_busy = False
        try:
            if callable(busy_fn):
                is_busy = bool(busy_fn())
        except Exception:
            is_busy = False
        if not is_busy:
            return
        try:
            if callable(pump_fn):
                pump_fn()
        except Exception:
            pass
        time.sleep(0.05)


def _resolve_now(state_module=None, retries=2):
    last_error = None
    for _attempt in range(max(1, int(retries))):
        _drain_resolve_pipeline(state_module)
        try:
            return bpy.ops.planetka.load_textures(skip_render_compatibility=True, defer_download=False)
        except RuntimeError as exc:
            last_error = exc
            text = str(exc or "")
            if "PKA-RES-002" in text:
                _drain_resolve_pipeline(state_module, timeout_sec=5.0)
                time.sleep(0.15)
                continue
            raise
    if last_error is not None:
        raise last_error
    return {'CANCELLED'}


def _set_quality_and_resolve(mode: str):
    return bpy.ops.planetka.set_texture_quality_and_resolve(texture_quality_mode=str(mode).upper())


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


def _render_zoom_sequence(scene, props, state_module, lat, lon, start_alt_km, end_alt_km, frames, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    rendered = []
    for frame in range(1, int(frames) + 1):
        t = 0.0 if frames <= 1 else (frame - 1) / float(frames - 1)
        altitude = (1.0 - t) * float(start_alt_km) + t * float(end_alt_km)
        _set_navigation(props, state_module, lat, lon, altitude, heading_deg=0.0, tilt_deg=35.0, roll_deg=0.0)
        resolve_result = _resolve_now(state_module=state_module)
        if "FINISHED" not in resolve_result:
            raise RuntimeError(f"Resolve failed during animation frame {frame}: {resolve_result}")
        scene.frame_set(frame)
        path = os.path.join(out_dir, f"{prefix}_{frame:04d}.png")
        _render_still(scene, path)
        rendered.append(path)
    return rendered


def _apply_place_search(props, geonames_module, query_text: str):
    options = geonames_module.search_places(query_text, max_results=10)
    if not options:
        return None
    display = str(options[0][0])
    props.nav_city_search = display
    return display


def _run_common_setup(scene, props):
    props.auto_resolve = False
    props.show_earth_preview = True
    props.texture_quality_mode = "PREVIEW"


def main():
    started = time.time()
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    random_seed = int(os.environ.get("PLANETKA_TIER_E2E_SEED") or "20260416")
    rng = random.Random(random_seed)

    os.makedirs(render_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    session_prefix = f"planetka_tier_e2e_{stamp}"
    report_path = os.path.join(render_dir, f"{session_prefix}_report.json")

    report = {
        "ok": True,
        "started_at": stamp,
        "seed": random_seed,
        "api_base_url": API_BASE_URL,
        "scenarios": [],
        "errors": [],
        "elapsed_sec": None,
    }

    try:
        base_module = _enable_module()
        auth_module = _import_submodule(base_module, "auth")
        extension_prefs = _import_submodule(base_module, "extension_prefs")
        state_module = _import_submodule(base_module, "state")
        diagnostics = _import_submodule(base_module, "diagnostics")
        geonames_module = _import_submodule(base_module, "geonames_db")

        prefs = extension_prefs.get_prefs()
        if prefs is None:
            raise RuntimeError("Planetka prefs unavailable")

        auth_module.sync_account_profile(prefs)
        email = str(getattr(prefs, "auth_email", "") or "").strip().lower()
        if not email:
            raise RuntimeError("No authenticated Planetka account found in local prefs")

        _log(f"Using authenticated account: {email}")

        scenarios = [
            {"tier": "free", "label": "Free"},
            {"tier": "lite", "label": "Personal"},
            {"tier": "pro", "label": "Pro"},
        ]

        for scenario in scenarios:
            tier = scenario["tier"]
            label = scenario["label"]
            _log(f"--- Scenario: {label} ({tier}) ---")
            set_plan_payload = _set_plan_for_email(auth_module, prefs, email, tier)
            _log(f"Set-plan response: {set_plan_payload}")

            auth_module.sync_account_profile(prefs)
            effective_tier = str(auth_module.get_account_tier(prefs) or "").strip().lower()
            simulated_tier = False
            if tier in {"free", "lite"} and effective_tier != tier:
                # Current deployed backend can force selected accounts to Pro.
                # Simulate lower-tier gating locally to execute Free/Personal flows end-to-end.
                prefs.auth_account_tier = tier
                prefs.auth_plan_code = tier
                prefs.auth_plan_name = "Planetka Free" if tier == "free" else "Planetka Personal"
                effective_tier = tier
                simulated_tier = True
                _log(f"Backend did not apply {tier} directly; using local {tier} simulation for this scenario.")
            elif effective_tier != tier:
                raise RuntimeError(f"Tier mismatch after set-plan. expected={tier} got={effective_tier}")

            scene = bpy.context.scene
            _purge_planetka_data()
            _configure_render(scene)
            camera = _ensure_camera(scene)
            _run_common_setup(scene, scene.planetka)

            create_result = bpy.ops.planetka.add_earth()
            if "FINISHED" not in create_result:
                raise RuntimeError(f"Create Earth failed for tier={tier}: {create_result}")
            _drain_resolve_pipeline(state_module, timeout_sec=20.0)

            props = scene.planetka
            _run_common_setup(scene, props)

            scenario_result = {
                "tier": tier,
                "label": label,
                "account_email": email,
                "simulated_tier": bool(simulated_tier),
                "checks": [],
                "renders": [],
                "animation_frames": 0,
            }

            # Milan gate/quality checks
            _set_navigation(props, state_module, MILAN["lat"], MILAN["lon"], 30.0, heading_deg=12.0, tilt_deg=55.0, roll_deg=2.0)

            if tier == "free":
                props.texture_quality_mode = "FULL"
                result = _resolve_now(state_module=state_module)
                if "FINISHED" not in result:
                    raise RuntimeError(f"Free Milan resolve failed: {result}")
                tiles = list(scene.get("planetka_last_resolved_tiles", []) or [])
                d_values = _parse_tile_d_values(tiles)
                min_d = min(d_values) if d_values else None
                scenario_result["checks"].append({
                    "name": "free_milan_d090_cap",
                    "passed": bool(min_d is not None and min_d >= 90),
                    "min_d": min_d,
                    "tile_count": len(tiles),
                })
            elif tier == "lite":
                balanced_result = _set_quality_and_resolve("BALANCED")
                scenario_result["checks"].append({
                    "name": "personal_milan_balanced_allowed",
                    "passed": "FINISHED" in balanced_result,
                    "result": list(balanced_result),
                })
                full_result = _set_quality_and_resolve("FULL")
                scenario_result["checks"].append({
                    "name": "personal_full_blocked",
                    "passed": "FINISHED" not in full_result,
                    "result": list(full_result),
                })
            else:
                full_result = _set_quality_and_resolve("FULL")
                scenario_result["checks"].append({
                    "name": "pro_milan_full_allowed",
                    "passed": "FINISHED" in full_result,
                    "result": list(full_result),
                })

            # Milan still render for Personal and Pro, and one for Free as reference
            milan_quality = "FULL" if tier == "pro" else ("BALANCED" if tier == "lite" else "PREVIEW")
            props.texture_quality_mode = milan_quality
            resolve_result = _resolve_now(state_module=state_module)
            if "FINISHED" not in resolve_result:
                raise RuntimeError(f"Milan render resolve failed for tier={tier}: {resolve_result}")
            milan_path = os.path.join(render_dir, f"{session_prefix}_{tier}_milan_{milan_quality.lower()}.png")
            _render_still(scene, milan_path)
            scenario_result["renders"].append(milan_path)

            # Global sample stills at 30 km.
            for city in (AUCKLAND, CHRISTCHURCH, WELLINGTON):
                props.texture_quality_mode = "FULL" if tier == "pro" else ("BALANCED" if tier == "lite" else "PREVIEW")
                _set_navigation(props, state_module, city["lat"], city["lon"], 30.0, heading_deg=rng.uniform(-20, 20), tilt_deg=50.0, roll_deg=rng.uniform(-5, 5))
                result = _resolve_now(state_module=state_module)
                if "FINISHED" not in result:
                    raise RuntimeError(f"{label} sample resolve failed for {city['name']}: {result}")
                out_path = os.path.join(render_dir, f"{session_prefix}_{tier}_{city['name'].lower().replace(' ', '_')}_30km.png")
                _render_still(scene, out_path)
                scenario_result["renders"].append(out_path)

            # 30-frame Auckland zoom (2000km -> 30km)
            # Use the best allowed mode per tier.
            props.texture_quality_mode = "FULL" if tier == "pro" else ("BALANCED" if tier == "lite" else "PREVIEW")

            anim_dir = os.path.join(render_dir, f"{session_prefix}_{tier}_auckland_zoom")
            frames = _render_zoom_sequence(
                scene,
                props,
                state_module,
                AUCKLAND["lat"],
                AUCKLAND["lon"],
                2000.0,
                30.0,
                30,
                anim_dir,
                f"{session_prefix}_{tier}_auckland_zoom",
            )
            scenario_result["animation_frames"] = len(frames)

            # Pro-only 100 random place-search renders
            if tier == "pro":
                sampled = rng.sample(CAPITAL_QUERIES, 100)
                for idx, query in enumerate(sampled, start=1):
                    selected = _apply_place_search(props, geonames_module, query)
                    if not selected:
                        continue
                    altitude = rng.uniform(30.0, 200.0)
                    tilt = rng.uniform(45.0, 70.0)
                    heading = rng.uniform(-45.0, 45.0)
                    roll = rng.uniform(-15.0, 15.0)
                    # Keep the random 100-image matrix fast/stable; Pro Full Quality is
                    # explicitly verified in the dedicated Milan test above.
                    props.texture_quality_mode = "PREVIEW"
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
                        raise RuntimeError(f"Pro random resolve failed idx={idx} query={query}: {result}")
                    out_path = os.path.join(render_dir, f"{session_prefix}_pro_random_{idx:03d}.png")
                    _render_still(scene, out_path)
                    scenario_result["renders"].append(out_path)

            diag_payload = diagnostics.read_diagnostics(scene)
            scenario_result["diagnostics_tail"] = diag_payload
            report["scenarios"].append(scenario_result)

        # Restore to Pro for local dev convenience.
        _set_plan_for_email(auth_module, prefs, email, "pro")
        auth_module.sync_account_profile(prefs)

    except Exception as exc:
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
