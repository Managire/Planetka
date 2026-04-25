#!/usr/bin/env python3
"""Internal helper to reset a QA auth account and issue a fresh key/session.

Usage examples:
  python3 tools/worker_auth_qa_reset.py \
    --email free@planetka.io \
    --bearer-token "$PLANETKA_ADMIN_BEARER_TOKEN"

  python3 tools/worker_auth_qa_reset.py \
    --email personal@planetka.io \
    --device-id 1de81a60-831d-4aac-9e66-e86af91a900b \
    --auth-payload-out /tmp/personal_auth.json \
    --api-key-out /tmp/personal_api_key.json \
    --bearer-token "$PLANETKA_ADMIN_BEARER_TOKEN"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS

DEFAULT_BASE_URL = "https://api.planetka.io"


def write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 60.0) -> tuple[int, dict]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=req_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            return int(response.status), body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except TOOL_RECOVERABLE_EXCEPTIONS:
            body = {}
        return int(exc.code), body if isinstance(body, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset internal QA auth account and issue a fresh key.")
    parser.add_argument("--email", required=True, help="Internal QA account email to reset.")
    parser.add_argument(
        "--base-url",
        default=str(os.environ.get("PLANETKA_API_BASE_URL") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        help="Worker base URL. Default: https://api.planetka.io",
    )
    parser.add_argument("--plan-code", default="", help="Optional stored tier override: free, personal, or commercial.")
    parser.add_argument(
        "--bearer-token",
        default=str(os.environ.get("PLANETKA_ADMIN_BEARER_TOKEN") or "").strip(),
        help="Primary admin bearer token. Can also be provided via PLANETKA_ADMIN_BEARER_TOKEN.",
    )
    parser.add_argument(
        "--device-id",
        default=str(
            os.environ.get("PLANETKA_AUTH_DEVICE_ID")
            or os.environ.get("PLANETKA_DEVICE_ID")
            or ""
        ).strip(),
        help="Device id to use for immediate exchange. If omitted, a new UUID is generated when exchange is enabled.",
    )
    parser.add_argument("--no-exchange", action="store_true", help="Only issue a fresh API key; do not exchange it.")
    parser.add_argument("--api-key-out", default="", help="Optional file path to write the fresh API key JSON.")
    parser.add_argument("--auth-payload-out", default="", help="Optional file path to write exchanged auth payload JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bearer_token = str(args.bearer_token or "").strip()
    if not bearer_token:
        print("Missing --bearer-token or PLANETKA_ADMIN_BEARER_TOKEN.", file=sys.stderr)
        return 1

    base_url = str(args.base_url or DEFAULT_BASE_URL).rstrip("/")
    reset_payload = {"email": str(args.email or "").strip()}
    plan_code = str(args.plan_code or "").strip().lower()
    if plan_code:
        reset_payload["plan_code"] = plan_code

    status, payload = post_json(
        f"{base_url}/admin/qa/auth-reset",
        reset_payload,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    if status != 200 or not payload.get("ok"):
        print(json.dumps({"ok": False, "stage": "qa_reset", "status": status, "payload": payload}, indent=2, ensure_ascii=True))
        return 1

    result = {
        "ok": True,
        "qa_reset": payload,
    }

    api_key = str(payload.get("api_key", "") or "").strip()
    if args.api_key_out and api_key:
        write_json(
            args.api_key_out,
            {
                "email": str(payload.get("user_email", "") or "").strip(),
                "plan_code": str(payload.get("plan_code", "") or "").strip(),
                "api_key": api_key,
                "api_key_id": str(payload.get("api_key_id", "") or "").strip(),
                "expires_at": str(payload.get("expires_at", "") or "").strip(),
            },
        )
        result["api_key_out"] = str(args.api_key_out)

    if not args.no_exchange:
        device_id = str(args.device_id or "").strip() or str(uuid.uuid4())
        exchange_status, exchange_payload = post_json(
            f"{base_url}/auth/api-key/exchange",
            {
                "api_key": api_key,
                "device_id": device_id,
            },
        )
        if exchange_status != 200 or not exchange_payload.get("ok"):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "exchange",
                        "status": exchange_status,
                        "device_id": device_id,
                        "qa_reset": payload,
                        "payload": exchange_payload,
                    },
                    indent=2,
                    ensure_ascii=True,
                )
            )
            return 1
        result["device_id"] = device_id
        result["auth_payload"] = exchange_payload
        if args.auth_payload_out:
            write_json(args.auth_payload_out, exchange_payload)
            result["auth_payload_out"] = str(args.auth_payload_out)

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
