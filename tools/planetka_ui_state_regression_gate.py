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
        "Data Streaming must draw the shared resolve status line above Texture Quality.",
    )
    _assert(
        ".progress(" not in live_text,
        "Texture Quality must not draw per-button download progress bars.",
    )
    _assert(
        "_quality_progress_factor" not in text,
        "Removed button-level download indicator helper must not return.",
    )
    return {"checked": True}


def _test_streaming_quality_ui_has_no_pricing_gate() -> dict:
    """Static guard for the simplified streaming-only texture-quality UI."""

    text = _source_text("ui.py")
    _assert(
        'header_row.label(text="Texture Quality", icon="TEXTURE")' in text,
        "Sidebar should expose the simplified Texture Quality section.",
    )
    _assert(
        'bl_label = "Data Streaming"' in text,
        "Sidebar panel should be named Data Streaming.",
    )
    _assert(
        '"BALANCED", "Balanced"' in text,
        "Texture Quality must expose the Balanced streaming quality button.",
    )
    _assert(
        "planetka.open_credit_checkout" not in text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")],
        "Texture Quality must not route Full Quality through checkout.",
    )
    return {"checked": True}


def _test_quality_operator_is_streaming_only() -> dict:
    text = _source_text("operators.py")
    start = text.find("class PLANETKA_OT_SetTextureQualityAndResolve")
    end = text.find("class PLANETKA_OT_OpenCreditCheckout", start)
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
        "planetka_last_full_source_tiles" in operator_text
        and "apply_texture_quality_to_full_tiles" in operator_text
        and "tiles_override_json=tiles_override_json" in operator_text,
        "Texture quality operator must reuse the last full-source tile list for fast quality switching.",
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
    return {"full": full, "balanced": balanced, "preview": preview}


def _test_quality_switch_fast_path() -> dict:
    text = _source_text("planetka_runtime/auto_resolve_pipeline.py")
    _assert(
        "quality_switch_fast_path" in text,
        "Auto-resolve planner must expose the quality-switch fast path.",
    )
    _assert(
        "apply_texture_quality_to_full_tiles" in text,
        "Quality changes must transform the last optimal source tile list instead of recomputing visibility.",
    )
    _assert(
        "not quality_mode_changed and now - last_resolve < min_interval_sec" in text,
        "Quality changes must not be delayed by the normal auto-resolve interval.",
    )
    _assert(
        "and not quality_mode_changed" in text,
        "Same camera signature must still plan when only the texture quality changed.",
    )
    return {"checked": True}


def _test_full_quality_details_removed_from_data_control() -> dict:
    text = _source_text("ui.py")
    data_control_text = text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")]
    _assert(
        "planetka.data_cost_breakdown" not in data_control_text,
        "Texture Quality should not expose the old Full Quality Details pricing popup.",
    )
    _assert(
        "Relevant Data Packs" not in data_control_text,
        "Texture Quality should not expose data-pack upsells.",
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
