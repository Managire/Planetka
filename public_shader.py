import logging

import bpy

from .asset_builder import EARTH_MATERIAL_NAME, PREVIEW_MATERIAL_NAME, SURFACE_GRADING_GROUP_NAME
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

SURFACE_ELEVATION_SCALE_NODE_NAME = "Math.011"
SURFACE_ELEVATION_SCALE_DEFAULT = 0.024
SUNLIGHT_TEXTURE_COORD_NODE_NAME = "Select Sunlight Source Object Here"
SUNLIGHT_VECTOR_SOCKET_NAME = "SunLight Object"
SURFACE_MATERIAL_NAMES = (EARTH_MATERIAL_NAME, PREVIEW_MATERIAL_NAME)


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


def set_public_surface_displacement_scale_static():
    """Keep the locked v1 displacement scale static and remove obsolete drivers."""
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
            if abs(float(getattr(socket, "default_value", 0.0)) - float(SURFACE_ELEVATION_SCALE_DEFAULT)) > 1e-12:
                socket.default_value = float(SURFACE_ELEVATION_SCALE_DEFAULT)
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
    return bool(changed)
