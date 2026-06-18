import logging

import bpy

from .asset_builder import EARTH_MATERIAL_NAME, PREVIEW_MATERIAL_NAME, SURFACE_GRADING_GROUP_NAME
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

SURFACE_ELEVATION_SCALE_NODE_NAME = "Math.011"
SURFACE_ELEVATION_SCALE_DEFAULT = 0.024
SURFACE_ELEVATION_REFERENCE_RADIUS = 2.0
EARTH_SURFACE_OBJECT_NAME = "Planetka Earth Surface"
SUNLIGHT_TEXTURE_COORD_NODE_NAME = "Select Sunlight Source Object Here"
SUNLIGHT_VECTOR_SOCKET_NAME = "SunLight Object"
SURFACE_MATERIAL_NAMES = (EARTH_MATERIAL_NAME, PREVIEW_MATERIAL_NAME)
_LAST_DISPLACEMENT_SCALE_SIGNATURE = None


def _iter_group_nodes(group_name):
    prefix = str(group_name or "").strip()
    if not prefix:
        return
    for node_group in tuple(getattr(bpy.data, "node_groups", ()) or ()):
        name = str(getattr(node_group, "name", "") or "")
        if name == prefix or name.startswith(f"{prefix}."):
            yield node_group


def prepare_public_sunlight_shader_control(sunlight_object=None):
    """Bind the material-level sunlight coordinate node used by the locked v1 shader."""
    changed = False
    for material_name in SURFACE_MATERIAL_NAMES:
        material = bpy.data.materials.get(material_name)
        node_tree = getattr(material, "node_tree", None)
        nodes = getattr(node_tree, "nodes", None)
        links = getattr(node_tree, "links", None)
        if nodes is None:
            continue

        node = nodes.get(SUNLIGHT_TEXTURE_COORD_NODE_NAME) if hasattr(nodes, "get") else None
        if node is None or str(getattr(node, "bl_idname", "")) != "ShaderNodeTexCoord":
            node = next(
                (
                    candidate
                    for candidate in nodes
                    if str(getattr(candidate, "bl_idname", "")) == "ShaderNodeTexCoord"
                    and str(getattr(candidate, "label", "") or "") == SUNLIGHT_TEXTURE_COORD_NODE_NAME
                ),
                None,
            )
        if node is None or str(getattr(node, "bl_idname", "")) != "ShaderNodeTexCoord":
            continue

        try:
            node.label = SUNLIGHT_TEXTURE_COORD_NODE_NAME
            node.name = SUNLIGHT_TEXTURE_COORD_NODE_NAME
            if sunlight_object is not None:
                node.object = sunlight_object
            changed = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed binding public sunlight shader control", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed binding public sunlight shader control", exc_info=True)
            continue

        if links is None:
            continue
        try:
            object_socket = node.outputs.get("Object") if hasattr(node.outputs, "get") else None
            if object_socket is None:
                continue
            has_link = any(
                str(getattr(link.from_node, "name", "") or "") == str(getattr(node, "name", "") or "")
                and str(getattr(link.from_socket, "name", "") or "") == "Object"
                and str(getattr(link.to_socket, "name", "") or "") == SUNLIGHT_VECTOR_SOCKET_NAME
                for link in tuple(links)
            )
            if has_link:
                continue
            target_socket = None
            for candidate in nodes:
                if str(getattr(candidate, "bl_idname", "")) != "ShaderNodeGroup":
                    continue
                if getattr(candidate, "node_tree", None) is None:
                    continue
                if str(getattr(candidate.node_tree, "name", "") or "").split(".")[0] != SURFACE_GRADING_GROUP_NAME:
                    continue
                target_socket = candidate.inputs.get(SUNLIGHT_VECTOR_SOCKET_NAME) if hasattr(candidate.inputs, "get") else None
                if target_socket is not None:
                    break
            if target_socket is not None:
                links.new(object_socket, target_socket)
                changed = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed checking public sunlight shader link", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed checking public sunlight shader link", exc_info=True)
    return changed


def _remove_socket_driver(owner, socket):
    try:
        socket_path = socket.path_from_id("default_value")
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False

    animation_data = getattr(owner, "animation_data", None)
    drivers = getattr(animation_data, "drivers", None) if animation_data is not None else None
    if not drivers:
        return False

    removed = False
    for fcurve in tuple(drivers):
        if str(getattr(fcurve, "data_path", "") or "") != str(socket_path):
            continue
        if int(getattr(fcurve, "array_index", 0) or 0) != 0:
            continue
        try:
            owner.driver_remove(socket_path, 0)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            try:
                drivers.remove(fcurve)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed removing obsolete displacement scale driver", exc_info=True)
                continue
        removed = True
    return removed


def _mesh_surface_vertex_radius(mesh):
    vertices = getattr(mesh, "vertices", None)
    polygons = getattr(mesh, "polygons", None)
    if not vertices:
        return 0.0
    try:
        used_indices = set()
        if polygons:
            for poly in polygons:
                used_indices.update(int(index) for index in poly.vertices)
        if used_indices:
            return max(float(vertices[index].co.length) for index in used_indices if 0 <= index < len(vertices))
        return max(float(vertex.co.length) for vertex in vertices)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed inferring Earth Surface face radius for displacement scale", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
        logger.debug("Planetka: failed inferring Earth Surface face radius for displacement scale", exc_info=True)
    return 0.0


def _active_surface_local_radius(earth_obj=None):
    earth = earth_obj or bpy.data.objects.get(EARTH_SURFACE_OBJECT_NAME)
    mesh = getattr(earth, "data", None) if earth is not None else None
    radius = _mesh_surface_vertex_radius(mesh)
    return float(radius) if radius > 1e-9 else float(SURFACE_ELEVATION_REFERENCE_RADIUS)


def _displacement_scale_for_surface(earth_obj=None):
    local_radius = _active_surface_local_radius(earth_obj)
    return float(SURFACE_ELEVATION_SCALE_DEFAULT) * (
        float(local_radius) / float(SURFACE_ELEVATION_REFERENCE_RADIUS)
    )


def _displacement_sync_signature(earth_obj=None, scale_value=None):
    earth = earth_obj or bpy.data.objects.get(EARTH_SURFACE_OBJECT_NAME)
    mesh = getattr(earth, "data", None) if earth is not None else None
    return (
        int(getattr(earth, "as_pointer", lambda: 0)()) if earth is not None else 0,
        int(getattr(mesh, "as_pointer", lambda: 0)()) if mesh is not None else 0,
        len(getattr(mesh, "vertices", ()) or ()) if mesh is not None else 0,
        len(getattr(mesh, "polygons", ()) or ()) if mesh is not None else 0,
        round(float(_active_surface_local_radius(earth)), 9),
        round(float(scale_value if scale_value is not None else _displacement_scale_for_surface(earth)), 9),
    )


def sync_public_surface_displacement_scale(earth_obj=None, *, force=False):
    """Sync locked v1 displacement scale from actual local mesh radius."""
    global _LAST_DISPLACEMENT_SCALE_SIGNATURE
    scale_value = _displacement_scale_for_surface(earth_obj)
    signature = _displacement_sync_signature(earth_obj, scale_value=scale_value)
    if not force and signature == _LAST_DISPLACEMENT_SCALE_SIGNATURE:
        return False

    changed = False
    for node_group in _iter_group_nodes(SURFACE_GRADING_GROUP_NAME):
        nodes = getattr(node_group, "nodes", None)
        if nodes is None:
            continue
        scale_node = nodes.get(SURFACE_ELEVATION_SCALE_NODE_NAME) if hasattr(nodes, "get") else None
        if scale_node is None or str(getattr(scale_node, "bl_idname", "")) != "ShaderNodeMath":
            continue
        inputs = getattr(scale_node, "inputs", None)
        if inputs is None or len(inputs) < 2:
            continue
        socket = inputs[1]
        try:
            driver_removed = _remove_socket_driver(node_group, socket)
            if abs(float(getattr(socket, "default_value", 0.0)) - float(scale_value)) > 1e-12:
                socket.default_value = float(scale_value)
                changed = True
            changed = changed or driver_removed
            try:
                node_group.update_tag()
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting public displacement scale", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            logger.debug("Planetka: failed setting public displacement scale", exc_info=True)
    _LAST_DISPLACEMENT_SCALE_SIGNATURE = signature
    return bool(changed)
