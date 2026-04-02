import json
import os
import platform
import sys
from datetime import datetime, timezone
import urllib.error
import urllib.request

import bpy

from .auth import (
    AuthApiError,
    get_api_base_url,
    get_authorized_headers,
    is_authenticated,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_prefs
from .operator_utils import ErrorCode, fail
from .sanity_utils import invalidate_texture_source_health_cache, validate_known_good_texture_source


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


def _build_minimal_report(context):
    scene = getattr(context, "scene", None)
    render = getattr(scene, "render", None) if scene else None
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "addon": __package__ or "Planetka",
        "blender_version": list(getattr(bpy.app, "version", ())),
        "blender_version_string": getattr(bpy.app, "version_string", ""),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "scene_name": getattr(scene, "name", ""),
        "render_engine": getattr(render, "engine", "") if render else "",
    }


def _open_bug_mail_draft(
    report_path,
    report_json_text,
    issue_what_happened="",
    issue_steps_to_reproduce="",
    issue_expected_behavior="",
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
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return

    safe_lines = [str(line) for line in lines if line]

    def _draw(self, _context):
        col = self.layout.column(align=True)
        for line in safe_lines:
            col.label(text=line)

    wm.popup_menu(_draw, title=title, icon=icon)


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
        sent, send_error = _send_bug_report_via_api(
            report_path_abs,
            report_json_text,
            issue_what_happened=issue_what,
            issue_steps_to_reproduce=issue_steps,
            issue_expected_behavior=issue_expected,
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
