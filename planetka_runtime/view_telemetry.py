import math

_VIEW_TELEMETRY_CTX = None

def _require_ctx():
    ctx = _VIEW_TELEMETRY_CTX
    if ctx is None:
        raise RuntimeError("Planetka view telemetry context is not configured.")
    return ctx


def _is_context(value):
    return hasattr(value, "deps") and hasattr(value, "state")


def _active_view_signature_from_bpy(bpy_module):
    if bpy_module is None:
        return None
    wm = getattr(bpy_module.context, "window_manager", None)
    if not wm:
        return None

    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
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
    return None


def _ctx_active_view_signature(ctx):
    return _active_view_signature_from_bpy(ctx.deps.bpy)


def active_view_signature(ctx=None):
    if _is_context(ctx):
        return _ctx_active_view_signature(ctx)
    if isinstance(ctx, dict):
        return _active_view_signature_from_bpy(ctx.get("bpy"))
    return _ctx_active_view_signature(_require_ctx())


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
    wm = getattr(bpy_module.context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def tag_view3d_redraw(ctx=None):
    if _is_context(ctx):
        return _ctx_tag_view3d_redraw(ctx)
    if isinstance(ctx, dict):
        bpy_module = ctx.get("bpy")
        if bpy_module is None:
            return
        wm = getattr(bpy_module.context, "window_manager", None)
        if not wm:
            return
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return
    return _ctx_tag_view3d_redraw(_require_ctx())


def _ctx_get_camera_inside_earth_warning(ctx, scene):
    deps = ctx.deps
    target_scene = scene if scene is not None else getattr(getattr(deps.bpy, "context", None), "scene", None)
    if target_scene is None:
        return ""
    try:
        return str(target_scene.get(deps.camera_inside_earth_warning_key, "") or "").strip()
    except deps.recoverable_exceptions:
        return ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""


def get_camera_inside_earth_warning(scene, ctx=None):
    if _is_context(ctx):
        return _ctx_get_camera_inside_earth_warning(ctx, scene)
    if isinstance(ctx, dict):
        target_scene = scene if scene is not None else getattr(getattr(ctx.get("bpy"), "context", None), "scene", None)
        if target_scene is None:
            return ""
        try:
            return str(target_scene.get(ctx["CAMERA_INSIDE_EARTH_WARNING_KEY"], "") or "").strip()
        except ctx["PLANETKA_RECOVERABLE_EXCEPTIONS"]:
            return ""
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return ""
    return _ctx_get_camera_inside_earth_warning(_require_ctx(), scene)


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
    if _is_context(ctx):
        return _ctx_clear_camera_inside_earth_warning(ctx, scene)
    if isinstance(ctx, dict):
        if scene is None:
            return
        try:
            if ctx["CAMERA_INSIDE_EARTH_WARNING_KEY"] in scene:
                del scene[ctx["CAMERA_INSIDE_EARTH_WARNING_KEY"]]
        except ctx["PLANETKA_RECOVERABLE_EXCEPTIONS"]:
            ctx["logger"].debug("Planetka: failed clearing inside-Earth warning", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            ctx["logger"].debug("Planetka: failed clearing inside-Earth warning", exc_info=True)
        return
    return _ctx_clear_camera_inside_earth_warning(_require_ctx(), scene)


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
    if _is_context(ctx):
        return _ctx_set_camera_inside_earth_warning(ctx, scene, altitude_km=altitude_km)
    if isinstance(ctx, dict):
        if scene is None:
            return ""
        _ = altitude_km
        message = "Below Earth's surface"
        try:
            scene[ctx["CAMERA_INSIDE_EARTH_WARNING_KEY"]] = str(message)
        except ctx["PLANETKA_RECOVERABLE_EXCEPTIONS"]:
            ctx["logger"].debug("Planetka: failed storing inside-Earth warning", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            ctx["logger"].debug("Planetka: failed storing inside-Earth warning", exc_info=True)
        return message
    return _ctx_set_camera_inside_earth_warning(_require_ctx(), scene, altitude_km=altitude_km)


def resolve_scope_altitude_info(scene, runtime, scope_mode="AUTO"):
    result = {
        "inside_earth": False,
        "altitude_km": None,
        "altitude_bu": None,
        "scope_used": None,
    }
    if scene is None:
        return result
    earth = runtime["get_earth_object"]()
    if earth is None:
        return result

    tile_utils = runtime["_get_tile_utils"]()
    if tile_utils is None:
        return result
    get_camera_info = getattr(tile_utils, "get_camera_info", None)
    get_radius = getattr(tile_utils, "get_earth_radius_blender_units", None)
    if not callable(get_camera_info) or not callable(get_radius):
        return result

    try:
        camera_info = get_camera_info(scene, scope_mode=str(scope_mode or "AUTO"))
    except runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]:
        runtime["logger"].debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
        return result
    except (RuntimeError, TypeError, ValueError, AttributeError):
        runtime["logger"].debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
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
        meters_per_bu = float(runtime["_REAL_EARTH_RADIUS_M"] / max(radius_bu, 1e-9))
        altitude_km = float((altitude_bu * meters_per_bu) / 1000.0)
        inside_epsilon_bu = float(max(1e-9, radius_bu * 1e-6))
    except (runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"], RuntimeError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        runtime["logger"].debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
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
    if token == "HALF":
        return "BALANCED"
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


def _ctx_enforce_texture_quality_mode_for_account(ctx, scene, requested_mode):
    deps = ctx.deps
    del scene
    mode = normalize_texture_quality_mode(requested_mode)
    if mode == "PREVIEW":
        return mode
    try:
        from ..auth import get_account_tier
        prefs = deps.get_prefs()
        tier = str(get_account_tier(prefs) or "").strip().lower()
    except deps.import_recoverable_exceptions:
        tier = ""

    if mode == "BALANCED":
        if tier in {"personal", "commercial"}:
            return "BALANCED"
        return "PREVIEW"

    if tier == "commercial":
        return "FULL"
    if tier == "personal":
        return "BALANCED"
    return "PREVIEW"


def enforce_texture_quality_mode_for_account(scene, requested_mode, ctx=None):
    if _is_context(ctx):
        return _ctx_enforce_texture_quality_mode_for_account(ctx, scene, requested_mode)
    if isinstance(ctx, dict):
        del scene
        mode = normalize_texture_quality_mode(requested_mode)
        if mode == "PREVIEW":
            return mode
        try:
            from ..auth import get_account_tier
            prefs = ctx["get_prefs"]()
            tier = str(get_account_tier(prefs) or "").strip().lower()
        except ctx["PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS"]:
            tier = ""
        if mode == "BALANCED":
            if tier in {"personal", "commercial"}:
                return "BALANCED"
            return "PREVIEW"
        if tier == "commercial":
            return "FULL"
        if tier == "personal":
            return "BALANCED"
        return "PREVIEW"
    return _ctx_enforce_texture_quality_mode_for_account(_require_ctx(), scene, requested_mode)


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
    if _is_context(ctx):
        return _ctx_output_resolution_signature(ctx, scene)
    if isinstance(ctx, dict):
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
    return _ctx_output_resolution_signature(_require_ctx(), scene)


def _ctx_current_view_scope(ctx, scene):
    active_sig = _ctx_active_view_signature(ctx)
    if active_sig is not None and str(active_sig[0]) != "CAMERA":
        return "ACTIVE_VIEW"
    if getattr(scene, "camera", None) is not None:
        return "CAMERA"
    return "NONE"


def current_view_scope(scene, ctx=None):
    if _is_context(ctx):
        return _ctx_current_view_scope(ctx, scene)
    if isinstance(ctx, dict):
        active_sig = active_view_signature(ctx)
        if active_sig is not None and str(active_sig[0]) != "CAMERA":
            return "ACTIVE_VIEW"
        if getattr(scene, "camera", None) is not None:
            return "CAMERA"
        return "NONE"
    return _ctx_current_view_scope(_require_ctx(), scene)


def _ctx_auto_resolve_scope_mode(ctx, scene):
    current_scope = _ctx_current_view_scope(ctx, scene)
    if current_scope == "ACTIVE_VIEW":
        return "ACTIVE_VIEW"
    if getattr(scene, "camera", None) is not None:
        return "CAMERA"
    return "NONE"


def auto_resolve_scope_mode(scene, ctx=None):
    if _is_context(ctx):
        return _ctx_auto_resolve_scope_mode(ctx, scene)
    if isinstance(ctx, dict):
        current_scope = current_view_scope(scene, ctx)
        if current_scope == "ACTIVE_VIEW":
            return "ACTIVE_VIEW"
        if getattr(scene, "camera", None) is not None:
            return "CAMERA"
        return "NONE"
    return _ctx_auto_resolve_scope_mode(_require_ctx(), scene)


def handle_viewport_motion_optimization(scene, camera_signature, runtime):
    if _is_context(runtime):
        deps = runtime.deps
        state = runtime.state
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
        return

    if scene is None or camera_signature is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = runtime["_scene_key"](scene)
    previous_signature = runtime["_VIEWPORT_OPT_LAST_SIGNATURE"].get(scene_id)
    if previous_signature == camera_signature:
        return
    runtime["_VIEWPORT_OPT_LAST_SIGNATURE"][scene_id] = camera_signature
    runtime["_suspend_adaptive_viewport_during_navigation"](scene)


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


def iter_scene_animation_fcurves(scene, runtime):
    if _is_context(runtime):
        recoverable_exceptions = runtime.deps.recoverable_exceptions
    else:
        recoverable_exceptions = runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]

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
            except (recoverable_exceptions, RuntimeError, TypeError, ValueError, AttributeError):
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


def handle_timeline_motion_optimization(scene, runtime):
    if _is_context(runtime):
        deps = runtime.deps
        state = runtime.state
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
        return

    if scene is None:
        return
    if runtime["_is_render_job_active"]():
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = runtime["_scene_key"](scene)
    current_signature = timeline_signature(scene)
    previous_signature = runtime["_TIMELINE_LAST_SIGNATURE"].get(scene_id)
    runtime["_TIMELINE_LAST_SIGNATURE"][scene_id] = current_signature

    if runtime["_is_animation_playing"]():
        runtime["_suspend_adaptive_viewport_during_navigation"](scene)
        return

    if previous_signature is None:
        return
    if current_signature == previous_signature:
        return
    runtime["_suspend_adaptive_viewport_during_navigation"](scene)


def sunlight_signature(scene, runtime):
    if _is_context(runtime):
        deps = runtime.deps
        state = runtime.state
        bpy_module = deps.bpy
        scene_id = deps.scene_key(scene) if scene is not None else None
        sunlight_object_name = deps.sunlight_object_name
        cache = state.sunlight_object_name_cache
        recoverable_exceptions = deps.recoverable_exceptions
    else:
        bpy_module = runtime["bpy"]
        scene_id = runtime["_scene_key"](scene) if scene is not None else None
        sunlight_object_name = runtime["_SUNLIGHT_OBJECT_NAME"]
        cache = runtime["_SUNLIGHT_OBJECT_NAME_CACHE"]
        recoverable_exceptions = runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]

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


def handle_sunlight_motion_optimization(scene, runtime):
    if _is_context(runtime):
        deps = runtime.deps
        state = runtime.state
        if scene is None:
            return
        props = getattr(scene, "planetka", None)
        if props is None:
            return
        if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
            return

        scene_id = deps.scene_key(scene)
        signature = sunlight_signature(scene, runtime)
        previous_signature = state.sunlight_last_signature.get(scene_id)
        state.sunlight_last_signature[scene_id] = signature
        if signature is None or previous_signature is None:
            return
        if signature == previous_signature:
            return
        deps.suspend_adaptive_viewport_during_navigation(scene)
        return

    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = runtime["_scene_key"](scene)
    signature = sunlight_signature(scene, runtime)
    previous_signature = runtime["_SUNLIGHT_LAST_SIGNATURE"].get(scene_id)
    runtime["_SUNLIGHT_LAST_SIGNATURE"][scene_id] = signature
    if signature is None or previous_signature is None:
        return
    if signature == previous_signature:
        return
    runtime["_suspend_adaptive_viewport_during_navigation"](scene)


def handle_view_scope_quality_transition(scene, runtime):
    if _is_context(runtime):
        deps = runtime.deps
        state = runtime.state
        if scene is None:
            return
        props = getattr(scene, "planetka", None)
        if props is None:
            return
        if deps.get_earth_object() is None:
            return

        scene_id = deps.scene_key(scene)
        current_scope = current_view_scope(scene, runtime)
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
        return

    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if runtime["get_earth_object"]() is None:
        return

    scene_id = runtime["_scene_key"](scene)
    current_scope = current_view_scope(scene, runtime)
    previous_scope = runtime["_VIEWPORT_SCOPE_LAST"].get(scene_id)
    runtime["_VIEWPORT_SCOPE_LAST"][scene_id] = current_scope
    if previous_scope is None or previous_scope == current_scope:
        return

    if previous_scope != "ACTIVE_VIEW" or current_scope != "CAMERA":
        return
    if not bool(getattr(props, "auto_resolve", False)):
        return
    if runtime["_AUTO_RESOLVE_IN_FLIGHT"]:
        return
    if runtime["_is_render_job_active"]():
        return
    if runtime["_is_animation_playing"]() and bool(getattr(props, "lock_resolve_during_animation", True)):
        return

    now = runtime["time"].monotonic()
    last_transition_resolve = runtime["_VIEWPORT_SCOPE_LAST_RESOLVE_TIME"].get(scene_id, 0.0)
    if now - float(last_transition_resolve) < 0.2:
        return

    runtime["request_auto_resolve"](scene, immediate=True, mark_dirty=True)


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


def realtime_view_camera_info(scene, runtime):
    bpy_module = runtime["bpy"]
    context = bpy_module.context
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)

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

    wm = getattr(context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for candidate_area in screen.areas:
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


def best_available_mpp_for_lon_lat(lon_deg, lat_deg, runtime):
    coverage = runtime["_get_coverage_map"]()
    for z in runtime["_LIVE_Z_LEVELS"]:
        level = coverage.get(int(z), set()) if coverage else set()
        if not level:
            continue
        x, y = tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) in level:
            return float(z) * runtime["_DATASET_MPP_BASE_D1"]
    return None


def safety_for_required_vs_available(required_mpp, available_mpp, runtime):
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
    if ratio <= runtime["_LIVE_SAFETY_CAUTION_RATIO"]:
        return "CAUTION"
    return "WARNING"


def update_realtime_telemetry(scene, runtime, write_realtime_view_diagnostics):
    get_earth_object = runtime["get_earth_object"]
    _scene_key = runtime["_scene_key"]
    _LAST_REALTIME_TELEMETRY = runtime["_LAST_REALTIME_TELEMETRY"]
    _REAL_EARTH_RADIUS_M = runtime["_REAL_EARTH_RADIUS_M"]
    _MAX_TERRAIN_HEIGHT_M = runtime["_MAX_TERRAIN_HEIGHT_M"]
    _LIVE_FALLBACK_MPP_M = runtime["_LIVE_FALLBACK_MPP_M"]

    if scene is None:
        return
    scene_id = _scene_key(scene)

    earth = get_earth_object()
    if earth is None:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    camera_info = realtime_view_camera_info(scene, runtime)
    if not camera_info:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    cam_pos_world = camera_info.get("position")
    cam_forward_world = camera_info.get("forward")
    projection_info = active_camera_projection_info(scene)
    if projection_info is None:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
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
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return

    center, rotation, _scale = earth.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            tag_view3d_redraw(runtime)
        return
    cam_forward_local.normalize()

    radius_bu = earth_radius_blender_units(earth)
    hit_local = intersect_ray_sphere_nearest(cam_pos_local, cam_forward_local, radius_bu)

    cam_dist = float(cam_pos_local.length)
    altitude_bu = max(0.0, cam_dist - float(radius_bu))
    meters_per_bu = _REAL_EARTH_RADIUS_M / max(float(radius_bu), 1e-9)
    altitude_km = (altitude_bu * meters_per_bu) / 1000.0
    terrain_offset_bu = _MAX_TERRAIN_HEIGHT_M / max(meters_per_bu, 1e-9)
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
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, altitude_km, estimated_mpp, live_safety)
            tag_view3d_redraw(runtime)
        return

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    available_mpp = best_available_mpp_for_lon_lat(lon, lat, runtime)
    if available_mpp is None:
        available_mpp = _LIVE_FALLBACK_MPP_M
    live_safety = safety_for_required_vs_available(estimated_mpp, available_mpp, runtime)
    telemetry = (
        round(float(lat), 4),
        round(float(lon), 4),
        round(float(altitude_km), 3),
        round(float(estimated_mpp), 3),
        live_safety,
    )
    if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
        _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
        write_realtime_view_diagnostics(scene, lat, lon, altitude_km, estimated_mpp, live_safety)
        tag_view3d_redraw(runtime)


def canonical_tiles(tiles):
    if not isinstance(tiles, (list, tuple)):
        return tuple()
    return tuple(sorted(str(tile) for tile in tiles if tile))


def clear_resolve_size_estimates(scene, runtime):
    logger = runtime["logger"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    if scene is None:
        return
    for key in (
        runtime["RESOLVE_ESTIMATE_FULL_BYTES_KEY"],
        runtime["RESOLVE_ESTIMATE_BALANCED_BYTES_KEY"],
        runtime["RESOLVE_ESTIMATE_PREVIEW_BYTES_KEY"],
    ):
        try:
            if key in scene:
                del scene[key]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed clearing resolve-size estimate key '%s'", key, exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed clearing resolve-size estimate key '%s'", key, exc_info=True)


def estimate_download_bytes_for_visible_tiles(tiles, base_path, runtime, texture_quality_mode="PREVIEW"):
    logger = runtime["logger"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    safe_tiles = canonical_tiles(tiles)
    if not safe_tiles:
        return 0
    streaming_utils = runtime["_get_streaming_utils"]()
    if streaming_utils is None:
        return 0
    estimate_fn = getattr(streaming_utils, "estimate_remote_download_bytes_for_visible_tiles", None)
    if not callable(estimate_fn):
        return 0
    normalized_mode = runtime["_normalize_texture_quality_mode"](texture_quality_mode)
    try:
        estimate = estimate_fn(
            safe_tiles,
            str(base_path or ""),
            allow_remote_probe=True,
            texture_quality_mode=normalized_mode,
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
        return 0
    except TypeError:
        try:
            estimate = estimate_fn(
                safe_tiles,
                str(base_path or ""),
                allow_remote_probe=True,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
            return 0
        except TypeError:
            try:
                estimate = estimate_fn(safe_tiles, str(base_path or ""))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
                return 0
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
                return 0
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
            return 0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: resolve-size estimate failed", exc_info=True)
        return 0
    if not isinstance(estimate, dict):
        return 0
    try:
        return int(max(0, int(estimate.get("planned_total_bytes", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def update_resolve_size_estimates(scene, runtime, scope_mode="CAMERA", base_path="", full_tiles_override=None):
    logger = runtime["logger"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    if scene is None:
        return False
    tile_utils = runtime["_get_tile_utils"]()
    if tile_utils is None:
        clear_resolve_size_estimates(scene, runtime)
        return False

    scope_token = str(scope_mode or "CAMERA").strip().upper()
    if scope_token not in {"CAMERA", "ACTIVE_VIEW", "AUTO"}:
        scope_token = "CAMERA"

    def _compute_mode_tiles(mode, override_tiles=None):
        normalized_mode = runtime["_normalize_texture_quality_mode"](mode)
        if override_tiles is not None:
            return canonical_tiles(override_tiles)
        try:
            return canonical_tiles(
                tile_utils.main(
                    scope_mode=scope_token,
                    texture_quality_mode_override=normalized_mode,
                )
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    balanced_tiles = _compute_mode_tiles("BALANCED")
    preview_tiles = _compute_mode_tiles("PREVIEW")

    if full_tiles is None or balanced_tiles is None or preview_tiles is None:
        clear_resolve_size_estimates(scene, runtime)
        return False

    full_bytes = estimate_download_bytes_for_visible_tiles(
        full_tiles,
        base_path,
        runtime,
        texture_quality_mode="FULL",
    )
    balanced_bytes = estimate_download_bytes_for_visible_tiles(
        balanced_tiles,
        base_path,
        runtime,
        texture_quality_mode="BALANCED",
    )
    preview_bytes = estimate_download_bytes_for_visible_tiles(
        preview_tiles,
        base_path,
        runtime,
        texture_quality_mode="PREVIEW",
    )

    try:
        scene[runtime["RESOLVE_ESTIMATE_FULL_BYTES_KEY"]] = int(max(0, int(full_bytes)))
        scene[runtime["RESOLVE_ESTIMATE_BALANCED_BYTES_KEY"]] = int(max(0, int(balanced_bytes)))
        scene[runtime["RESOLVE_ESTIMATE_PREVIEW_BYTES_KEY"]] = int(max(0, int(preview_bytes)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing resolve-size estimates", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing resolve-size estimates", exc_info=True)
        return False
    return True


def get_resolve_size_estimates(scene=None, runtime=None):
    runtime = runtime or {}
    bpy_module = runtime.get("bpy")
    target_scene = scene if scene is not None else getattr(getattr(bpy_module, "context", None), "scene", None)
    if target_scene is None:
        return {"FULL": None, "BALANCED": None, "PREVIEW": None}

    def _read_int(key):
        try:
            if key not in target_scene:
                return None
            return int(max(0, int(target_scene.get(key, 0) or 0)))
        except runtime.get("PLANETKA_RECOVERABLE_EXCEPTIONS", (RuntimeError, TypeError, ValueError, AttributeError)):
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return None

    return {
        "FULL": _read_int(runtime["RESOLVE_ESTIMATE_FULL_BYTES_KEY"]),
        "BALANCED": _read_int(runtime["RESOLVE_ESTIMATE_BALANCED_BYTES_KEY"]),
        "PREVIEW": _read_int(runtime["RESOLVE_ESTIMATE_PREVIEW_BYTES_KEY"]),
    }


def last_resolved_tiles(scene, runtime):
    try:
        return canonical_tiles(scene.get("planetka_last_resolved_tiles", ()))
    except runtime["PLANETKA_RECOVERABLE_EXCEPTIONS"]:
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return tuple()
