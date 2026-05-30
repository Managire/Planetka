import logging
import os

import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object
from . import clouds_local as _local


logger = logging.getLogger(__name__)
_RECOVERABLE_LOG_COUNTS = {}
BUNDLED_GLOBAL_CLOUD_TEXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "Resources",
    "Clouds Global",
    _local.REMOTE_GLOBAL_CLOUD_TEXTURE_FILE,
)


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _is_global_cloud_object(obj):
    if obj is None or str(getattr(obj, "type", "")) != "MESH":
        return False
    try:
        if str(obj.get(_local.CLOUD_ROLE_KEY, "")) == _local.GLOBAL_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDG-001", "Failed reading global-cloud role custom property")
    return str(getattr(obj, "name", "")) == _local.GLOBAL_CLOUD_LAYER_NAME


def _safe_existing_file(path):
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    safe_path = os.path.abspath(os.path.expanduser(raw_path))
    try:
        if os.path.isfile(safe_path) and int(os.path.getsize(safe_path)) > 0:
            return safe_path
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return ""
    return ""


def _resolve_global_cloud_texture_path(scene=None):
    props = getattr(scene, "planetka", None) if scene else None
    source = str(getattr(props, "global_cloud_texture_source", "CLOUD") or "CLOUD").strip().upper()
    if source == "LOCAL":
        return _safe_existing_file(getattr(props, "global_cloud_local_file", ""))

    bundled_path = _safe_existing_file(BUNDLED_GLOBAL_CLOUD_TEXTURE_PATH)
    if bundled_path:
        return bundled_path

    texture_path = ""
    try:
        texture_path = _local._download_public_cloud_asset(
            _local.REMOTE_GLOBAL_CLOUDS_FOLDER,
            _local.REMOTE_GLOBAL_CLOUD_TEXTURE_FILE,
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed resolving global cloud texture", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka clouds: failed resolving global cloud texture", exc_info=True)

    return _safe_existing_file(texture_path)


def _apply_global_cloud_texture(material, scene=None):
    if material is None or getattr(material, "node_tree", None) is None:
        return
    texture_path = _resolve_global_cloud_texture_path(scene=scene)
    if not texture_path:
        return

    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return
    node = node_tree.nodes.get(_local.GLOBAL_CLOUD_IMAGE_NODE_NAME)
    if node is None or str(getattr(node, "type", "")) != "TEX_IMAGE":
        node = next((candidate for candidate in node_tree.nodes if str(getattr(candidate, "type", "")) == "TEX_IMAGE"), None)
    if node is None:
        return
    try:
        image = bpy.data.images.load(texture_path, check_existing=True)
        image.colorspace_settings.name = "Non-Color"
        node.image = image
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed assigning merged global cloud texture", exc_info=True)


def _global_cloud_final_look_enabled(scene=None):
    props = getattr(scene, "planetka", None) if scene else None
    try:
        return str(getattr(props, "cloud_view_mode", "PREVIEW") or "PREVIEW").strip().upper() == "FINAL"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _ensure_global_cloud_subdivision_modifier(obj):
    if obj is None:
        return None
    modifier = None
    for candidate in getattr(obj, "modifiers", ()):
        if str(getattr(candidate, "type", "")) == "SUBSURF":
            modifier = candidate
            break
    if modifier is None:
        try:
            modifier = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating global cloud subdivision modifier", exc_info=True)
            return None
    try:
        modifier.levels = max(1, int(getattr(modifier, "levels", 1)))
        modifier.render_levels = max(1, int(getattr(modifier, "render_levels", 1)))
        modifier.show_render = True
        if hasattr(modifier, "use_adaptive_subdivision"):
            modifier.use_adaptive_subdivision = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed configuring global cloud subdivision modifier", exc_info=True)
    return modifier


def apply_global_cloud_subdivision_viewport_state(scene=None, final_look=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if final_look is None:
        final_look = _global_cloud_final_look_enabled(scene=scene)
    final_look = bool(final_look)
    changed = 0
    for obj in tuple(bpy.data.objects):
        if not _is_global_cloud_object(obj):
            continue
        modifier = _ensure_global_cloud_subdivision_modifier(obj)
        if modifier is None:
            continue
        try:
            modifier.show_viewport = final_look
            changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed setting global cloud subdivision viewport state", exc_info=True)
    return changed


def _refresh_global_cloud_displacement_material(material):
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    if node_tree is None:
        return False
    changed = False
    for node in tuple(getattr(node_tree, "nodes", ())):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        group = getattr(node, "node_tree", None)
        group_name = str(getattr(group, "name", "") or "")
        if group_name != _local.CLOUD_MATERIAL_GROUP_NAME:
            continue
        for socket_name in ("Displacement (Bump) Scale Coefficient",):
            socket = node.inputs.get(socket_name)
            if socket is None or not hasattr(socket, "default_value"):
                continue
            try:
                socket.default_value = socket.default_value
                changed = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed refreshing global cloud displacement socket", exc_info=True)
    try:
        node_tree.update_tag()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed tagging global cloud material node tree for update", exc_info=True)
    try:
        material.update_tag()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed tagging global cloud material for update", exc_info=True)
    return changed


def apply_global_cloud_object(obj, scene=None):
    if not _is_global_cloud_object(obj):
        return
    scene = scene or getattr(bpy.context, "scene", None)
    _local._ensure_cloud_parented_to_root(obj, scene=scene)
    earth = get_earth_object()
    if earth is None:
        return

    earth_radius = max(1e-6, float(_local._earth_radius_blender_units(earth)))
    mesh_radius = max(1e-6, float(_local._mesh_local_radius(obj) or 0.0))
    target_radius = earth_radius * float(_local.GLOBAL_CLOUD_RELATIVE_SCALE)
    scale_value = target_radius / mesh_radius

    try:
        obj.location = (0.0, 0.0, 0.0)
        obj.scale = (scale_value, scale_value, scale_value)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating global cloud transform", exc_info=True)

    mesh = getattr(obj, "data", None)
    if mesh is not None and hasattr(mesh, "polygons"):
        try:
            for polygon in mesh.polygons:
                polygon.use_smooth = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed smoothing global cloud mesh", exc_info=True)

    material = _local._resolve_object_material(obj)
    _apply_global_cloud_texture(material, scene=scene)
    _refresh_global_cloud_displacement_material(material)
    try:
        obj.update_tag(refresh={'OBJECT', 'DATA'})
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed tagging global cloud object after radius update", exc_info=True)
    try:
        view_layer = getattr(getattr(bpy, "context", None), "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed updating view layer after global cloud radius update", exc_info=True)
    apply_global_cloud_subdivision_viewport_state(scene=scene)


def ensure_global_cloud_layer(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    earth = get_earth_object()
    if earth is None:
        return None

    source_obj = bpy.data.objects.get(_local.GLOBAL_CLOUD_LAYER_NAME)
    if not _is_global_cloud_object(source_obj):
        source_obj = next((obj for obj in bpy.data.objects if _is_global_cloud_object(obj)), None)

    if source_obj is None:
        _local._append_from_reference(
            object_names=(_local.GLOBAL_CLOUD_LAYER_NAME,),
            material_names=(_local.GLOBAL_CLOUD_MATERIAL_NAME,),
            blend_path=_local.GLOBAL_CLOUD_REFERENCE_BLEND_PATH,
        )
        source_obj = bpy.data.objects.get(_local.GLOBAL_CLOUD_LAYER_NAME)

    if source_obj is None:
        raise RuntimeError(f"Global cloud object '{_local.GLOBAL_CLOUD_LAYER_NAME}' not found in reference blend.")

    _local._clear_cloud_drivers(source_obj)
    _local._remove_cloud_cull_modifiers(source_obj)
    modifiers = getattr(source_obj, "modifiers", None)
    if modifiers:
        for modifier in list(modifiers):
            if str(getattr(modifier, "type", "")) == "SUBSURF":
                continue
            try:
                modifiers.remove(modifier)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing global cloud modifier", exc_info=True)

    if scene is not None:
        _clouds, global_clouds, _local_clouds, _vdb_clouds = _local._ensure_cloud_collections(scene)
        _local._set_object_collections(source_obj, [global_clouds])
        _local._ensure_cloud_parented_to_root(source_obj, scene=scene)

    try:
        source_obj[_local.CLOUD_ROLE_KEY] = _local.GLOBAL_CLOUD_ROLE
        source_obj.hide_viewport = False
        source_obj.hide_render = False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDG-002", "Failed setting global cloud role/visibility flags")

    apply_global_cloud_object(source_obj, scene=scene)
    return source_obj


def update_enable_global_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _local._sync_scene_idprops(
        scene,
        (
            "enable_global_clouds",
            "global_cloud_texture_source",
            "global_cloud_folder",
            "global_cloud_local_file",
        ),
    )
    _local._sync_cloud_collection_visibility(scene, self)
    if bool(getattr(self, "enable_global_clouds", False)):
        try:
            ensure_global_cloud_layer(scene=scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed ensuring global cloud layer", exc_info=True)


class PLANETKA_PT_GlobalCloudsPanel(bpy.types.Panel):
    bl_label = "Global Clouds"
    bl_idname = "PLANETKA_PT_global_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9006

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.use_property_split = False
        row.prop(
            props,
            "enable_global_clouds",
            text="Disable Global Clouds" if bool(getattr(props, "enable_global_clouds", False)) else "Enable Global Clouds",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_global_clouds", False)):
            return

        obj = bpy.data.objects.get(_local.GLOBAL_CLOUD_LAYER_NAME)
        if obj is None:
            layout.label(text="Global cloud layer will appear after Create Earth.", icon="INFO")
            return

        row = layout.row()
        row.use_property_split = False
        row.prop(
            obj,
            "hide_viewport",
            text="Show in Viewport" if bool(getattr(obj, "hide_viewport", False)) else "Hide in Viewport",
            toggle=True,
            icon="HIDE_OFF",
        )
        layout.label(text="Static 16K cloud coverage map", icon="TEXTURE")


__all__ = [
    "PLANETKA_PT_GlobalCloudsPanel",
    "apply_global_cloud_object",
    "apply_global_cloud_subdivision_viewport_state",
    "ensure_global_cloud_layer",
    "_resolve_global_cloud_texture_path",
    "update_enable_global_clouds",
]
