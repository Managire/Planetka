import logging

import bpy

from .asset_builder import NIGHTDAY_GROUP_NAME, SURFACE_GRADING_GROUP_NAME
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

SURFACE_ELEVATION_SCALE_NODE_NAME = "Math.011"
SURFACE_ELEVATION_SCALE_EXPRESSION = "0.024 * ((max(dim_x, dim_y, dim_z) / 2.0) / 2.0)"
SURFACE_ELEVATION_SCALE_DEFAULT = 0.024


def _iter_group_nodes(group_name):
    prefix = str(group_name or "").strip()
    if not prefix:
        return
    for node_group in tuple(getattr(bpy.data, "node_groups", ()) or ()):
        name = str(getattr(node_group, "name", "") or "")
        if name == prefix or name.startswith(f"{prefix}."):
            yield node_group


def prepare_public_sunlight_shader_control():
    """Make the day/night object picker discoverable inside the shader graph."""
    changed = False
    for node_group in _iter_group_nodes(NIGHTDAY_GROUP_NAME):
        nodes = getattr(node_group, "nodes", None)
        if nodes is None:
            continue
        target_nodes = []
        named = nodes.get("Texture Coordinate") if hasattr(nodes, "get") else None
        if named is not None and str(getattr(named, "bl_idname", "")) == "ShaderNodeTexCoord":
            target_nodes.append(named)
        target_nodes.extend(
            node
            for node in nodes
            if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexCoord" and node not in target_nodes
        )
        for node in target_nodes:
            try:
                node.label = "Select Sunlight Source Object Here"
                node.name = "Select Sunlight Source Object Here"
                changed = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed labelling public sunlight shader control", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed labelling public sunlight shader control", exc_info=True)
    return changed


def _surface_diameter_from_object(earth_obj):
    if earth_obj is None:
        return 0.0

    try:
        dimensions = getattr(earth_obj, "dimensions", None)
        if dimensions is not None:
            diameter = max(abs(float(dimensions.x)), abs(float(dimensions.y)), abs(float(dimensions.z)))
            if diameter > 1e-9:
                return float(diameter)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading Earth Surface dimensions for displacement driver", exc_info=True)

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0) or 0.0)
        if stored_local_radius > 1e-9:
            scale = earth_obj.matrix_world.to_scale()
            max_scale = max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)), 1e-9)
            return float(stored_local_radius) * float(max_scale) * 2.0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading Earth Surface radius metadata for displacement driver", exc_info=True)

    mesh = getattr(earth_obj, "data", None)
    vertices = getattr(mesh, "vertices", None)
    if vertices:
        try:
            local_radius = max(float(vertex.co.length) for vertex in vertices)
            if local_radius > 1e-9:
                scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)), 1e-9)
                return float(local_radius) * float(max_scale) * 2.0
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed inferring Earth Surface mesh size for displacement driver", exc_info=True)

    return 0.0


def _find_socket_driver(owner, socket):
    try:
        socket_path = socket.path_from_id("default_value")
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None
    animation_data = getattr(owner, "animation_data", None)
    drivers = getattr(animation_data, "drivers", None) if animation_data is not None else None
    if not drivers:
        return None
    for fcurve in tuple(drivers):
        if (
            str(getattr(fcurve, "data_path", "") or "") == str(socket_path)
            and int(getattr(fcurve, "array_index", 0) or 0) == 0
        ):
            return fcurve
    return None


def _ensure_dimension_driver_variable(driver, earth_obj, variable_name, data_path):
    target_variable = None
    for variable in tuple(getattr(driver, "variables", ()) or ()):
        if str(getattr(variable, "name", "") or "") == str(variable_name) and target_variable is None:
            target_variable = variable

    if target_variable is None:
        target_variable = driver.variables.new()
        target_variable.name = str(variable_name)

    if str(getattr(target_variable, "type", "") or "") != "SINGLE_PROP":
        target_variable.type = "SINGLE_PROP"

    targets = getattr(target_variable, "targets", ())
    if not targets:
        return
    target = targets[0]
    if str(getattr(target, "id_type", "") or "") != "OBJECT":
        target.id_type = "OBJECT"
    if getattr(target, "id", None) is not earth_obj:
        target.id = earth_obj
    if str(getattr(target, "data_path", "") or "") != str(data_path):
        target.data_path = str(data_path)


def bind_public_surface_displacement_scale_driver(earth_obj):
    """Drive elevation displacement scale from the live Earth Surface dimensions."""
    if earth_obj is None:
        return False

    diameter = _surface_diameter_from_object(earth_obj)
    fallback_scale = (
        float(SURFACE_ELEVATION_SCALE_DEFAULT) * ((float(diameter) / 2.0) / 2.0)
        if diameter > 1e-9
        else float(SURFACE_ELEVATION_SCALE_DEFAULT)
    )

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
            socket.default_value = float(fallback_scale)
            fcurve = _find_socket_driver(node_group, socket)
            if fcurve is None:
                fcurve = socket.driver_add("default_value")
            driver = getattr(fcurve, "driver", None)
            if driver is None:
                continue
            if str(getattr(driver, "type", "") or "") != "SCRIPTED":
                driver.type = "SCRIPTED"
            if str(getattr(driver, "expression", "") or "") != SURFACE_ELEVATION_SCALE_EXPRESSION:
                driver.expression = SURFACE_ELEVATION_SCALE_EXPRESSION
            required_variables = {"dim_x", "dim_y", "dim_z"}
            seen_variables = set()
            for variable in tuple(getattr(driver, "variables", ()) or ()):
                name = str(getattr(variable, "name", "") or "")
                if name in required_variables and name not in seen_variables:
                    seen_variables.add(name)
                    continue
                driver.variables.remove(variable)
            for variable_name, data_path in (
                ("dim_x", "dimensions[0]"),
                ("dim_y", "dimensions[1]"),
                ("dim_z", "dimensions[2]"),
            ):
                _ensure_dimension_driver_variable(driver, earth_obj, variable_name, data_path)
            try:
                node_group.update_tag()
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            changed = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed binding public displacement scale driver", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            logger.debug("Planetka: failed binding public displacement scale driver", exc_info=True)
    return bool(changed)
