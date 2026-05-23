"""Live gate for Planetka Free/Pro streaming access.

Run from Blender after setting the target account plan in D1:
  PLANETKA_EXPECTED_PLAN=free /Applications/Blender5.0.app/Contents/MacOS/Blender --background \
    --python tools/planetka_account_tier_gate.py

The gate verifies tile-session creation for several global locations across
Preview, Balanced, and Full texture quality.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import bpy

from planetka_e2e_common import (
    E2EError,
    enable_module,
    ensure_authenticated,
    import_submodule,
    log,
    write_json,
)

TAG = "[Planetka Account Tier Gate]"
EXPECTED_PLAN = str(os.environ.get("PLANETKA_EXPECTED_PLAN") or "free").strip().lower()
if EXPECTED_PLAN == "personal":
    EXPECTED_PLAN = "free"
elif EXPECTED_PLAN == "professional":
    EXPECTED_PLAN = "pro"
QUALITY_MODES = ("preview", "balanced", "full")
LOCATIONS = (
    {"name": "New Zealand", "lat": -41.2865, "lon": 174.7762},
    {"name": "Iceland", "lat": 64.1466, "lon": -21.9426},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198},
)


def _assert(condition, message):
    if not condition:
        raise E2EError(str(message))


def _try_session(r2_source, location, quality_mode):
    resolve_id = f"account-tier-{EXPECTED_PLAN}-{location['name'].lower().replace(' ', '-')}-{quality_mode}-{int(time.time() * 1000)}"
    r2_source.set_resolve_request_context(
        resolve_id=resolve_id,
        texture_quality_mode=quality_mode,
        nav_latitude_deg=location["lat"],
        nav_longitude_deg=location["lon"],
        nav_altitude_km=100.0,
    )
    try:
        token, expires_at = r2_source._request_tile_session_token(resolve_id, quality_mode)  # noqa: SLF001
        return {
            "ok": bool(str(token or "").strip()),
            "expires_at": float(expires_at or 0.0),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - gate must capture backend error text
        return {
            "ok": False,
            "expires_at": 0.0,
            "error": str(exc),
        }
    finally:
        r2_source.clear_resolve_request_context()


def main():
    report_path = Path(tempfile.gettempdir()) / f"planetka_account_tier_gate_{EXPECTED_PLAN}.json"
    payload = {
        "status": "running",
        "expected_plan": EXPECTED_PLAN,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [],
    }
    try:
        _assert(EXPECTED_PLAN in {"free", "pro"}, "PLANETKA_EXPECTED_PLAN must be free or pro.")
        base_module = enable_module(required_planetka_attr="add_earth")
        auth = import_submodule(base_module, "auth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        r2_source = import_submodule(base_module, "r2_source")
        prefs = extension_prefs.get_prefs()
        account = ensure_authenticated(
            auth,
            prefs,
            payload_path=str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip(),
            api_key=str(os.environ.get("PLANETKA_API_KEY") or "").strip(),
            api_key_path=str(os.environ.get("PLANETKA_API_KEY_PATH") or "").strip(),
        )
        try:
            auth.refresh_auth_session(prefs)
        except Exception:
            log(TAG, "Auth refresh failed; continuing with current authenticated session.")
        account.update(
            {
                "email": str(auth.get_connected_email(prefs) or "").strip(),
                "upgrade_url": str(auth.get_upgrade_url(prefs) or "").strip(),
            }
        )
        actual_plan = str(auth.get_account_tier(prefs) or "").strip().lower()
        if actual_plan == "professional":
            actual_plan = "pro"
        elif actual_plan == "personal":
            actual_plan = "free"
        account["actual_plan"] = actual_plan
        payload["account"] = account
        _assert(account["email"].lower() == "tom.griger@gmail.com", f"Unexpected test account: {account['email']}")
        _assert(
            actual_plan == EXPECTED_PLAN,
            f"Test account tier is {actual_plan or 'unknown'}, but PLANETKA_EXPECTED_PLAN is {EXPECTED_PLAN}. "
            "Set the account tier in Analytics/D1 before running this gate.",
        )

        for location in LOCATIONS:
            for quality_mode in QUALITY_MODES:
                result = _try_session(r2_source, location, quality_mode)
                expected_ok = (
                    quality_mode in {"preview", "balanced"}
                    or EXPECTED_PLAN == "pro"
                )
                result.update(
                    {
                        "location": location["name"],
                        "quality_mode": quality_mode,
                        "expected_ok": expected_ok,
                    }
                )
                payload["results"].append(result)
                log(TAG, f"{location['name']} {quality_mode}: ok={result['ok']} expected={expected_ok}")
                if expected_ok:
                    _assert(result["ok"], f"{EXPECTED_PLAN} account should access {location['name']} in {quality_mode}: {result['error']}")
                else:
                    _assert(not result["ok"], f"{EXPECTED_PLAN} account incorrectly accessed {location['name']} in {quality_mode}.")
                    _assert(
                        "quality" in result["error"].lower() or "tier" in result["error"].lower() or "account" in result["error"].lower(),
                        f"Blocked error should explain the quality-tier restriction: {result['error']}",
                    )

        payload["status"] = "passed"
        write_json(report_path, payload)
        log(TAG, f"PASSED: {report_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        payload["status"] = "failed"
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
        write_json(report_path, payload)
        log(TAG, f"FAILED: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
