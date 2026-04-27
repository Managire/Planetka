import importlib
import logging

import bpy

from ..error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object
from .mesh_lifecycle import ensure_preview_object, remove_object_and_unused_mesh

logger = logging.getLogger(__name__)


def _get_state_module():
    return importlib.import_module("..state", __package__)



def _set_atmosphere_collection_enabled(scene, enabled):
    _ = (scene, enabled)



def _remove_object_and_unused_data_any_type(obj):
    if obj is None:
        return False
    obj_type = str(getattr(obj, "type", "") or "")
    data_block = getattr(obj, "data", None)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return False

    try:
        if data_block is None or int(getattr(data_block, "users", 0)) > 0:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return True

    try:
        if obj_type == "MESH":
            bpy.data.meshes.remove(data_block)
        elif obj_type == "VOLUME" and hasattr(bpy.data, "volumes"):
            bpy.data.volumes.remove(data_block)
        elif obj_type == "LIGHT" and hasattr(bpy.data, "lights"):
            bpy.data.lights.remove(data_block)
        elif obj_type == "CURVE" and hasattr(bpy.data, "curves"):
            bpy.data.curves.remove(data_block)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing data block for %s", getattr(obj, "name", "<unknown>"), exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing data block for %s", getattr(obj, "name", "<unknown>"), exc_info=True)
    return True



def _remove_collection_if_exists(collection_name):
    collection = bpy.data.collections.get(str(collection_name or ""))
    if collection is None:
        return False
    try:
        for parent in list(getattr(bpy.data, "collections", ())):
            try:
                if collection.name in tuple(getattr(parent, "children", ()).keys()):
                    parent.children.unlink(collection)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
        for scene in list(getattr(bpy.data, "scenes", ())):
            root = getattr(scene, "collection", None)
            if root is None:
                continue
            try:
                if collection.name in tuple(getattr(root, "children", ()).keys()):
                    root.children.unlink(collection)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
        bpy.data.collections.remove(collection)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing collection %s", collection_name, exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing collection %s", collection_name, exc_info=True)
    return False



def purge_disabled_atmosphere_and_cloud_assets(scene=None):
    _ = scene
    object_names = {
        "Atmosphere - EEVEE supplement",
        "Atmosphere - Volumetric",
        "Planetka Atmosphere",
        "Planetka Atmosphere Fake",
        "Planetka Global Cloud Layer",
        "Planetka Cloud VDB",
    }
    object_prefixes = (
        "Local Cloud No ",
        "VDB Cloud No ",
        "Planetka Local Cloud Cap Mesh",
    )
    collection_names = {
        "Atmosphere",
        "Atmpshere",
        "Clouds",
        "Global Clouds",
        "Local Clouds",
        "VDB Clouds",
    }
    material_exact = {
        "Planetka Atmosphere Fake Material",
        "Planetka Atmosphere Material",
        "Planetka Global Clouds Shader",
        "Planetka Local Clouds Shader",
        "Planetka VDB Cloud Shader",
    }
    material_prefixes = (
        "Planetka Local Clouds Shader",
        "Planetka VDB Cloud Shader",
    )
    node_group_exact = {
        "Planetka Atmosphere Group",
        "Planetka Atmosphere Fake Group",
        "Planetka Fake Atmosphere Textures Group",
        "Planetka Global Clouds Shader Group",
        "Planetka Local Clouds Shader Group",
        "Cloud Preview Switch",
    }

    try:
        asset_builder_module = importlib.import_module("..asset_builder", __package__)
        for attr in (
            "FAKE_ATMOSPHERE_OBJECT_NAME",
            "FAKE_ATMOSPHERE_SOURCE_OBJECT_NAME",
            "VOLUMETRIC_ATMOSPHERE_OBJECT_NAME",
            "VOLUMETRIC_ATMOSPHERE_SOURCE_OBJECT_NAME",
        ):
            value = str(getattr(asset_builder_module, attr, "") or "").strip()
            if value:
                object_names.add(value)
        for attr in (
            "FAKE_ATMOSPHERE_COLLECTION_NAME",
            "_LEGACY_FAKE_ATMOSPHERE_COLLECTION_NAMES",
        ):
            value = getattr(asset_builder_module, attr, None)
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    text = str(item or "").strip()
                    if text:
                        collection_names.add(text)
            else:
                text = str(value or "").strip()
                if text:
                    collection_names.add(text)
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        pass

    try:
        clouds_module = importlib.import_module("..clouds_local", __package__)
        for attr in (
            "CLOUDS_ROOT_COLLECTION_NAME",
            "GLOBAL_CLOUDS_COLLECTION_NAME",
            "LOCAL_CLOUDS_COLLECTION_NAME",
            "VDB_CLOUDS_COLLECTION_NAME",
            "GLOBAL_CLOUD_LAYER_NAME",
            "VDB_CLOUD_TEMPLATE_OBJECT_NAME",
        ):
            text = str(getattr(clouds_module, attr, "") or "").strip()
            if not text:
                continue
            if "COLLECTION" in attr:
                collection_names.add(text)
            else:
                object_names.add(text)
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        pass

    removed_objects = 0
    removed_collections = 0
    removed_materials = 0
    removed_node_groups = 0

    for obj in list(getattr(bpy.data, "objects", ())):
        name = str(getattr(obj, "name", "") or "")
        role = str(obj.get("planetka_role", "") or "")
        cloud_role = str(obj.get("planetka_cloud_role", "") or "")
        should_remove = (
            name in object_names
            or any(name.startswith(prefix) for prefix in object_prefixes)
            or role in {"fake_atmosphere", "atmosphere_volumetric"}
            or bool(cloud_role)
        )
        if not should_remove:
            continue
        if _remove_object_and_unused_data_any_type(obj):
            removed_objects += 1

    for name in sorted(collection_names):
        if _remove_collection_if_exists(name):
            removed_collections += 1

    for material in list(getattr(bpy.data, "materials", ())):
        name = str(getattr(material, "name", "") or "")
        if not (name in material_exact or any(name.startswith(prefix) for prefix in material_prefixes)):
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
                removed_materials += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing atmosphere/cloud material %s", name, exc_info=True)

    for group in list(getattr(bpy.data, "node_groups", ())):
        name = str(getattr(group, "name", "") or "")
        if name not in node_group_exact:
            continue
        try:
            if int(getattr(group, "users", 0)) == 0:
                bpy.data.node_groups.remove(group)
                removed_node_groups += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing atmosphere/cloud node group %s", name, exc_info=True)

    return {
        "objects": int(removed_objects),
        "collections": int(removed_collections),
        "materials": int(removed_materials),
        "node_groups": int(removed_node_groups),
    }



def _remove_preview_assets():
    preview_obj = bpy.data.objects.get("Planetka Preview Object")
    if preview_obj is not None:
        remove_object_and_unused_mesh(preview_obj)

    for mat_name in ("Planetka Preview Material", "Planetka Preview Shader"):
        material = bpy.data.materials.get(mat_name)
        if material is None:
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing preview material %s", mat_name, exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed removing preview material %s", mat_name, exc_info=True)



def update_show_earth_preview(self, context):
    state_module = _get_state_module()
    if bool(getattr(state_module, "_IDPROP_SYNCING", False)):
        return
    scene = getattr(context, "scene", None) if context else None
    if scene:
        state_module._sync_idprops_from_props(scene, ("show_earth_preview",))

    show_preview = bool(getattr(self, "show_earth_preview", False))
    if show_preview:
        earth = get_earth_object()
        if earth is not None:
            try:
                ensure_preview_object(earth)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed enabling preview object", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed enabling preview object", exc_info=True)
    else:
        _remove_preview_assets()



def update_atmosphere_enabled(self, context):
    state_module = _get_state_module()
    scene = getattr(context, "scene", None) if context else None
    if scene:
        state_module._sync_idprops_from_props(scene, ("atmosphere_enabled",))
    _set_atmosphere_collection_enabled(
        scene,
        bool(getattr(self, "atmosphere_enabled", True)),
    )
