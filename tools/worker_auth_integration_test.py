#!/usr/bin/env python3
"""Minimal integration checks for Planetka auth/device Worker endpoints."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request


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
        except Exception:
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
        except Exception:
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}, dict(exc.headers.items() if exc.headers else {})


def _fmt_status_counts(statuses: list[int]) -> str:
    counts: dict[int, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{code}x{count}" for code, count in sorted(counts.items()))


def _print_result(ok: bool, message: str) -> None:
    prefix = "[PASS]" if ok else "[FAIL]"
    print(f"{prefix} {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Planetka Worker auth/device integration test")
    parser.add_argument(
        "--base-url",
        default=str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/"),
        help="Worker base URL (default: PLANETKA_API_BASE_URL or https://api.planetka.io)",
    )
    parser.add_argument(
        "--auth-rate-limit-attempts",
        type=int,
        default=8,
        help="How many /auth/start attempts to run for 429 check (default: 8)",
    )
    parser.add_argument(
        "--device-poll-rate-limit-attempts",
        type=int,
        default=140,
        help="How many /device/poll attempts to run for 429 check (default: 140)",
    )
    args = parser.parse_args()

    base_url = str(args.base_url or "").rstrip("/")
    if not base_url.startswith("http"):
        print("[FAIL] Invalid base URL.")
        return 1

    failures = 0
    print(f"Planetka Worker Auth Integration Test")
    print(f"- base_url: {base_url}")
    health_status, health_payload, _ = _get_json(f"{base_url}/health")
    magic_link_enabled = bool(health_status == 200 and health_payload.get("magic_link_auth_enabled"))
    print(f"- magic_link_auth_enabled: {magic_link_enabled}")

    if not magic_link_enabled:
        status, payload, _headers = _post_json(f"{base_url}/auth/start", {"email": f"probe-{int(time.time())}@example.com"})
        auth_disabled_ok = status == 404 and str(payload.get("error", "")).strip() == "magic_link_auth_disabled"
        _print_result(auth_disabled_ok, "/auth/start disabled when legacy magic-link auth is off")
        if not auth_disabled_ok:
            failures += 1

        status, payload, _headers = _post_json(f"{base_url}/device/start", {})
        device_disabled_ok = status == 404 and str(payload.get("error", "")).strip() == "magic_link_auth_disabled"
        _print_result(device_disabled_ok, "/device/start disabled when legacy magic-link auth is off")
        if not device_disabled_ok:
            failures += 1

        if failures:
            print(f"Integration test failed with {failures} issue(s).")
            return 1
        print("Integration test passed.")
        return 0

    # 1) auth/start basic shape + 429 behavior using invalid email (no email is sent)
    auth_statuses: list[int] = []
    auth_429_payload = {}
    auth_probe = f"rate-limit-probe-{int(time.time())}"
    for _ in range(max(1, int(args.auth_rate_limit_attempts))):
        status, payload, _headers = _post_json(f"{base_url}/auth/start", {"email": auth_probe})
        auth_statuses.append(status)
        if status == 429:
            auth_429_payload = payload
            break
    saw_auth_429 = 429 in auth_statuses
    _print_result(
        saw_auth_429,
        f"/auth/start rate limiting observed ({_fmt_status_counts(auth_statuses)})",
    )
    if not saw_auth_429:
        failures += 1
    elif not isinstance(auth_429_payload.get("retry_after_seconds"), int):
        _print_result(False, "/auth/start 429 payload missing integer retry_after_seconds")
        failures += 1

    # 2) device/start baseline
    status, payload, _headers = _post_json(f"{base_url}/device/start", {})
    device_code = str(payload.get("device_code", "") or "").strip()
    device_start_ok = status == 200 and bool(device_code)
    _print_result(device_start_ok, "/device/start returned device_code")
    if not device_start_ok:
        failures += 1
        return failures

    # 3) device/poll baseline (pending)
    status, payload, _headers = _post_json(f"{base_url}/device/poll", {"device_code": device_code})
    poll_baseline_ok = status == 200 and str(payload.get("status", "")).lower() in {"pending", "completed"}
    _print_result(poll_baseline_ok, "/device/poll baseline returned pending/completed")
    if not poll_baseline_ok:
        failures += 1

    # 4) device/poll 429 behavior
    poll_statuses: list[int] = []
    poll_429_payload = {}
    for _ in range(max(1, int(args.device_poll_rate_limit_attempts))):
        status, payload, _headers = _post_json(f"{base_url}/device/poll", {"device_code": device_code})
        poll_statuses.append(status)
        if status == 429:
            poll_429_payload = payload
            break
        # Stop early if session leaves pending state in this environment.
        if status in {408, 410, 404}:
            break
    saw_poll_429 = 429 in poll_statuses
    _print_result(
        saw_poll_429,
        f"/device/poll rate limiting observed ({_fmt_status_counts(poll_statuses)})",
    )
    if not saw_poll_429:
        failures += 1
    elif not isinstance(poll_429_payload.get("retry_after_seconds"), int):
        _print_result(False, "/device/poll 429 payload missing integer retry_after_seconds")
        failures += 1

    if failures:
        print(f"Integration test failed with {failures} issue(s).")
        return 1
    print("Integration test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
