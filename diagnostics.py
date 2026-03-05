from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


DIAG_KEY_LAST_RESOLVE_MS = "planetka_diag_last_resolve_ms"
DIAG_KEY_LAST_TILE_COUNT = "planetka_diag_last_tile_count"
DIAG_KEY_LAST_FALLBACK_COUNT = "planetka_diag_last_fallback_count"
DIAG_KEY_RESOLVE_ASSETS_MS = "planetka_diag_resolve_assets_ms"
DIAG_KEY_RESOLVE_TILE_SELECT_MS = "planetka_diag_resolve_tile_select_ms"
DIAG_KEY_RESOLVE_MESH_MS = "planetka_diag_resolve_mesh_ms"
DIAG_KEY_RESOLVE_SHADER_MS = "planetka_diag_resolve_shader_ms"
DIAG_KEY_RESOLVE_POST_MS = "planetka_diag_resolve_post_ms"
DIAG_KEY_RESOLVE_POST_DELETE_MS = "planetka_diag_resolve_post_delete_ms"
DIAG_KEY_RESOLVE_POST_MARK_MS = "planetka_diag_resolve_post_mark_ms"
DIAG_KEY_RESOLVE_POST_PREVIEW_MS = "planetka_diag_resolve_post_preview_ms"
DIAG_KEY_RESOLVE_UNACCOUNTED_MS = "planetka_diag_resolve_unaccounted_ms"
DIAG_KEY_CAMERA_ALTITUDE_BU = "planetka_diag_camera_altitude_bu"
DIAG_KEY_CAMERA_ALTITUDE_KM = "planetka_diag_camera_altitude_km"
DIAG_KEY_NEAREST_VISIBLE_DISTANCE_BU = "planetka_diag_nearest_visible_distance_bu"
DIAG_KEY_NEAREST_VISIBLE_DISTANCE_KM = "planetka_diag_nearest_visible_distance_km"
DIAG_KEY_VIEW_LATITUDE_DEG = "planetka_diag_view_latitude_deg"
DIAG_KEY_VIEW_LONGITUDE_DEG = "planetka_diag_view_longitude_deg"
DIAG_KEY_VIEW_ALTITUDE_KM = "planetka_diag_view_altitude_km"
DIAG_KEY_VIEW_ESTIMATED_MPP_M = "planetka_diag_view_estimated_mpp_m"
DIAG_KEY_VIEW_ESTIMATED_SAFETY_STATE = "planetka_diag_view_estimated_safety_state"
DIAG_KEY_RESOLVE_REQUIRED_MPP_M = "planetka_diag_resolve_required_mpp_m"
DIAG_KEY_RESOLVE_SAFETY_STATE = "planetka_diag_resolve_safety_state"
DIAG_KEY_RESOLVE_TEXTURES_MB = "planetka_diag_resolve_textures_mb"


def _set_scene_value(scene, key, value):
    if not scene:
        return
    try:
        if value is None:
            if key in scene:
                del scene[key]
            return
        scene[key] = value
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass


def _get_scene_value(scene, key, default=None):
    if not scene:
        return default
    try:
        return scene.get(key, default)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return default


def _distance_bu_to_km(distance_bu, earth_radius_bu):
    if distance_bu is None or earth_radius_bu is None:
        return None
    safe_radius = max(float(earth_radius_bu), 1e-9)
    return (float(distance_bu) * 6371.0) / safe_radius


def write_tile_view_diagnostics(scene, camera_altitude_bu, nearest_visible_distance_bu, earth_radius_bu):
    camera_altitude_km = _distance_bu_to_km(camera_altitude_bu, earth_radius_bu)
    nearest_visible_distance_km = _distance_bu_to_km(nearest_visible_distance_bu, earth_radius_bu)
    _set_scene_value(scene, DIAG_KEY_CAMERA_ALTITUDE_BU, None if camera_altitude_bu is None else float(camera_altitude_bu))
    _set_scene_value(scene, DIAG_KEY_CAMERA_ALTITUDE_KM, None if camera_altitude_km is None else float(camera_altitude_km))
    _set_scene_value(
        scene,
        DIAG_KEY_NEAREST_VISIBLE_DISTANCE_BU,
        None if nearest_visible_distance_bu is None else float(nearest_visible_distance_bu),
    )
    _set_scene_value(
        scene,
        DIAG_KEY_NEAREST_VISIBLE_DISTANCE_KM,
        None if nearest_visible_distance_km is None else float(nearest_visible_distance_km),
    )


def write_realtime_view_diagnostics(
    scene,
    latitude_deg,
    longitude_deg,
    altitude_km,
    estimated_mpp_m=None,
    estimated_safety_state=None,
):
    _set_scene_value(
        scene,
        DIAG_KEY_VIEW_LATITUDE_DEG,
        None if latitude_deg is None else float(latitude_deg),
    )
    _set_scene_value(
        scene,
        DIAG_KEY_VIEW_LONGITUDE_DEG,
        None if longitude_deg is None else float(longitude_deg),
    )
    _set_scene_value(
        scene,
        DIAG_KEY_VIEW_ALTITUDE_KM,
        None if altitude_km is None else float(altitude_km),
    )
    _set_scene_value(
        scene,
        DIAG_KEY_VIEW_ESTIMATED_MPP_M,
        None if estimated_mpp_m is None else float(estimated_mpp_m),
    )
    _set_scene_value(
        scene,
        DIAG_KEY_VIEW_ESTIMATED_SAFETY_STATE,
        None if estimated_safety_state is None else str(estimated_safety_state),
    )


def write_resolve_diagnostics(scene, tile_count, resolve_ms, fallback_count, breakdown=None):
    _set_scene_value(scene, DIAG_KEY_LAST_TILE_COUNT, int(max(0, int(tile_count))))
    _set_scene_value(scene, DIAG_KEY_LAST_RESOLVE_MS, max(0.0, float(resolve_ms)))
    _set_scene_value(scene, DIAG_KEY_LAST_FALLBACK_COUNT, int(max(0, int(fallback_count))))
    breakdown = breakdown or {}
    _set_scene_value(scene, DIAG_KEY_RESOLVE_ASSETS_MS, float(max(0.0, breakdown.get("assets_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_TILE_SELECT_MS, float(max(0.0, breakdown.get("tile_select_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_MESH_MS, float(max(0.0, breakdown.get("mesh_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_SHADER_MS, float(max(0.0, breakdown.get("shader_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_POST_MS, float(max(0.0, breakdown.get("post_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_POST_DELETE_MS, float(max(0.0, breakdown.get("post_delete_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_POST_MARK_MS, float(max(0.0, breakdown.get("post_mark_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_POST_PREVIEW_MS, float(max(0.0, breakdown.get("post_preview_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_UNACCOUNTED_MS, float(max(0.0, breakdown.get("unaccounted_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_REQUIRED_MPP_M, breakdown.get("required_mpp_m"))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_SAFETY_STATE, breakdown.get("resolution_safety"))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_TEXTURES_MB, breakdown.get("loaded_textures_mb"))


def read_diagnostics(scene):
    return {
        "last_tile_count": _get_scene_value(scene, DIAG_KEY_LAST_TILE_COUNT),
        "last_resolve_ms": _get_scene_value(scene, DIAG_KEY_LAST_RESOLVE_MS),
        "last_fallback_count": _get_scene_value(scene, DIAG_KEY_LAST_FALLBACK_COUNT),
        "resolve_assets_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_ASSETS_MS),
        "resolve_tile_select_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_TILE_SELECT_MS),
        "resolve_mesh_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_MESH_MS),
        "resolve_shader_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_SHADER_MS),
        "resolve_post_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_POST_MS),
        "resolve_post_delete_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_POST_DELETE_MS),
        "resolve_post_mark_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_POST_MARK_MS),
        "resolve_post_preview_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_POST_PREVIEW_MS),
        "resolve_unaccounted_ms": _get_scene_value(scene, DIAG_KEY_RESOLVE_UNACCOUNTED_MS),
        "camera_altitude_bu": _get_scene_value(scene, DIAG_KEY_CAMERA_ALTITUDE_BU),
        "camera_altitude_km": _get_scene_value(scene, DIAG_KEY_CAMERA_ALTITUDE_KM),
        "nearest_visible_distance_bu": _get_scene_value(scene, DIAG_KEY_NEAREST_VISIBLE_DISTANCE_BU),
        "nearest_visible_distance_km": _get_scene_value(scene, DIAG_KEY_NEAREST_VISIBLE_DISTANCE_KM),
        "view_latitude_deg": _get_scene_value(scene, DIAG_KEY_VIEW_LATITUDE_DEG),
        "view_longitude_deg": _get_scene_value(scene, DIAG_KEY_VIEW_LONGITUDE_DEG),
        "view_altitude_km": _get_scene_value(scene, DIAG_KEY_VIEW_ALTITUDE_KM),
        "view_estimated_mpp_m": _get_scene_value(scene, DIAG_KEY_VIEW_ESTIMATED_MPP_M),
        "view_estimated_safety_state": _get_scene_value(scene, DIAG_KEY_VIEW_ESTIMATED_SAFETY_STATE),
        "resolve_required_mpp_m": _get_scene_value(scene, DIAG_KEY_RESOLVE_REQUIRED_MPP_M),
        "resolve_safety_state": _get_scene_value(scene, DIAG_KEY_RESOLVE_SAFETY_STATE),
        "resolve_textures_mb": _get_scene_value(scene, DIAG_KEY_RESOLVE_TEXTURES_MB),
    }
