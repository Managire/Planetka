#!/usr/bin/env python3
"""Planetka pre-launch abuse simulation checks (API + source guards)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            return int(resp.status), payload if isinstance(payload, dict) else {}, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except TOOL_RECOVERABLE_EXCEPTIONS:
            payload = {}
        return int(exc.code), payload if isinstance(payload, dict) else {}, dict(exc.headers.items() if exc.headers else {})


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 20.0) -> tuple[int, dict, dict]:
    base_headers = {"Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=base_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            return int(resp.status), body if isinstance(body, dict) else {}, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except TOOL_RECOVERABLE_EXCEPTIONS:
            body = {}
        return int(exc.code), body if isinstance(body, dict) else {}, dict(exc.headers.items() if exc.headers else {})


def _print_check(ok: bool, message: str) -> None:
    print(f"{'[PASS]' if ok else '[FAIL]'} {message}")


def _print_skip(message: str) -> None:
    print(f"[SKIP] {message}")


def _status_counts(values: list[int]) -> str:
    counts: dict[int, int] = {}
    for val in values:
        counts[val] = counts.get(val, 0) + 1
    return ", ".join(f"{code}x{count}" for code, count in sorted(counts.items()))


def _run_static_guard_checks(root: Path) -> tuple[int, int]:
    src_dir = root / "cloudflare-api" / "src"
    source_paths = [src_dir / "index.js", *sorted((src_dir / "worker").glob("*.js"))]
    source_map = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in source_paths
        if path.is_file()
    }

    failures = 0
    checks = 0
    required_markers = [
        (
            "free multi-key guard function exists",
            ["async function enforceSingleActiveFreeApiKey"],
        ),
        (
            "free key issue path enforces single active key",
            ["await deps.enforceSingleActiveFreeApiKey(", "await enforceSingleActiveFreeApiKey("],
        ),
        (
            "all plans enforce single-device runtime",
            ["function maxDevicesForPlan(planCode)"],
        ),
        (
            "max device count hardcoded to 1",
            ["return 1;"],
        ),
        (
            "issue-time device-limit enforcement exists",
            ["await deps.enforceApiKeyIssueDeviceLimit(", "await enforceApiKeyIssueDeviceLimit("],
        ),
        (
            "public API key request forces free plan",
            ["const requestedPlan = deps.PLAN_CODE_FREE;", "const requestedPlan = PLAN_CODE_FREE;"],
        ),
        (
            "admin query-token rejection enabled",
            ["query_token_not_allowed"],
        ),
    ]

    for label, markers in required_markers:
        checks += 1
        ok = any(marker in src for marker in markers for src in source_map.values())
        _print_check(ok, f"Static guard: {label}")
        if not ok:
            failures += 1

    return checks, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Planetka abuse simulation checks")
    parser.add_argument(
        "--base-url",
        default=str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/"),
        help="Worker base URL (default: PLANETKA_API_BASE_URL or https://api.planetka.io)",
    )
    parser.add_argument(
        "--bearer-token",
        default=str(os.getenv("PLANETKA_BEARER_TOKEN") or "").strip(),
        help="Optional access token for authenticated high-volume tile checks",
    )
    parser.add_argument(
        "--tile-path",
        default=str(os.getenv("PLANETKA_TEST_TILE_PATH") or "/tiles/S2/S2_x000_y000_z360_d360.exr").strip(),
        help="Tile path used for high-volume requests",
    )
    parser.add_argument(
        "--tile-requests",
        type=int,
        default=int(os.getenv("PLANETKA_TILE_VOLUME_REQUESTS") or "120"),
        help="Number of tile requests in high-volume simulation",
    )
    parser.add_argument(
        "--analytics-minutes",
        type=int,
        default=int(os.getenv("PLANETKA_ABUSE_ANALYTICS_MINUTES") or "30"),
        help="Lookback window for telemetry evidence check (default: 30)",
    )
    args = parser.parse_args()

    base_url = str(args.base_url or "").rstrip("/")
    tile_path = str(args.tile_path or "").strip()
    bearer_token = str(args.bearer_token or "").strip()
    tile_requests = max(1, int(args.tile_requests))
    analytics_minutes = max(5, int(args.analytics_minutes))

    if not base_url.startswith("http"):
        print("[FAIL] Invalid --base-url")
        return 1
    if not tile_path.startswith("/"):
        tile_path = f"/{tile_path}"

    print("Planetka Abuse Simulation")
    print(f"- base_url: {base_url}")
    print(f"- tile_path: {tile_path}")
    print(f"- tile_requests: {tile_requests}")

    checks = 0
    failures = 0

    checks += 1
    health_status, health_payload, _ = _get_json(f"{base_url}/health")
    ok = health_status == 200 and bool(health_payload.get("ok"))
    _print_check(ok, "/health reachable")
    if not ok:
        failures += 1

    checks += 1
    status, payload, _ = _post_json(f"{base_url}/auth/start", {"email": "legacy-probe"})
    ok = status == 404 and str(payload.get("error", "")).strip() == "not_found"
    _print_check(ok, "Legacy /auth/start endpoint removed")
    if not ok:
        failures += 1

    _print_skip(
        "Public account-creation probes removed. This simulation uses provided internal accounts only unless explicitly changed."
    )

    checks += 1
    leak_url = f"{base_url}/admin/analytics?access_token=fake"
    status, payload, _ = _get_json(leak_url)
    ok = status == 400 and str(payload.get("error", "")).strip() == "query_token_not_allowed"
    _print_check(ok, "Admin analytics rejects query token on HTML endpoint")
    if not ok:
        failures += 1

    checks += 1
    leak_data_url = f"{base_url}/admin/analytics/data?minutes=60&access_token=fake"
    status, payload, _ = _get_json(leak_data_url)
    ok = status == 400 and str(payload.get("error", "")).strip() == "query_token_not_allowed"
    _print_check(ok, "Admin analytics rejects query token on JSON endpoint")
    if not ok:
        failures += 1

    tile_statuses: list[int] = []
    tile_headers = {"X-Planetka-Device-Id": "abuse-sim-device-01"}
    if bearer_token:
        tile_headers["Authorization"] = f"Bearer {bearer_token}"

    tile_url = f"{base_url}{tile_path}"
    for _ in range(tile_requests):
        status, _payload, _ = _get_json(tile_url, headers=tile_headers, timeout=30.0)
        tile_statuses.append(status)

    checks += 1
    status_set = set(tile_statuses)
    ok = all(code < 500 for code in status_set)
    _print_check(ok, f"High-volume tile requests returned no 5xx ({_status_counts(tile_statuses)})")
    if not ok:
        failures += 1

    if bearer_token:
        checks += 1
        analytics_headers = {"Authorization": f"Bearer {bearer_token}"}
        analytics_url = f"{base_url}/admin/analytics/data?minutes={analytics_minutes}"
        status, payload, _ = _get_json(analytics_url, headers=analytics_headers, timeout=30.0)
        if status != 200 or not payload.get("ok"):
            _print_check(False, "Analytics evidence check failed (admin analytics endpoint unavailable)")
            failures += 1
        else:
            failures_feed = payload.get("recent_failures") or []
            observed = False
            for row in failures_feed:
                if int(row.get("status_code") or 0) in {401, 402, 403, 404, 429}:
                    observed = True
                    break
            _print_check(observed, "Analytics evidence contains recent blocked/error tile events")
            if not observed:
                failures += 1

    static_checks, static_failures = _run_static_guard_checks(Path(__file__).resolve().parents[1])
    checks += static_checks
    failures += static_failures

    print(f"\nSummary: {checks - failures}/{checks} checks passed")
    if failures:
        print(f"Simulation failed with {failures} issue(s).")
        return 1

    print("Simulation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
