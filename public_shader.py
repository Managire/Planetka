import logging

import bpy

from .asset_builder import NIGHTDAY_GROUP_NAME
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)


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
