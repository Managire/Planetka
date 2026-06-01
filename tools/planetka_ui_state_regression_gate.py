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
    """Texture quality buttons must stay static; progress belongs in the status row."""

    text = _source_text("ui.py")
    live_text = text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")]
    _assert(
        "_draw_resolve_status_line(layout, scene, runtime, runtime_code, runtime_text)" in live_text,
        "Data Control must draw the shared resolve status line above Quality Level.",
    )
    _assert(
        ".progress(" not in live_text,
        "Quality Level must not draw per-button download progress bars.",
    )
    _assert(
        "_quality_progress_factor" not in text,
        "Removed button-level download indicator helper must not return.",
    )
    return {"checked": True}


def _test_streaming_quality_ui_has_no_pricing_gate() -> dict:
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
        "planetka.open_credit_checkout" not in text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")],
        "Quality Level must not route Full Quality through checkout.",
    )
    return {"checked": True}


def _test_quality_operator_is_streaming_only() -> dict:
    text = _source_text("operators.py")
    start = text.find("class PLANETKA_OT_SetTextureQualityAndResolve")
    end = text.find("class PLANETKA_OT_OpenCreditCheckout", start)
    if end < 0:
        end = len(text)
    operator_text = text[start:end]
    _assert(
        '"BALANCED",' in operator_text,
        "Texture quality operator must accept Balanced mode.",
    )
    _assert(
        "open_credit_checkout" not in operator_text,
        "Texture quality operator must not open checkout.",
    )
    _assert(
        "bpy.ops.planetka.load_textures" in operator_text and "defer_download=True" in operator_text,
        "Texture quality operator must explicitly queue the shared async resolve path.",
    )
    _assert(
        "planetka_last_full_source_tiles" not in operator_text
        and "apply_texture_quality_to_full_tiles" not in operator_text
        and 'tiles_override_json=""' in operator_text,
        "Texture quality operator must not reuse cached source tiles; it must run the shared resolve path.",
    )
    _assert(
        "_SUPPRESS_TEXTURE_QUALITY_UPDATE_AUTO_RESOLVE_KEY" in operator_text
        and "planetka_suppress_texture_quality_update_auto_resolve" in text,
        "Texture quality operator must suppress the EnumProperty update auto-resolve and queue exactly one explicit resolve.",
    )
    properties_text = _source_text("properties.py")
    _assert(
        "planetka_suppress_texture_quality_update_auto_resolve" in properties_text
        and "return" in properties_text[properties_text.find("def update_texture_quality_mode"):properties_text.find("def _request_resolve_kill_switch")],
        "Texture quality property update must honor the operator suppression flag.",
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
    text = _source_text("planetka_runtime/auto_resolve_pipeline.py")
    _assert(
        "quality_switch_fast_path" not in text
        and "_scene_last_full_source_tiles" not in text
        and "planetka_last_full_source_tiles" not in text,
        "Texture quality changes must not use the obsolete shortcut source-tile cache.",
    )
    _assert(
        "full_source_tiles = tile_utils.main(" in text
        and "apply_texture_quality_to_full_tiles(full_source_tiles, current_quality_mode)" in text,
        "Auto-resolve must recompute full source tiles and apply quality through the normal path.",
    )
    _assert(
        "not quality_mode_changed and now - last_resolve < min_interval_sec" in text,
        "Quality changes must not be delayed by the normal auto-resolve interval.",
    )
    _assert(
        "and not quality_mode_changed" in text,
        "Same camera signature must still plan when only the texture quality changed.",
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
        "planetka_runtime/auto_resolve_pipeline.py",
    ):
        text = _source_text(name)
        _assert(
            "viewport_opt_active_view_coarse_textures" not in text
            and "Use Lower Texture Quality in Active View" not in text,
            f"Obsolete Active View lower-quality override must not exist in {name}.",
        )
    return {"checked": True}


def _test_auto_resolve_has_no_forced_preview_jobs() -> dict:
    text = _source_text("planetka_runtime/auto_resolve_pipeline.py")
    context_text = _source_text("planetka_runtime/auto_resolve_context.py")
    state_text = _source_text("state.py")
    _assert(
        "automatic Preview" not in text and "suppress_auto_preview" not in text,
        "Normal auto-resolve must not contain a special automatic Preview job path.",
    )
    _assert(
        "texture_quality_mode = _ctx_auto_resolve_texture_quality_mode(" in text
        and "getattr(props, \"texture_quality_mode\", \"PREVIEW\")" in text,
        "Normal auto-resolve must read the currently selected Quality Level from scene properties.",
    )
    _assert(
        "class AutoResolveDecisionDeps" in context_text
        and "normalize_texture_quality_mode: Any" in context_text,
        "Auto-resolve decision context must have the quality normalizer; otherwise it silently falls back to Preview.",
    )
    _assert(
        "normalize_texture_quality_mode=_normalize_texture_quality_mode" in state_text[
            state_text.find("decision_deps = AutoResolveDecisionDeps("):state_text.find("noncritical_deps = AutoResolveNonCriticalDeps(")
        ],
        "Auto-resolve decision deps must receive the quality normalizer from state.py.",
    )
    return {"checked": True}


def _test_stale_completed_resolve_cannot_override_newer_request() -> dict:
    text = _source_text("planetka_runtime/auto_resolve_pipeline.py")
    _assert(
        "_ctx_job_supersedes_completed_payload" in text,
        "Download pump must be able to identify stale completed resolves superseded by newer requests.",
    )
    _assert(
        "queue dropped stale completed resolve" in text,
        "Queueing a newer request must clear an older completed payload before it can apply.",
    )
    _assert(
        "Worker dropped completed resolve because a newer request is pending" in text,
        "Download worker must not store an old completed payload when a newer different request is already pending.",
    )
    _assert(
        "Pump dropped stale completed resolve before apply" in text,
        "Pump must drop stale completed payloads before shader apply.",
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
        "Quality Level should not expose the old Full Quality Details pricing popup.",
    )
    _assert(
        "Relevant Data Packs" not in data_control_text,
        "Quality Level should not expose data-pack upsells.",
    )
    return {"checked": True}


def _test_region_pack_offer_context_is_not_download_context() -> dict:
    text = _source_text("planetka_runtime/auto_resolve_pipeline.py")
    _assert(
        "schedule_region_pack_offer_refresh(\n            scene,\n            ctx," not in text,
        "Relevant Data Packs refresh must not pass the auto-resolve download context as view telemetry runtime.",
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
            ("streaming_quality_ui_has_no_pricing_gate", _test_streaming_quality_ui_has_no_pricing_gate),
            ("quality_operator_is_streaming_only", _test_quality_operator_is_streaming_only),
            ("texture_quality_tile_levels", lambda: _test_texture_quality_tile_levels(base_module)),
            ("quality_switch_fast_path", _test_quality_switch_fast_path),
            ("obsolete_active_view_quality_override_removed", _test_obsolete_active_view_quality_override_removed),
            ("auto_resolve_has_no_forced_preview_jobs", _test_auto_resolve_has_no_forced_preview_jobs),
            ("stale_completed_resolve_cannot_override_newer_request", _test_stale_completed_resolve_cannot_override_newer_request),
            ("animation_stop_is_cooperative", _test_animation_stop_is_cooperative),
            ("animation_restart_ignores_old_cancel_epoch", _test_animation_restart_ignores_old_cancel_epoch),
            ("full_quality_details_removed_from_data_control", _test_full_quality_details_removed_from_data_control),
            ("region_pack_offer_context_is_correct", _test_region_pack_offer_context_is_not_download_context),
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
