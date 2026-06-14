from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


DIAG_KEY_LAST_RESOLVE_MS = "planetka_diag_last_resolve_ms"
DIAG_KEY_LAST_TILE_COUNT = "planetka_diag_last_tile_count"
DIAG_KEY_LAST_FALLBACK_COUNT = "planetka_diag_last_fallback_count"
DIAG_KEY_RESOLVE_ASSETS_MS = "planetka_diag_resolve_assets_ms"
DIAG_KEY_RESOLVE_TILE_SELECT_MS = "planetka_diag_resolve_tile_select_ms"
DIAG_KEY_RESOLVE_STREAM_MS = "planetka_diag_resolve_stream_ms"
DIAG_KEY_RESOLVE_MESH_MS = "planetka_diag_resolve_mesh_ms"
DIAG_KEY_RESOLVE_SHADER_MS = "planetka_diag_resolve_shader_ms"
DIAG_KEY_RESOLVE_POST_MS = "planetka_diag_resolve_post_ms"
DIAG_KEY_RESOLVE_POST_DELETE_MS = "planetka_diag_resolve_post_delete_ms"
DIAG_KEY_RESOLVE_POST_MARK_MS = "planetka_diag_resolve_post_mark_ms"
DIAG_KEY_RESOLVE_POST_PREVIEW_MS = "planetka_diag_resolve_post_preview_ms"
DIAG_KEY_RESOLVE_UNACCOUNTED_MS = "planetka_diag_resolve_unaccounted_ms"
DIAG_KEY_CAMERA_ALTITUDE_BU = "planetka_diag_camera_altitude_bu"
DIAG_KEY_NEAREST_VISIBLE_DISTANCE_BU = "planetka_diag_nearest_visible_distance_bu"
DIAG_KEY_RESOLVE_REQUIRED_MPP_M = "planetka_diag_resolve_required_mpp_m"
DIAG_KEY_RESOLVE_SAFETY_STATE = "planetka_diag_resolve_safety_state"
DIAG_KEY_RESOLVE_TEXTURES_MB = "planetka_diag_resolve_textures_mb"
DIAG_KEY_RESOLVE_DOWNLOAD_MS = "planetka_diag_resolve_download_ms"
DIAG_KEY_RESOLVE_DOWNLOADED_MB = "planetka_diag_resolve_downloaded_mb"
DIAG_KEY_RESOLVE_DOWNLOAD_THREAD_MS = "planetka_diag_resolve_download_thread_ms"
DIAG_KEY_RESOLVE_FULL_QUALITY_COST_BYTES = "planetka_diag_resolve_full_quality_cost_bytes"


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


def write_tile_view_diagnostics(scene, camera_altitude_bu, nearest_visible_distance_bu):
    _set_scene_value(scene, DIAG_KEY_CAMERA_ALTITUDE_BU, None if camera_altitude_bu is None else float(camera_altitude_bu))
    _set_scene_value(
        scene,
        DIAG_KEY_NEAREST_VISIBLE_DISTANCE_BU,
        None if nearest_visible_distance_bu is None else float(nearest_visible_distance_bu),
    )


def write_resolve_diagnostics(scene, tile_count, resolve_ms, fallback_count, breakdown=None):
    _set_scene_value(scene, DIAG_KEY_LAST_TILE_COUNT, int(max(0, int(tile_count))))
    _set_scene_value(scene, DIAG_KEY_LAST_RESOLVE_MS, max(0.0, float(resolve_ms)))
    _set_scene_value(scene, DIAG_KEY_LAST_FALLBACK_COUNT, int(max(0, int(fallback_count))))
    breakdown = breakdown or {}
    _set_scene_value(scene, DIAG_KEY_RESOLVE_ASSETS_MS, float(max(0.0, breakdown.get("assets_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_TILE_SELECT_MS, float(max(0.0, breakdown.get("tile_select_ms", 0.0))))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_STREAM_MS, float(max(0.0, breakdown.get("stream_ms", 0.0))))
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
    _set_scene_value(scene, DIAG_KEY_RESOLVE_DOWNLOAD_MS, breakdown.get("download_ms"))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_DOWNLOADED_MB, breakdown.get("downloaded_mb"))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_DOWNLOAD_THREAD_MS, breakdown.get("download_thread_ms"))
    _set_scene_value(scene, DIAG_KEY_RESOLVE_FULL_QUALITY_COST_BYTES, breakdown.get("full_quality_cost_bytes"))

