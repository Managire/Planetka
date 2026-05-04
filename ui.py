"""Planetka UI panels and telemetry rendering."""

import bpy
import datetime
import time

from .asset_builder import PLANETKA_ROOT_OBJECT_NAME
from .auth import (
    AuthApiError,
    allows_animation_render_for_context,
    allows_balanced_full_quality_for_context,
    get_account_tier,
    get_connected_email,
    get_status_message,
    has_unrestricted_quality_access,
    is_authenticated,
    sync_account_profile,
)
from .extension_prefs import get_earth_object, get_prefs
from .geonames_db import get_search_status_text
from .diagnostics import read_diagnostics
from .r2_source import get_download_progress, get_local_source_stale_notice, is_download_active, is_remote_source_configured
from .planetka_ops.scene_setup_ops import is_scene_background_black
from .updater import get_public_status as get_updater_public_status
from .animation_tools import (
    ANIMATION_RENDER_STATUS_ICON_KEY,
    ANIMATION_RENDER_STATUS_TEXT_KEY,
    ANIMATION_STATS_SEGMENTS_KEY,
)
from .render_prep import (
    LAST_MANUAL_RESOLVE_DOWNLOADED_MB_KEY,
    LAST_MANUAL_RESOLVE_DOWNLOADED_GB_KEY,
    LAST_MANUAL_RESOLVE_TILE_COUNT_KEY,
    LAST_MANUAL_RESOLVE_TOTAL_SECONDS_KEY,
)
from .state import (
    ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY,
    ADD_EARTH_BUTTON_SCALE_X,
    ADD_EARTH_BUTTON_SCALE_Y,
    _is_render_job_active,
    get_camera_inside_earth_warning,
    is_final_animation_render_active,
    get_resolve_size_estimates,
    get_resolve_runtime_status,
    logger,
)

SHOW_INTERNAL_ANIMATION_UI = False
CLIPPING_AUTO_NOTICE_KEY = "planetka_status_clip_auto_notice"
CACHE_NOTICE_KEY = "planetka_status_cache_notice"
RADIUS_SYNC_NOTICE_KEY = "planetka_status_radius_sync_notice"
RESOLVE_FAILURE_FLAG_KEY = "planetka_resolve_integrity_failed"
RESOLVE_FAILURE_MESSAGE_KEY = "planetka_resolve_integrity_message"
EARTH_RADIUS_SAFE_MIN_BU = 0.2
EARTH_RADIUS_SAFE_MAX_BU = 20.0
LOW_ALTITUDE_WARNING_EPS_KM = 0.05
ACCOUNT_PANEL_PROFILE_SYNC_INTERVAL_SEC = 120.0
_ACCOUNT_PANEL_LAST_PROFILE_SYNC_AT = 0.0


def _float_close(value, target, tol=1e-4):
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except (TypeError, ValueError):
        return False


def _fmt_int(value):
    if value is None:
        return "—"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} ms"
    except (TypeError, ValueError):
        return "—"


def _fmt_km(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} km"
    except (TypeError, ValueError):
        return "—"


def _fmt_deg(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.4f}°"
    except (TypeError, ValueError):
        return "—"


def _fmt_m(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} m"
    except (TypeError, ValueError):
        return "—"


def _fmt_mb(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.0f} MB"
    except (TypeError, ValueError):
        return "—"


def _fmt_mbps(downloaded_mb, download_ms):
    if downloaded_mb is None or download_ms is None:
        return "—"
    try:
        size_mb = float(downloaded_mb)
        elapsed_ms = float(download_ms)
        if elapsed_ms <= 0.0:
            return "—"
        return f"{size_mb / (elapsed_ms / 1000.0):.2f} MB/s"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def _waypoint_label(index):
    try:
        idx = int(max(0, int(index)))
    except (TypeError, ValueError):
        idx = 0
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    base = len(alphabet)
    label = ""
    while True:
        label = alphabet[idx % base] + label
        idx = (idx // base) - 1
        if idx < 0:
            break
    return label


def _status_activity_suffix(running):
    if not bool(running):
        return ""
    phase = int(datetime.datetime.now().timestamp() * 2.0) % 3
    return "." * (phase + 1)


def _status_icon(code):
    token = str(code or "").upper()
    if token == "PREPARING":
        return "TIME"
    if token == "DOWNLOADING":
        return "IMPORT"
    if token in {"FINALIZING", "FINALIZE_QUEUED"}:
        return "MOD_REMESH"
    if token == "QUEUED":
        return "SORTTIME"
    if token == "MONITORING":
        return "VIEW_CAMERA"
    if token == "IDLE":
        return "CHECKMARK"
    return "INFO"


def _is_animation_render_running():
    try:
        if callable(is_final_animation_render_active):
            return bool(is_final_animation_render_active())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        if callable(_is_render_job_active):
            return bool(_is_render_job_active())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


def _animation_render_status_for_ui(scene):
    text = ""
    icon = "RENDER_ANIMATION"
    if scene is not None:
        try:
            text = str(scene.get(ANIMATION_RENDER_STATUS_TEXT_KEY, "") or "").strip()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            text = ""
        try:
            icon = str(scene.get(ANIMATION_RENDER_STATUS_ICON_KEY, icon) or icon).strip() or icon
        except (AttributeError, RuntimeError, TypeError, ValueError):
            icon = "RENDER_ANIMATION"
    return (text or "Rendering Animation", icon or "RENDER_ANIMATION")


def _planetka_controls_enabled(base_enabled=True):
    return bool(base_enabled) and (not _is_animation_render_running())


def _action_has_keyframes(action):
    if action is None:
        return False
    try:
        fcurves = getattr(action, "fcurves", None)
        if fcurves is not None:
            for fcurve in fcurves:
                if int(len(getattr(fcurve, "keyframe_points", ()) or ())) > 0:
                    return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        layers = getattr(action, "layers", None)
        if layers is not None:
            for layer in layers:
                for strip in getattr(layer, "strips", ()) or ():
                    for channelbag in getattr(strip, "channelbags", ()) or ():
                        for fcurve in getattr(channelbag, "fcurves", ()) or ():
                            if int(len(getattr(fcurve, "keyframe_points", ()) or ())) > 0:
                                return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


def _animation_data_has_nla_tracks(animation_data):
    if animation_data is None:
        return False
    tracks = getattr(animation_data, "nla_tracks", None)
    if tracks is None:
        return False
    try:
        if int(len(tracks)) > 0:
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for _track in tracks:
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


def _id_block_has_animation_bindings(id_block):
    if id_block is None:
        return False
    try:
        animation_data = getattr(id_block, "animation_data", None)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        animation_data = None
    if animation_data is None:
        return False
    try:
        if _action_has_keyframes(getattr(animation_data, "action", None)):
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return _animation_data_has_nla_tracks(animation_data)


def _navigation_has_camera_keyframe_lock(scene):
    if scene is None:
        return False, False, False
    try:
        camera = getattr(scene, "camera", None)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        camera = None
    if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
        return False, False, False
    object_locked = _id_block_has_animation_bindings(camera)
    lens_locked = _id_block_has_animation_bindings(getattr(camera, "data", None))
    return bool(object_locked or lens_locked), bool(object_locked), bool(lens_locked)


def _resolve_runtime_display(scene):
    progress = get_download_progress()
    active_download = is_download_active()
    downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
    total_bytes = int(progress.get("total_bytes", 0) or 0)
    downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
    total_mb = float(total_bytes) / (1024.0 * 1024.0)
    runtime = get_resolve_runtime_status(scene)
    runtime_code = str(runtime.get("code", "IDLE") or "IDLE").upper()
    runtime_text = str(runtime.get("text", "Idle") or "Idle")
    if runtime_code == "MONITORING":
        runtime_code = "IDLE"
        runtime_text = "Idle"
    animation_render_running = _is_animation_render_running()
    if active_download and runtime_code in {"IDLE", "MONITORING"}:
        runtime_code = "DOWNLOADING"
        runtime_text = "Animation Downloading" if animation_render_running else "Downloading"
    if runtime_code == "PREPARING":
        runtime_text = "Preparing Download"
    if runtime_code == "DOWNLOADING":
        runtime_text = "Animation Downloading" if animation_render_running else "Downloading"
        if total_bytes > 0:
            runtime_text = f"{runtime_text} ({downloaded_mb:.2f} / {total_mb:.2f} MB)"
        else:
            runtime_text = f"{runtime_text} ({downloaded_mb:.2f} MB)"
    return runtime, runtime_code, runtime_text


def _earth_radius_bu_for_ui(scene):
    earth = get_earth_object()
    if earth is None:
        return None
    try:
        operators_module = __import__(f"{__package__}.operators", fromlist=["_earth_radius_blender_units"])
        radius_fn = getattr(operators_module, "_earth_radius_blender_units", None)
        if callable(radius_fn):
            radius = float(radius_fn(earth))
            if radius > 0.0:
                return radius
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        stored_local_radius = float(earth.get("planetka_surface_local_radius", 0.0))
        if stored_local_radius > 0.0:
            world_scale = earth.matrix_world.to_scale()
            max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
            return float(stored_local_radius) * float(max_scale)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _auto_adjust_clipping_for_status(scene):
    _ = scene
    return []


def _non_black_background_warning(scene):
    _ = scene
    return None


def _clipping_button_text(clipping_warning):
    if not isinstance(clipping_warning, dict):
        return "Change Clipping Automatically"
    try:
        clip_start = float(clipping_warning.get("clip_start", 0.0))
        clip_end = float(clipping_warning.get("clip_end", 0.0))
    except (TypeError, ValueError):
        return "Change Clipping Automatically"

    breach_min = bool(clipping_warning.get("breach_min", False))
    breach_max = bool(clipping_warning.get("breach_max", False))
    if breach_min:
        new_start = max(1e-9, clip_start / 10.0)
        return f"Change Clip Start to {new_start:.6g}"
    if breach_max:
        new_end = max(max(1e-9, clip_start) * 1.000001, clip_end * 10.0)
        return f"Change Clip End to {new_end:.6g}"
    return "Change Clipping Automatically"


def _radius_needs_clipping_adjustment(radius_bu):
    try:
        radius = float(radius_bu)
    except (TypeError, ValueError):
        return False
    return radius < float(EARTH_RADIUS_SAFE_MIN_BU) or radius > float(EARTH_RADIUS_SAFE_MAX_BU)


class _PLANETKA_PT_BaseSection:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    # Keep Planetka tab ordering behind Blender built-in tabs.
    # Blender's tab/category ordering can be influenced by low panel bl_order values.
    bl_order = 9000
    bl_options = {'DEFAULT_CLOSED'}


def _has_earth():
    return get_earth_object() is not None


def _resolve_failure_notice(scene=None):
    target_scene = scene if scene is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return ""
    try:
        failed = bool(target_scene.get(RESOLVE_FAILURE_FLAG_KEY, False))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        failed = False
    if not failed:
        return ""
    try:
        message = str(target_scene.get(RESOLVE_FAILURE_MESSAGE_KEY, "") or "").strip()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        message = ""
    return message or "Resolve failed. Please click Rebuild Earth"


def _has_resolve_failure_notice(scene=None):
    return bool(_resolve_failure_notice(scene))


def _resolve_failure_message_for_ui(scene=None):
    message = _resolve_failure_notice(scene)
    if message:
        return message
    target_scene = scene if scene is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return ""
    try:
        return str(target_scene.get("planetka_last_resolve_error", "") or "").strip()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return ""


def _inside_earth_warning_for_ui(scene=None):
    return str(get_camera_inside_earth_warning(scene) or "").strip()


def _max_proximity_altitude_km_for_ui(scene=None):
    target_scene = scene if scene is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return None
    props = getattr(target_scene, "planetka", None)
    if props is None:
        return None

    try:
        diag = read_diagnostics(target_scene)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        diag = {}

    lat_value = diag.get("view_latitude_deg", None)
    lon_value = diag.get("view_longitude_deg", None)
    try:
        if lat_value is None:
            lat_value = float(getattr(props, "nav_latitude_deg", 0.0))
        else:
            lat_value = float(lat_value)
        if lon_value is None:
            lon_value = float(getattr(props, "nav_longitude_deg", 0.0))
        else:
            lon_value = float(lon_value)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None

    try:
        from .extension_prefs import get_earth_object
        from .operators import _earth_radius_blender_units, _max_proximity_altitude_km
    except (ImportError, ModuleNotFoundError):
        logger.debug("Planetka: failed importing Max Proximity helpers for low-altitude warning", exc_info=True)
        return None

    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    try:
        earth_radius_bu = float(_earth_radius_blender_units(earth_obj))
        threshold_km, _note = _max_proximity_altitude_km(
            target_scene,
            earth_obj,
            earth_radius_bu,
            float(lon_value),
            float(lat_value),
        )
        if threshold_km is None:
            return None
        return max(0.0, float(threshold_km))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing Max Proximity threshold for low-altitude warning", exc_info=True)
        return None


def _low_altitude_warning_for_ui(scene=None):
    target_scene = scene if scene is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return ""
    try:
        diag = read_diagnostics(target_scene)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""
    try:
        current_altitude_km = diag.get("view_altitude_km", None)
        if current_altitude_km is None:
            current_altitude_km = float(getattr(getattr(target_scene, "planetka", None), "nav_altitude_km", 0.0))
        else:
            current_altitude_km = float(current_altitude_km)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""
    threshold_km = _max_proximity_altitude_km_for_ui(target_scene)
    if threshold_km is None:
        return ""
    if float(current_altitude_km) + float(LOW_ALTITUDE_WARNING_EPS_KM) < float(threshold_km):
        return "Low altitude"
    return ""


def _is_connected():
    from .extension_prefs import get_prefs

    prefs = get_prefs()
    if not is_authenticated(prefs):
        return False
    try:
        return bool(get_account_tier(prefs))
    except AuthApiError:
        return False


def _account_panel_should_default_collapsed(context=None):
    if not _is_connected():
        return False
    target_scene = getattr(context, "scene", None) if context is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return False
    try:
        return bool(target_scene.get(ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY, False))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return False


def _connected_account_tier():
    prefs = get_prefs()
    try:
        return str(get_account_tier(prefs) or "").strip().lower()
    except AuthApiError:
        return ""


def _account_tier_label(tier):
    safe_tier = str(tier or "").strip().lower()
    if safe_tier == "personal":
        return "Personal"
    if safe_tier == "commercial":
        return "Commercial"
    if safe_tier == "free":
        return "Free"
    return "Invalid"


def _account_tier_display_label(tier, unrestricted=False):
    base_label = _account_tier_label(tier)
    safe_tier = str(tier or "").strip().lower()
    if unrestricted and safe_tier in {"free", "personal"}:
        return f"{base_label} (Unrestricted)"
    return base_label


def _is_paid_connected_account():
    if not _is_connected():
        return False
    return _connected_account_tier() in {"personal", "commercial"}


def _full_texture_quality_allowed():
    return _connected_account_tier() == "commercial"


def _is_cloud_source_mode():
    return True


def _is_earth_workflow_enabled():
    if not _has_earth():
        return False
    if _is_cloud_source_mode():
        return _is_connected()
    return True


def _is_animation_prepared(scene):
    if scene is None:
        return False
    try:
        return int(scene.get(ANIMATION_STATS_SEGMENTS_KEY, 0)) > 0
    except (TypeError, ValueError):
        return False


def _draw_animation_ready_message(layout):
    message = layout.box()
    message.alert = False
    message.label(text="Quick Preview Ready.", icon="CHECKMARK")
    message.label(text="Clear Quick Preview to return to normal editing.", icon="INFO")
    return message


def _show_internal_animation_ui():
    return bool(SHOW_INTERNAL_ANIMATION_UI)


def _api_key_inline_status(prefs, connected, status_message):
    if connected:
        return "", "NONE", False

    message = str(status_message or "").strip()
    if not message:
        return "", "NONE", False

    lowered = message.lower()
    invalid_tokens = (
        "invalid planetka api key",
        "invalid_api_key",
        "api key expired",
        "api key is revoked",
    )
    if any(token in lowered for token in invalid_tokens):
        return "Key invalid", "ERROR", True
    if "critical account tier integrity error" in lowered or "tier integrity" in lowered:
        return "Critical tier integrity error", "ERROR", True

    return "Connect failed", "ERROR", True


def _draw_addon_update_controls(layout):
    try:
        updater = get_updater_public_status()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        logger.debug("Planetka: failed reading updater status in settings panel", exc_info=True)
        updater = {}
    updater_ready = bool(updater.get("update_ready", False))
    latest_version = str(updater.get("latest_version") or "").strip()
    current_version = str(updater.get("current_version") or "").strip()

    version_row = layout.row()
    version_row.label(text=f"Addon version: {current_version or 'unknown'}", icon="BLENDER")
    updates_row = layout.row()
    updates_row.operator("planetka.check_updates", text="Check for updates", icon="FILE_REFRESH")
    if updater_ready and latest_version:
        row = layout.row()
        row.alert = True
        row.label(text=f"Update available: {latest_version}", icon="ERROR")
        row.operator("planetka.update_now", text="Update now", icon="IMPORT")


def _draw_account_panel(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False

    from .extension_prefs import get_prefs

    global _ACCOUNT_PANEL_LAST_PROFILE_SYNC_AT

    prefs = get_prefs()
    connected = _is_connected()
    now_ts = time.time()
    if connected and (now_ts - float(_ACCOUNT_PANEL_LAST_PROFILE_SYNC_AT)) >= float(ACCOUNT_PANEL_PROFILE_SYNC_INTERVAL_SEC):
        _ACCOUNT_PANEL_LAST_PROFILE_SYNC_AT = now_ts
        try:
            sync_account_profile(prefs)
        except (AuthApiError, TypeError, ValueError, RuntimeError, AttributeError):
            logger.debug("Planetka: account panel profile sync failed", exc_info=True)
    connected = _is_connected()
    status_message = get_status_message(prefs)
    key_text = str(getattr(prefs, "auth_api_key_input", "") or "").strip()
    key_mask = str(getattr(prefs, "auth_api_key_mask", "") or "").strip()
    stored_key = str(getattr(prefs, "auth_api_key", "") or "").strip()
    key_locked = bool(connected)
    inline_status_text, inline_status_icon, inline_status_alert = _api_key_inline_status(
        prefs,
        connected,
        status_message,
    )

    request_row = layout.row()
    request_row.enabled = not key_locked
    request_row.operator("planetka.account_login", text="Request API Key", icon="URL")

    key_row = layout.row(align=True)
    if key_locked:
        key_row.enabled = False
        if key_mask:
            key_row.prop(prefs, "auth_api_key_mask", text="API Key")
        else:
            key_row.prop(prefs, "auth_api_key_input", text="API Key")
    else:
        key_row.enabled = True
        key_row.prop(prefs, "auth_api_key_input", text="API Key")
    if inline_status_text and not connected:
        key_status = key_row.row(align=True)
        key_status.alert = bool(inline_status_alert)
        key_status.label(text=inline_status_text, icon=inline_status_icon)

    key_action_row = layout.row(align=True)
    connect_row = key_action_row.row(align=True)
    connect_row.enabled = (not key_locked) and bool(key_text)
    connect_row.operator("planetka.account_open_login", text="Connect API Key", icon="CHECKMARK")

    try:
        email = str(get_connected_email(prefs) or "").strip()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        email = str(getattr(prefs, "auth_email", "") or "").strip()
    status_icon = "CHECKMARK" if connected else "ERROR"
    status_text = "Status: Connected to Planetka cloud" if connected else "Status: Not connected"
    layout.label(text=status_text, icon=status_icon)
    layout.label(text=f"Account: {email or '-'}", icon="USER")

    if connected:
        credit_payload = {}
        try:
            from .credit_api import get_credit_account
            credit_payload = get_credit_account(force=False)
        except (AuthApiError, TypeError, ValueError, RuntimeError, AttributeError):
            logger.debug("Planetka: failed reading credit account for UI", exc_info=True)
            credit_payload = {}
        credit_known = bool(credit_payload)
        try:
            balance = float(credit_payload.get("balance_credits", 0.0) or 0.0)
        except (TypeError, ValueError, AttributeError):
            balance = 0.0
        try:
            unlocked_count = int(credit_payload.get("unlocked_tile_count", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            unlocked_count = 0
        if bool(credit_payload.get("unlimited_credits", False)):
            layout.label(text="Credits: Unlimited", icon="SOLO_ON")
        elif not credit_known:
            layout.label(text="Credits: —", icon="SOLO_ON")
        else:
            layout.label(text=f"Credits: {balance:.2f}", icon="SOLO_ON")
        layout.label(text=f"Unlocked tiles: {unlocked_count}", icon="TEXTURE")
        unlocked_row = layout.row(align=True)
        unlocked_row.operator("planetka.account_list_unlocked_tiles", text="List Unlocked", icon="TEXT")
        unlocked_row.operator("planetka.account_download_unlocked_tiles", text="Download Unlocked", icon="IMPORT")

    local_row = layout.row()
    local_row.prop(prefs, "local_texture_source_path", text="Local Source")
    auto_row = layout.row()
    auto_row.prop(prefs, "auto_download_unlocked_tiles", text="Download unlocked tiles automatically")
    try:
        auto_enabled = bool(getattr(prefs, "auto_download_unlocked_tiles", False))
        local_path = str(getattr(prefs, "local_texture_source_path", "") or "").strip()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        auto_enabled = False
        local_path = ""
    if auto_enabled and not local_path:
        warning_row = layout.row(align=True)
        warning_row.alert = True
        warning_row.label(text="Select Local Source folder for automatic downloads.", icon="INFO")
    local_notice = get_local_source_stale_notice()
    if local_notice:
        notice_row = layout.row(align=True)
        notice_row.alert = True
        notice_row.label(text=local_notice, icon="INFO")

    action_row = layout.row(align=True)
    logout_row = action_row.row(align=True)
    logout_row.enabled = connected
    logout_row.operator("planetka.account_logout", text="Log Out", icon="X")

    if status_message:
        layout.label(text=status_message, icon="INFO")


def _draw_new_earth(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    prefs = get_prefs()
    connected = _is_connected()
    has_earth = _has_earth()

    if scene is not None and prefs is not None and not has_earth:
        try:
            status = get_updater_public_status()
            current_version = str(status.get("current_version", "") or "").strip() or "unknown"
        except (TypeError, ValueError, AttributeError):
            current_version = "unknown"
        try:
            seen_version = str(getattr(prefs, "create_earth_preflight_seen_version", "") or "").strip()
        except (TypeError, ValueError, AttributeError):
            seen_version = ""
        if seen_version != current_version:
            source_path = str(getattr(prefs, "texture_base_path", "") or "").strip()
            source_ready = bool(is_remote_source_configured(source_path))
            scene_ready = bool(scene is not None and not has_earth)
            preflight_box = layout.box()
            preflight_box.label(text="Create Earth Preflight (info only)", icon="INFO")
            preflight_box.label(
                text=f"Auth: {'Connected' if connected else 'Not connected'}",
                icon="CHECKMARK" if connected else "ERROR",
            )
            preflight_box.label(
                text=f"Source: {'Cloud ready' if source_ready else 'Cloud not ready'}",
                icon="CHECKMARK" if source_ready else "ERROR",
            )
            preflight_box.label(
                text=f"Scene: {'Ready' if scene_ready else 'Not ready'}",
                icon="CHECKMARK" if scene_ready else "ERROR",
            )
            preflight_box.label(
                text=f"Shown once for addon version {current_version}.",
                icon="INFO",
            )
            try:
                status_message = str(get_status_message(prefs) or "").strip()
            except (TypeError, ValueError, AttributeError):
                status_message = ""
            if status_message and not connected:
                preflight_box.label(text=status_message, icon="INFO")
            try:
                prefs.create_earth_preflight_seen_version = current_version
            except (TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed storing Create Earth preflight seen version", exc_info=True)

    row = layout.row()
    row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    row.alert = False
    row.enabled = (not has_earth) and connected
    row.operator("planetka.remove_default_scene", text="Remove Default Scene", icon="TRASH")

    row = layout.row()
    row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    row.alert = False
    row.enabled = (not has_earth) and connected and (not is_scene_background_black(scene))
    row.operator("planetka.set_background_black", text="Set Background to Black", icon="WORLD_DATA")

    row = layout.row()
    row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    row.alert = False
    row.enabled = (not has_earth) and connected
    row.operator("planetka.add_earth", text="Create Earth", icon="WORLD_DATA")
    rebuild_row = layout.row()
    rebuild_row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    rebuild_row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    rebuild_row.alert = False
    rebuild_row.enabled = connected and has_earth
    rebuild_row.operator("planetka.rebuild_earth", text="Rebuild Earth", icon="FILE_REFRESH")

def _last_resolve_summary_text(scene, include_prefix=False):
    summary_tile_count = None
    summary_total_mb = None
    summary_total_seconds = None
    if scene is not None:
        try:
            summary_tile_count = int(scene.get(LAST_MANUAL_RESOLVE_TILE_COUNT_KEY))
        except (TypeError, ValueError, AttributeError):
            summary_tile_count = None
        try:
            summary_total_mb = float(scene.get(LAST_MANUAL_RESOLVE_DOWNLOADED_MB_KEY))
        except (TypeError, ValueError, AttributeError):
            summary_total_mb = None
        if summary_total_mb is None:
            # Backward compatibility: legacy summary stored GB.
            try:
                legacy_gb = float(scene.get(LAST_MANUAL_RESOLVE_DOWNLOADED_GB_KEY))
                summary_total_mb = float(legacy_gb) * 1024.0
            except (TypeError, ValueError, AttributeError):
                summary_total_mb = None
        try:
            summary_total_seconds = float(scene.get(LAST_MANUAL_RESOLVE_TOTAL_SECONDS_KEY))
        except (TypeError, ValueError, AttributeError):
            summary_total_seconds = None

    if not (
        summary_tile_count is not None
        and summary_total_mb is not None
        and summary_total_seconds is not None
    ):
        return ""

    text = (
        f"{int(max(0, summary_tile_count))} Tiles | "
        f"{max(0.0, float(summary_total_mb)):.0f} MB | "
        f"{max(0.0, float(summary_total_seconds)):.0f}s"
    )
    if include_prefix:
        return f"Last Resolve: {text}"
    return text


def _draw_live_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False

    runtime, runtime_code, _runtime_text = _resolve_runtime_display(scene)

    props = getattr(scene, "planetka", None) if scene else None
    from .extension_prefs import get_prefs
    prefs = get_prefs()

    # Keep informational auto-fix notices visible until the next resolve starts.
    if runtime_code in {"PREPARING", "DOWNLOADING", "FINALIZING", "FINALIZE_QUEUED", "QUEUED"}:
        try:
            if scene is not None and CLIPPING_AUTO_NOTICE_KEY in scene:
                del scene[CLIPPING_AUTO_NOTICE_KEY]
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    clip_sticky_notice = str(getattr(scene, "get", lambda *_: "")(CLIPPING_AUTO_NOTICE_KEY, "") or "").strip() if scene else ""
    if clip_sticky_notice:
        layout.label(text=clip_sticky_notice, icon="INFO")

    cache_sticky_notice = str(getattr(scene, "get", lambda *_: "")(CACHE_NOTICE_KEY, "") or "").strip() if scene else ""
    if cache_sticky_notice:
        layout.label(text=cache_sticky_notice, icon="INFO")

    radius_sync_notice = str(getattr(scene, "get", lambda *_: "")(RADIUS_SYNC_NOTICE_KEY, "") or "").strip() if scene else ""
    if radius_sync_notice:
        notice_row = layout.row(align=True)
        notice_row.alert = True
        notice_row.label(text=radius_sync_notice, icon="ERROR")

    if props is not None and is_authenticated(prefs):
        current_mode = str(getattr(props, "texture_quality_mode", "PREVIEW") or "PREVIEW").strip().upper()
        estimates = get_resolve_size_estimates(scene)

        def _estimate_mb_label(mode):
            mode_key = str(mode or "").upper()
            try:
                size_bytes = estimates.get(mode_key)
            except (AttributeError, TypeError, ValueError):
                size_bytes = None
            if size_bytes is None:
                return "— MB"
            try:
                size_mb = float(size_bytes) / float(1024.0 ** 2)
            except (TypeError, ValueError, ZeroDivisionError):
                return "— MB"
            return f"{max(0.0, size_mb):.0f} MB"

        def _estimate_credit_label(mode):
            mode_key = str(mode or "").upper()
            if mode_key == "PREVIEW":
                return "Free"
            if bool(credit_unlimited):
                return "Unlimited"
            try:
                credits = estimates.get(f"{mode_key}_CREDITS")
                if credits is None:
                    return "— credits"
                return f"{max(0.0, float(credits)):.2f} credits"
            except (AttributeError, TypeError, ValueError):
                return "— credits"

        quality_box = layout.box()
        header_row = quality_box.row(align=True)
        header_row.use_property_split = False
        header_row.use_property_decorate = False
        header_row.label(text="Data Downloading", icon="TEXTURE")
        header_toggle = header_row.row(align=True)
        header_toggle.alignment = 'RIGHT'
        header_toggle.scale_x = 1.1
        header_toggle.label(text="Pause")
        header_toggle.prop(
            props,
            "hold_resolve",
            text="",
            icon="PAUSE",
            toggle=True,
        )

        quality_row = quality_box.row(align=True)
        quality_row.use_property_split = False

        preview_allowed = allows_balanced_full_quality_for_context(prefs=prefs, source=props, requested_mode="PREVIEW")
        balanced_allowed = allows_balanced_full_quality_for_context(prefs=prefs, source=props, requested_mode="BALANCED")
        full_allowed = allows_balanced_full_quality_for_context(prefs=prefs, source=props, requested_mode="FULL")
        credit_balance = 0.0
        credit_known = False
        try:
            from .credit_api import get_credit_account
            credit_account = get_credit_account(force=False)
            credit_known = bool(credit_account)
            credit_unlimited = bool(credit_account.get("unlimited_credits", False))
            credit_balance = float(credit_account.get("balance_credits", 0.0) or 0.0)
        except (AuthApiError, TypeError, ValueError, RuntimeError, AttributeError):
            credit_known = False
            credit_unlimited = False
            credit_balance = 0.0
        try:
            balanced_credits = float(estimates.get("BALANCED_CREDITS", 0.0) or 0.0)
        except (AttributeError, TypeError, ValueError):
            balanced_credits = 0.0
        try:
            full_credits = float(estimates.get("FULL_CREDITS", 0.0) or 0.0)
        except (AttributeError, TypeError, ValueError):
            full_credits = 0.0
        if credit_known and (not credit_unlimited) and balanced_credits > credit_balance:
            balanced_allowed = False
        if credit_known and (not credit_unlimited) and full_credits > credit_balance:
            full_allowed = False
        effective_mode = str(current_mode or "PREVIEW").strip().upper()
        if effective_mode == "FULL" and not full_allowed:
            effective_mode = "BALANCED" if balanced_allowed else "PREVIEW"
        elif effective_mode == "BALANCED" and not balanced_allowed:
            effective_mode = "PREVIEW"

        preview_col = quality_row.column(align=True)
        preview_col.enabled = bool(preview_allowed)
        preview_col.operator(
            "planetka.set_texture_quality_and_resolve",
            text="Preview",
            depress=(effective_mode == "PREVIEW"),
        ).texture_quality_mode = "PREVIEW"
        preview_size_row = preview_col.row(align=True)
        preview_size_row.alignment = 'CENTER'
        preview_size_row.enabled = (effective_mode == "PREVIEW")
        preview_size_row.label(text=_estimate_mb_label("PREVIEW"))
        preview_credit_row = preview_col.row(align=True)
        preview_credit_row.alignment = 'CENTER'
        preview_credit_row.enabled = (effective_mode == "PREVIEW")
        preview_credit_row.label(text=_estimate_credit_label("PREVIEW"))

        balanced_col = quality_row.column(align=True)
        balanced_col.enabled = bool(balanced_allowed)
        balanced_col.operator(
            "planetka.set_texture_quality_and_resolve",
            text="Balanced",
            depress=(effective_mode == "BALANCED"),
        ).texture_quality_mode = "BALANCED"
        balanced_size_row = balanced_col.row(align=True)
        balanced_size_row.alignment = 'CENTER'
        balanced_size_row.enabled = (effective_mode == "BALANCED")
        balanced_size_row.label(text=_estimate_mb_label("BALANCED"))
        balanced_credit_row = balanced_col.row(align=True)
        balanced_credit_row.alignment = 'CENTER'
        balanced_credit_row.enabled = (effective_mode == "BALANCED")
        balanced_credit_row.label(text=_estimate_credit_label("BALANCED"))

        full_col = quality_row.column(align=True)
        full_col.enabled = bool(full_allowed)
        full_col.operator(
            "planetka.set_texture_quality_and_resolve",
            text="Full Quality",
            depress=(effective_mode == "FULL"),
        ).texture_quality_mode = "FULL"
        full_size_row = full_col.row(align=True)
        full_size_row.alignment = 'CENTER'
        full_size_row.enabled = (effective_mode == "FULL")
        full_size_row.label(text=_estimate_mb_label("FULL"))
        full_credit_row = full_col.row(align=True)
        full_credit_row.alignment = 'CENTER'
        full_credit_row.enabled = (effective_mode == "FULL")
        full_credit_row.label(text=_estimate_credit_label("FULL"))

        if credit_known and (not credit_unlimited) and max(balanced_credits, full_credits) > credit_balance:
            credit_notice = quality_box.row(align=True)
            credit_notice.label(text=f"Credits available: {credit_balance:.2f}", icon="INFO")

        runtime, runtime_code, runtime_text = _resolve_runtime_display(scene)
        resolve_failure_message = _resolve_failure_message_for_ui(scene)
        inside_earth_warning = _inside_earth_warning_for_ui(scene)
        low_altitude_warning = _low_altitude_warning_for_ui(scene)
        status_row = quality_box.row(align=True)
        status_row.alert = bool(resolve_failure_message or inside_earth_warning or low_altitude_warning)
        animation_render_running = _is_animation_render_running()
        status_label_text = f"{runtime_text}{_status_activity_suffix(runtime.get('running', False))}"
        status_icon = _status_icon(runtime_code)
        last_resolve_text = _last_resolve_summary_text(scene, include_prefix=True)
        if resolve_failure_message:
            status_label_text = "Error detected"
            status_icon = "ERROR"
        elif inside_earth_warning:
            status_label_text = "Below Earth's surface"
            status_icon = "ERROR"
        elif low_altitude_warning:
            status_label_text = low_altitude_warning
            status_icon = "ERROR"
        elif animation_render_running:
            status_label_text, status_icon = _animation_render_status_for_ui(scene)
        elif runtime_code == "IDLE" and last_resolve_text:
            status_label_text = last_resolve_text
        status_row.label(
            text=status_label_text,
            icon=status_icon,
        )

        if resolve_failure_message:
            error_box = quality_box.box()
            error_box.alert = True
            error_box.label(text=resolve_failure_message, icon="ERROR")
            rebuild_row = error_box.row(align=True)
            rebuild_row.alert = True
            rebuild_row.operator("planetka.rebuild_earth", text="Rebuild Earth", icon="FILE_REFRESH")

    throttle_message = str(get_status_message(prefs) or "").strip()
    if throttle_message and "throttl" in throttle_message.lower():
        alert_box = layout.box()
        alert_box.alert = True
        alert_box.label(text=throttle_message, icon="ERROR")


def _draw_advanced_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    advanced_col = layout.column(align=True)
    download_size_mb = diag.get("resolve_downloaded_mb")
    download_time_ms = diag.get("resolve_download_ms")
    download_thread_ms = diag.get("resolve_download_thread_ms")
    advanced_col.label(text=f"Tiles: {_fmt_int(diag.get('last_tile_count'))}")
    advanced_col.label(text=f"Spatial Resolution: {_fmt_m(diag.get('resolve_required_mpp_m'))}")
    advanced_col.label(text=f"Texture Size: {_fmt_mb(diag.get('resolve_textures_mb'))}")
    advanced_col.label(text=f"Resolve Prep Time: {_fmt_ms(diag.get('last_resolve_ms'))}")
    advanced_col.label(text=f"Download Time (Wall): {_fmt_ms(download_time_ms)}")
    if download_thread_ms is not None:
        advanced_col.label(text=f"Download Time (All Requests): {_fmt_ms(download_thread_ms)}")
    advanced_col.label(text=f"Download Size: {_fmt_mb(download_size_mb)}")
    advanced_col.label(text=f"Effective Download Speed: {_fmt_mbps(download_size_mb, download_time_ms)}")


def _draw_navigation(layout, context, controls_enabled=True):
    layout.use_property_split = True
    layout.use_property_decorate = False

    scene = getattr(context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    prepared = _is_animation_prepared(scene)
    base_enabled = bool(controls_enabled)
    if not props:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    keyframe_locked, _object_locked, _lens_locked = _navigation_has_camera_keyframe_lock(scene)
    navigation_unlocked = bool(base_enabled) and (not prepared) and (not keyframe_locked)

    if prepared:
        _draw_animation_ready_message(layout)
    if keyframe_locked:
        lock_box = layout.box()
        lock_box.label(text="Camera keyframes are active. Clear Camera Keyframes to unlock.", icon="LOCKED")
        unlock_row = lock_box.row(align=True)
        unlock_row.scale_y = 1.05
        unlock_row.enabled = bool(base_enabled)
        unlock_row.operator(
            "planetka.animation_clear_camera_keyframes",
            text="Clear Camera Keyframes",
            icon="TRASH",
        )

    location_box = layout.box()
    location_box.enabled = navigation_unlocked
    geonames_status = str(get_search_status_text() or "")
    if geonames_status:
        status_icon = "ERROR" if "not configured" in geonames_status else "INFO"
        location_box.label(text=geonames_status, icon=status_icon)
    location_box.label(text="Location", icon="PINNED")
    location_box.prop(props, "nav_city_search", text="Place Search")
    selected_place = str(getattr(props, "nav_city_selected_name", "") or "")
    if selected_place:
        location_box.label(text=f"Selected: {selected_place}", icon="BOOKMARKS")
    latlon_row = location_box.row(align=True)
    latlon_row.use_property_split = False
    latlon_row.use_property_decorate = False
    lat_col = latlon_row.column(align=True)
    lat_label = lat_col.row()
    lat_label.alignment = 'CENTER'
    lat_label.label(text="Latitude")
    lat_col.prop(props, "nav_latitude_deg", text="")
    lon_col = latlon_row.column(align=True)
    lon_label = lon_col.row()
    lon_label.alignment = 'CENTER'
    lon_label.label(text="Longitude")
    lon_col.prop(props, "nav_longitude_deg", text="")

    shot_box = layout.box()
    shot_box.enabled = navigation_unlocked
    shot_box.label(text="Camera Controls", icon="CAMERA_DATA")
    altitude_col = shot_box.column(align=True)
    altitude_col.use_property_split = False
    altitude_col.use_property_decorate = False
    altitude_label = altitude_col.row()
    altitude_label.alignment = 'CENTER'
    altitude_label.label(text="Altitude (km)")
    altitude_col.prop(props, "nav_altitude_km", text="")
    orientation_row = shot_box.row(align=True)
    orientation_row.use_property_split = False
    orientation_row.use_property_decorate = False
    heading_col = orientation_row.column(align=True)
    heading_label = heading_col.row()
    heading_label.alignment = 'CENTER'
    heading_label.label(text="Heading")
    heading_col.prop(props, "nav_azimuth_deg", text="")
    tilt_col = orientation_row.column(align=True)
    tilt_label = tilt_col.row()
    tilt_label.alignment = 'CENTER'
    tilt_label.label(text="Tilt")
    tilt_col.prop(props, "nav_tilt_deg", text="")
    roll_col = orientation_row.column(align=True)
    roll_label = roll_col.row()
    roll_label.alignment = 'CENTER'
    roll_label.label(text="Roll")
    roll_col.prop(props, "nav_roll_deg", text="")
    shot_box.prop(props, "nav_focal_length_mm", text="Focal Length (mm)")

    preset_box = layout.box()
    preset_box.enabled = navigation_unlocked
    preset_box.label(text="Altitude Presets", icon="ORIENTATION_GLOBAL")
    preset_row_top = preset_box.row(align=True)
    preset_row_top.operator(
        "planetka.navigation_preset",
        text="Max Proximity",
        icon="ZOOM_IN",
    ).preset = "MAX_PROXIMITY"
    preset_row_top.operator(
        "planetka.navigation_preset",
        text="ISS Orbit",
        icon="ORIENTATION_GLOBAL",
    ).preset = "ISS_ORBIT"
    preset_row_bottom = preset_box.row(align=True)
    preset_row_bottom.operator(
        "planetka.navigation_preset",
        text="ESA Sentinel-2",
        icon="IMAGE_DATA",
    ).preset = "SENTINEL2"
    preset_row_bottom.operator(
        "planetka.navigation_preset",
        text="Full Globe",
        icon="WORLD_DATA",
    ).preset = "HIGH_ORBIT"

def _iter_surface_grading_nodes():
    material_name = "Planetka Earth Material"
    group_name = "Planetka Surface Grading Group"
    try:
        from .asset_builder import EARTH_MATERIAL_NAME, SURFACE_GRADING_GROUP_NAME

        material_name = str(EARTH_MATERIAL_NAME or material_name)
        group_name = str(SURFACE_GRADING_GROUP_NAME or group_name)
    except (ImportError, ModuleNotFoundError):
        logger.debug("Planetka: failed loading surface grading identifiers", exc_info=True)

    material = bpy.data.materials.get(material_name)
    if material is None or getattr(material, "node_tree", None) is None:
        return []
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return []

    nodes = []
    for node in getattr(node_tree, "nodes", ()):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        node_group = getattr(node, "node_tree", None)
        if str(getattr(node_group, "name", "")) == group_name:
            nodes.append(node)
    return nodes


def _iter_surface_grading_input_sockets(node):
    sockets = []
    for socket in getattr(node, "inputs", ()):
        if bool(getattr(socket, "is_linked", False)):
            continue
        if not hasattr(socket, "default_value"):
            continue
        socket_type = str(getattr(socket, "bl_socket_idname", "")).strip()
        if socket_type in {"NodeSocketShader", "NodeSocketVirtual"}:
            continue
        sockets.append(socket)
    return sockets


_SURFACE_GRADING_SECTION_ORDER = (
    "Global",
    "Water",
    "Elevation",
    "Night Lights",
)

_SURFACE_GRADING_SECTION_SOCKET_MAP = {
    "Global": {
        "surface brightness",
        "surface saturation",
    },
    "Water": {
        "roughness",
        "ior",
        "hue",
        "saturation",
        "brightness",
    },
    "Elevation": {
        "coefficient",
    },
    "Night Lights": {
        "intensity",
        "color temperature",
        "night terminator shift",
    },
}

_SURFACE_GRADING_SECTION_RESET_KEY = {
    "Global": "GLOBAL",
    "Water": "WATER",
    "Elevation": "ELEVATION",
    "Night Lights": "NIGHT",
}


def _surface_grading_section_for_socket(socket_name):
    normalized = str(socket_name or "").strip().lower()
    for section in _SURFACE_GRADING_SECTION_ORDER:
        names = _SURFACE_GRADING_SECTION_SOCKET_MAP.get(section, set())
        if normalized in names:
            return section
    return None


def _split_surface_grading_sockets(sockets):
    grouped = {section: [] for section in _SURFACE_GRADING_SECTION_ORDER}
    for socket in sockets or ():
        section = _surface_grading_section_for_socket(getattr(socket, "name", ""))
        if section is None:
            continue
        grouped.setdefault(section, []).append(socket)
    return grouped


def _surface_grading_socket_label(socket_name):
    normalized = str(socket_name or "").strip().lower()
    if normalized == "surface brightness":
        return "Brightness"
    if normalized == "surface saturation":
        return "Saturation"
    if normalized == "night terminator shift":
        return "Terminator Shift"
    return str(socket_name or "Value")


def _draw_surface_grading(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    nodes = _iter_surface_grading_nodes()
    if not nodes:
        layout.label(text="Earth Surface Grading node group not found.", icon="INFO")
        return

    many_nodes = len(nodes) > 1
    for index, node in enumerate(nodes, start=1):
        container = layout.box() if many_nodes else layout
        if many_nodes:
            container.label(text=f"Surface Grading Node {index}", icon="NODETREE")
        sockets = _iter_surface_grading_input_sockets(node)
        if not sockets:
            container.label(text="No adjustable inputs found.", icon="INFO")
            continue
        grouped = _split_surface_grading_sockets(sockets)
        for section in _SURFACE_GRADING_SECTION_ORDER:
            section_sockets = grouped.get(section, [])
            if not section_sockets:
                continue
            section_box = container.box()
            section_header = section_box.row(align=True)
            section_header.label(text=section)
            reset_section = _SURFACE_GRADING_SECTION_RESET_KEY.get(section, "")
            if reset_section:
                reset_button = section_header.row(align=True)
                reset_button.alignment = 'RIGHT'
                reset_button.operator(
                    "planetka.reset_surface_grading_section",
                    text="Reset",
                    icon="LOOP_BACK",
                ).section = reset_section
            for socket in section_sockets:
                row = section_box.row()
                try:
                    row.prop(socket, "default_value", text=_surface_grading_socket_label(getattr(socket, "name", "")))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue


def _draw_earth_transform(layout, scene):
    layout.use_property_split = True
    layout.use_property_decorate = False

    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is None:
        layout.label(text="Planetka Root not found. Create Earth first.", icon="INFO")
        return
    if str(getattr(root, "type", "")) != "EMPTY":
        layout.label(text="Planetka Root has invalid type.", icon="ERROR")
        return
    if scene is None or root not in tuple(getattr(scene, "objects", ())):
        layout.label(text="Planetka Root is not in active scene.", icon="INFO")
        return

    props = getattr(scene, "planetka", None) if scene else None
    if props is not None:
        layout.prop(props, "earth_radius_bu", text="Earth Radius")
        try:
            earth_radius = float(getattr(props, "earth_radius_bu", 2.0))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            earth_radius = 2.0
        if _radius_needs_clipping_adjustment(earth_radius):
            warning_box = layout.box()
            warning_box.label(
                text="New radius may require clipping adjustment.",
                icon="INFO",
            )
            warning_box.operator(
                "planetka.auto_adjust_clipping",
                text=_clipping_button_text(None),
            )

    layout.prop(root, "location", text="Location")
    layout.prop(root, "rotation_euler", text="Rotation")
    reset_row = layout.row()
    reset_row.use_property_split = False
    reset_row.use_property_decorate = False
    reset_row.operator(
        "planetka.reset_earth_transform",
        text="Reset Transform",
        icon="LOOP_BACK",
    )


def _iter_atmosphere_nodes():
    object_name = "Atmosphere - Volumetric"
    group_name = "Planetka Atmosphere Group"
    try:
        from .asset_builder import VOLUMETRIC_ATMOSPHERE_GROUP_NAME, VOLUMETRIC_ATMOSPHERE_OBJECT_NAME

        object_name = str(VOLUMETRIC_ATMOSPHERE_OBJECT_NAME or object_name)
        group_name = str(VOLUMETRIC_ATMOSPHERE_GROUP_NAME or group_name)
    except (ImportError, ModuleNotFoundError):
        logger.debug("Planetka: failed loading atmosphere identifiers", exc_info=True)

    atmosphere_obj = bpy.data.objects.get(object_name)
    if atmosphere_obj is None:
        return []

    nodes = []
    for slot in getattr(atmosphere_obj, "material_slots", ()):
        material = getattr(slot, "material", None)
        if material is None or getattr(material, "node_tree", None) is None:
            continue
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        for node in getattr(node_tree, "nodes", ()):
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_group = getattr(node, "node_tree", None)
            node_group_name = str(getattr(node_group, "name", ""))
            lowered = node_group_name.lower()
            if node_group_name == group_name or ("atmosphere" in lowered and "fake" not in lowered):
                nodes.append(node)
    return nodes


def _iter_atmosphere_input_sockets(node):
    sockets = []
    for socket in getattr(node, "inputs", ()):
        if bool(getattr(socket, "is_linked", False)):
            continue
        if not hasattr(socket, "default_value"):
            continue
        socket_type = str(getattr(socket, "bl_socket_idname", "")).strip()
        if socket_type in {"NodeSocketShader", "NodeSocketVirtual"}:
            continue
        sockets.append(socket)
    return sockets


def _draw_atmosphere(layout, context):
    layout.use_property_split = True
    layout.use_property_decorate = False

    scene = getattr(context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    layout.prop(props, "atmosphere_enabled", text="Enable Atmosphere")

    nodes = _iter_atmosphere_nodes()
    if not nodes:
        layout.label(text="Volumetric atmosphere shader not found.", icon="INFO")
        return

    many_nodes = len(nodes) > 1
    for index, node in enumerate(nodes, start=1):
        container = layout.box() if many_nodes else layout
        if many_nodes:
            container.label(text=f"Atmosphere Shader Node {index}", icon="NODETREE")
        sockets = _iter_atmosphere_input_sockets(node)
        if not sockets:
            container.label(text="No adjustable inputs found.", icon="INFO")
            continue
        for socket in sockets:
            row = container.row()
            try:
                row.prop(socket, "default_value", text=str(getattr(socket, "name", "Value")))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue


class PLANETKA_PT_AccountPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Account"
    bl_idname = "PLANETKA_PT_account"
    bl_order = 9000
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _account_panel_should_default_collapsed(context)

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled()
        _draw_account_panel(layout)


class PLANETKA_PT_AccountPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Account"
    bl_idname = "PLANETKA_PT_account_collapsed"
    bl_order = 9000

    @classmethod
    def poll(cls, context):
        return _account_panel_should_default_collapsed(context)

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled()
        _draw_account_panel(layout)


class PLANETKA_PT_NewEarthPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "New Earth"
    bl_idname = "PLANETKA_PT_new_earth"
    bl_order = 9001
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_connected())
        _draw_new_earth(layout)


class PLANETKA_PT_NewEarthPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "New Earth"
    bl_idname = "PLANETKA_PT_new_earth_collapsed"
    bl_order = 9001
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        _ = context
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_connected())
        _draw_new_earth(layout)


class PLANETKA_PT_NewEarthPanelFailure(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "New Earth"
    bl_idname = "PLANETKA_PT_new_earth_failure"
    bl_order = 9001
    bl_options = set()

    @classmethod
    def poll(cls, context):
        _ = context
        return False

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_connected())
        _draw_new_earth(layout)


class PLANETKA_PT_SettingsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Planetka Settings"
    bl_idname = "PLANETKA_PT_settings"
    bl_order = 9007

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(True)
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        prepared = _is_animation_prepared(scene)
        workflow_enabled = _is_earth_workflow_enabled()

        if props:
            addon_box = layout.box()
            addon_box.label(text="Add-on", icon="PREFERENCES")
            _draw_addon_update_controls(addon_box)

            startup_box = layout.box()
            startup_box.label(text="Startup Setup", icon="TOOL_SETTINGS")
            save_row = startup_box.row()
            save_row.enabled = workflow_enabled
            save_row.operator(
                "planetka.save_startup_setup",
                text="Save Current Setup as Startup Default",
                icon="FILE_TICK",
            )
            startup_box.operator(
                "planetka.reset_startup_setup_factory",
                text="Reset Startup Setup",
                icon="LOOP_BACK",
            )

            standalone_box = layout.box()
            standalone_box.label(text="Standalone Export", icon="PACKAGE")
            standalone_box.enabled = _has_earth()
            standalone_box.operator(
                "planetka.create_standalone_file",
                text="Create Standalone File",
                icon="FILE_BLEND",
            )

            diagnostics_box = layout.box()
            diagnostics_box.label(text="Diagnostics", icon="CHECKMARK")
            diagnostics_box.operator(
                "planetka.scene_health_check",
                text="Scene Health Check",
                icon="CHECKMARK",
            )

            scene_objects_box = layout.box()
            scene_objects_box.enabled = workflow_enabled and (not prepared)
            scene_objects_box.label(text="Scene Objects", icon="OUTLINER_OB_EMPTY")
            scene_objects_box.prop(
                props,
                "show_earth_preview",
                text="Show Earth Preview",
                toggle=True,
            )

            clipping_box = layout.box()
            clipping_box.enabled = workflow_enabled
            clipping_box.label(text="Clipping", icon="ZOOM_ALL")
            clipping_box.prop(
                props,
                "auto_adjust_clipping_values",
                text="Auto-adjust clipping",
                toggle=True,
            )

class PLANETKA_PT_LiveTelemetryPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Data Control"
    bl_idname = "PLANETKA_PT_live_telemetry"
    bl_order = 9001
    bl_options = set()

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None) if context else None
        return _has_earth() and (not bool(_resolve_failure_message_for_ui(scene)))

    def draw(self, context):
        self.layout.enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Data Control"
    bl_idname = "PLANETKA_PT_live_telemetry_collapsed"
    bl_order = 9001
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        _ = context
        return not _has_earth()

    def draw(self, context):
        # Pre-Earth state: keep panel available but collapsed by default.
        self.layout.enabled = _planetka_controls_enabled(_is_connected())
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryPanelFailure(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Data Control"
    bl_idname = "PLANETKA_PT_live_telemetry_failure"
    bl_order = 9001
    bl_options = set()

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None) if context else None
        return _has_earth() and bool(_resolve_failure_message_for_ui(scene))

    def draw(self, context):
        self.layout.enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LinksPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Links"
    bl_idname = "PLANETKA_PT_links"
    bl_order = 9008
    bl_options = set()

    @classmethod
    def poll(cls, context):
        _ = context
        return not _is_paid_connected_account()

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(True)
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/@tomasgriger-planetka/videos"
        row.operator("planetka.report_bug", text="Send Feedback", icon="INFO")

        layout.operator(
            "wm.url_open",
            text="www.planetka.io",
            icon="URL",
        ).url = "https://www.planetka.io"


class PLANETKA_PT_LinksPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Links"
    bl_idname = "PLANETKA_PT_links_collapsed"
    bl_order = 9008
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        _ = context
        return _is_paid_connected_account()

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(True)
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/@tomasgriger-planetka/videos"
        row.operator("planetka.report_bug", text="Send Feedback", icon="INFO")

        layout.operator(
            "wm.url_open",
            text="www.planetka.io",
            icon="URL",
        ).url = "https://www.planetka.io"


class PLANETKA_PT_NavigationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Navigation"
    bl_idname = "PLANETKA_PT_navigation"
    bl_order = 9002
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        controls_enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        layout.enabled = True
        _draw_navigation(layout, context, controls_enabled=controls_enabled)


class PLANETKA_PT_NavigationPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Navigation"
    bl_idname = "PLANETKA_PT_navigation_collapsed"
    bl_order = 9002

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = True
        _draw_navigation(layout, context, controls_enabled=False)


def _draw_earth_settings(layout, scene, enabled):
    layout.enabled = bool(enabled)
    layout.use_property_split = True
    layout.use_property_decorate = False

    # Blender 5.0 can crash inside uiLayout.panel() when this panel redraws
    # immediately after Create Earth. Use a plain box here; stability matters
    # more than a collapsible subsection.
    transform_box = layout.box()
    transform_box.label(text="Earth Transform", icon="EMPTY_AXIS")
    transform_box.enabled = bool(enabled)
    _draw_earth_transform(transform_box, scene)

    _draw_surface_grading(layout)


class PLANETKA_PT_EarthSettingsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Earth Settings"
    bl_idname = "PLANETKA_PT_earth_settings"
    bl_order = 9004

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_earth_settings(self.layout, scene, enabled=_planetka_controls_enabled(True))


class PLANETKA_PT_EarthSettingsPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Earth Settings"
    bl_idname = "PLANETKA_PT_earth_settings_collapsed"
    bl_order = 9004

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_earth_settings(self.layout, scene, enabled=_planetka_controls_enabled(False))


class PLANETKA_PT_AtmospherePanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Atmosphere"
    bl_idname = "PLANETKA_PT_atmosphere"
    bl_order = 9005

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        _draw_atmosphere(layout, context)


class PLANETKA_PT_AtmospherePanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Atmosphere"
    bl_idname = "PLANETKA_PT_atmosphere_collapsed"
    bl_order = 9005

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_atmosphere(layout, context)


class PLANETKA_PT_SunlightPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Sunlight"
    bl_idname = "PLANETKA_PT_sunlight"
    bl_order = 9005
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if not props:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.prop(props, "sunlight_strength", text="Strength")
        layout.prop(props, "sunlight_longitude_deg", text="Longitude (°)")
        layout.prop(props, "sunlight_seasonal_tilt_deg", text="Seasonal Tilt (°)")

        layout.separator()
        layout.label(text="Presets", icon="LIGHT_SUN")
        last_preset = str(getattr(props, "sunlight_last_preset", "") or "").upper()

        def _draw_preset_button(row, label, preset_key):
            op = row.operator(
                "planetka.sunlight_preset",
                text=label,
                depress=(last_preset == preset_key),
            )
            op.preset = preset_key

        row1 = layout.row(align=True)
        _draw_preset_button(row1, "Dawn", "DAWN")
        _draw_preset_button(row1, "Dusk", "DUSK")

        row2 = layout.row(align=True)
        _draw_preset_button(row2, "Sunrise", "SUNRISE")
        _draw_preset_button(row2, "Sunset", "SUNSET")

        row3 = layout.row(align=True)
        _draw_preset_button(row3, "Early Morning", "EARLY_MORNING")
        _draw_preset_button(row3, "Late Afternoon", "LATE_AFTERNOON")

        row4 = layout.row(align=True)
        _draw_preset_button(row4, "Mid-morning", "MID_MORNING")
        _draw_preset_button(row4, "Mid-afternoon", "MID_AFTERNOON")

        row5 = layout.row(align=True)
        _draw_preset_button(row5, "Noon", "NOON")
        _draw_preset_button(row5, "Night", "NIGHT")


class PLANETKA_PT_AnimationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "PLANETKA_PT_animation"
    bl_order = 9006
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # Cinematic presets are part of the public UI; render-setup stays internal-only.
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return
        earth_workflow_enabled = _is_earth_workflow_enabled()
        controls_enabled = _planetka_controls_enabled(earth_workflow_enabled)

        cinematic_box = layout.box()
        cinematic_box.enabled = bool(controls_enabled)
        cinematic_box.label(text="Cinematic Camera", icon="CAMERA_DATA")
        cinematic_box.prop(props, "anim_camera_preset", text="Preset")

        preset = str(getattr(props, "anim_camera_preset", "NONE")).upper()
        if preset in {"PUSH_IN", "PULL_BACK"}:
            preset = "ZOOM"
        elif preset in {"ARC_LEFT", "ARC_RIGHT"}:
            preset = "ARC"
        elif preset == "FLYBY":
            preset = "NONE"
        if preset != "NONE":
            cinematic_box.prop(props, "anim_motion_curve", text="Motion Curve")
        if preset in {"ORBIT", "ARC"}:
            cinematic_box.prop(props, "anim_orbit_degrees", text=("Circle Degrees" if preset == "ORBIT" else "Arc Degrees"))
            cinematic_box.prop(props, "anim_circle_direction", text="Direction")
        if preset == "ZOOM":
            cinematic_box.prop(props, "anim_end_altitude_km", text="End Altitude (km)")
            cinematic_box.prop(props, "anim_zoom_rotate_degrees", text="Rotate (°)")
        if preset == "A_TO_B":
            view_row = cinematic_box.row(align=True)
            view_row.operator("planetka.animation_save_view", text="Save View A", icon="BOOKMARKS").slot = "A"
            view_row.operator("planetka.animation_save_view", text="Save View B", icon="BOOKMARKS").slot = "B"
            status_a = "Ready" if bool(getattr(props, "anim_ab_a_valid", False)) else "Not Set"
            status_b = "Ready" if bool(getattr(props, "anim_ab_b_valid", False)) else "Not Set"
            cinematic_box.label(text=f"View A: {status_a}")
            cinematic_box.label(text=f"View B: {status_b}")
            if bool(getattr(props, "anim_ab_a_valid", False)):
                frame_a = int(getattr(props, "anim_ab_a_capture_frame", 0) or 0)
                timecode_a = str(getattr(props, "anim_ab_a_capture_timecode", "") or "").strip()
                if frame_a > 0 or timecode_a:
                    meta_a = f"Frame {frame_a}" if frame_a > 0 else "Frame n/a"
                    if timecode_a:
                        meta_a = f"{meta_a} ({timecode_a})"
                    meta_row_a = cinematic_box.row()
                    meta_row_a.scale_y = 0.82
                    meta_row_a.label(text=f"View A last captured: {meta_a}", icon="TIME")
            if bool(getattr(props, "anim_ab_b_valid", False)):
                frame_b = int(getattr(props, "anim_ab_b_capture_frame", 0) or 0)
                timecode_b = str(getattr(props, "anim_ab_b_capture_timecode", "") or "").strip()
                if frame_b > 0 or timecode_b:
                    meta_b = f"Frame {frame_b}" if frame_b > 0 else "Frame n/a"
                    if timecode_b:
                        meta_b = f"{meta_b} ({timecode_b})"
                    meta_row_b = cinematic_box.row()
                    meta_row_b.scale_y = 0.82
                    meta_row_b.label(text=f"View B last captured: {meta_b}", icon="TIME")

        if preset != "NONE":
            frame_row = cinematic_box.row(align=True)
            frame_row.prop(props, "anim_frame_start", text="Frames")
            frame_row.prop(props, "anim_frame_end", text="End")

            generate_row = cinematic_box.row(align=True)
            generate_row.scale_y = 1.05
            generate_row.operator(
                "planetka.animation_generate_camera_keyframes",
                text="Generate Camera Keyframes",
                icon="KEY_HLT",
            )

        clear_keys_row = cinematic_box.row(align=True)
        clear_keys_row.scale_y = 1.05
        clear_keys_row.enabled = bool(controls_enabled)
        clear_keys_row.operator(
            "planetka.animation_clear_camera_keyframes",
            text="Clear Camera Keyframes",
            icon="TRASH",
        )

        prepared = _is_animation_prepared(scene)
        quick_preview_box = layout.box()
        quick_preview_box.enabled = bool(controls_enabled)
        quick_preview_box.label(text="Quick Preview", icon="SHADING_RENDERED")

        if _show_internal_animation_ui():
            quick_preview_box.prop(props, "anim_prepare_max_segments", text="Max Segments")
            quick_preview_box.prop(props, "anim_prepare_max_textures_mb", text="Max Textures (MB)")

        build_row = quick_preview_box.row(align=True)
        build_row.scale_y = 1.15
        build_row.operator(
            "planetka.animation_make_ready",
            text=("Rebuild Quick Preview" if prepared else "Build Quick Preview"),
            icon="SHADING_RENDERED",
        )
        clear_row = quick_preview_box.row(align=True)
        clear_row.scale_y = 1.05
        clear_row.enabled = bool(controls_enabled) and bool(prepared)
        clear_row.operator(
            "planetka.animation_clear_prepared",
            text="Clear Quick Preview",
            icon="TRASH",
        )

        final_render_box = layout.box()
        final_render_box.enabled = bool(controls_enabled)
        final_render_box.label(text="Final Animation Render", icon="RENDER_ANIMATION")
        selected_final_quality = str(getattr(props, "anim_render_texture_quality_mode", "FULL") or "FULL").strip().upper()
        if selected_final_quality != "BALANCED":
            selected_final_quality = "FULL"
        final_render_allowed = allows_animation_render_for_context(
            prefs=get_prefs(),
            source=props,
            requested_mode=selected_final_quality,
        )
        balanced_allowed = allows_animation_render_for_context(
            prefs=get_prefs(),
            source=props,
            requested_mode="BALANCED",
        )
        full_allowed = allows_animation_render_for_context(
            prefs=get_prefs(),
            source=props,
            requested_mode="FULL",
        )

        quality_row = final_render_box.row(align=True)
        quality_row.use_property_split = False
        balanced_col = quality_row.column(align=True)
        balanced_col.enabled = bool(earth_workflow_enabled) and bool(balanced_allowed)
        balanced_col.operator(
            "planetka.set_animation_render_texture_quality",
            text="Balanced",
            depress=(selected_final_quality == "BALANCED"),
        ).texture_quality_mode = "BALANCED"
        full_col = quality_row.column(align=True)
        full_col.enabled = bool(earth_workflow_enabled) and bool(full_allowed)
        full_col.operator(
            "planetka.set_animation_render_texture_quality",
            text="Full Quality",
            depress=(selected_final_quality == "FULL"),
        ).texture_quality_mode = "FULL"
        try:
            anim_credits = float(scene.get("planetka_anim_estimated_credits", 0.0) or 0.0)
            anim_paid_tiles = int(scene.get("planetka_anim_estimated_paid_tile_count", 0) or 0)
        except (TypeError, ValueError, RuntimeError, AttributeError):
            anim_credits = 0.0
            anim_paid_tiles = 0
        if anim_credits > 0.0 or anim_paid_tiles > 0:
            final_render_box.label(
                text=f"Estimated new tiles: {anim_paid_tiles} / {anim_credits:.2f} credits",
                icon="SOLO_ON",
            )
        if anim_credits > 0.0:
            anim_account_known = False
            try:
                from .credit_api import get_credit_account
                anim_account = get_credit_account(force=False)
                anim_account_known = bool(anim_account)
                anim_unlimited = bool(anim_account.get("unlimited_credits", False))
                anim_balance = float(anim_account.get("balance_credits", 0.0) or 0.0)
            except (AuthApiError, TypeError, ValueError, RuntimeError, AttributeError):
                anim_account_known = False
                anim_unlimited = False
                anim_balance = 0.0
            if anim_account_known and (not anim_unlimited) and anim_credits > anim_balance:
                final_render_allowed = False
                final_render_box.label(text=f"Not enough credits ({anim_balance:.2f} available).", icon="INFO")
        if _is_animation_render_running():
            render_status_text, render_status_icon = _animation_render_status_for_ui(scene)
            status_row = final_render_box.row(align=True)
            status_row.label(text=render_status_text, icon=render_status_icon)

        render_row = final_render_box.row(align=True)
        render_button_row = render_row.row(align=True)
        render_button_row.scale_y = 1.2
        render_button_row.enabled = bool(final_render_allowed) and bool(earth_workflow_enabled)
        render_button_row.operator(
            "planetka.animation_render",
            text="Render Animation",
            icon="RENDER_ANIMATION",
        )
        render_info_row = render_row.row(align=True)
        render_info_row.scale_y = 1.2
        render_info_row.enabled = bool(earth_workflow_enabled)
        render_info_row.operator(
            "planetka.animation_render_info",
            text="",
            icon="QUESTION",
        )
        if not final_render_allowed:
            final_render_box.label(text="Final Animation Render requires enough credits for selected tiles.", icon="INFO")
