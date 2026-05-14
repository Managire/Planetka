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
import re
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


def _test_price_pending_does_not_disable_full_quality() -> dict:
    """Static guard until sidebar state is refactored into a view model."""

    text = _source_text("ui.py")
    _assert(
        "if not full_size_known or not full_price_known:" not in text,
        "Full Quality must not be disabled solely because async price is pending.",
    )
    _assert(
        re.search(r"if\s+not\s+full_size_known:\s*\n\s+full_allowed\s*=\s*False", text) is not None,
        "Full Quality should only be disabled for missing size, not pending price.",
    )
    _assert(
        "Full Quality price is being calculated." not in text,
        "Sidebar must not expose the old stuck price-calculation message.",
    )
    return {"checked": True}


def _test_full_quality_pricing_fails_closed() -> dict:
    text = _source_text("operators.py")
    pattern = re.compile(
        r"failed checking direct payment before Full Quality resolve.*?"
        r"return fail\(\s*self,\s*\"Full Quality pricing is not available",
        re.S,
    )
    _assert(pattern.search(text) is not None, "Full Quality pricing exceptions must fail closed.")
    _assert(
        "scene_price = 0.0\n            if scene_price > 0.000001" not in text,
        "Full Quality pricing exceptions must not fall through as a free resolve.",
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
            ("price_pending_does_not_disable_full_quality", _test_price_pending_does_not_disable_full_quality),
            ("full_quality_pricing_fails_closed", _test_full_quality_pricing_fails_closed),
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
