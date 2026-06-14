_VIEW_TELEMETRY_CTX = None

def _require_ctx():
    ctx = _VIEW_TELEMETRY_CTX
    if ctx is None:
        raise RuntimeError("Planetka view telemetry context is not configured.")
    return ctx


def _is_context(value):
    return hasattr(value, "deps")


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


def _ctx_set_camera_inside_earth_warning(ctx, scene):
    deps = ctx.deps
    if scene is None:
        return ""
    message = "Below Earth's surface"
    try:
        scene[deps.camera_inside_earth_warning_key] = str(message)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing inside-Earth warning", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing inside-Earth warning", exc_info=True)
    return message


def set_camera_inside_earth_warning(scene, ctx=None):
    return _ctx_set_camera_inside_earth_warning(_coerce_ctx(ctx), scene)


def resolve_scope_altitude_info(scene, runtime=None, scope_mode="AUTO"):
    result = {
        "inside_earth": False,
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

    try:
        camera_info = tile_utils.get_camera_info(scene, scope_mode=str(scope_mode or "AUTO"))
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
        radius_bu = float(tile_utils.get_earth_radius_blender_units(earth))
        altitude_bu = float((camera_position - earth_center).length) - radius_bu
        inside_epsilon_bu = float(max(1e-9, radius_bu * 1e-6))
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
        return result
    except (RuntimeError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        deps.logger.debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
        return result

    result["scope_used"] = str(camera_info.get("scope_used", "CAMERA") or "CAMERA")
    result["altitude_bu"] = altitude_bu
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


def _ctx_enforce_texture_quality_mode(ctx, scene, requested_mode):
    del ctx
    mode = normalize_texture_quality_mode(requested_mode)
    return mode


def enforce_texture_quality_mode(scene, requested_mode, ctx=None):
    return _ctx_enforce_texture_quality_mode(_coerce_ctx(ctx), scene, requested_mode)


def _ctx_output_resolution_signature(ctx, scene):
    render = getattr(scene, "render", None) if scene is not None else None
    if render is None:
        return None
    props = getattr(scene, "planetka_public", None) if scene is not None else None
    texture_quality_mode = "PREVIEW"
    try:
        texture_quality_mode = enforce_texture_quality_mode(
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


def canonical_tiles(tiles):
    if not isinstance(tiles, (list, tuple)):
        return tuple()
    return tuple(sorted(str(tile) for tile in tiles if tile))


def estimate_download_bytes_for_visible_tiles(tiles, runtime=None, texture_quality_mode="PREVIEW"):
    estimate = estimate_download_availability_for_visible_tiles(
        tiles,
        runtime=runtime,
        texture_quality_mode=texture_quality_mode,
    )
    try:
        return int(max(0, int(estimate.get("total_bytes", 0) or 0)))
    except (AttributeError, TypeError, ValueError):
        return 0


def estimate_download_availability_for_visible_tiles(
    tiles,
    runtime=None,
    texture_quality_mode="PREVIEW",
    allow_remote_probe=False,
):
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
    try:
        estimate = streaming_utils.estimate_remote_download_bytes_for_visible_tiles(
            safe_tiles,
            allow_remote_probe=bool(allow_remote_probe),
            texture_quality_mode=normalized_mode,
        )
    except recoverable_exceptions:
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
