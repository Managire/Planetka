#!/usr/bin/env python3
"""Planetka paid-claim lifecycle integration test.

Validates pending -> provisional -> approved / rejected + cooldown behavior
through authenticated admin endpoints.
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


def _expect(ok: bool, message: str, failures: list[str]) -> None:
    _print_check(ok, message)
    if not ok:
        failures.append(message)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _extract_claim_id(payload: dict) -> str:
    return str(payload.get("claim_id") or "").strip()


def _extract_lifecycle(payload: dict) -> dict:
    value = payload.get("lifecycle")
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Planetka paid-claim lifecycle integration test")
    parser.add_argument(
        "--base-url",
        default=str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/"),
        help="API base URL (default: PLANETKA_API_BASE_URL or https://api.planetka.io)",
    )
    parser.add_argument(
        "--bearer-token",
        default=str(os.getenv("PLANETKA_BEARER_TOKEN") or "").strip(),
        help="Admin bearer token (default: PLANETKA_BEARER_TOKEN env)",
    )
    args = parser.parse_args()

    base_url = str(args.base_url or "").rstrip("/")
    token = str(args.bearer_token or "").strip()
    if not base_url.startswith("http"):
        print("[FAIL] Invalid --base-url")
        return 1
    if not token:
        print("[FAIL] Missing --bearer-token (or PLANETKA_BEARER_TOKEN).")
        return 1

    failures: list[str] = []
    auth_headers = _auth_headers(token)
    ts = int(time.time())
    email_approve = f"ci-paid-approve-{ts}@example.com"
    email_reject = f"ci-paid-reject-{ts}@example.com"
    email_pending = f"ci-paid-pending-{ts}@example.com"

    # 1) pending lifecycle + single pending guard
    status, payload = _post_json(
        f"{base_url}/admin/claims/create",
        {
            "email": email_pending,
            "requested_plan": "planetka_pro",
            "order_id": f"ORDER-PENDING-{ts}",
            "device_id": "ci-device-pending",
        },
        headers=auth_headers,
    )
    claim_pending_id = _extract_claim_id(payload)
    lifecycle = _extract_lifecycle(payload)
    _expect(status == 200 and bool(claim_pending_id), "Create paid claim enters pending state", failures)
    _expect(
        str(((lifecycle.get("claim") or {}).get("review_status") or "")).strip().lower() == "pending",
        "New claim review_status is pending",
        failures,
    )

    status, payload = _post_json(
        f"{base_url}/admin/claims/create",
        {
            "email": email_pending,
            "requested_plan": "planetka_pro",
            "order_id": f"ORDER-PENDING-SECOND-{ts}",
            "device_id": "ci-device-pending-2",
        },
        headers=auth_headers,
    )
    _expect(
        status == 409 and str(payload.get("error") or "").strip() == "paid_claim_pending_review",
        "Second pending paid claim is blocked",
        failures,
    )

    # 2) pending -> provisional -> approved
    status, payload = _post_json(
        f"{base_url}/admin/claims/create",
        {
            "email": email_approve,
            "requested_plan": "planetka_pro",
            "order_id": f"ORDER-APPROVE-{ts}",
            "device_id": "ci-device-approve",
        },
        headers=auth_headers,
    )
    claim_approve_id = _extract_claim_id(payload)
    _expect(status == 200 and bool(claim_approve_id), "Create approvable paid claim", failures)

    status, payload = _post_json(
        f"{base_url}/admin/claims/activate",
        {"claim_id": claim_approve_id},
        headers=auth_headers,
    )
    lifecycle = _extract_lifecycle(payload)
    entitlement_state = str(((lifecycle.get("entitlement") or {}).get("state") or "")).strip().lower()
    _expect(status == 200, "Activate paid claim succeeded", failures)
    _expect(entitlement_state == "provisional_paid", "Claim activation enters provisional state", failures)

    status, payload = _post_json(
        f"{base_url}/admin/claims/review",
        {
            "claim_id": claim_approve_id,
            "decision": "approved",
            "review_note": "ci_lifecycle_approved",
        },
        headers=auth_headers,
    )
    lifecycle = _extract_lifecycle(payload)
    approved_review = str(((lifecycle.get("claim") or {}).get("review_status") or "")).strip().lower()
    approved_entitlement = str(((lifecycle.get("entitlement") or {}).get("state") or "")).strip().lower()
    approved_confirmed_at = str(((lifecycle.get("user") or {}).get("pro_confirmed_at") or "")).strip()
    _expect(status == 200, "Approve paid claim succeeded", failures)
    _expect(approved_review == "approved", "Approved claim review_status persisted", failures)
    _expect(approved_entitlement == "permanent_paid", "Approved claim becomes permanent paid", failures)
    _expect(bool(approved_confirmed_at), "Approved claim sets pro_confirmed_at", failures)

    # 3) pending -> provisional -> rejected -> cooldown
    status, payload = _post_json(
        f"{base_url}/admin/claims/create",
        {
            "email": email_reject,
            "requested_plan": "planetka_studio",
            "order_id": f"ORDER-REJECT-{ts}",
            "device_id": "ci-device-reject",
        },
        headers=auth_headers,
    )
    claim_reject_id = _extract_claim_id(payload)
    _expect(status == 200 and bool(claim_reject_id), "Create rejectable paid claim", failures)

    status, payload = _post_json(
        f"{base_url}/admin/claims/activate",
        {"claim_id": claim_reject_id},
        headers=auth_headers,
    )
    lifecycle = _extract_lifecycle(payload)
    rejected_activation_state = str(((lifecycle.get("entitlement") or {}).get("state") or "")).strip().lower()
    _expect(status == 200, "Activate rejectable paid claim succeeded", failures)
    _expect(rejected_activation_state == "provisional_paid", "Rejectable claim activation is provisional", failures)

    status, payload = _post_json(
        f"{base_url}/admin/claims/review",
        {
            "claim_id": claim_reject_id,
            "decision": "rejected",
            "review_note": "ci_lifecycle_rejected",
            "cooldown_days": 7,
        },
        headers=auth_headers,
    )
    lifecycle = _extract_lifecycle(payload)
    rejected_review = str(((lifecycle.get("claim") or {}).get("review_status") or "")).strip().lower()
    rejected_cooldown = str(((lifecycle.get("claim") or {}).get("cooldown_until") or "")).strip()
    rejected_status = str(((lifecycle.get("user") or {}).get("status") or "")).strip().lower()
    _expect(status == 200, "Reject paid claim succeeded", failures)
    _expect(rejected_review == "rejected", "Rejected claim review_status persisted", failures)
    _expect(bool(rejected_cooldown), "Rejected claim sets cooldown_until", failures)
    _expect(rejected_status == "planetka", "Rejected claim falls back to free status", failures)

    # Cooldown guard in public request flow.
    status, payload = _post_json(
        f"{base_url}/auth/api-key/request",
        {
            "email": email_reject,
            "requested_plan": "planetka_pro",
            "order_id": f"ORDER-COOLDOWN-RETRY-{ts}",
            "accept_terms": True,
            "accept_privacy": True,
            "opt_in_news": False,
            "submitted_at_ms": int(time.time() * 1000),
            "device_id": "ci-device-reject-retry",
        },
    )
    _expect(
        status == 429 and str(payload.get("error") or "").strip() == "paid_claim_cooldown_active",
        "Cooldown blocks new paid claim request",
        failures,
    )

    # Fetch latest lifecycle snapshot endpoint sanity.
    status, payload = _get_json(
        f"{base_url}/admin/claims/latest?email={email_approve}",
        headers=auth_headers,
    )
    lifecycle = _extract_lifecycle(payload)
    _expect(status == 200 and bool(lifecycle), "Latest claim lifecycle endpoint returns data", failures)

    if failures:
        print(f"\nLifecycle integration failed with {len(failures)} issue(s).")
        return 1
    print("\nLifecycle integration passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
