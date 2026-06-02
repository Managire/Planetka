import os
import logging

import bpy
from bpy.props import PointerProperty

# Includes data from GeoNames (allCountries) licenced under CC BY 4.0.

from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from . import updater as _planetka_updater

from .animation_tools import (
    PLANETKA_OT_AnimationClearCameraKeyframes,
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_AnimationGenerateCameraKeyframes,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRender,
    PLANETKA_OT_AnimationSaveView,
    PLANETKA_OT_AnimationStop,
    PLANETKA_OT_AnimationWaypointAdd,
    PLANETKA_OT_AnimationWaypointApply,
    PLANETKA_OT_AnimationWaypointCaptureCurrent,
    PLANETKA_OT_AnimationWaypointRemove,
)
from .extension_prefs import PlanetkaExtensionPreferences
from .operators import (
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
    PLANETKA_OT_DownloadStatusPopup,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_ResetEarthTransform,
    PLANETKA_OT_ResetSurfaceGradingSection,
    PLANETKA_OT_AutoAdjustClipping,
    PLANETKA_OT_CreateStandaloneFile,
    PLANETKA_OT_OptimizeRenderSettings,
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
    mark_render_job_progress,
    mark_render_job_started,
    recover_post_render_state,
    stop_auto_resolve_service,
)
from .ui import (
    PLANETKA_OT_ToggleUiSection,
    PLANETKA_PT_AnimationStopPanel,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryPanelFailure,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_LinksPanelCollapsed,
    PLANETKA_PT_AtmospherePanel,
    PLANETKA_PT_AtmospherePanelCollapsed,
    PLANETKA_PT_CloudsPanel,
    PLANETKA_PT_CloudsPanelCollapsed,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_EarthSettingsPanel,
    PLANETKA_PT_EarthSettingsPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NewEarthPanelFailure,
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
    "version": (0, 8, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Planetka",
    "description": "Cinematic Earth visualisation system",
    "category": "3D View",
}

logger = logging.getLogger(__name__)


def _feature_flag_enabled(name, default=False):
    fallback = "1" if bool(default) else "0"
    token = str(os.getenv(name, fallback) or fallback).strip().lower()
    return token in {"1", "true", "yes", "on"}


_CLOUD_RUNTIME_ENABLED = _feature_flag_enabled("PLANETKA_ENABLE_CLOUD_RUNTIME", default=True)
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
        register_object_properties as register_cloud_object_properties,
        unregister_object_properties as unregister_cloud_object_properties,
    )
    from .clouds_vdb import (
        PLANETKA_OT_AddVDBCloud,
        PLANETKA_OT_DeleteVDBCloud,
        PLANETKA_OT_ResetVDBCloudToCameraView,
    )

    _CLOUD_CLASSES = (
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
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
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
    PLANETKA_OT_OptimizeRenderSettings,
    PLANETKA_OT_SetBackgroundBlack,
    PLANETKA_OT_SetTextureQualityAndResolve,
    PLANETKA_OT_UseCurrentViewNavigation,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
    *_CLOUD_CLASSES,
    PLANETKA_OT_AnimationClearCameraKeyframes,
    PLANETKA_OT_AnimationGenerateCameraKeyframes,
    PLANETKA_OT_AnimationSaveView,
    PLANETKA_OT_AnimationWaypointAdd,
    PLANETKA_OT_AnimationWaypointRemove,
    PLANETKA_OT_AnimationWaypointCaptureCurrent,
    PLANETKA_OT_AnimationWaypointApply,
    PLANETKA_OT_AnimationRender,
    PLANETKA_OT_AnimationStop,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_LoadTextures,
    PLANETKA_OT_SceneHealthCheck,
    PLANETKA_OT_ReportBug,
    PLANETKA_OT_SaveStartupSetup,
    PLANETKA_OT_ResetStartupSetupFactory,
    PLANETKA_OT_ToggleUiSection,
    PLANETKA_PT_AnimationStopPanel,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelFailure,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_NavigationPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanelFailure,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_AtmospherePanel,
    PLANETKA_PT_AtmospherePanelCollapsed,
    PLANETKA_PT_CloudsPanel,
    PLANETKA_PT_CloudsPanelCollapsed,
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


def _is_readonly_state_error(exc):
    message = str(exc or "").strip().lower()
    if not message:
        return False
    return any(
        token in message
        for token in (
            "readonly state",
            "read-only state",
            "cannot run in readonly state",
            "cannot set in readonly state",
            "cannot modify blend data in this state",
            "writing to id classes in this context is not allowed",
        )
    )


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        message = str(exc)
        if (
            "missing bl_rna" in message
            or "not registered" in message
            or _is_readonly_state_error(exc)
        ):
            logger.debug(
                "Planetka: ignored unregister_class issue for %s during lifecycle cleanup",
                str(getattr(cls, "__name__", cls)),
                exc_info=True,
            )
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


def _planetka_render_complete(scene):
    recover_post_render_state(scene, cancelled=False)


def _planetka_render_cancel(scene):
    recover_post_render_state(scene, cancelled=True)


def _planetka_render_pre(scene):
    mark_render_job_started(scene)


def _planetka_render_post(scene, *args):
    del args
    mark_render_job_progress(scene, frame_written=False)


def _planetka_render_write(scene, *args):
    del args
    mark_render_job_progress(scene, frame_written=True)


def _remove_render_handlers():
    handler_lists = [
        bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post,
        bpy.app.handlers.render_complete,
        bpy.app.handlers.render_cancel,
    ]
    render_write_handlers = getattr(bpy.app.handlers, "render_write", None)
    if render_write_handlers is not None:
        handler_lists.append(render_write_handlers)

    for handler_list in handler_lists:
        for handler in list(handler_list):
            if handler is _planetka_render_pre or getattr(handler, "__name__", "") == "_planetka_render_pre":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_post or getattr(handler, "__name__", "") == "_planetka_render_post":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_write or getattr(handler, "__name__", "") == "_planetka_render_write":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_complete or getattr(handler, "__name__", "") == "_planetka_render_complete":
                handler_list.remove(handler)
                continue
            if handler is _planetka_render_cancel or getattr(handler, "__name__", "") == "_planetka_render_cancel":
                handler_list.remove(handler)


def _register_keymaps():
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed accessing window manager while registering keymaps", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed accessing window manager while registering keymaps", exc_info=True)
        return
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
            logger.debug("Planetka: failed removing addon keymap item during unregister", exc_info=True)
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
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed tagging VIEW_3D area for redraw during register", exc_info=True)
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
    try:
        from .auth import _ensure_device_id
        _ensure_device_id()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed initializing anonymous install id during register", exc_info=True)

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
    render_write_handlers = getattr(bpy.app.handlers, "render_write", None)
    if render_write_handlers is not None:
        render_write_handlers.append(_planetka_render_write)
    bpy.app.handlers.render_complete.append(_planetka_render_complete)
    bpy.app.handlers.render_cancel.append(_planetka_render_cancel)
    _unregister_keymaps()
    _register_keymaps()
    try:
        _planetka_updater.kickoff_background_update_check(force=False)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed starting background update check during register", exc_info=True)
    try:
        from .unsupported import apply_runtime_unsupported_overrides
        apply_runtime_unsupported_overrides()
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying unsupported-runtime overrides during register", exc_info=True)
    try:
        bpy.app.timers.register(_tag_view3d_ui_redraw, first_interval=0.05)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed scheduling initial UI redraw timer during register", exc_info=True)


def unregister():
    try:
        _unregister_keymaps()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed unregistering keymaps during unregister", exc_info=True)
    try:
        _remove_load_post_handler()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing load_post handler during unregister", exc_info=True)
    try:
        _remove_depsgraph_post_handler()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing depsgraph_update_post handler during unregister", exc_info=True)
    try:
        _remove_frame_change_post_handler()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing frame_change_post handler during unregister", exc_info=True)
    try:
        _remove_render_handlers()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing render handlers during unregister", exc_info=True)
    try:
        stop_auto_resolve_service()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping auto-resolve service during unregister", exc_info=True)
    if hasattr(bpy.types.Scene, "planetka"):
        try:
            del bpy.types.Scene.planetka
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if not _is_readonly_state_error(exc):
                raise
            logger.debug(
                "Planetka: ignored read-only state while deleting Scene.planetka during unregister",
                exc_info=True,
            )
    for cls in reversed(classes):
        try:
            _safe_unregister_class(cls)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if not _is_readonly_state_error(exc):
                raise
            logger.debug(
                "Planetka: ignored read-only state while unregistering %s during unregister",
                str(getattr(cls, "__name__", cls)),
                exc_info=True,
            )
    try:
        unregister_cloud_object_properties()
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        if not _is_readonly_state_error(exc):
            raise
        logger.debug(
            "Planetka: ignored read-only state while unregistering cloud object properties",
            exc_info=True,
        )


if __name__ == "__main__":
    register()
