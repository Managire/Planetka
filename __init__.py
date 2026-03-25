import bpy
from bpy.props import PointerProperty

# Includes data from GeoNames (allCountries) licensed under CC BY 4.0.

from .auth import ensure_device_login_polling, get_login_state
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .animation_tools import (
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationSaveView,
)
from .extension_prefs import PlanetkaExtensionPreferences
from .extension_prefs import get_prefs
from .operators import (
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountManageSubscription,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_ConfirmImportNewData,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_ImportNewData,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_SelectTextureSource,
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
from .properties import PlanetkaProperties
from .render_prep import PLANETKA_OT_LoadTextures
from .state import (
    _iter_scenes,
    _planetka_depsgraph_update_post,
    _planetka_load_post,
    _sync_logging_from_scenes,
    _sync_props_from_idprops,
    mark_render_job_started,
    migrate_scene,
    recover_post_render_state,
    stop_auto_resolve_service,
)
from .ui import (
    PLANETKA_PT_DataUsagePanel,
    PLANETKA_PT_DataUsagePanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_NavigationSavedLocationsPanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_SubscriptionDetailsPanel,
    PLANETKA_PT_SubscriptionDetailsPanelCollapsed,
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_SurfaceGradingPanel,
    PLANETKA_PT_SurfaceGradingPanelCollapsed,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_SettingsPanel,
)
from .validation import PLANETKA_OT_ReportBug, PLANETKA_OT_ValidateTextureSource

bl_info = {
    "name": "Planetka - the Earth",
    "author": "Tomas Griger",
    "version": (0, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Planetka",
    "description": "Cinematic Earth visualisation system",
    "category": "3D View",
}


classes = (
    PlanetkaExtensionPreferences,
    PlanetkaProperties,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_AccountManageSubscription,
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
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
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_SubscriptionDetailsPanel,
    PLANETKA_PT_SubscriptionDetailsPanelCollapsed,
    PLANETKA_PT_DataUsagePanel,
    PLANETKA_PT_DataUsagePanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LiveTelemetryAdvancedPanel,
    PLANETKA_PT_LiveTelemetryAdvancedPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_NavigationSavedLocationsPanelCollapsed,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_SurfaceGradingPanel,
    PLANETKA_PT_SurfaceGradingPanelCollapsed,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_SettingsPanel,
    PLANETKA_PT_LinksPanel,
)
_addon_keymaps = []

def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        message = str(exc)
        if "already registered as a subclass" in message:
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


def register():
    register_cloud_object_properties()
    for cls in classes:
        _safe_register_class(cls)
    if not hasattr(bpy.types.Scene, "planetka"):
        bpy.types.Scene.planetka = PointerProperty(type=PlanetkaProperties)

    for scene in _iter_scenes():
        _sync_props_from_idprops(scene)
        migrate_scene(scene)
    _sync_logging_from_scenes()
    if get_login_state(get_prefs()) == "pending":
        ensure_device_login_polling()

    _remove_load_post_handler()
    _remove_depsgraph_post_handler()
    bpy.app.handlers.load_post.append(_planetka_load_post)
    bpy.app.handlers.depsgraph_update_post.append(_planetka_depsgraph_update_post)
    _remove_render_handlers()
    bpy.app.handlers.render_pre.append(_planetka_render_pre)
    bpy.app.handlers.render_post.append(_planetka_render_post)
    bpy.app.handlers.render_complete.append(_planetka_render_post)
    bpy.app.handlers.render_cancel.append(_planetka_render_post)
    _unregister_keymaps()
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    _remove_load_post_handler()
    _remove_depsgraph_post_handler()
    _remove_render_handlers()
    stop_auto_resolve_service()
    if hasattr(bpy.types.Scene, "planetka"):
        del bpy.types.Scene.planetka
    for cls in reversed(classes):
        _safe_unregister_class(cls)
    unregister_cloud_object_properties()


if __name__ == "__main__":
    register()
