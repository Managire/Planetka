"""Common helpers for Planetka end-to-end Blender test scripts.

Authentication bootstrap order:
1. reuse an already-authenticated Blender profile session
2. create or refresh an anonymous Planetka install session automatically

Optional for deterministic clean-session tests:
- force a stable device id via ``PLANETKA_AUTH_DEVICE_ID`` or ``PLANETKA_DEVICE_ID``
"""

from __future__ import annotations

import addon_utils
import bpy
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS

DEFAULT_RENDER_ROOT = "/Volumes/SSDA/Renders"
DEFAULT_PLACE_QUERIES = (
    "Auckland",
    "Bratislava",
    "Cape Town",
    "Lima",
    "Reykjavik",
    "Singapore",
    "Wellington",
)
COUNTRY_HINT_BY_CITY = {
    "Auckland": "NZ",
    "Bratislava": "SK",
    "Cape Town": "ZA",
    "Lima": "PE",
    "Reykjavik": "IS",
    "Singapore": "SG",
    "Wellington": "NZ",
}


class E2EError(RuntimeError):
    pass


def log(tag, message):
    print(f"{tag} {message}", flush=True)


def unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def timestamp_slug():
    return time.strftime("%Y%m%d_%H%M%S")


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, default=str)


def output_root():
    return Path(str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_ROOT).strip())


def output_session(prefix):
    root = output_root()
    root.mkdir(parents=True, exist_ok=True)
    session_dir = root / f"{prefix}_{timestamp_slug()}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def addon_root():
    return _REPO_ROOT


def enable_module(required_planetka_attr="add_earth"):
    candidates = unique(
        [
            os.environ.get("PLANETKA_MODULE"),
            "bl_ext.user_default.Planetka",
            "bl_ext.user_default.planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, required_planetka_attr):
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue

    parent_dir = os.path.dirname(_REPO_ROOT)
    package_name = os.path.basename(_REPO_ROOT)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
        module = importlib.import_module(package_name)
        if hasattr(module, "register"):
            try:
                module.unregister()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            module.register()
        if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, required_planetka_attr):
            return package_name
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    raise E2EError("Could not enable Planetka addon module.")


def import_submodule(base_module_name, submodule_name):
    candidates = unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.Planetka.{submodule_name}",
            f"bl_ext.user_default.planetka.{submodule_name}",
            f"Planetka.{submodule_name}",
            f"planetka.{submodule_name}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    raise E2EError(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _load_auth_payload(path):
    target = str(path or "").strip()
    if not target:
        return None
    if not os.path.isfile(target):
        raise E2EError(f"Auth payload file not found: {target}")
    with open(target, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise E2EError("Auth payload is not a JSON object.")
    return payload


def _parse_bool_like(value):
    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return False


def ensure_authenticated(auth_module, prefs, payload_path="", api_token="", api_token_path=""):
    del payload_path, api_token, api_token_path
    if not auth_module.is_authenticated(prefs):
        auth_module.ensure_authenticated_session(prefs)
    return {
        "bootstrap": "anonymous",
        "email": str(getattr(prefs, "auth_email", "") or "").strip(),
        "licence_code": str(auth_module.get_licence_code(prefs) or "").strip(),
        "login_state": str(getattr(prefs, "auth_login_state", "") or "").strip(),
    }

def ensure_camera(scene, name="Planetka E2E Camera"):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if getattr(obj, "type", None) == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new(name)
    camera_obj = bpy.data.objects.new(name, camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def purge_planetka_data():
    for obj in list(bpy.data.objects):
        if str(getattr(obj, "name", "")).startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for coll in list(bpy.data.collections):
        coll_name = str(getattr(coll, "name", "") or "")
        if not (coll_name.startswith("Planetka") or coll_name == "Collection Planetka"):
            continue
        for scene in bpy.data.scenes:
            try:
                if coll in scene.collection.children:
                    scene.collection.children.unlink(coll)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        try:
            bpy.data.collections.remove(coll)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

    for material in list(bpy.data.materials):
        if str(getattr(material, "name", "")).startswith("Planetka"):
            try:
                bpy.data.materials.remove(material, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for mesh in list(bpy.data.meshes):
        if str(getattr(mesh, "name", "")).startswith("Planetka"):
            try:
                bpy.data.meshes.remove(mesh, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for node_group in list(bpy.data.node_groups):
        if str(getattr(node_group, "name", "")).startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for image in list(bpy.data.images):
        try:
            name = str(getattr(image, "name", "") or "")
            filepath = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").lower()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
        looks_planetka = (
            name.startswith(("Planetka", "S2_", "EL_", "WT_", "PO_"))
            or "planetka" in name.lower()
            or "/s2/" in filepath
            or "/el/" in filepath
            or "/wt/" in filepath
            or "/po/" in filepath
            or "fallback images" in filepath
        )
        if not looks_planetka:
            continue
        try:
            bpy.data.images.remove(image, do_unlink=True)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass


def ensure_standard_world(scene, name="Planetka E2E World"):
    world = getattr(scene, "world", None)
    if world is None:
        world = bpy.data.worlds.new(name=name)
        scene.world = world
    node_tree = getattr(world, "node_tree", None)
    nodes = getattr(node_tree, "nodes", None) if node_tree is not None else None
    if nodes is None:
        try:
            world.color = (0.0, 0.0, 0.0)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        return world
    background = nodes.get("Background")
    output = nodes.get("World Output")
    if background is None:
        background = nodes.new("ShaderNodeBackground")
        background.location = (0.0, 0.0)
    if output is None:
        output = nodes.new("ShaderNodeOutputWorld")
        output.location = (200.0, 0.0)
    links = getattr(node_tree, "links", None)
    if links is not None and not any(link.to_node == output for link in links):
        try:
            links.new(background.outputs[0], output.inputs[0])
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
    return world


def wait_for_geonames_ready(geonames_module, timeout_sec=240.0):
    started = time.time()
    while True:
        geonames_module.load_geonames_database()
        status = str(geonames_module.get_search_status() or "")
        if status == "ready":
            return
        if status == "error":
            raise E2EError(f"GeoNames index failed: {geonames_module.get_search_status_text()}")
        if (time.time() - started) >= float(timeout_sec):
            raise E2EError(f"GeoNames index did not reach ready state within {timeout_sec:.0f}s (status={status}).")
        time.sleep(0.5)


def pick_place_display(geonames_module, query_text, country_hint=None):
    options = geonames_module.search_places(query_text, max_results=20)
    if not options:
        raise E2EError(f"Place Search returned no results for '{query_text}'.")
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


def search_place(props, state_module, geonames_module, query_text, country_hint=None, wait_sec=5.0):
    display_name = pick_place_display(geonames_module, query_text, country_hint=country_hint)
    props.nav_city_search = display_name
    deadline = time.time() + float(max(0.5, wait_sec))
    last_selected = ""
    while time.time() < deadline:
        try:
            bpy.context.view_layer.update()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        last_selected = str(getattr(props, "nav_city_selected_name", "") or "").strip()
        if last_selected:
            return last_selected
        time.sleep(0.05)
    return display_name


def set_navigation(props, state_module, **values):
    state_module.suspend_navigation_shot_updates()
    try:
        for key, value in values.items():
            if hasattr(props, key):
                setattr(props, key, value)
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)


def find_view3d_override(context):
    wm = getattr(context, "window_manager", None)
    windows = tuple(getattr(wm, "windows", ()) or ()) if wm is not None else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if str(getattr(area, "type", "")) != "VIEW_3D":
                continue
            regions = tuple(getattr(area, "regions", ()) or ())
            spaces = tuple(getattr(area, "spaces", ()) or ())
            region = next((r for r in regions if str(getattr(r, "type", "")) == "WINDOW"), None)
            space = next((s for s in spaces if str(getattr(s, "type", "")) == "VIEW_3D"), None)
            region_data = getattr(space, "region_3d", None) if space is not None else None
            if region is None or space is None or region_data is None:
                continue
            return {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
                "space_data": space,
                "region_data": region_data,
                "scene": getattr(context, "scene", None),
                "view_layer": getattr(context, "view_layer", None),
            }
    return None


def get_runtime_status(state_module, scene):
    runtime_fn = getattr(state_module, "get_resolve_runtime_status", None)
    if not callable(runtime_fn):
        return {}
    try:
        return dict(runtime_fn(scene) or {})
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return {}


def read_scene_last_resolve_error(scene):
    if scene is None:
        return ""
    try:
        return str(scene.get("planetka_last_resolve_error", "") or "").strip()
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""


def drain_queued_resolve(state_module, scene, timeout_sec=60.0, sleep_sec=0.05):
    runtime_fn = getattr(state_module, "get_resolve_runtime_status", None)
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
    started = time.monotonic()
    last_status = {}
    baseline_error = read_scene_last_resolve_error(scene)
    while True:
        if callable(pump_fn):
            try:
                pump_fn()
            except TOOL_RECOVERABLE_EXCEPTIONS as exc:
                raise E2EError(f"Queued resolve pump raised an exception: {exc}") from exc
        if callable(runtime_fn):
            try:
                last_status = dict(runtime_fn(scene) or {})
            except TOOL_RECOVERABLE_EXCEPTIONS:
                last_status = {}
        running = bool(last_status.get("running", False))
        pending_count = int(last_status.get("pending_count", 0) or 0)
        code = str(last_status.get("code", "") or "")
        scene_error = read_scene_last_resolve_error(scene)
        if scene_error and scene_error != baseline_error:
            if callable(stop_fn):
                try:
                    stop_fn()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
            raise E2EError(f"Queued resolve failed: {scene_error}")
        if not running and pending_count <= 0 and code in {"", "IDLE", "MONITORING"}:
            return last_status
        if (time.monotonic() - started) > float(timeout_sec):
            if callable(stop_fn):
                try:
                    stop_fn()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
            raise E2EError(f"Queued resolve did not settle in time: {last_status}")
        time.sleep(float(max(0.01, sleep_sec)))


def create_earth_and_wait(state_module, scene):
    result = bpy.ops.planetka.add_earth()
    if "FINISHED" not in result:
        raise E2EError(f"Create Earth failed: {result}")
    return drain_queued_resolve(state_module, scene, timeout_sec=90.0)


def resolve_textures(state_module, scene, *, scope_mode="CAMERA", texture_quality_mode=None, defer_download=False, tiles_override_json=""):
    kwargs = {
        "scope_mode": str(scope_mode or "CAMERA"),
        "defer_download": bool(defer_download),
    }
    if texture_quality_mode:
        kwargs["texture_quality_mode_override"] = str(texture_quality_mode)
    if tiles_override_json:
        kwargs["tiles_override_json"] = str(tiles_override_json)
    result = bpy.ops.planetka.load_textures(**kwargs)
    if "FINISHED" not in result:
        raise E2EError(f"Resolve failed: {result}")
    drain_queued_resolve(state_module, scene, timeout_sec=120.0)
    return list(result)


def configure_eevee(scene):
    available = []
    try:
        available = list(scene.render.bl_rna.properties["engine"].enum_items.keys())
    except TOOL_RECOVERABLE_EXCEPTIONS:
        available = []
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "EEVEE"):
        if candidate in available:
            scene.render.engine = candidate
            return candidate
    raise E2EError("EEVEE engine is unavailable in this Blender build.")


def configure_cycles(scene):
    available = []
    try:
        available = list(scene.render.bl_rna.properties["engine"].enum_items.keys())
    except TOOL_RECOVERABLE_EXCEPTIONS:
        available = []
    if "CYCLES" not in available:
        raise E2EError("Cycles engine is unavailable in this Blender build.")
    scene.render.engine = "CYCLES"

    backend_selected = ""
    gpu_enabled = False
    devices_used = []
    try:
        prefs = bpy.context.preferences
        cycles_addon = prefs.addons.get("cycles")
        if cycles_addon and hasattr(cycles_addon, "preferences"):
            cprefs = cycles_addon.preferences
            for backend in ("METAL", "CUDA", "OPTIX", "HIP", "ONEAPI"):
                try:
                    cprefs.compute_device_type = backend
                    cprefs.get_devices()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    continue
                devices = list(getattr(cprefs, "devices", []))
                non_cpu = [d for d in devices if str(getattr(d, "type", "")).upper() != "CPU"]
                if non_cpu:
                    for device in devices:
                        try:
                            device.use = True
                        except TOOL_RECOVERABLE_EXCEPTIONS:
                            pass
                    backend_selected = backend
                    gpu_enabled = True
                    devices_used = [str(getattr(d, "name", "GPU")) for d in non_cpu]
                    break
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    try:
        scene.cycles.device = "GPU" if gpu_enabled else "CPU"
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    return {
        "engine": "CYCLES",
        "gpu_enabled": bool(gpu_enabled),
        "backend": backend_selected,
        "devices": devices_used,
        "scene_cycles_device": str(getattr(scene.cycles, "device", "")),
    }


def configure_png_output(scene, *, output_prefix, resolution_x, resolution_y, resolution_percentage=100):
    scene.render.resolution_x = int(resolution_x)
    scene.render.resolution_y = int(resolution_y)
    scene.render.resolution_percentage = int(resolution_percentage)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_prefix)


def render_still(scene, output_path):
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(target)
    try:
        result = bpy.ops.render.render(write_still=True, use_viewport=False)
    except TypeError:
        result = bpy.ops.render.render(write_still=True)
    if "FINISHED" not in result:
        raise E2EError(f"Still render failed: {result}")
    return str(target)


def render_animation(scene, *, output_prefix, frame_start, frame_end):
    scene.frame_start = int(frame_start)
    scene.frame_end = int(frame_end)
    scene.render.filepath = str(output_prefix)
    try:
        result = bpy.ops.render.render(animation=True, use_viewport=False)
    except TypeError:
        result = bpy.ops.render.render(animation=True)
    if "FINISHED" not in result:
        raise E2EError(f"Animation render failed: {result}")
    return list(result)


def list_pngs(directory):
    return sorted(str(path) for path in Path(directory).glob("*.png"))


def _safe_pixel_value(pixels, index):
    try:
        return float(pixels[index])
    except (IndexError, TypeError, ValueError):
        return 0.0


def _analyze_rgba_metrics(width, height, sampler):
    pixel_count = max(1, int(width) * int(height))
    step = max(1, pixel_count // 30000)
    sampled = 0
    black_count = 0
    pink_count = 0
    lum_sum = 0.0
    max_lum = 0.0
    for i in range(0, pixel_count, step):
        r, g, b = sampler(i)
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
        "width": int(width),
        "height": int(height),
        "samples": int(sampled),
        "avg_luminance": round(avg_lum, 6),
        "max_luminance": round(max_lum, 6),
        "black_ratio": round(black_ratio, 6),
        "pink_ratio": round(pink_ratio, 6),
        "mostly_black": bool(mostly_black),
        "pink_corrupt": bool(pink_corrupt),
    }


def _analyze_render_image_with_pil(path):
    from PIL import Image  # type: ignore

    image_path = Path(path)
    with Image.open(image_path) as handle:
        rgba = handle.convert("RGBA")
        width, height = rgba.size
        pixels = rgba.load()

        def _sampler(index):
            x = int(index % width)
            y = int(index // width)
            r, g, b, _a = pixels[x, y]
            return (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0)

        metrics = _analyze_rgba_metrics(width, height, _sampler)
    metrics["path"] = str(image_path)
    return metrics


def _analyze_render_image_external(path):
    python_bin = shutil.which("python3") or sys.executable
    script = r"""
import json, sys
from pathlib import Path
from PIL import Image

path = Path(sys.argv[1])
with Image.open(path) as handle:
    rgba = handle.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    pixel_count = max(1, width * height)
    step = max(1, pixel_count // 30000)
    sampled = 0
    black_count = 0
    pink_count = 0
    lum_sum = 0.0
    max_lum = 0.0
    for i in range(0, pixel_count, step):
        x = int(i % width)
        y = int(i // width)
        r8, g8, b8, _a = pixels[x, y]
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
    }))
"""
    result = subprocess.run(
        [python_bin, "-c", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if int(result.returncode) != 0:
        stderr = str(result.stderr or "").strip()
        raise E2EError(f"External image analysis failed for {path}: {stderr or result.returncode}")
    payload = json.loads(str(result.stdout or "{}").strip() or "{}")
    if not isinstance(payload, dict):
        raise E2EError(f"External image analysis returned invalid JSON for {path}")
    return payload


def analyze_render_image(path):
    try:
        return _analyze_render_image_with_pil(path)
    except Exception:
        return _analyze_render_image_external(path)


def analyze_png_directory(directory, max_samples=6):
    pngs = list_pngs(directory)
    if not pngs:
        raise E2EError(f"No PNG renders found in {directory}")
    if len(pngs) <= int(max_samples):
        sample_paths = pngs
    else:
        sample_paths = []
        for idx in range(int(max_samples)):
            pos = int(round((len(pngs) - 1) * (idx / max(1, int(max_samples) - 1))))
            sample_paths.append(pngs[pos])
        sample_paths = unique(sample_paths)
    analyses = [analyze_render_image(path) for path in sample_paths]
    return {
        "frame_count": len(pngs),
        "samples": analyses,
        "has_mostly_black": any(item.get("mostly_black") for item in analyses),
        "has_pink_corrupt": any(item.get("pink_corrupt") for item in analyses),
        "first_frame": pngs[0],
        "last_frame": pngs[-1],
    }


def scene_health_operator_available():
    return hasattr(getattr(bpy.ops, "planetka", None), "scene_health_check")
