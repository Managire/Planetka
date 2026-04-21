"""
Planetka end-to-end capitals render test for Cycles.

Flow:
1. Enable addon in a fresh Blender process.
2. Authenticate (existing prefs session or PLANETKA_AUTH_PAYLOAD override).
3. Create Earth.
4. Set render engine to Cycles.
5. For 50 random capital-city queries:
   - Place Search query
   - Random altitude [30, 3000] km
   - Random tilt [25, 75] deg
   - Resolve from Camera scope
   - Render PNG
   - Validate output is not mostly-black and not pink-texture corrupted

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_capitals_cycles_e2e_test.py

Optional env:
  PLANETKA_MODULE=<module-name>
  PLANETKA_AUTH_PAYLOAD=/absolute/path/to/auth_verify_payload.json
  PLANETKA_RENDER_DIR=/Volumes/SSDA/Renders
  PLANETKA_CAPITAL_COUNT=50
  PLANETKA_CAPITAL_SEED=20260326
"""

import importlib
import json
import math
import os
import random
import sys
import time
import traceback

import addon_utils
import bpy


TAG = "[Planetka Capitals E2E]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"
DEFAULT_COUNT = 50
DEFAULT_SEED = 20260326

# Broad pool; script samples requested count.
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

# Country-code hints for ambiguous city names during Place Search.
COUNTRY_HINT_BY_CITY = {
    "Sofia": "BG",
    "Washington": "US",
    "London": "GB",
    "Vienna": "AT",
    "Bratislava": "SK",
    "Rome": "IT",
    "Cairo": "EG",
    "Accra": "GH",
    "Maputo": "MZ",
    "Pretoria": "ZA",
    "Cape Town": "ZA",
    "Canberra": "AU",
    "Ottawa": "CA",
    "Quito": "EC",
    "Santiago": "CL",
    "La Paz": "BO",
    "Hanoi": "VN",
    "Tbilisi": "GE",
    "Riyadh": "SA",
    "Baku": "AZ",
}


def _log(message):
    print(f"{TAG} {message}")


def _fail(message):
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _assert(condition, message):
    if not condition:
        _fail(message)


def _addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _enable_module():
    candidates = _unique(
        [
            os.environ.get("PLANETKA_MODULE"),
            "bl_ext.user_default.Planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except Exception:
            continue

    addon_root = _addon_root()
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
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
    except Exception:
        pass
    return None


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.Planetka.{submodule_name}",
            f"Planetka.{submodule_name}",
            f"planetka.{submodule_name}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except Exception:
            continue
    _fail(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _load_auth_payload(path):
    if not path:
        return None
    if not os.path.isfile(path):
        _fail(f"Auth payload file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
        _fail("Auth payload is invalid (missing access_token/refresh_token).")
    return payload


def _remove_existing_planetka_objects():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new("Planetka E2E Camera")
    camera_obj = bpy.data.objects.new("Planetka E2E Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _configure_cycles_gpu(scene):
    backend_selected = ""
    gpu_enabled = False
    gpu_devices = []

    try:
        prefs = bpy.context.preferences
        cycles_addon = prefs.addons.get("cycles")
        if cycles_addon and hasattr(cycles_addon, "preferences"):
            cprefs = cycles_addon.preferences
            for backend in ("METAL", "CUDA", "OPTIX", "HIP", "ONEAPI"):
                try:
                    cprefs.compute_device_type = backend
                    cprefs.get_devices()
                except Exception:
                    continue
                devices = list(getattr(cprefs, "devices", []))
                non_cpu = [d for d in devices if str(getattr(d, "type", "")).upper() != "CPU"]
                if non_cpu:
                    for device in devices:
                        try:
                            device.use = True
                        except Exception:
                            pass
                    backend_selected = backend
                    gpu_enabled = True
                    gpu_devices = [str(getattr(d, "name", "GPU")) for d in non_cpu]
                    break
    except Exception:
        pass

    try:
        scene.cycles.device = "GPU" if gpu_enabled else "CPU"
    except Exception:
        pass

    return {
        "gpu_enabled": bool(gpu_enabled),
        "backend": backend_selected,
        "devices": gpu_devices,
        "scene_cycles_device": str(getattr(scene.cycles, "device", "")),
    }


def _set_nav_values(props, state_module, altitude_km, tilt_deg, azimuth_deg, roll_deg):
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_altitude_km = float(altitude_km)
        props.nav_tilt_deg = float(tilt_deg)
        props.nav_azimuth_deg = float(azimuth_deg)
        props.nav_roll_deg = float(roll_deg)
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)


def _pick_place_display(geonames_module, query_text, country_hint=None):
    options = geonames_module.search_places(query_text, max_results=20)
    if not options:
        return None
    hint = str(country_hint or "").strip().upper()
    if hint:
        for display_name, _place_id in options:
            normalized = str(display_name or "").strip().upper()
            if normalized.endswith(f", {hint}") or f", {hint}," in normalized:
                return str(display_name)
    lower_query = str(query_text).strip().lower()
    for display_name, _place_id in options:
        if str(display_name).strip().lower().startswith(lower_query):
            return str(display_name)
    return str(options[0][0])


def _analyze_render_image(path):
    # Returns a dict with aggregate brightness and pink ratios from sampled pixels.
    img = bpy.data.images.load(path, check_existing=False)
    try:
        width = int(img.size[0])
        height = int(img.size[1])
        pixel_count = max(1, width * height)
        sample_target = 30000
        step = max(1, pixel_count // sample_target)

        sampled = 0
        black_count = 0
        pink_count = 0
        lum_sum = 0.0
        max_lum = 0.0

        pixels = img.pixels
        for i in range(0, pixel_count, step):
            base = i * 4
            r = float(pixels[base])
            g = float(pixels[base + 1])
            b = float(pixels[base + 2])
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
        return {
            "width": width,
            "height": height,
            "samples": sampled,
            "avg_luminance": round(avg_lum, 6),
            "max_luminance": round(max_lum, 6),
            "black_ratio": round(black_ratio, 6),
            "pink_ratio": round(pink_ratio, 6),
            "mostly_black": bool(mostly_black),
            "pink_corrupt": bool(pink_corrupt),
        }
    finally:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass


def main():
    started_at = time.time()
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    run_count = max(1, int(os.environ.get("PLANETKA_CAPITAL_COUNT") or str(DEFAULT_COUNT)))
    run_seed = int(os.environ.get("PLANETKA_CAPITAL_SEED") or str(DEFAULT_SEED))
    auth_payload_path = str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip()

    if run_count > len(CAPITAL_QUERIES):
        _fail(f"Requested count {run_count} exceeds available capital pool ({len(CAPITAL_QUERIES)}).")

    os.makedirs(render_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(render_dir, f"planetka_capitals_cycles_e2e_report_{ts}.json")
    render_prefix = f"planetka_capitals_{ts}"

    rng = random.Random(run_seed)
    selected_capitals = rng.sample(CAPITAL_QUERIES, run_count)

    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        auth_module = _import_submodule(base_module_name, "auth")
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        geonames_module = _import_submodule(base_module_name, "geonames_db")
        state_module = _import_submodule(base_module_name, "state")
        diagnostics = _import_submodule(base_module_name, "diagnostics")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        auth_payload = _load_auth_payload(auth_payload_path)
        if auth_payload:
            auth_module._apply_auth_payload(prefs, auth_payload, login_state="authenticated")  # noqa: SLF001

        _assert(auth_module.is_authenticated(prefs), "Planetka account is not authenticated.")
        auth_module.sync_account_profile(prefs)

        scene = bpy.context.scene
        _ensure_active_camera(scene)
        _remove_existing_planetka_objects()

        prefs.texture_base_path = "planetka-remote"
        props = scene.planetka
        props.auto_resolve = False
        props.texture_quality_mode = "HALF"
        props.show_earth_preview = False

        # Keep E2E coverage broad (50 locations) by using a lightweight render preset.
        scene.render.resolution_x = 960
        scene.render.resolution_y = 540
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = False
        scene.render.use_simplify = True
        scene.cycles.samples = 16
        scene.cycles.preview_samples = 8
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = True

        create_result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in create_result, f"Create Earth failed: {create_result}")

        scene.render.engine = "CYCLES"
        _assert(str(scene.render.engine) == "CYCLES", f"Render engine is not CYCLES after switch: {scene.render.engine}")
        gpu_info = _configure_cycles_gpu(scene)
        _assert(bool(gpu_info.get("gpu_enabled")), "Cycles GPU is not available/enabled on this machine.")
        _assert(str(gpu_info.get("scene_cycles_device")) == "GPU", "Cycles scene device is not set to GPU.")
        _log(
            f"Cycles GPU enabled: backend={gpu_info.get('backend')} "
            f"devices={gpu_info.get('devices')}"
        )

        # Ensure geonames index is loaded before loop.
        _assert(bool(geonames_module.load_geonames_database()), "GeoNames database is not available.")

        failures = []
        cases = []
        for index, capital_query in enumerate(selected_capitals, start=1):
            case_started = time.perf_counter()
            country_hint = COUNTRY_HINT_BY_CITY.get(capital_query)
            place_display = _pick_place_display(geonames_module, capital_query, country_hint=country_hint)
            if not place_display:
                failures.append(f"Case {index:02d} ({capital_query}): Place search returned no results.")
                continue

            props.nav_city_search = place_display
            selected_name = str(getattr(props, "nav_city_selected_name", "") or "")
            if not selected_name:
                failures.append(f"Case {index:02d} ({capital_query}): Place selection not applied.")
                continue

            altitude = rng.uniform(30.0, 3000.0)
            tilt = rng.uniform(25.0, 75.0)
            azimuth = rng.uniform(0.0, 360.0)
            roll = rng.uniform(-20.0, 20.0)
            _set_nav_values(props, state_module, altitude, tilt, azimuth, roll)

            resolve_result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
            if "FINISHED" not in resolve_result:
                failures.append(f"Case {index:02d} ({capital_query}): Resolve failed ({resolve_result}).")
                continue

            render_path = os.path.join(render_dir, f"{render_prefix}_{index:02d}.png")
            scene.render.filepath = render_path
            bpy.ops.render.render(write_still=True)

            analysis = _analyze_render_image(render_path)
            if analysis["mostly_black"]:
                failures.append(f"Case {index:02d} ({capital_query}): Render is mostly black ({analysis}).")
            if analysis["pink_corrupt"]:
                failures.append(f"Case {index:02d} ({capital_query}): Render has pink corruption ({analysis}).")

            diag = diagnostics.read_diagnostics(scene)
            case_payload = {
                "case": index,
                "capital_query": capital_query,
                "country_hint": country_hint,
                "selected_place": selected_name,
                "longitude_deg": round(float(getattr(props, "nav_longitude_deg", 0.0)), 6),
                "latitude_deg": round(float(getattr(props, "nav_latitude_deg", 0.0)), 6),
                "altitude_km": round(float(altitude), 3),
                "tilt_deg": round(float(tilt), 3),
                "azimuth_deg": round(float(azimuth), 3),
                "roll_deg": round(float(roll), 3),
                "render_path": render_path,
                "resolve_tile_count": diag.get("last_tile_count"),
                "resolve_downloaded_mb": diag.get("resolve_downloaded_mb"),
                "resolve_download_ms": diag.get("resolve_download_ms"),
                "image_analysis": analysis,
                "elapsed_ms": round((time.perf_counter() - case_started) * 1000.0, 3),
            }
            cases.append(case_payload)
            _log(
                f"Case {index:02d}/{run_count}: {capital_query} -> {selected_name}, "
                f"alt={altitude:.1f}km tilt={tilt:.1f}deg, render={render_path}"
            )

        report = {
            "ok": len(failures) == 0,
            "seed": run_seed,
            "count_requested": run_count,
            "count_completed": len(cases),
            "render_dir": render_dir,
            "report_path": report_path,
            "gpu_info": gpu_info,
            "selected_capitals": selected_capitals,
            "failures": failures,
            "elapsed_sec": round(time.time() - started_at, 3),
            "cases": cases,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=True)

        if failures:
            _log("Completed with failures:")
            for line in failures:
                _log(f"- {line}")
            _log(f"Report: {report_path}")
            raise SystemExit(2)

        _log("PASS: all renders validated (no mostly-black and no pink corruption).")
        _log(f"Report: {report_path}")
    except SystemExit:
        raise
    except Exception as exc:
        _log(f"Unhandled error: {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
