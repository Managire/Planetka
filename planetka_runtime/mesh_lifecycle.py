"""Mesh and datablock lifecycle helpers used by runtime and operators."""

import logging
import bpy

from ..extension_prefs import get_earth_object
from ..mesh_utils import (
    SURFACE_COLLECTION_NAME,
    create_temp_mesh_for_all_tiles,
    ensure_base_sphere_mesh_cache,
    ensure_preview_object as ensure_preview_object_impl,
)
from ..shader_utils import main as replace_tiles_impl
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)


def create_temp_mesh(tiles, name="Planetka Earth Surface", collection_policy="preserve_surface"):
    return create_temp_mesh_for_all_tiles(
        tiles,
        name=name,
        collection_policy=collection_policy,
    )


def warm_base_sphere_mesh_cache():
    return ensure_base_sphere_mesh_cache()


def ensure_preview_object(parent_surface):
    return ensure_preview_object_impl(parent_surface)


def replace_tiles(
    tiles,
    material_name="Planetka Earth Material",
    force_remove_unused=False,
    resolved_paths=None,
    resolved_tiles_override=None,
    ocean_tiles_override=None,
):
    return replace_tiles_impl(
        tiles,
        material_name=material_name,
        force_remove_datablocks=force_remove_unused,
        resolved_paths=resolved_paths,
        resolved_tiles_override=resolved_tiles_override,
        ocean_tiles_override=ocean_tiles_override,
    )


def remove_object_and_unused_mesh(obj):
    if obj is None:
        return
    mesh_data = getattr(obj, "data", None) if getattr(obj, "type", None) == 'MESH' else None
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return

    if mesh_data is None:
        return
    try:
        if int(getattr(mesh_data, "users", 0)) == 0:
            bpy.data.meshes.remove(mesh_data)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing unused mesh data", exc_info=True)


def _is_planetka_runtime_name(name):
    try:
        text = str(name or "")
    except (TypeError, ValueError):
        return False
    return text.startswith("Planetka") and (not text.startswith("PlanetkaStandalone"))


def delete_temp_meshes(keep_obj=None):
    for obj in list(getattr(bpy.data, "objects", ())):
        if obj is keep_obj:
            continue
        if obj.name.startswith("Earth Surface") or obj.name.startswith("Planetka Earth Surface"):
            remove_object_and_unused_mesh(obj)


def ensure_planetka_temp_collection():
    try:
        scene = getattr(getattr(bpy, "context", None), "scene", None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed accessing context scene for temp collection", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed accessing context scene for temp collection", exc_info=True)
        return None
    if scene is None:
        return None
    root = scene.collection
    surface_collection = bpy.data.collections.get(SURFACE_COLLECTION_NAME)
    if surface_collection is None:
        surface_collection = bpy.data.collections.new(SURFACE_COLLECTION_NAME)
        root.children.link(surface_collection)
    elif SURFACE_COLLECTION_NAME not in root.children:
        try:
            root.children.link(surface_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
    return surface_collection


def cleanup_planetka_unused_data():
    counts = {
        "objects": 0,
        "meshes": 0,
        "images": 0,
        "materials": 0,
        "node_groups": 0,
    }

    keep_surface = get_earth_object()
    keep_preview = bpy.data.objects.get("Planetka Preview Object")
    for obj in list(getattr(bpy.data, "objects", ())):
        if obj in (keep_surface, keep_preview):
            continue
        name = str(getattr(obj, "name", ""))
        if not (
            name.startswith("Planetka Earth Surface")
            or name.startswith("Earth Surface")
            or name.startswith("Planetka Preview Object")
        ):
            continue
        remove_object_and_unused_mesh(obj)
        counts["objects"] += 1

    for mesh_data in list(getattr(bpy.data, "meshes", ())):
        name = str(getattr(mesh_data, "name", ""))
        if not (
            _is_planetka_runtime_name(name)
            or name.startswith("Earth Surface")
        ):
            continue
        try:
            if int(getattr(mesh_data, "users", 0)) == 0:
                bpy.data.meshes.remove(mesh_data)
                counts["meshes"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing mesh %s", name, exc_info=True)

    image_prefixes = ("S2_", "EL_", "WT_", "PO_")
    for image in list(getattr(bpy.data, "images", ())):
        name = str(getattr(image, "name", ""))
        filepath = str(getattr(image, "filepath", "")).lower()
        name_lower = name.lower()
        looks_planetka = (
            name.startswith(image_prefixes)
            or ("planetka" in name_lower and "planetkastandalone" not in name_lower)
            or "/s2/" in filepath
            or "/el/" in filepath
            or "/wt/" in filepath
            or "/po/" in filepath
            or "fallback images" in filepath
        )
        if not looks_planetka:
            continue
        try:
            if int(getattr(image, "users", 0)) == 0:
                bpy.data.images.remove(image)
                counts["images"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing image %s", name, exc_info=True)

    for material in list(getattr(bpy.data, "materials", ())):
        name = str(getattr(material, "name", ""))
        if not _is_planetka_runtime_name(name):
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
                counts["materials"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing material %s", name, exc_info=True)

    for node_group in list(getattr(bpy.data, "node_groups", ())):
        name = str(getattr(node_group, "name", ""))
        if not _is_planetka_runtime_name(name):
            continue
        try:
            if int(getattr(node_group, "users", 0)) == 0:
                bpy.data.node_groups.remove(node_group)
                counts["node_groups"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing node group %s", name, exc_info=True)

    return counts
