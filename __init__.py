import bpy
from bpy.props import PointerProperty

# Includes data from GeoNames (allCountries) licensed under CC BY 4.0.

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .animation_tools import (
    PLANETKA_OT_AnimationClearPrepared,
    PLANETKA_OT_AnimationMakeReady,
    PLANETKA_OT_AnimationPreviewShot,
    PLANETKA_OT_AnimationRenderHeadless,
    PLANETKA_OT_AnimationSaveView,
)
from .extension_prefs import PlanetkaExtensionPreferences
from .operators import (
    PLANETKA_OT_AddEarth,
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
from .properties import PlanetkaProperties
from .render_prep import PLANETKA_OT_LoadTextures
from .state import (
    _iter_scenes,
    _planetka_load_post,
    _sync_logging_from_scenes,
    _sync_props_from_idprops,
    ensure_auto_resolve_service_running,
    mark_render_job_started,
    migrate_scene,
    recover_post_render_state,
    stop_auto_resolve_service,
)
from .ui import (
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_LinksPanel,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_AtmospherePanel,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
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
    PLANETKA_OT_AddEarth,
    PLANETKA_OT_SaveLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_NavigationApplyShot,
    PLANETKA_OT_UseCurrentViewNavigation,
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
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
    PLANETKA_PT_NewEarthPanel,
    PLANETKA_PT_NewEarthPanelCollapsed,
    PLANETKA_PT_LiveTelemetryPanel,
    PLANETKA_PT_LiveTelemetryPanelCollapsed,
    PLANETKA_PT_NavigationPanel,
    PLANETKA_PT_NavigationSavedLocationsPanel,
    PLANETKA_PT_SunlightPanel,
    PLANETKA_PT_AtmospherePanel,
    PLANETKA_PT_AnimationPanel,
    PLANETKA_PT_SettingsPanel,
    PLANETKA_PT_LinksPanel,
)

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


def register():
    for cls in classes:
        _safe_register_class(cls)
    if not hasattr(bpy.types.Scene, "planetka"):
        bpy.types.Scene.planetka = PointerProperty(type=PlanetkaProperties)

    for scene in _iter_scenes():
        _sync_props_from_idprops(scene)
        migrate_scene(scene)
    _sync_logging_from_scenes()
    ensure_auto_resolve_service_running()

    _remove_load_post_handler()
    bpy.app.handlers.load_post.append(_planetka_load_post)
    _remove_render_handlers()
    bpy.app.handlers.render_pre.append(_planetka_render_pre)
    bpy.app.handlers.render_post.append(_planetka_render_post)
    bpy.app.handlers.render_complete.append(_planetka_render_post)
    bpy.app.handlers.render_cancel.append(_planetka_render_post)


def unregister():
    _remove_load_post_handler()
    _remove_render_handlers()
    stop_auto_resolve_service()
    if hasattr(bpy.types.Scene, "planetka"):
        del bpy.types.Scene.planetka
    for cls in reversed(classes):
        _safe_unregister_class(cls)


if __name__ == "__main__":
    register()
