import json
import logging
import math
import os
import platform
import re
import sys
import base64
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
import urllib.error
import urllib.request
from urllib.parse import quote

import bpy
from mathutils import Vector

from .auth import (
    AuthApiError,
    get_api_base_url,
    get_authorized_headers,
    is_authenticated,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail
from .asset_builder import (
    EARTH_MATERIAL_NAME,
    NIGHTDAY_GROUP_NAME,
    PLANETKA_ROOT_OBJECT_NAME,
    SUNLIGHT_OBJECT_NAME,
    SURFACE_GRADING_GROUP_NAME,
)

logger = logging.getLogger(__name__)

_BUG_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
_BUG_ATTACHMENT_ALLOWED_MIME = {
    "image/png",
    "image/jpeg",
    "image/webp",
}
_HEALTH_CAMERA_DISTANCE_RATIO_WARN = 50000.0
_HEALTH_CAMERA_DISTANCE_RATIO_ERROR = 120000.0
_HEALTH_MIN_FACING_DOT_WARN = 0.15
_CLOUD_ROLE_KEY = "planetka_cloud_role"
_GLOBAL_CLOUD_ROLE = "global_cloud"
_TEXTURE_CLOUD_ROLE = "local_cloud"
_VDB_CLOUD_ROLE = "vdb_cloud"
_TEXTURE_CLOUD_PATH_PROPS = (
    "planetka_texture_based_cloud_loaded_texture",
    "planetka_texture_based_cloud_final_texture",
    "planetka_texture_based_cloud_balanced_texture",
    "planetka_texture_based_cloud_preview_texture",
)
_VDB_CLOUD_PATH_PROPS = (
    "planetka_vdb_cloud_loaded_file",
    "planetka_vdb_cloud_final_file",
    "planetka_vdb_cloud_balanced_file",
    "planetka_vdb_cloud_preview_file",
)


def _default_bug_report_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"planetka_bug_report_{timestamp}.json"
    blend_dir = bpy.path.abspath("//") or ""
    if blend_dir and os.path.isdir(blend_dir):
        return os.path.join(blend_dir, filename)
    temp_dir = getattr(bpy.app, "tempdir", "") or ""
    if temp_dir and os.path.isdir(temp_dir):
        return os.path.join(temp_dir, filename)
    return filename


def _encode_optional_bug_attachment(file_path):
    normalized = str(file_path or "").strip()
    if not normalized:
        return None, ""
    abs_path = os.path.abspath(bpy.path.abspath(normalized))
    if not os.path.isfile(abs_path):
        return None, "attachment_not_found"
    try:
        size_bytes = int(os.path.getsize(abs_path))
    except (OSError, TypeError, ValueError):
        return None, "attachment_unreadable"
    if size_bytes <= 0:
        return None, "attachment_empty"
    if size_bytes > _BUG_ATTACHMENT_MAX_BYTES:
        return None, "attachment_too_large"

    mime_type, _encoding = mimetypes.guess_type(abs_path)
    mime_type = str(mime_type or "").strip().lower()
    if mime_type not in _BUG_ATTACHMENT_ALLOWED_MIME:
        return None, "attachment_unsupported_type"

    try:
        with open(abs_path, "rb") as handle:
            data = handle.read()
    except (OSError, TypeError, ValueError):
        return None, "attachment_unreadable"
    if not data:
        return None, "attachment_empty"
    if len(data) > _BUG_ATTACHMENT_MAX_BYTES:
        return None, "attachment_too_large"

    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "attachment_filename": os.path.basename(abs_path),
        "attachment_mime": mime_type,
        "attachment_base64": encoded,
        "attachment_size_bytes": len(data),
        "attachment_path": abs_path,
    }
    return payload, ""


def _build_minimal_report(context):
    scene = getattr(context, "scene", None)
    render = getattr(scene, "render", None) if scene else None
    health = collect_scene_health_data(context)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "addon": __package__ or "Planetka",
        "blender_version": list(getattr(bpy.app, "version", ())),
        "blender_version_string": getattr(bpy.app, "version_string", ""),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "scene_name": getattr(scene, "name", ""),
        "render_engine": getattr(render, "engine", "") if render else "",
        "scene_health_report": health,
    }


def _open_bug_mail_draft(
    report_path,
    report_json_text,
    issue_what_happened="",
    issue_steps_to_reproduce="",
    issue_expected_behavior="",
    attachment_path="",
):
    subject = "Planetka Blender Bug Report"
    max_json_chars = 6000
    safe_json = str(report_json_text or "").strip()
    if len(safe_json) > max_json_chars:
        safe_json = (
            safe_json[:max_json_chars]
            + "\n... [truncated in email body; see exported JSON file path below for full report]"
        )
    body = (
        "Hi Planetka team,\n\n"
        "Planetka debug report JSON:\n\n"
        f"{safe_json}\n\n"
        "Local debug report path (full file):\n"
        f"{report_path}\n\n"
        "Debug report path:\n"
        "(included above)\n\n"
        "Issue description:\n"
        f"- What happened: {str(issue_what_happened or '').strip()}\n"
        f"- Steps to reproduce: {str(issue_steps_to_reproduce or '').strip()}\n"
        f"- Expected behavior: {str(issue_expected_behavior or '').strip()}\n"
        f"- Attachment path: {str(attachment_path or '').strip() or '(none)'}\n"
    )
    mailto_url = (
        "mailto:info@planetka.io"
        f"?subject={quote(subject)}"
        f"&body={quote(body)}"
    )
    try:
        bpy.ops.wm.url_open(url=mailto_url)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    return True


def _open_feedback_mail_draft(feedback_text):
    subject = "Planetka Blender Feedback"
    body = (
        "Hi Planetka team,\n\n"
        "Feedback:\n"
        f"{str(feedback_text or '').strip()}\n"
    )
    mailto_url = (
        "mailto:info@planetka.io"
        f"?subject={quote(subject)}"
        f"&body={quote(body)}"
    )
    try:
        bpy.ops.wm.url_open(url=mailto_url)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    return True


def _send_bug_report_via_api(
    report_path,
    report_json_text,
    issue_what_happened="",
    issue_steps_to_reproduce="",
    issue_expected_behavior="",
    attachment_payload=None,
):
    prefs = get_prefs()
    if not is_authenticated(prefs):
        return False, "Planetka Cloud is not connected."

    url = f"{get_api_base_url()}/support/bug-report"
    payload = {
        "report_json": str(report_json_text or ""),
        "report_filename": os.path.basename(str(report_path or "")) or "planetka_bug_report.json",
        "report_path": str(report_path or ""),
        "issue_what_happened": str(issue_what_happened or "").strip(),
        "issue_steps_to_reproduce": str(issue_steps_to_reproduce or "").strip(),
        "issue_expected_behavior": str(issue_expected_behavior or "").strip(),
    }
    if isinstance(attachment_payload, dict):
        payload.update(
            {
                "attachment_filename": str(attachment_payload.get("attachment_filename", "") or "").strip(),
                "attachment_mime": str(attachment_payload.get("attachment_mime", "") or "").strip(),
                "attachment_base64": str(attachment_payload.get("attachment_base64", "") or "").strip(),
                "attachment_size_bytes": int(attachment_payload.get("attachment_size_bytes", 0) or 0),
            }
        )
    body = json.dumps(payload).encode("utf-8")
    headers = dict(get_authorized_headers(prefs=prefs, allow_refresh=True))
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace") if raw else "{}"
            response_payload = json.loads(text or "{}")
            if not bool(response_payload.get("ok", False)):
                error_text = str(response_payload.get("error", "unknown_api_error") or "unknown_api_error")
                return False, error_text
            return True, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace") if raw else ""
        try:
            payload = json.loads(text or "{}")
            error_text = str(payload.get("error", "") or "").strip()
            if error_text:
                return False, f"http_{exc.code}_{error_text}"
        except (TypeError, ValueError):
            pass
        return False, f"http_{exc.code}"
    except urllib.error.URLError as exc:
        return False, f"network_error_{exc.reason}"
    except AuthApiError as exc:
        return False, str(getattr(exc, "error", "") or "auth_error")


def _show_popup_lines(context, title, icon, lines):
    if bool(getattr(bpy.app, "background", False)):
        logger.info("%s: %s", str(title or "Popup"), " | ".join(str(line) for line in (lines or ()) if line))
        return

    wm = getattr(context, "window_manager", None)
    windows = tuple(getattr(wm, "windows", ()) or ()) if wm is not None else ()
    if wm is None or not windows:
        return

    safe_lines = [str(line) for line in lines if line]

    def _draw(self, _context):
        col = self.layout.column(align=True)
        for line in safe_lines:
            col.label(text=line)

    try:
        wm.popup_menu(_draw, title=title, icon=icon)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed opening popup '%s'", title, exc_info=True)


class PLANETKA_OT_ReportBug(bpy.types.Operator):
    bl_idname = "planetka.report_bug"
    bl_label = "Send Feedback"
    bl_description = "Send feedback to Planetka support"

    feedback_text: bpy.props.StringProperty(
        name="Feedback",
        description="Write your feedback",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )

    def invoke(self, context, event):
        del event
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return self.execute(context)
        return wm.invoke_props_dialog(self, width=640)

    def draw(self, context):
        del context
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.label(text="Send quick feedback to Planetka team.")
        feedback_box = layout.box()
        feedback_row = feedback_box.row()
        feedback_row.prop(self, "feedback_text", text="")

    def execute(self, context):
        feedback_text = str(getattr(self, "feedback_text", "") or "").strip()
        if not feedback_text:
            return fail(
                self,
                "Please enter feedback before sending.",
                code=ErrorCode.IO_DEBUG_REPORT_FAILED,
            )

        sent, send_error = _send_bug_report_via_api(
            report_path="",
            report_json_text="{}",
            issue_what_happened=feedback_text,
            issue_steps_to_reproduce="",
            issue_expected_behavior="",
            attachment_payload=None,
        )
        if sent:
            _show_popup_lines(
                context,
                "Feedback Sent",
                "CHECKMARK",
                [
                    "Feedback was sent successfully.",
                    "Thank you.",
                ],
            )
            self.report({'INFO'}, "Feedback sent.")
            return {'FINISHED'}

        fallback_opened = _open_feedback_mail_draft(feedback_text)
        if fallback_opened:
            self.report(
                {'WARNING'},
                f"Feedback email draft opened (API send failed: {send_error or 'unknown_error'}).",
            )
            return {'FINISHED'}

        return fail(
            self,
            f"Feedback send failed: {send_error or 'unknown_error'}",
            code=ErrorCode.IO_DEBUG_REPORT_FAILED,
        )


def _new_scene_health_payload():
    return {
        "errors": [],
        "warnings": [],
        "info": [],
        "checks": [],
    }


def _append_scene_health_check(payload, section, layer, check_id, severity, ok, message, detail=""):
    level = str(severity or "INFO").strip().upper()
    if level not in {"ERROR", "WARNING", "INFO"}:
        level = "INFO"
    entry = {
        "section": str(section or "General"),
        "layer": str(layer or "General"),
        "id": str(check_id or ""),
        "severity": level,
        "ok": bool(ok),
        "message": str(message or "").strip(),
        "detail": str(detail or "").strip(),
    }
    payload["checks"].append(entry)
    if bool(ok):
        return
    if level == "ERROR":
        payload["errors"].append(entry["message"])
    elif level == "WARNING":
        payload["warnings"].append(entry["message"])
    else:
        payload["info"].append(entry["message"])


def _safe_socket(node, socket_name, is_output=False):
    if node is None:
        return None
    sockets = getattr(node, "outputs", None) if bool(is_output) else getattr(node, "inputs", None)
    if sockets is None:
        return None
    try:
        if hasattr(sockets, "get"):
            sock = sockets.get(str(socket_name))
            if sock is not None:
                return sock
    except (TypeError, ValueError, AttributeError, RuntimeError):
        pass
    return None


def _socket_is_linked(node, socket_name, is_output=False):
    sock = _safe_socket(node, socket_name, is_output=is_output)
    if sock is None:
        return False
    try:
        return bool(getattr(sock, "is_linked", False))
    except (TypeError, ValueError, AttributeError, RuntimeError):
        return False


def _find_material_output_node(node_tree):
    if node_tree is None:
        return None
    nodes = getattr(node_tree, "nodes", None)
    if nodes is None:
        return None
    fallback = None
    for node in nodes:
        if str(getattr(node, "type", "")) != "OUTPUT_MATERIAL":
            continue
        if fallback is None:
            fallback = node
        try:
            if bool(getattr(node, "is_active_output", False)):
                return node
        except (TypeError, ValueError, AttributeError, RuntimeError):
            continue
    return fallback


def _find_texture_loading_node(material):
    if material is None or getattr(material, "node_tree", None) is None:
        return None
    nodes = material.node_tree.nodes
    named = nodes.get("Planetka Textures Loading")
    if named is not None:
        return named
    for node in nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        node_tree = getattr(node, "node_tree", None)
        tree_name = str(getattr(node_tree, "name", "") or "").lower()
        if "textures loading group" in tree_name:
            return node
    return None


def _find_surface_grading_node(material):
    if material is None or getattr(material, "node_tree", None) is None:
        return None
    nodes = getattr(material.node_tree, "nodes", None)
    if nodes is None:
        return None
    preferred_name = str(SURFACE_GRADING_GROUP_NAME or "").strip()
    for node in nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        node_tree = getattr(node, "node_tree", None)
        node_tree_name = str(getattr(node_tree, "name", "") or "").strip()
        if node_tree_name == preferred_name or node_tree_name.startswith(f"{preferred_name}."):
            return node
    for node in nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        if _safe_socket(node, "Surface Brightness", is_output=False) is not None:
            return node
    return None


def _iter_view3d_shading_types(context):
    seen = []
    wm = getattr(context, "window_manager", None)
    windows = tuple(getattr(wm, "windows", ()) or ()) if wm is not None else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if str(getattr(area, "type", "")) != "VIEW_3D":
                continue
            for space in tuple(getattr(area, "spaces", ()) or ()):
                if str(getattr(space, "type", "")) != "VIEW_3D":
                    continue
                shading = getattr(space, "shading", None)
                mode = str(getattr(shading, "type", "") or "").strip().upper()
                if mode:
                    seen.append(mode)
    return tuple(seen)


def _normalize_scene_health_path(path_value):
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return ""
    try:
        return os.path.abspath(bpy.path.abspath(raw_path))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return raw_path
    except (RuntimeError, TypeError, ValueError):
        return raw_path


def _node_tree_token(node_tree):
    try:
        return int(node_tree.as_pointer())
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return id(node_tree)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return id(node_tree)


def _collect_image_nodes(node_tree, out_nodes, visited):
    if node_tree is None:
        return
    token = _node_tree_token(node_tree)
    if token in visited:
        return
    visited.add(token)
    nodes = getattr(node_tree, "nodes", None)
    if nodes is None:
        return
    for node in nodes:
        if str(getattr(node, "bl_idname", "") or "") == "ShaderNodeTexImage":
            out_nodes.append(node)
            continue
        if str(getattr(node, "type", "") or "") == "GROUP":
            _collect_image_nodes(getattr(node, "node_tree", None), out_nodes, visited)


def _image_file_path(image):
    if image is None:
        return ""
    return str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()


def _current_texture_path_stats(loading_node):
    stats = {
        "node_count": 0,
        "assigned_count": 0,
        "missing_count": 0,
        "missing_samples": [],
    }
    loading_tree = getattr(loading_node, "node_tree", None) if loading_node is not None else None
    if loading_tree is None:
        return stats
    image_nodes = []
    _collect_image_nodes(loading_tree, image_nodes, visited=set())
    stats["node_count"] = int(len(image_nodes))
    for node in image_nodes:
        image = getattr(node, "image", None)
        raw_path = _image_file_path(image)
        if not raw_path:
            continue
        stats["assigned_count"] += 1
        abs_path = _normalize_scene_health_path(raw_path)
        if abs_path and not os.path.isfile(abs_path):
            stats["missing_count"] += 1
            if len(stats["missing_samples"]) < 8:
                stats["missing_samples"].append(os.path.basename(abs_path) or abs_path)
    return stats


def _iter_planetka_cloud_objects():
    for obj in tuple(getattr(bpy.data, "objects", ()) or ()):
        role = str(obj.get(_CLOUD_ROLE_KEY, "") or "").strip()
        if role in {_GLOBAL_CLOUD_ROLE, _TEXTURE_CLOUD_ROLE, _VDB_CLOUD_ROLE}:
            yield obj, role


def _object_path_prop(obj, prop_names):
    for prop_name in prop_names:
        value = str(obj.get(prop_name, "") or "").strip()
        if value:
            return prop_name, value
        value = str(getattr(obj, prop_name, "") or "").strip()
        if value:
            return prop_name, value
    return "", ""


def _check_path_exists(payload, section, layer, check_id, severity, path_value, ok_message, missing_message):
    raw_path = str(path_value or "").strip()
    if not raw_path:
        _append_scene_health_check(payload, section, layer, check_id, severity, True, ok_message, detail="not loaded yet")
        return
    abs_path = _normalize_scene_health_path(raw_path)
    exists = bool(abs_path and os.path.isfile(abs_path))
    _append_scene_health_check(
        payload,
        section,
        layer,
        check_id,
        severity,
        exists,
        ok_message if exists else missing_message,
        detail=os.path.basename(abs_path) if abs_path else raw_path,
    )


def _camera_earth_diagnostics(scene, earth, camera, props):
    result = {
        "distance_bu": None,
        "radius_bu": None,
        "distance_ratio": None,
        "facing_dot": None,
        "inside_earth": False,
        "surface_margin_bu": None,
        "surface_margin_km": None,
    }
    if scene is None or earth is None or camera is None:
        return result
    try:
        earth_center = Vector(earth.matrix_world.translation)
        camera_pos = Vector(camera.matrix_world.translation)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return result

    radius_bu = None
    try:
        radius_bu = float(getattr(props, "earth_radius_bu", 0.0)) if props is not None else 0.0
    except (TypeError, ValueError, AttributeError):
        radius_bu = 0.0
    if not radius_bu or radius_bu <= 0.0:
        try:
            dims = getattr(earth, "dimensions", None)
            if dims is not None:
                radius_bu = max(float(dims[0]), float(dims[1]), float(dims[2])) * 0.5
        except (TypeError, ValueError, AttributeError):
            radius_bu = 0.0
    radius_bu = max(float(radius_bu or 0.0), 1e-9)

    distance_bu = float((camera_pos - earth_center).length)
    ratio = float(distance_bu / radius_bu)
    surface_margin_bu = float(distance_bu - radius_bu)
    meters_per_bu = float(6371000.0 / max(radius_bu, 1e-9))
    surface_margin_km = float((surface_margin_bu * meters_per_bu) / 1000.0)
    inside_epsilon_bu = float(max(1e-9, radius_bu * 1e-6))
    result["distance_bu"] = distance_bu
    result["radius_bu"] = radius_bu
    result["distance_ratio"] = ratio
    result["surface_margin_bu"] = surface_margin_bu
    result["surface_margin_km"] = surface_margin_km
    # Exact geometry check:
    # positive margin => camera is above surface, negative margin => inside Earth.
    result["inside_earth"] = bool(surface_margin_bu < (-inside_epsilon_bu))

    try:
        forward = Vector((0.0, 0.0, -1.0))
        forward.rotate(camera.matrix_world.to_quaternion())
        to_earth = earth_center - camera_pos
        if to_earth.length > 1e-9 and forward.length > 1e-9:
            result["facing_dot"] = float(forward.normalized().dot(to_earth.normalized()))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        result["facing_dot"] = None
    return result


@dataclass
class _SceneHealthContext:
    context: object
    scene: object
    prefs: object
    props: object
    earth: object
    root: object
    material: object
    sunlight: object
    camera: object


@dataclass
class _SceneHealthMaterialState:
    loading_node: object = None
    surface_grading_node: object = None
    output_node: object = None


def _build_scene_health_context(context):
    scene = getattr(context, "scene", None)
    prefs = get_prefs()
    return _SceneHealthContext(
        context=context,
        scene=scene,
        prefs=prefs,
        props=getattr(scene, "planetka", None) if scene is not None else None,
        earth=get_earth_object(),
        root=bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME),
        material=bpy.data.materials.get(EARTH_MATERIAL_NAME),
        sunlight=bpy.data.objects.get(SUNLIGHT_OBJECT_NAME),
        camera=getattr(scene, "camera", None) if scene is not None else None,
    )


def _check_scene_health_general(ctx, payload):
    has_planetka = not (ctx.earth is None and ctx.root is None and ctx.material is None)
    if not has_planetka:
        payload["info"].append("Earth not created in this scene yet.")
        _append_scene_health_check(
            payload,
            "General",
            "Objects",
            "GENERAL_NO_EARTH",
            "INFO",
            True,
            "Earth is not created in this scene yet.",
        )
        return False

    _append_scene_health_check(
        payload,
        "General",
        "Objects",
        "EARTH_OBJECT",
        "ERROR",
        ctx.earth is not None,
        "Planetka Earth surface object is present." if ctx.earth is not None else "Planetka Earth surface object is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Objects",
        "ROOT_OBJECT",
        "ERROR",
        ctx.root is not None,
        "Planetka Root object is present." if ctx.root is not None else "Planetka Root object is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Material",
        "EARTH_MATERIAL",
        "ERROR",
        ctx.material is not None,
        "Planetka Earth Material is present." if ctx.material is not None else "Planetka Earth Material is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Sunlight",
        "SUNLIGHT_OBJECT",
        "WARNING",
        ctx.sunlight is not None,
        "Planetka Sunlight object is present." if ctx.sunlight is not None else "Planetka Sunlight object is missing.",
    )

    if ctx.camera is None or str(getattr(ctx.camera, "type", "")) != "CAMERA":
        _append_scene_health_check(
            payload,
            "Camera",
            "View",
            "ACTIVE_CAMERA",
            "WARNING",
            False,
            "Active scene camera is missing or invalid.",
        )
    else:
        _append_scene_health_check(
            payload,
            "Camera",
            "View",
            "ACTIVE_CAMERA",
            "INFO",
            True,
            "Active scene camera is available.",
        )
    return True


def _check_scene_health_viewport(ctx, payload):
    shading_types = _iter_view3d_shading_types(ctx.context)
    if not shading_types:
        return
    texture_visible = any(mode in {"MATERIAL", "RENDERED"} for mode in shading_types)
    _append_scene_health_check(
        payload,
        "Viewport",
        "Display",
        "VIEW_MODE_TEXTURE_VISIBLE",
        "WARNING",
        texture_visible,
        (
            "At least one 3D viewport can show Planetka materials."
            if texture_visible
            else "3D viewport is in Solid/Wireframe mode; Planetka materials may not be visible."
        ),
        detail=f"Detected modes: {', '.join(shading_types)}",
    )


def _check_scene_health_material(ctx, payload, state):
    if ctx.earth is not None:
        _append_scene_health_check(
            payload,
            "General",
            "Objects",
            "EARTH_HIDE_VIEWPORT",
            "WARNING",
            not bool(getattr(ctx.earth, "hide_viewport", False)),
            "Earth object is visible in viewport." if not bool(getattr(ctx.earth, "hide_viewport", False)) else "Earth object is hidden in viewport.",
        )
        _append_scene_health_check(
            payload,
            "General",
            "Objects",
            "EARTH_HIDE_RENDER",
            "WARNING",
            not bool(getattr(ctx.earth, "hide_render", False)),
            "Earth object is enabled for render." if not bool(getattr(ctx.earth, "hide_render", False)) else "Earth object is hidden for render.",
        )
        earth_data = getattr(ctx.earth, "data", None)
        material_slots = getattr(earth_data, "materials", None) if earth_data is not None else None
        has_material_slot = bool(material_slots and len(material_slots) > 0 and material_slots[0] is not None)
        _append_scene_health_check(
            payload,
            "Material",
            "Earth Surface",
            "EARTH_MATERIAL_SLOT",
            "ERROR",
            has_material_slot,
            "Earth mesh has an assigned material." if has_material_slot else "Earth mesh material slot is missing.",
        )

    node_tree = getattr(ctx.material, "node_tree", None) if ctx.material is not None else None
    output_node = _find_material_output_node(node_tree)
    loading_node = _find_texture_loading_node(ctx.material)
    surface_grading_node = _find_surface_grading_node(ctx.material)
    state.output_node = output_node
    state.loading_node = loading_node
    state.surface_grading_node = surface_grading_node

    _append_scene_health_check(
        payload,
        "Material",
        "Earth Surface",
        "MATERIAL_NODES",
        "ERROR",
        bool(ctx.material is not None and node_tree is not None),
        "Earth material node tree is available." if node_tree is not None else "Earth material node tree is unavailable.",
    )
    _append_scene_health_check(
        payload,
        "Material",
        "Earth Surface",
        "MATERIAL_OUTPUT_SURFACE",
        "ERROR",
        bool(output_node is not None and _socket_is_linked(output_node, "Surface", is_output=False)),
        "Material Output Surface is connected." if output_node is not None and _socket_is_linked(output_node, "Surface", is_output=False) else "Material Output Surface is not connected.",
    )
    _append_scene_health_check(
        payload,
        "Material",
        "Earth Surface",
        "MATERIAL_OUTPUT_DISPLACEMENT",
        "WARNING",
        bool(output_node is not None and _socket_is_linked(output_node, "Displacement", is_output=False)),
        "Material Output Displacement is connected." if output_node is not None and _socket_is_linked(output_node, "Displacement", is_output=False) else "Material Output Displacement is not connected.",
    )
    _append_scene_health_check(
        payload,
        "Material",
        "Earth Surface",
        "TEXTURE_LOADING_GROUP",
        "ERROR",
        bool(loading_node is not None and getattr(loading_node, "node_tree", None) is not None),
        "Planetka Textures Loading Group is present." if loading_node is not None and getattr(loading_node, "node_tree", None) is not None else "Planetka Textures Loading Group is missing.",
    )

    if loading_node is not None and getattr(loading_node, "node_tree", None) is not None:
        for output_name in ("S2", "EL", "WT", "SE"):
            socket_exists = _safe_socket(loading_node, output_name, is_output=True) is not None
            _append_scene_health_check(
                payload,
                "Material",
                "Texture Loading",
                f"TEXTURE_OUTPUT_{output_name}",
                "ERROR",
                socket_exists,
                f"Texture Loading output '{output_name}' exists." if socket_exists else f"Texture Loading output '{output_name}' is missing.",
            )

    _append_scene_health_check(
        payload,
        "Material",
        "Earth Surface",
        "SURFACE_GRADING_GROUP",
        "WARNING",
        surface_grading_node is not None,
        "Planetka Surface Grading Group is present." if surface_grading_node is not None else "Planetka Surface Grading Group is missing.",
    )

    nightday_groups = []
    for group in getattr(bpy.data, "node_groups", ()):
        name = str(getattr(group, "name", "") or "")
        if name == str(NIGHTDAY_GROUP_NAME) or name.startswith(f"{str(NIGHTDAY_GROUP_NAME)}."):
            nightday_groups.append(group)
    _append_scene_health_check(
        payload,
        "Material",
        "Night Lights",
        "NIGHTDAY_GROUP_PRESENT",
        "WARNING",
        bool(nightday_groups),
        "Planetka NightDay Transition Group is present." if nightday_groups else "Planetka NightDay Transition Group is missing.",
    )


def _check_scene_health_texture_paths(_ctx, payload, state):
    stats = _current_texture_path_stats(state.loading_node)
    _append_scene_health_check(
        payload,
        "Texture Paths",
        "Earth Textures",
        "TEXTURE_IMAGE_NODES",
        "WARNING",
        int(stats.get("node_count", 0)) > 0,
        (
            f"Current texture image nodes detected: {int(stats.get('node_count', 0))}."
            if int(stats.get("node_count", 0)) > 0
            else "No current texture image nodes detected in Planetka Textures Loading Group."
        ),
        detail=f"assigned_paths={int(stats.get('assigned_count', 0))}",
    )
    missing_count = int(stats.get("missing_count", 0))
    samples = list(stats.get("missing_samples", ()) or ())
    _append_scene_health_check(
        payload,
        "Texture Paths",
        "Earth Textures",
        "TEXTURE_PATHS_EXIST",
        "ERROR",
        missing_count == 0,
        "Current Earth texture file paths exist on disk." if missing_count == 0 else f"{missing_count} current Earth texture file path(s) are missing on disk.",
        detail=", ".join(samples),
    )


def _check_scene_health_clouds(ctx, payload):
    cloud_entries = list(_iter_planetka_cloud_objects())
    role_counts = {
        _GLOBAL_CLOUD_ROLE: 0,
        _TEXTURE_CLOUD_ROLE: 0,
        _VDB_CLOUD_ROLE: 0,
    }
    for _obj, role in cloud_entries:
        role_counts[role] = int(role_counts.get(role, 0)) + 1
    _append_scene_health_check(
        payload,
        "Clouds",
        "Objects",
        "CLOUD_OBJECT_COUNTS",
        "INFO",
        True,
        (
            "Cloud objects found."
            if cloud_entries
            else "No Planetka cloud objects found."
        ),
        detail=(
            f"global={role_counts[_GLOBAL_CLOUD_ROLE]}, "
            f"texture_based={role_counts[_TEXTURE_CLOUD_ROLE]}, "
            f"vdb={role_counts[_VDB_CLOUD_ROLE]}"
        ),
    )

    render_engine = str(getattr(getattr(ctx.scene, "render", None), "engine", "") or "").upper()
    for obj, role in cloud_entries:
        name = str(getattr(obj, "name", "") or "Cloud")
        layer = "Global Clouds" if role == _GLOBAL_CLOUD_ROLE else ("Texture-Based Clouds" if role == _TEXTURE_CLOUD_ROLE else "VDB Clouds")
        _append_scene_health_check(
            payload,
            "Clouds",
            layer,
            f"{name}_VISIBLE",
            "WARNING",
            not bool(getattr(obj, "hide_viewport", False)) and not bool(getattr(obj, "hide_render", False)),
            f"{name} is visible." if not bool(getattr(obj, "hide_viewport", False)) and not bool(getattr(obj, "hide_render", False)) else f"{name} is hidden in viewport or render.",
        )

        if role in {_GLOBAL_CLOUD_ROLE, _TEXTURE_CLOUD_ROLE}:
            data = getattr(obj, "data", None)
            materials = getattr(data, "materials", None) if data is not None else None
            has_material = bool(materials and len(materials) > 0 and materials[0] is not None)
            _append_scene_health_check(
                payload,
                "Clouds",
                layer,
                f"{name}_MATERIAL",
                "WARNING",
                has_material,
                f"{name} has a material assigned." if has_material else f"{name} material is missing.",
            )
            if role == _TEXTURE_CLOUD_ROLE:
                _prop_name, texture_path = _object_path_prop(obj, _TEXTURE_CLOUD_PATH_PROPS)
                _check_path_exists(
                    payload,
                    "Clouds",
                    layer,
                    f"{name}_TEXTURE_PATH",
                    "WARNING",
                    texture_path,
                    f"{name} texture path is available.",
                    f"{name} texture path is missing on disk.",
                )
            continue

        if role == _VDB_CLOUD_ROLE:
            _prop_name, vdb_path = _object_path_prop(obj, _VDB_CLOUD_PATH_PROPS)
            _check_path_exists(
                payload,
                "Clouds",
                layer,
                f"{name}_VDB_PATH",
                "ERROR",
                vdb_path,
                f"{name} VDB file path is available.",
                f"{name} VDB file path is missing on disk.",
            )
            _append_scene_health_check(
                payload,
                "Render",
                "VDB Clouds",
                f"{name}_RENDER_ENGINE",
                "WARNING",
                render_engine == "CYCLES",
                f"{name} is compatible with the current render engine." if render_engine == "CYCLES" else f"{name} is a VDB cloud; switch to Cycles to render it.",
                detail=f"render_engine={render_engine or 'UNKNOWN'}",
            )


def _check_scene_health_render_engine(ctx, payload):
    render_engine = str(getattr(getattr(ctx.scene, "render", None), "engine", "") or "").upper()
    supported = render_engine == "CYCLES" or render_engine.startswith("BLENDER_EEVEE") or render_engine == "BLENDER_EEVEE_NEXT"
    _append_scene_health_check(
        payload,
        "Render",
        "Engine",
        "RENDER_ENGINE_SUPPORTED",
        "WARNING",
        supported,
        "Render engine is supported by Planetka." if supported else "Current render engine is not a standard Planetka target.",
        detail=f"render_engine={render_engine or 'UNKNOWN'}",
    )


def _check_scene_health_camera(ctx, payload):
    if ctx.camera is None or ctx.earth is None:
        return
    cam_diag = _camera_earth_diagnostics(ctx.scene, ctx.earth, ctx.camera, ctx.props)
    ratio = cam_diag.get("distance_ratio")
    distance_bu = cam_diag.get("distance_bu")
    radius_bu = cam_diag.get("radius_bu")
    facing_dot = cam_diag.get("facing_dot")
    surface_margin_bu = cam_diag.get("surface_margin_bu")
    surface_margin_km = cam_diag.get("surface_margin_km")
    inside_earth = bool(cam_diag.get("inside_earth", False))
    margin_detail_parts = []
    if isinstance(surface_margin_bu, float):
        margin_detail_parts.append(f"surface_margin={surface_margin_bu:.6f} BU")
    if isinstance(surface_margin_km, float):
        margin_detail_parts.append(f"~{surface_margin_km:.2f} km")
    _append_scene_health_check(
        payload,
        "Camera",
        "Earth Visibility",
        "CAMERA_INSIDE_EARTH",
        "ERROR",
        not inside_earth,
        "Camera is outside Earth geometry." if not inside_earth else "Camera is inside Earth geometry.",
        detail=(", ".join(margin_detail_parts) if margin_detail_parts else ""),
    )
    if isinstance(ratio, float):
        ratio_ok = ratio < float(_HEALTH_CAMERA_DISTANCE_RATIO_WARN)
        severity = "WARNING"
        if ratio >= float(_HEALTH_CAMERA_DISTANCE_RATIO_ERROR):
            severity = "ERROR"
            ratio_ok = False
        _append_scene_health_check(
            payload,
            "Camera",
            "Earth Visibility",
            "CAMERA_DISTANCE",
            severity,
            ratio_ok,
            "Camera distance is within a typical visible range." if ratio_ok else "Camera is very far from Earth; Earth may be effectively invisible.",
            detail=(
                f"distance={distance_bu:.3f} BU, radius={radius_bu:.3f} BU, ratio={ratio:.1f}"
                if isinstance(distance_bu, float) and isinstance(radius_bu, float)
                else ""
            ),
        )
    if isinstance(facing_dot, float):
        _append_scene_health_check(
            payload,
            "Camera",
            "Earth Visibility",
            "CAMERA_FACING",
            "WARNING",
            facing_dot >= float(_HEALTH_MIN_FACING_DOT_WARN),
            (
                "Camera is facing Earth."
                if facing_dot >= float(_HEALTH_MIN_FACING_DOT_WARN)
                else "Camera is not facing Earth strongly; Earth may be out of view."
            ),
            detail=f"dot={facing_dot:.3f}",
        )
    cam_data = getattr(ctx.camera, "data", None)
    if cam_data is not None and isinstance(distance_bu, float) and isinstance(radius_bu, float):
        try:
            clip_end = float(getattr(cam_data, "clip_end", 0.0))
        except (TypeError, ValueError, AttributeError):
            clip_end = 0.0
        target_distance = max(0.0, float(distance_bu - radius_bu))
        _append_scene_health_check(
            payload,
            "Camera",
            "Earth Visibility",
            "CAMERA_CLIP_END",
            "WARNING",
            clip_end <= 0.0 or clip_end >= target_distance,
            "Camera clip end can reach Earth." if clip_end <= 0.0 or clip_end >= target_distance else "Camera clip end may cut Earth from view.",
            detail=f"clip_end={clip_end:.3f}, required>={target_distance:.3f}",
        )


_SCENE_HEALTH_CHECK_REGISTRY = (
    (_check_scene_health_viewport, False),
    (_check_scene_health_material, True),
    (_check_scene_health_texture_paths, True),
    (_check_scene_health_clouds, False),
    (_check_scene_health_render_engine, False),
    (_check_scene_health_camera, False),
)



def collect_scene_health_data(context):
    ctx = _build_scene_health_context(context)
    payload = _new_scene_health_payload()
    if not _check_scene_health_general(ctx, payload):
        return payload

    state = _SceneHealthMaterialState()
    for checker, uses_state in _SCENE_HEALTH_CHECK_REGISTRY:
        if uses_state:
            checker(ctx, payload, state)
        else:
            checker(ctx, payload)
    return payload


def _draw_scene_health_report_layout(layout, health, title_text="Scene Health Check"):
    checks = list(health.get("checks", ()) or ())
    errors = list(health.get("errors", ()) or ())
    warnings = list(health.get("warnings", ()) or ())
    info = list(health.get("info", ()) or ())

    summary = layout.box()
    summary.label(text=str(title_text or "Scene Health Check"), icon="CHECKMARK")
    summary_row = summary.row()
    summary_row.alert = bool(errors or warnings)
    summary_parts = [f"Errors: {len(errors)}", f"Warnings: {len(warnings)}"]
    if info:
        summary_parts.append(f"Notes: {len(info)}")
    summary_row.label(text=" | ".join(summary_parts))

    if info:
        notes_box = layout.box()
        notes_box.label(text="Notes", icon="INFO")
        seen_notes = set()
        for note in info:
            note_text = str(note or "").strip()
            if not note_text or note_text in seen_notes:
                continue
            seen_notes.add(note_text)
            notes_box.label(text=note_text, icon="BLANK1")

    section_labels = {
        "General": "Scene Objects",
        "Viewport": "Viewport",
        "Camera": "Camera",
        "Material": "Materials",
        "Texture Paths": "Loaded Texture Paths",
        "Clouds": "Clouds",
        "Render": "Render Compatibility",
    }

    grouped = {}
    for check in checks:
        section = str(check.get("section", "General") or "General")
        grouped.setdefault(section, []).append(check)

    section_order = (
        "General",
        "Viewport",
        "Camera",
        "Material",
        "Texture Paths",
        "Clouds",
        "Render",
    )
    rendered_sections = set()
    for section_name in section_order:
        entries = grouped.get(section_name, [])
        if not entries:
            continue
        rendered_sections.add(section_name)
        box = layout.box()
        box.label(text=section_labels.get(section_name, section_name))
        for entry in entries:
            ok = bool(entry.get("ok", False))
            severity = str(entry.get("severity", "INFO") or "INFO").upper()
            layer = str(entry.get("layer", "General") or "General")
            check_id = str(entry.get("id", "") or "").strip()
            message = str(entry.get("message", "") or "").strip()
            detail = str(entry.get("detail", "") or "").strip()
            if ok:
                icon = "CHECKMARK"
            elif severity == "ERROR":
                icon = "ERROR"
            elif severity == "WARNING":
                icon = "QUESTION"
            else:
                icon = "INFO"
            label = f"[{layer}] {message}" if layer else message
            if check_id:
                label = f"{check_id}: {label}"
            emphasize = (not ok) and severity in {"WARNING", "ERROR", "CRITICAL", "IMPORTANT"}
            label_row = box.row()
            label_row.alert = bool(emphasize)
            label_row.label(text=label, icon=icon)
            if detail:
                detail_row = box.row()
                detail_row.scale_y = 0.85
                detail_row.alert = bool(emphasize)
                detail_row.label(text=f"  {detail}", icon="BLANK1")

    remaining_sections = [name for name in grouped.keys() if name not in rendered_sections]
    for section_name in remaining_sections:
        entries = grouped.get(section_name, [])
        if not entries:
            continue
        box = layout.box()
        box.label(text=section_name)
        for entry in entries:
            ok = bool(entry.get("ok", False))
            severity = str(entry.get("severity", "INFO") or "INFO").upper()
            icon = "CHECKMARK" if ok else ("ERROR" if severity == "ERROR" else "QUESTION")
            message = str(entry.get("message", "") or "").strip()
            emphasize = (not ok) and severity in {"WARNING", "ERROR", "CRITICAL", "IMPORTANT"}
            row = box.row()
            row.alert = bool(emphasize)
            row.label(text=message, icon=icon)


class PLANETKA_OT_SceneHealthCheck(bpy.types.Operator):
    bl_idname = "planetka.scene_health_check"
    bl_label = "Scene Health Check"
    bl_description = "Check current Planetka scene objects, materials, textures, clouds, camera, and render compatibility"

    _health = None

    def invoke(self, context, event):
        del event
        self._health = collect_scene_health_data(context)
        wm = getattr(context, "window_manager", None)
        if wm is None or bool(getattr(bpy.app, "background", False)):
            return self.execute(context)
        return wm.invoke_props_dialog(self, width=860)

    def draw(self, context):
        del context
        layout = self.layout
        health = self._health if isinstance(self._health, dict) else {}
        _draw_scene_health_report_layout(layout, health, title_text="Scene Health Check")

    def execute(self, context):
        health = self._health if isinstance(self._health, dict) else collect_scene_health_data(context)
        errors = int(len(list(health.get("errors", ()) or ())))
        warnings = int(len(list(health.get("warnings", ()) or ())))
        if errors > 0:
            self.report({'ERROR'}, f"Scene Health Check found {errors} error(s), {warnings} warning(s).")
        elif warnings > 0:
            self.report({'WARNING'}, f"Scene Health Check found {warnings} warning(s).")
        else:
            self.report({'INFO'}, "Scene Health Check passed.")
        return {'FINISHED'}
