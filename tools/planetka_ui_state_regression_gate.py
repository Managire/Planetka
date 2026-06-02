#!/usr/bin/env python3
"""Focused Blender UI-state regressions for Planetka release gates.

This catches customer-visible sidebar state bugs that backend/operator tests do
not see. It is intentionally small and deterministic so it can run before every
release.

Run:
  /Applications/Blender5.0.app/Contents/MacOS/Blender --background \
    --factory-startup --python tools/planetka_ui_state_regression_gate.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import addon_utils

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)


REPORT_PATH = Path(tempfile.gettempdir()) / "planetka_ui_state_regression_gate_report.json"


def _write_report(payload: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _source_text(name: str) -> str:
    return (Path(_REPO_ROOT) / name).read_text(encoding="utf-8")


def _enable_addon() -> str:
    candidates = (
        "bl_ext.user_default.Planetka",
        "Planetka",
        "planetka",
    )
    for module_name in candidates:
        try:
            addon_utils.enable(module_name, default_set=False, persistent=False)
            return module_name
        except Exception:
            continue
    raise RuntimeError("Could not enable Planetka for UI-state regression gate.")


def _test_texture_quality_uses_single_status_line() -> dict:
    """Texture quality buttons stay static; status/progress belongs under Resolve."""

    text = _source_text("ui.py")
    live_text = text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")]
    _assert(
        "_draw_data_control_progress_section(quality_box, scene, runtime, runtime_code, runtime_text)" in live_text,
        "Data Control must draw the fixed status/progress section below Resolve Planetka.",
    )
    _assert(
        'resolve_row.operator("planetka.resolve_planetka", text="Resolve Planetka", icon="FILE_REFRESH")' in live_text,
        "Data Control must expose the Resolve Planetka button.",
    )
    _assert(
        live_text.find('resolve_row.operator("planetka.resolve_planetka", text="Resolve Planetka", icon="FILE_REFRESH")')
        < live_text.find("_draw_data_control_progress_section(quality_box, scene, runtime, runtime_code, runtime_text)"),
        "Status/progress section must be placed directly below Resolve Planetka.",
    )
    _assert(
        "_quality_progress_factor" not in text,
        "Removed button-level download indicator helper must not return.",
    )
    return {"checked": True}


def _test_streaming_quality_ui_has_no_licence_gate() -> dict:
    """Static guard for the simplified streaming-only quality-level UI."""

    text = _source_text("ui.py")
    _assert(
        'header_row.label(text="Quality Level", icon="TEXTURE")' in text,
        "Sidebar should expose the simplified Quality Level section.",
    )
    _assert(
        'bl_label = "Data Control"' in text,
        "Sidebar panel should be named Data Control.",
    )
    _assert(
        '"BALANCED", "Balanced"' in text,
        "Quality Level must expose the Balanced streaming quality button.",
    )
    _assert(
        "planetka.open_credit_package" not in text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")],
        "Quality Level must not route Full Quality through package.",
    )
    return {"checked": True}


def _test_quality_operator_is_streaming_only() -> dict:
    text = _source_text("operators.py")
    quality_start = text.find("class PLANETKA_OT_SetTextureQuality")
    resolve_start = text.find("class PLANETKA_OT_ResolvePlanetka", quality_start)
    next_class = text.find("class ", resolve_start + 1)
    if next_class < 0:
        next_class = len(text)
    quality_text = text[quality_start:resolve_start]
    resolve_text = text[resolve_start:next_class]
    _assert(
        '"BALANCED",' in quality_text,
        "Texture quality operator must accept Balanced mode.",
    )
    _assert(
        "bpy.ops.planetka.load_textures" not in quality_text
        and "defer_download" not in quality_text,
        "Texture quality buttons must only set Quality Level; they must not resolve or download.",
    )
    _assert(
        "bpy.ops.planetka.load_textures" in resolve_text
        and 'scope_mode="CAMERA"' in resolve_text
        and "defer_download=True" in resolve_text,
        "Resolve Planetka must start the shared manual camera resolve path.",
    )
    properties_text = _source_text("properties.py")
    update_text = properties_text[properties_text.find("def update_texture_quality_mode"):properties_text.find("def _show_earth_preview_description")]
    _assert(
        "Changing it must not start any resolve or download" in update_text
        and "return None" in update_text,
        "Texture quality property update must be a pure switch with no resolve side effects.",
    )
    return {"checked": True}

def _test_texture_quality_tile_levels(base_module: str) -> dict:
    """Guard the core texture quality contract.

    Full keeps the tile list generated for the view. Balanced requests the same
    tiles at doubled d-levels. Preview requests the same tiles at four-times
    d-levels, clamped to the nearest available dataset level.
    """

    render_prep = __import__(f"{base_module}.render_prep", fromlist=["dummy"])
    full_tiles = [
        "x000_y000_z001_d002",
        "x010_y010_z001_d008",
        "x020_y020_z180_d180",
        "x000_y000_z360_d360",
    ]
    full = render_prep.apply_texture_quality_to_full_tiles(full_tiles, "FULL")
    balanced = render_prep.apply_texture_quality_to_full_tiles(full_tiles, "BALANCED")
    preview = render_prep.apply_texture_quality_to_full_tiles(full_tiles, "PREVIEW")
    _assert("x000_y000_z001_d002" in full, f"Full must keep optimal d-levels: {full}")
    _assert("x000_y000_z001_d004" in balanced, f"Balanced must double d-levels: {balanced}")
    _assert("x000_y000_z001_d008" in preview, f"Preview must quadruple d-levels: {preview}")
    _assert("x010_y010_z001_d030" in balanced, f"Balanced must clamp to next available doubled d-level: {balanced}")
    _assert("x010_y010_z001_d060" in preview, f"Preview must clamp to next available quadrupled d-level: {preview}")
    _assert("x020_y020_z180_d180" in full, f"Full z180 must stay d180: {full}")
    _assert("x020_y020_z180_d360" in balanced, f"Balanced z180 must be d360: {balanced}")
    _assert("x020_y020_z180_d720" in preview, f"Preview z180 must be d720: {preview}")
    _assert("x000_y000_z360_d360" in full, f"Full z360 must stay d360: {full}")
    _assert("x000_y000_z360_d720" in balanced, f"Balanced z360 must be d720: {balanced}")
    _assert("x000_y000_z360_d000" in preview, f"Preview z360 must be d000, the filename form of d1440: {preview}")
    return {"full": full, "balanced": balanced, "preview": preview}


def _test_quality_switch_fast_path() -> dict:
    text = _source_text("render_prep.py")
    pipeline_text = _source_text("planetka_runtime/resolve.py")
    _assert(
        "quality_switch_fast_path" not in text and "quality_switch_fast_path" not in pipeline_text
        and "_scene_last_full_source_tiles" not in text
        and "planetka_last_full_source_tiles" not in text,
        "Texture quality changes must not use the obsolete shortcut source-tile cache.",
    )
    _assert(
        "full_source_tiles" in text
        and "tile_utils.main(" in text
        and "apply_texture_quality_to_full_tiles(" in text
        and "quality_mode" in text,
        "Manual resolve must recompute full source tiles and apply quality through the normal path.",
    )
    _assert(
        "min_interval_sec" not in text
        and "quality_mode_changed" not in text,
        "Manual resolve must not contain obsolete resolve interval or quality-change planning logic.",
    )
    operators_text = _source_text("operators.py")
    _assert(
        "planetka_last_full_source_tiles" not in operators_text
        and "texture quality fast-path" not in operators_text,
        "Quality Level buttons must not bypass the normal resolve path.",
    )
    return {"checked": True}

def _test_obsolete_active_view_quality_override_removed() -> dict:
    for name in (
        "properties.py",
        "state.py",
        "render_prep.py",
        "planetka_runtime/resolve.py",
    ):
        text = _source_text(name)
        _assert(
            "viewport_opt_active_view_coarse_textures" not in text
            and "Use Lower Texture Quality in Active View" not in text,
            f"Obsolete Active View lower-quality override must not exist in {name}.",
        )
    return {"checked": True}


def _test_resolve_has_no_forced_preview_jobs() -> dict:
    pipeline_text = _source_text("planetka_runtime/resolve.py")
    context_text = _source_text("planetka_runtime/resolve_context.py")
    state_text = _source_text("state.py")
    _assert(
        "automatic Preview" not in pipeline_text and "suppress_auto_preview" not in pipeline_text,
        "Manual resolve must not contain special automatic Preview jobs.",
    )
    _assert(
        "DecisionDeps" not in context_text
        and "NonCriticalDeps" not in context_text
        and "SceneResolveState" not in state_text,
        "Deleted decision/noncritical internals must not reappear.",
    )
    _assert(
        "class PLANETKA_OT_ResolvePlanetka" in _source_text("operators.py")
        and "bpy.ops.planetka.load_textures" in _source_text("operators.py"),
        "Manual Resolve Planetka operator must remain the sole user-facing resolve trigger.",
    )
    return {"checked": True}

def _test_manual_resolve_replaces_active_job() -> dict:
    text = _source_text("planetka_runtime/resolve.py")
    context_text = _source_text("planetka_runtime/resolve_context.py")
    state_text = _source_text("planetka_runtime/resolve_state.py")
    _assert(
        "second job slot" not in text + context_text + state_text,
        "Manual resolve must not maintain a second job slot.",
    )
    _assert(
        "state.download_epoch = int(state.download_epoch) + 1" in text
        and "state.download_completed = None" in text
        and "state.download_active_job = new_job" in text,
        "Starting Resolve Planetka must cancel/replace the active job and clear any ready-to-apply payload.",
    )
    _assert(
        "_ctx_job_supersedes" + "_completed_payload" not in text
        and "state.download_" + "pending" + "_job" not in text,
        "Stale-completed queue logic must not reappear in the simplified manual resolve pipeline.",
    )
    return {"checked": True}


def _test_animation_stop_is_cooperative() -> dict:
    text = _source_text("animation_tools.py")
    external_start = text.find("def _request_external_stop(self):")
    external_end = text.find("def _read_render_heartbeat", external_start)
    external_stop = text[external_start:external_end]
    _assert(
        "_request_render_stop()" not in external_stop,
        "Animation Stop button must not call Blender render cancel directly from the UI operator.",
    )
    render_operator_start = text.find("class PLANETKA_OT_AnimationRender")
    modal_start = text.find("def modal(self, context, event):", render_operator_start)
    modal_render_start = text.find('if self._state == "RENDER":', modal_start)
    modal_pre_render = text[modal_start:modal_render_start]
    _assert(
        "_request_render_stop()" not in modal_pre_render,
        "Modal stop handling must be cooperative before entering the render-state branch.",
    )
    stop_operator_start = text.find("class PLANETKA_OT_AnimationStop")
    stop_operator_end = text.find("class PLANETKA_OT_AnimationMakeReady", stop_operator_start)
    stop_operator = text[stop_operator_start:stop_operator_end]
    _assert(
        "render.cancel" not in stop_operator and "view_cancel" not in stop_operator,
        "Animation Stop fallback must not call Blender render.cancel/view_cancel directly.",
    )
    return {"checked": True}


def _test_animation_restart_ignores_old_cancel_epoch() -> dict:
    text = _source_text("animation_tools.py")
    render_operator_start = text.find("class PLANETKA_OT_AnimationRender")
    execute_start = text.find("def execute(self, context):", render_operator_start)
    modal_start = text.find("def modal(self, context, event):", execute_start)
    execute_text = text[execute_start:modal_start]
    _assert(
        "def _reset_segment_cancel_epoch_baseline(self):" in text,
        "Final Animation Render must have an explicit helper to baseline the render-cancel epoch.",
    )
    _assert(
        "self._reset_segment_cancel_epoch_baseline()" in execute_text,
        "New Final Animation Render runs must baseline old render cancellations before the first segment launch.",
    )
    _assert(
        "self._segment_cancel_epoch_before_launch = -1" not in execute_text,
        "New Final Animation Render runs must not start from -1 because an old cancelled render would kill them immediately.",
    )
    return {"checked": True}


def _test_full_quality_details_removed_from_data_control() -> dict:
    text = _source_text("ui.py")
    data_control_text = text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")]
    _assert(
        "planetka.data_cost_breakdown" not in data_control_text,
        "Quality Level should not expose the old Full Quality Details licence popup.",
    )
    _assert(
        "Relevant Data Packs" not in data_control_text,
        "Quality Level should not expose data-pack upsells.",
    )
    return {"checked": True}


def _test_animation_preview_has_no_modal_timer() -> dict:
    text = _source_text("animation_tools.py")
    preview_start = text.find("class PLANETKA_OT_AnimationPreviewShot")
    preview_end = text.find("class PLANETKA_OT_AnimationClearPrepared", preview_start)
    _assert(preview_start >= 0 and preview_end > preview_start, "Animation preview operator block not found.")
    preview_text = text[preview_start:preview_end]
    forbidden = (
        "def modal(",
        "event_timer_add",
        "event_timer_remove",
        "_timer",
        "_frame_change_handler",
        "RUNNING_MODAL",
        "bpy.ops.planetka.load_textures",
    )
    present = [token for token in forbidden if token in preview_text]
    _assert(
        not present,
        f"Animation preview must remain simple playback with no modal/timer/resolve remnants: {present}",
    )
    return {"checked": True}


def main() -> int:
    started = time.time()
    report = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "tests": [],
    }
    try:
        base_module = _enable_addon()
        ui_module = __import__(f"{base_module}.ui", fromlist=["dummy"])
        checks = (
            ("texture_quality_uses_single_status_line", _test_texture_quality_uses_single_status_line),
            ("streaming_quality_ui_has_no_licence_gate", _test_streaming_quality_ui_has_no_licence_gate),
            ("quality_operator_is_streaming_only", _test_quality_operator_is_streaming_only),
            ("texture_quality_tile_levels", lambda: _test_texture_quality_tile_levels(base_module)),
            ("quality_switch_fast_path", _test_quality_switch_fast_path),
            ("obsolete_active_view_quality_override_removed", _test_obsolete_active_view_quality_override_removed),
            ("resolve_has_no_forced_preview_jobs", _test_resolve_has_no_forced_preview_jobs),
            ("manual_resolve_replaces_active_job", _test_manual_resolve_replaces_active_job),
            ("animation_stop_is_cooperative", _test_animation_stop_is_cooperative),
            ("animation_restart_ignores_old_cancel_epoch", _test_animation_restart_ignores_old_cancel_epoch),
            ("full_quality_details_removed_from_data_control", _test_full_quality_details_removed_from_data_control),
            ("animation_preview_has_no_modal_timer", _test_animation_preview_has_no_modal_timer),
        )
        for name, fn in checks:
            result = fn()
            report["tests"].append({"name": name, "status": "ok", "result": result})
            print(f"[Planetka UI State Regression Gate] OK: {name}", flush=True)
        report["status"] = "ok"
        report["elapsed_sec"] = round(time.time() - started, 3)
        _write_report(report)
        print(f"[Planetka UI State Regression Gate] PASS: report={REPORT_PATH}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - release gate must catch all failures.
        report["status"] = "error"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        report["elapsed_sec"] = round(time.time() - started, 3)
        _write_report(report)
        print(f"[Planetka UI State Regression Gate] FAIL: {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
