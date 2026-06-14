import logging
import time

import bpy
from bpy.props import EnumProperty

from .auth import AuthApiError, describe_cloud_session_error, ensure_authenticated_session
from .asset_builder import (
    _ensure_surface_material_library,
    ensure_planetka_root,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .planetka_ops.earth_lifecycle_helpers import _earth_graph_create_bootstrap_surface, _earth_graph_rebind
from .state import (
    _sync_idprops_from_props,
    ensure_preview_object,
    logger as state_logger,
    warm_base_sphere_mesh_cache,
)
from .public_shader import prepare_public_sunlight_shader_control


logger = logging.getLogger(__name__)
CREATE_EARTH_STATUS_KEY = "planetka_create_earth_status"
CREATE_EARTH_STATUS_ACTIVE_KEY = "planetka_create_earth_status_active"


def _normalize_quality_mode(value):
    text = str(value or "").strip().upper()
    if text in {"BALANCED", "FULL"}:
        return text
    return "PREVIEW"


def _set_create_status(scene, message, active=True):
    if scene is None:
        return
    try:
        scene[CREATE_EARTH_STATUS_KEY] = str(message or "").strip()
        scene[CREATE_EARTH_STATUS_ACTIVE_KEY] = bool(active)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    try:
        for area in tuple(getattr(getattr(bpy.context, "screen", None), "areas", ()) or ()):
            area.tag_redraw()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass


def _configure_public_defaults(scene, props):
    if scene is None or props is None:
        return
    for name, value in (
        ("texture_quality_mode", "PREVIEW"),
        ("show_earth_preview", True),
        ("lock_resolve_during_animation", True),
    ):
        if hasattr(props, name):
            try:
                setattr(props, name, value)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed setting public default %s", name, exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed setting public default %s", name, exc_info=True)
    try:
        _sync_idprops_from_props(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed syncing public defaults", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed syncing public defaults", exc_info=True)


class PLANETKA_OT_PublicSetTextureQuality(bpy.types.Operator):
    bl_idname = "planetka_public.set_texture_quality"
    bl_label = "Set Quality Level"
    bl_description = "Set Planetka Quality Level. Press Resolve Planetka to apply it."

    texture_quality_mode: EnumProperty(
        name="Quality Level",
        items=(
            ("PREVIEW", "Preview", "Fastest lower-resolution streaming textures"),
            ("BALANCED", "Balanced", "Medium-resolution streaming textures"),
            ("FULL", "Full", "Highest available streaming textures for this edition"),
        ),
        default="PREVIEW",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        try:
            props.texture_quality_mode = _normalize_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                "Quality level could not be changed.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
            )
        return {'FINISHED'}


class PLANETKA_OT_PublicCreateEarth(bpy.types.Operator):
    bl_idname = "planetka_public.add_earth"
    bl_label = "Create New Earth"
    bl_description = "Create the Planetka Earth surface, root, and preview objects"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        existing = get_earth_object()
        if existing is not None:
            _set_create_status(scene, "Planetka Earth already exists.", active=False)
            self.report({'INFO'}, "Planetka Earth already exists.")
            return {'CANCELLED'}

        prefs = get_prefs()
        if prefs is None:
            _set_create_status(scene, "Planetka preferences unavailable.", active=False)
            return fail(self, "Planetka preferences unavailable.", code=ErrorCode.RESOLVE_PREFS_MISSING, logger=logger)

        try:
            _set_create_status(scene, "Connecting to Planetka Cloud...")
            ensure_authenticated_session(prefs)
        except AuthApiError as exc:
            message = describe_cloud_session_error(exc)
            _set_create_status(scene, message, active=False)
            return fail(self, message, code=ErrorCode.RESOLVE_PREFS_MISSING, logger=logger)

        started = time.perf_counter()
        try:
            _set_create_status(scene, "Loading Planetka surface shader...")
            _ensure_surface_material_library(scene)

            _set_create_status(scene, "Creating Planetka Root...")
            ensure_planetka_root(scene)
            _configure_public_defaults(scene, props)

            _set_create_status(scene, "Preparing Earth mesh...")
            warm_base_sphere_mesh_cache()
            earth = _earth_graph_create_bootstrap_surface(scene)
            _earth_graph_rebind(scene=scene, earth_surface=earth)

            _set_create_status(scene, "Creating Earth preview...")
            ensure_preview_object(earth)
            prepare_public_sunlight_shader_control()

            _set_create_status(scene, "Resolving preview data...")
            props.texture_quality_mode = "PREVIEW"
            _sync_idprops_from_props(scene, ("texture_quality_mode",))
            result = bpy.ops.planetka_public.load_textures(
                scope_mode="CAMERA",
                defer_download=True,
                tiles_override_json="",
                texture_quality_mode_override="PREVIEW",
            )
            if "FINISHED" not in set(result):
                raise RuntimeError("Preview resolve did not start.")
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            _set_create_status(scene, "Create Earth failed.", active=False)
            return fail(
                self,
                f"Create Earth failed: {exc}",
                code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
                logger=state_logger,
                exc=exc,
            )
        except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
            _set_create_status(scene, "Create Earth failed.", active=False)
            return fail(
                self,
                f"Create Earth failed: {exc}",
                code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
                logger=state_logger,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info("Planetka public Create Earth completed in %.1f ms", elapsed_ms)
        _set_create_status(scene, "", active=False)
        return {'FINISHED'}


class PLANETKA_OT_PublicResolvePlanetka(bpy.types.Operator):
    bl_idname = "planetka_public.resolve_planetka"
    bl_label = "Resolve Planetka"
    bl_description = "Resolve Planetka for the current active scene camera and selected quality level"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        if get_earth_object() is None:
            return fail(self, "Create Earth first.", code=ErrorCode.PRECHECK_FAILED, logger=logger)
        camera = getattr(scene, "camera", None)
        if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
            return fail(
                self,
                "Set an active scene camera, then press Resolve Planetka again.",
                code=ErrorCode.PRECHECK_FAILED,
                logger=logger,
            )
        prepare_public_sunlight_shader_control()
        quality_mode = _normalize_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW"))
        try:
            result = bpy.ops.planetka_public.load_textures(
                scope_mode="CAMERA",
                defer_download=True,
                tiles_override_json="",
                texture_quality_mode_override=quality_mode,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                "Resolve Planetka failed. Please retry.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
            )
        except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
            return fail(
                self,
                f"Resolve Planetka failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        return {'FINISHED'} if "FINISHED" in set(result) else {'CANCELLED'}
