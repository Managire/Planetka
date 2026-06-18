import bpy

from ..asset_builder import ensure_earth_surface_unparented
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import mark_earth_object
from ..state import delete_temp_meshes, ensure_planetka_temp_collection, logger


def _earth_graph_rebind(scene, earth_surface):
    if scene is None or earth_surface is None:
        return False
    try:
        ensure_earth_surface_unparented(scene=scene, earth_surface=earth_surface)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed preparing unparented Earth surface", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed preparing unparented Earth surface", exc_info=True)
    return False


def _create_placeholder_surface_object(scene):
    placeholder_mesh = bpy.data.meshes.new("Planetka Earth Surface Placeholder Mesh")
    obj = bpy.data.objects.new("Planetka Earth Surface", placeholder_mesh)
    scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj["planetka_surface_local_radius"] = 2.0
    material = bpy.data.materials.get("Planetka Earth Material")
    if material is not None:
        try:
            obj.data.materials.clear()
            obj.data.materials.append(material)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed assigning Earth material to bootstrap surface", exc_info=True)
    return obj


def _earth_graph_create_bootstrap_surface(scene):
    surface_collection = ensure_planetka_temp_collection()
    new_obj = _create_placeholder_surface_object(scene)
    if new_obj is None:
        raise RuntimeError("Failed to create bootstrap Earth surface mesh")
    if surface_collection is not None:
        for collection in list(new_obj.users_collection):
            if collection is surface_collection:
                continue
            collection.objects.unlink(new_obj)
        if new_obj.name not in surface_collection.objects:
            surface_collection.objects.link(new_obj)
    delete_temp_meshes(keep_obj=new_obj)
    try:
        new_obj.name = "Planetka Earth Surface"
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    mark_earth_object(new_obj)
    _earth_graph_rebind(scene=scene, earth_surface=new_obj)
    return new_obj
