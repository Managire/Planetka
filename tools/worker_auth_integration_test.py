#!/usr/bin/env python3
"""Minimal integration checks for Planetka Worker auth endpoints."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS


def _get_json(url: str, timeout: float = 20.0) -> tuple[int, dict, dict]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body.strip() else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body.strip() else {}
        except TOOL_RECOVERABLE_EXCEPTIONS:
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}, dict(exc.headers.items() if exc.headers else {})


def _post_json(url: str, payload: dict, timeout: float = 20.0) -> tuple[int, dict, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body.strip() else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body.strip() else {}
        except TOOL_RECOVERABLE_EXCEPTIONS:
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}, dict(exc.headers.items() if exc.headers else {})


def _print_result(ok: bool, message: str) -> None:
    prefix = "[PASS]" if ok else "[FAIL]"
    print(f"{prefix} {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Planetka Worker auth integration test")
    parser.add_argument(
        "--base-url",
        default=str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/"),
        help="Worker base URL (default: PLANETKA_API_BASE_URL or https://api.planetka.io)",
    )
    args = parser.parse_args()

    base_url = str(args.base_url or "").rstrip("/")
    if not base_url.startswith("http"):
        print("[FAIL] Invalid base URL.")
        return 1

    failures = 0
    print("Planetka Worker Auth Integration Test")
    print(f"- base_url: {base_url}")

    health_status, health_payload, _ = _get_json(f"{base_url}/health")
    health_ok = health_status == 200 and bool(health_payload.get("ok"))
    _print_result(health_ok, "/health is reachable")
    if not health_ok:
        failures += 1

    invalid_email = f"probe-{int(time.time())}"
    status, payload, _headers = _post_json(
        f"{base_url}/auth/api-key/request",
        {"email": invalid_email, "accept_terms": True, "accept_privacy": True},
    )
    api_key_request_ok = status == 400 and str(payload.get("error", "")).strip() == "invalid_email"
    _print_result(api_key_request_ok, "/auth/api-key/request rejects invalid email")
    if not api_key_request_ok:
        failures += 1

    legacy_checks = [
        ("POST", "/auth/start", {"email": "legacy@example.com"}),
        ("POST", "/auth/verify", {"token": "legacy-token"}),
        ("POST", "/device/start", {}),
        ("POST", "/device/poll", {"device_code": "legacy-device-code"}),
    ]
    for method, path, payload in legacy_checks:
        status, body, _headers = _post_json(f"{base_url}{path}", payload)
        ok = status == 404 and str(body.get("error", "")).strip() == "not_found"
        _print_result(ok, f"{path} removed from public auth surface")
        if not ok:
            failures += 1

    status, body, _headers = _get_json(f"{base_url}/device/login")
    device_login_ok = status == 404 and str(body.get("error", "")).strip() == "not_found"
    _print_result(device_login_ok, "/device/login removed from public auth surface")
    if not device_login_ok:
        failures += 1

    if failures:
        print(f"Integration test failed with {failures} issue(s).")
        return 1
    print("Integration test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
