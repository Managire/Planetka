import math


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


def tag_view3d_redraw(runtime):
    bpy_module = runtime["bpy"]
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
    _realtime_view_camera_info = runtime["_realtime_view_camera_info"]
    _earth_radius_blender_units = runtime["_earth_radius_blender_units"]
    _intersect_ray_sphere_nearest = runtime["_intersect_ray_sphere_nearest"]
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

    camera_info = _realtime_view_camera_info(scene)
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

    radius_bu = _earth_radius_blender_units(earth)
    hit_local = _intersect_ray_sphere_nearest(cam_pos_local, cam_forward_local, radius_bu)

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
