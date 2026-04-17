import bpy
from bpy.props import PointerProperty

# Includes data from GeoNames (allCountries) licensed under CC BY 4.0.

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from . import updater as _planetka_updater

try:
    _planetka_updater.apply_pending_update_on_import()
except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
    # Updater bootstrap must never block addon import/registration.
    pass

from .animation_tools import (
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationSaveView,
    PLANETKA_OT_AnimationWaypointAdd,
    PLANETKA_OT_AnimationWaypointApply,
    PLANETKA_OT_AnimationWaypointCaptureCurrent,
    PLANETKA_OT_AnimationWaypointRemove,
)
from .extension_prefs import PlanetkaExtensionPreferences
from .operators import (
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_ConfirmImportNewData,
    PLANETKA_OT_DownloadStatusPopup,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_ImportNewData,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_GoToNewZealand,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_AutoAdjustClipping,
    PLANETKA_OT_SetBackgroundBlack,
    PLANETKA_OT_SetTextureQualityAndResolve,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_ResetStartupSetupFactory,
    PLANETKA_OT_SaveStartupSetup,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_SelectTextureSource,
    PLANETKA_OT_SwitchToCycles,
    PLANETKA_OT_SunlightPreset,
    PLANETKA_OT_UseCurrentViewNavigation,
)
from .clouds_local import (
    PLANETKA_OT_AddLocalCloud,
    PLANETKA_OT_DeleteLocalCloud,
    PLANETKA_OT_ResetLocalCloudToCameraView,
    PLANETKA_OT_SetCloudViewMode,
    PLANETKA_PT_LocalCloudsPanel,
    register_object_properties as register_cloud_object_properties,
    sync_cloud_system_scene,
    unregister_object_properties as unregister_cloud_object_properties,
)
from .clouds_global import PLANETKA_PT_GlobalCloudsPanel
from .clouds_vdb import (
    PLANETKA_OT_AddVDBCloud,
    PLANETKA_OT_DeleteVDBCloud,
    PLANETKA_OT_ResetVDBCloudToCameraView,
    PLANETKA_PT_VDBCloudsPanel,
)
from .properties import PlanetkaAnimationWaypoint, PlanetkaProperties
from .render_prep import PLANETKA_OT_LoadTextures
from .state import (
    _planetka_depsgraph_update_post,
    _planetka_frame_change_post,
    _planetka_load_post,
    _sync_logging_from_scenes,
    mark_render_job_started,
    recover_post_render_state,
    stop_auto_resolve_service,
)
from .ui import (
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanelCollapsed,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_LinksPanelCollapsed,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_EarthSettingsPanel,
    PLANETKA_PT_EarthSettingsPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_NavigationSavedLocationsPanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_SettingsPanel,
)
from .validation import PLANETKA_OT_ReportBug, PLANETKA_OT_ValidateTextureSource

bl_info = {
    "name": "Planetka - the Earth",
    "author": "Tomas Griger",
    "version": (0, 7, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Planetka",
    "description": "Cinematic Earth visualisation system",
    "category": "3D View",
}


classes = (
    PlanetkaExtensionPreferences,
    PlanetkaAnimationWaypoint,
    PlanetkaProperties,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_SwitchToCycles,
    PLANETKA_OT_DownloadStatusPopup,
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_GoToNewZealand,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_AutoAdjustClipping,
    PLANETKA_OT_SetBackgroundBlack,
    PLANETKA_OT_SetTextureQualityAndResolve,
    PLANETKA_OT_UseCurrentViewNavigation,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
    PLANETKA_OT_SetCloudViewMode,
    PLANETKA_OT_AddLocalCloud,
    PLANETKA_OT_ResetLocalCloudToCameraView,
    PLANETKA_OT_DeleteLocalCloud,
    PLANETKA_OT_AddVDBCloud,
    PLANETKA_OT_ResetVDBCloudToCameraView,
    PLANETKA_OT_DeleteVDBCloud,
    PLANETKA_OT_AnimationSaveView,
    PLANETKA_OT_AnimationWaypointAdd,
    PLANETKA_OT_AnimationWaypointRemove,
    PLANETKA_OT_AnimationWaypointCaptureCurrent,
    PLANETKA_OT_AnimationWaypointApply,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_SelectTextureSource,
    PLANETKA_OT_ImportNewData,
    PLANETKA_OT_ConfirmImportNewData,
    PLANETKA_OT_LoadTextures,
    PLANETKA_OT_ValidateTextureSource,
    PLANETKA_OT_ReportBug,
    PLANETKA_OT_SaveStartupSetup,
    PLANETKA_OT_ResetStartupSetupFactory,
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_NavigationSavedLocationsPanelCollapsed,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_EarthSettingsPanel,
    PLANETKA_PT_EarthSettingsPanelCollapsed,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_SettingsPanel,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_LinksPanelCollapsed,
)
_addon_keymaps = []

def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        message = str(exc)
        if "already registered as a subclass" in message:
            _safe_unregister_class(cls)
            bpy.utils.register_class(cls)
            return
        raise


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        message = str(exc)
        if "missing bl_rna" in message or "not registered" in message:
            return
        raise


def _remove_load_post_handler():
    handlers = bpy.app.handlers.load_post
    for handler in list(handlers):
        if handler is _planetka_load_post or getattr(handler, "__name__", "") == "_planetka_load_post":
            handlers.remove(handler)


def _remove_depsgraph_post_handler():
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in list(handlers):
        if (
            handler is _planetka_depsgraph_update_post
            or getattr(handler, "__name__", "") == "_planetka_depsgraph_update_post"
        ):
            handlers.remove(handler)


def _remove_frame_change_post_handler():
    handlers = bpy.app.handlers.frame_change_post
    for handler in list(handlers):
        if (
            handler is _planetka_frame_change_post
            or getattr(handler, "__name__", "") == "_planetka_frame_change_post"
        ):
            handlers.remove(handler)


def _planetka_render_post(_dummy):
    recover_post_render_state(getattr(bpy.context, "scene", None))


def _planetka_render_pre(_dummy):
    mark_render_job_started()


def _remove_render_handlers():
    for handler_list in (
        bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post,
        bpy.app.handlers.render_complete,
        bpy.app.handlers.render_cancel,
    ):
        for handler in list(handler_list):
            if handler is _planetka_render_pre or getattr(handler, "__name__", "") == "_planetka_render_pre":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_post or getattr(handler, "__name__", "") == "_planetka_render_post":
                handler_list.remove(handler)


def _register_keymaps():
    wm = getattr(bpy.context, "window_manager", None)
    keyconfigs = getattr(wm, "keyconfigs", None) if wm else None
    addon_keyconfig = getattr(keyconfigs, "addon", None) if keyconfigs else None
    if addon_keyconfig is None:
        return
    keymap = addon_keyconfig.keymaps.new(name="3D View", space_type='VIEW_3D')
    for key_type in ("NUMPAD_0", "ZERO"):
        keymap_item = keymap.keymap_items.new(
            "planetka.navigation_use_current_view",
            type=key_type,
            value='PRESS',
            alt=True,
            oskey=True,
        )
        _addon_keymaps.append((keymap, keymap_item))


def _unregister_keymaps():
    for keymap, keymap_item in list(_addon_keymaps):
        try:
            keymap.keymap_items.remove(keymap_item)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
    _addon_keymaps.clear()


def _tag_view3d_ui_redraw():
    context = getattr(bpy, "context", None)
    wm = getattr(context, "window_manager", None) if context else None
    if wm is None:
        return None

    for window in getattr(wm, "windows", ()):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in getattr(screen, "areas", ()):
            if str(getattr(area, "type", "")) != "VIEW_3D":
                continue
            try:
                area.tag_redraw()
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue
    return None


def register():
    register_cloud_object_properties()
    for cls in classes:
        _safe_unregister_class(cls)
        _safe_register_class(cls)
    if not hasattr(bpy.types.Scene, "planetka"):
        bpy.types.Scene.planetka = PointerProperty(type=PlanetkaProperties)

    _sync_logging_from_scenes()
    _remove_load_post_handler()
    _remove_depsgraph_post_handler()
    _remove_frame_change_post_handler()
    bpy.app.handlers.load_post.append(_planetka_load_post)
    bpy.app.handlers.depsgraph_update_post.append(_planetka_depsgraph_update_post)
    bpy.app.handlers.frame_change_post.append(_planetka_frame_change_post)
    _remove_render_handlers()
    bpy.app.handlers.render_pre.append(_planetka_render_pre)
    bpy.app.handlers.render_post.append(_planetka_render_post)
    bpy.app.handlers.render_complete.append(_planetka_render_post)
    bpy.app.handlers.render_cancel.append(_planetka_render_post)
    _unregister_keymaps()
    _register_keymaps()
    try:
        _planetka_updater.kickoff_background_update_check(force=False)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .unsupported import apply_runtime_unsupported_overrides
        apply_runtime_unsupported_overrides()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        pass
    try:
        bpy.app.timers.register(_tag_view3d_ui_redraw, first_interval=0.05)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass


def unregister():
    _unregister_keymaps()
    _remove_load_post_handler()
    _remove_depsgraph_post_handler()
    _remove_frame_change_post_handler()
    _remove_render_handlers()
    stop_auto_resolve_service()
    if hasattr(bpy.types.Scene, "planetka"):
        del bpy.types.Scene.planetka
    for cls in reversed(classes):
        _safe_unregister_class(cls)
    unregister_cloud_object_properties()


if __name__ == "__main__":
    register()
