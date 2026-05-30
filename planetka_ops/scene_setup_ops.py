import bpy

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object
from ..operator_utils import ErrorCode, fail, require_scene
from ..state import logger

_DEFAULT_SCENE_REMOVED_KEY = "planetka_default_scene_removed"
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count == 0:
        logger.warning("Planetka recoverable issue [%s]: %s", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _float_close(value, target, tol=1e-4):
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _is_default_world_shader(scene):
    if scene is None:
        return False
    world = getattr(scene, "world", None)
    if world is None:
        return False
    if str(getattr(world, "name", "") or "") != "World":
        return False
    node_tree = getattr(world, "node_tree", None)
    if node_tree is None:
        return False
    nodes = getattr(node_tree, "nodes", None)
    links = getattr(node_tree, "links", None)
    if nodes is None or links is None:
        return False

    background = nodes.get("Background")
    output = nodes.get("World Output")
    if background is None or output is None:
        return False
    if str(getattr(background, "bl_idname", "")) != "ShaderNodeBackground":
        return False
    if str(getattr(output, "bl_idname", "")) != "ShaderNodeOutputWorld":
        return False
    if len(tuple(nodes)) != 2:
        return False
    if len(tuple(links)) != 1:
        return False

    surface_input = output.inputs.get("Surface")
    color_socket = background.inputs[0] if len(background.inputs) > 0 else None
    strength_socket = background.inputs[1] if len(background.inputs) > 1 else None
    if surface_input is None or color_socket is None or strength_socket is None:
        return False
    if not bool(getattr(surface_input, "is_linked", False)):
        return False

    color = getattr(color_socket, "default_value", None)
    if color is None or len(color) < 4:
        return False
    default_gray = 0.050876
    return bool(
        _float_close(color[0], default_gray)
        and _float_close(color[1], default_gray)
        and _float_close(color[2], default_gray)
        and _float_close(color[3], 1.0)
        and _float_close(getattr(strength_socket, "default_value", 1.0), 1.0)
    )


def _find_world_background_node(world):
    node_tree = getattr(world, "node_tree", None) if world is not None else None
    nodes = getattr(node_tree, "nodes", None) if node_tree is not None else None
    if nodes is None:
        return None
    background = nodes.get("Background")
    if background is not None:
        return background
    for node in nodes:
        if str(getattr(node, "bl_idname", "")) == "ShaderNodeBackground":
            return node
    return None


def is_scene_background_black(scene):
    world = getattr(scene, "world", None) if scene is not None else None
    if world is None:
        return False

    node_tree = getattr(world, "node_tree", None)
    if node_tree is not None:
        background = _find_world_background_node(world)
        if background is None or len(getattr(background, "inputs", ())) < 1:
            return False
        color_socket = background.inputs[0]
        if bool(getattr(color_socket, "is_linked", False)):
            return False
        color = getattr(color_socket, "default_value", None)
        if color is None or len(color) < 4:
            return False
        return bool(
            _float_close(color[0], 0.0)
            and _float_close(color[1], 0.0)
            and _float_close(color[2], 0.0)
            and _float_close(color[3], 1.0)
        )

    try:
        color = getattr(world, "color", None)
        return bool(
            color is not None
            and len(color) >= 3
            and _float_close(color[0], 0.0)
            and _float_close(color[1], 0.0)
            and _float_close(color[2], 0.0)
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def set_scene_background_black(scene):
    if scene is None:
        return False

    world = getattr(scene, "world", None)
    if world is None:
        world = bpy.data.worlds.new("Planetka Black World")
        scene.world = world

    node_tree = getattr(world, "node_tree", None)
    nodes = getattr(node_tree, "nodes", None) if node_tree is not None else None
    links = getattr(node_tree, "links", None) if node_tree is not None else None
    if node_tree is None or nodes is None or links is None:
        try:
            world.color = (0.0, 0.0, 0.0)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return False

    background = _find_world_background_node(world)
    if background is None:
        background = nodes.new(type="ShaderNodeBackground")
        background.name = "Background"
    output = nodes.get("World Output")
    if output is None:
        for node in nodes:
            if str(getattr(node, "bl_idname", "")) == "ShaderNodeOutputWorld":
                output = node
                break
    if output is None:
        output = nodes.new(type="ShaderNodeOutputWorld")
        output.name = "World Output"

    color_socket = background.inputs[0] if len(background.inputs) > 0 else None
    strength_socket = background.inputs[1] if len(background.inputs) > 1 else None
    surface_socket = output.inputs.get("Surface") if getattr(output, "inputs", None) is not None else None
    if color_socket is None or surface_socket is None:
        return False

    try:
        for link in tuple(getattr(color_socket, "links", ())):
            links.remove(link)
        color_socket.default_value = (0.0, 0.0, 0.0, 1.0)
        if strength_socket is not None and not bool(getattr(strength_socket, "is_linked", False)):
            strength_socket.default_value = 1.0
        for link in tuple(getattr(surface_socket, "links", ())):
            links.remove(link)
        links.new(background.outputs[0], surface_socket)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting scene background to black", exc_info=True)
        return False


def _is_pristine_default_scene(scene):
    if scene is None:
        return False
    try:
        scene_objects = tuple(getattr(scene, "objects", ()))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    if len(scene_objects) != 3:
        return False
    required = {
        "Cube": "MESH",
        "Camera": "CAMERA",
        "Light": "LIGHT",
    }
    scene_names = {str(getattr(obj, "name", "")) for obj in scene_objects}
    if scene_names != set(required.keys()):
        return False
    for name, expected_type in required.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj not in scene_objects:
            return False
        if str(getattr(obj, "type", "")) != expected_type:
            return False

    root_collection = getattr(scene, "collection", None)
    if root_collection is None:
        return False
    children = tuple(getattr(root_collection, "children", ()))
    if len(children) != 1:
        return False
    child = children[0]
    if str(getattr(child, "name", "")) != "Collection":
        return False
    child_names = {str(getattr(obj, "name", "")) for obj in tuple(getattr(child, "objects", ()))}
    if child_names != set(required.keys()):
        return False
    if not _is_default_world_shader(scene):
        return False
    return True


def _cleanup_pristine_default_scene(scene):
    if not _is_pristine_default_scene(scene):
        return False

    removed_any = False
    for object_name in ("Cube", "Camera", "Light"):
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_any = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-027", f"Failed removing default object '{object_name}'")

    default_collection = bpy.data.collections.get("Collection")
    root_collection = getattr(scene, "collection", None)
    if default_collection is not None and root_collection is not None:
        try:
            if (
                default_collection in tuple(getattr(root_collection, "children", ()))
                and len(tuple(getattr(default_collection, "objects", ()))) == 0
                and len(tuple(getattr(default_collection, "children", ()))) == 0
            ):
                root_collection.children.unlink(default_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-028", "Failed unlinking default collection from scene root")
        try:
            if (
                len(tuple(getattr(default_collection, "users_scene", ()))) == 0
                and len(tuple(getattr(default_collection, "users_collection", ()))) == 0
            ):
                bpy.data.collections.remove(default_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-029", "Failed deleting empty default collection")

    world = getattr(scene, "world", None)
    if world is not None and _is_default_world_shader(scene):
        try:
            scene.world = None
            removed_any = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-062", "Failed unlinking default World shader from scene")
        try:
            if int(getattr(world, "users", 0) or 0) == 0:
                bpy.data.worlds.remove(world)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-063", "Failed removing default World datablock")

    return removed_any


class PLANETKA_OT_SetBackgroundBlack(bpy.types.Operator):
    bl_idname = "planetka.set_background_black"
    bl_label = "Set Background to Black"
    bl_description = "Set World background color to black"

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene is not None and not is_scene_background_black(scene))

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        if not set_scene_background_black(scene):
            self.report({'WARNING'}, "World background color could not be changed automatically.")
            return {'CANCELLED'}

        return {'FINISHED'}


def _set_render_setting(owner, attr: str, value) -> bool:
    if owner is None or not hasattr(owner, attr):
        return False
    try:
        setattr(owner, attr, value)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting render setting %s=%r", attr, value, exc_info=True)
        return False


def optimize_render_settings(scene) -> tuple[int, list[str]]:
    if scene is None:
        return 0, ["Scene not available."]

    engine = str(getattr(getattr(scene, "render", None), "engine", "") or "")
    changed = 0
    skipped: list[str] = []

    if engine.startswith("BLENDER_EEVEE"):
        eevee = getattr(scene, "eevee", None)
        if _set_render_setting(eevee, "volumetric_tile_size", "2"):
            changed += 1
        else:
            skipped.append("EEVEE Volumes Resolution")
        return changed, skipped

    if engine == "CYCLES":
        cycles = getattr(scene, "cycles", None)
        render = getattr(scene, "render", None)
        settings = (
            (cycles, "volume_biased", True, "Cycles Volumes Biased"),
            (cycles, "volume_max_steps", 16, "Cycles Volumes Max Steps"),
            (cycles, "dicing_rate", 1.25, "Cycles Dicing Rate Render"),
            (cycles, "offscreen_dicing_scale", 1.5, "Cycles Off-Screen Scale"),
            (cycles, "preview_dicing_rate", 2.0, "Cycles Viewport Dicing Rate"),
            (cycles, "max_subdivisions", 16, "Cycles Max Subdivision"),
            (render, "use_persistent_data", True, "Cycles Persistent Data"),
            (cycles, "volume_bounces", 16, "Cycles Volume Bounces"),
            (cycles, "adaptive_threshold", 0.025, "Cycles Noise Threshold"),
            (cycles, "adaptive_min_samples", 8, "Cycles Min Samples"),
            (cycles, "use_denoising", False, "Cycles Denoise"),
        )
        for owner, attr, value, label in settings:
            if _set_render_setting(owner, attr, value):
                changed += 1
            else:
                skipped.append(label)
        return changed, skipped

    skipped.append(f"Unsupported render engine: {engine or 'Unknown'}")
    return changed, skipped


class PLANETKA_OT_OptimizeRenderSettings(bpy.types.Operator):
    bl_idname = "planetka.optimize_render_settings"
    bl_label = "Optimize Render Settings"
    bl_description = (
        "Optimize Blender render settings for Planetka. "
        "In EEVEE, set Volumes Resolution to 1:2. "
        "In Cycles, enable Volumes Biased, set Volume Max Steps to 16, "
        "Subdivision Dicing Rate Render to 1.25, Off-Screen Scale to 1.5, "
        "Viewport Dicing Rate to 2.0, Max Subdivision to 16, Persistent Data on, "
        "Volume Bounces to 16, Noise Threshold to 0.025, Min Samples to 8, and Denoise off."
    )

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        changed, skipped = optimize_render_settings(scene)
        if skipped:
            self.report({'WARNING'}, f"Optimized {changed} render setting(s); skipped: {', '.join(skipped)}.")
        else:
            self.report({'INFO'}, f"Optimized {changed} render setting(s).")
        return {'FINISHED'}


class PLANETKA_OT_RemoveDefaultScene(bpy.types.Operator):
    bl_idname = "planetka.remove_default_scene"
    bl_label = "Remove Default Scene"
    bl_description = (
        "Remove Blender's default Collection/Cube/Camera/Light and default World shader "
        "when the scene is still pristine Blender startup state"
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        if get_earth_object() is not None:
            return False
        return _is_pristine_default_scene(scene)

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        if not _is_pristine_default_scene(scene):
            return fail(
                self,
                "Remove Default Scene is available only for untouched Blender default startup scene.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        removed = bool(_cleanup_pristine_default_scene(scene))
        if not removed:
            return fail(
                self,
                "Unable to remove default scene items.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )

        try:
            scene[_DEFAULT_SCENE_REMOVED_KEY] = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed tagging scene as default-cleaned", exc_info=True)

        self.report({'INFO'}, "Default startup scene removed.")
        return {'FINISHED'}
