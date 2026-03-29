#!/usr/bin/env python3
"""Planetka entitlement flow compatibility test.

This keeps the historical script entrypoint but validates the new model:
- provisional/manual paid-claim endpoints are disabled
- public API-key request ignores paid-plan tampering and stays on free flow
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 25.0) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            return int(response.status), payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception:
            payload = {}
        return int(exc.code), payload if isinstance(payload, dict) else {}


def _post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: float = 25.0,
) -> tuple[int, dict]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            return int(response.status), body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except Exception:
            body = {}
        return int(exc.code), body if isinstance(body, dict) else {}


def _print_check(ok: bool, message: str) -> None:
    print(f"{'[PASS]' if ok else '[FAIL]'} {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Planetka entitlement flow compatibility test")
    parser.add_argument(
        "--base-url",
        default=str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/"),
        help="API base URL (default: PLANETKA_API_BASE_URL or https://api.planetka.io)",
    )
    parser.add_argument(
        "--bearer-token",
        default=str(os.getenv("PLANETKA_BEARER_TOKEN") or "").strip(),
        help="Admin bearer token for disabled claim-route checks",
    )
    args = parser.parse_args()

    base_url = str(args.base_url or "").rstrip("/")
    token = str(args.bearer_token or "").strip()
    if not base_url.startswith("http"):
        print("[FAIL] Invalid --base-url")
        return 1

    failures = 0
    checks = 0
    auth_headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 1) Public API key request ignores requested paid plan and still succeeds.
    checks += 1
    status, payload = _post_json(
        f"{base_url}/auth/api-key/request",
        {
            "email": f"ci-free-{int(time.time())}@example.com",
            "requested_plan": "planetka_pro",
            "accept_terms": True,
            "accept_privacy": True,
            "opt_in_news": False,
            "submitted_at_ms": 9999,
        },
    )
    ok = status == 200 and bool(payload.get("ok"))
    _print_check(ok, "Public key request succeeds when paid plan is requested (forced free flow)")
    if not ok:
        failures += 1

    # 2) Legacy paid-claim admin routes are disabled.
    checks += 1
    status, payload = _get_json(f"{base_url}/admin/claims/latest?email=ci@example.com", headers=auth_headers)
    ok = status == 410 and str(payload.get("error") or "").strip() == "paid_claim_workflow_disabled"
    _print_check(ok, "Admin claims latest endpoint disabled")
    if not ok:
        failures += 1

    checks += 1
    status, payload = _post_json(
        f"{base_url}/admin/claims/create",
        {
            "email": "ci@example.com",
            "requested_plan": "planetka_pro",
            "order_id": "ORDER-CI",
        },
        headers=auth_headers,
    )
    ok = status == 410 and str(payload.get("error") or "").strip() == "paid_claim_workflow_disabled"
    _print_check(ok, "Admin claims create endpoint disabled")
    if not ok:
        failures += 1

    checks += 1
    status, payload = _post_json(
        f"{base_url}/admin/claims/review",
        {"claim_id": "00000000-0000-0000-0000-000000000000", "decision": "approved"},
        headers=auth_headers,
    )
    ok = status == 410 and str(payload.get("error") or "").strip() == "paid_claim_workflow_disabled"
    _print_check(ok, "Admin claims review endpoint disabled")
    if not ok:
        failures += 1

    print(f"\nSummary: {checks - failures}/{checks} checks passed")
    if failures:
        print(f"Compatibility test failed with {failures} issue(s).")
        return 1
    print("Compatibility test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
