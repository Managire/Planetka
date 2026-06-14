import os

import bpy

from .asset_builder import EARTH_MATERIAL_NAME, NIGHTDAY_GROUP_NAME, PLANETKA_ROOT_OBJECT_NAME
from .auth import get_cached_cloud_connection_status, is_authenticated
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail


def _append(payload, severity, ok, message, detail=""):
    entry = {
        "severity": str(severity or "INFO").upper(),
        "ok": bool(ok),
        "message": str(message or "").strip(),
        "detail": str(detail or "").strip(),
    }
    payload["checks"].append(entry)
    if ok:
        return
    key = "errors" if entry["severity"] == "ERROR" else ("warnings" if entry["severity"] == "WARNING" else "info")
    payload[key].append(entry["message"])


def _image_path(image):
    if image is None:
        return ""
    return str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()


def _texture_assignment_stats(material):
    stats = {"assigned": 0, "missing": 0}
    visited = set()

    def visit_tree(tree):
        if tree is None:
            return
        try:
            token = int(tree.as_pointer())
        except (RuntimeError, TypeError, ValueError, AttributeError):
            token = id(tree)
        if token in visited:
            return
        visited.add(token)
        for node in tuple(getattr(tree, "nodes", ()) or ()):
            if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexImage":
                path = _image_path(getattr(node, "image", None))
                if path:
                    stats["assigned"] += 1
                    abs_path = os.path.abspath(bpy.path.abspath(path))
                    if not os.path.isfile(abs_path):
                        stats["missing"] += 1
                continue
            if str(getattr(node, "type", "")) == "GROUP":
                visit_tree(getattr(node, "node_tree", None))

    visit_tree(getattr(material, "node_tree", None))
    return stats


def _shader_sunlight_object():
    for node_group in tuple(getattr(bpy.data, "node_groups", ()) or ()):
        name = str(getattr(node_group, "name", "") or "")
        if name != NIGHTDAY_GROUP_NAME and not name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
            continue
        node = getattr(node_group, "nodes", None)
        if node is None:
            continue
        texcoord = node.get("Select Sunlight Source Object Here") if hasattr(node, "get") else None
        if texcoord is None:
            texcoord = node.get("Texture Coordinate") if hasattr(node, "get") else None
        if texcoord is None:
            continue
        return getattr(texcoord, "object", None)
    return None


def collect_public_scene_health(context):
    scene = getattr(context, "scene", None)
    prefs = get_prefs()
    earth = get_earth_object()
    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    material = bpy.data.materials.get(EARTH_MATERIAL_NAME)
    camera = getattr(scene, "camera", None) if scene is not None else None
    sunlight = _shader_sunlight_object()

    payload = {"checks": [], "errors": [], "warnings": [], "info": []}
    _append(payload, "ERROR", earth is not None, "Planetka Earth Surface is present.")
    _append(payload, "ERROR", root is not None, "Planetka Root is present.")
    _append(payload, "ERROR", material is not None, "Planetka Earth Material is present.")
    _append(
        payload,
        "WARNING",
        camera is not None and str(getattr(camera, "type", "")) == "CAMERA",
        "Active scene camera is set.",
    )
    _append(
        payload,
        "INFO",
        sunlight is not None,
        "Shader sunlight source object is selected.",
        detail=str(getattr(sunlight, "name", "") or "not selected"),
    )

    authenticated = is_authenticated(prefs)
    cloud = get_cached_cloud_connection_status() if authenticated else {"checked": False, "online": False}
    cloud_ok = bool(authenticated and cloud.get("online", False))
    _append(
        payload,
        "WARNING",
        cloud_ok,
        "Planetka Cloud connection is active.",
        detail=str(cloud.get("message", "") or ""),
    )

    if material is not None:
        stats = _texture_assignment_stats(material)
        _append(
            payload,
            "WARNING",
            int(stats["missing"]) == 0,
            "Assigned texture files are available on disk.",
            detail=f"assigned={int(stats['assigned'])}, missing={int(stats['missing'])}",
        )
    return payload


def _draw_health(layout, health):
    errors = len(health.get("errors", ()) or ())
    warnings = len(health.get("warnings", ()) or ())
    if errors:
        layout.label(text=f"{errors} error(s)", icon="ERROR")
    elif warnings:
        layout.label(text=f"{warnings} warning(s)", icon="INFO")
    else:
        layout.label(text="Scene health check passed.", icon="CHECKMARK")
    for entry in list(health.get("checks", ()) or ()):
        icon = "CHECKMARK" if bool(entry.get("ok")) else ("ERROR" if entry.get("severity") == "ERROR" else "INFO")
        layout.label(text=str(entry.get("message", "") or ""), icon=icon)
        detail = str(entry.get("detail", "") or "").strip()
        if detail:
            row = layout.row()
            row.scale_y = 0.8
            row.label(text=detail)


class PLANETKA_OT_PublicSceneHealthCheck(bpy.types.Operator):
    bl_idname = "planetka_public.scene_health_check"
    bl_label = "Scene Health Check"
    bl_description = "Check the public Planetka Earth surface, camera, cloud session, and texture assignments"

    _health = None

    def invoke(self, context, event):
        del event
        self._health = collect_public_scene_health(context)
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return self.execute(context)
        return wm.invoke_props_dialog(self, width=560)

    def draw(self, context):
        del context
        _draw_health(self.layout, self._health if isinstance(self._health, dict) else {"checks": []})

    def execute(self, context):
        health = self._health if isinstance(self._health, dict) else collect_public_scene_health(context)
        errors = len(health.get("errors", ()) or ())
        warnings = len(health.get("warnings", ()) or ())
        if errors:
            return fail(self, f"Scene Health Check found {errors} error(s).", code=ErrorCode.PRECHECK_FAILED)
        self.report({'INFO'}, f"Scene Health Check complete ({warnings} warning(s)).")
        return {'FINISHED'}
