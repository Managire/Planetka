import logging
import os

import bpy

from .asset_builder import ensure_planetka_root
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object
from .r2_source import resolve_remote_asset
from . import clouds_local as _local


logger = logging.getLogger(__name__)


def _is_global_cloud_object(obj):
    if obj is None or str(getattr(obj, "type", "")) != "MESH":
        return False
    try:
        if str(obj.get(_local.CLOUD_ROLE_KEY, "")) == _local.GLOBAL_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return str(getattr(obj, "name", "")) == _local.GLOBAL_CLOUD_LAYER_NAME


def _apply_global_cloud_texture(material):
    if material is None or not bool(getattr(material, "use_nodes", False)):
        return
    texture_path = ""
    try:
        texture_path = resolve_remote_asset(
            _local.REMOTE_GLOBAL_CLOUDS_FOLDER,
            _local.REMOTE_GLOBAL_CLOUD_TEXTURE_FILE,
        )
    except Exception:
        texture_path = ""
    if not texture_path or not os.path.isfile(texture_path):
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


def apply_global_cloud_object(obj, scene=None):
    if not _is_global_cloud_object(obj):
        return
    scene = scene or getattr(bpy.context, "scene", None)
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
    _apply_global_cloud_texture(material)


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
            try:
                modifiers.remove(modifier)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing global cloud modifier", exc_info=True)

    if scene is not None:
        _clouds, global_clouds, _local_clouds, _vdb_clouds = _local._ensure_cloud_collections(scene)
        _local._set_object_collections(source_obj, [global_clouds])
        root = ensure_planetka_root(scene)
        try:
            if root is not None:
                source_obj.parent = root
                source_obj.matrix_parent_inverse = root.matrix_world.inverted()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed parenting global cloud layer", exc_info=True)

    try:
        source_obj[_local.CLOUD_ROLE_KEY] = _local.GLOBAL_CLOUD_ROLE
        source_obj.hide_viewport = False
        source_obj.hide_render = False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass

    apply_global_cloud_object(source_obj, scene=scene)
    return source_obj


def update_enable_global_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _local._sync_scene_idprops(scene, ("enable_global_clouds",))
    _local._sync_cloud_collection_visibility(scene, self)
    if bool(getattr(self, "enable_global_clouds", True)):
        try:
            ensure_global_cloud_layer(scene=scene)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka clouds: failed ensuring global cloud layer", exc_info=True)


class PLANETKA_PT_GlobalCloudsPanel(bpy.types.Panel):
    bl_label = "Global Clouds"
    bl_idname = "PLANETKA_PT_global_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 6

    @classmethod
    def poll(cls, context):
        return _local._is_workflow_enabled()

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
            text="Disable Global Clouds" if bool(getattr(props, "enable_global_clouds", True)) else "Enable Global Clouds",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_global_clouds", True)):
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
    "ensure_global_cloud_layer",
    "update_enable_global_clouds",
]
