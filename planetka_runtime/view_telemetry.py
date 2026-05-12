import hashlib
import json
import math
import os
import threading
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_VIEW_TELEMETRY_CTX = None
_CENT = Decimal("0.01")
_FULL_PRICE_SIGNATURE_KEY = "planetka_resolve_estimate_full_price_signature"
_FULL_PRICE_PENDING_KEY = "planetka_resolve_estimate_full_price_pending"
_REGION_OFFER_PRICING_TILES_KEY = "planetka_resolve_estimate_region_offer_tiles"
_REGION_OFFERS_JSON_KEY = "planetka_region_pack_offers_json"
_REGION_OFFERS_STATUS_KEY = "planetka_region_pack_offers_status"
_REGION_OFFERS_SIGNATURE_KEY = "planetka_region_pack_offers_signature"
_REGION_OFFERS_PENDING_SIGNATURE_KEY = "planetka_region_pack_offers_pending_signature"
_REGION_OFFERS_CAMERA_SIGNATURE_KEY = "planetka_region_pack_offers_camera_signature"
_REGION_OFFERS_MESSAGE_KEY = "planetka_region_pack_offers_message"
_REGION_OFFERS_UPDATED_AT_KEY = "planetka_region_pack_offers_updated_at"
_REGION_OFFERS_LATITUDE_KEY = "planetka_region_pack_offers_latitude"
_REGION_OFFERS_LONGITUDE_KEY = "planetka_region_pack_offers_longitude"
_FULL_PRICE_CACHE_TTL_SECONDS = 300.0
_REGION_OFFERS_REFRESH_DELAY_SECONDS = 1.25
_REGION_OFFERS_STALE_DISTANCE_DEG = 4.0
_FULL_PRICE_CACHE = {}
_FULL_PRICE_IN_FLIGHT = set()
_FULL_PRICE_RESULTS = []
_FULL_PRICE_LOCK = threading.Lock()
_FULL_PRICE_APPLY_TIMER_RUNNING = False
_FULL_PRICE_GENERATION = 0
_REGION_OFFERS_IN_FLIGHT = set()
_REGION_OFFERS_RESULTS = []
_REGION_OFFERS_LOCK = threading.Lock()
_REGION_OFFERS_APPLY_TIMER_RUNNING = False
_REGION_OFFERS_GENERATION = 0


def clear_full_price_estimate_cache():
    global _FULL_PRICE_GENERATION
    with _FULL_PRICE_LOCK:
        _FULL_PRICE_CACHE.clear()
        _FULL_PRICE_GENERATION += 1


def clear_region_pack_offer_cache():
    global _REGION_OFFERS_GENERATION
    with _REGION_OFFERS_LOCK:
        _REGION_OFFERS_IN_FLIGHT.clear()
        _REGION_OFFERS_RESULTS.clear()
        _REGION_OFFERS_GENERATION += 1


def _money_round(value):
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    return float(amount.quantize(_CENT, rounding=ROUND_HALF_UP))

def _require_ctx():
    ctx = _VIEW_TELEMETRY_CTX
    if ctx is None:
        raise RuntimeError("Planetka view telemetry context is not configured.")
    return ctx


def _is_context(value):
    return hasattr(value, "deps") and hasattr(value, "state")


def _coerce_ctx(value=None):
    if _is_context(value):
        return value
    return _require_ctx()


def _safe_bpy_context(bpy_module):
    if bpy_module is None:
        return None
    try:
        return getattr(bpy_module, "context", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _safe_context_scene(bpy_module):
    context = _safe_bpy_context(bpy_module)
    if context is None:
        return None
    try:
        return getattr(context, "scene", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _safe_window_manager_from_bpy(bpy_module):
    context = _safe_bpy_context(bpy_module)
    if context is None:
        return None
    try:
        return getattr(context, "window_manager", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _safe_windows_from_manager(wm):
    if wm is None:
        return ()
    try:
        return tuple(getattr(wm, "windows", ()) or ())
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ()


def _active_view_signature_from_bpy(bpy_module):
    if bpy_module is None:
        return None
    wm = _safe_window_manager_from_bpy(bpy_module)
    if not wm:
        return None

    for window in _safe_windows_from_manager(wm):
        try:
            screen = getattr(window, "screen", None)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if not screen:
            continue
        try:
            areas = tuple(getattr(screen, "areas", ()) or ())
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        for area in areas:
            try:
                if area.type != 'VIEW_3D':
                    continue
                space = getattr(area.spaces, "active", None)
                if not space or space.type != 'VIEW_3D':
                    continue
                rv3d = getattr(space, "region_3d", None)
                if rv3d is None:
                    continue
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                region_sig = (
                    int(getattr(region, "width", 0)) if region else 0,
                    int(getattr(region, "height", 0)) if region else 0,
                )
                matrix_signature = tuple(
                    round(float(value), 6)
                    for row in rv3d.view_matrix
                    for value in row
                )
                return (
                    str(getattr(rv3d, "view_perspective", "")),
                    bool(getattr(rv3d, "is_perspective", True)),
                    round(float(getattr(space, "lens", 50.0)), 6),
                    region_sig,
                    matrix_signature,
                )
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue
    return None


def _ctx_active_view_signature(ctx):
    return _active_view_signature_from_bpy(ctx.deps.bpy)


def active_view_signature(ctx=None):
    return _ctx_active_view_signature(_coerce_ctx(ctx))


def active_camera_projection_info(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return None
    cam_data = getattr(camera, "data", None)
    if cam_data is None:
        return None

    render = getattr(scene, "render", None) if scene else None
    scale = float(getattr(render, "resolution_percentage", 100)) / 100.0 if render else 1.0
    res_x = max(1.0, float(getattr(render, "resolution_x", 1920)) * scale) if render else 1920.0
    res_y = max(1.0, float(getattr(render, "resolution_y", 1080)) * scale) if render else 1080.0
    cam_type = str(getattr(cam_data, "type", "PERSP"))

    if cam_type == "ORTHO":
        h_fov = math.radians(50.0)
        v_fov = math.radians(35.0)
        ortho_scale = float(getattr(cam_data, "ortho_scale", 1.0))
    else:
        h_fov = float(getattr(cam_data, "angle_x", math.radians(50.0)))
        v_fov = float(getattr(cam_data, "angle_y", math.radians(35.0)))
        ortho_scale = 1.0

    return {
        "camera_type": cam_type,
        "h_fov": h_fov,
        "v_fov": v_fov,
        "res_x": float(res_x),
        "res_y": float(res_y),
        "ortho_scale": float(ortho_scale),
    }


def _ctx_tag_view3d_redraw(ctx):
    bpy_module = ctx.deps.bpy
    wm = _safe_window_manager_from_bpy(bpy_module)
    if not wm:
        return
    for window in _safe_windows_from_manager(wm):
        try:
            screen = getattr(window, "screen", None)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if not screen:
            continue
        try:
            areas = tuple(getattr(screen, "areas", ()) or ())
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        for area in areas:
            try:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue


def tag_view3d_redraw(ctx=None):
    return _ctx_tag_view3d_redraw(_coerce_ctx(ctx))


def _ctx_get_camera_inside_earth_warning(ctx, scene):
    deps = ctx.deps
    target_scene = scene if scene is not None else _safe_context_scene(deps.bpy)
    if target_scene is None:
        return ""
    try:
        return str(target_scene.get(deps.camera_inside_earth_warning_key, "") or "").strip()
    except deps.recoverable_exceptions:
        return ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""


def get_camera_inside_earth_warning(scene, ctx=None):
    return _ctx_get_camera_inside_earth_warning(_coerce_ctx(ctx), scene)


def _ctx_clear_camera_inside_earth_warning(ctx, scene):
    deps = ctx.deps
    if scene is None:
        return
    try:
        if deps.camera_inside_earth_warning_key in scene:
            del scene[deps.camera_inside_earth_warning_key]
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed clearing inside-Earth warning", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed clearing inside-Earth warning", exc_info=True)


def clear_camera_inside_earth_warning(scene, ctx=None):
    return _ctx_clear_camera_inside_earth_warning(_coerce_ctx(ctx), scene)


def _ctx_set_camera_inside_earth_warning(ctx, scene, altitude_km=None):
    deps = ctx.deps
    if scene is None:
        return ""
    _ = altitude_km
    message = "Below Earth's surface"
    try:
        scene[deps.camera_inside_earth_warning_key] = str(message)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing inside-Earth warning", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing inside-Earth warning", exc_info=True)
    return message


def set_camera_inside_earth_warning(scene, altitude_km=None, ctx=None):
    return _ctx_set_camera_inside_earth_warning(_coerce_ctx(ctx), scene, altitude_km=altitude_km)


def resolve_scope_altitude_info(scene, runtime=None, scope_mode="AUTO"):
    result = {
        "inside_earth": False,
        "altitude_km": None,
        "altitude_bu": None,
        "scope_used": None,
    }
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    if scene is None:
        return result
    earth = deps.get_earth_object()
    if earth is None:
        return result

    tile_utils = deps.get_tile_utils()
    if tile_utils is None:
        return result
    get_camera_info = getattr(tile_utils, "get_camera_info", None)
    get_radius = getattr(tile_utils, "get_earth_radius_blender_units", None)
    if not callable(get_camera_info) or not callable(get_radius):
        return result

    try:
        camera_info = get_camera_info(scene, scope_mode=str(scope_mode or "AUTO"))
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
        return result
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
        return result

    if not isinstance(camera_info, dict):
        return result

    camera_position = camera_info.get("position")
    if camera_position is None:
        return result

    try:
        earth_center = earth.matrix_world.translation.copy()
        radius_bu = float(get_radius(earth))
        altitude_bu = float((camera_position - earth_center).length) - radius_bu
        meters_per_bu = float(deps.real_earth_radius_m / max(radius_bu, 1e-9))
        altitude_km = float((altitude_bu * meters_per_bu) / 1000.0)
        inside_epsilon_bu = float(max(1e-9, radius_bu * 1e-6))
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
        return result
    except (RuntimeError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        deps.logger.debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
        return result

    result["scope_used"] = str(camera_info.get("scope_used", "CAMERA") or "CAMERA")
    result["altitude_bu"] = altitude_bu
    result["altitude_km"] = altitude_km
    result["inside_earth"] = bool(altitude_bu < (-inside_epsilon_bu))
    return result


def camera_signature(scene):
    camera = getattr(scene, "camera", None)
    if camera is None:
        return None
    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    matrix_signature = tuple(round(float(value), 6) for row in camera.matrix_world for value in row)
    return (
        str(getattr(camera, "name_full", camera.name)),
        str(getattr(camera_data, "type", "")),
        round(float(getattr(camera_data, "lens", 0.0)), 6),
        round(float(getattr(camera_data, "ortho_scale", 0.0)), 6),
        matrix_signature,
    )


def normalize_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token in {"FULL", "PREVIEW"}:
        return token
    return "PREVIEW"


def _ctx_enforce_texture_quality_mode_for_account(ctx, scene, requested_mode):
    del ctx
    mode = normalize_texture_quality_mode(requested_mode)
    return mode


def enforce_texture_quality_mode_for_account(scene, requested_mode, ctx=None):
    return _ctx_enforce_texture_quality_mode_for_account(_coerce_ctx(ctx), scene, requested_mode)


def _ctx_output_resolution_signature(ctx, scene):
    render = getattr(scene, "render", None) if scene is not None else None
    if render is None:
        return None
    props = getattr(scene, "planetka", None) if scene is not None else None
    texture_quality_mode = "PREVIEW"
    try:
        texture_quality_mode = enforce_texture_quality_mode_for_account(
            scene,
            getattr(props, "texture_quality_mode", "PREVIEW"),
            ctx,
        )
    except (TypeError, ValueError, RuntimeError):
        texture_quality_mode = "PREVIEW"
    try:
        return (
            int(getattr(render, "resolution_x", 1920)),
            int(getattr(render, "resolution_y", 1080)),
            int(getattr(render, "resolution_percentage", 100)),
            texture_quality_mode,
        )
    except (TypeError, ValueError, RuntimeError):
        return None


def output_resolution_signature(scene, ctx=None):
    return _ctx_output_resolution_signature(_coerce_ctx(ctx), scene)


def _ctx_current_view_scope(ctx, scene):
    active_sig = _ctx_active_view_signature(ctx)
    if active_sig is not None and str(active_sig[0]) != "CAMERA":
        return "ACTIVE_VIEW"
    if getattr(scene, "camera", None) is not None:
        return "CAMERA"
    return "NONE"


def current_view_scope(scene, ctx=None):
    return _ctx_current_view_scope(_coerce_ctx(ctx), scene)


def _ctx_auto_resolve_scope_mode(ctx, scene):
    current_scope = _ctx_current_view_scope(ctx, scene)
    if current_scope == "ACTIVE_VIEW":
        return "ACTIVE_VIEW"
    if getattr(scene, "camera", None) is not None:
        return "CAMERA"
    return "NONE"


def auto_resolve_scope_mode(scene, ctx=None):
    return _ctx_auto_resolve_scope_mode(_coerce_ctx(ctx), scene)


def handle_viewport_motion_optimization(scene, camera_signature, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    if scene is None or camera_signature is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = deps.scene_key(scene)
    previous_signature = state.viewport_opt_last_signature.get(scene_id)
    if previous_signature == camera_signature:
        return
    state.viewport_opt_last_signature[scene_id] = camera_signature
    deps.suspend_adaptive_viewport_during_navigation(scene)


def timeline_signature(scene):
    if scene is None:
        return None
    try:
        frame = int(getattr(scene, "frame_current", 0))
    except (TypeError, ValueError, RuntimeError):
        frame = 0
    try:
        subframe = round(float(getattr(scene, "frame_subframe", 0.0)), 4)
    except (TypeError, ValueError, RuntimeError):
        subframe = 0.0
    return (frame, subframe)


def keyed_runtime_signature(scene):
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None

    def _as_float(value, fallback=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    nav_lon = _as_float(getattr(props, "nav_longitude_deg", 0.0), 0.0)
    nav_lat = _as_float(getattr(props, "nav_latitude_deg", 0.0), 0.0)
    nav_alt = max(0.0, _as_float(getattr(props, "nav_altitude_km", 0.0), 0.0))
    nav_heading = _as_float(getattr(props, "nav_azimuth_deg", 0.0), 0.0)
    nav_tilt = _as_float(getattr(props, "nav_tilt_deg", 0.0), 0.0)
    nav_roll = _as_float(getattr(props, "nav_roll_deg", 0.0), 0.0)
    nav_focal = max(1.0, _as_float(getattr(props, "nav_focal_length_mm", 50.0), 50.0))
    sun_lon = _as_float(getattr(props, "sunlight_longitude_deg", 0.0), 0.0)
    sun_tilt = _as_float(getattr(props, "sunlight_seasonal_tilt_deg", 0.0), 0.0)
    sun_strength = max(0.0, _as_float(getattr(props, "sunlight_strength", 10.0), 10.0))

    return (
        round(nav_lon, 6),
        round(nav_lat, 6),
        round(nav_alt, 6),
        round(nav_heading, 6),
        round(nav_tilt, 6),
        round(nav_roll, 6),
        round(nav_focal, 6),
        round(sun_lon, 6),
        round(sun_tilt, 6),
        round(sun_strength, 6),
    )


def iter_scene_animation_fcurves(scene, runtime=None):
    recoverable_exceptions = _coerce_ctx(runtime).deps.recoverable_exceptions
    if scene is None:
        return
    animation_data = getattr(scene, "animation_data", None)
    if animation_data is None:
        return
    seen = set()

    def _yield_action_fcurves(action):
        fcurves = getattr(action, "fcurves", None) if action is not None else None
        if not fcurves:
            return
        for fcurve in fcurves:
            if fcurve is None:
                continue
            try:
                token = int(fcurve.as_pointer())
            except recoverable_exceptions:
                token = id(fcurve)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                token = id(fcurve)
            if token in seen:
                continue
            seen.add(token)
            yield fcurve

    action = getattr(animation_data, "action", None)
    for fcurve in _yield_action_fcurves(action):
        yield fcurve

    nla_tracks = getattr(animation_data, "nla_tracks", None)
    if not nla_tracks:
        return
    for track in nla_tracks:
        strips = getattr(track, "strips", None)
        if not strips:
            continue
        for strip in strips:
            strip_action = getattr(strip, "action", None)
            for fcurve in _yield_action_fcurves(strip_action):
                yield fcurve


def scene_has_keyed_runtime_path(scene, accepted_paths, runtime):
    allowed = {str(path or "").strip() for path in (accepted_paths or ()) if str(path or "").strip()}
    if not allowed:
        return False
    for fcurve in iter_scene_animation_fcurves(scene, runtime):
        data_path = str(getattr(fcurve, "data_path", "") or "").strip()
        if data_path in allowed:
            return True
    return False


def handle_timeline_motion_optimization(scene, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        return
    if deps.is_render_job_active():
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = deps.scene_key(scene)
    current_signature = timeline_signature(scene)
    previous_signature = state.timeline_last_signature.get(scene_id)
    state.timeline_last_signature[scene_id] = current_signature

    if deps.is_animation_playing():
        deps.suspend_adaptive_viewport_during_navigation(scene)
        return

    if previous_signature is None:
        return
    if current_signature == previous_signature:
        return
    deps.suspend_adaptive_viewport_during_navigation(scene)


def sunlight_signature(scene, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    bpy_module = deps.bpy
    scene_id = deps.scene_key(scene) if scene is not None else None
    sunlight_object_name = deps.sunlight_object_name
    cache = state.sunlight_object_name_cache
    recoverable_exceptions = deps.recoverable_exceptions

    def _is_valid_sunlight_object(obj):
        if obj is None or str(getattr(obj, "type", "")) != "LIGHT":
            return False
        light_data = getattr(obj, "data", None)
        return str(getattr(light_data, "type", "")) == "SUN"

    def _scene_object_by_name(name):
        if scene is None or not name:
            return None
        scene_objects = getattr(scene, "objects", None)
        if scene_objects is None:
            return None
        try:
            return scene_objects.get(name)
        except recoverable_exceptions:
            return None

    sunlight = _scene_object_by_name(sunlight_object_name)
    if not _is_valid_sunlight_object(sunlight):
        sunlight = None

    if sunlight is None and scene_id is not None:
        cached_name = str(cache.get(scene_id, "") or "")
        cached_obj = _scene_object_by_name(cached_name)
        if _is_valid_sunlight_object(cached_obj):
            sunlight = cached_obj

    if sunlight is None and scene is not None:
        fallback = None
        fallback_name = ""
        for obj in getattr(scene, "objects", ()):
            if not _is_valid_sunlight_object(obj):
                continue
            name = str(getattr(obj, "name", ""))
            if name == sunlight_object_name:
                sunlight = obj
                break
            if name.startswith(sunlight_object_name):
                if fallback is None or name < fallback_name:
                    fallback = obj
                    fallback_name = name
        if sunlight is None:
            sunlight = fallback

    if sunlight is None:
        fallback_obj = bpy_module.data.objects.get(sunlight_object_name)
        if _is_valid_sunlight_object(fallback_obj):
            sunlight = fallback_obj

    if scene_id is not None:
        if sunlight is not None:
            cache[scene_id] = str(getattr(sunlight, "name", ""))
        else:
            cache.pop(scene_id, None)

    if sunlight is None:
        return None
    matrix_signature = tuple(
        round(float(value), 6)
        for row in sunlight.matrix_world
        for value in row
    )
    return (
        str(getattr(sunlight, "name", sunlight_object_name)),
        matrix_signature,
    )


def handle_sunlight_motion_optimization(scene, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = deps.scene_key(scene)
    signature = sunlight_signature(scene, ctx)
    previous_signature = state.sunlight_last_signature.get(scene_id)
    state.sunlight_last_signature[scene_id] = signature
    if signature is None or previous_signature is None:
        return
    if signature == previous_signature:
        return
    deps.suspend_adaptive_viewport_during_navigation(scene)


def handle_view_scope_quality_transition(scene, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if deps.get_earth_object() is None:
        return

    scene_id = deps.scene_key(scene)
    current_scope = current_view_scope(scene, ctx)
    previous_scope = state.viewport_scope_last.get(scene_id)
    state.viewport_scope_last[scene_id] = current_scope
    if previous_scope is None or previous_scope == current_scope:
        return

    if previous_scope != "ACTIVE_VIEW" or current_scope != "CAMERA":
        return
    if not bool(getattr(props, "auto_resolve", False)):
        return
    if bool(deps.get_auto_resolve_in_flight()):
        return
    if deps.is_render_job_active():
        return
    if deps.is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        return

    now = deps.monotonic()
    last_transition_resolve = state.viewport_scope_last_resolve_time.get(scene_id, 0.0)
    if now - float(last_transition_resolve) < 0.2:
        return

    deps.request_auto_resolve(scene, immediate=True, mark_dirty=True)


def earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0
    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0
    if stored_local_radius > 1e-9:
        scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
        return stored_local_radius * float(max_scale)
    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def intersect_ray_sphere_nearest(origin, direction, radius):
    a = float(direction.dot(direction))
    if a <= 1e-12:
        return None
    b = 2.0 * float(origin.dot(direction))
    c = float(origin.dot(origin)) - float(radius) * float(radius)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(disc)
    inv = 0.5 / a
    t0 = (-b - sqrt_disc) * inv
    t1 = (-b + sqrt_disc) * inv
    for t in (t0, t1):
        if t > 1e-6:
            return origin + direction * t
    return None


def realtime_view_camera_info(scene, runtime=None):
    bpy_module = _coerce_ctx(runtime).deps.bpy
    context = _safe_bpy_context(bpy_module)
    try:
        area = getattr(context, "area", None) if context is not None else None
        space = getattr(context, "space_data", None) if context is not None else None
        rv3d = getattr(context, "region_data", None) if context is not None else None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        area = None
        space = None
        rv3d = None

    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
        ):
        cam_matrix = rv3d.view_matrix.inverted()
        return {
            "position": cam_matrix.translation.copy(),
            "forward": (-cam_matrix.col[2].xyz).normalized(),
        }

    wm = _safe_window_manager_from_bpy(bpy_module)
    if wm:
        for window in _safe_windows_from_manager(wm):
            try:
                screen = getattr(window, "screen", None)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue
            if not screen:
                continue
            try:
                areas = tuple(getattr(screen, "areas", ()) or ())
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue
            for candidate_area in areas:
                try:
                    if candidate_area.type != 'VIEW_3D':
                        continue
                    candidate_space = getattr(candidate_area.spaces, "active", None)
                    if not candidate_space or candidate_space.type != 'VIEW_3D':
                        continue
                    candidate_rv3d = getattr(candidate_space, "region_3d", None)
                    if candidate_rv3d is None:
                        continue
                    cam_matrix = candidate_rv3d.view_matrix.inverted()
                    return {
                        "position": cam_matrix.translation.copy(),
                        "forward": (-cam_matrix.col[2].xyz).normalized(),
                    }
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    continue

    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return None
    matrix = camera.matrix_world
    return {
        "position": matrix.translation.copy(),
        "forward": (-matrix.col[2].xyz).normalized(),
    }


def tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    lon_shift = (float(lon_deg) + 180.0) % 360.0
    lat_shift = max(0.0, min(179.999999, float(lat_deg) + 90.0))
    step = max(1, int(z))
    x = int(lon_shift // step) * step
    y = int(lat_shift // step) * step
    return x % 360, max(0, min(179, y))


def best_available_mpp_for_lon_lat(lon_deg, lat_deg, runtime=None):
    deps = _coerce_ctx(runtime).deps
    coverage = deps.get_coverage_map()
    for z in deps.live_z_levels:
        level = coverage.get(int(z), set()) if coverage else set()
        if not level:
            continue
        x, y = tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) in level:
            return float(z) * deps.dataset_mpp_base_d1
    return None


def safety_for_required_vs_available(required_mpp, available_mpp, runtime=None):
    live_safety_caution_ratio = _coerce_ctx(runtime).deps.live_safety_caution_ratio
    if required_mpp is None:
        return "OK"
    try:
        required = max(1e-9, float(required_mpp))
    except (TypeError, ValueError):
        return "OK"
    try:
        available = float(available_mpp)
    except (TypeError, ValueError):
        return "WARNING"

    ratio = available / required
    if ratio <= 1.0:
        return "OK"
    if ratio <= live_safety_caution_ratio:
        return "CAUTION"
    return "WARNING"


def update_realtime_telemetry(scene, runtime=None, write_realtime_view_diagnostics=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    get_earth_object = deps.get_earth_object
    scene_key = deps.scene_key
    last_realtime_telemetry = state.last_realtime_telemetry
    real_earth_radius_m = deps.real_earth_radius_m
    max_terrain_height_m = deps.max_terrain_height_m
    live_fallback_mpp_m = deps.live_fallback_mpp_m
    diagnostics_writer = write_realtime_view_diagnostics or deps.write_realtime_view_diagnostics

    if scene is None:
        return
    scene_id = scene_key(scene)

    earth = get_earth_object()
    if earth is None:
        telemetry = (None, None, None, None, None)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    camera_info = realtime_view_camera_info(scene, runtime)
    if not camera_info:
        telemetry = (None, None, None, None, None)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    cam_pos_world = camera_info.get("position")
    cam_forward_world = camera_info.get("forward")
    projection_info = active_camera_projection_info(scene)
    if projection_info is None:
        telemetry = (None, None, None, None, None)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return
    camera_type = str(projection_info.get("camera_type", "PERSP"))
    h_fov = float(projection_info.get("h_fov", math.radians(50.0)))
    v_fov = float(projection_info.get("v_fov", math.radians(35.0)))
    res_x = max(1.0, float(projection_info.get("res_x", 1920.0)))
    res_y = max(1.0, float(projection_info.get("res_y", 1080.0)))
    ortho_scale = float(projection_info.get("ortho_scale", 1.0))
    if cam_pos_world is None or cam_forward_world is None or cam_forward_world.length_squared <= 1e-12:
        telemetry = (None, None, None, None, None)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    center, rotation, _scale = earth.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        telemetry = (None, None, None, None, None)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return
    cam_forward_local.normalize()

    radius_bu = earth_radius_blender_units(earth)
    hit_local = intersect_ray_sphere_nearest(cam_pos_local, cam_forward_local, radius_bu)

    cam_dist = float(cam_pos_local.length)
    altitude_bu = max(0.0, cam_dist - float(radius_bu))
    meters_per_bu = real_earth_radius_m / max(float(radius_bu), 1e-9)
    altitude_km = (altitude_bu * meters_per_bu) / 1000.0
    terrain_offset_bu = max_terrain_height_m / max(meters_per_bu, 1e-9)
    effective_distance = max(0.0, float(altitude_bu) - float(terrain_offset_bu))
    if camera_type == "ORTHO":
        px_world = max(float(ortho_scale) / res_x, float(ortho_scale) / res_y)
        estimated_mpp = px_world * meters_per_bu
    else:
        px_angle = max(h_fov / res_x, v_fov / res_y)
        px_angle = max(1e-9, float(px_angle))
        footprint_world = 2.0 * effective_distance * math.tan(px_angle * 0.5)
        estimated_mpp = footprint_world * meters_per_bu

    if hit_local is None:
        live_safety = "OK"
        telemetry = (None, None, round(float(altitude_km), 3), round(float(estimated_mpp), 3), live_safety)
        if last_realtime_telemetry.get(scene_id) != telemetry:
            last_realtime_telemetry[scene_id] = telemetry
            diagnostics_writer(scene, None, None, altitude_km, estimated_mpp, live_safety)
            tag_view3d_redraw(runtime)
        return

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    available_mpp = best_available_mpp_for_lon_lat(lon, lat, runtime)
    if available_mpp is None:
        available_mpp = live_fallback_mpp_m
    live_safety = safety_for_required_vs_available(estimated_mpp, available_mpp, runtime)
    telemetry = (
        round(float(lat), 4),
        round(float(lon), 4),
        round(float(altitude_km), 3),
        round(float(estimated_mpp), 3),
        live_safety,
    )
    if last_realtime_telemetry.get(scene_id) != telemetry:
        last_realtime_telemetry[scene_id] = telemetry
        diagnostics_writer(scene, lat, lon, altitude_km, estimated_mpp, live_safety)
        tag_view3d_redraw(runtime)


def canonical_tiles(tiles):
    if not isinstance(tiles, (list, tuple)):
        return tuple()
    return tuple(sorted(str(tile) for tile in tiles if tile))


def clear_resolve_size_estimates(scene, runtime=None):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    recoverable_exceptions = deps.recoverable_exceptions
    keys = (
        deps.resolve_estimate_full_bytes_key,
        deps.resolve_estimate_preview_bytes_key,
        deps.resolve_estimate_full_credits_key,
        deps.resolve_estimate_preview_credits_key,
        "planetka_resolve_estimate_full_available_bytes",
        "planetka_resolve_estimate_preview_available_bytes",
        "planetka_resolve_estimate_full_download_bytes",
        "planetka_resolve_estimate_preview_download_bytes",
        _REGION_OFFER_PRICING_TILES_KEY,
    )
    if scene is None:
        return
    for key in keys:
        try:
            if key in scene:
                del scene[key]
        except recoverable_exceptions:
            logger.debug("Planetka: failed clearing resolve-size estimate key '%s'", key, exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed clearing resolve-size estimate key '%s'", key, exc_info=True)


def estimate_download_bytes_for_visible_tiles(tiles, base_path, runtime=None, texture_quality_mode="PREVIEW"):
    estimate = estimate_download_availability_for_visible_tiles(
        tiles,
        base_path,
        runtime=runtime,
        texture_quality_mode=texture_quality_mode,
    )
    try:
        return int(max(0, int(estimate.get("total_bytes", 0) or 0)))
    except (AttributeError, TypeError, ValueError):
        return 0


def estimate_download_availability_for_visible_tiles(tiles, base_path, runtime=None, texture_quality_mode="PREVIEW"):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    recoverable_exceptions = deps.recoverable_exceptions
    streaming_utils = deps.get_streaming_utils()
    normalized_mode = deps.normalize_texture_quality_mode(texture_quality_mode)
    safe_tiles = canonical_tiles(tiles)
    if not safe_tiles:
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    if streaming_utils is None:
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    estimate_fn = getattr(streaming_utils, "estimate_remote_download_bytes_for_visible_tiles", None)
    if not callable(estimate_fn):
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    try:
        estimate = estimate_fn(
            safe_tiles,
            str(base_path or ""),
            allow_remote_probe=True,
            texture_quality_mode=normalized_mode,
        )
    except recoverable_exceptions:
        logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    except TypeError:
        try:
            estimate = estimate_fn(
                safe_tiles,
                str(base_path or ""),
                allow_remote_probe=True,
            )
        except recoverable_exceptions:
            logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
            return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
        except TypeError:
            try:
                estimate = estimate_fn(safe_tiles, str(base_path or ""))
            except recoverable_exceptions:
                logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
                return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
                return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
            return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    if not isinstance(estimate, dict):
        return {"total_bytes": 0, "available_bytes": 0, "download_bytes": 0}
    try:
        total_bytes = int(max(0, int(estimate.get("planned_total_bytes", 0) or 0)))
    except (TypeError, ValueError):
        total_bytes = 0
    try:
        available_bytes = int(max(0, int(estimate.get("local_available_bytes", 0) or 0)))
    except (TypeError, ValueError):
        available_bytes = 0
    try:
        download_bytes = int(max(0, int(estimate.get("planned_download_bytes", 0) or 0)))
    except (TypeError, ValueError):
        download_bytes = 0
    if available_bytes <= 0 and total_bytes > 0 and download_bytes > 0:
        available_bytes = int(max(0, total_bytes - min(download_bytes, total_bytes)))
    if download_bytes <= 0 and total_bytes > 0 and available_bytes > 0:
        download_bytes = int(max(0, total_bytes - min(available_bytes, total_bytes)))
    return {
        "total_bytes": int(max(0, total_bytes)),
        "available_bytes": int(max(0, min(available_bytes, total_bytes))) if total_bytes > 0 else int(max(0, available_bytes)),
        "download_bytes": int(max(0, min(download_bytes, total_bytes))) if total_bytes > 0 else int(max(0, download_bytes)),
    }


def _pricing_tiles_for_visible_tiles(tiles, runtime=None, texture_quality_mode="PREVIEW", base_path=""):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    normalized_mode = deps.normalize_texture_quality_mode(texture_quality_mode)
    streaming_utils = deps.get_streaming_utils()
    safe_tiles = canonical_tiles(tiles)
    if normalized_mode == "PREVIEW" or not safe_tiles:
        return tuple()
    if streaming_utils is None:
        return tuple(safe_tiles)
    try:
        plan_payload = streaming_utils.build_resolve_download_requests_for_visible_tiles(
            safe_tiles,
            str(base_path or ""),
            texture_quality_mode=normalized_mode,
        )
    except deps.recoverable_exceptions:
        logger.debug("Planetka: failed building pricing tile plan for resolve-credit estimate", exc_info=True)
        return tuple(safe_tiles)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed building pricing tile plan for resolve-credit estimate", exc_info=True)
        return tuple(safe_tiles)
    resolved_tiles = canonical_tiles(plan_payload.get("resolved_tiles", ()) if isinstance(plan_payload, dict) else ())
    ocean_lookup = set(plan_payload.get("ocean_tiles", ()) if isinstance(plan_payload, dict) else ())
    pricing_tiles = tuple(tile for tile in resolved_tiles if str(tile) not in ocean_lookup)
    if resolved_tiles:
        return pricing_tiles
    return tuple(safe_tiles)


def current_full_quality_pricing_tiles_for_region_offers(scene=None, runtime=None, scope_mode="CAMERA", base_path=""):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    recoverable_exceptions = deps.recoverable_exceptions
    target_scene = scene if scene is not None else _safe_context_scene(deps.bpy)
    if target_scene is not None:
        try:
            raw = str(target_scene.get(_REGION_OFFER_PRICING_TILES_KEY, "") or "")
            stored_tiles = canonical_tiles(raw.split("|") if raw else ())
            if stored_tiles:
                return stored_tiles
        except recoverable_exceptions:
            logger.debug("Planetka: failed reading cached region-offer tiles", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reading cached region-offer tiles", exc_info=True)

    tile_utils = deps.get_tile_utils()
    if tile_utils is None:
        return tuple()
    scope_token = str(scope_mode or "CAMERA").strip().upper()
    if scope_token not in {"CAMERA", "ACTIVE_VIEW", "AUTO"}:
        scope_token = "CAMERA"
    try:
        visible_tiles = canonical_tiles(
            tile_utils.main(
                scope_mode=scope_token,
                texture_quality_mode_override="FULL",
            )
        )
    except recoverable_exceptions:
        logger.debug("Planetka: failed computing region-offer tiles", exc_info=True)
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing region-offer tiles", exc_info=True)
        return tuple()
    return _pricing_tiles_for_visible_tiles(
        visible_tiles,
        runtime,
        texture_quality_mode="FULL",
        base_path=base_path,
    )


def _region_offer_location_for_scene(scene):
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None
    try:
        lat = max(-90.0, min(90.0, float(getattr(props, "nav_latitude_deg", 0.0) or 0.0)))
        lon = max(-180.0, min(180.0, float(getattr(props, "nav_longitude_deg", 0.0) or 0.0)))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None
    return lat, lon


def _camera_signature_text(camera_sig):
    try:
        return json.dumps(camera_sig, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(camera_sig)


def _longitude_distance_degrees(a, b):
    try:
        diff = abs(float(a) - float(b))
    except (TypeError, ValueError):
        return 180.0
    return min(diff, 360.0 - diff)


def _location_distance_degrees(a, b):
    if not a or not b:
        return 0.0
    try:
        lat_delta = abs(float(a[0]) - float(b[0]))
        lon_delta = _longitude_distance_degrees(float(a[1]), float(b[1]))
        return math.sqrt(lat_delta * lat_delta + lon_delta * lon_delta)
    except (TypeError, ValueError, IndexError):
        return 0.0


def _region_offer_signature(latitude_deg, longitude_deg, pricing_tiles, camera_signature_value):
    safe_tiles = canonical_tiles(pricing_tiles)
    tile_hash = hashlib.sha1("|".join(safe_tiles[:256]).encode("utf-8")).hexdigest()[:16] if safe_tiles else "none"
    camera_hash = hashlib.sha1(_camera_signature_text(camera_signature_value).encode("utf-8")).hexdigest()[:16]
    return f"{round(float(latitude_deg), 4):.4f}:{round(float(longitude_deg), 4):.4f}:{tile_hash}:{camera_hash}"


def _scene_region_offer_pricing_tiles(scene, deps):
    if scene is None:
        return tuple()
    try:
        raw = str(scene.get(_REGION_OFFER_PRICING_TILES_KEY, "") or "")
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed reading region-pack offer pricing tiles", exc_info=True)
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed reading region-pack offer pricing tiles", exc_info=True)
        return tuple()
    return canonical_tiles(raw.split("|") if raw else ())


def get_cached_region_pack_offers(scene=None, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    target_scene = scene if scene is not None else _safe_context_scene(deps.bpy)
    payload = {
        "offers": [],
        "status": "EMPTY",
        "message": "",
        "updated_at": 0.0,
    }
    if target_scene is None:
        return payload
    try:
        payload["status"] = str(target_scene.get(_REGION_OFFERS_STATUS_KEY, "EMPTY") or "EMPTY")
        payload["message"] = str(target_scene.get(_REGION_OFFERS_MESSAGE_KEY, "") or "")
        payload["updated_at"] = float(target_scene.get(_REGION_OFFERS_UPDATED_AT_KEY, 0.0) or 0.0)
        stored_lat = float(target_scene.get(_REGION_OFFERS_LATITUDE_KEY, 9999.0) or 9999.0)
        stored_lon = float(target_scene.get(_REGION_OFFERS_LONGITUDE_KEY, 9999.0) or 9999.0)
        raw = str(target_scene.get(_REGION_OFFERS_JSON_KEY, "") or "")
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed reading cached Full Quality Data Packs", exc_info=True)
        return payload
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed reading cached Full Quality Data Packs", exc_info=True)
        return payload
    if not raw:
        return payload
    current_location = _region_offer_location_for_scene(target_scene)
    if (
        current_location is not None
        and abs(stored_lat) <= 90.0
        and abs(stored_lon) <= 180.0
        and _location_distance_degrees(current_location, (stored_lat, stored_lon)) > _REGION_OFFERS_STALE_DISTANCE_DEG
    ):
        payload["status"] = "STALE"
        payload["message"] = "Data Packs update after Resolve."
        return payload
    try:
        offers = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        offers = []
    if isinstance(offers, list):
        payload["offers"] = [dict(offer) for offer in offers if isinstance(offer, dict)]
    return payload


def _set_region_offer_pending(scene, deps, signature, camera_signature_value, latitude_deg=None, longitude_deg=None):
    if scene is None:
        return
    try:
        scene[_REGION_OFFERS_PENDING_SIGNATURE_KEY] = str(signature or "")
        scene[_REGION_OFFERS_CAMERA_SIGNATURE_KEY] = _camera_signature_text(camera_signature_value)
        # Keep the previous completed payload visible while a low-priority refresh runs.
        scene[_REGION_OFFERS_STATUS_KEY] = "LOADING"
        scene[_REGION_OFFERS_MESSAGE_KEY] = "Updating Data Packs..."
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing region-pack offer pending state", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing region-pack offer pending state", exc_info=True)


def _store_region_pack_offers(scene, deps, signature, offers, latitude_deg=None, longitude_deg=None):
    if scene is None:
        return
    safe_offers = [dict(offer) for offer in offers if isinstance(offer, dict)]
    status = "READY" if safe_offers else "EMPTY"
    message = "" if safe_offers else "No Data Packs for this view."
    try:
        scene[_REGION_OFFERS_JSON_KEY] = json.dumps(safe_offers, separators=(",", ":"), sort_keys=True)
        scene[_REGION_OFFERS_SIGNATURE_KEY] = str(signature or "")
        scene[_REGION_OFFERS_PENDING_SIGNATURE_KEY] = ""
        scene[_REGION_OFFERS_STATUS_KEY] = status
        scene[_REGION_OFFERS_MESSAGE_KEY] = message
        scene[_REGION_OFFERS_UPDATED_AT_KEY] = float(time.time())
        if latitude_deg is not None and longitude_deg is not None:
            scene[_REGION_OFFERS_LATITUDE_KEY] = float(latitude_deg)
            scene[_REGION_OFFERS_LONGITUDE_KEY] = float(longitude_deg)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing cached Full Quality Data Packs", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing cached Full Quality Data Packs", exc_info=True)


def _store_region_pack_offer_error(scene, deps, signature, message="", latitude_deg=None, longitude_deg=None):
    if scene is None:
        return
    text = str(message or "Data Packs update failed.").strip()
    try:
        scene[_REGION_OFFERS_JSON_KEY] = "[]"
        if str(scene.get(_REGION_OFFERS_PENDING_SIGNATURE_KEY, "") or "") == str(signature or ""):
            scene[_REGION_OFFERS_PENDING_SIGNATURE_KEY] = ""
        scene[_REGION_OFFERS_SIGNATURE_KEY] = str(signature or "")
        scene[_REGION_OFFERS_STATUS_KEY] = "ERROR"
        scene[_REGION_OFFERS_MESSAGE_KEY] = text
        scene[_REGION_OFFERS_UPDATED_AT_KEY] = float(time.time())
        if latitude_deg is not None and longitude_deg is not None:
            scene[_REGION_OFFERS_LATITUDE_KEY] = float(latitude_deg)
            scene[_REGION_OFFERS_LONGITUDE_KEY] = float(longitude_deg)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing Full Quality Data Packs error state", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing Full Quality Data Packs error state", exc_info=True)


def _discard_stale_region_pack_offer_result(scene, deps, signature):
    if scene is None:
        return
    try:
        if str(scene.get(_REGION_OFFERS_PENDING_SIGNATURE_KEY, "") or "") == str(signature or ""):
            scene[_REGION_OFFERS_PENDING_SIGNATURE_KEY] = ""
            scene[_REGION_OFFERS_STATUS_KEY] = "STALE"
            scene[_REGION_OFFERS_MESSAGE_KEY] = "Data Packs update after Resolve."
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed discarding stale Full Quality Data Packs", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed discarding stale Full Quality Data Packs", exc_info=True)


def _region_pack_offer_result_still_relevant(scene, result):
    current_location = _region_offer_location_for_scene(scene)
    if current_location is None:
        return True
    try:
        result_location = (float(result.get("latitude_deg")), float(result.get("longitude_deg")))
    except (TypeError, ValueError):
        return True
    return _location_distance_degrees(current_location, result_location) <= _REGION_OFFERS_STALE_DISTANCE_DEG


def _apply_region_pack_offer_results_timer():
    global _REGION_OFFERS_APPLY_TIMER_RUNNING
    try:
        ctx = _require_ctx()
        deps = ctx.deps
    except (RuntimeError, TypeError, ValueError, AttributeError):
        with _REGION_OFFERS_LOCK:
            _REGION_OFFERS_APPLY_TIMER_RUNNING = False
        return None

    with _REGION_OFFERS_LOCK:
        results = list(_REGION_OFFERS_RESULTS)
        _REGION_OFFERS_RESULTS.clear()
        for result in results:
            _REGION_OFFERS_IN_FLIGHT.discard(str(result.get("signature", "") or ""))
        if not results:
            if _REGION_OFFERS_IN_FLIGHT:
                return 0.1
            _REGION_OFFERS_APPLY_TIMER_RUNNING = False
            return None
        current_generation = int(_REGION_OFFERS_GENERATION)

    redraw = False
    for result in results:
        try:
            result_generation = int(result.get("generation", -1))
        except (TypeError, ValueError):
            result_generation = -1
        if result_generation != current_generation:
            try:
                scene = _find_scene_by_key(deps, result.get("scene_id"))
                if scene is not None:
                    _discard_stale_region_pack_offer_result(scene, deps, result.get("signature"))
                    redraw = True
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            continue
        signature = str(result.get("signature", "") or "")
        scene = _find_scene_by_key(deps, result.get("scene_id"))
        if scene is None:
            continue
        try:
            pending_signature = str(scene.get(_REGION_OFFERS_PENDING_SIGNATURE_KEY, "") or "")
        except deps.recoverable_exceptions:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if pending_signature != signature:
            continue
        current_camera_signature = _camera_signature_text(camera_signature(scene))
        result_camera_signature = str(result.get("camera_signature_text", "") or "")
        if current_camera_signature != result_camera_signature and not _region_pack_offer_result_still_relevant(scene, result):
            _discard_stale_region_pack_offer_result(scene, deps, signature)
            redraw = True
            continue
        if not bool(result.get("ok", False)):
            _store_region_pack_offer_error(
                scene,
                deps,
                signature,
                result.get("message", ""),
                latitude_deg=result.get("latitude_deg"),
                longitude_deg=result.get("longitude_deg"),
            )
            redraw = True
            continue
        _store_region_pack_offers(
            scene,
            deps,
            signature,
            result.get("offers", ()),
            latitude_deg=result.get("latitude_deg"),
            longitude_deg=result.get("longitude_deg"),
        )
        redraw = True

    if redraw:
        try:
            tag_view3d_redraw(ctx)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

    with _REGION_OFFERS_LOCK:
        if _REGION_OFFERS_RESULTS:
            return 0.1
        _REGION_OFFERS_APPLY_TIMER_RUNNING = False
    return None


def schedule_region_pack_offer_refresh(
    scene,
    runtime=None,
    latitude_deg=None,
    longitude_deg=None,
    pricing_tiles=None,
    camera_signature_value=None,
    delay_seconds=_REGION_OFFERS_REFRESH_DELAY_SECONDS,
    force=False,
):
    global _REGION_OFFERS_APPLY_TIMER_RUNNING
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    if scene is None:
        return False
    if camera_signature_value is None:
        camera_signature_value = camera_signature(scene)
    if camera_signature_value is None:
        return False

    if latitude_deg is None or longitude_deg is None:
        location = _region_offer_location_for_scene(scene)
        if location is None:
            return False
        latitude_deg, longitude_deg = location
    try:
        lat = max(-90.0, min(90.0, float(latitude_deg or 0.0)))
        lon = max(-180.0, min(180.0, float(longitude_deg or 0.0)))
    except (TypeError, ValueError):
        return False

    safe_tiles = canonical_tiles(pricing_tiles if pricing_tiles is not None else _scene_region_offer_pricing_tiles(scene, deps))
    signature = _region_offer_signature(lat, lon, safe_tiles, camera_signature_value)
    try:
        existing_signature = str(scene.get(_REGION_OFFERS_SIGNATURE_KEY, "") or "")
        existing_status = str(scene.get(_REGION_OFFERS_STATUS_KEY, "") or "").strip().upper()
        existing_raw = str(scene.get(_REGION_OFFERS_JSON_KEY, "") or "")
    except deps.recoverable_exceptions:
        existing_signature = ""
        existing_status = ""
        existing_raw = ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        existing_signature = ""
        existing_status = ""
        existing_raw = ""
    has_ready_offers = False
    if existing_raw:
        try:
            has_ready_offers = bool(json.loads(existing_raw) or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            has_ready_offers = False
    if (
        existing_signature == signature
        and not bool(force)
        and (
            (existing_status == "READY" and has_ready_offers)
            or existing_status == "EMPTY"
        )
    ):
        return False

    with _REGION_OFFERS_LOCK:
        if signature in _REGION_OFFERS_IN_FLIGHT:
            _set_region_offer_pending(scene, deps, signature, camera_signature_value, lat, lon)
            return True
        _REGION_OFFERS_IN_FLIGHT.add(signature)
        generation = int(_REGION_OFFERS_GENERATION)
        _set_region_offer_pending(scene, deps, signature, camera_signature_value, lat, lon)
        try:
            if not _REGION_OFFERS_APPLY_TIMER_RUNNING:
                deps.bpy.app.timers.register(_apply_region_pack_offer_results_timer, first_interval=0.1)
                _REGION_OFFERS_APPLY_TIMER_RUNNING = True
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed registering Full Quality Data Packs timer", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            deps.logger.debug("Planetka: failed registering Full Quality Data Packs timer", exc_info=True)

    try:
        scene_id = deps.scene_key(scene)
    except deps.recoverable_exceptions:
        scene_id = 0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        scene_id = 0
    camera_signature_text = _camera_signature_text(camera_signature_value)

    def _worker():
        offers = []
        ok = False
        message = ""
        try:
            delay = max(0.0, float(delay_seconds or 0.0))
        except (TypeError, ValueError):
            delay = _REGION_OFFERS_REFRESH_DELAY_SECONDS
        if delay > 0.0:
            time.sleep(delay)
        try:
            from ..credit_api import get_region_pack_offers
            offers = get_region_pack_offers(lat, lon, tile_keys=safe_tiles, force=force, raise_errors=True)
            ok = True
        except deps.import_recoverable_exceptions:
            message = "Data Packs update failed."
            deps.logger.debug("Planetka: Full Quality Data Packs refresh failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            message = "Data Packs update failed."
            deps.logger.debug("Planetka: Full Quality Data Packs refresh failed", exc_info=True)
        with _REGION_OFFERS_LOCK:
            _REGION_OFFERS_RESULTS.append(
                {
                    "scene_id": scene_id,
                    "signature": signature,
                    "camera_signature_text": camera_signature_text,
                    "latitude_deg": lat,
                    "longitude_deg": lon,
                    "offers": offers,
                    "ok": ok,
                    "message": message,
                    "generation": generation,
                }
            )

    threading.Thread(
        target=_worker,
        name="PlanetkaRegionPackOffers",
        daemon=True,
    ).start()
    return True


def _full_price_signature(pricing_tiles, texture_quality_mode="FULL"):
    mode = str(texture_quality_mode or "FULL").strip().upper()
    return "|".join((mode, *canonical_tiles(pricing_tiles)))


def _find_scene_by_key(deps, scene_id):
    try:
        target_id = int(scene_id)
    except (TypeError, ValueError):
        return None
    try:
        scenes = tuple(getattr(getattr(deps.bpy, "data", None), "scenes", ()) or ())
    except deps.recoverable_exceptions:
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None
    for scene in scenes:
        try:
            if int(deps.scene_key(scene)) == target_id:
                return scene
        except deps.recoverable_exceptions:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
    return None


def _set_full_price_pending(scene, deps, signature, pending=True):
    if scene is None:
        return
    try:
        scene[_FULL_PRICE_SIGNATURE_KEY] = str(signature or "")
        scene[_FULL_PRICE_PENDING_KEY] = bool(pending)
        if bool(pending) and deps.resolve_estimate_full_credits_key in scene:
            del scene[deps.resolve_estimate_full_credits_key]
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing Full Quality price pending state", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing Full Quality price pending state", exc_info=True)


def _store_full_price_estimate(scene, deps, signature, credits):
    if scene is None:
        return
    try:
        scene[_FULL_PRICE_SIGNATURE_KEY] = str(signature or "")
        scene[_FULL_PRICE_PENDING_KEY] = False
        if credits is None:
            if deps.resolve_estimate_full_credits_key in scene:
                del scene[deps.resolve_estimate_full_credits_key]
        else:
            scene[deps.resolve_estimate_full_credits_key] = float(max(0.0, float(credits)))
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing Full Quality price estimate", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing Full Quality price estimate", exc_info=True)


def _estimate_full_credits_for_pricing_tiles(pricing_tiles):
    safe_tiles = canonical_tiles(pricing_tiles)
    if not safe_tiles:
        return 0.0
    from ..credit_api import estimate_credits_for_tiles
    summary = estimate_credits_for_tiles(safe_tiles, quality_mode="FULL")
    if not isinstance(summary, dict) or not bool(summary.get("authoritative", False)):
        return None
    return _money_round(max(0.0, float(summary.get("credits", 0.0) or 0.0)))


def _apply_async_full_price_results_timer():
    global _FULL_PRICE_APPLY_TIMER_RUNNING
    try:
        ctx = _require_ctx()
        deps = ctx.deps
    except (RuntimeError, TypeError, ValueError, AttributeError):
        with _FULL_PRICE_LOCK:
            _FULL_PRICE_APPLY_TIMER_RUNNING = False
        return None

    with _FULL_PRICE_LOCK:
        results = list(_FULL_PRICE_RESULTS)
        _FULL_PRICE_RESULTS.clear()
        for result in results:
            _FULL_PRICE_IN_FLIGHT.discard(str(result.get("signature", "") or ""))
        if not results:
            if _FULL_PRICE_IN_FLIGHT:
                return 0.1
            _FULL_PRICE_APPLY_TIMER_RUNNING = False
            return None
        current_generation = int(_FULL_PRICE_GENERATION)

    for result in results:
        try:
            result_generation = int(result.get("generation", -1))
        except (TypeError, ValueError):
            result_generation = -1
        if result_generation != current_generation:
            continue
        signature = str(result.get("signature", "") or "")
        scene = _find_scene_by_key(deps, result.get("scene_id"))
        if scene is None:
            continue
        try:
            if str(scene.get(_FULL_PRICE_SIGNATURE_KEY, "") or "") != signature:
                continue
        except deps.recoverable_exceptions:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        _store_full_price_estimate(scene, deps, signature, result.get("credits"))
        try:
            tag_view3d_redraw(ctx)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

    with _FULL_PRICE_LOCK:
        if _FULL_PRICE_RESULTS:
            return 0.1
        _FULL_PRICE_APPLY_TIMER_RUNNING = False
    return None


def _schedule_async_full_price_estimate(scene, runtime, pricing_tiles, signature):
    global _FULL_PRICE_APPLY_TIMER_RUNNING
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    safe_tiles = canonical_tiles(pricing_tiles)
    safe_signature = str(signature or _full_price_signature(safe_tiles, "FULL"))
    now = time.monotonic()

    with _FULL_PRICE_LOCK:
        cached = _FULL_PRICE_CACHE.get(safe_signature)
        if isinstance(cached, dict) and (now - float(cached.get("time", 0.0) or 0.0)) <= _FULL_PRICE_CACHE_TTL_SECONDS:
            _store_full_price_estimate(scene, deps, safe_signature, cached.get("credits"))
            return
        if safe_signature in _FULL_PRICE_IN_FLIGHT:
            _set_full_price_pending(scene, deps, safe_signature, pending=True)
            return
        _FULL_PRICE_IN_FLIGHT.add(safe_signature)
        generation = int(_FULL_PRICE_GENERATION)
        _set_full_price_pending(scene, deps, safe_signature, pending=True)
        try:
            if not _FULL_PRICE_APPLY_TIMER_RUNNING:
                deps.bpy.app.timers.register(_apply_async_full_price_results_timer, first_interval=0.1)
                _FULL_PRICE_APPLY_TIMER_RUNNING = True
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed registering async Full Quality price timer", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            deps.logger.debug("Planetka: failed registering async Full Quality price timer", exc_info=True)

    try:
        scene_id = deps.scene_key(scene)
    except deps.recoverable_exceptions:
        scene_id = 0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        scene_id = 0

    def _worker():
        credits = None
        try:
            credits = _estimate_full_credits_for_pricing_tiles(safe_tiles)
        except deps.import_recoverable_exceptions:
            deps.logger.debug("Planetka: async Full Quality price estimate failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            deps.logger.debug("Planetka: async Full Quality price estimate failed", exc_info=True)
        with _FULL_PRICE_LOCK:
            _FULL_PRICE_CACHE[safe_signature] = {
                "time": time.monotonic(),
                "credits": credits,
            }
            _FULL_PRICE_RESULTS.append(
                {
                    "scene_id": scene_id,
                    "signature": safe_signature,
                    "credits": credits,
                    "generation": generation,
                }
            )

    thread = threading.Thread(
        target=_worker,
        name="PlanetkaFullPriceEstimate",
        daemon=True,
    )
    thread.start()


def estimate_credits_for_visible_tiles(tiles, runtime=None, texture_quality_mode="PREVIEW", base_path=""):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    normalized_mode = deps.normalize_texture_quality_mode(texture_quality_mode)
    safe_tiles = _pricing_tiles_for_visible_tiles(
        tiles,
        runtime,
        texture_quality_mode=normalized_mode,
        base_path=base_path,
    )
    if normalized_mode == "PREVIEW" or not safe_tiles:
        return 0.0
    try:
        from ..credit_api import estimate_credits_for_tiles
        summary = estimate_credits_for_tiles(safe_tiles, quality_mode=normalized_mode)
        if normalized_mode != "PREVIEW" and not bool(summary.get("authoritative", False)):
            return None
        return float(max(0.0, float(summary.get("credits", 0.0) or 0.0)))
    except deps.import_recoverable_exceptions:
        logger.debug("Planetka: resolve-credit estimate failed", exc_info=True)
        return 0.0 if normalized_mode == "PREVIEW" else None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: resolve-credit estimate failed", exc_info=True)
        return 0.0 if normalized_mode == "PREVIEW" else None


def build_resolve_cost_breakdown(scene=None, runtime=None, scope_mode="CAMERA", base_path="", texture_quality_mode="FULL"):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    recoverable_exceptions = deps.recoverable_exceptions
    tile_utils = deps.get_tile_utils()
    streaming_utils = deps.get_streaming_utils()
    normalized_mode = deps.normalize_texture_quality_mode(texture_quality_mode)
    if scene is None:
        scene = _safe_context_scene(deps.bpy)
    if scene is None or tile_utils is None or streaming_utils is None:
        return {
            "ok": False,
            "error": "breakdown_unavailable",
            "quality_mode": normalized_mode,
            "tiles": [],
            "excluded_tiles": [],
            "total_bytes": 0,
            "total_credits": 0.0,
        }

    scope_token = str(scope_mode or "CAMERA").strip().upper()
    if scope_token not in {"CAMERA", "ACTIVE_VIEW", "AUTO"}:
        scope_token = "CAMERA"

    try:
        visible_tiles = canonical_tiles(
            tile_utils.main(
                scope_mode=scope_token,
                texture_quality_mode_override=normalized_mode,
            )
        )
    except recoverable_exceptions:
        logger.debug("Planetka: failed computing tiles for resolve-cost breakdown", exc_info=True)
        visible_tiles = tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing tiles for resolve-cost breakdown", exc_info=True)
        visible_tiles = tuple()

    try:
        plan_payload = streaming_utils.build_resolve_download_requests_for_visible_tiles(
            visible_tiles,
            str(base_path or ""),
            texture_quality_mode=normalized_mode,
        )
    except recoverable_exceptions:
        logger.debug("Planetka: failed building download plan for resolve-cost breakdown", exc_info=True)
        plan_payload = {}
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed building download plan for resolve-cost breakdown", exc_info=True)
        plan_payload = {}

    resolved_tiles = canonical_tiles(plan_payload.get("resolved_tiles", ()) if isinstance(plan_payload, dict) else ())
    ocean_lookup = set(plan_payload.get("ocean_tiles", ()) if isinstance(plan_payload, dict) else ())
    pricing_tiles = [tile for tile in resolved_tiles if str(tile) not in ocean_lookup]
    if not pricing_tiles and not resolved_tiles:
        pricing_tiles = list(visible_tiles)

    try:
        from ..credit_api import estimate_credit_breakdown_for_tiles
        credit_summary = estimate_credit_breakdown_for_tiles(pricing_tiles, quality_mode=normalized_mode)
    except deps.import_recoverable_exceptions:
        logger.debug("Planetka: failed computing credit breakdown", exc_info=True)
        credit_summary = {}
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing credit breakdown", exc_info=True)
        credit_summary = {}

    pricing_authoritative = bool(
        normalized_mode == "PREVIEW"
        or (isinstance(credit_summary, dict) and credit_summary.get("authoritative", False))
    )
    if normalized_mode != "PREVIEW" and not pricing_authoritative:
        return {
            "ok": False,
            "error": "pricing_unavailable",
            "quality_mode": normalized_mode,
            "pricing_authoritative": False,
            "tiles": [],
            "charged_tiles": [],
            "excluded_tiles": [],
            "free_tiles": [],
            "total_bytes": 0,
            "tile_bytes_sum": 0,
            "total_credits": 0.0,
            "paid_tile_count": 0,
            "free_tile_count": 0,
        }

    price_by_tile = {}
    for record in credit_summary.get("tiles", ()) if isinstance(credit_summary, dict) else ():
        if not isinstance(record, dict):
            continue
        key = str(record.get("tile_key", "") or "").strip()
        if key:
            price_by_tile[key] = dict(record)

    texture_types = tuple(getattr(streaming_utils, "TEXTURE_TYPES", ("S2", "EL", "WT", "PO")) or ("S2", "EL", "WT", "PO"))
    texture_extensions = dict(getattr(streaming_utils, "TEXTURE_EXTENSIONS", {}) or {})
    uses_pole_cap = getattr(streaming_utils, "_tile_uses_pole_cap", None)

    def _asset_size(folder, file_name):
        try:
            from ..r2_source import find_local_source_asset, texture_asset_size_bytes
            local_path = find_local_source_asset(folder, file_name)
            if local_path:
                return int(max(0, int(os.path.getsize(local_path))))
            known_size = texture_asset_size_bytes(folder, file_name, allow_remote_probe=True)
            return int(max(0, int(known_size or 0)))
        except deps.import_recoverable_exceptions:
            logger.debug("Planetka: failed reading asset size for breakdown", exc_info=True)
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reading asset size for breakdown", exc_info=True)
        return 0

    tile_rows = []
    for tile_text in pricing_tiles:
        tile_key = str(tile_text or "").strip()
        if not tile_key or tile_key in ocean_lookup:
            continue
        try:
            if callable(uses_pole_cap) and uses_pole_cap(tile_key):
                continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
        parts = tile_key.split("_")
        try:
            z_value = int(parts[2][1:])
            d_value = int(parts[3][1:])
        except (TypeError, ValueError, IndexError):
            z_value = 0
            d_value = 0
        assets = []
        tile_bytes = 0
        for texture_type in texture_types:
            folder = str(texture_type or "").strip()
            if not folder:
                continue
            asset_tile_key = tile_key
            if folder == "EL" and z_value == 1 and d_value == 2:
                asset_tile_key = tile_key.replace("_d002", "_d001")
            exts = texture_extensions.get(folder, (".exr",))
            ext = str(tuple(exts or (".exr",))[0] or ".exr")
            file_name = f"{folder}_{asset_tile_key}{ext}"
            size_bytes = _asset_size(folder, file_name)
            tile_bytes += int(max(0, size_bytes))
            assets.append(
                {
                    "folder": folder,
                    "file_name": file_name,
                    "bytes": int(max(0, size_bytes)),
                }
            )
        price_record = dict(price_by_tile.get(tile_key, {}))
        tile_rows.append(
            {
                "tile_key": tile_key,
                "bytes": int(max(0, tile_bytes)),
                "mb": float(tile_bytes) / float(1024.0 ** 2),
                "credits": float(price_record.get("credits", 0.0) or 0.0),
                "gross_credits": float(price_record.get("gross_credits", price_record.get("credits", 0.0)) or 0.0),
                "gross_price_eur": float(price_record.get("gross_price_eur", price_record.get("gross_credits", price_record.get("credits", 0.0))) or 0.0),
                "land_km2": float(price_record.get("land_km2", 0.0) or 0.0),
                "billable_land_km2": float(price_record.get("billable_land_km2", 0.0) or 0.0),
                "delivered_mpp": float(price_record.get("delivered_mpp", 0.0) or 0.0),
                "detail_ratio": float(price_record.get("detail_ratio", 0.0) or 0.0),
                "price_factor": float(price_record.get("price_factor", 0.0) or 0.0),
                "free_reason": str(price_record.get("free_reason", "") or "").strip(),
                "already_owned": bool(price_record.get("already_owned", False)) or str(price_record.get("free_reason", "") or "").strip() == "already_unlocked",
                "upgrade_credit_applied": float(price_record.get("upgrade_credit_applied", 0.0) or 0.0),
                "partially_licenced": bool(price_record.get("partially_licenced", False)),
                "assets": assets,
            }
        )

    total_bytes = sum(int(row.get("bytes", 0) or 0) for row in tile_rows)
    try:
        from ..r2_source import estimate_total_resolve_bytes
        estimate = estimate_total_resolve_bytes(list(plan_payload.get("requests", ()) or ()), allow_remote_probe=True)
        if isinstance(estimate, dict):
            total_bytes = int(max(0, int(estimate.get("planned_total_bytes", total_bytes) or total_bytes)))
    except deps.import_recoverable_exceptions:
        logger.debug("Planetka: failed computing exact breakdown total bytes", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing exact breakdown total bytes", exc_info=True)

    excluded_keys = {
        str(record.get("tile_key", "") or "").strip()
        for record in credit_summary.get("excluded_tiles", ()) if isinstance(record, dict)
    } if isinstance(credit_summary, dict) else set()
    excluded_tiles = [
        row for row in tile_rows
        if row.get("already_owned") or str(row.get("tile_key", "") or "") in excluded_keys
    ]
    charged_tiles = [row for row in tile_rows if float(row.get("credits", 0.0) or 0.0) > 0.0]
    partial_tiles = [
        row for row in charged_tiles
        if bool(row.get("partially_licenced", False))
        or float(row.get("upgrade_credit_applied", 0.0) or 0.0) > 0.0
    ]
    free_tiles = [row for row in tile_rows if float(row.get("credits", 0.0) or 0.0) <= 0.0 and row not in excluded_tiles]
    raw_total_credits = _money_round(sum(float(row.get("credits", 0.0) or 0.0) for row in tile_rows))
    total_credits = raw_total_credits
    if normalized_mode != "PREVIEW" and isinstance(credit_summary, dict):
        try:
            total_credits = _money_round(max(0.0, float(credit_summary.get("credits", raw_total_credits) or 0.0)))
        except (TypeError, ValueError):
            total_credits = raw_total_credits
    partial_credit = _money_round(sum(float(row.get("upgrade_credit_applied", 0.0) or 0.0) for row in partial_tiles))
    scene_tile_price = raw_total_credits
    custom_scene_licence = 0.0
    scene_payable = total_credits
    scene_small_free = False
    scene_custom_applied = False
    scene_small_free_threshold = 0.0
    scene_custom_label = ""
    if isinstance(credit_summary, dict):
        try:
            scene_tile_price = _money_round(float(credit_summary.get("scene_tile_price_eur", raw_total_credits) or 0.0))
        except (TypeError, ValueError):
            scene_tile_price = raw_total_credits
        try:
            custom_scene_licence = _money_round(float(credit_summary.get("custom_scene_licence_eur", 0.0) or 0.0))
        except (TypeError, ValueError):
            custom_scene_licence = 0.0
        try:
            scene_payable = _money_round(float(credit_summary.get("scene_payable_eur", total_credits) or 0.0))
        except (TypeError, ValueError):
            scene_payable = total_credits
        scene_small_free = bool(credit_summary.get("scene_small_free_threshold_applied", False))
        scene_custom_applied = bool(credit_summary.get("scene_custom_licence_applied", custom_scene_licence > 0.0))
        try:
            scene_small_free_threshold = _money_round(float(credit_summary.get("scene_small_free_threshold_eur", 0.0) or 0.0))
        except (TypeError, ValueError):
            scene_small_free_threshold = 0.0
        scene_custom_label = str(credit_summary.get("scene_custom_licence_label", "") or "")

    return {
        "ok": True,
        "quality_mode": normalized_mode,
        "tiles": tile_rows,
        "charged_tiles": charged_tiles,
        "partial_tiles": partial_tiles,
        "excluded_tiles": excluded_tiles,
        "free_tiles": free_tiles,
        "total_bytes": int(max(0, total_bytes)),
        "tile_bytes_sum": int(max(0, sum(int(row.get("bytes", 0) or 0) for row in tile_rows))),
        "total_credits": float(total_credits),
        "raw_total_credits": float(raw_total_credits),
        "scene_tile_price_eur": float(scene_tile_price),
        "custom_scene_licence_eur": float(custom_scene_licence),
        "scene_payable_eur": float(scene_payable),
        "scene_custom_licence_label": scene_custom_label,
        "scene_custom_licence_applied": bool(scene_custom_applied),
        "scene_small_free_threshold_eur": float(scene_small_free_threshold),
        "scene_small_free_threshold_applied": bool(scene_small_free),
        "partial_licence_tile_count": int(len(partial_tiles)),
        "partial_licence_credit_eur": float(partial_credit),
        "paid_tile_count": int(len(charged_tiles)),
        "free_tile_count": int(len(free_tiles)),
        "pricing_authoritative": bool(pricing_authoritative),
    }


def update_resolve_size_estimates(
    scene,
    runtime=None,
    scope_mode="CAMERA",
    base_path="",
    full_tiles_override=None,
    include_full_price=True,
    async_full_price=False,
    force_full_price_refresh=False,
):
    deps = _coerce_ctx(runtime).deps
    logger = deps.logger
    recoverable_exceptions = deps.recoverable_exceptions
    tile_utils = deps.get_tile_utils()
    normalize_texture_quality_mode = deps.normalize_texture_quality_mode
    resolve_estimate_full_bytes_key = deps.resolve_estimate_full_bytes_key
    resolve_estimate_preview_bytes_key = deps.resolve_estimate_preview_bytes_key
    if scene is None:
        return False
    if tile_utils is None:
        clear_resolve_size_estimates(scene, runtime)
        return False

    scope_token = str(scope_mode or "CAMERA").strip().upper()
    if scope_token not in {"CAMERA", "ACTIVE_VIEW", "AUTO"}:
        scope_token = "CAMERA"

    def _compute_mode_tiles(mode, override_tiles=None):
        normalized_mode = normalize_texture_quality_mode(mode)
        if override_tiles is not None:
            return canonical_tiles(override_tiles)
        try:
            return canonical_tiles(
                tile_utils.main(
                    scope_mode=scope_token,
                    texture_quality_mode_override=normalized_mode,
                )
            )
        except recoverable_exceptions:
            logger.debug(
                "Planetka: failed computing %s tiles for resolve-size estimate",
                normalized_mode,
                exc_info=True,
            )
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug(
                "Planetka: failed computing %s tiles for resolve-size estimate",
                normalized_mode,
                exc_info=True,
            )
            return None

    full_tiles = _compute_mode_tiles("FULL", override_tiles=full_tiles_override)
    preview_tiles = _compute_mode_tiles("PREVIEW")

    if full_tiles is None or preview_tiles is None:
        clear_resolve_size_estimates(scene, runtime)
        return False

    full_availability = estimate_download_availability_for_visible_tiles(
        full_tiles,
        base_path,
        runtime,
        texture_quality_mode="FULL",
    )
    preview_availability = estimate_download_availability_for_visible_tiles(
        preview_tiles,
        base_path,
        runtime,
        texture_quality_mode="PREVIEW",
    )
    full_bytes = int(max(0, int((full_availability or {}).get("total_bytes", 0) or 0)))
    preview_bytes = int(max(0, int((preview_availability or {}).get("total_bytes", 0) or 0)))
    full_available_bytes = int(max(0, int((full_availability or {}).get("available_bytes", 0) or 0)))
    preview_available_bytes = int(max(0, int((preview_availability or {}).get("available_bytes", 0) or 0)))
    full_download_bytes = int(max(0, int((full_availability or {}).get("download_bytes", 0) or 0)))
    preview_download_bytes = int(max(0, int((preview_availability or {}).get("download_bytes", 0) or 0)))
    full_pricing_tiles = _pricing_tiles_for_visible_tiles(
        full_tiles,
        runtime,
        texture_quality_mode="FULL",
        base_path=base_path,
    )
    full_price_signature = _full_price_signature(full_pricing_tiles, "FULL")
    full_credits = None
    full_price_pending = False
    existing_signature = ""
    try:
        existing_signature = str(scene.get(_FULL_PRICE_SIGNATURE_KEY, "") or "")
    except recoverable_exceptions:
        existing_signature = ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        existing_signature = ""
    if not full_pricing_tiles:
        full_credits = 0.0
    elif existing_signature == full_price_signature and not bool(force_full_price_refresh):
        try:
            if deps.resolve_estimate_full_credits_key in scene:
                full_credits = float(max(0.0, float(scene.get(deps.resolve_estimate_full_credits_key, 0.0) or 0.0)))
        except recoverable_exceptions:
            full_credits = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            full_credits = None
    if full_credits is None and bool(include_full_price):
        if bool(async_full_price):
            _schedule_async_full_price_estimate(scene, runtime, full_pricing_tiles, full_price_signature)
            full_price_pending = True
        else:
            try:
                full_credits = _estimate_full_credits_for_pricing_tiles(full_pricing_tiles)
            except deps.import_recoverable_exceptions:
                logger.debug("Planetka: resolve-credit estimate failed", exc_info=True)
                full_credits = None
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: resolve-credit estimate failed", exc_info=True)
                full_credits = None
    preview_credits = 0.0

    try:
        scene[resolve_estimate_full_bytes_key] = int(max(0, int(full_bytes)))
        scene[resolve_estimate_preview_bytes_key] = int(max(0, int(preview_bytes)))
        scene["planetka_resolve_estimate_full_available_bytes"] = int(max(0, int(full_available_bytes)))
        scene["planetka_resolve_estimate_preview_available_bytes"] = int(max(0, int(preview_available_bytes)))
        scene["planetka_resolve_estimate_full_download_bytes"] = int(max(0, int(full_download_bytes)))
        scene["planetka_resolve_estimate_preview_download_bytes"] = int(max(0, int(preview_download_bytes)))
        scene[_REGION_OFFER_PRICING_TILES_KEY] = "|".join(str(tile) for tile in full_pricing_tiles[:256])
        scene[_FULL_PRICE_SIGNATURE_KEY] = str(full_price_signature or "")
        if full_price_pending:
            scene[_FULL_PRICE_PENDING_KEY] = True
        elif full_credits is None:
            scene[_FULL_PRICE_PENDING_KEY] = False
            if deps.resolve_estimate_full_credits_key in scene:
                del scene[deps.resolve_estimate_full_credits_key]
        else:
            scene[_FULL_PRICE_PENDING_KEY] = False
            scene[deps.resolve_estimate_full_credits_key] = float(max(0.0, float(full_credits)))
        scene[deps.resolve_estimate_preview_credits_key] = float(max(0.0, float(preview_credits)))
    except recoverable_exceptions:
        logger.debug("Planetka: failed storing resolve-size estimates", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing resolve-size estimates", exc_info=True)
        return False
    return True


def get_resolve_size_estimates(scene=None, runtime=None):
    deps = _coerce_ctx(runtime).deps
    target_scene = scene if scene is not None else _safe_context_scene(deps.bpy)
    recoverable_exceptions = deps.recoverable_exceptions
    resolve_estimate_full_bytes_key = deps.resolve_estimate_full_bytes_key
    resolve_estimate_preview_bytes_key = deps.resolve_estimate_preview_bytes_key
    if target_scene is None:
        return {"FULL": None, "PREVIEW": None}

    def _read_int(key):
        try:
            if key not in target_scene:
                return None
            return int(max(0, int(target_scene.get(key, 0) or 0)))
        except recoverable_exceptions:
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return None

    def _read_float(key):
        try:
            if key not in target_scene:
                return None
            return float(max(0.0, float(target_scene.get(key, 0.0) or 0.0)))
        except recoverable_exceptions:
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return None

    def _read_bool(key):
        try:
            if key not in target_scene:
                return False
            return bool(target_scene.get(key, False))
        except recoverable_exceptions:
            return False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return False

    return {
        "FULL": _read_int(resolve_estimate_full_bytes_key),
        "PREVIEW": _read_int(resolve_estimate_preview_bytes_key),
        "FULL_AVAILABLE": _read_int("planetka_resolve_estimate_full_available_bytes"),
        "PREVIEW_AVAILABLE": _read_int("planetka_resolve_estimate_preview_available_bytes"),
        "FULL_DOWNLOAD": _read_int("planetka_resolve_estimate_full_download_bytes"),
        "PREVIEW_DOWNLOAD": _read_int("planetka_resolve_estimate_preview_download_bytes"),
        "FULL_CREDITS": _read_float(deps.resolve_estimate_full_credits_key),
        "FULL_CREDITS_PENDING": _read_bool(_FULL_PRICE_PENDING_KEY),
        "PREVIEW_CREDITS": _read_float(deps.resolve_estimate_preview_credits_key),
    }


def last_resolved_tiles(scene, runtime=None):
    recoverable_exceptions = _coerce_ctx(runtime).deps.recoverable_exceptions
    try:
        return canonical_tiles(scene.get("planetka_last_resolved_tiles", ()))
    except recoverable_exceptions:
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return tuple()
