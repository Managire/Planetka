import os

import bpy
from bpy.props import PointerProperty

# Includes data from GeoNames (allCountries) licensed under CC BY 4.0.

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from . import updater as _planetka_updater

from .animation_tools import (
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationRenderInfo,
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
    PLANETKA_OT_UpdateNow,
    PLANETKA_OT_DownloadStatusPopup,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_ResetEarthTransform,
    PLANETKA_OT_ResetSurfaceGradingSection,
    PLANETKA_OT_AutoAdjustClipping,
    PLANETKA_OT_CreateStandaloneFile,
    PLANETKA_OT_RemoveDefaultScene,
    PLANETKA_OT_SetBackgroundBlack,
    PLANETKA_OT_SetTextureQualityAndResolve,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_RebuildEarth,
    PLANETKA_OT_ResetStartupSetupFactory,
    PLANETKA_OT_SaveStartupSetup,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_SunlightPreset,
    PLANETKA_OT_UseCurrentViewNavigation,
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
    PLANETKA_PT_LiveTelemetryPanelFailure,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_LinksPanelCollapsed,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_EarthSettingsPanel,
    PLANETKA_PT_EarthSettingsPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NewEarthPanelFailure,
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_SubscriptionPanelUpdate,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_SettingsPanel,
)
from .validation import (
    PLANETKA_OT_ReportBug,
    PLANETKA_OT_SceneHealthCheck,
    PLANETKA_OT_ValidateTextureSource,
)

bl_info = {
    "name": "Planetka - the Earth",
    "author": "Tomas Griger",
    "version": (0, 7, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Planetka",
    "description": "Cinematic Earth visualisation system",
    "category": "3D View",
}


def _feature_flag_enabled(name, default=False):
    fallback = "1" if bool(default) else "0"
    token = str(os.getenv(name, fallback) or fallback).strip().lower()
    return token in {"1", "true", "yes", "on"}


_CLOUD_RUNTIME_ENABLED = _feature_flag_enabled("PLANETKA_ENABLE_CLOUD_RUNTIME", default=False)
_PUBLIC_BUILD_PROFILE = _feature_flag_enabled("PLANETKA_PUBLIC_BUILD", default=True)
_LEGACY_RUNTIME_ENABLED = _feature_flag_enabled(
    "PLANETKA_ENABLE_LEGACY_RUNTIME",
    default=(not _PUBLIC_BUILD_PROFILE),
)

if _CLOUD_RUNTIME_ENABLED:
    from .clouds_local import (
        PLANETKA_OT_AddLocalCloud,
        PLANETKA_OT_DeleteLocalCloud,
        PLANETKA_OT_ResetLocalCloudToCameraView,
        PLANETKA_OT_SetCloudViewMode,
        register_object_properties as register_cloud_object_properties,
        unregister_object_properties as unregister_cloud_object_properties,
    )
    from .clouds_vdb import (
        PLANETKA_OT_AddVDBCloud,
        PLANETKA_OT_DeleteVDBCloud,
        PLANETKA_OT_ResetVDBCloudToCameraView,
    )

    _CLOUD_CLASSES = (
        PLANETKA_OT_SetCloudViewMode,
        PLANETKA_OT_AddLocalCloud,
        PLANETKA_OT_ResetLocalCloudToCameraView,
        PLANETKA_OT_DeleteLocalCloud,
        PLANETKA_OT_AddVDBCloud,
        PLANETKA_OT_ResetVDBCloudToCameraView,
        PLANETKA_OT_DeleteVDBCloud,
    )
else:
    def register_cloud_object_properties():
        return None


    def unregister_cloud_object_properties():
        return None


    _CLOUD_CLASSES = ()


if _LEGACY_RUNTIME_ENABLED:
    _LEGACY_CLASSES = (
        PLANETKA_OT_DownloadStatusPopup,
        PLANETKA_OT_AnimationPreviewShot,
        PLANETKA_OT_ValidateTextureSource,
    )
else:
    _LEGACY_CLASSES = ()

_PLANETKA_PROPERTIES_ANNOTATIONS_ORIGINAL = dict(getattr(PlanetkaProperties, "__annotations__", {}) or {})
_LEGACY_PROPERTY_NAMES = (
    "anim_render_texture_quality",
    "anim_start_altitude_km",
    "anim_flyby_degrees",
    "anim_flyby_camera_heading_deg",
)


def _configure_planetka_properties_for_profile():
    annotations = getattr(PlanetkaProperties, "__annotations__", None)
    if not isinstance(annotations, dict):
        return
    annotations.clear()
    annotations.update(_PLANETKA_PROPERTIES_ANNOTATIONS_ORIGINAL)
    if not _LEGACY_RUNTIME_ENABLED:
        for key in _LEGACY_PROPERTY_NAMES:
            annotations.pop(str(key), None)


classes = (
    PlanetkaExtensionPreferences,
    PlanetkaAnimationWaypoint,
    PlanetkaProperties,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountUpgrade,
    *_LEGACY_CLASSES,
    PLANETKA_OT_RemoveDefaultScene,
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_RebuildEarth,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_ResetEarthTransform,
    PLANETKA_OT_ResetSurfaceGradingSection,
    PLANETKA_OT_AutoAdjustClipping,
    PLANETKA_OT_CreateStandaloneFile,
    PLANETKA_OT_SetBackgroundBlack,
    PLANETKA_OT_SetTextureQualityAndResolve,
    PLANETKA_OT_UseCurrentViewNavigation,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
    *_CLOUD_CLASSES,
    PLANETKA_OT_AnimationSaveView,
    PLANETKA_OT_AnimationWaypointAdd,
    PLANETKA_OT_AnimationWaypointRemove,
    PLANETKA_OT_AnimationWaypointCaptureCurrent,
    PLANETKA_OT_AnimationWaypointApply,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationRenderInfo,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_LoadTextures,
    PLANETKA_OT_SceneHealthCheck,
    PLANETKA_OT_ReportBug,
    PLANETKA_OT_SaveStartupSetup,
    PLANETKA_OT_ResetStartupSetupFactory,
    PLANETKA_PT_SubscriptionPanel,
    PLANETKA_PT_SubscriptionPanelCollapsed,
    PLANETKA_PT_SubscriptionPanelUpdate,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelFailure,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanelFailure,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_NavigationPanel,
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


def _planetka_render_complete(_dummy):
    recover_post_render_state(getattr(bpy.context, "scene", None), cancelled=False)


def _planetka_render_cancel(_dummy):
    recover_post_render_state(getattr(bpy.context, "scene", None), cancelled=True)


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
            if handler is _planetka_render_complete or getattr(handler, "__name__", "") == "_planetka_render_complete":
                handler_list.remove(handler)
                continue
            if getattr(handler, "__name__", "") == "_planetka_render_post":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_cancel or getattr(handler, "__name__", "") == "_planetka_render_cancel":
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
    _configure_planetka_properties_for_profile()
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
    bpy.app.handlers.render_complete.append(_planetka_render_complete)
    bpy.app.handlers.render_cancel.append(_planetka_render_cancel)
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
