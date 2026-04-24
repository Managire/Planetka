import json
import logging
import math
import os
import platform
import re
import sys
import base64
import mimetypes
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
from .sanity_utils import invalidate_texture_source_health_cache, validate_known_good_texture_source
from .asset_builder import (
    EARTH_MATERIAL_NAME,
    NIGHTDAY_GROUP_NAME,
    PLANETKA_ROOT_OBJECT_NAME,
    SUNLIGHT_OBJECT_NAME,
    SURFACE_GRADING_GROUP_NAME,
)
from .r2_source import is_remote_source_configured

logger = logging.getLogger(__name__)

_BUG_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
_BUG_ATTACHMENT_ALLOWED_MIME = {
    "image/png",
    "image/jpeg",
    "image/webp",
}
_ANIMATION_PREPARED_SEGMENTS_KEY = "planetka_anim_prepared_segments"
_ANIMATION_PREPARED_COLLECTION_NAME = "Planetka Animation Preview"
_ANIMATION_PREPARED_COLLECTION_NAMES_LEGACY = ("Planetka Animation Prepared",)
_HEALTH_CAMERA_DISTANCE_RATIO_WARN = 50000.0
_HEALTH_CAMERA_DISTANCE_RATIO_ERROR = 120000.0
_HEALTH_MIN_FACING_DOT_WARN = 0.15
_HEALTH_DICING_WARN_THRESHOLD = 2.0
_HEALTH_DICING_RECOMMENDED_MIN = 1.25
_HEALTH_DICING_RECOMMENDED_MAX = 1.5
_HEALTH_LAYER_FALLBACK_FILES = {
    "S2": {"ocean_pixel_final_20.exr", "white_pixel_20.exr"},
    "EL": {"black_pixel_20.exr", "el_south_cap_pixel_20.exr"},
    "WT": {"blue_pixel_20.exr", "black_pixel_20.exr"},
    "PO": {"black_pixel_20.exr"},
}


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
        return False, "Account is not connected."

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
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed opening popup '%s'", title, exc_info=True)


class PLANETKA_OT_ReportBug(bpy.types.Operator):
    bl_idname = "planetka.report_bug"
    bl_label = "Report Bug"
    bl_description = "Describe the issue and send a compact debug report JSON to Planetka support"

    issue_what_happened: bpy.props.StringProperty(
        name="What happened",
        description="Describe what went wrong",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )
    issue_steps_to_reproduce: bpy.props.StringProperty(
        name="Steps to reproduce",
        description="How we can reproduce this issue",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )
    issue_expected_behavior: bpy.props.StringProperty(
        name="Expected behavior",
        description="What you expected to happen",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )
    attachment_file: bpy.props.StringProperty(
        name="Attachment",
        description="Optional screenshot/image attachment (PNG/JPG/WEBP, max 10 MB)",
        default="",
        subtype='FILE_PATH',
        options={'TEXTEDIT_UPDATE'},
    )

    def invoke(self, context, event):
        del event
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return self.execute(context)
        return wm.invoke_props_dialog(self, width=760)

    def draw(self, context):
        del context
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.label(text="Describe the issue before sending.")

        what_box = layout.box()
        what_box.label(text="What happened")
        what_row = what_box.row()
        what_row.scale_y = 1.0
        what_row.prop(self, "issue_what_happened", text="")

        steps_box = layout.box()
        steps_box.label(text="Steps to reproduce")
        steps_row = steps_box.row()
        steps_row.scale_y = 1.0
        steps_row.prop(self, "issue_steps_to_reproduce", text="")

        expected_box = layout.box()
        expected_box.label(text="Expected behavior")
        expected_row = expected_box.row()
        expected_row.scale_y = 1.0
        expected_row.prop(self, "issue_expected_behavior", text="")

        attachment_box = layout.box()
        attachment_box.label(text="Attachment (optional screenshot/image)")
        attachment_row = attachment_box.row()
        attachment_row.prop(self, "attachment_file", text="")

    def execute(self, context):
        target_path = _default_bug_report_path()
        try:
            report = _build_minimal_report(context)
            report_json_text = json.dumps(report, indent=2, sort_keys=False)
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(report_json_text)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Report Bug failed while exporting debug report: {exc}",
                code=ErrorCode.IO_DEBUG_REPORT_FAILED,
            )
        except (OSError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Report Bug failed while exporting debug report: {exc}",
                code=ErrorCode.IO_DEBUG_REPORT_FAILED,
            )

        report_path_abs = os.path.abspath(target_path)
        issue_what = str(getattr(self, "issue_what_happened", "") or "").strip()
        issue_steps = str(getattr(self, "issue_steps_to_reproduce", "") or "").strip()
        issue_expected = str(getattr(self, "issue_expected_behavior", "") or "").strip()
        attachment_payload, attachment_error = _encode_optional_bug_attachment(
            str(getattr(self, "attachment_file", "") or "").strip()
        )
        if attachment_error:
            attachment_error_messages = {
                "attachment_not_found": "Attachment file was not found.",
                "attachment_unreadable": "Attachment file could not be read.",
                "attachment_empty": "Attachment file is empty.",
                "attachment_too_large": "Attachment exceeds 10 MB limit.",
                "attachment_unsupported_type": "Attachment must be PNG, JPG/JPEG, or WEBP.",
            }
            return fail(
                self,
                attachment_error_messages.get(attachment_error, "Invalid attachment."),
                code=ErrorCode.IO_DEBUG_REPORT_FAILED,
            )
        sent, send_error = _send_bug_report_via_api(
            report_path_abs,
            report_json_text,
            issue_what_happened=issue_what,
            issue_steps_to_reproduce=issue_steps,
            issue_expected_behavior=issue_expected,
            attachment_payload=attachment_payload,
        )
        if sent:
            _show_popup_lines(
                context,
                "Report Sent",
                "CHECKMARK",
                [
                    "Planetka bug report was sent successfully.",
                    "Thank you for reporting the issue.",
                ],
            )
            self.report({'INFO'}, "Bug report sent with attached JSON report.")
            return {'FINISHED'}

        fallback_opened = _open_bug_mail_draft(
            report_path_abs,
            report_json_text,
            issue_what_happened=issue_what,
            issue_steps_to_reproduce=issue_steps,
            issue_expected_behavior=issue_expected,
            attachment_path=(attachment_payload or {}).get("attachment_path", ""),
        )
        if fallback_opened:
            self.report(
                {'WARNING'},
                f"Bug report email draft opened (API send failed: {send_error or 'unknown_error'}).",
            )
            return {'FINISHED'}

        return fail(
            self,
            f"Bug report send failed: {send_error or 'unknown_error'}",
            code=ErrorCode.IO_DEBUG_REPORT_FAILED,
        )


class PLANETKA_OT_ValidateTextureSource(bpy.types.Operator):
    bl_idname = "planetka.validate_texture_source"
    bl_label = "Validate Texture Source"
    bl_description = "Validate Planetka cloud source access and sentinel availability"

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
            )

        details = validate_known_good_texture_source(getattr(prefs, "texture_base_path", ""))
        normalized_path = details.get("normalized_path", "")
        if normalized_path:
            prefs.texture_base_path = normalized_path
            invalidate_texture_source_health_cache(normalized_path)

        issues = details.get("issues", [])
        has_errors = any(level == "ERROR" for level, _code, _message in issues)
        has_warnings = any(level == "WARNING" for level, _code, _message in issues)

        lines = []
        if normalized_path:
            lines.append(f"Path: {normalized_path}")
        else:
            lines.append("Path: <not set>")

        folder_counts = details.get("folder_counts", {})
        for folder_name in ("S2", "EL", "WT", "PO"):
            count = int(folder_counts.get(folder_name, 0))
            lines.append(f"{folder_name} files: {count}")

        present = details.get("known_good_s2_present", [])
        missing = details.get("known_good_s2_missing", [])
        if present:
            lines.append(f"S2 sentinels found: {len(present)}/2")
        if missing:
            lines.append(f"S2 sentinels missing: {len(missing)}/2")

        if issues:
            for level, _code, message in issues[:4]:
                lines.append(f"{level}: {message}")
            if len(issues) > 4:
                lines.append(f"... and {len(issues) - 4} more issue(s)")
        else:
            lines.append("No cloud-source issues detected.")

        if has_errors:
            _show_popup_lines(context, "Texture Source Check", "ERROR", lines)
            self.report({'ERROR'}, "Texture source validation found blocking issues.")
        elif has_warnings:
            _show_popup_lines(context, "Texture Source Check", "QUESTION", lines)
            self.report({'WARNING'}, "Texture source validation finished with warnings.")
        else:
            _show_popup_lines(context, "Texture Source Check", "CHECKMARK", lines)
            self.report({'INFO'}, "Texture source validation passed.")
        return {'FINISHED'}


def _is_planetka_runtime_image(image):
    if image is None:
        return False
    try:
        name = str(getattr(image, "name", "") or "").strip().upper()
    except (TypeError, ValueError, AttributeError):
        name = ""
    if name.startswith(("S2_", "EL_", "WT_", "PO_")):
        return True
    try:
        raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
    except (TypeError, ValueError, AttributeError):
        raw_path = ""
    if not raw_path:
        return False
    return "planetka_cache" in raw_path.replace("\\", "/").lower()


def _is_missing_file_image(image):
    if image is None:
        return False
    if getattr(image, "packed_file", None) is not None:
        return False
    try:
        raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
    except (TypeError, ValueError, AttributeError):
        return False
    if not raw_path:
        return False
    try:
        absolute = os.path.abspath(bpy.path.abspath(raw_path))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return False
    if not absolute:
        return False
    return not os.path.isfile(absolute)


def _camera_has_transform_keys(camera):
    if camera is None:
        return False
    animation_data = getattr(camera, "animation_data", None)
    action = getattr(animation_data, "action", None) if animation_data is not None else None
    if action is None:
        return False
    fcurves = getattr(action, "fcurves", None) or ()
    for fcurve in fcurves:
        data_path = str(getattr(fcurve, "data_path", "") or "")
        if data_path not in {"location", "rotation_euler"}:
            continue
        points = getattr(fcurve, "keyframe_points", None)
        if points and len(points) > 0:
            return True
    return False


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


def _socket_float_value(node, socket_name):
    sock = _safe_socket(node, socket_name, is_output=False)
    if sock is None:
        return None
    try:
        value = getattr(sock, "default_value", None)
        if isinstance(value, (list, tuple)):
            return None
        return float(value)
    except (TypeError, ValueError, AttributeError, RuntimeError):
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


def _layer_from_image_node_name(node_name):
    token = str(node_name or "").strip().upper()
    if not token:
        return ""
    for layer in ("S2", "EL", "WT", "PO"):
        if token == layer:
            return layer
        if f"_{layer}" in token:
            return layer
        if token.startswith(f"{layer}_"):
            return layer
        if token.endswith(f" {layer}"):
            return layer
    if "SE" in token:
        return "PO"
    return ""


def _collect_layer_image_nodes(node_tree, out_map, visited):
    if node_tree is None:
        return
    try:
        ptr = int(node_tree.as_pointer())
    except (TypeError, ValueError, AttributeError, RuntimeError):
        ptr = None
    if ptr is not None:
        if ptr in visited:
            return
        visited.add(ptr)
    nodes = getattr(node_tree, "nodes", None)
    if nodes is None:
        return
    for node in nodes:
        node_type = str(getattr(node, "bl_idname", "") or "")
        if node_type == "ShaderNodeTexImage":
            layer = _layer_from_image_node_name(getattr(node, "name", ""))
            if not layer:
                layer = _layer_from_image_node_name(getattr(node, "label", ""))
            if layer:
                out_map.setdefault(layer, []).append(node)
            continue
        if str(getattr(node, "type", "")) == "GROUP":
            child_tree = getattr(node, "node_tree", None)
            if child_tree is not None:
                _collect_layer_image_nodes(child_tree, out_map, visited)


def _tile_loading_layer_stats(loading_node):
    stats = {
        layer: {
            "node_count": 0,
            "image_count": 0,
            "missing_path_count": 0,
            "fallback_count": 0,
            "non_fallback_count": 0,
        }
        for layer in ("S2", "EL", "WT", "PO")
    }
    if loading_node is None:
        return stats
    loading_tree = getattr(loading_node, "node_tree", None)
    if loading_tree is None:
        return stats
    collected = {}
    _collect_layer_image_nodes(loading_tree, collected, visited=set())
    for layer, nodes in collected.items():
        if layer not in stats:
            continue
        layer_stats = stats[layer]
        layer_stats["node_count"] = int(len(nodes))
        for img_node in nodes:
            image = getattr(img_node, "image", None)
            if image is None:
                continue
            layer_stats["image_count"] += 1
            raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
            file_name = str(os.path.basename(raw_path)).strip().lower()
            if file_name in _HEALTH_LAYER_FALLBACK_FILES.get(layer, set()):
                layer_stats["fallback_count"] += 1
            elif file_name:
                layer_stats["non_fallback_count"] += 1
            if raw_path:
                try:
                    abs_path = os.path.abspath(bpy.path.abspath(raw_path))
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                    abs_path = ""
                if abs_path and not os.path.isfile(abs_path):
                    layer_stats["missing_path_count"] += 1
    return stats


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
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        result["facing_dot"] = None
    return result


def collect_scene_health_data(context):
    scene = getattr(context, "scene", None)
    prefs = get_prefs()
    props = getattr(scene, "planetka", None) if scene is not None else None
    payload = _new_scene_health_payload()

    earth = get_earth_object()
    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    material = bpy.data.materials.get(EARTH_MATERIAL_NAME)
    sunlight = bpy.data.objects.get(SUNLIGHT_OBJECT_NAME)
    camera = getattr(scene, "camera", None) if scene is not None else None

    # General object/material presence.
    has_planetka = not (earth is None and root is None and material is None)
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
        return payload

    _append_scene_health_check(
        payload,
        "General",
        "Objects",
        "EARTH_OBJECT",
        "ERROR",
        earth is not None,
        "Planetka Earth surface object is present." if earth is not None else "Planetka Earth surface object is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Objects",
        "ROOT_OBJECT",
        "ERROR",
        root is not None,
        "Planetka Root object is present." if root is not None else "Planetka Root object is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Material",
        "EARTH_MATERIAL",
        "ERROR",
        material is not None,
        "Planetka Earth Material is present." if material is not None else "Planetka Earth Material is missing.",
    )
    _append_scene_health_check(
        payload,
        "General",
        "Sunlight",
        "SUNLIGHT_OBJECT",
        "WARNING",
        sunlight is not None,
        "Planetka Sunlight object is present." if sunlight is not None else "Planetka Sunlight object is missing.",
    )

    if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
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

    # Data source and runtime image health.
    base_path = str(getattr(prefs, "texture_base_path", "") or "").strip() if prefs is not None else ""
    remote_ready = bool(is_remote_source_configured(base_path))
    if remote_ready:
        payload["info"].append("Data source: Cloud.")
        _append_scene_health_check(
            payload,
            "General",
            "Data Source",
            "SOURCE_REMOTE",
            "INFO",
            True,
            "Cloud source is configured.",
        )
    else:
        if not base_path:
            _append_scene_health_check(
                payload,
                "General",
                "Data Source",
                "SOURCE_PATH_EMPTY",
                "ERROR",
                False,
                "Texture source path is empty.",
            )
        else:
            try:
                normalized_base_path = os.path.abspath(bpy.path.abspath(base_path))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                normalized_base_path = ""
            is_valid_path = bool(normalized_base_path and os.path.isdir(normalized_base_path))
            _append_scene_health_check(
                payload,
                "General",
                "Data Source",
                "SOURCE_PATH_VALID",
                "ERROR",
                is_valid_path,
                (
                    f"Texture source path is valid: {normalized_base_path}"
                    if is_valid_path
                    else "Texture source path is invalid or missing on disk."
                ),
            )
            if is_valid_path:
                payload["info"].append(f"Data source: {normalized_base_path}")

    missing_runtime_images = 0
    for image in tuple(getattr(bpy.data, "images", ())):
        if not _is_planetka_runtime_image(image):
            continue
        if _is_missing_file_image(image):
            missing_runtime_images += 1
    _append_scene_health_check(
        payload,
        "General",
        "Runtime Images",
        "RUNTIME_IMAGE_PATHS",
        "WARNING",
        int(missing_runtime_images) == 0,
        (
            "All Planetka runtime image paths exist on disk."
            if int(missing_runtime_images) == 0
            else f"{int(missing_runtime_images)} Planetka runtime image file(s) are missing on disk."
        ),
    )

    # Viewport shading visibility checks.
    shading_types = _iter_view3d_shading_types(context)
    preview_visible = any(mode in {"MATERIAL", "RENDERED"} for mode in shading_types)
    _append_scene_health_check(
        payload,
        "Viewport",
        "Display",
        "VIEW_MODE_TEXTURE_VISIBLE",
        "WARNING",
        preview_visible,
        (
            "At least one 3D viewport is in Material Preview/Rendered mode."
            if preview_visible
            else "No 3D viewport is in Material Preview/Rendered mode; textures may appear hidden."
        ),
        detail=f"Detected modes: {', '.join(shading_types) if shading_types else 'none'}",
    )

    # Earth object visibility.
    if earth is not None:
        _append_scene_health_check(
            payload,
            "General",
            "Objects",
            "EARTH_HIDE_VIEWPORT",
            "WARNING",
            not bool(getattr(earth, "hide_viewport", False)),
            (
                "Earth object is visible in viewport."
                if not bool(getattr(earth, "hide_viewport", False))
                else "Earth object is hidden in viewport."
            ),
        )
        _append_scene_health_check(
            payload,
            "General",
            "Objects",
            "EARTH_HIDE_RENDER",
            "WARNING",
            not bool(getattr(earth, "hide_render", False)),
            (
                "Earth object is enabled for render."
                if not bool(getattr(earth, "hide_render", False))
                else "Earth object is hidden for render."
            ),
        )
        earth_data = getattr(earth, "data", None)
        material_slots = getattr(earth_data, "materials", None) if earth_data is not None else None
        has_material_slot = bool(material_slots and len(material_slots) > 0 and material_slots[0] is not None)
        _append_scene_health_check(
            payload,
            "Material",
            "General",
            "EARTH_MATERIAL_SLOT",
            "ERROR",
            has_material_slot,
            "Earth mesh has an assigned material slot." if has_material_slot else "Earth mesh material slot is missing.",
        )

    # Material pipeline checks.
    loading_node = _find_texture_loading_node(material)
    surface_grading_node = _find_surface_grading_node(material)
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    output_node = _find_material_output_node(node_tree)

    _append_scene_health_check(
        payload,
        "Material",
        "General",
        "MATERIAL_NODES",
        "ERROR",
        bool(material is not None and bool(getattr(material, "use_nodes", False)) and node_tree is not None),
        (
            "Material node tree is available."
            if material is not None and bool(getattr(material, "use_nodes", False)) and node_tree is not None
            else "Material nodes are disabled or missing."
        ),
    )
    _append_scene_health_check(
        payload,
        "Material",
        "General",
        "MATERIAL_OUTPUT_SURFACE",
        "ERROR",
        bool(output_node is not None and _socket_is_linked(output_node, "Surface", is_output=False)),
        (
            "Material Output Surface is connected."
            if output_node is not None and _socket_is_linked(output_node, "Surface", is_output=False)
            else "Material Output Surface is not connected."
        ),
    )
    _append_scene_health_check(
        payload,
        "Tile Loading",
        "General",
        "LOADING_GROUP_NODE",
        "ERROR",
        loading_node is not None and getattr(loading_node, "node_tree", None) is not None,
        (
            "Planetka Textures Loading group node is present."
            if loading_node is not None and getattr(loading_node, "node_tree", None) is not None
            else "Planetka Textures Loading group node is missing."
        ),
    )

    if loading_node is not None and getattr(loading_node, "node_tree", None) is not None:
        for output_name, layer_name in (("S2", "S2"), ("EL", "EL"), ("WT", "WT"), ("SE", "PO")):
            _append_scene_health_check(
                payload,
                "Tile Loading",
                layer_name,
                f"LOADING_OUTPUT_{output_name}",
                "ERROR",
                _safe_socket(loading_node, output_name, is_output=True) is not None,
                (
                    f"Tile Loading output '{output_name}' exists."
                    if _safe_socket(loading_node, output_name, is_output=True) is not None
                    else f"Tile Loading output '{output_name}' is missing."
                ),
            )

    # Layer image assignment/fallback checks.
    layer_stats = _tile_loading_layer_stats(loading_node)
    for layer in ("S2", "EL", "WT", "PO"):
        stats = layer_stats.get(layer, {})
        node_count = int(stats.get("node_count", 0))
        image_count = int(stats.get("image_count", 0))
        missing_paths = int(stats.get("missing_path_count", 0))
        fallback_count = int(stats.get("fallback_count", 0))
        non_fallback_count = int(stats.get("non_fallback_count", 0))

        _append_scene_health_check(
            payload,
            "Tile Loading",
            layer,
            f"{layer}_IMAGE_NODES",
            "WARNING",
            node_count > 0,
            (
                f"{layer} image nodes detected: {node_count}."
                if node_count > 0
                else f"No {layer} image nodes detected in Tile Loading group."
            ),
        )
        _append_scene_health_check(
            payload,
            "Tile Loading",
            layer,
            f"{layer}_MISSING_PATHS",
            "WARNING",
            missing_paths == 0,
            (
                f"{layer} assigned image paths are present."
                if missing_paths == 0
                else f"{layer} has {missing_paths} assigned image path(s) missing on disk."
            ),
        )
        fallback_only = image_count > 0 and non_fallback_count == 0 and fallback_count > 0
        _append_scene_health_check(
            payload,
            layer,
            layer,
            f"{layer}_FALLBACK_ONLY",
            "WARNING",
            not fallback_only,
            (
                f"{layer} has non-fallback texture assignments."
                if not fallback_only
                else f"{layer} is currently using fallback-only textures."
            ),
            detail=(
                f"images={image_count}, fallback={fallback_count}, non_fallback={non_fallback_count}"
            ),
        )

    # S2 visibility checks.
    s2_linked = loading_node is not None and _socket_is_linked(loading_node, "S2", is_output=True)
    _append_scene_health_check(
        payload,
        "S2",
        "Shader",
        "S2_OUTPUT_LINKED",
        "ERROR",
        s2_linked,
        "S2 output from Tile Loading is linked." if s2_linked else "S2 output from Tile Loading is not linked.",
    )
    surface_brightness = _socket_float_value(surface_grading_node, "Surface Brightness")
    _append_scene_health_check(
        payload,
        "S2",
        "Shader",
        "SURFACE_BRIGHTNESS",
        "WARNING",
        surface_brightness is None or surface_brightness > 0.0,
        (
            "Surface Brightness is above zero."
            if surface_brightness is None or surface_brightness > 0.0
            else "Surface Brightness is zero; S2 layer can appear black."
        ),
        detail=(f"value={surface_brightness:.4f}" if isinstance(surface_brightness, float) else ""),
    )

    # EL / displacement checks.
    el_linked = loading_node is not None and _socket_is_linked(loading_node, "EL", is_output=True)
    _append_scene_health_check(
        payload,
        "EL",
        "Shader",
        "EL_OUTPUT_LINKED",
        "ERROR",
        el_linked,
        "EL output from Tile Loading is linked." if el_linked else "EL output from Tile Loading is not linked.",
    )
    displacement_linked = bool(output_node is not None and _socket_is_linked(output_node, "Displacement", is_output=False))
    _append_scene_health_check(
        payload,
        "EL",
        "Material",
        "DISPLACEMENT_OUTPUT_LINKED",
        "WARNING",
        displacement_linked,
        (
            "Material Output Displacement is connected."
            if displacement_linked
            else "Material Output Displacement is not connected."
        ),
    )

    displacement_mode = ""
    if material is not None:
        cycles_settings = getattr(material, "cycles", None)
        try:
            displacement_mode = str(getattr(cycles_settings, "displacement_method", "") or "").upper().strip()
        except (TypeError, ValueError, AttributeError, RuntimeError):
            displacement_mode = ""
        if not displacement_mode:
            try:
                displacement_mode = str(getattr(material, "displacement_method", "") or "").upper().strip()
            except (TypeError, ValueError, AttributeError, RuntimeError):
                displacement_mode = ""
    _append_scene_health_check(
        payload,
        "EL",
        "Material",
        "DISPLACEMENT_MODE",
        "WARNING",
        displacement_mode in {"BOTH", "DISPLACEMENT", "DISPLACEMENT_ONLY", "DISPLACEMENT_AND_BUMP"},
        (
            "Material displacement mode supports displacement."
            if displacement_mode in {"BOTH", "DISPLACEMENT", "DISPLACEMENT_ONLY", "DISPLACEMENT_AND_BUMP"}
            else "Material displacement mode is not set to Displacement or Bump+Displacement."
        ),
        detail=(f"mode={displacement_mode or 'UNKNOWN'}"),
    )

    adaptive_modifier = None
    if earth is not None:
        modifiers = getattr(earth, "modifiers", None)
        if modifiers is not None:
            for modifier in modifiers:
                if str(getattr(modifier, "type", "")) != "SUBSURF":
                    continue
                if bool(getattr(modifier, "use_adaptive_subdivision", False)) or (
                    "Adaptive" in str(getattr(modifier, "name", ""))
                ):
                    adaptive_modifier = modifier
                    break
    adaptive_enabled = bool(adaptive_modifier is not None and bool(getattr(adaptive_modifier, "use_adaptive_subdivision", False)))
    _append_scene_health_check(
        payload,
        "EL",
        "Geometry",
        "ADAPTIVE_SUBDIVISION",
        "WARNING",
        adaptive_enabled,
        (
            "Adaptive Subdivision is enabled."
            if adaptive_enabled
            else "Adaptive Subdivision is not enabled on Earth mesh."
        ),
    )

    cycles_settings = getattr(scene, "cycles", None) if scene is not None else None
    render_engine = str(getattr(getattr(scene, "render", None), "engine", "") or "").upper()
    feature_set = str(getattr(cycles_settings, "feature_set", "") or "").upper() if cycles_settings is not None else ""
    if render_engine == "CYCLES":
        _append_scene_health_check(
            payload,
            "EL",
            "Render Settings",
            "CYCLES_FEATURE_SET",
            "WARNING",
            feature_set in {"EXPERIMENTAL", ""},
            (
                "Cycles feature set allows adaptive subdivision."
                if feature_set in {"EXPERIMENTAL", ""}
                else "Cycles feature set is not Experimental; adaptive subdivision may be disabled."
            ),
            detail=(f"feature_set={feature_set or 'UNKNOWN'}"),
        )

    dicing_rate = None
    preview_dicing_rate = None
    offscreen_dicing_scale = None
    if cycles_settings is not None:
        try:
            dicing_rate = float(getattr(cycles_settings, "dicing_rate", 0.0))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            dicing_rate = None
        try:
            preview_dicing_rate = float(getattr(cycles_settings, "preview_dicing_rate", 0.0))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            preview_dicing_rate = None
        try:
            offscreen_dicing_scale = float(getattr(cycles_settings, "offscreen_dicing_scale", 0.0))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            offscreen_dicing_scale = None

    if dicing_rate is not None:
        _append_scene_health_check(
            payload,
            "EL",
            "Render Settings",
            "DICING_RATE_RENDER",
            "WARNING",
            float(dicing_rate) < float(_HEALTH_DICING_WARN_THRESHOLD),
            (
                "Render dicing rate is in recommended range."
                if float(dicing_rate) < float(_HEALTH_DICING_WARN_THRESHOLD)
                else (
                    f"Render dicing rate is {dicing_rate:.2f}; this can be too low detail. "
                    f"Recommended {float(_HEALTH_DICING_RECOMMENDED_MIN):.2f}-{float(_HEALTH_DICING_RECOMMENDED_MAX):.2f}."
                )
            ),
        )
    if preview_dicing_rate is not None:
        _append_scene_health_check(
            payload,
            "EL",
            "Render Settings",
            "DICING_RATE_VIEWPORT",
            "INFO",
            True,
            f"Viewport dicing rate: {preview_dicing_rate:.2f}.",
        )
    if offscreen_dicing_scale is not None:
        _append_scene_health_check(
            payload,
            "EL",
            "Render Settings",
            "DICING_OFFSCREEN_SCALE",
            "INFO",
            True,
            f"Offscreen dicing scale: {offscreen_dicing_scale:.2f}.",
        )

    # WT checks.
    wt_linked = loading_node is not None and _socket_is_linked(loading_node, "WT", is_output=True)
    _append_scene_health_check(
        payload,
        "WT",
        "Shader",
        "WT_OUTPUT_LINKED",
        "ERROR",
        wt_linked,
        "WT output from Tile Loading is linked." if wt_linked else "WT output from Tile Loading is not linked.",
    )
    roughness_value = _socket_float_value(surface_grading_node, "Roughness")
    _append_scene_health_check(
        payload,
        "WT",
        "Shader",
        "WATER_ROUGHNESS",
        "WARNING",
        roughness_value is None or roughness_value < 0.99,
        (
            "Roughness allows visible water specular response."
            if roughness_value is None or roughness_value < 0.99
            else "Roughness is near 1.0; water can look like land and appear invisible."
        ),
        detail=(f"value={roughness_value:.4f}" if isinstance(roughness_value, float) else ""),
    )

    # PO checks.
    po_linked = loading_node is not None and _socket_is_linked(loading_node, "SE", is_output=True)
    _append_scene_health_check(
        payload,
        "PO",
        "Shader",
        "PO_OUTPUT_LINKED",
        "ERROR",
        po_linked,
        "PO/SE output from Tile Loading is linked." if po_linked else "PO/SE output from Tile Loading is not linked.",
    )
    intensity_value = _socket_float_value(surface_grading_node, "Intensity")
    _append_scene_health_check(
        payload,
        "PO",
        "Shader",
        "NIGHT_INTENSITY",
        "WARNING",
        intensity_value is None or intensity_value > 0.0,
        (
            "Night lights intensity is above zero."
            if intensity_value is None or intensity_value > 0.0
            else "Night lights intensity is zero; PO layer can appear invisible."
        ),
        detail=(f"value={intensity_value:.4f}" if isinstance(intensity_value, float) else ""),
    )
    nightday_groups = []
    for group in getattr(bpy.data, "node_groups", ()):
        name = str(getattr(group, "name", "") or "")
        if name == str(NIGHTDAY_GROUP_NAME) or name.startswith(f"{str(NIGHTDAY_GROUP_NAME)}."):
            nightday_groups.append(group)
    _append_scene_health_check(
        payload,
        "PO",
        "Shader",
        "NIGHTDAY_GROUP_PRESENT",
        "WARNING",
        bool(nightday_groups),
        "NightDay group is present." if nightday_groups else "NightDay group is missing.",
    )
    sunlight_hook_ok = False
    if nightday_groups and sunlight is not None:
        for group in nightday_groups:
            nodes = getattr(group, "nodes", None)
            if nodes is None:
                continue
            texcoord_nodes = [
                node for node in nodes
                if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexCoord"
            ]
            if not texcoord_nodes:
                continue
            if any(getattr(node, "object", None) is sunlight for node in texcoord_nodes):
                sunlight_hook_ok = True
                break
    _append_scene_health_check(
        payload,
        "PO",
        "Shader",
        "SUNLIGHT_HOOK",
        "WARNING",
        sunlight_hook_ok,
        (
            "Sunlight object is hooked in NightDay group."
            if sunlight_hook_ok
            else "Sunlight object is not hooked in NightDay group."
        ),
    )

    # Camera orientation/distance checks against Earth.
    if camera is not None and earth is not None:
        cam_diag = _camera_earth_diagnostics(scene, earth, camera, props)
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
            (
                "Camera is outside Earth geometry."
                if not inside_earth
                else "Camera is inside Earth geometry."
            ),
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
                (
                    "Camera distance is within a typical visible range."
                    if ratio_ok
                    else "Camera is very far from Earth; Earth may be effectively invisible."
                ),
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
        cam_data = getattr(camera, "data", None)
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
                (
                    "Camera clip end can reach Earth."
                    if clip_end <= 0.0 or clip_end >= target_distance
                    else "Camera clip end may cut Earth from view."
                ),
                detail=f"clip_end={clip_end:.3f}, required>={target_distance:.3f}",
            )

    # Animation state checks kept from previous behavior.
    if props is not None:
        frame_start = int(getattr(props, "anim_frame_start", 1) or 1)
        frame_end = int(getattr(props, "anim_frame_end", 1) or 1)
        _append_scene_health_check(
            payload,
            "Animation",
            "Timeline",
            "ANIM_FRAME_RANGE",
            "WARNING",
            frame_end > frame_start,
            (
                "Animation frame range is valid."
                if frame_end > frame_start
                else "Animation frame range is invalid (End must be greater than Start)."
            ),
        )

        preset = str(getattr(props, "anim_camera_preset", "NONE") or "NONE").strip().upper()
        if preset == "A_TO_B":
            has_a = bool(getattr(props, "anim_ab_a_valid", False))
            has_b = bool(getattr(props, "anim_ab_b_valid", False))
            _append_scene_health_check(
                payload,
                "Animation",
                "Preset",
                "ANIM_A_TO_B_VIEWS",
                "WARNING",
                bool(has_a and has_b),
                (
                    "A-to-B preset has both View A and View B."
                    if has_a and has_b
                    else "A-to-B preset is selected but View A/B capture is incomplete."
                ),
            )

        if preset not in {"", "NONE"}:
            keyed = _camera_has_transform_keys(camera)
            _append_scene_health_check(
                payload,
                "Animation",
                "Preset",
                "ANIM_CAMERA_KEYS",
                "WARNING",
                keyed,
                (
                    "Camera keyframes are present for selected animation preset."
                    if keyed
                    else "Animation preset is selected but camera keyframes are not present."
                ),
            )

    prepared_segments = 0
    if scene is not None:
        try:
            prepared_segments = int(scene.get(_ANIMATION_PREPARED_SEGMENTS_KEY, 0) or 0)
        except (TypeError, ValueError, AttributeError):
            prepared_segments = 0
    prepared_collection = bpy.data.collections.get(_ANIMATION_PREPARED_COLLECTION_NAME)
    if prepared_collection is None:
        for legacy_name in _ANIMATION_PREPARED_COLLECTION_NAMES_LEGACY:
            prepared_collection = bpy.data.collections.get(str(legacy_name or "").strip())
            if prepared_collection is not None:
                break
    prepared_object_count = len(getattr(prepared_collection, "objects", ())) if prepared_collection is not None else 0
    if prepared_segments > 0 and prepared_collection is None:
        _append_scene_health_check(
            payload,
            "Animation",
            "Quick Preview",
            "PREPARED_COLLECTION_MISSING",
            "WARNING",
            False,
            "Prepared animation segment state exists, but prepared collection is missing.",
        )
    elif prepared_segments <= 0 and prepared_collection is not None and prepared_object_count > 0:
        _append_scene_health_check(
            payload,
            "Animation",
            "Quick Preview",
            "PREPARED_STATE_STALE",
            "WARNING",
            False,
            "Prepared animation collection has stale objects, but prepared state is not active.",
        )
    else:
        _append_scene_health_check(
            payload,
            "Animation",
            "Quick Preview",
            "PREPARED_STATE_CONSISTENT",
            "INFO",
            True,
            "Prepared animation state is internally consistent.",
        )

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
    summary_row.label(text=f"Errors: {len(errors)} | Warnings: {len(warnings)} | Info: {len(info)}")

    grouped = {}
    for check in checks:
        section = str(check.get("section", "General") or "General")
        grouped.setdefault(section, []).append(check)

    section_order = (
        "General",
        "Viewport",
        "Camera",
        "Material",
        "Tile Loading",
        "S2",
        "EL",
        "WT",
        "PO",
        "Animation",
    )
    rendered_sections = set()
    for section_name in section_order:
        entries = grouped.get(section_name, [])
        if not entries:
            continue
        rendered_sections.add(section_name)
        box = layout.box()
        box.label(text=section_name)
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
    bl_description = "Check for missing Planetka assets, invalid paths, and stale animation state"

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
