import hashlib
import math
import os
import time

_VIEW_TELEMETRY_CTX = None

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
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


def _cloud_lod_signature(scene):
    """Return only cloud inputs that affect LOD selection.

    Do not include prepared/loaded d-level metadata here. Those values are
    written during cloud optimization and including them would make resolve
    finalization dirty itself.
    """
    if scene is None:
        return tuple()
    props = getattr(scene, "planetka", None)
    try:
        local_enabled = bool(getattr(props, "enable_local_clouds", False)) if props is not None else False
        vdb_enabled = bool(getattr(props, "enable_vdb_clouds", False)) if props is not None else False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        local_enabled = False
        vdb_enabled = False

    entries = []
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except (RuntimeError, TypeError, ValueError, AttributeError):
        objects = tuple()

    for obj in objects:
        try:
            role = str(obj.get("planetka_cloud_role", "") or "")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            role = ""
        if role == "local_cloud":
            try:
                source = str(
                    obj.get("planetka_local_cloud_texture", "")
                    or getattr(obj, "planetka_local_cloud_texture", "")
                    or obj.get("planetka_local_cloud_texture_path", "")
                    or ""
                )
            except (RuntimeError, TypeError, ValueError, AttributeError):
                source = ""
            try:
                size = round(float(getattr(obj, "planetka_local_cloud_size_coef", 1.0)), 6)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                size = 1.0
            entries.append((
                "local",
                str(getattr(obj, "name_full", getattr(obj, "name", "")) or ""),
                os.path.basename(source),
                size,
            ))
        elif role == "vdb_cloud":
            try:
                source = str(
                    obj.get("planetka_vdb_cloud_source_file", "")
                    or getattr(obj, "planetka_vdb_cloud_file", "")
                    or ""
                )
            except (RuntimeError, TypeError, ValueError, AttributeError):
                source = ""
            try:
                size = round(float(getattr(obj, "planetka_vdb_cloud_size_coef", 1.0)), 6)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                size = 1.0
            entries.append((
                "vdb",
                str(getattr(obj, "name_full", getattr(obj, "name", "")) or ""),
                os.path.basename(source),
                size,
            ))

    return (bool(local_enabled), bool(vdb_enabled), tuple(sorted(entries)))


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
            _cloud_lod_signature(scene),
        )
    except (TypeError, ValueError, RuntimeError):
        return None


def output_resolution_signature(scene, ctx=None):
    return _ctx_output_resolution_signature(_coerce_ctx(ctx), scene)


def handle_viewport_motion_optimization(scene, camera_signature, runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    if scene is None or camera_signature is None:
        return

    scene_id = deps.scene_key(scene)
    previous_signature = state.viewport_opt_last_signature.get(scene_id)
    if previous_signature == camera_signature:
        return
    state.viewport_opt_last_signature[scene_id] = camera_signature


def _iter_action_fcurves(action):
    if action is None:
        return
    fcurves = getattr(action, "fcurves", None)
    if not fcurves:
        return
    for fcurve in fcurves:
        yield fcurve


def iter_scene_animation_fcurves(scene, runtime=None):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    animation_data = getattr(props, "animation_data", None) if props is not None else None
    if animation_data is None:
        return
    seen = set()
    for action in (getattr(animation_data, "action", None),):
        for fcurve in _iter_action_fcurves(action) or ():
            token = id(fcurve)
            if token in seen:
                continue
            seen.add(token)
            yield fcurve
    tracks = getattr(animation_data, "nla_tracks", None)
    if not tracks:
        return
    for track in tracks:
        for strip in getattr(track, "strips", ()) or ():
            action = getattr(strip, "action", None)
            for fcurve in _iter_action_fcurves(action) or ():
                token = id(fcurve)
                if token in seen:
                    continue
                seen.add(token)
                yield fcurve


def scene_has_keyed_runtime_path(scene, accepted_paths, runtime=None):
    del runtime
    allowed = {str(path or "").strip() for path in (accepted_paths or ()) if str(path or "").strip()}
    if not allowed:
        return False
    for fcurve in iter_scene_animation_fcurves(scene):
        data_path = str(getattr(fcurve, "data_path", "") or "").strip()
        if data_path in allowed:
            return True
    return False


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

    scene_id = deps.scene_key(scene)
    signature = sunlight_signature(scene, ctx)
    previous_signature = state.sunlight_last_signature.get(scene_id)
    state.sunlight_last_signature[scene_id] = signature
    if signature is None or previous_signature is None:
        return
    if signature == previous_signature:
        return


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
        "planetka_resolve_estimate_full_available_bytes",
        "planetka_resolve_estimate_preview_available_bytes",
        "planetka_resolve_estimate_full_download_bytes",
        "planetka_resolve_estimate_preview_download_bytes",
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
            allow_remote_probe=False,
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
                allow_remote_probe=False,
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


def update_resolve_size_estimates(
    scene,
    runtime=None,
    scope_mode="CAMERA",
    base_path="",
    full_tiles_override=None,
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

    try:
        full_source_tiles = canonical_tiles(full_tiles_override) if full_tiles_override is not None else None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        full_source_tiles = None
    if full_source_tiles is None:
        try:
            full_source_tiles = canonical_tiles(tile_utils.main(scope_mode=scope_token))
        except recoverable_exceptions:
            logger.debug("Planetka: failed computing full source tiles for resolve-size estimate", exc_info=True)
            clear_resolve_size_estimates(scene, runtime)
            return False
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed computing full source tiles for resolve-size estimate", exc_info=True)
            clear_resolve_size_estimates(scene, runtime)
            return False

    def _compute_mode_tiles(mode):
        normalized_mode = normalize_texture_quality_mode(mode)
        try:
            from ..render_prep import apply_texture_quality_to_full_tiles
            return canonical_tiles(apply_texture_quality_to_full_tiles(full_source_tiles, normalized_mode))
        except recoverable_exceptions:
            logger.debug(
                "Planetka: failed computing %s tiles for resolve-size estimate",
                normalized_mode,
                exc_info=True,
            )
            return None
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug(
                "Planetka: failed computing %s tiles for resolve-size estimate",
                normalized_mode,
                exc_info=True,
            )
            return None

    full_tiles = _compute_mode_tiles("FULL")
    balanced_tiles = _compute_mode_tiles("BALANCED")
    preview_tiles = _compute_mode_tiles("PREVIEW")

    if full_tiles is None or balanced_tiles is None or preview_tiles is None:
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
    balanced_availability = estimate_download_availability_for_visible_tiles(
        balanced_tiles,
        base_path,
        runtime,
        texture_quality_mode="BALANCED",
    )
    full_bytes = int(max(0, int((full_availability or {}).get("total_bytes", 0) or 0)))
    balanced_bytes = int(max(0, int((balanced_availability or {}).get("total_bytes", 0) or 0)))
    preview_bytes = int(max(0, int((preview_availability or {}).get("total_bytes", 0) or 0)))
    full_available_bytes = int(max(0, int((full_availability or {}).get("available_bytes", 0) or 0)))
    balanced_available_bytes = int(max(0, int((balanced_availability or {}).get("available_bytes", 0) or 0)))
    preview_available_bytes = int(max(0, int((preview_availability or {}).get("available_bytes", 0) or 0)))
    full_download_bytes = int(max(0, int((full_availability or {}).get("download_bytes", 0) or 0)))
    balanced_download_bytes = int(max(0, int((balanced_availability or {}).get("download_bytes", 0) or 0)))
    preview_download_bytes = int(max(0, int((preview_availability or {}).get("download_bytes", 0) or 0)))
    try:
        scene[resolve_estimate_full_bytes_key] = int(max(0, int(full_bytes)))
        scene["planetka_resolve_estimate_balanced_bytes"] = int(max(0, int(balanced_bytes)))
        scene[resolve_estimate_preview_bytes_key] = int(max(0, int(preview_bytes)))
        scene["planetka_resolve_estimate_full_available_bytes"] = int(max(0, int(full_available_bytes)))
        scene["planetka_resolve_estimate_balanced_available_bytes"] = int(max(0, int(balanced_available_bytes)))
        scene["planetka_resolve_estimate_preview_available_bytes"] = int(max(0, int(preview_available_bytes)))
        scene["planetka_resolve_estimate_full_download_bytes"] = int(max(0, int(full_download_bytes)))
        scene["planetka_resolve_estimate_balanced_download_bytes"] = int(max(0, int(balanced_download_bytes)))
        scene["planetka_resolve_estimate_preview_download_bytes"] = int(max(0, int(preview_download_bytes)))
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
        return {"FULL": None, "BALANCED": None, "PREVIEW": None}

    def _read_int(key):
        try:
            if key not in target_scene:
                return None
            return int(max(0, int(target_scene.get(key, 0) or 0)))
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
        "BALANCED": _read_int("planetka_resolve_estimate_balanced_bytes"),
        "PREVIEW": _read_int(resolve_estimate_preview_bytes_key),
        "FULL_AVAILABLE": _read_int("planetka_resolve_estimate_full_available_bytes"),
        "BALANCED_AVAILABLE": _read_int("planetka_resolve_estimate_balanced_available_bytes"),
        "PREVIEW_AVAILABLE": _read_int("planetka_resolve_estimate_preview_available_bytes"),
        "FULL_DOWNLOAD": _read_int("planetka_resolve_estimate_full_download_bytes"),
        "BALANCED_DOWNLOAD": _read_int("planetka_resolve_estimate_balanced_download_bytes"),
        "PREVIEW_DOWNLOAD": _read_int("planetka_resolve_estimate_preview_download_bytes"),
    }


def last_resolved_tiles(scene, runtime=None):
    recoverable_exceptions = _coerce_ctx(runtime).deps.recoverable_exceptions
    try:
        return canonical_tiles(scene.get("planetka_last_resolved_tiles", ()))
    except recoverable_exceptions:
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return tuple()
