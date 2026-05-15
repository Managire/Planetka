#!/usr/bin/env python3
"""Hermetic stale-auth recovery gate for Planetka.

This gate does not call the live API. It verifies that backend-confirmed
terminal auth failures clear the saved session and surface a plain reconnect
message instead of raw auth/backend errors.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import addon_utils


REPORT_PATH = Path("/tmp/planetka_stale_auth_recovery_gate_report.json")
AUTH_FIELDS = (
    "auth_email",
    "auth_api_key",
    "auth_api_key_input",
    "auth_api_key_mask",
    "auth_device_id",
    "auth_access_token",
    "auth_refresh_token",
    "auth_login_state",
    "auth_status_message",
)


class GateFailure(RuntimeError):
    pass


class FakeOperator:
    def __init__(self):
        self.messages = []

    def report(self, level, message):
        self.messages.append({"level": list(level or ()), "message": str(message or "")})


def _assert(condition, message):
    if not condition:
        raise GateFailure(str(message))


def _snapshot_prefs(prefs):
    return {field: str(getattr(prefs, field, "") or "") for field in AUTH_FIELDS}


def _restore_prefs(prefs, snapshot):
    for field, value in (snapshot or {}).items():
        try:
            setattr(prefs, field, value)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass


def _seed_stale_session(prefs):
    prefs.auth_email = "stale-session-test@planetka.local"
    prefs.auth_api_key = "pka_test_preserved_key"
    prefs.auth_api_key_input = "pka_test_preserved_key"
    prefs.auth_api_key_mask = "pka_test...key"
    prefs.auth_device_id = "stale-auth-test-device"
    prefs.auth_access_token = "stale.access.token"
    prefs.auth_refresh_token = "stale-refresh-token"
    prefs.auth_login_state = "authenticated"
    prefs.auth_status_message = ""


def _assert_recovered(auth, prefs, step_name):
    _assert(not auth.is_authenticated(prefs), f"{step_name}: stale session was not cleared")
    _assert(str(getattr(prefs, "auth_api_key", "") or "") == "pka_test_preserved_key", f"{step_name}: API key was not preserved")
    status = str(getattr(prefs, "auth_status_message", "") or "")
    _assert("session expired" in status.lower() or "connect your account again" in status.lower(), f"{step_name}: unclear status message: {status}")


def main() -> int:
    started = time.time()
    report = {"status": "running", "steps": []}
    original_functions = {}
    prefs_snapshot = {}
    prefs = None
    credit_api = None
    earth_lifecycle_helpers = None
    try:
        addon_utils.enable("bl_ext.user_default.Planetka", default_set=False)
        from bl_ext.user_default.Planetka import auth, credit_api as _credit_api  # noqa: PLC0415
        from bl_ext.user_default.Planetka.planetka_ops import earth_lifecycle_helpers as _earth_lifecycle_helpers  # noqa: PLC0415
        credit_api = _credit_api
        earth_lifecycle_helpers = _earth_lifecycle_helpers

        prefs = auth.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable")
        prefs_snapshot = _snapshot_prefs(prefs)

        _seed_stale_session(prefs)
        recovered = auth.recover_from_terminal_auth_error(
            auth.AuthApiError(401, "refresh_token_revoked"),
            prefs=prefs,
            source="stale_auth_gate_direct",
        )
        _assert(recovered, "direct recovery did not report recovered")
        _assert_recovered(auth, prefs, "direct_recovery")
        report["steps"].append({"name": "direct_recovery", "ok": True})

        _seed_stale_session(prefs)
        original_functions["credit_get_authorized_headers"] = credit_api.get_authorized_headers

        def _raise_credit_auth(*_args, **_kwargs):
            raise auth.AuthApiError(401, "refresh_token_revoked")

        credit_api.get_authorized_headers = _raise_credit_auth
        try:
            credit_api._request_json("GET", "/me", timeout=1)  # noqa: SLF001
            raise GateFailure("credit_api request unexpectedly succeeded")
        except credit_api.CreditApiError as exc:
            _assert(str(getattr(exc, "error", "") or "") == "account_not_connected", f"unexpected credit_api error: {exc}")
        _assert_recovered(auth, prefs, "credit_api_request")
        report["steps"].append({"name": "credit_api_request", "ok": True})

        _seed_stale_session(prefs)
        original_functions["earth_sync_account_profile"] = earth_lifecycle_helpers.sync_account_profile
        original_functions["earth_get_cloud_connection_status"] = earth_lifecycle_helpers.get_cloud_connection_status

        def _raise_profile_auth(_prefs=None):
            raise auth.AuthApiError(401, "refresh_token_revoked")

        earth_lifecycle_helpers.sync_account_profile = _raise_profile_auth
        earth_lifecycle_helpers.get_cloud_connection_status = lambda **_kwargs: {"online": True, "message": "", "checked": True}
        operator = FakeOperator()
        result = earth_lifecycle_helpers._require_authenticated_account(operator, prefs)  # noqa: SLF001
        _assert(result is False, "Create Earth auth precheck unexpectedly succeeded")
        _assert_recovered(auth, prefs, "create_earth_precheck")
        message_text = " ".join(entry.get("message", "") for entry in operator.messages)
        _assert("session expired" in message_text.lower(), f"Create Earth precheck did not report session expiry: {message_text}")
        report["steps"].append({"name": "create_earth_precheck", "ok": True})

        report["status"] = "ok"
        report["elapsed_sec"] = round(time.time() - started, 3)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print("PLANETKA_STALE_AUTH_RECOVERY_GATE_RESULT " + json.dumps({"status": "ok", "report": str(REPORT_PATH)}, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        report["elapsed_sec"] = round(time.time() - started, 3)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print("PLANETKA_STALE_AUTH_RECOVERY_GATE_RESULT " + json.dumps({"status": "failed", "error": str(exc), "report": str(REPORT_PATH)}, sort_keys=True))
        return 1
    finally:
        try:
            if credit_api is not None and "credit_get_authorized_headers" in original_functions:
                credit_api.get_authorized_headers = original_functions["credit_get_authorized_headers"]
            if earth_lifecycle_helpers is not None and "earth_sync_account_profile" in original_functions:
                earth_lifecycle_helpers.sync_account_profile = original_functions["earth_sync_account_profile"]
            if earth_lifecycle_helpers is not None and "earth_get_cloud_connection_status" in original_functions:
                earth_lifecycle_helpers.get_cloud_connection_status = original_functions["earth_get_cloud_connection_status"]
            if prefs is not None and prefs_snapshot:
                _restore_prefs(prefs, prefs_snapshot)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
