#!/usr/bin/env python3
"""Live probe for materialized product quote queue behavior.

This targets the deployed sandbox backend and the internal test account only.
It does not create Stripe payments. It creates temporary data-pack detail tokens,
requests product/catalog pages, and observes whether quote jobs progress without
public routes doing heavy synchronous pricing work or returning Worker limit
errors.
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import os
import random
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE_DIR = ROOT / "cloudflare-api"
API_BASE = os.environ.get("PLANETKA_API_BASE", "https://api.planetka.io").rstrip("/")
TARGET_EMAIL = os.environ.get("PLANETKA_LIVE_PROBE_EMAIL", "tom.griger@gmail.com").strip().lower()
NORMAL_PRODUCTS = [p.strip() for p in os.environ.get("PLANETKA_LIVE_PROBE_NORMAL_PRODUCTS", "slovakia,asia,world").split(",") if p.strip()]
STRESS_PRODUCTS = [p.strip() for p in os.environ.get("PLANETKA_LIVE_PROBE_STRESS_PRODUCTS", "world,asia,europe,north_america,germany,slovakia").split(",") if p.strip()]
STRESS_REQUESTS = int(os.environ.get("PLANETKA_LIVE_PROBE_STRESS_REQUESTS", "48") or "48")
STRESS_CONCURRENCY = int(os.environ.get("PLANETKA_LIVE_PROBE_STRESS_CONCURRENCY", "16") or "16")
READY_TIMEOUT_SEC = float(os.environ.get("PLANETKA_LIVE_PROBE_READY_TIMEOUT_SEC", "180") or "180")
POLL_SEC = float(os.environ.get("PLANETKA_LIVE_PROBE_POLL_SEC", "4") or "4")


def _sql_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _extract_json_array(stdout: str) -> list[dict[str, Any]]:
    text = str(stdout or "")
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise RuntimeError(f"Could not parse wrangler JSON output: {text[-1000:]}")
    return json.loads(text[start:end + 1])


def run_d1(sql: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["npx", "wrangler", "d1", "execute", "planetka-auth", "--remote", "--command", sql],
        cwd=str(CLOUDFLARE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip())
    return _extract_json_array(proc.stdout)


def first_results(sql: str) -> list[dict[str, Any]]:
    payload = run_d1(sql)
    if not payload:
        return []
    return list(payload[0].get("results") or [])


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def add_hours_iso(hours: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + hours * 3600))


def get_user_id() -> str:
    rows = first_results(
        "SELECT id, email FROM users WHERE LOWER(email) = " + _sql_quote(TARGET_EMAIL) + " LIMIT 1"
    )
    if not rows:
        raise RuntimeError(f"Test user not found: {TARGET_EMAIL}")
    return str(rows[0].get("id") or "").strip()


def cleanup_user_quotes(user_id: str) -> None:
    run_d1(
        "DELETE FROM user_product_quote_jobs WHERE user_id = " + _sql_quote(user_id) + ";"
        "DELETE FROM user_product_quote_batches WHERE user_id = " + _sql_quote(user_id) + ";"
        "DELETE FROM user_product_quotes WHERE user_id = " + _sql_quote(user_id) + ";"
        "DELETE FROM region_pack_detail_tokens WHERE user_id = " + _sql_quote(user_id)
        + " AND token LIKE 'probe_%';"
    )


def create_detail_token(user_id: str, product_id: str) -> str:
    token = "probe_" + secrets.token_urlsafe(24).replace("-", "_")
    run_d1(
        "INSERT INTO region_pack_detail_tokens (token, user_id, region_pack_id, created_at, expires_at) VALUES ("
        + ",".join([
            _sql_quote(token),
            _sql_quote(user_id),
            _sql_quote(product_id),
            _sql_quote(now_iso()),
            _sql_quote(add_hours_iso(2)),
        ])
        + ")"
    )
    return token


@dataclass
class FetchResult:
    url: str
    status: int
    elapsed_ms: int
    body: str
    error: str = ""


def fetch_url(url: str, timeout: float = 45) -> FetchResult:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return FetchResult(url=url, status=int(response.status), elapsed_ms=round((time.perf_counter() - started) * 1000), body=body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return FetchResult(url=url, status=int(exc.code), elapsed_ms=round((time.perf_counter() - started) * 1000), body=body, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url=url, status=0, elapsed_ms=round((time.perf_counter() - started) * 1000), body="", error=str(exc))


def parse_map_data(body: str) -> dict[str, Any]:
    match = re.search(r"window\.PLANETKA_REGION_PACK_DATA=(\{.*?\});</script>", body, re.S)
    if not match:
        return {}
    return json.loads(html.unescape(match.group(1)))


def queue_summary() -> dict[str, Any]:
    rows = first_results(
        "SELECT status, COUNT(*) AS count FROM user_product_quote_jobs GROUP BY status ORDER BY status"
    )
    return {str(row.get("status") or ""): int(row.get("count") or 0) for row in rows}


def quote_summary(user_id: str) -> dict[str, Any]:
    rows = first_results(
        "SELECT COUNT(*) AS quotes,"
        " SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) AS ready,"
        " SUM(CASE WHEN map_state_status='ready' THEN 1 ELSE 0 END) AS maps_ready"
        " FROM user_product_quotes WHERE user_id = " + _sql_quote(user_id)
    )
    row = rows[0] if rows else {}
    return {key: int(row.get(key) or 0) for key in ("quotes", "ready", "maps_ready")}


def wait_product_ready(user_id: str, product_id: str) -> dict[str, Any]:
    token = create_detail_token(user_id, product_id)
    url = f"{API_BASE}/credits/region-pack-map?token={urllib.parse.quote(token)}&region_pack_id={urllib.parse.quote(product_id)}"
    started = time.perf_counter()
    attempts = 0
    first_status = None
    first_elapsed_ms = None
    last_data: dict[str, Any] = {}
    last_fetch: FetchResult | None = None
    while time.perf_counter() - started <= READY_TIMEOUT_SEC:
        attempts += 1
        result = fetch_url(url)
        last_fetch = result
        if first_status is None:
            first_status = result.status
            first_elapsed_ms = result.elapsed_ms
        if result.status >= 500 or result.status == 0 or "1102" in result.body:
            return {
                "product_id": product_id,
                "ok": False,
                "error": result.error or "server_error",
                "status": result.status,
                "elapsed_ms": result.elapsed_ms,
                "body_sample": result.body[:240],
            }
        data = parse_map_data(result.body)
        last_data = data
        if data and not bool(data.get("price_pending")) and not bool(data.get("map_pending")) and data.get("quote"):
            summary = data.get("summary") or {}
            return {
                "product_id": product_id,
                "ok": True,
                "attempts": attempts,
                "first_status": first_status,
                "first_elapsed_ms": first_elapsed_ms,
                "ready_seconds": round(time.perf_counter() - started, 3),
                "final_price_cents": int(summary.get("price_cents") or 0),
                "new_tiles": int(summary.get("new_tiles") or 0),
                "total_tiles": int(summary.get("total_tiles") or 0),
                "queue": queue_summary(),
            }
        time.sleep(max(1.0, POLL_SEC))
    return {
        "product_id": product_id,
        "ok": False,
        "error": "timeout_waiting_for_ready_quote_and_map",
        "attempts": attempts,
        "last_status": last_fetch.status if last_fetch else 0,
        "last_data": {
            "price_pending": bool(last_data.get("price_pending")),
            "map_pending": bool(last_data.get("map_pending")),
            "quote_status": last_data.get("quote_status"),
            "map_state_status": last_data.get("map_state_status"),
        },
        "queue": queue_summary(),
    }


def fetch_catalog_page(token: str, offset: int = 0, limit: int = 20) -> FetchResult:
    params = urllib.parse.urlencode({"token": token, "offset": offset, "limit": limit})
    return fetch_url(f"{API_BASE}/credits/region-pack-catalog-page?{params}")


def run_stress(user_id: str) -> dict[str, Any]:
    tokens = {product_id: create_detail_token(user_id, product_id) for product_id in STRESS_PRODUCTS}
    catalog_token = create_detail_token(user_id, STRESS_PRODUCTS[0] if STRESS_PRODUCTS else "world")
    urls: list[str] = []
    for index in range(STRESS_REQUESTS):
        if index % 5 == 0:
            offset = (index * 20) % 300
            urls.append(f"{API_BASE}/credits/region-pack-catalog-page?token={urllib.parse.quote(catalog_token)}&offset={offset}&limit=20")
        else:
            product_id = STRESS_PRODUCTS[index % len(STRESS_PRODUCTS)]
            token = tokens[product_id]
            urls.append(f"{API_BASE}/credits/region-pack-map?token={urllib.parse.quote(token)}&region_pack_id={urllib.parse.quote(product_id)}")
    random.Random(20260515).shuffle(urls)
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, STRESS_CONCURRENCY)) as pool:
        results = list(pool.map(fetch_url, urls))
    elapsed = round(time.perf_counter() - started, 3)
    bad = [
        {
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
            "body_sample": result.body[:180],
        }
        for result in results
        if result.status == 0 or result.status >= 500 or "1102" in result.body
    ]
    statuses: dict[str, int] = {}
    for result in results:
        statuses[str(result.status)] = statuses.get(str(result.status), 0) + 1
    queue_after_burst = queue_summary()
    queue_timeline = []
    drain_started = time.perf_counter()
    while time.perf_counter() - drain_started <= READY_TIMEOUT_SEC:
        snapshot = queue_summary()
        queue_timeline.append({
            "t_seconds": round(time.perf_counter() - drain_started, 1),
            "queue": snapshot,
            "quotes": quote_summary(user_id),
        })
        if not snapshot.get("queued") and not snapshot.get("running"):
            break
        # A light catalog request is enough to kick one bounded job if cron is delayed.
        fetch_catalog_page(catalog_token, 0, 5)
        time.sleep(max(1.0, POLL_SEC))
    return {
        "ok": not bad,
        "requests": len(results),
        "concurrency": STRESS_CONCURRENCY,
        "elapsed_seconds": elapsed,
        "status_counts": statuses,
        "server_errors": bad[:10],
        "queue_after_burst": queue_after_burst,
        "queue_timeline": queue_timeline,
    }


def main() -> int:
    user_id = get_user_id()
    cleanup_user_quotes(user_id)
    report: dict[str, Any] = {
        "ok": True,
        "email": TARGET_EMAIL,
        "user_id": user_id,
        "normal_products": [],
        "stress": {},
    }
    for product_id in NORMAL_PRODUCTS:
        result = wait_product_ready(user_id, product_id)
        report["normal_products"].append(result)
        if not result.get("ok"):
            report["ok"] = False
    cleanup_user_quotes(user_id)
    stress = run_stress(user_id)
    report["stress"] = stress
    if not stress.get("ok"):
        report["ok"] = False
    final_queue = queue_summary()
    report["final_queue_before_cleanup"] = final_queue
    cleanup_user_quotes(user_id)
    report["final_queue_after_cleanup"] = queue_summary()
    print("PLANETKA_QUOTE_QUEUE_LIVE_PROBE_RESULT " + json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
