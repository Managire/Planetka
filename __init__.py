import logging

import bpy
from bpy.props import PointerProperty

from .auth import local_addon_edition_code
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import PlanetkaExtensionPreferences
from .properties import PlanetkaProperties
from .public_operators import (
    PLANETKA_OT_PublicCreateEarth,
    PLANETKA_OT_PublicResolvePlanetka,
    PLANETKA_OT_PublicSetTextureQuality,
)
from .public_ui import PLANETKA_PT_PublicAnimationPanel, PLANETKA_PT_PublicMainPanel
from .public_validation import PLANETKA_OT_PublicSceneHealthCheck
from .render_prep import PLANETKA_OT_LoadTextures
from .state import stop_resolve


bl_info = {
    "name": "Planetka",
    "author": "Tomas Griger",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Planetka",
    "description": "DIY Earth texture streaming for Blender",
    "category": "3D View",
}


logger = logging.getLogger(__name__)
_PRO_EDITION = local_addon_edition_code() == "pro"
mark_render_job_progress = None
mark_render_job_started = None
recover_post_render_state = None


base_classes = (
    PlanetkaExtensionPreferences,
    PlanetkaProperties,
    PLANETKA_OT_PublicSetTextureQuality,
    PLANETKA_OT_PublicCreateEarth,
    PLANETKA_OT_PublicResolvePlanetka,
    PLANETKA_OT_LoadTextures,
    PLANETKA_OT_PublicSceneHealthCheck,
    PLANETKA_PT_PublicMainPanel,
)

pro_classes = ()
if _PRO_EDITION:
    from .animation_tools import (
        PLANETKA_OT_AnimationClearPrepared,
        PLANETKA_OT_AnimationMakeReady,
        PLANETKA_OT_AnimationPreviewShot,
        PLANETKA_OT_AnimationRender,
        PLANETKA_OT_AnimationStop,
    )
    from .state import (
        mark_render_job_progress,
        mark_render_job_started,
        recover_post_render_state,
    )

    pro_classes = (
        PLANETKA_OT_AnimationPreviewShot,
        PLANETKA_OT_AnimationMakeReady,
        PLANETKA_OT_AnimationClearPrepared,
        PLANETKA_OT_AnimationRender,
        PLANETKA_OT_AnimationStop,
        PLANETKA_PT_PublicAnimationPanel,
    )

classes = base_classes + pro_classes


def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        if "already registered as a subclass" in str(exc):
            _safe_unregister_class(cls)
            bpy.utils.register_class(cls)
            return
        raise


def _is_readonly_state_error(exc):
    message = str(exc or "").strip().lower()
    return bool(message) and any(
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
        if "missing bl_rna" in message or "not registered" in message or _is_readonly_state_error(exc):
            return
        raise


def _planetka_render_pre(scene):
    if _PRO_EDITION:
        mark_render_job_started(scene)


def _planetka_render_post(scene, *args):
    del args
    if _PRO_EDITION:
        mark_render_job_progress(scene, frame_written=False)


def _planetka_render_write(scene, *args):
    del args
    if _PRO_EDITION:
        mark_render_job_progress(scene, frame_written=True)


def _planetka_render_complete(scene):
    if _PRO_EDITION:
        recover_post_render_state(scene, cancelled=False)


def _planetka_render_cancel(scene):
    if _PRO_EDITION:
        recover_post_render_state(scene, cancelled=True)


def _planetka_shutdown_cleanup(*_args):
    try:
        stop_resolve()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping resolve during shutdown", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed stopping resolve during shutdown", exc_info=True)
    try:
        if _PRO_EDITION:
            recover_post_render_state(None, cancelled=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing render state during shutdown", exc_info=True)


def _remove_handler(handler_list, fn):
    for handler in list(handler_list):
        if handler is fn or getattr(handler, "__name__", "") == getattr(fn, "__name__", ""):
            handler_list.remove(handler)


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
        for fn in (
            _planetka_render_pre,
            _planetka_render_post,
            _planetka_render_write,
            _planetka_render_complete,
            _planetka_render_cancel,
        ):
            _remove_handler(handler_list, fn)


def _remove_quit_pre_handler():
    handlers = getattr(bpy.app.handlers, "quit_pre", None)
    if handlers is not None:
        _remove_handler(handlers, _planetka_shutdown_cleanup)


def register():
    for cls in classes:
        _safe_unregister_class(cls)
        _safe_register_class(cls)
    if not hasattr(bpy.types.Scene, "planetka_public"):
        bpy.types.Scene.planetka_public = PointerProperty(type=PlanetkaProperties)
    try:
        from .auth import _ensure_cloud_install_id
        _ensure_cloud_install_id()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed initializing install id", exc_info=True)

    if _PRO_EDITION:
        _remove_render_handlers()
        bpy.app.handlers.render_pre.append(_planetka_render_pre)
        bpy.app.handlers.render_post.append(_planetka_render_post)
        render_write_handlers = getattr(bpy.app.handlers, "render_write", None)
        if render_write_handlers is not None:
            render_write_handlers.append(_planetka_render_write)
        bpy.app.handlers.render_complete.append(_planetka_render_complete)
        bpy.app.handlers.render_cancel.append(_planetka_render_cancel)
        _remove_quit_pre_handler()
        quit_pre_handlers = getattr(bpy.app.handlers, "quit_pre", None)
        if quit_pre_handlers is not None:
            quit_pre_handlers.append(_planetka_shutdown_cleanup)


def unregister():
    try:
        stop_resolve()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping resolve during unregister", exc_info=True)
    _remove_render_handlers()
    _remove_quit_pre_handler()
    if hasattr(bpy.types.Scene, "planetka_public"):
        try:
            del bpy.types.Scene.planetka_public
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if not _is_readonly_state_error(exc):
                raise
    for cls in reversed(classes):
        try:
            _safe_unregister_class(cls)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if not _is_readonly_state_error(exc):
                raise


if __name__ == "__main__":
    register()
