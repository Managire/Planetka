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


def _test_full_quality_progress_not_shown_without_download(ui_module) -> dict:
    """Regression for completed Full Quality bar replacing the clickable button.

    Previously any active runtime state could return a Full Quality progress
    factor, even with no active download. That turned the button into a passive
    blue progress bar after purchases.
    """

    state = {
        "active": True,
        "download_active": False,
        "runtime_code": "IDLE",
        "quality_mode": "FULL",
    }
    factor = ui_module._quality_progress_factor(  # noqa: SLF001 - release gate targets internal UI logic.
        "FULL",
        state,
        "PREVIEW",
        estimate_bytes=143_280_000,
        estimate_available_bytes=143_280_000,
    )
    _assert(factor is None, "Full Quality progress factor must be None when no Full Quality download is active.")

    active_state = dict(state)
    active_state["download_active"] = True
    active_state["runtime_code"] = "DOWNLOADING"
    active_factor = ui_module._quality_progress_factor(  # noqa: SLF001
        "FULL",
        active_state,
        "PREVIEW",
        estimate_bytes=100,
        estimate_available_bytes=25,
    )
    _assert(active_factor is not None, "Full Quality progress factor should exist during an active Full Quality download.")
    _assert(0.0 <= float(active_factor) <= 1.0, f"Progress factor out of range: {active_factor}")
    return {
        "inactive_factor": factor,
        "active_factor": active_factor,
    }


def _test_streaming_quality_ui_has_no_pricing_gate() -> dict:
    """Static guard for the simplified streaming-only texture-quality UI."""

    text = _source_text("ui.py")
    _assert(
        'header_row.label(text="Textures Quality", icon="TEXTURE")' in text,
        "Sidebar should expose the simplified Textures Quality section.",
    )
    _assert(
        '"BALANCED", "Balanced"' in text,
        "Textures Quality must expose the Balanced streaming quality button.",
    )
    _assert(
        "planetka.open_credit_checkout" not in text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")],
        "Textures Quality must not route Full Quality through checkout.",
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
        "skip_pricing_session=True" in operator_text,
        "Texture quality operator must not require a commerce pricing session.",
    )
    return {"checked": True}


def _test_full_quality_details_removed_from_data_control() -> dict:
    text = _source_text("ui.py")
    data_control_text = text[text.find("def _draw_live_telemetry"):text.find("def _draw_advanced_telemetry")]
    _assert(
        "planetka.data_cost_breakdown" not in data_control_text,
        "Textures Quality should not expose the old Full Quality Details pricing popup.",
    )
    _assert(
        "Relevant Data Packs" not in data_control_text,
        "Textures Quality should not expose data-pack upsells.",
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
            ("full_quality_progress_not_shown_without_download", lambda: _test_full_quality_progress_not_shown_without_download(ui_module)),
            ("streaming_quality_ui_has_no_pricing_gate", _test_streaming_quality_ui_has_no_pricing_gate),
            ("quality_operator_is_streaming_only", _test_quality_operator_is_streaming_only),
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
