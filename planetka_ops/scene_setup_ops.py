import textwrap

import bpy

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object, get_prefs
from ..operator_utils import ErrorCode, fail, require_scene
from ..state import logger

_DEFAULT_SCENE_REMOVED_KEY = "planetka_default_scene_removed"
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count == 0:
        logger.warning("Planetka recoverable issue [%s]: %s", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _draw_popup_help(layout, text, icon="INFO", width=62):
    column = layout.column(align=True)
    column.use_property_split = False
    column.use_property_decorate = False
    wrapped = textwrap.wrap(str(text or "").strip(), width=max(24, int(width))) or [""]
    for index, line in enumerate(wrapped):
        column.label(text=line, icon=icon if index == 0 else "BLANK1")


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


def _safe_set_attr(owner, attr_name, value, changes=None, label=None):
    if owner is None or not hasattr(owner, attr_name):
        return False
    try:
        current = getattr(owner, attr_name)
        if current == value:
            return False
        setattr(owner, attr_name, value)
        setting_label = str(label or f"{type(owner).__name__}.{attr_name}")
        message = f"{setting_label}: {current!r} -> {value!r}"
        logger.info(
            "Planetka Optimize Settings: %s",
            message,
        )
        if isinstance(changes, list):
            changes.append(message)
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed setting %s.%s", type(owner).__name__, attr_name, exc_info=True)
        return False


def _int_pref(prefs, attr_name, default):
    try:
        return int(getattr(prefs, attr_name, default))
    except (TypeError, ValueError, AttributeError):
        return int(default)


def _float_pref(prefs, attr_name, default):
    try:
        return float(getattr(prefs, attr_name, default))
    except (TypeError, ValueError, AttributeError):
        return float(default)


def _bool_pref(prefs, attr_name, default):
    try:
        return bool(getattr(prefs, attr_name, default))
    except (TypeError, ValueError, AttributeError):
        return bool(default)


def _apply_optimize_render_settings(scene, prefs, changes=None):
    if scene is None or prefs is None:
        return 0

    changed = 0
    eevee = getattr(scene, "eevee", None)
    cycles = getattr(scene, "cycles", None)
    render = getattr(scene, "render", None)

    try:
        volume_resolution = str(getattr(prefs, "optimize_eevee_volume_resolution", "2") or "2")
    except (TypeError, ValueError, AttributeError):
        volume_resolution = "2"
    if _safe_set_attr(eevee, "volumetric_tile_size", volume_resolution, changes, "EEVEE Volumes / Resolution"):
        changed += 1

    if _safe_set_attr(
        cycles,
        "volume_bounces",
        max(0, _int_pref(prefs, "optimize_cycles_volume_bounces", 16)),
        changes,
        "Cycles Light Paths / Max Bounces / Volume",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "volume_biased",
        _bool_pref(prefs, "optimize_cycles_volume_biased", True),
        changes,
        "Cycles Volumes / Biased",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "volume_max_steps",
        max(1, _int_pref(prefs, "optimize_cycles_volume_max_steps", 16)),
        changes,
        "Cycles Volumes / Max Steps",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "dicing_rate",
        max(0.001, _float_pref(prefs, "optimize_cycles_dicing_rate_render", 1.5)),
        changes,
        "Cycles Subdivision / Dicing Rate Render",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "preview_dicing_rate",
        max(0.001, _float_pref(prefs, "optimize_cycles_dicing_rate_viewport", 2.0)),
        changes,
        "Cycles Subdivision / Viewport",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "offscreen_dicing_scale",
        max(0.001, _float_pref(prefs, "optimize_cycles_offscreen_scale", 1.5)),
        changes,
        "Cycles Subdivision / Offscreen Scale",
    ):
        changed += 1
    if _safe_set_attr(
        cycles,
        "max_subdivisions",
        max(0, _int_pref(prefs, "optimize_cycles_max_subdivisions", 16)),
        changes,
        "Cycles Subdivision / Max Subdivisions",
    ):
        changed += 1
    if _safe_set_attr(
        render,
        "use_persistent_data",
        _bool_pref(prefs, "optimize_persistent_data", True),
        changes,
        "Performance / Final Render / Persistent Data",
    ):
        changed += 1

    return changed


def apply_optimize_settings(scene, prefs, changes=None):
    if scene is None or prefs is None:
        return 0

    changed = 0
    if _bool_pref(prefs, "optimize_remove_default_scene", True) and get_earth_object() is None:
        try:
            if _is_pristine_default_scene(scene) and _cleanup_pristine_default_scene(scene):
                scene[_DEFAULT_SCENE_REMOVED_KEY] = True
                message = "Preparation / Remove Default Cube Scene: applied"
                logger.info("Planetka Optimize Settings: %s", message)
                if isinstance(changes, list):
                    changes.append(message)
                changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying default scene cleanup from Optimize Settings", exc_info=True)

    if _bool_pref(prefs, "optimize_background_black", True):
        try:
            if not is_scene_background_black(scene) and set_scene_background_black(scene):
                message = "Preparation / Set Background to Black: applied"
                logger.info("Planetka Optimize Settings: %s", message)
                if isinstance(changes, list):
                    changes.append(message)
                changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying black background from Optimize Settings", exc_info=True)

    changed += _apply_optimize_render_settings(scene, prefs, changes)
    return changed


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


class PLANETKA_OT_OptimizeSettings(bpy.types.Operator):
    bl_idname = "planetka.optimize_settings"
    bl_label = "Prepare / Optimize Settings"
    bl_description = (
        "Apply the saved Planetka preparation settings before Create Earth: optionally remove the default "
        "Cube scene, set the background to black, set EEVEE volume resolution, and set Cycles volume, "
        "adaptive subdivision, and persistent-data render settings"
    )

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "scene", None) is not None)

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if prefs is None:
            return fail(
                self,
                "Planetka preferences are not available.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        changes = []
        changed = apply_optimize_settings(scene, prefs, changes)
        for message in changes:
            self.report({'INFO'}, message)
        self.report({'INFO'}, f"Optimized {int(changed)} setting(s).")
        return {'FINISHED'}


class PLANETKA_OT_OptimizeSettingsPopup(bpy.types.Operator):
    bl_idname = "planetka.optimize_settings_popup"
    bl_label = "Prepare / Optimize Settings"
    bl_description = "Edit the saved settings applied by the Prepare / Optimize Settings button"

    def invoke(self, context, _event):
        try:
            return context.window_manager.invoke_props_dialog(self, width=460, confirm_text="Save Settings")
        except TypeError:
            return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        prefs = get_prefs()
        if prefs is None or not isinstance(prefs, bpy.types.AddonPreferences):
            layout.label(text="Planetka preferences are not available.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        _draw_popup_help(
            layout,
            "These are the most commonly used Blender settings that usually need adjusting for Planetka to render correctly.",
        )

        box = layout.box()
        box.label(text="Preparation", icon="SCENE_DATA")
        _draw_popup_help(box, "One click scene preparation for new scenes.")
        box.prop(prefs, "optimize_remove_default_scene")
        box.prop(prefs, "optimize_background_black")

        box = layout.box()
        box.label(text="EEVEE Render Settings", icon="RENDER_STILL")
        _draw_popup_help(
            box,
            "Default 1:8 volume resolution can produce blotchy volumetrics. 1:2 is a good balance between quality and speed.",
        )
        box.prop(prefs, "optimize_eevee_volume_resolution")

        box = layout.box()
        box.label(text="Cycles Render Settings", icon="RENDER_STILL")

        section = box.box()
        section.label(text="Light Paths")
        _draw_popup_help(
            section,
            "Default Volume bounces of 0 prevents light rays from entering volumetric clouds, so they can render black. "
            "Values around 12-16 are recommended for high quality VDB clouds; lower values are faster but rays do not penetrate as deeply.",
        )
        section.prop(prefs, "optimize_cycles_volume_bounces")

        section = box.box()
        section.label(text="Volumes")
        _draw_popup_help(
            section,
            "For GPU rendering keep Biased on and reduce Max Steps. 16 is a good quality/speed balance. Higher values can significantly increase render time; lower values reduce detail, especially in VDB clouds.",
        )
        _draw_popup_help(
            section,
            "With Unbiased rendering, CPU rendering is often faster than GPU rendering on fast CPU setups.",
        )
        section.prop(prefs, "optimize_cycles_volume_biased")
        section.prop(prefs, "optimize_cycles_volume_max_steps")

        section = box.box()
        section.label(text="Subdivision")
        _draw_popup_help(
            section,
            "Slightly increasing Dicing Rate Render from 1.00 to 1.25 or 1.5 can significantly reduce memory usage while keeping high elevation detail.",
        )
        _draw_popup_help(
            section,
            "Keep Offscreen Scale similar for animations. As the camera moves, offscreen areas enter view and can lack elevation detail if this is much higher than Dicing Rate Render.",
        )
        _draw_popup_help(
            section,
            "Viewport is personal preference and does not affect final renders. Max Subdivisions is set high to avoid losing fine elevation detail.",
        )
        section.prop(prefs, "optimize_cycles_dicing_rate_render")
        section.prop(prefs, "optimize_cycles_dicing_rate_viewport")
        section.prop(prefs, "optimize_cycles_offscreen_scale")
        section.prop(prefs, "optimize_cycles_max_subdivisions")

        section = box.box()
        section.label(text="Performance")
        _draw_popup_help(
            section,
            "Persistent Data is recommended for animation rendering to avoid preprocessing every frame.",
        )
        section.prop(prefs, "optimize_persistent_data")

        _draw_popup_help(
            layout,
            "Save Settings stores these choices for this Planetka installation and reuses them in future projects when you click Prepare / Optimize Settings.",
        )

    def execute(self, _context):
        try:
            bpy.ops.wm.save_userpref()
            self.report({'INFO'}, "Optimize Settings saved.")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed saving Optimize Settings preferences", exc_info=True)
            self.report({'WARNING'}, "Optimize Settings were applied but could not be saved to Blender preferences.")
        return {'FINISHED'}
