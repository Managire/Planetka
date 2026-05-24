"""Planetka UI panels and telemetry rendering."""

import bpy
import datetime
import json
import os
import time

from .asset_builder import PLANETKA_ROOT_OBJECT_NAME
from .auth import (
    AuthApiError,
    CLOUD_OVERLOADED_MESSAGE,
    allows_animation_render_for_context,
    allows_texture_quality_for_context,
    get_cached_cloud_connection_status,
    get_cloud_connection_status,
    get_account_tier,
    get_connected_email,
    get_status_message,
    ensure_authenticated_session,
    is_authenticated,
    is_pro_account,
)
from .extension_prefs import get_earth_object, get_prefs
from .geonames_db import get_search_status_text
from .diagnostics import read_diagnostics
from .r2_source import get_download_progress, is_download_active, is_remote_source_configured
from .planetka_ops.scene_setup_ops import is_scene_background_black
from .updater import get_public_status as get_updater_public_status
from .animation_tools import (
    ANIMATION_SEGMENT_TAG_KEY,
    ANIMATION_RENDER_STATUS_ICON_KEY,
    ANIMATION_RENDER_STATUS_TEXT_KEY,
    ANIMATION_STATS_SEGMENTS_KEY,
)
from .state import (
    ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY,
    ADD_EARTH_BUTTON_SCALE_X,
    ADD_EARTH_BUTTON_SCALE_Y,
    _auto_resolve_scope_mode,
    _is_render_job_active,
    get_camera_inside_earth_warning,
    is_final_animation_render_active,
    get_resolve_size_estimates,
    get_resolve_runtime_status,
    logger,
)

SHOW_INTERNAL_ANIMATION_UI = False
BETA_DISABLE_FULL_QUALITY_DATA_DOWNLOADS = True
CLIPPING_AUTO_NOTICE_KEY = "planetka_status_clip_auto_notice"
CACHE_NOTICE_KEY = "planetka_status_cache_notice"
RADIUS_SYNC_NOTICE_KEY = "planetka_status_radius_sync_notice"
RESOLVE_FAILURE_FLAG_KEY = "planetka_resolve_integrity_failed"
RESOLVE_FAILURE_MESSAGE_KEY = "planetka_resolve_integrity_message"
LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY = "planetka_last_resolve_texture_quality_mode"
EARTH_TRANSFORM_SECTION_OPEN_KEY = "planetka_ui_earth_transform_open"
DATA_CONTROL_MORE_OPTIONS_SECTION_OPEN_KEY = "planetka_ui_data_more_options_open"
EARTH_RADIUS_SAFE_MIN_BU = 0.2
EARTH_RADIUS_SAFE_MAX_BU = 20.0
LOW_ALTITUDE_WARNING_EPS_KM = 0.05
SIDEBAR_ACCOUNT_REFRESH_INTERVAL_SEC = 20.0
SIDEBAR_ACCOUNT_REFRESH_INITIAL_DELAY_SEC = 0.35
_SIDEBAR_ACCOUNT_REFRESH_LAST_AT = 0.0
_SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED = False
UPDATER_UI_REDRAW_INTERVAL_SEC = 0.25
_UPDATER_UI_REDRAW_TIMER_REGISTERED = False


def _float_close(value, target, tol=1e-4):
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except (TypeError, ValueError):
        return False


def _fmt_int(value):
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} ms"
    except (TypeError, ValueError):
        return "—"


def _tag_view3d_redraw():
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
        if wm is None:
            return
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if getattr(area, "type", "") == "VIEW_3D":
                    area.tag_redraw()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed tagging UI redraw", exc_info=True)


def _sidebar_account_refresh_timer():
    global _SIDEBAR_ACCOUNT_REFRESH_LAST_AT
    global _SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED

    _SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED = False
    prefs = get_prefs()
    if prefs is None or not is_authenticated(prefs):
        return None

    try:
        get_cloud_connection_status(prefs=prefs, force=True, timeout=1.0)
    except (AuthApiError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: deferred Planetka Cloud refresh failed", exc_info=True)

    _SIDEBAR_ACCOUNT_REFRESH_LAST_AT = time.time()
    _tag_view3d_redraw()
    return None


def _schedule_sidebar_account_refresh(force=False):
    global _SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED

    prefs = get_prefs()
    if prefs is None or not is_authenticated(prefs):
        return
    now_ts = time.time()
    cloud_status = get_cached_cloud_connection_status()
    should_refresh = bool(force) or not bool(cloud_status.get("checked", False))
    if not should_refresh:
        elapsed = now_ts - float(_SIDEBAR_ACCOUNT_REFRESH_LAST_AT)
        should_refresh = elapsed >= float(SIDEBAR_ACCOUNT_REFRESH_INTERVAL_SEC)
    if not should_refresh or _SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED:
        return
    try:
        bpy.app.timers.register(
            _sidebar_account_refresh_timer,
            first_interval=float(SIDEBAR_ACCOUNT_REFRESH_INITIAL_DELAY_SEC),
        )
        _SIDEBAR_ACCOUNT_REFRESH_TIMER_REGISTERED = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed scheduling deferred account refresh", exc_info=True)


def _updater_is_busy(status):
    phase = str((status or {}).get("phase", "") or "").strip().lower()
    return bool((status or {}).get("checking", False)) or phase in {
        "checking_manifest",
        "downloading",
        "verifying",
        "installing",
    }


def _updater_redraw_timer():
    global _UPDATER_UI_REDRAW_TIMER_REGISTERED
    try:
        status = get_updater_public_status()
        busy = _updater_is_busy(status)
    except (TypeError, ValueError, RuntimeError, AttributeError):
        logger.debug("Planetka: updater redraw timer failed", exc_info=True)
        busy = False
    _tag_view3d_redraw()
    if busy:
        return float(UPDATER_UI_REDRAW_INTERVAL_SEC)
    _UPDATER_UI_REDRAW_TIMER_REGISTERED = False
    return None


def _schedule_updater_ui_redraw():
    global _UPDATER_UI_REDRAW_TIMER_REGISTERED
    if _UPDATER_UI_REDRAW_TIMER_REGISTERED:
        return
    try:
        bpy.app.timers.register(
            _updater_redraw_timer,
            first_interval=float(UPDATER_UI_REDRAW_INTERVAL_SEC),
        )
        _UPDATER_UI_REDRAW_TIMER_REGISTERED = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed scheduling updater UI redraw", exc_info=True)


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


def _fmt_bytes(value):
    try:
        size = float(value or 0.0)
    except (TypeError, ValueError):
        size = 0.0
    if size >= 1024.0 ** 4:
        return f"{size / (1024.0 ** 4):,.0f} TB"
    if size >= 1024.0 ** 3:
        return f"{size / (1024.0 ** 3):,.0f} GB"
    return f"{size / (1024.0 ** 2):,.0f} MB"


def _fmt_eur(value):
    try:
        return f"€{max(0.0, float(value or 0.0)):,.2f}"
    except (TypeError, ValueError):
        return "€0.00"


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


def _normalize_texture_quality_for_ui(value):
    token = str(value or "").strip().upper()
    if token == "FULL":
        return "FULL"
    if token == "BALANCED":
        return "BALANCED"
    if token == "PREVIEW":
        return "PREVIEW"
    return ""


def _last_visible_texture_quality_label(scene):
    mode = _last_visible_texture_quality_mode(scene)
    if mode == "FULL":
        return "Full"
    if mode == "BALANCED":
        return "Balanced"
    return "Preview"


def _last_visible_texture_quality_mode(scene):
    if _is_animation_prepared(scene):
        return "PREVIEW"
    mode = ""
    if scene is not None:
        try:
            mode = _normalize_texture_quality_for_ui(scene.get(LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY, ""))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            mode = ""
        if not mode:
            try:
                props = getattr(scene, "planetka", None)
                mode = _normalize_texture_quality_for_ui(getattr(props, "texture_quality_mode", ""))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                mode = ""
    if mode in {"PREVIEW", "BALANCED", "FULL"}:
        return mode
    return "PREVIEW"


def _is_planetka_camera_object(camera):
    if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
        return False
    try:
        if str(camera.get("planetka_role", "") or "").strip().lower() == "camera":
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        name = str(getattr(camera, "name", "") or "")
        return name.startswith("Planetka Camera")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _id_block_has_keyframes(id_block):
    if id_block is None:
        return False
    try:
        animation_data = getattr(id_block, "animation_data", None)
        action = getattr(animation_data, "action", None) if animation_data is not None else None
        if _action_has_keyframes(action):
            return True
        for track in tuple(getattr(animation_data, "nla_tracks", ()) if animation_data is not None else ()):
            for strip in tuple(getattr(track, "strips", ()) or ()):
                strip_action = getattr(strip, "action", None)
                if _action_has_keyframes(strip_action):
                    return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


def _planetka_camera_has_keyframes(scene):
    camera = getattr(scene, "camera", None) if scene is not None else None
    if not _is_planetka_camera_object(camera):
        return False
    return _id_block_has_keyframes(camera) or _id_block_has_keyframes(getattr(camera, "data", None))


def _last_resolve_download_bytes_for_ui(scene):
    if scene is None:
        return 0
    for key in (
        "planetka_last_manual_resolve_downloaded_mb",
        "planetka_diag_resolve_downloaded_mb",
        "planetka_diag_resolve_textures_mb",
    ):
        try:
            value = float(scene.get(key, 0.0) or 0.0)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            value = 0.0
        if value > 0.0:
            return int(max(0, round(value * float(1024 ** 2))))
    return 0


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


def _is_active_view_resolve_scope(scene):
    try:
        scope = str(_auto_resolve_scope_mode(scene) or "CAMERA").strip().upper()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        scope = "CAMERA"
    return scope == "ACTIVE_VIEW"


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
    active_download = is_download_active()
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
    return runtime, runtime_code, runtime_text


def _resolve_download_indicator_state(scene, runtime, runtime_code, runtime_text):
    resolve_failure_message = _resolve_failure_message_for_ui(scene)
    inside_earth_warning = _inside_earth_warning_for_ui(scene)
    low_altitude_warning = _low_altitude_warning_for_ui(scene)
    animation_render_running = _is_animation_render_running()

    status_token = str(runtime_code or "").upper()
    suffix = "" if status_token == "DOWNLOADING" else _status_activity_suffix(runtime.get('running', False))
    status_label_text = f"{runtime_text}{suffix}"
    status_icon = _status_icon(runtime_code)
    alert = False
    if resolve_failure_message:
        status_label_text = "Error detected"
        status_icon = "ERROR"
        alert = True
    elif inside_earth_warning:
        status_label_text = "Below Earth's surface"
        status_icon = "ERROR"
        alert = True
    elif low_altitude_warning:
        status_label_text = low_altitude_warning
        status_icon = "ERROR"
        alert = True
    elif animation_render_running:
        status_label_text, status_icon = _animation_render_status_for_ui(scene)
    elif str(runtime_code or "").upper() in {"", "IDLE", "MONITORING"}:
        status_label_text = f"Complete - Showing {_last_visible_texture_quality_label(scene)}"

    progress = get_download_progress()
    progress_quality_mode = _normalize_texture_quality_for_ui(progress.get("quality_mode", ""))
    total_bytes = int(progress.get("total_bytes", 0) or 0)
    downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
    progress_download_active = bool(progress.get("download_active", False))
    animation_status_upper = str(status_label_text or "").strip().upper()
    animation_download_phase = bool(
        animation_render_running
        and ("DOWNLOADING" in animation_status_upper or "LICENC" in animation_status_upper)
    )
    if animation_render_running and not animation_download_phase:
        total_bytes = 0
        downloaded_bytes = 0
        progress_download_active = False
    animation_waiting_for_download = bool(
        animation_render_running
        and not progress_download_active
        and total_bytes <= 0
        and downloaded_bytes <= 0
    )
    if (
        total_bytes <= 0
        and downloaded_bytes <= 0
        and status_token in {"", "IDLE", "MONITORING"}
        and not animation_waiting_for_download
    ):
        total_bytes = _last_resolve_download_bytes_for_ui(scene)
        downloaded_bytes = total_bytes
    factor = 0.0
    if animation_waiting_for_download and not ("LICENC" in animation_status_upper or "DOWNLOADING" in animation_status_upper):
        factor = 1.0
    elif total_bytes > 0:
        factor = max(0.0, min(1.0, float(downloaded_bytes) / float(total_bytes)))
    elif status_token in {"FINALIZING", "FINALIZE_QUEUED"}:
        factor = 1.0

    if total_bytes > 0:
        progress_text = f"{_fmt_bytes(downloaded_bytes)} / {_fmt_bytes(total_bytes)}"
    elif downloaded_bytes > 0:
        progress_text = f"{_fmt_bytes(downloaded_bytes)} downloaded"
    elif animation_waiting_for_download and "LICENC" in animation_status_upper:
        progress_text = "Confirming licence"
    elif animation_waiting_for_download and "DOWNLOADING" in animation_status_upper:
        progress_text = "Preparing download"
    elif animation_waiting_for_download:
        progress_text = "Data ready"
    elif status_token == "QUEUED":
        progress_text = "Waiting to start"
    elif status_token == "PREPARING":
        progress_text = "Preparing download"
    elif status_token in {"FINALIZING", "FINALIZE_QUEUED"}:
        progress_text = "Download finished"
    elif resolve_failure_message:
        progress_text = "Resolve failed"
    elif inside_earth_warning or low_altitude_warning:
        progress_text = "Resolve paused"
    elif status_token in {"", "IDLE", "MONITORING"}:
        progress_text = f"{_fmt_bytes(downloaded_bytes)} / {_fmt_bytes(total_bytes)}"
    else:
        progress_text = "Waiting for data"

    active_status = status_token in {"QUEUED", "PREPARING", "DOWNLOADING", "FINALIZING", "FINALIZE_QUEUED"}
    active = bool(progress_download_active or active_status or runtime.get("running", False))
    quality_mode = progress_quality_mode if active else ""
    if not quality_mode and active:
        quality_mode = _normalize_texture_quality_for_ui(runtime.get("quality_mode", ""))
    if not quality_mode and active:
        try:
            props = getattr(scene, "planetka", None)
            quality_mode = _normalize_texture_quality_for_ui(getattr(props, "texture_quality_mode", ""))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            quality_mode = ""
    if not quality_mode:
        quality_mode = _last_visible_texture_quality_mode(scene)

    return {
        "status_text": status_label_text,
        "status_icon": status_icon,
        "alert": bool(alert),
        "factor": factor,
        "progress_text": progress_text,
        "total_bytes": total_bytes,
        "downloaded_bytes": downloaded_bytes,
        "download_active": bool(progress_download_active),
        "active": active,
        "runtime_code": status_token,
        "quality_mode": quality_mode,
    }


def _draw_resolve_status_line(layout, scene, runtime, runtime_code, runtime_text):
    resolve_failure_message = _resolve_failure_message_for_ui(scene)
    inside_earth_warning = _inside_earth_warning_for_ui(scene)
    low_altitude_warning = _low_altitude_warning_for_ui(scene)
    animation_render_running = _is_animation_render_running()

    status_token = str(runtime_code or "").upper()
    status_text = str(runtime_text or "Idle")
    status_icon = _status_icon(status_token)
    alert = False

    if resolve_failure_message:
        status_text = resolve_failure_message
        status_icon = "ERROR"
        alert = True
    elif inside_earth_warning:
        status_text = "Below Earth's surface"
        status_icon = "INFO"
    elif low_altitude_warning:
        status_text = low_altitude_warning
        status_icon = "INFO"
    elif animation_render_running:
        status_text, status_icon = _animation_render_status_for_ui(scene)
    elif status_token == "PREPARING":
        status_text = "Preparing Download"
    elif status_token == "DOWNLOADING":
        progress = get_download_progress()
        downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
        total_bytes = int(progress.get("total_bytes", 0) or 0)
        downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
        total_mb = float(total_bytes) / (1024.0 * 1024.0)
        if total_bytes > 0:
            status_text = f"Downloading ({downloaded_mb:.2f} / {total_mb:.2f} MB)"
        else:
            status_text = f"Downloading ({downloaded_mb:.2f} MB)"
    elif status_token in {"", "IDLE", "MONITORING"}:
        status_text = "Idle"
        status_icon = "CHECKMARK"

    suffix = _status_activity_suffix(runtime.get("running", False))
    if status_token == "DOWNLOADING" or resolve_failure_message or inside_earth_warning or low_altitude_warning:
        suffix = ""

    status_row = layout.row()
    status_row.alert = bool(alert)
    status_row.label(text=f"{status_text}{suffix}", icon=status_icon)


def _draw_resolve_download_indicator(layout, scene, runtime, runtime_code, runtime_text):
    state = _resolve_download_indicator_state(scene, runtime, runtime_code, runtime_text)
    box = layout.box()
    box.alert = bool(state.get("alert", False))
    box.label(text=str(state.get("status_text", "") or "Idle"), icon=str(state.get("status_icon", "INFO") or "INFO"))
    box.progress(
        factor=float(state.get("factor", 0.0) or 0.0),
        type='BAR',
        text=str(state.get("progress_text", "") or "Waiting for data"),
    )


def _estimate_bytes_for_quality(estimates, mode):
    mode_key = str(mode or "").upper()
    try:
        value = estimates.get(mode_key)
    except (AttributeError, TypeError, ValueError):
        value = None
    if value is None:
        return None
    try:
        return int(max(0, round(float(value))))
    except (TypeError, ValueError):
        return None


def _draw_quality_meta_row(layout, progress_text, usage_label=""):
    if not str(usage_label or "").strip():
        row = layout.row(align=True)
        row.alignment = 'CENTER'
        row.label(text=str(progress_text or "-"))
        return
    row = layout.split(factor=0.68, align=True)
    left = row.row(align=True)
    left.alignment = 'CENTER'
    left.label(text=str(progress_text or "-"))
    right = row.row(align=True)
    right.alignment = 'RIGHT'
    right.label(text=str(usage_label or ""))


def _quality_total_size_label(estimate_bytes):
    if estimate_bytes is None:
        return "Calculating size"
    try:
        return _fmt_bytes(int(max(0, int(estimate_bytes))))
    except (TypeError, ValueError):
        return "Calculating size"


def _scene_licence_price_label(prefs):
    label = str(getattr(prefs, "scene_licence_price_label", "") or "").strip() if prefs is not None else ""
    if label:
        return label
    try:
        cents = int(getattr(prefs, "scene_licence_price_cents", 0) or 0) if prefs is not None else 0
    except (TypeError, ValueError, RuntimeError, AttributeError):
        cents = 0
    return f"€{(cents / 100):.2f}" if cents > 0 else ""


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


class PLANETKA_PT_AnimationStopPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Animation Render"
    bl_idname = "PLANETKA_PT_animation_stop"
    bl_order = 8999
    bl_options = set()

    @classmethod
    def poll(cls, context):
        _ = context
        return _is_animation_render_running()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        layout = self.layout
        layout.enabled = True
        status_text, status_icon = _animation_render_status_for_ui(scene)
        layout.label(text=status_text, icon=status_icon)
        stop_row = layout.row(align=True)
        stop_row.alert = True
        stop_row.scale_y = 1.45
        stop_row.operator(
            "planetka.animation_stop",
            text="Stop Animation Render",
            icon="CANCEL",
        )


class PLANETKA_OT_ToggleUiSection(bpy.types.Operator):
    bl_idname = "planetka.toggle_ui_section"
    bl_label = "Toggle UI Section"
    bl_description = "Expand or collapse a Planetka UI section"
    bl_options = {'INTERNAL'}

    section_key: bpy.props.StringProperty(default="")
    default_open: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        scene = getattr(context, "scene", None)
        key = str(getattr(self, "section_key", "") or "").strip()
        if scene is None or not key:
            return {'CANCELLED'}
        try:
            current = bool(scene.get(key, bool(getattr(self, "default_open", True))))
            scene[key] = not current
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed toggling UI section %s", key, exc_info=True)
            return {'CANCELLED'}
        return {'FINISHED'}


def _draw_collapsible_subsection(layout, scene, title, icon, section_key, default_open=True):
    expanded = bool(default_open)
    if scene is not None:
        try:
            expanded = bool(scene.get(section_key, bool(default_open)))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            expanded = bool(default_open)

    box = layout.box()
    header = box.row(align=True)
    header.use_property_split = False
    header.use_property_decorate = False
    toggle = header.operator(
        "planetka.toggle_ui_section",
        text=str(title or ""),
        icon='DISCLOSURE_TRI_DOWN' if expanded else 'DISCLOSURE_TRI_RIGHT',
        emboss=False,
    )
    toggle.section_key = str(section_key or "")
    toggle.default_open = bool(default_open)
    if icon:
        icon_row = header.row(align=True)
        icon_row.alignment = 'RIGHT'
        icon_row.label(text="", icon=icon)
    return box if expanded else None


def _cloud_subsection_key(kind, cloud_obj):
    name = str(getattr(cloud_obj, "name", "") or "cloud")
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "cloud"
    return f"planetka_ui_cloud_{kind}_{safe_name}_expanded"


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
    status = get_cached_cloud_connection_status()
    if not bool(status.get("checked", False)):
        _schedule_sidebar_account_refresh(force=True)
        return False
    _schedule_sidebar_account_refresh(force=False)
    return bool(status.get("online", False))


def _account_panel_should_default_collapsed(context=None):
    prefs = get_prefs()
    if not is_authenticated(prefs):
        return False
    target_scene = getattr(context, "scene", None) if context is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return True
    try:
        if ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY in target_scene:
            return bool(target_scene.get(ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY, True))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return True
    # Missing scene marker happens briefly in newly opened Blender files before
    # load handlers write persistent UI defaults. Keep the authenticated default
    # collapsed immediately to avoid a visible open-then-close flash.
    return True


def _is_paid_connected_account():
    return False


def _full_texture_quality_allowed():
    return _is_connected()


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
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for obj in tuple(bpy.data.objects):
            if bool(obj.get(ANIMATION_SEGMENT_TAG_KEY, False)):
                return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
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
    if "session expired" in lowered or "connect your account again" in lowered:
        return "Session expired", "ERROR", True
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
    updater_busy = _updater_is_busy(updater)
    latest_version = str(updater.get("latest_version") or "").strip()
    current_version = str(updater.get("current_version") or "").strip()
    phase = str(updater.get("phase") or "").strip().lower()
    message = str(updater.get("message") or "").strip()
    last_error = str(updater.get("last_error") or "").strip()
    try:
        downloaded_bytes = int(updater.get("downloaded_bytes", 0) or 0)
    except (TypeError, ValueError):
        downloaded_bytes = 0
    try:
        total_bytes = int(updater.get("download_total_bytes", 0) or 0)
    except (TypeError, ValueError):
        total_bytes = 0

    if updater_busy:
        _schedule_updater_ui_redraw()

    version_row = layout.row()
    version_row.label(text=f"Addon version: {current_version or 'unknown'}", icon="BLENDER")
    updates_row = layout.row()
    updates_row.enabled = not updater_busy
    updates_row.operator("planetka.check_updates", text="Check for updates", icon="FILE_REFRESH")
    if updater_busy:
        status_box = layout.box()
        status_box.label(
            text=message or f"Updating Planetka{_status_activity_suffix(True)}",
            icon="TIME",
        )
        if total_bytes > 0 and hasattr(status_box, "progress"):
            factor = max(0.0, min(1.0, float(downloaded_bytes) / float(total_bytes)))
            status_box.progress(
                factor=factor,
                type='BAR',
                text=f"{_fmt_bytes(downloaded_bytes)} / {_fmt_bytes(total_bytes)}",
            )
        elif phase in {"verifying", "installing"} and hasattr(status_box, "progress"):
            status_box.progress(
                factor=1.0,
                type='BAR',
                text=message or "Finishing update",
            )
        else:
            status_box.label(text=f"Please wait{_status_activity_suffix(True)}", icon="INFO")
    elif updater_ready and latest_version:
        row = layout.row()
        row.alert = True
        row.label(text=f"Update available: {latest_version}", icon="ERROR")
        row.operator("planetka.update_now", text="Update now", icon="IMPORT")
    elif message:
        message_box = layout.box()
        message_box.alert = bool(phase == "error" or last_error)
        message_box.label(text=message, icon="ERROR" if message_box.alert else "CHECKMARK")
        if message.lower().startswith("updated to "):
            message_box.label(text="Restart Blender to finish the update.", icon="INFO")
        elif "restart blender" in message.lower():
            message_box.label(text="Restart Blender to finish the update.", icon="INFO")


def _has_active_camera(scene):
    return bool(scene is not None and getattr(scene, "camera", None) is not None)


def _draw_account_panel(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False

    from .extension_prefs import get_prefs

    prefs = get_prefs()
    authenticated = bool(is_authenticated(prefs))
    if authenticated:
        _schedule_sidebar_account_refresh(force=False)
    cloud_status = (
        get_cached_cloud_connection_status()
        if authenticated
        else {"online": False, "message": "", "checked": False}
    )
    checked = bool(cloud_status.get("checked", False))
    connected = bool(authenticated and checked and cloud_status.get("online", False))
    status_message = get_status_message(prefs)
    key_text = str(getattr(prefs, "auth_api_key_input", "") or "").strip()
    key_mask = str(getattr(prefs, "auth_api_key_mask", "") or "").strip()
    stored_key = str(getattr(prefs, "auth_api_key", "") or "").strip()
    key_locked = bool(authenticated)
    inline_status_text, inline_status_icon, inline_status_alert = _api_key_inline_status(
        prefs,
        connected,
        status_message,
    )

    request_row = layout.row()
    request_row.enabled = not key_locked
    request_row.operator("planetka.account_login", text="Request Account Access", icon="URL")

    key_row = layout.row(align=True)
    if key_locked:
        key_row.enabled = False
        if key_mask:
            key_row.prop(prefs, "auth_api_key_mask", text="Access Key")
        else:
            key_row.prop(prefs, "auth_api_key_input", text="Access Key")
    else:
        key_row.enabled = True
        key_row.prop(prefs, "auth_api_key_input", text="Access Key")
    if inline_status_text and not connected:
        key_status = key_row.row(align=True)
        key_status.alert = bool(inline_status_alert)
        key_status.label(text=inline_status_text, icon=inline_status_icon)

    key_action_row = layout.row(align=True)
    connect_row = key_action_row.row(align=True)
    connect_row.enabled = (not key_locked) and bool(key_text)
    connect_row.operator("planetka.account_open_login", text="Connect Account", icon="CHECKMARK")

    logout_row = layout.row(align=True)
    logout_row.enabled = authenticated
    logout_row.operator("planetka.account_logout", text="Log Out", icon="X")

    try:
        email = str(get_connected_email(prefs) or "").strip()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        email = str(getattr(prefs, "auth_email", "") or "").strip()
    cloud_message = str(cloud_status.get("message", "") or "").strip()
    cloud_overloaded = bool(cloud_message == CLOUD_OVERLOADED_MESSAGE)
    status_icon = "CHECKMARK" if connected else ("INFO" if authenticated and not checked else "ERROR")
    if connected:
        status_text = "Status: Connected to Planetka Cloud"
    elif authenticated and not checked:
        status_text = "Status: Checking Planetka Cloud"
    elif authenticated and cloud_overloaded:
        status_text = "Status: Planetka Cloud overloaded"
    elif authenticated:
        status_text = "Status: Not connected to Planetka Cloud"
    else:
        status_text = "Status: Not connected"
    status_row = layout.row(align=True)
    status_row.alert = bool(authenticated and checked and not connected)
    status_row.label(text=status_text, icon=status_icon)
    layout.label(text=f"Account: {email or '-'}", icon="USER")
    try:
        account_tier = str(get_account_tier(prefs) or "").strip().lower()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        account_tier = ""
    if account_tier == "pro":
        account_type_label = "Pro (Commercial)"
    elif account_tier == "free":
        account_type_label = "Free (Personal)"
    else:
        account_type_label = "-"
    layout.label(text=f"Account type: {account_type_label}", icon="COMMUNITY")

def _draw_general_account_summary(layout):
    from .extension_prefs import get_prefs

    prefs = get_prefs()
    if prefs is not None and not is_authenticated(prefs):
        try:
            ensure_authenticated_session(prefs)
        except (AuthApiError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: automatic anonymous session start failed", exc_info=True)
    authenticated = bool(is_authenticated(prefs))
    if authenticated:
        _schedule_sidebar_account_refresh(force=False)
    cloud_status = (
        get_cached_cloud_connection_status()
        if authenticated
        else {"online": False, "message": "", "checked": False}
    )
    checked = bool(cloud_status.get("checked", False))
    connected = bool(authenticated and checked and cloud_status.get("online", False))
    cloud_message = str(cloud_status.get("message", "") or "").strip()
    cloud_overloaded = bool(cloud_message == CLOUD_OVERLOADED_MESSAGE)
    status_icon = "CHECKMARK" if connected else ("INFO" if authenticated and not checked else "ERROR")
    if connected:
        status_text = "Connected to Planetka Cloud"
    elif authenticated and not checked:
        status_text = "Checking Planetka Cloud"
    elif authenticated and cloud_overloaded:
        status_text = "Planetka Cloud overloaded"
    elif authenticated:
        status_text = "Not connected to Planetka Cloud"
    else:
        status_text = "Starting Planetka session"
    try:
        account_tier = str(get_account_tier(prefs) or "").strip().lower()
    except (TypeError, ValueError, RuntimeError, AttributeError):
        account_tier = ""
    account_type_label = "Pro" if account_tier == "pro" else "Free"
    status_message = get_status_message(prefs)

    account_box = layout.box()
    account_box.label(text="Planetka Cloud", icon="WORLD")
    row = account_box.row()
    row.label(text="Status")
    row.label(text=status_text, icon=status_icon)
    row = account_box.row()
    row.label(text="Account Type")
    row.label(text=account_type_label)
    if account_tier != "pro":
        account_box.operator("planetka.account_upgrade", text="Upgrade to Pro", icon="KEY_HLT")
        restore_box = account_box.box()
        restore_box.label(text="Restore Pro", icon="KEY_HLT")
        if prefs is not None:
            restore_box.prop(prefs, "pro_restore_license_key_input", text="Planetka Licence Key")
        restore_box.operator("planetka.account_restore_pro", text="Restore Pro", icon="CHECKMARK")

    history_box = account_box.box()
    history_box.label(text="Scene Licences", icon="FILE_TICK")
    if prefs is not None:
        history_box.prop(prefs, "scene_licence_restore_email", text="Email")
    history_box.operator("planetka.scene_licences_send_access_link", text="Send Access Link", icon="URL")
    history_box.operator("planetka.scene_purchases_refresh", text="Refresh Scene Licences", icon="LOOP_BACK")
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    try:
        purchases = json.loads(str(scene.get("planetka_scene_purchase_history_json", "[]") or "[]")) if scene is not None else []
    except (TypeError, ValueError, RuntimeError, AttributeError, json.JSONDecodeError):
        purchases = []
    if purchases:
        for purchase in purchases[:8]:
            if not isinstance(purchase, dict):
                continue
            scene_id = str(purchase.get("scene_id", "") or "")
            camera_payload = purchase.get("camera", {}) if isinstance(purchase.get("camera", {}), dict) else {}
            label = str(camera_payload.get("place_name", "") or purchase.get("purchased_at", "") or scene_id)
            row = history_box.row(align=True)
            row.label(text=label[:32])
            op = row.operator("planetka.scene_purchase_restore", text="Restore", icon="LOOP_BACK")
            op.scene_id = scene_id
    else:
        history_box.label(text="No scene licences loaded.", icon="INFO")

    if authenticated and checked and not connected:
        warning_box = layout.box()
        warning_box.alert = True
        if cloud_overloaded:
            warning_box.label(text="Planetka Cloud is busy.", icon="ERROR")
        else:
            warning_box.label(text="Planetka Cloud connection required.", icon="ERROR")
        warning_box.label(text=cloud_message or "Check your internet connection and try again.")

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
    row.operator("planetka.set_background_black", text="Set Background to Black", icon="SHADING_RENDERED")

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
        estimates = get_resolve_size_estimates(scene)

        runtime, runtime_code, runtime_text = _resolve_runtime_display(scene)
        _draw_resolve_status_line(layout, scene, runtime, runtime_code, runtime_text)
        quality_box = layout.box()
        header_row = quality_box.row(align=True)
        header_row.use_property_split = False
        header_row.use_property_decorate = False
        header_row.label(text="Quality Level", icon="TEXTURE")
        resolve_failure_message = _resolve_failure_message_for_ui(scene)

        selected_auto_quality = _normalize_texture_quality_for_ui(getattr(props, "texture_quality_mode", "PREVIEW"))
        if not selected_auto_quality:
            selected_auto_quality = "PREVIEW"

        qualities = (
            ("PREVIEW", "Preview"),
            ("BALANCED", "Balanced"),
            ("FULL", "Full"),
        )
        button_row = quality_box.row(align=True)
        pro_account = is_pro_account(prefs)
        scene_price_label = _scene_licence_price_label(prefs)
        for mode_key, label in qualities:
            quality_allowed = allows_texture_quality_for_context(prefs, mode_key)
            button_label = label
            if mode_key == "FULL" and not pro_account and scene_price_label:
                button_label = f"Full ({scene_price_label})"
            mode_col = button_row.column(align=True)
            estimate_bytes = _estimate_bytes_for_quality(estimates, mode_key)
            operator_row = mode_col.row(align=True)
            operator_row.enabled = quality_allowed
            operator_row.alert = bool(resolve_failure_message and selected_auto_quality == mode_key)
            operator_row.operator(
                "planetka.set_texture_quality_and_resolve",
                text=(f"{button_label} (Pro only)" if not quality_allowed else button_label),
                depress=(selected_auto_quality == mode_key),
            ).texture_quality_mode = mode_key
            _draw_quality_meta_row(
                mode_col,
                _quality_total_size_label(estimate_bytes),
            )
        if resolve_failure_message:
            error_row = quality_box.row(align=True)
            error_row.alert = True
            error_row.label(text=resolve_failure_message, icon="ERROR")

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
        unlock_row.enabled = bool(base_enabled) and _planetka_camera_has_keyframes(scene)
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
    search_col = location_box.column(align=True)
    search_col.use_property_split = False
    search_col.use_property_decorate = False
    search_col.label(text="Search")
    search_col.prop(props, "nav_city_search", text="")
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
    shot_box.prop(props, "nav_focal_length_mm", text="Focal Length (mm)", icon="CAMERA_DATA")

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

_SURFACE_GRADING_SECTION_ICON = {
    "Global": "WORLD",
    "Water": "MOD_OCEAN",
    "Elevation": "MOD_DISPLACE",
    "Night Lights": "LIGHT_SUN",
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
            section_header.label(text=section, icon=_SURFACE_GRADING_SECTION_ICON.get(section, "NONE"))
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


_ATMOSPHERE_SOCKET_LABELS = {
    "Scattering Color - Main": "Scattering Color",
    "Anisotropy - Main": "Anisotropy",
    "Scattering Color - Low Altitude": "Scattering Color",
    "Anisotropy - Low Altitude": "Anisotropy",
    "Absorbtion Color": "Absorption Color",
}

_ATMOSPHERE_SOCKET_TOOLTIPS = {
    "Height (km)": "Height of the atmosphere shell above Earth in kilometres. Higher values make the glow extend farther from the horizon.",
    "Density Coefficient": "Multiplier for overall volume density. Higher values make the atmosphere thicker, brighter and more opaque.",
    "Falloff Exponent": "Controls how quickly density fades with altitude. Higher values concentrate haze near the surface; lower values spread it upward.",
    "Scattering Color - Main": "Primary color of scattered light through the upper atmosphere.",
    "Anisotropy - Main": "Directionality of main scattering. Positive values push light forward for stronger rim and horizon glow; lower values look more even.",
    "Absorption Color": "Color removed from light as it travels through the atmosphere. This tints sunsets and shadows toward the opposite color.",
    "Absorbtion Color": "Color removed from light in the EEVEE supplement atmosphere shader. This tints the atmospheric glow.",
    "Absorption Strength": "Strength of light absorption. Higher values make the atmosphere darker and more strongly color-filtered.",
    "Scattering Color - Low Altitude": "Scattering color near the surface and horizon haze.",
    "Anisotropy - Low Altitude": "Directionality of low-altitude haze. Higher values emphasize glancing-angle glow near the horizon.",
    "Scattering Color": "Tint of the EEVEE supplement atmosphere glow.",
    "Rim Exponent": "Controls how tightly the EEVEE supplement glow is concentrated around the rim. Higher values make a thinner rim.",
    "Opacity": "Overall transparency of the EEVEE supplement atmosphere shell.",
}


def _iter_atmosphere_nodes(mode="VOLUMETRIC"):
    mode_token = str(mode or "VOLUMETRIC").strip().upper()
    object_name = "Atmosphere - Volumetric"
    group_name = "Planetka Atmosphere Group"
    try:
        from .asset_builder import (
            FAKE_ATMOSPHERE_GROUP_NAME,
            FAKE_ATMOSPHERE_OBJECT_NAME,
            VOLUMETRIC_ATMOSPHERE_GROUP_NAME,
            VOLUMETRIC_ATMOSPHERE_OBJECT_NAME,
        )

        if mode_token == "EEVEE":
            object_name = str(FAKE_ATMOSPHERE_OBJECT_NAME or "Atmosphere - EEVEE supplement")
            group_name = str(FAKE_ATMOSPHERE_GROUP_NAME or "Planetka Atmosphere EEVEE Supplement Group")
        else:
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
            if node_group_name == group_name or (
                "atmosphere" in lowered
                and ("eevee" in lowered and "supplement" in lowered) == (mode_token == "EEVEE")
            ):
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


def _socket_map(node):
    return {str(getattr(socket, "name", "")): socket for socket in _iter_atmosphere_input_sockets(node)}


def _apply_socket_tooltip(socket):
    tooltip = _ATMOSPHERE_SOCKET_TOOLTIPS.get(str(getattr(socket, "name", "")))
    if not tooltip:
        return
    try:
        socket.description = str(tooltip)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _draw_atmosphere_socket(container, socket, label=None):
    if socket is None:
        return
    _apply_socket_tooltip(socket)
    row = container.row()
    try:
        row.prop(socket, "default_value", text=str(label or _ATMOSPHERE_SOCKET_LABELS.get(socket.name, socket.name)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _draw_atmosphere_notice(layout, mode):
    notice = layout.box()
    if str(mode or "VOLUMETRIC").strip().upper() == "VOLUMETRIC":
        for line in (
            "Recommended Render Settings",
            "In Volumes Section:",
            "Biased: On",
            "Step Rate Render: 1.00",
            "Viewport: 1.00",
            "Max Steps: 16 (+-8)",
        ):
            notice.label(text=line)
    else:
        for line in (
            "Recommended Render Settings",
            "In Volume section:",
            "Resolution: 1:2 or 1:1",
            "Steps: 32",
            "Distribution: 1.000",
            "Max Depth: 16",
        ):
            notice.label(text=line)


def _draw_volumetric_atmosphere_node(layout, node):
    sockets = _socket_map(node)
    for socket_name in ("Height (km)", "Density Coefficient", "Falloff Exponent"):
        _draw_atmosphere_socket(layout, sockets.get(socket_name))

    main_box = layout.box()
    main_box.label(text="Main Settings")
    for socket_name in (
        "Scattering Color - Main",
        "Anisotropy - Main",
        "Absorption Color",
        "Absorption Strength",
    ):
        _draw_atmosphere_socket(main_box, sockets.get(socket_name))

    low_box = layout.box()
    low_box.label(text="Low Altitude Settings")
    for socket_name in ("Scattering Color - Low Altitude", "Anisotropy - Low Altitude"):
        _draw_atmosphere_socket(low_box, sockets.get(socket_name))


def _draw_eevee_supplement_atmosphere_node(layout, node):
    sockets = _socket_map(node)
    for socket_name in (
        "Scattering Color",
        "Absorbtion Color",
        "Rim Exponent",
        "Opacity",
    ):
        _draw_atmosphere_socket(layout, sockets.get(socket_name))


def _iter_global_cloud_material_nodes():
    obj = bpy.data.objects.get("Planetka Global Cloud Layer")
    if obj is None:
        return []
    nodes = []
    for slot in getattr(obj, "material_slots", ()):
        material = getattr(slot, "material", None)
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        for node in getattr(node_tree, "nodes", ()):
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            group = getattr(node, "node_tree", None)
            group_name = str(getattr(group, "name", ""))
            if group_name == "Planetka Cloud Material" or "global cloud" in group_name.lower():
                nodes.append(node)
    return nodes


def _draw_global_cloud_material_settings(layout):
    nodes = _iter_global_cloud_material_nodes()
    if not nodes:
        return
    settings = layout.box()
    settings.label(text="Settings")
    for node in nodes:
        sockets = _socket_map(node)
        for socket_name in (
            "Cloud Color",
            "Density",
            "Density Gamma",
            "Contrast",
            "Clouds on Horizon Transparency",
            "Subsurface Scattering Scale Coefficient",
            "IOR",
            "Roughness",
            "Anisotropy",
            "Displacement (Bump) Scale Coefficient",
        ):
            _draw_atmosphere_socket(settings, sockets.get(socket_name))


def _draw_global_clouds(layout, scene, props):
    box = layout.box()
    box.label(text="Global Clouds", icon="FORCE_TURBULENCE")
    box.prop(props, "enable_global_clouds", text="Enable Global Clouds")
    if not bool(getattr(props, "enable_global_clouds", False)):
        return

    box.label(text="Texture Source")
    source_row = box.row(align=True)
    source_row.prop_enum(props, "global_cloud_texture_source", "CLOUD", text="Planetka Cloud")
    source_row.prop_enum(props, "global_cloud_texture_source", "LOCAL", text="Local File")

    source = str(getattr(props, "global_cloud_texture_source", "CLOUD") or "CLOUD").strip().upper()
    if source == "LOCAL":
        box.prop(props, "global_cloud_local_file", text="Cloud Texture")
        if not str(getattr(props, "global_cloud_local_file", "") or "").strip():
            box.label(text="Select a local Global Clouds texture file.", icon="INFO")

    obj = bpy.data.objects.get("Planetka Global Cloud Layer")
    if obj is None:
        box.label(text="Global Clouds will appear after Create Earth.", icon="INFO")
    else:
        cloud_box = _draw_collapsible_subsection(
            box,
            scene,
            "Global Cloud Layer",
            "FORCE_TURBULENCE",
            _cloud_subsection_key("global", obj),
            default_open=True,
        )
        if cloud_box is not None:
            _draw_global_cloud_material_settings(cloud_box)


def _draw_local_clouds(layout, context, props):
    try:
        from . import clouds_local as cloud_runtime
    except (ImportError, ModuleNotFoundError):
        box = layout.box()
        box.label(text="Texture-Based Clouds", icon="FORCE_WIND")
        box.label(text="Texture-based cloud runtime is unavailable.", icon="ERROR")
        return

    box = layout.box()
    box.label(text="Texture-Based Clouds", icon="FORCE_WIND")
    box.prop(props, "enable_local_clouds", text="Enable Texture-Based Clouds")
    if not bool(getattr(props, "enable_local_clouds", False)):
        return

    source_row = box.row(align=True)
    source_row.prop_enum(props, "local_cloud_texture_source", "CLOUD", text="Planetka Cloud")
    source_row.prop_enum(props, "local_cloud_texture_source", "LOCAL", text="Local EXR File")

    source = str(getattr(props, "local_cloud_texture_source", "CLOUD") or "CLOUD").strip().upper()
    picker_box = box.box()
    if source == "LOCAL":
        picker_box.prop(props, "local_cloud_local_file", text="Cloud Mask")
        if not str(getattr(props, "local_cloud_local_file", "") or "").strip():
            picker_box.label(text="Select a local EXR cloud mask file.", icon="INFO")
    else:
        picker_box.label(text="Planetka Cloud Masks", icon="IMAGE_DATA")
        picker_box.template_icon_view(props, "local_cloud_texture", show_labels=True, scale=5.0, scale_popup=6.0)

    add_row = picker_box.row(align=True)
    add_row.operator("planetka.add_local_cloud", text="Add Cloud", icon="ADD")

    progress = cloud_runtime.get_cloud_download_progress()
    progress_error = str(progress.get("error", "") or "").strip()
    progress_label = str(progress.get("label", "") or "")
    is_texture_based_download = "TEXTURE-BASED" in progress_label.upper()
    if bool(progress.get("active", False)) and is_texture_based_download:
        downloaded = max(0, int(progress.get("downloaded_bytes", 0) or 0))
        total = max(0, int(progress.get("total_bytes", 0) or 0))
        if total > 0:
            text = f"Downloading: {_fmt_bytes(downloaded)} / {_fmt_bytes(total)}"
            factor = min(1.0, max(0.0, downloaded / float(total)))
        else:
            text = f"Downloading: {_fmt_bytes(downloaded)}"
            factor = 0.0
        try:
            picker_box.progress(factor=factor, type='BAR', text=text)
        except (AttributeError, TypeError, RuntimeError):
            picker_box.label(text=text, icon="IMPORT")
    elif progress_error and is_texture_based_download:
        err_box = picker_box.box()
        err_box.alert = True
        err_box.label(text=progress_error, icon="ERROR")

    clouds = cloud_runtime._sort_cloud_objects_by_suffix(list(cloud_runtime._iter_local_cloud_objects()))
    if not clouds:
        box.label(text="No texture-based clouds added yet.", icon="INFO")
        return

    scene = getattr(context, "scene", None) if context else None
    for idx, cloud_obj in enumerate(clouds, start=1):
        cloud_box = _draw_collapsible_subsection(
            box,
            scene,
            cloud_runtime._cloud_title(cloud_obj.name, idx, "Cloud No"),
            "FORCE_WIND",
            _cloud_subsection_key("local", cloud_obj),
            default_open=True,
        )
        if cloud_box is None:
            continue
        cloud_box.prop(
            cloud_obj,
            "hide_viewport",
            text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
            toggle=True,
            icon="HIDE_OFF",
        )
        texture_path = str(cloud_obj.get(cloud_runtime.LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP, "") or "").strip()
        texture_name = str(getattr(cloud_obj, cloud_runtime.LOCAL_CLOUD_OBJ_TEXTURE_PROP, "") or "").strip()
        if not texture_name or texture_name == "NONE":
            texture_name = os.path.basename(texture_path) if texture_path else "No cloud mask assigned"
        cloud_box.label(text=texture_name, icon="IMAGE_DATA")

        downscale_warning = str(cloud_obj.get(cloud_runtime.LOCAL_CLOUD_DOWNSCALE_WARNING_PROP, "") or "").strip()
        if downscale_warning:
            warning_box = cloud_box.box()
            warning_box.label(text=downscale_warning, icon="INFO")

        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_SIZE_COEF, text="Size")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_LATITUDE, text="Latitude")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_LONGITUDE, text="Longitude")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_ROTATION_DEG, text="Rotation")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_THICKNESS_M, text="Thickness (m)")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_DENSITY, text="Density")
        cloud_box.prop(cloud_obj, cloud_runtime.LOCAL_CLOUD_PROP_DENSITY_GAMMA, text="Density Gamma")

        row = cloud_box.row(align=True)
        op = row.operator("planetka.reset_local_cloud_to_camera_view", text="Reset to Camera", icon="TRACKING")
        op.object_name = cloud_obj.name
        op = row.operator("planetka.delete_local_cloud", text="Delete", icon="TRASH")
        op.object_name = cloud_obj.name


def _draw_vdb_clouds(layout, context, props):
    prefs = get_prefs()
    if not is_pro_account(prefs):
        box = layout.box()
        box.enabled = False
        box.label(text="VDB Clouds (Cycles only, Pro only)", icon="VOLUME_DATA")
        box.prop(props, "enable_vdb_clouds", text="Enable VDB Clouds (Cycles only, Pro only)")
        return

    try:
        from . import clouds_local as cloud_runtime
    except (ImportError, ModuleNotFoundError):
        box = layout.box()
        box.label(text="VDB Clouds (Cycles only)", icon="VOLUME_DATA")
        box.label(text="VDB cloud runtime is unavailable.", icon="ERROR")
        return

    box = layout.box()
    box.label(text="VDB Clouds (Cycles only)", icon="VOLUME_DATA")
    box.prop(props, "enable_vdb_clouds", text="Enable VDB Clouds (Cycles only)")
    if not bool(getattr(props, "enable_vdb_clouds", False)):
        return

    source_row = box.row(align=True)
    source_row.prop_enum(props, "vdb_cloud_source", "CLOUD", text="Planetka Cloud")
    source_row.prop_enum(props, "vdb_cloud_source", "LOCAL", text="Local VDB File")

    source = str(getattr(props, "vdb_cloud_source", "CLOUD") or "CLOUD").strip().upper()
    picker_box = box.box()
    if source == "LOCAL":
        picker_box.prop(props, "vdb_cloud_file", text="VDB File")
        if not str(getattr(props, "vdb_cloud_file", "") or "").strip():
            picker_box.label(text="Select a local VDB file.", icon="INFO")
    else:
        picker_box.label(text="Planetka Cloud VDB Presets", icon="VOLUME_DATA")
        picker_box.template_icon_view(props, "vdb_cloud_preset", show_labels=True, scale=5.0, scale_popup=6.0)

    add_row = picker_box.row(align=True)
    add_row.operator("planetka.add_vdb_cloud", text="Add Cloud", icon="ADD")

    progress = cloud_runtime.get_cloud_download_progress()
    progress_error = str(progress.get("error", "") or "").strip()
    progress_label = str(progress.get("label", "") or "")
    if bool(progress.get("active", False)) and "VDB" in progress_label.upper():
        downloaded = max(0, int(progress.get("downloaded_bytes", 0) or 0))
        total = max(0, int(progress.get("total_bytes", 0) or 0))
        if total > 0:
            text = f"Downloading: {_fmt_bytes(downloaded)} / {_fmt_bytes(total)}"
            factor = min(1.0, max(0.0, downloaded / float(total)))
        else:
            text = f"Downloading: {_fmt_bytes(downloaded)}"
            factor = 0.0
        try:
            picker_box.progress(factor=factor, type='BAR', text=text)
        except (AttributeError, TypeError, RuntimeError):
            picker_box.label(text=text, icon="IMPORT")
    elif progress_error and "VDB" in progress_label.upper():
        err_box = picker_box.box()
        err_box.alert = True
        err_box.label(text=progress_error, icon="ERROR")

    clouds = cloud_runtime._sort_cloud_objects_by_suffix(list(cloud_runtime._iter_vdb_cloud_objects()))
    if not clouds:
        box.label(text="No VDB clouds added yet.", icon="INFO")
        return

    scene = getattr(context, "scene", None) if context else None
    for idx, cloud_obj in enumerate(clouds, start=1):
        cloud_box = _draw_collapsible_subsection(
            box,
            scene,
            cloud_runtime._cloud_title(cloud_obj.name, idx, "VDB Cloud No"),
            "VOLUME_DATA",
            _cloud_subsection_key("vdb", cloud_obj),
            default_open=True,
        )
        if cloud_box is None:
            continue
        cloud_box.prop(
            cloud_obj,
            "hide_viewport",
            text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
            toggle=True,
            icon="HIDE_OFF",
        )
        cloud_box.label(text=f"File: {cloud_runtime._vdb_file_label(cloud_obj)}", icon="FILE")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_SIZE_COEF, text="Size")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_LATITUDE, text="Latitude")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_LONGITUDE, text="Longitude")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_ROTATION_DEG, text="Rotation")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
        cloud_box.prop(cloud_obj, cloud_runtime.VDB_CLOUD_PROP_DENSITY, text="Density")

        row = cloud_box.row(align=True)
        op = row.operator("planetka.reset_vdb_cloud_to_camera_view", text="Reset to Camera", icon="TRACKING")
        op.object_name = cloud_obj.name
        op = row.operator("planetka.delete_vdb_cloud", text="Delete", icon="TRASH")
        op.object_name = cloud_obj.name


def _draw_clouds(layout, context):
    layout.use_property_split = False
    layout.use_property_decorate = False

    scene = getattr(context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    _draw_global_clouds(layout, scene, props)
    _draw_local_clouds(layout, context, props)
    _draw_vdb_clouds(layout, context, props)


def _draw_atmosphere(layout, context):
    layout.use_property_split = False
    layout.use_property_decorate = False

    scene = getattr(context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    layout.prop(props, "atmosphere_enabled", text="Enable Atmosphere")
    layout.label(text="Type")
    mode_row = layout.row(align=True)
    mode_row.prop_enum(props, "atmosphere_mode", "VOLUMETRIC", text="Cycles Optimized")
    mode_row.prop_enum(props, "atmosphere_mode", "EEVEE", text="EEVEE Optimized")

    mode = str(getattr(props, "atmosphere_mode", "VOLUMETRIC") or "VOLUMETRIC").strip().upper()
    _draw_atmosphere_notice(layout, mode)

    nodes = _iter_atmosphere_nodes(mode)
    if not nodes:
        layout.label(text="Atmosphere shader not found. Enable Atmosphere or Create Earth to append it.", icon="INFO")
        return

    many_nodes = len(nodes) > 1
    for index, node in enumerate(nodes, start=1):
        container = layout.box() if many_nodes else layout
        if many_nodes:
            container.label(text=f"Atmosphere Shader Node {index}", icon="NODETREE")
        if not _iter_atmosphere_input_sockets(node):
            container.label(text="No adjustable inputs found.", icon="INFO")
            continue
        if mode == "VOLUMETRIC":
            _draw_volumetric_atmosphere_node(container, node)
        else:
            _draw_eevee_supplement_atmosphere_node(container, node)


class PLANETKA_PT_AccountPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Account"
    bl_idname = "PLANETKA_PT_account"
    bl_order = 9000
    bl_options = set()

    @classmethod
    def poll(cls, context):
        _ = context
        return False

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
        _ = context
        return False

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
    bl_label = "General Settings"
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
            _draw_general_account_summary(layout)

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

            diagnostics_box = layout.box()
            diagnostics_box.label(text="Diagnostics", icon="CHECKMARK")
            diagnostics_box.operator(
                "planetka.scene_health_check",
                text="Scene Health Check",
                icon="CHECKMARK",
            )

            auto_box = layout.box()
            auto_box.label(text="Auto-Resolve Options", icon="DRIVER")
            auto_row = auto_box.row(align=True)
            auto_row.use_property_split = False
            auto_row.prop_enum(props, "auto_resolve_mode", "NEVER", text="Never")
            auto_row.prop_enum(props, "auto_resolve_mode", "CAMERA_VIEW", text="Camera only")
            always_row = auto_row.row(align=True)
            always_allowed = is_pro_account(get_prefs())
            always_row.enabled = bool(always_allowed)
            always_row.prop_enum(
                props,
                "auto_resolve_mode",
                "ALWAYS",
                text=("Always" if always_allowed else "Always (Pro only)"),
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

            standalone_box = layout.box()
            standalone_allowed = is_pro_account(get_prefs())
            standalone_box.label(text=("Standalone Export" if standalone_allowed else "Standalone Export (Pro only)"), icon="PACKAGE")
            standalone_box.enabled = _has_earth() and standalone_allowed
            standalone_box.operator(
                "planetka.create_standalone_file",
                text=("Create Standalone File" if standalone_allowed else "Create Standalone File (Pro only)"),
                icon="FILE_BLEND",
            )

class PLANETKA_PT_LiveTelemetryPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Quality Settings"
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
    bl_label = "Quality Settings"
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
    bl_label = "Quality Settings"
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
        return True

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(True)
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/@tomasgriger-planetka/videos"

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
        return False

    def draw(self, context):
        _ = context
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(True)
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/@tomasgriger-planetka/videos"

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

    transform_box = _draw_collapsible_subsection(
        layout,
        scene,
        "Earth Transform",
        "EMPTY_AXIS",
        EARTH_TRANSFORM_SECTION_OPEN_KEY,
        default_open=False,
    )
    if transform_box is not None:
        transform_box.enabled = bool(enabled)
        _draw_earth_transform(transform_box, scene)

    _draw_surface_grading(layout)


class PLANETKA_PT_EarthSettingsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Earth Surface"
    bl_idname = "PLANETKA_PT_earth_settings"
    bl_order = 9004

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_earth_settings(self.layout, scene, enabled=_planetka_controls_enabled(True))


class PLANETKA_PT_EarthSettingsPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Earth Surface"
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
        return _is_earth_workflow_enabled()

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
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_atmosphere(layout, context)


class PLANETKA_PT_CloudsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Clouds"
    bl_idname = "PLANETKA_PT_clouds"
    bl_order = 9006

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _planetka_controls_enabled(_is_earth_workflow_enabled())
        _draw_clouds(layout, context)


class PLANETKA_PT_CloudsPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Clouds"
    bl_idname = "PLANETKA_PT_clouds_collapsed"
    bl_order = 9006

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_clouds(layout, context)


class PLANETKA_PT_SunlightPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Sunlight"
    bl_idname = "PLANETKA_PT_sunlight"
    bl_order = 9007
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
        clear_keys_row.enabled = bool(controls_enabled) and _planetka_camera_has_keyframes(scene)
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

        animation_render_running = _is_animation_render_running()
        final_render_box = layout.box()
        final_render_box.enabled = bool(earth_workflow_enabled) if animation_render_running else bool(controls_enabled)
        final_render_box.label(
            text=("Final Animation Render" if allows_animation_render_for_context(prefs=get_prefs()) else "Final Animation Render (Pro only)"),
            icon="RENDER_ANIMATION",
        )
        selected_final_quality = _normalize_texture_quality_for_ui(getattr(props, "texture_quality_mode", "PREVIEW"))
        final_render_allowed = allows_animation_render_for_context(
            prefs=get_prefs(),
            source=props,
            requested_mode=selected_final_quality,
        )
        if animation_render_running:
            runtime, runtime_code, runtime_text = _resolve_runtime_display(scene)
            _draw_resolve_download_indicator(final_render_box, scene, runtime, runtime_code, runtime_text)

        render_button_row = final_render_box.row(align=True)
        render_button_row.scale_y = 1.2
        if animation_render_running:
            render_button_row.enabled = True
            render_button_row.alert = True
            render_button_row.operator(
                "planetka.animation_stop",
                text="Stop",
                icon="CANCEL",
            )
        else:
            render_button_row.enabled = bool(final_render_allowed) and bool(earth_workflow_enabled)
            render_button_row.operator(
                "planetka.animation_render",
                text=("Render Animation" if final_render_allowed else "Render Animation (Pro only)"),
                icon="RENDER_ANIMATION",
            )
