import json
import os
import platform
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import bpy

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


def _open_bug_mail_draft(report_path):
    subject = "Planetka Blender Bug Report"
    body = (
        "Hi Planetka team,\n\n"
        "Please find attached the Planetka debug report.\n\n"
        "Debug report path:\n"
        f"{report_path}\n\n"
        "Issue description:\n"
        "- What happened:\n"
        "- Steps to reproduce:\n"
        "- Expected behavior:\n"
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
    bl_description = "Export a compact debug report JSON and open an email draft to info@planetka.io"

    def execute(self, context):
        target_path = _default_bug_report_path()
        try:
            report = _build_minimal_report(context)
            with open(target_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, sort_keys=False)
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

        _open_bug_mail_draft(os.path.abspath(target_path))
        self.report({'INFO'}, "Bug report draft opened. Attach the exported JSON if needed.")
        return {'FINISHED'}


class PLANETKA_OT_ValidateTextureSource(bpy.types.Operator):
    bl_idname = "planetka.validate_texture_source"
    bl_label = "Validate Texture Source"
    bl_description = "Validate the configured texture source directory against Planetka dataset requirements"

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
            lines.append("No path-structure issues detected.")

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
