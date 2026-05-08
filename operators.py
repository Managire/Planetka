import textwrap
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .auth import (
    allows_balanced_full_quality_for_context,
    is_authenticated,
)
from .planetka_ops.account_ops import (
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
)
from .planetka_ops.location_ops import (
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_SaveLocation,
)
from .planetka_ops.startup_profile_ops import (
    _SURFACE_GRADING_SECTION_SOCKET_NAMES,
    _apply_startup_setup_for_create_earth,
    _apply_startup_setup_profile,
    _apply_surface_grading_values,
    _build_factory_startup_setup_profile,
    _iter_surface_grading_input_sockets,
    _iter_surface_grading_nodes,
    _normalize_startup_texture_quality_mode,
    _serialize_current_startup_setup_profile,
    _serialize_surface_grading_values,
    _store_startup_setup_profile,
    _surface_grading_factory_values,
)
from .planetka_ops.earth_lifecycle_helpers import (
    _DEFAULT_SCENE_REMOVED_KEY,
    _PLANETKA_CREATE_CAMERA_NAME,
    _REBUILD_EXCEPTIONS,
    _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY,
    _apply_create_earth_clipping_defaults,
    _apply_radius_based_clipping,
    _earth_graph_cleanup_for_rebuild,
    _earth_graph_create_bootstrap_surface,
    _earth_graph_rebind,
    _earth_graph_restore_after_rebuild,
    _ensure_close_clip_limits,
    _ensure_planetka_create_camera,
    _is_planetka_create_camera,
    _pick_scene_camera,
    _position_planetka_create_camera,
    _require_authenticated_account,
    _restore_view_selection,
    _snapshot_camera_state_for_rebuild,
    _snapshot_earth_settings_for_rebuild,
    _snapshot_view_selection,
    _validate_create_earth_texture_source,
)
from .planetka_ops.import_export_ops import (
    PLANETKA_OT_ConfirmImportNewData,
    PLANETKA_OT_CreateStandaloneFile,
    PLANETKA_OT_ImportNewData,
    PLANETKA_OT_SelectTextureSource,
)
from .planetka_ops import earth_lifecycle_ops as _earth_lifecycle_ops
from .planetka_ops import navigation_ops as _navigation_ops
from .planetka_ops.navigation_ops import (
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
)
from .planetka_ops.scene_setup_ops import (
    PLANETKA_OT_RemoveDefaultScene,
    PLANETKA_OT_SetBackgroundBlack,
)
from .asset_builder import (
    PLANETKA_ROOT_OBJECT_NAME,
    ensure_planetka_assets,
    ensure_planetka_root,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import (
    get_earth_object,
    get_prefs,
    read_saved_locations,
    write_saved_locations,
)
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .sanity_utils import (
    _normalize_texture_source_path,
    invalidate_texture_source_health_cache,
)
from .r2_source import (
    get_download_progress,
    is_download_active,
    is_remote_source_configured,
    texture_file_exists,
)

STANDARD_RESOLUTION_INFO_URL = "https://www.planetka.io/blender/standard-resolution-info"

_UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED = False


def _tag_view3d_for_unlocked_download():
    try:
        context = getattr(bpy, "context", None)
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return None
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if getattr(area, "type", "") == "VIEW_3D":
                    area.tag_redraw()
        from .credit_api import is_unlocked_download_active
        if is_unlocked_download_active():
            return 0.5
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed redrawing unlocked-download UI", exc_info=True)
    global _UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED
    _UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED = False
    return None


def _ensure_unlocked_download_redraw_timer():
    global _UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED
    if _UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED:
        return
    try:
        bpy.app.timers.register(_tag_view3d_for_unlocked_download, first_interval=0.2)
        _UNLOCKED_DOWNLOAD_REDRAW_TIMER_REGISTERED = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed starting unlocked-download redraw timer", exc_info=True)


def _format_bytes_for_ui(size_bytes):
    try:
        value = float(size_bytes or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 1024.0 ** 3:
        return f"{value / (1024.0 ** 3):.2f} GB"
    return f"{value / (1024.0 ** 2):.2f} MB"


def _format_eur_for_ui(value):
    try:
        return f"€{max(0.0, float(value or 0.0)):.2f}"
    except (TypeError, ValueError):
        return "€0.00"


def _wrapped_label(layout, text, icon='NONE', width=58):
    safe_text = str(text or "").strip()
    if not safe_text:
        return
    lines = textwrap.wrap(safe_text, width=max(20, int(width or 58))) or [safe_text]
    for index, line in enumerate(lines):
        layout.label(text=line, icon=icon if index == 0 else 'BLANK1')


class PLANETKA_OT_AccountDownloadUnlockedTiles(bpy.types.Operator):
    bl_idname = "planetka.account_download_unlocked_tiles"
    bl_label = "Download Licenced Tiles"
    bl_description = "Download all licenced tiles to a local source folder"

    period: EnumProperty(
        name="Data Range",
        description="Choose which licenced tiles should be downloaded",
        items=(
            ("TODAY", "Today", "Download tiles licenced today"),
            ("THIS_WEEK", "This Week", "Download tiles licenced this week"),
            ("THIS_MONTH", "This Month", "Download tiles licenced this month"),
            ("ALL", "All Data", "Download every licenced tile"),
        ),
        default="ALL",
        options={'SKIP_SAVE'},
    )

    directory: StringProperty(
        name="Directory",
        subtype='DIR_PATH',
        default="",
        options={'SKIP_SAVE'},
    )

    confirmed: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    plan_id: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_total_bytes: StringProperty(default="0", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_total_files: StringProperty(default="0", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_selected_tiles: StringProperty(default="0", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_existing_files: StringProperty(default="0", options={'HIDDEN', 'SKIP_SAVE'})

    def draw(self, _context):
        layout = self.layout
        if not bool(getattr(self, "confirmed", False)):
            layout.prop(self, "period", text="Download")
            layout.prop(self, "directory", text="To")
            layout.label(text="A confirmation with total size appears before download starts.", icon="INFO")
            return
        try:
            total_bytes = int(str(getattr(self, "confirm_total_bytes", "0") or "0"))
        except (TypeError, ValueError):
            total_bytes = 0
        layout.label(text=f"Download {_format_bytes_for_ui(total_bytes)}?", icon="IMPORT")
        layout.label(text=f"Files: {getattr(self, 'confirm_total_files', '0')}")
        layout.label(text=f"Licenced tiles: {getattr(self, 'confirm_selected_tiles', '0')}")
        existing = str(getattr(self, "confirm_existing_files", "0") or "0")
        if existing != "0":
            layout.label(text=f"Already present: {existing} files", icon="CHECKMARK")
        layout.label(text=f"Data range: {self.period.replace('_', ' ').title()}")
        layout.label(text=f"Folder: {self.directory}")

    def invoke(self, context, _event):
        if bool(getattr(self, "confirmed", False)):
            wm = getattr(context, "window_manager", None)
            if wm is None:
                return self.execute(context)
            return wm.invoke_props_dialog(self, width=520)
        if not str(getattr(self, "directory", "") or "").strip():
            try:
                prefs = get_prefs()
                self.directory = str(getattr(prefs, "local_texture_source_path", "") or "")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                self.directory = ""
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return self.execute(context)
        return wm.invoke_props_dialog(self, width=520)

    def execute(self, context):
        try:
            from .credit_api import (
                is_unlocked_download_active,
                prepare_unlocked_download_plan,
                start_unlocked_download_plan,
            )
            if is_unlocked_download_active():
                self.report({'WARNING'}, "Licenced tile download is already running.")
                return {'CANCELLED'}
            if not bool(getattr(self, "confirmed", False)):
                plan = prepare_unlocked_download_plan(self.directory, period=self.period)
                self.plan_id = str(plan.get("plan_id", "") or "")
                self.confirm_total_bytes = str(int(plan.get("total_bytes", 0) or 0))
                self.confirm_total_files = str(int(plan.get("total_files", 0) or 0))
                self.confirm_selected_tiles = str(int(plan.get("selected_tiles", 0) or 0))
                self.confirm_existing_files = str(int(plan.get("skipped_existing_files", 0) or 0))
                self.confirmed = True
                wm = getattr(context, "window_manager", None)
                if wm is None:
                    return {'CANCELLED'}
                return wm.invoke_props_dialog(self, width=520)
            progress = start_unlocked_download_plan(str(getattr(self, "plan_id", "") or ""))
            _ensure_unlocked_download_redraw_timer()
        except Exception as exc:
            return fail(
                self,
                f"Unable to download licenced tiles: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka licenced tile download failed",
            )
        self.report(
            {'INFO'},
            (
                "Licenced tile download started "
                f"({_format_bytes_for_ui(progress.get('total_bytes', 0))}, "
                f"{int(progress.get('total_files', 0) or 0)} files)."
            ),
        )
        return {'FINISHED'}


class PLANETKA_OT_AccountCancelUnlockedDownload(bpy.types.Operator):
    bl_idname = "planetka.account_cancel_unlocked_download"
    bl_label = "Cancel Download"
    bl_description = "Cancel the active licenced tile download"

    def execute(self, _context):
        try:
            from .credit_api import cancel_unlocked_download
            active = cancel_unlocked_download()
        except Exception as exc:
            return fail(
                self,
                f"Unable to cancel licenced tile download: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka licenced tile download cancel failed",
            )
        if active:
            self.report({'INFO'}, "Cancelling licenced tile download...")
        return {'FINISHED'}
from .state import (
    ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY,
    _auto_resolve_scope_mode,
    _is_render_job_active,
    _tag_view3d_redraw,
    _initialize_props_from_imported_planetka,
    _sync_idprops_from_props,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
    resume_navigation_shot_updates,
    stop_auto_resolve_download_pipeline,
    suspend_navigation_shot_updates,
    update_resolve_size_estimates,
    warm_base_sphere_mesh_cache,
)
from .updater import kickoff_background_update_check

_RECOVERABLE_LOG_COUNTS = {}
_DOWNLOAD_POPUP_WM_FLAG = "planetka_download_popup_running"
_POST_CHECKOUT_MONITOR = {}
_POST_CHECKOUT_MONITOR_REGISTERED = False
_POST_CHECKOUT_POLL_INTERVAL_SEC = 3.0
_POST_CHECKOUT_TIMEOUT_SEC = 300.0


def _is_active_view_resolve_scope(scene):
    try:
        scope = str(_auto_resolve_scope_mode(scene) or "CAMERA").strip().upper()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        scope = "CAMERA"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        scope = "CAMERA"
    return scope == "ACTIVE_VIEW"


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _scene_full_quality_price_eur(scene):
    if scene is None:
        return None
    try:
        from .credit_api import clear_credit_caches
        clear_credit_caches()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed clearing credit caches during checkout refresh", exc_info=True)
    try:
        prefs = get_prefs()
        base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or "")) if prefs else ""
        from .planetka_runtime.view_telemetry import build_resolve_cost_breakdown
        breakdown = build_resolve_cost_breakdown(
            scene=scene,
            scope_mode="CAMERA",
            base_path=base_path,
            texture_quality_mode="FULL",
        )
        update_resolve_size_estimates(scene, scope_mode="CAMERA", base_path=base_path, include_full_price=False)
        _tag_view3d_redraw()
        if not isinstance(breakdown, dict):
            return None
        if not bool(breakdown.get("ok", True)):
            return None
        return float(max(0.0, float(breakdown.get("total_credits", 0.0) or 0.0)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed refreshing checkout price state", exc_info=True)
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed refreshing checkout price state", exc_info=True)
    return None


def _run_camera_full_quality_resolve_after_checkout(scene):
    if scene is None:
        return False
    try:
        context_scene = getattr(getattr(bpy, "context", None), "scene", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        context_scene = None
    if context_scene is not scene:
        _tag_view3d_redraw()
        return False
    try:
        stop_auto_resolve_download_pipeline()
        result = bpy.ops.planetka.load_textures(
            scope_mode="CAMERA",
            skip_render_compatibility=True,
            defer_download=False,
            texture_quality_mode_override="FULL",
        )
        if "FINISHED" in result:
            try:
                from .credit_api import clear_credit_caches
                clear_credit_caches()
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed clearing credit caches after checkout resolve", exc_info=True)
            prefs = get_prefs()
            base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or "")) if prefs else ""
            update_resolve_size_estimates(
                scene,
                scope_mode="CAMERA",
                base_path=base_path,
                force_full_price_refresh=True,
            )
            _tag_view3d_redraw()
            logger.info("Planetka: Full Quality resolve started after scene payment.")
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed running Full Quality resolve after checkout", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed running Full Quality resolve after checkout", exc_info=True)
    return False


def _region_offer_location_for_context(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    lat_value = None
    lon_value = None
    try:
        if props is not None:
            lat_value = getattr(props, "nav_latitude_deg", 0.0)
            lon_value = getattr(props, "nav_longitude_deg", 0.0)
        if lat_value is None or lon_value is None:
            from .diagnostics import read_diagnostics
            diag = read_diagnostics(scene)
            if lat_value is None and isinstance(diag, dict):
                lat_value = diag.get("view_latitude_deg", None)
            if lon_value is None and isinstance(diag, dict):
                lon_value = diag.get("view_longitude_deg", None)
        lat = max(-90.0, min(90.0, float(lat_value or 0.0)))
        lon = max(-180.0, min(180.0, float(lon_value or 0.0)))
        return lat, lon
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _region_offer_number(offer, key, fallback=0.0):
    try:
        return float((offer or {}).get(key, fallback) or fallback)
    except (TypeError, ValueError, AttributeError):
        return float(fallback)


def _region_offer_int(offer, key, fallback=0):
    try:
        return int((offer or {}).get(key, fallback) or fallback)
    except (TypeError, ValueError, AttributeError):
        return int(fallback)


def _region_offer_countries_text(offer):
    countries = (offer or {}).get("included_countries", ())
    if isinstance(countries, (list, tuple)):
        return "|".join(str(country).strip() for country in countries if str(country).strip())
    return str(countries or "")


def _populate_region_pack_info_operator(operator, offer):
    name = str((offer or {}).get("name", "") or (offer or {}).get("region_pack_name", "") or "Region Pack").strip()
    region_id = str((offer or {}).get("id", "") or (offer or {}).get("region_pack_id", "") or "").strip()
    operator.region_pack_id = region_id
    operator.region_pack_name = name
    operator.included_countries = _region_offer_countries_text(offer)
    operator.new_tile_count = max(0, _region_offer_int(offer, "new_tile_count", _region_offer_int(offer, "paid_tile_count", 0)))
    operator.total_tile_count = max(0, _region_offer_int(offer, "tile_count", 0))
    operator.already_licenced_tile_count = max(0, _region_offer_int(offer, "already_licenced_tile_count", 0))
    operator.already_licenced_saving_eur = max(0.0, _region_offer_number(offer, "already_licenced_saving_eur", 0.0))
    operator.full_price_eur = max(0.0, _region_offer_number(offer, "gross_eur", _region_offer_number(offer, "gross_price_eur", 0.0)))
    operator.discount_percent = max(0, _region_offer_int(offer, "discount_percent", 0))
    operator.discount_eur = max(0.0, _region_offer_number(offer, "discount_eur", 0.0))
    operator.price_eur = max(0.0, _region_offer_number(offer, "price_eur", _region_offer_number(offer, "credits", 0.0)))


def _draw_region_pack_upsell_options(layout, context, *, current_region_pack_id="", title="Broader Full Quality options"):
    location = _region_offer_location_for_context(context)
    if location is None:
        return
    try:
        from .credit_api import get_region_pack_offers
        offers = get_region_pack_offers(location[0], location[1])
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed fetching broader region pack options for popup", exc_info=True)
        return
    offers = [offer for offer in offers if isinstance(offer, dict) and bool(offer.get("ok", True))]
    current_id = str(current_region_pack_id or "").strip()
    if current_id:
        current_index = next(
            (index for index, offer in enumerate(offers) if str(offer.get("id", "") or offer.get("region_pack_id", "") or "").strip() == current_id),
            -1,
        )
        if current_index >= 0:
            offers = offers[current_index + 1:]
        else:
            offers = [offer for offer in offers if str(offer.get("id", "") or offer.get("region_pack_id", "") or "").strip() != current_id]
    if not offers:
        return
    box = layout.box()
    box.label(text=title, icon="WORLD_DATA")
    for offer in offers[:4]:
        name = str(offer.get("name", "") or offer.get("region_pack_name", "") or "Region Pack").strip()
        region_id = str(offer.get("id", "") or offer.get("region_pack_id", "") or "").strip()
        if not name or not region_id:
            continue
        price = max(0.0, _region_offer_number(offer, "price_eur", _region_offer_number(offer, "credits", 0.0)))
        new_tiles = max(0, _region_offer_int(offer, "new_tile_count", _region_offer_int(offer, "paid_tile_count", 0)))
        row = box.row(align=True)
        row.alignment = 'EXPAND'
        button = row.row(align=True)
        button.alignment = 'LEFT'
        button.enabled = not bool(price <= 0.0 and new_tiles <= 0)
        checkout = button.operator(
            "planetka.open_credit_checkout",
            text=("Already Licenced" if price <= 0.0 and new_tiles <= 0 else (f"{name} (Free)" if price <= 0.0 else f"{name} ({_format_eur_for_ui(price)})")),
            icon=("CHECKMARK" if price <= 0.0 else "URL"),
        )
        checkout.checkout_option = "REGION_PACK"
        checkout.region_pack_id = region_id
        checkout.region_pack_name = name
        checkout.included_countries = _region_offer_countries_text(offer)
        info = row.operator("planetka.region_pack_info", text="", icon="INFO")
        _populate_region_pack_info_operator(info, offer)


def _checkout_monitor_scene(scene_name):
    safe_name = str(scene_name or "").strip()
    if safe_name:
        scene = bpy.data.scenes.get(safe_name)
        if scene is not None:
            return scene
    try:
        return getattr(getattr(bpy, "context", None), "scene", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _post_checkout_monitor_timer():
    global _POST_CHECKOUT_MONITOR
    global _POST_CHECKOUT_MONITOR_REGISTERED
    monitor = dict(_POST_CHECKOUT_MONITOR or {})
    if not monitor:
        _POST_CHECKOUT_MONITOR_REGISTERED = False
        return None
    try:
        deadline = float(monitor.get("deadline", 0.0) or 0.0)
    except (TypeError, ValueError):
        deadline = 0.0
    if deadline > 0.0 and time.monotonic() > deadline:
        logger.info("Planetka: scene payment monitor timed out before Full Quality licence appeared.")
        _POST_CHECKOUT_MONITOR = {}
        _POST_CHECKOUT_MONITOR_REGISTERED = False
        return None

    scene = _checkout_monitor_scene(monitor.get("scene_name", ""))
    price_eur = _scene_full_quality_price_eur(scene)
    if price_eur is not None and price_eur <= 0.000001:
        _POST_CHECKOUT_MONITOR = {}
        _POST_CHECKOUT_MONITOR_REGISTERED = False
        _run_camera_full_quality_resolve_after_checkout(scene)
        return None
    return _POST_CHECKOUT_POLL_INTERVAL_SEC


def _start_post_checkout_scene_monitor(scene):
    global _POST_CHECKOUT_MONITOR
    global _POST_CHECKOUT_MONITOR_REGISTERED
    if scene is None:
        return
    _POST_CHECKOUT_MONITOR = {
        "scene_name": str(getattr(scene, "name", "") or ""),
        "deadline": float(time.monotonic() + _POST_CHECKOUT_TIMEOUT_SEC),
    }
    if _POST_CHECKOUT_MONITOR_REGISTERED:
        return
    try:
        bpy.app.timers.register(_post_checkout_monitor_timer, first_interval=_POST_CHECKOUT_POLL_INTERVAL_SEC)
        _POST_CHECKOUT_MONITOR_REGISTERED = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed starting scene payment monitor", exc_info=True)


def _persist_user_preferences():
    if bool(getattr(bpy.app, "background", False)):
        return False
    # Planetka must not write Blender's global user preferences automatically.
    return False


def _cancel_if_animation_render_active(operator, action_label="This action"):
    try:
        if callable(_is_render_job_active) and bool(_is_render_job_active()):
            label = str(action_label or "This action").strip() or "This action"
            operator.report(
                {'WARNING'},
                f"{label} is unavailable while Final Animation Render is running.",
            )
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


from .planetka_ops.navigation_helpers import (
    _anchor_distance_from_altitude_and_tilt,
    _anchor_frame_world,
    _apply_navigation_shot,
    _best_available_d_for_tile,
    _bu_to_km,
    _camera_projection_info,
    _camera_to_current_view,
    _compute_current_view_navigation_values,
    _compute_scene_camera_navigation_values,
    _derive_navigation_shot_from_camera,
    _earth_radius_blender_units,
    _ensure_ortho_full_globe_if_needed,
    _ensure_shot_anchor_object,
    _find_active_view3d_context,
    _find_active_view3d_context_details,
    _finest_available_d_for_location,
    _full_globe_altitude_km,
    _get_coverage_map,
    _hide_shot_anchor_in_viewport,
    _is_scene_camera_below_surface,
    _km_to_bu,
    _lon_lat_normal_local,
    _look_rotation_quaternion,
    _max_proximity_altitude_km,
    _meters_per_blender_unit,
    _navigate_camera_internal,
    _populate_navigation_from_scene_camera,
    _quantize_navigation_ui_payload,
    _quantize_navigation_ui_value,
    _ray_sphere_hit_nearest,
    _read_full_globe_tilt_lock,
    _read_last_navigation_values,
    _scene_camera_altitude_bu,
    _set_planetka_earth_radius_bu,
    _signed_angle_around_axis,
    _store_last_navigation_values,
    _switch_viewport_to_camera_view,
    _sync_active_view_to_scene_camera,
    _tile_xy_for_lon_lat,
    _update_shot_anchor_object,
)


class PLANETKA_OT_SetTextureQualityAndResolve(bpy.types.Operator):
    bl_idname = "planetka.set_texture_quality_and_resolve"
    bl_label = "Texture Quality"
    bl_description = "Select Preview or Standard for personal-use automated resolving, or licence Full Quality textures for commercial use"

    texture_quality_mode: EnumProperty(
        name="Texture Quality",
        items=(
            (
                "PREVIEW",
                "Preview",
                "Personal use only. Streamed/cached Preview textures for Planetka use",
            ),
            (
                "BALANCED",
                "Standard",
                "Personal use only. Streamed/cached Standard Quality textures for Planetka use",
            ),
            (
                "FULL",
                "Full Quality",
                "Commercial licence included for licenced Full Quality texture data",
            ),
        ),
        default="PREVIEW",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    confirm_purchase: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_new_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_already_licenced_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_free_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_total_bytes: StringProperty(default="0", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_price_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_balance_after_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    confirm_charged_tile_keys: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        mode = _normalize_startup_texture_quality_mode(
            getattr(properties, "texture_quality_mode", "PREVIEW")
        )
        if mode == "PREVIEW":
            return "Use Preview textures for automated resolving. Personal use only."
        if mode == "BALANCED":
            return "Use Standard Quality textures for automated resolving. Personal use only."
        return "Licence and download Full Quality textures for Camera View. Commercial licence included."

    def invoke(self, context, event):
        del event
        target_mode = _normalize_startup_texture_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        if target_mode == "FULL" and not bool(getattr(self, "confirm_purchase", False)):
            try:
                summary = self._positive_balance_purchase_summary(context)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed preparing Full Quality balance-purchase confirmation", exc_info=True)
                summary = {}
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed preparing Full Quality balance-purchase confirmation", exc_info=True)
                summary = {}
            price = float((summary or {}).get("price_eur", 0.0) or 0.0)
            balance = float((summary or {}).get("balance_eur", 0.0) or 0.0)
            if price > 0.000001 and balance > 0.0:
                self.confirm_purchase = True
                self.confirm_new_tile_count = int((summary or {}).get("new_tile_count", 0) or 0)
                self.confirm_already_licenced_tile_count = int((summary or {}).get("already_licenced_tile_count", 0) or 0)
                self.confirm_free_tile_count = int((summary or {}).get("free_tile_count", 0) or 0)
                self.confirm_total_bytes = str(int((summary or {}).get("total_bytes", 0) or 0))
                self.confirm_price_eur = float(price)
                self.confirm_balance_after_eur = float(balance - price)
                self.confirm_charged_tile_keys = "|".join(str(key) for key in (summary or {}).get("charged_tile_keys", ()) if str(key).strip())
                wm = getattr(context, "window_manager", None)
                if wm is not None:
                    return wm.invoke_props_dialog(self, width=520)
        return self.execute(context)

    def _positive_balance_purchase_summary(self, context):
        scene = getattr(context, "scene", None)
        prefs = get_prefs()
        base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or "")) if prefs else ""
        from .credit_api import get_credit_account
        from .planetka_runtime.view_telemetry import build_resolve_cost_breakdown, get_resolve_size_estimates
        account = get_credit_account(force=False)
        balance = float(account.get("balance_credits", 0.0) or 0.0) if account else 0.0
        breakdown = build_resolve_cost_breakdown(
            scene=scene,
            scope_mode="CAMERA",
            base_path=base_path,
            texture_quality_mode="FULL",
        )
        if not isinstance(breakdown, dict) or not bool(breakdown.get("ok", True)):
            return {}
        try:
            update_resolve_size_estimates(scene, scope_mode="CAMERA", base_path=base_path, include_full_price=False)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed refreshing Full Quality estimates for balance-purchase confirmation", exc_info=True)
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed refreshing Full Quality estimates for balance-purchase confirmation", exc_info=True)
        estimates = get_resolve_size_estimates(scene)
        total_bytes = breakdown.get("total_bytes", 0)
        if isinstance(estimates, dict) and estimates.get("FULL") is not None:
            total_bytes = estimates.get("FULL")
        charged_tiles = list(breakdown.get("charged_tiles", ()) or ())
        excluded_tiles = list(breakdown.get("excluded_tiles", ()) or ())
        free_tiles = list(breakdown.get("free_tiles", ()) or ())
        charged_tile_keys = []
        for entry in charged_tiles:
            key = str(entry.get("tile_key", "") if isinstance(entry, dict) else entry or "").strip()
            if key:
                charged_tile_keys.append(key)
        return {
            "balance_eur": balance,
            "price_eur": float(max(0.0, float(breakdown.get("total_credits", 0.0) or 0.0))),
            "total_bytes": int(max(0, int(total_bytes or 0))),
            "new_tile_count": len(charged_tiles),
            "already_licenced_tile_count": len(excluded_tiles),
            "free_tile_count": len(free_tiles),
            "charged_tile_keys": charged_tile_keys,
        }

    def draw(self, context):
        layout = self.layout
        if not bool(getattr(self, "confirm_purchase", False)):
            return
        layout.label(text="Confirm Full Quality Purchase", icon="TEXTURE")
        _wrapped_label(
            layout,
            "This will licence and download Full Quality textures for the current Camera View.",
            icon="INFO",
            width=64,
        )
        box = layout.box()
        box.label(text=f"New tiles: {int(getattr(self, 'confirm_new_tile_count', 0) or 0)}", icon="TEXTURE")
        box.label(
            text=f"Already licenced: {int(getattr(self, 'confirm_already_licenced_tile_count', 0) or 0)}",
            icon="CHECKMARK",
        )
        free_count = int(getattr(self, "confirm_free_tile_count", 0) or 0)
        if free_count > 0:
            box.label(text=f"Free / not charged: {free_count}", icon="HIDE_OFF")
        try:
            total_bytes = int(str(getattr(self, "confirm_total_bytes", "0") or "0"))
        except (TypeError, ValueError):
            total_bytes = 0
        box.label(text=f"Data size: {_format_bytes_for_ui(total_bytes)}", icon="DISK_DRIVE")
        box.label(text=f"Price: {_format_eur_for_ui(getattr(self, 'confirm_price_eur', 0.0))}", icon="USER")
        balance_after = float(getattr(self, "confirm_balance_after_eur", 0.0) or 0.0)
        box.label(text=f"Balance after purchase: €{balance_after:.2f}", icon="USER")
        keys = [part.strip() for part in str(getattr(self, "confirm_charged_tile_keys", "") or "").split("|") if part.strip()]
        if keys:
            tile_box = layout.box()
            tile_box.label(text="Newly licenced tiles", icon="TEXTURE")
            for key in keys[:12]:
                tile_box.label(text=key)
        _wrapped_label(
            layout,
            "These textures remain licenced to your account and can be downloaded again later.",
            icon="CHECKMARK",
            width=64,
        )
        _draw_region_pack_upsell_options(
            layout,
            context,
            title="Broader Full Quality options",
        )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Texture quality change"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        target_mode = _normalize_startup_texture_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        if target_mode == "FULL":
            if _is_active_view_resolve_scope(scene):
                return fail(
                    self,
                    "Bring Camera to View before downloading Full Quality textures.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            try:
                from .animation_tools import _quick_preview_is_prepared
                quick_preview_prepared = bool(_quick_preview_is_prepared(scene))
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                quick_preview_prepared = False
            if quick_preview_prepared:
                return fail(
                    self,
                    "Clear Quick Preview before downloading Full Quality textures.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
        if not allows_balanced_full_quality_for_context(
            prefs=prefs,
            source=props,
            requested_mode=target_mode,
        ):
            if target_mode == "BALANCED":
                return fail(
                    self,
                    "Standard Quality is not unlocked for this Planetka account.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            if target_mode == "FULL":
                return fail(
                    self,
                    "Full Quality requires non-negative Planetka balance.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            return fail(
                self,
                "Selected texture quality is not available.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        if target_mode in {"PREVIEW", "BALANCED"}:
            try:
                previous_mode = _normalize_startup_texture_quality_mode(
                    getattr(props, "texture_quality_mode", "PREVIEW")
                )
                if previous_mode != target_mode:
                    props.texture_quality_mode = target_mode
                else:
                    from .planetka_runtime.auto_resolve_pipeline import update_auto_resolve
                    update_auto_resolve(props, context)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Texture quality selection failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka texture quality selection failed",
                )
            try:
                base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or ""))
                update_resolve_size_estimates(
                    scene,
                    scope_mode="AUTO",
                    base_path=base_path,
                    async_full_price=True,
                )
                _tag_view3d_redraw()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed refreshing selected texture quality estimates", exc_info=True)
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed refreshing selected texture quality estimates", exc_info=True)
            return {'FINISHED'}

        if target_mode == "FULL":
            try:
                from .credit_api import get_credit_account
                from .planetka_runtime.view_telemetry import build_resolve_cost_breakdown
                account = get_credit_account(force=False)
                balance = float(account.get("balance_credits", 0.0) or 0.0) if account else 0.0
                base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or ""))
                breakdown = build_resolve_cost_breakdown(
                    scene=scene,
                    scope_mode="CAMERA",
                    base_path=base_path,
                    texture_quality_mode="FULL",
                )
                if not isinstance(breakdown, dict) or not bool(breakdown.get("ok", True)):
                    return fail(
                        self,
                        "Full Quality pricing is not available. Reconnect Planetka Cloud and retry.",
                        code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                        logger=logger,
                    )
                scene_price = float(
                    (breakdown or {}).get("total_credits", (breakdown or {}).get("credits", 0.0)) or 0.0
                )
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed checking balance before Full Quality resolve", exc_info=True)
                balance = 0.0
                scene_price = 0.0
            if scene_price > 0.000001 and balance <= 0.0:
                checkout_result = bpy.ops.planetka.open_credit_checkout(checkout_option="SCENE")
                return {'FINISHED'} if "FINISHED" in checkout_result else {'CANCELLED'}

        try:
            if target_mode in {"BALANCED", "FULL"}:
                stop_auto_resolve_download_pipeline()
            result = bpy.ops.planetka.load_textures(
                scope_mode="CAMERA" if target_mode == "FULL" else "AUTO",
                skip_render_compatibility=True,
                defer_download=False,
                texture_quality_mode_override=target_mode,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Texture resolve failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka texture quality change failed during resolve",
            )
        if "FINISHED" not in result:
            return {'CANCELLED'}
        try:
            from .credit_api import clear_credit_caches
            clear_credit_caches()
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed clearing credit caches after texture quality resolve", exc_info=True)
        try:
            base_path = _normalize_texture_source_path(str(getattr(prefs, "texture_base_path", "") or ""))
            update_resolve_size_estimates(
                scene,
                scope_mode="CAMERA" if target_mode == "FULL" else "AUTO",
                base_path=base_path,
                async_full_price=(target_mode != "FULL"),
                force_full_price_refresh=(target_mode == "FULL"),
            )
            _tag_view3d_redraw()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed refreshing Full Quality price estimate after resolve", exc_info=True)
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed refreshing Full Quality price estimate after resolve", exc_info=True)
        return {'FINISHED'}


class PLANETKA_OT_OpenCreditCheckout(bpy.types.Operator):
    bl_idname = "planetka.open_credit_checkout"
    bl_label = "Open Planetka Payment"
    bl_description = "Open Stripe Checkout for Standard Quality, Full Quality scene data, or EUR balance"

    checkout_option: EnumProperty(
        name="Payment Option",
        items=(
            ("OPTIONS", "Payment Options", "Choose how to pay for Planetka data"),
            ("STANDARD_UNLOCK", "Unlock Standard Quality", "Unlock Standard Quality forever for this account"),
            ("SCENE", "Buy This Scene", "Pay the exact current Full Quality scene price"),
            ("REGION_PACK", "Buy Region Pack", "Buy a broader Full Quality region pack"),
            ("BALANCE_OPTIONS", "Add Balance", "Choose a Planetka balance top-up amount"),
            ("BALANCE_10", "Add €10 Balance", "Add €10 to your Planetka balance"),
        ),
        default="OPTIONS",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    region_pack_id: StringProperty(
        name="Region Pack",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    region_pack_name: StringProperty(default="Region Pack", options={'HIDDEN', 'SKIP_SAVE'})
    included_countries: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    texture_quality_mode: EnumProperty(
        name="Texture Quality",
        items=(
            ("BALANCED", "Standard", "Standard Quality one-time unlock"),
            ("FULL", "Full Quality", "Full Quality paid land-detail data"),
        ),
        default="FULL",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def _open_url(self, url):
        safe_url = str(url or "").strip()
        if not safe_url:
            return False
        try:
            result = bpy.ops.wm.url_open(url=safe_url)
            if "FINISHED" in result:
                return True
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed opening checkout URL through Blender", exc_info=True)
        try:
            import webbrowser
            return bool(webbrowser.open(safe_url))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed opening checkout URL in system browser", exc_info=True)
        return False

    def _current_scene_tile_keys(self, context):
        try:
            prefs = get_prefs()
            base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
            from .planetka_runtime.view_telemetry import build_resolve_cost_breakdown
            breakdown = build_resolve_cost_breakdown(
                scene=getattr(context, "scene", None),
                scope_mode="CAMERA",
                base_path=base_path,
                texture_quality_mode="FULL",
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            raise RuntimeError(f"Unable to calculate scene price: {exc}") from exc
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(f"Unable to calculate scene price: {exc}") from exc
        keys = []
        for entry in list((breakdown or {}).get("tiles", ()) or ()):
            key = str(entry.get("tile_key", "") if isinstance(entry, dict) else entry or "").strip()
            if key and key not in keys:
                keys.append(key)
        return keys

    def invoke(self, context, event):
        del event
        option = str(getattr(self, "checkout_option", "OPTIONS") or "OPTIONS").strip().upper()
        if option != "OPTIONS":
            return self.execute(context)
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}
        return wm.invoke_popup(self, width=360)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="Planetka payment", icon="URL")
        layout.operator(
            "wm.url_open",
            text="Unlock Standard Quality",
            icon="URL",
        ).url = STANDARD_RESOLUTION_INFO_URL
        layout.operator(
            "planetka.open_credit_checkout",
            text="Buy This Scene",
            icon="URL",
        ).checkout_option = "SCENE"
        layout.operator(
            "planetka.open_credit_checkout",
            text="Add Balance",
            icon="URL",
        ).checkout_option = "BALANCE_OPTIONS"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Planetka payment"):
            return {'CANCELLED'}
        option = str(getattr(self, "checkout_option", "SCENE") or "SCENE").strip().upper()
        if option == "OPTIONS":
            return {'FINISHED'}
        try:
            from .credit_api import create_checkout_session
            tile_keys = self._current_scene_tile_keys(context) if option == "SCENE" else []
            if option == "STANDARD_UNLOCK":
                checkout_option = "standard_unlock"
                quality_mode = "BALANCED"
            elif option == "REGION_PACK":
                checkout_option = "region_pack"
                quality_mode = "FULL"
            elif option in {"BALANCE_OPTIONS", "BALANCE"}:
                checkout_option = "balance_options"
                quality_mode = "FULL"
            else:
                checkout_option = "balance_10" if option == "BALANCE_10" else "scene"
                quality_mode = "FULL"
            checkout = create_checkout_session(
                checkout_option,
                tiles=tile_keys,
                quality_mode=quality_mode,
                region_pack_id=str(getattr(self, "region_pack_id", "") or ""),
            )
        except Exception as exc:
            return fail(
                self,
                f"Unable to open Planetka payment: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka checkout creation failed",
            )
        if bool(checkout.get("no_payment_required", False)):
            if option == "STANDARD_UNLOCK":
                try:
                    from .credit_api import clear_credit_caches
                    clear_credit_caches()
                except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                    logger.debug("Planetka: failed clearing credit cache after Standard unlock check", exc_info=True)
                self.report({'INFO'}, "Standard Quality is already unlocked.")
                return {'FINISHED'}
            if option == "REGION_PACK":
                try:
                    from .credit_api import clear_credit_caches
                    clear_credit_caches()
                except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                    logger.debug("Planetka: failed clearing credit cache after region pack no-payment check", exc_info=True)
                pack_name = str(getattr(self, "region_pack_name", "") or "Region Pack").strip()
                self.report({'INFO'}, f"{pack_name} is already licenced or has no newly charged tiles.")
                return {'FINISHED'}
            scene = getattr(context, "scene", None)
            _scene_full_quality_price_eur(scene)
            _run_camera_full_quality_resolve_after_checkout(scene)
            self.report({'INFO'}, "No payment required for this Full Quality purchase.")
            return {'FINISHED'}
        checkout_url = str(checkout.get("checkout_url", "") or "").strip()
        if not self._open_url(checkout_url):
            return fail(
                self,
                "Could not open Planetka payment page.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        if option in {"SCENE", "REGION_PACK"}:
            _start_post_checkout_scene_monitor(getattr(context, "scene", None))
        self.report({'INFO'}, "Planetka payment page opened in browser.")
        return {'FINISHED'}


def _open_external_url(url):
    safe_url = str(url or "").strip()
    if not safe_url:
        return False
    try:
        result = bpy.ops.wm.url_open(url=safe_url)
        if "FINISHED" in result:
            return True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed opening URL through Blender", exc_info=True)
    try:
        import webbrowser
        return bool(webbrowser.open(safe_url))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed opening URL in system browser", exc_info=True)
    return False


class PLANETKA_OT_OpenRegionPackMap(bpy.types.Operator):
    bl_idname = "planetka.open_region_pack_map"
    bl_label = "Open Region Pack Map"
    bl_description = "Open the detailed user-specific region-pack map in a browser"

    region_pack_id: StringProperty(
        name="Region Pack",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, _context):
        region_id = str(getattr(self, "region_pack_id", "") or "").strip()
        if not region_id:
            return fail(
                self,
                "No region pack selected.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        try:
            from .credit_api import create_region_pack_detail_link
            link = create_region_pack_detail_link(region_id)
        except Exception as exc:
            return fail(
                self,
                f"Unable to open region pack map: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka region pack detail link creation failed",
            )
        url = str(link.get("detail_url", "") or "").strip()
        if not _open_external_url(url):
            return fail(
                self,
                "Could not open Planetka region pack map.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        self.report({'INFO'}, "Planetka region pack map opened in browser.")
        return {'FINISHED'}


class PLANETKA_OT_RegionPackInfo(bpy.types.Operator):
    bl_idname = "planetka.region_pack_info"
    bl_label = "Region Pack Details"
    bl_description = "Show what is included in this broader Full Quality region pack"

    region_pack_id: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    region_pack_name: StringProperty(default="Region Pack", options={'HIDDEN', 'SKIP_SAVE'})
    included_countries: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    new_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    total_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    already_licenced_tile_count: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    already_licenced_saving_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    full_price_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    discount_percent: IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})
    discount_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    price_eur: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        del event
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}
        return wm.invoke_popup(self, width=440)

    def _wrapped_label(self, layout, text, icon='NONE', width=58):
        safe_text = str(text or "").strip()
        if not safe_text:
            return
        lines = textwrap.wrap(safe_text, width=max(20, int(width or 58))) or [safe_text]
        for index, line in enumerate(lines):
            layout.label(text=line, icon=icon if index == 0 else 'BLANK1')

    def draw(self, context):
        layout = self.layout
        name = str(getattr(self, "region_pack_name", "") or "Region Pack").strip()
        countries = [part.strip() for part in str(getattr(self, "included_countries", "") or "").split("|") if part.strip()]
        layout.label(text=name, icon="WORLD")
        summary = layout.box()
        summary.label(text=f"New Tiles: {int(getattr(self, 'new_tile_count', 0) or 0)}", icon="TEXTURE")
        summary.label(text=f"Total Tiles: {int(getattr(self, 'total_tile_count', 0) or 0)}", icon="GRID")
        licenced = int(getattr(self, "already_licenced_tile_count", 0) or 0)
        if licenced > 0:
            saving = float(getattr(self, "already_licenced_saving_eur", 0.0) or 0.0)
            licenced_text = f"Already Licenced: {licenced} tile{'s' if licenced != 1 else ''}"
            if saving > 0.000001:
                licenced_text += f" (-{_format_eur_for_ui(saving)})"
            summary.label(text=licenced_text, icon="CHECKMARK")
        summary.label(text=f"Full Price: €{float(getattr(self, 'full_price_eur', 0.0) or 0.0):.2f}", icon="SOLO_ON")
        discount = int(getattr(self, "discount_percent", 0) or 0)
        if discount > 0:
            summary.label(
                text=(
                    f"Volume Discount: {discount}% "
                    f"(€{float(getattr(self, 'discount_eur', 0.0) or 0.0):.2f})"
                ),
                icon="SORTSIZE",
            )
        summary.label(text=f"Price: €{float(getattr(self, 'price_eur', 0.0) or 0.0):.2f}", icon="USER")
        country_box = layout.box()
        country_box.label(text="Included Countries / Areas", icon="WORLD_DATA")
        country_text = f"Countries: {', '.join(countries)}" if countries else "Country / area list is not available for this pack yet."
        self._wrapped_label(country_box, country_text)
        self._wrapped_label(
            layout,
            "Price uses only new Full Quality tiles; already licenced tiles are excluded before the volume discount is applied.",
            icon="INFO",
        )
        actions = layout.row(align=True)
        map_op = actions.operator("planetka.open_region_pack_map", text="Detailed Map", icon="URL")
        map_op.region_pack_id = str(getattr(self, "region_pack_id", "") or "")
        checkout = actions.operator(
            "planetka.open_credit_checkout",
            text=f"Licence {name} ({_format_eur_for_ui(getattr(self, 'price_eur', 0.0))})",
            icon="URL",
        )
        checkout.checkout_option = "REGION_PACK"
        checkout.region_pack_id = str(getattr(self, "region_pack_id", "") or "")
        checkout.region_pack_name = name
        checkout.included_countries = str(getattr(self, "included_countries", "") or "")
        _draw_region_pack_upsell_options(
            layout,
            context,
            current_region_pack_id=str(getattr(self, "region_pack_id", "") or ""),
            title="Larger Full Quality options",
        )

    def execute(self, _context):
        return {'FINISHED'}


class PLANETKA_OT_DataCostBreakdown(bpy.types.Operator):
    bl_idname = "planetka.data_cost_breakdown"
    bl_label = "Resolve Cost Breakdown"
    bl_description = "Show detailed data size and price breakdown for this Resolve"

    texture_quality_mode: EnumProperty(
        name="Texture Quality",
        items=(
            ("PREVIEW", "Preview", "Preview data is free"),
            ("BALANCED", "Standard", "Standard Quality data"),
            ("FULL", "Full Quality", "Full Quality paid land-detail data"),
        ),
        default="FULL",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    _breakdown = None

    def _price_text(self, value):
        try:
            return f"€{max(0.0, float(value or 0.0)):.2f}"
        except (TypeError, ValueError):
            return "€0.00"

    def _area_text(self, value):
        try:
            area = max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            area = 0.0
        if area >= 1000.0:
            return f"{area:,.0f} km2"
        if area >= 10.0:
            return f"{area:,.1f} km2"
        return f"{area:,.2f} km2"

    def _mpp_text(self, value):
        try:
            mpp = max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            mpp = 0.0
        if mpp <= 0:
            return "-"
        if mpp >= 1000.0:
            return f"{mpp / 1000.0:.1f} km/px"
        return f"{mpp:.0f} m/px"

    def _land_area_text(self, entry):
        if not isinstance(entry, dict):
            return self._area_text(0.0)
        try:
            land = max(0.0, float(entry.get("land_km2", 0.0) or 0.0))
        except (TypeError, ValueError):
            land = 0.0
        if land <= 0.0:
            try:
                land = max(0.0, float(entry.get("billable_land_km2", 0.0) or 0.0))
            except (TypeError, ValueError):
                land = 0.0
        return self._area_text(land)

    def _free_reason_text(self, reason):
        value = str(reason or "").strip()
        if value in {"already_unlocked", "already_owned"}:
            return "already licenced"
        if value == "already_listed_in_earlier_segment":
            return "already counted in an earlier animation segment"
        return value.replace("_", " ")

    def _draw_rows(self, layout, title, rows, icon="TEXTURE", empty_text="None", show_original_price=False):
        box = layout.box()
        box.label(text=title, icon=icon)
        entries = list(rows or ())
        if not entries:
            box.label(text=empty_text)
            return
        header = box.row(align=True)
        header.label(text="Tile")
        header.label(text="Data")
        header.label(text="Land Area")
        header.label(text="Texture Detail")
        header.label(text="Price")
        for entry in entries:
            tile_key = str(entry.get("tile_key", "") or "").strip()
            size_text = _format_bytes_for_ui(int(entry.get("bytes", 0) or 0))
            land_text = self._land_area_text(entry)
            detail_text = self._mpp_text(entry.get("delivered_mpp", 0.0))
            price_text = self._price_text(entry.get("credits", 0.0))
            original_price = 0.0
            charged_price = 0.0
            if show_original_price:
                try:
                    original_price = float(
                        entry.get(
                            "gross_price_eur",
                            entry.get("gross_credits", entry.get("credits", 0.0)),
                        ) or 0.0
                    )
                    charged_price = float(entry.get("credits", 0.0) or 0.0)
                except (TypeError, ValueError):
                    original_price = 0.0
                    charged_price = 0.0
            reason = str(entry.get("free_reason", "") or "").strip()
            row = box.row(align=True)
            row.label(text=tile_key or "Unknown")
            row.label(text=size_text)
            row.label(text=land_text)
            row.label(text=detail_text)
            row.label(text=price_text)
            upgrade_credit = 0.0
            try:
                upgrade_credit = max(0.0, float(entry.get("upgrade_credit_applied", 0.0) or 0.0))
            except (TypeError, ValueError):
                upgrade_credit = 0.0
            if upgrade_credit > 0.0:
                upgrade_row = box.row(align=True)
                upgrade_row.label(
                    text=f"  upgrade credit from previously licenced lower detail: {self._price_text(upgrade_credit)}",
                    icon="INFO",
                )
            if show_original_price and original_price > charged_price + 1e-9:
                original_row = box.row(align=True)
                original_row.label(text=f"  No charge: already licenced. Original price: {self._price_text(original_price)}", icon="INFO")
            if (
                reason
                and reason not in {"already_unlocked", "already_owned", "already_listed_in_earlier_segment"}
                and float(entry.get("credits", 0.0) or 0.0) <= 0.0
            ):
                reason_row = box.row(align=True)
                reason_row.label(text=f"  Reason: {self._free_reason_text(reason)}", icon="INFO")

    def invoke(self, context, event):
        del event
        mode = str(getattr(self, "texture_quality_mode", "FULL") or "FULL").strip().upper()
        if mode != "PREVIEW":
            mode = "FULL"
        try:
            prefs = get_prefs()
            base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
            from .planetka_runtime.view_telemetry import build_resolve_cost_breakdown, get_resolve_size_estimates
            breakdown = build_resolve_cost_breakdown(
                scene=getattr(context, "scene", None),
                scope_mode="CAMERA",
                base_path=base_path,
                texture_quality_mode=mode,
            )
            try:
                update_resolve_size_estimates(
                    getattr(context, "scene", None),
                    scope_mode="CAMERA",
                    base_path=base_path,
                    include_full_price=False,
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed refreshing resolve estimates before cost breakdown", exc_info=True)
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed refreshing resolve estimates before cost breakdown", exc_info=True)
            estimates = get_resolve_size_estimates(getattr(context, "scene", None))
            if isinstance(breakdown, dict):
                breakdown["panel_total_bytes"] = estimates.get(mode) if isinstance(estimates, dict) else None
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Unable to build cost breakdown: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka cost breakdown failed",
            )
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            return fail(
                self,
                f"Unable to build cost breakdown: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka cost breakdown failed",
            )
        self._breakdown = breakdown if isinstance(breakdown, dict) else {}
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'FINISHED'}
        return wm.invoke_popup(self, width=760)

    def draw(self, context):
        layout = self.layout
        breakdown = self._breakdown if isinstance(self._breakdown, dict) else {}
        mode = str(breakdown.get("quality_mode", getattr(self, "texture_quality_mode", "FULL")) or "FULL").strip().upper()
        if mode == "PREVIEW":
            mode_label = "Preview"
        elif mode == "BALANCED":
            mode_label = "Standard"
        else:
            mode_label = "Full Quality"
        total_bytes = breakdown.get("panel_total_bytes")
        if total_bytes is None:
            total_bytes = breakdown.get("total_bytes", 0)
        total_credits = breakdown.get("total_credits", 0.0)

        header = layout.box()
        header.label(text=f"{mode_label} Resolve Breakdown", icon="INFO")
        if not bool(breakdown.get("ok", True)):
            error = str(breakdown.get("error", "pricing_unavailable") or "pricing_unavailable").replace("_", " ")
            header.label(text=f"Pricing unavailable: {error}.", icon="ERROR")
            header.label(text="Reconnect Planetka Cloud and refresh Resolve to get the exact price.")
            return
        header.label(text=f"Total data size: {_format_bytes_for_ui(int(total_bytes or 0))}")
        header.label(text=f"Total price: {'Free' if mode == 'PREVIEW' else self._price_text(total_credits)}")
        if mode != "PREVIEW":
            header.label(
                text="Price is based on land area and texture detail; ocean-only, coarse, and already-licenced tiles are not charged.",
                icon="INFO",
            )
        header.label(
            text=(
                f"Tiles: {len(breakdown.get('tiles', ()) or ())} total, "
                f"{len(breakdown.get('charged_tiles', ()) or ())} charged, "
                f"{len(breakdown.get('excluded_tiles', ()) or ())} already licenced"
            )
        )

        self._draw_rows(
            layout,
            "Charged Tiles",
            breakdown.get("charged_tiles", ()),
            icon="SOLO_ON",
            empty_text="No newly charged tiles.",
        )
        self._draw_rows(
            layout,
            "Excluded From Price: Already Licenced",
            breakdown.get("excluded_tiles", ()),
            icon="CHECKMARK",
            empty_text="No already-licenced tiles in this Resolve.",
            show_original_price=True,
        )
        self._draw_rows(
            layout,
            "Free / Not Charged Tiles",
            breakdown.get("free_tiles", ()),
            icon="HIDE_OFF",
            empty_text="No other free tiles.",
        )
        if mode == "FULL":
            _draw_region_pack_upsell_options(
                layout,
                context,
                title="Broader Full Quality options",
            )

    def execute(self, context):
        del context
        return {'FINISHED'}


class PLANETKA_OT_DownloadStatusPopup(bpy.types.Operator):
    bl_idname = "planetka.download_status_popup"
    bl_label = "Planetka Download"
    bl_description = "Shows active Planetka download progress"
    bl_options = {'INTERNAL'}

    _timer = None

    @classmethod
    def poll(cls, context):
        return context is not None and not bool(getattr(bpy.app, "background", False))

    def _clear_running_flag(self, context):
        wm = getattr(context, "window_manager", None) if context is not None else None
        if wm is None:
            return
        try:
            if _DOWNLOAD_POPUP_WM_FLAG in wm:
                del wm[_DOWNLOAD_POPUP_WM_FLAG]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-038", "Failed clearing download popup running flag")

    def _finish(self, context):
        wm = getattr(context, "window_manager", None) if context is not None else None
        if wm is not None and self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-OPS-039", "Failed removing download popup timer")
        self._timer = None
        self._clear_running_flag(context)

    def invoke(self, context, _event):
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}

        try:
            if bool(wm.get(_DOWNLOAD_POPUP_WM_FLAG, False)):
                return {'CANCELLED'}
            wm[_DOWNLOAD_POPUP_WM_FLAG] = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-040", "Failed setting download popup running flag")

        if not is_download_active():
            self._clear_running_flag(context)
            return {'CANCELLED'}

        try:
            self._timer = wm.event_timer_add(0.2, window=getattr(context, "window", None))
            wm.modal_handler_add(self)
            return wm.invoke_popup(self, width=280)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            self._finish(context)
            return {'CANCELLED'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if not is_download_active():
            self._finish(context)
            return {'FINISHED'}
        try:
            for window in tuple(getattr(getattr(context, "window_manager", None), "windows", ())):
                screen = getattr(window, "screen", None)
                if screen is None:
                    continue
                for area in tuple(getattr(screen, "areas", ())):
                    if str(getattr(area, "type", "")) in {"VIEW_3D", "PROPERTIES"}:
                        area.tag_redraw()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        progress = get_download_progress()
        downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
        total_bytes = int(progress.get("total_bytes", 0) or 0)
        downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
        total_mb = float(total_bytes) / (1024.0 * 1024.0)

        row = layout.row()
        row.alert = True
        row.label(text="Downloading Planetka data…", icon='IMPORT')
        if total_bytes > 0:
            fraction = max(0.0, min(1.0, float(downloaded_bytes) / float(max(1, total_bytes))))
            if hasattr(layout, "progress"):
                layout.progress(factor=fraction, type='BAR', text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
            else:
                layout.label(text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
        else:
            if hasattr(layout, "progress"):
                layout.progress(factor=0.0, type='BAR', text=f"{downloaded_mb:.2f} MB")
            else:
                layout.label(text=f"{downloaded_mb:.2f} MB")
        layout.label(text="Window closes automatically when download completes.", icon='INFO')


class PLANETKA_OT_RebuildEarth(bpy.types.Operator):
    bl_idname = "planetka.rebuild_earth"
    bl_label = "Rebuild Earth"
    bl_description = (
        "Emergency rebuild: remove Planetka objects/shaders/runtime data from memory, "
        "preserve camera transform and keyframes, then run Create Earth"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Rebuild Earth"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.rebuild_earth_execute(self, context, globals())


class PLANETKA_OT_AddEarth(bpy.types.Operator):
    bl_idname = "planetka.add_earth"
    bl_label = "Create Earth"
    bl_description = "Create Planetka Earth assets"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Create Earth"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.add_earth_execute(self, context, globals())


class PLANETKA_OT_SaveStartupSetup(bpy.types.Operator):
    bl_idname = "planetka.save_startup_setup"
    bl_label = "Save Current Setup as Startup Default"
    bl_description = (
        "Save current Planetka setup (Location, Sunlight, Earth Transform, Earth Grading, "
        "Animation, and Settings) and reuse it for Create Earth in new Blender files"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Save startup setup"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        if get_earth_object() is None:
            return fail(self, "Create Earth first, then save startup setup defaults.", logger=logger)
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        profile = _serialize_current_startup_setup_profile(scene, props)
        if not _store_startup_setup_profile(prefs, profile):
            return fail(self, "Failed to save startup setup defaults.", logger=logger)
        if not _persist_user_preferences():
            self.report({'WARNING'}, "Startup setup saved for this session only. Use Blender Save Preferences to persist it.")
        else:
            self.report({'INFO'}, "Startup setup saved. New Create Earth actions will reuse this setup.")
        return {'FINISHED'}


class PLANETKA_OT_ResetStartupSetupFactory(bpy.types.Operator):
    bl_idname = "planetka.reset_startup_setup_factory"
    bl_label = "Reset Startup Setup"
    bl_description = (
        "Clear custom startup setup and restore Planetka factory startup values "
        "(Location, Sunlight, Earth Transform, Earth Grading, Animation, and Settings)"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Reset startup setup"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        if not _store_startup_setup_profile(prefs, None):
            return fail(self, "Failed to clear custom startup setup.", logger=logger)
        if not _persist_user_preferences():
            self.report({'WARNING'}, "Startup setup reset for this session only. Use Blender Save Preferences to persist it.")

        factory_profile = _build_factory_startup_setup_profile(scene, props)
        _apply_startup_setup_profile(scene, props, factory_profile, apply_navigation_shot=False)
        if _persist_user_preferences():
            self.report({'INFO'}, "Startup setup reset to factory defaults.")
        return {'FINISHED'}


class PLANETKA_OT_NavigationApplyShot(bpy.types.Operator):
    bl_idname = "planetka.navigation_apply_shot"
    bl_label = "Apply Navigation Shot"
    bl_description = "Apply current Navigation shot values to the active scene camera"
    bl_options = {'INTERNAL'}

    force_camera_view: BoolProperty(
        name="Force Camera View",
        default=True,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    sync_active_view_when_not_camera: BoolProperty(
        name="Sync Active View",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Navigation apply"):
            return {'CANCELLED'}
        return _navigation_ops.navigation_apply_shot_execute(self, context, globals())


class PLANETKA_OT_UseCurrentViewNavigation(bpy.types.Operator):
    bl_idname = "planetka.navigation_use_current_view"
    bl_label = "Bring Camera to View"
    bl_description = "Move active camera to current viewport view and sync Navigation values"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Bring Camera to View"):
            return {'CANCELLED'}
        return _navigation_ops.use_current_view_navigation_execute(self, context, globals())


class PLANETKA_OT_AutoAdjustClipping(bpy.types.Operator):
    bl_idname = "planetka.auto_adjust_clipping"
    bl_label = "Change Clipping Automatically"
    bl_description = (
        "Automatically adjust Camera/Viewport clipping based on current Earth size and camera proximity"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Clipping adjustment"):
            return {'CANCELLED'}
        return _navigation_ops.auto_adjust_clipping_execute(self, context, globals())


class PLANETKA_OT_ResetEarthTransform(bpy.types.Operator):
    bl_idname = "planetka.reset_earth_transform"
    bl_label = "Reset Transform"
    bl_description = "Reset Planetka Root Location and Rotation to defaults (0, 0, 0)"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Reset transform"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.reset_earth_transform_execute(self, context, globals())


class PLANETKA_OT_ResetSurfaceGradingSection(bpy.types.Operator):
    bl_idname = "planetka.reset_surface_grading_section"
    bl_label = "Reset Surface Grading Section"
    bl_description = "Reset one Surface Grading section to Planetka defaults"

    section: EnumProperty(
        name="Section",
        items=(
            ("GLOBAL", "Global", "Reset Global section values"),
            ("WATER", "Water", "Reset Water section values"),
            ("ELEVATION", "Elevation", "Reset Elevation section values"),
            ("NIGHT", "Night", "Reset Night section values"),
        ),
        default="GLOBAL",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Surface grading reset"):
            return {'CANCELLED'}
        _ = context
        nodes = tuple(_iter_surface_grading_nodes())
        if not nodes:
            return fail(
                self,
                "Earth Surface Grading node group not found.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        section_key = str(getattr(self, "section", "GLOBAL") or "GLOBAL").strip().upper()
        section_socket_names = _SURFACE_GRADING_SECTION_SOCKET_NAMES.get(section_key, set())
        if not section_socket_names:
            return fail(
                self,
                f"Unknown Surface Grading section: {section_key}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        defaults_by_name = {}
        for key, value in _surface_grading_factory_values().items():
            normalized = str(key or "").strip().lower()
            if normalized:
                defaults_by_name[normalized] = value

        reset_count = 0
        touched_count = 0
        for node in nodes:
            for socket in _iter_surface_grading_input_sockets(node):
                socket_name_raw = str(getattr(socket, "name", "") or "").strip()
                socket_name = socket_name_raw.lower()
                if socket_name not in section_socket_names:
                    continue
                touched_count += 1
                if socket_name not in defaults_by_name:
                    continue
                target_value = defaults_by_name.get(socket_name)
                try:
                    if isinstance(target_value, (list, tuple)):
                        socket.default_value = tuple(target_value)
                    else:
                        socket.default_value = target_value
                    reset_count += 1
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug(
                        "Planetka: failed resetting surface grading socket '%s' in section '%s'",
                        socket_name_raw,
                        section_key,
                        exc_info=True,
                    )

        if touched_count <= 0:
            return fail(
                self,
                f"No sockets found for Surface Grading section '{section_key.title()}'.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        self.report({'INFO'}, f"Surface Grading '{section_key.title()}' reset ({reset_count}/{touched_count} values).")
        return {'FINISHED'}
