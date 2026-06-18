import logging
import math
import time
import webbrowser

import bpy
from bpy.props import EnumProperty, StringProperty

from .auth import AuthApiError, describe_cloud_session_error, ensure_authenticated_session
from .asset_builder import (
    _ensure_surface_material_library,
    remove_planetka_root_object,
    ensure_surface_collection,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .planetka_ops.earth_lifecycle_helpers import _earth_graph_create_bootstrap_surface
from .state import (
    _sync_idprops_from_props,
    ensure_preview_object,
    logger as state_logger,
    warm_base_sphere_mesh_cache,
)
from .public_shader import prepare_public_sunlight_shader_control, sync_public_surface_displacement_scale


logger = logging.getLogger(__name__)
CREATE_EARTH_STATUS_KEY = "planetka_create_earth_status"
CREATE_EARTH_STATUS_ACTIVE_KEY = "planetka_create_earth_status_active"
PLANETKA_SUNLIGHT_OBJECT_NAME = "Planetka Sunlight"
PLANETKA_SUNLIGHT_DATA_NAME = "Planetka Sunlight"
PLANETKA_SUNLIGHT_LEGACY_OBJECT_NAME = "Planetka sunlight"
PLANETKA_SUNLIGHT_ENERGY = 10.0
PLANETKA_SUNLIGHT_ROTATION_Y = math.radians(90.0)


QUALITY_LEVEL_DESCRIPTIONS = {
    "PREVIEW": "Preview: downloaded textures are 1/4 of the edge size of Full resolution textures, making them 1/16 of the pixel size. Press Resolve Planetka to apply this quality level to the Earth surface.",
    "BALANCED": "Balanced: downloaded textures are 1/2 of the edge size of Full resolution textures, making them 1/4 of the pixel size. Press Resolve Planetka to apply this quality level to the Earth surface.",
    "FULL": "Full: makes sure at least one pixel from the source texture is used for every pixel in the final render if proximity to Earth allows. Press Resolve Planetka to apply this quality level to the Earth surface.",
}

PLANETKA_LINKS = {
    "TUTORIALS": {
        "url": "https://www.youtube.com/@tomasgriger-planetka/videos",
        "description": "Open Planetka tutorial videos in your web browser.",
    },
    "RESOURCES": {
        "url": "https://www.planetka.io",
        "description": "Open Planetka resources in your web browser, including atmosphere, cloud, and related scene elements.",
    },
    "CUSTOM": {
        "url": "",
        "description": "Open this Planetka link in your web browser.",
    },
}


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


def _ensure_planetka_sunlight(scene):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None

    existing = bpy.data.objects.get(PLANETKA_SUNLIGHT_OBJECT_NAME)
    legacy_existing = bpy.data.objects.get(PLANETKA_SUNLIGHT_LEGACY_OBJECT_NAME)
    if existing is None and legacy_existing is not None:
        existing = legacy_existing
    elif existing is not None and legacy_existing is not None and legacy_existing is not existing:
        try:
            bpy.data.objects.remove(legacy_existing, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing duplicate legacy sunlight object", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed removing duplicate legacy sunlight object", exc_info=True)
    if existing is not None and str(getattr(existing, "type", "") or "") != "LIGHT":
        try:
            bpy.data.objects.remove(existing, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed replacing non-light Planetka sunlight object", exc_info=True)
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed replacing non-light Planetka sunlight object", exc_info=True)
            return None
        existing = None

    if existing is None:
        light_data = bpy.data.lights.new(PLANETKA_SUNLIGHT_DATA_NAME, type="SUN")
        light_obj = bpy.data.objects.new(PLANETKA_SUNLIGHT_OBJECT_NAME, light_data)
        target_collection = ensure_surface_collection(scene) or getattr(scene, "collection", None)
        if target_collection is not None:
            target_collection.objects.link(light_obj)
        else:
            scene.collection.objects.link(light_obj)
    else:
        light_obj = existing
        light_data = getattr(light_obj, "data", None)
        if light_data is None or str(getattr(light_data, "type", "") or "") != "SUN":
            light_data = bpy.data.lights.new(PLANETKA_SUNLIGHT_DATA_NAME, type="SUN")
            light_obj.data = light_data

    try:
        light_obj.name = PLANETKA_SUNLIGHT_OBJECT_NAME
        light_obj.data.name = PLANETKA_SUNLIGHT_DATA_NAME
        light_obj.data.type = "SUN"
        light_obj.data.energy = float(PLANETKA_SUNLIGHT_ENERGY)
        light_obj.location = (0.0, 0.0, 0.0)
        light_obj.rotation_euler = (0.0, float(PLANETKA_SUNLIGHT_ROTATION_Y), 0.0)
        light_obj.scale = (1.0, 1.0, 1.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed configuring Planetka sunlight", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed configuring Planetka sunlight", exc_info=True)

    return light_obj


class PLANETKA_OT_PublicSetTextureQuality(bpy.types.Operator):
    bl_idname = "planetka_public.set_texture_quality"
    bl_label = "Set Quality Level"
    bl_description = "Set Planetka Quality Level. Press Resolve Planetka to apply it."

    texture_quality_mode: EnumProperty(
        name="Quality Level",
        items=(
            ("PREVIEW", "Preview", "Downloaded textures are 1/4 of the edge size of Full resolution textures, making them 1/16 of the pixel size"),
            ("BALANCED", "Balanced", "Downloaded textures are 1/2 of the edge size of Full resolution textures, making them 1/4 of the pixel size"),
            ("FULL", "Full", "Makes sure at least one pixel from the source texture is used for every pixel in the final render if proximity to Earth allows"),
        ),
        default="PREVIEW",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        del context
        mode = _normalize_quality_mode(getattr(properties, "texture_quality_mode", "PREVIEW"))
        return QUALITY_LEVEL_DESCRIPTIONS.get(mode, cls.bl_description)

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


class PLANETKA_OT_PublicOpenLink(bpy.types.Operator):
    bl_idname = "planetka_public.open_link"
    bl_label = "Open Planetka Link"
    bl_description = "Open a Planetka web link in your browser"

    link_type: EnumProperty(
        name="Link",
        items=(
            ("TUTORIALS", "Tutorials", PLANETKA_LINKS["TUTORIALS"]["description"]),
            ("RESOURCES", "Resources", PLANETKA_LINKS["RESOURCES"]["description"]),
            ("CUSTOM", "Custom", PLANETKA_LINKS["CUSTOM"]["description"]),
        ),
        default="TUTORIALS",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    url: StringProperty(
        name="URL",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    tooltip: StringProperty(
        name="Tooltip",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        del context
        link_type = str(getattr(properties, "link_type", "TUTORIALS") or "TUTORIALS").upper()
        custom_tooltip = str(getattr(properties, "tooltip", "") or "").strip()
        if custom_tooltip:
            return custom_tooltip
        return str(PLANETKA_LINKS.get(link_type, {}).get("description") or cls.bl_description)

    def execute(self, context):
        del context
        link_type = str(getattr(self, "link_type", "TUTORIALS") or "TUTORIALS").upper()
        url = str(getattr(self, "url", "") or "").strip()
        if not url:
            url = str(PLANETKA_LINKS.get(link_type, {}).get("url") or "").strip()
        if not url:
            return fail(self, "Planetka link is unavailable.", code=ErrorCode.APPLY_FAILED, logger=logger)
        try:
            bpy.ops.wm.url_open(url=url)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            webbrowser.open(url)
        return {'FINISHED'}


class PLANETKA_OT_PublicCreateEarth(bpy.types.Operator):
    bl_idname = "planetka_public.add_earth"
    bl_label = "Create New Earth"
    bl_description = "Create Planetka Earth Surface and Planetka Preview Object, then load initial data for the current camera or active viewport."

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
            remove_planetka_root_object()

            _configure_public_defaults(scene, props)

            _set_create_status(scene, "Preparing Earth mesh...")
            warm_base_sphere_mesh_cache()
            earth = _earth_graph_create_bootstrap_surface(scene)

            _set_create_status(scene, "Creating Earth preview...")
            ensure_preview_object(earth)
            sync_public_surface_displacement_scale(earth, force=True)
            sunlight = _ensure_planetka_sunlight(scene)
            prepare_public_sunlight_shader_control(sunlight)

            _set_create_status(scene, "Resolving preview data...")
            props.texture_quality_mode = "PREVIEW"
            _sync_idprops_from_props(scene, ("texture_quality_mode",))
            result = bpy.ops.planetka_public.load_textures(
                scope_mode="AUTO",
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
    bl_description = "Stream visible Earth texture data for the current camera view or active viewport, then rebuild the Planetka Earth surface at the selected quality level."

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        if get_earth_object() is None:
            return fail(self, "Create Earth first.", code=ErrorCode.PRECHECK_FAILED, logger=logger)
        prepare_public_sunlight_shader_control()
        quality_mode = _normalize_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW"))
        try:
            result = bpy.ops.planetka_public.load_textures(
                scope_mode="AUTO",
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
