#!/usr/bin/env python3
"""
Bounded live Planetka pricing consistency gate.

Run with Blender Python so the installed add-on authentication is reused:

  /Applications/Blender5.0.app/Contents/MacOS/Blender --background --python tools/live_pricing_consistency_e2e.py

This gate is intentionally deterministic and small. It does not search the
catalog for chargeable products and it does not complete Stripe card payments.
It validates the customer-visible money path by comparing:

- Blender/API scene estimate -> scene checkout amount -> post-entitlement zero
- product map materialized quote -> checkout redirect amount -> post-entitlement zero

Synthetic entitlements are inserted directly into the internal test account and
removed again at the end. This keeps the test repeatable without creating real
payments or stressing production Workers.
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(
    "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka"
)
CLOUDFLARE_DIR = ROOT / "cloudflare-api"
CATALOG_PATH = ROOT / "cloudflare-api/src/worker/region_packs.generated.js"
CATALOG_PRODUCTS_PATH = ROOT / "cloudflare-api/src/worker/region_packs.products.generated.js"
CATALOG_TILE_DATA_PATH = ROOT / "cloudflare-api/src/worker/region_packs.tile_data.generated.js"
API_BASE = os.environ.get("PLANETKA_API_BASE", "https://api.planetka.io").rstrip("/")
TARGET_EMAIL = os.environ.get("PLANETKA_E2E_EMAIL", "tom.griger@gmail.com").strip().lower()

# Fixed default targets. Keep these small: this is a regular health gate, not a stress test.
SCENE_TARGET_SPECS = os.environ.get("PLANETKA_E2E_SCENE_TARGETS", "slovakia:2,belgium:2")
COUNTRY_TARGET_IDS = os.environ.get("PLANETKA_E2E_COUNTRY_TARGETS", "belize")
REGION_TARGET_IDS = os.environ.get("PLANETKA_E2E_REGION_TARGETS", "central_europe")
PACE_SEC = float(os.environ.get("PLANETKA_E2E_PACE_SEC", "1.0") or "1.0")
QUOTE_WAIT_TIMEOUT_SEC = float(os.environ.get("PLANETKA_E2E_QUOTE_WAIT_TIMEOUT_SEC", "180") or "180")
QUOTE_WAIT_POLL_SEC = float(os.environ.get("PLANETKA_E2E_QUOTE_WAIT_POLL_SEC", "4") or "4")
CLEANUP_AFTER = str(os.environ.get("PLANETKA_E2E_CLEANUP_AFTER") or "1").strip().lower() not in {"0", "false", "no", "off"}
RESET_BEFORE = str(os.environ.get("PLANETKA_E2E_RESET_BEFORE") or "1").strip().lower() not in {"0", "false", "no", "off"}
REQUIRE_PAID_PATH = str(os.environ.get("PLANETKA_E2E_REQUIRE_PAID_PATH") or "1").strip().lower() not in {"0", "false", "no", "off"}
ALLOW_LIVE_STRESS = str(os.environ.get("PLANETKA_ALLOW_LIVE_STRESS") or "").strip().lower() in {"1", "true", "yes", "on"}

REGULAR_MAX_SCENE_SAMPLES = 6
REGULAR_MAX_PACK_TARGETS = 4
REGULAR_MAX_PRODUCT_TILES = 700


@dataclass
class Failure:
    phase: str
    target: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stats:
    scene_checks: int = 0
    country_checks: int = 0
    region_checks: int = 0
    paid_scene_checks: int = 0
    paid_pack_checks: int = 0
    checkout_sessions: int = 0
    checkout_redirects: int = 0
    direct_granted_tiles: int = 0
    synthetic_pack_purchases: int = 0
    skipped_already_owned: int = 0
    timings: list[dict[str, Any]] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)

    def fail(self, phase: str, target: str, message: str, **details: Any) -> None:
        self.failures.append(Failure(phase=phase, target=target, message=message, details=details))

    def timing(self, phase: str, target: str, elapsed_ms: int, **details: Any) -> None:
        self.timings.append({"phase": phase, "target": target, "elapsed_ms": elapsed_ms, **details})


class Timer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def money_cents(value: Any) -> int:
    try:
        return int(round(float(value or 0) * 100))
    except (TypeError, ValueError):
        return 0


def sql_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def parse_id_list(raw: str) -> list[str]:
    return [item.strip().lower() for item in str(raw or "").split(",") if item.strip()]


def parse_scene_specs(raw: str) -> list[tuple[str, int]]:
    specs: list[tuple[str, int]] = []
    for item in parse_id_list(raw):
        if ":" in item:
            product_id, count = item.split(":", 1)
        else:
            product_id, count = item, "2"
        safe_count = max(1, min(8, int(count or "2")))
        specs.append((product_id.strip().lower(), safe_count))
    return specs


def parse_catalog() -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    products_source = CATALOG_PRODUCTS_PATH if CATALOG_PRODUCTS_PATH.exists() else CATALOG_PATH
    tile_data_source = CATALOG_TILE_DATA_PATH if CATALOG_TILE_DATA_PATH.exists() else CATALOG_PATH
    products_text = products_source.read_text(encoding="utf-8")
    tile_text = tile_data_source.read_text(encoding="utf-8")
    products_match = re.search(r"GENERATED_REGION_PACK_PRODUCTS = (\[.*?\]);", products_text, re.S)
    keys_match = re.search(r"GENERATED_REGION_PACK_TILE_KEYS = (\{.*?\});\n", tile_text, re.S)
    if not products_match or not keys_match:
        raise RuntimeError("generated region pack catalog could not be parsed")
    products = json.loads(products_match.group(1))
    keys_json = re.sub(r",\s*([}\]])", r"\1", keys_match.group(1))
    tile_keys = json.loads(keys_json)
    return products, tile_keys


def generated_catalog_version() -> str:
    products_source = CATALOG_PRODUCTS_PATH if CATALOG_PRODUCTS_PATH.exists() else CATALOG_PATH
    text = products_source.read_text(encoding="utf-8")
    match = re.search(r'GENERATED_REGION_PACK_CATALOG_VERSION = "([^"]+)"', text)
    return match.group(1) if match else "gadm_regions_v8"


def run_d1(sql: str, timeout: int = 180) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["npx", "wrangler", "d1", "execute", "planetka-auth", "--remote", "--command", sql],
        cwd=str(CLOUDFLARE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip())
    text = proc.stdout
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return []
    return json.loads(text[start:end + 1])


def first_results(sql: str) -> list[dict[str, Any]]:
    payload = run_d1(sql)
    if not payload:
        return []
    return list(payload[0].get("results") or [])


def queue_summary() -> dict[str, int]:
    rows = first_results("SELECT status, COUNT(*) AS count FROM user_product_quote_jobs GROUP BY status ORDER BY status")
    return {str(row.get("status") or ""): int(row.get("count") or 0) for row in rows}


def cleanup_e2e_state(user_id: str) -> None:
    run_d1(
        "DELETE FROM user_tile_entitlements WHERE user_id = " + sql_quote(user_id) + " AND source LIKE 'live_e2e_%';"
        "DELETE FROM purchase_history_tiles WHERE purchase_id IN ("
        "SELECT id FROM purchase_history WHERE user_id = " + sql_quote(user_id) + " AND id LIKE 'live_e2e_%'"
        ");"
        "DELETE FROM purchase_history WHERE user_id = " + sql_quote(user_id) + " AND id LIKE 'live_e2e_%';"
        "DELETE FROM user_product_quote_jobs WHERE user_id = " + sql_quote(user_id) + ";"
        "DELETE FROM user_product_quote_batches WHERE user_id = " + sql_quote(user_id) + ";"
        "DELETE FROM user_product_quotes WHERE user_id = " + sql_quote(user_id) + ";"
        "DELETE FROM region_pack_detail_tokens WHERE user_id = " + sql_quote(user_id) + " AND token LIKE 'probe_%';"
        "UPDATE user_credit_accounts "
        "SET pricing_version = COALESCE(pricing_version, 0) + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE user_id = " + sql_quote(user_id) + ";"
    )


def grant_entitlements(user_id: str, tile_keys: list[str], source: str) -> int:
    safe_keys: list[str] = []
    seen: set[str] = set()
    for key in tile_keys:
        safe = str(key or "").strip()
        if safe and safe not in seen:
            seen.add(safe)
            safe_keys.append(safe)
    if not safe_keys:
        return 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    inserted = 0
    for index in range(0, len(safe_keys), 80):
        chunk = safe_keys[index:index + 80]
        values = ",".join(
            "(" + ",".join([
                sql_quote(user_id),
                sql_quote(key),
                "'full'",
                "0",
                "0",
                "0",
                sql_quote(source),
                sql_quote(now),
            ]) + ")"
            for key in chunk
        )
        run_d1(
            "INSERT OR IGNORE INTO user_tile_entitlements "
            "(user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at) "
            "VALUES " + values
        )
        inserted += len(chunk)
    run_d1(
        "UPDATE user_credit_accounts "
        "SET pricing_version = COALESCE(pricing_version, 0) + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE user_id = " + sql_quote(user_id)
    )
    return inserted


def record_pack_purchase_history(
    user_id: str,
    user_email: str,
    product: dict[str, Any],
    summary: dict[str, Any],
    phase: str,
) -> str:
    product_id = str(product.get("id") or "").strip().lower()
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    purchase_id = f"live_e2e_{phase}_{product_id}_{int(time.time() * 1000)}"
    amount_eur = int(summary.get("price_cents") or money_cents(summary.get("price_eur"))) / 100.0
    full_eur = int(summary.get("full_price_cents") or money_cents(summary.get("full_price_eur"))) / 100.0
    discount_eur = int(summary.get("discount_cents") or money_cents(summary.get("discount_eur"))) / 100.0
    run_d1(
        "INSERT INTO purchase_history ("
        "id, user_id, user_email, purchase_type, stripe_session_id, stripe_payment_intent_id, "
        "currency, amount_paid_eur, nominal_eur, gross_eur, discount_eur, discount_percent, "
        "quality_mode, region_pack_id, region_pack_name, region_pack_type, catalog_version, "
        "tile_count_total, tile_count_new, tile_count_already_licenced, metadata_json, created_at"
        ") VALUES ("
        + ",".join([
            sql_quote(purchase_id),
            sql_quote(user_id),
            sql_quote(user_email),
            "'region_pack'",
            sql_quote(f"live_e2e_{purchase_id}"),
            "NULL",
            "'eur'",
            str(amount_eur),
            str(amount_eur),
            str(full_eur),
            str(discount_eur),
            str(max(0, int(summary.get("discount_percent") or 0))),
            "'full'",
            sql_quote(product_id),
            sql_quote(str(product.get("name") or product_id)),
            sql_quote(str(product.get("type") or "")),
            sql_quote(str(summary.get("catalog_version") or generated_catalog_version())),
            str(max(0, int(summary.get("total_tiles") or product.get("tile_count") or 0))),
            str(max(0, int(summary.get("new_tiles") or 0))),
            str(max(0, int(summary.get("already_licenced_tiles") or 0))),
            sql_quote(json.dumps({"source": "live_e2e", "phase": phase}, sort_keys=True)),
            sql_quote(created_at),
        ])
        + ")"
    )
    run_d1(
        "UPDATE user_credit_accounts "
        "SET pricing_version = COALESCE(pricing_version, 0) + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE user_id = " + sql_quote(user_id)
    )
    return purchase_id


def fetch_map_page_data(url: str, *, wait_for_map: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + max(1.0, QUOTE_WAIT_TIMEOUT_SEC)
    attempts = 0
    first_status = 0
    first_elapsed_ms = 0
    last_data: dict[str, Any] | None = None
    last_error = ""
    started = time.perf_counter()
    while True:
        attempts += 1
        timer = Timer()
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = int(response.status)
            if first_status == 0:
                first_status = status
                first_elapsed_ms = timer.ms()
            if status >= 500 or "1102" in raw:
                raise RuntimeError(f"server error while loading map page: status={status}")
            match = re.search(r"window\.PLANETKA_REGION_PACK_DATA=(\{.*?\});</script>", raw, re.S)
            if not match:
                raise RuntimeError("map page did not contain PLANETKA_REGION_PACK_DATA")
            data = json.loads(html.unescape(match.group(1)))
            last_data = data
            price_ready = not bool(data.get("price_pending")) and bool(data.get("quote"))
            map_ready = not wait_for_map or not bool(data.get("map_pending"))
            if price_ready and map_ready:
                return data, {
                    "attempts": attempts,
                    "ready_seconds": round(time.perf_counter() - started, 3),
                    "first_status": first_status,
                    "first_elapsed_ms": first_elapsed_ms,
                }
            last_error = f"pending price={data.get('price_pending')} map={data.get('map_pending')} quote_status={data.get('quote_status')} map_state_status={data.get('map_state_status')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if time.monotonic() >= deadline:
            if last_data is not None:
                return last_data, {
                    "attempts": attempts,
                    "ready_seconds": round(time.perf_counter() - started, 3),
                    "first_status": first_status,
                    "first_elapsed_ms": first_elapsed_ms,
                    "timeout": True,
                    "last_error": last_error,
                }
            raise RuntimeError(f"map page did not become ready: {last_error}")
        time.sleep(max(1.0, QUOTE_WAIT_POLL_SEC))


def fetch_checkout_redirect_cents(checkout_url: str) -> tuple[int | None, int, str]:
    parsed = urllib.parse.urlparse(checkout_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["method"] = "stripe"
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(url, timeout=45)
        body = response.read().decode("utf-8", errors="replace")
        return None, int(response.status), body[:500]
    except urllib.error.HTTPError as exc:
        if int(exc.code) == 303:
            cents = exc.headers.get("X-Planetka-Price-Cents")
            return int(cents) if cents is not None else None, int(exc.code), exc.headers.get("Location", "")
        body = exc.read().decode("utf-8", errors="replace")
        return None, int(exc.code), body[:500]


def selected_scene_keys(product_id: str, product_tile_keys: dict[str, list[str]], count: int) -> list[str]:
    keys = list(product_tile_keys.get(product_id, []))
    if not keys:
        return []
    d001 = [key for key in keys if "_d001" in key]
    source = d001 if len(d001) >= count else keys
    return sorted(source)[:count]


def verify_scene(stats: Stats, credit_api: Any, user_id: str, product_id: str, keys: list[str]) -> bool:
    if not keys:
        stats.fail("scene_setup", product_id, "scene target has no tile keys")
        return False
    timer = Timer()
    estimate = credit_api.estimate_credits_for_tiles(keys, quality_mode="FULL", pricing_context="scene")
    estimate_ms = timer.ms()
    expected_cents = money_cents(estimate.get("credits"))
    paid_count = int(estimate.get("paid_tile_count") or 0)
    stats.timing("scene_estimate", product_id, estimate_ms, price_cents=expected_cents, paid_tile_count=paid_count)
    if expected_cents <= 0 or paid_count <= 0:
        stats.skipped_already_owned += 1
        stats.scene_checks += 1
        return True
    try:
        timer = Timer()
        checkout = credit_api.create_checkout_session("scene", tiles=keys, quality_mode="FULL")
        checkout_ms = timer.ms()
        stats.checkout_sessions += 1
    except Exception as exc:  # noqa: BLE001
        stats.fail("scene_checkout", product_id, "checkout creation failed", error=str(exc), keys=keys)
        return False
    checkout_cents = money_cents(checkout.get("price_eur"))
    stats.timing("scene_checkout", product_id, checkout_ms, price_cents=checkout_cents)
    if checkout_cents != expected_cents:
        stats.fail("scene_checkout", product_id, "estimate and checkout amount differ", estimate_cents=expected_cents, checkout_cents=checkout_cents, estimate=estimate, checkout=checkout)
        return False
    inserted = grant_entitlements(user_id, keys, "live_e2e_scene_purchase")
    stats.direct_granted_tiles += inserted
    credit_api.clear_credit_caches()
    timer = Timer()
    post = credit_api.estimate_credits_for_tiles(keys, quality_mode="FULL", pricing_context="scene")
    post_ms = timer.ms()
    post_cents = money_cents(post.get("credits"))
    post_paid = int(post.get("paid_tile_count") or 0)
    stats.timing("scene_post_estimate", product_id, post_ms, price_cents=post_cents, paid_tile_count=post_paid)
    if post_cents != 0 or post_paid != 0:
        stats.fail("scene_post_purchase", product_id, "scene did not reprice to zero after entitlement grant", post_cents=post_cents, post_paid_tile_count=post_paid, post=post)
        return False
    stats.scene_checks += 1
    stats.paid_scene_checks += 1
    if PACE_SEC > 0:
        time.sleep(PACE_SEC)
    return True


def verify_pack(stats: Stats, credit_api: Any, user_id: str, user_email: str, product: dict[str, Any], product_keys: list[str], phase: str) -> bool:
    product_id = str(product.get("id") or "").strip().lower()
    if not product_id or not product_keys:
        stats.fail(f"{phase}_setup", product_id, "pack target is invalid")
        return False
    try:
        timer = Timer()
        detail = credit_api.create_region_pack_detail_link(product_id)
        detail_ms = timer.ms()
        data, ready = fetch_map_page_data(detail["detail_url"], wait_for_map=True)
        summary = {**(data.get("summary") or {}), "catalog_version": data.get("catalog_version") or generated_catalog_version()}
        quote_id = str(((data.get("quote") or {}).get("quote_id")) or "")
        map_cents = int(summary.get("price_cents") or money_cents(summary.get("price_eur")))
        stats.timing(f"{phase}_map_ready", product_id, int(ready["ready_seconds"] * 1000), price_cents=map_cents, attempts=ready.get("attempts"), first_elapsed_ms=ready.get("first_elapsed_ms"), detail_link_ms=detail_ms)
    except Exception as exc:  # noqa: BLE001
        stats.fail(f"{phase}_map", product_id, "map page quote/map failed", error=str(exc))
        return False
    if map_cents <= 0:
        stats.skipped_already_owned += 1
        if phase == "country":
            stats.country_checks += 1
        else:
            stats.region_checks += 1
        return True
    try:
        timer = Timer()
        checkout = credit_api.create_checkout_session("region_pack", region_pack_id=product_id, quote_id=quote_id)
        checkout_create_ms = timer.ms()
        stats.checkout_sessions += 1
        timer = Timer()
        checkout_cents, status, payload = fetch_checkout_redirect_cents(checkout["checkout_url"])
        redirect_ms = timer.ms()
    except Exception as exc:  # noqa: BLE001
        stats.fail(f"{phase}_checkout", product_id, "checkout preflight failed", error=str(exc), quote_id=quote_id)
        return False
    stats.timing(f"{phase}_checkout", product_id, checkout_create_ms + redirect_ms, price_cents=checkout_cents or 0, status=status)
    if status != 303 or checkout_cents is None:
        stats.fail(f"{phase}_checkout", product_id, "checkout did not redirect to Stripe for non-zero pack", status=status, map_cents=map_cents, payload=payload)
        return False
    stats.checkout_redirects += 1
    if checkout_cents != map_cents:
        stats.fail(f"{phase}_checkout", product_id, "map page and checkout amount differ", map_cents=map_cents, checkout_cents=checkout_cents, summary=summary)
        return False
    inserted = grant_entitlements(user_id, product_keys, f"live_e2e_{phase}_purchase")
    record_pack_purchase_history(user_id, user_email, product, summary, phase)
    stats.direct_granted_tiles += inserted
    stats.synthetic_pack_purchases += 1
    credit_api.clear_credit_caches()
    try:
        post_detail = credit_api.create_region_pack_detail_link(product_id)
        post_data, post_ready = fetch_map_page_data(post_detail["detail_url"], wait_for_map=True)
        post_summary = post_data.get("summary") or {}
    except Exception as exc:  # noqa: BLE001
        stats.fail(f"{phase}_post_map", product_id, "post-purchase map failed", error=str(exc))
        return False
    post_cents = int(post_summary.get("price_cents") or money_cents(post_summary.get("price_eur")))
    post_new = int(post_summary.get("new_tiles") or 0)
    post_total = int(post_summary.get("total_tiles") or 0)
    stats.timing(f"{phase}_post_map_ready", product_id, int(post_ready["ready_seconds"] * 1000), price_cents=post_cents, new_tiles=post_new, total_tiles=post_total, attempts=post_ready.get("attempts"))
    if post_cents != 0 or post_new != 0:
        stats.fail(f"{phase}_post_purchase", product_id, "pack did not reprice to zero/new=0 after entitlement grant", post_cents=post_cents, post_new_tiles=post_new, post_total_tiles=post_total, post_summary=post_summary)
        return False
    if phase == "country":
        stats.country_checks += 1
    else:
        stats.region_checks += 1
    stats.paid_pack_checks += 1
    if PACE_SEC > 0:
        time.sleep(PACE_SEC)
    return True


def validate_regular_workload(scene_specs: list[tuple[str, int]], pack_ids: list[str], by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    scene_sample_count = sum(count for _, count in scene_specs)
    if ALLOW_LIVE_STRESS:
        return None
    if scene_sample_count > REGULAR_MAX_SCENE_SAMPLES or len(pack_ids) > REGULAR_MAX_PACK_TARGETS:
        return {
            "ok": False,
            "error": "live_stress_not_allowed",
            "message": "Requested live pricing gate workload is above the regular safe limit. Set PLANETKA_ALLOW_LIVE_STRESS=1 only during maintenance.",
            "scene_sample_count": scene_sample_count,
            "pack_target_count": len(pack_ids),
        }
    for product_id in pack_ids:
        product = by_id.get(product_id)
        tile_count = int(product and product.get("tile_count") or 0)
        if tile_count > REGULAR_MAX_PRODUCT_TILES:
            return {
                "ok": False,
                "error": "live_stress_not_allowed",
                "message": "Pack target is too large for the regular gate. Use the quote queue probe or a maintenance stress run.",
                "product_id": product_id,
                "tile_count": tile_count,
            }
    return None


def report_and_return(report: dict[str, Any]) -> int:
    print("PLANETKA_LIVE_PRICING_E2E_RESULT " + json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


def main() -> int:
    scene_specs = parse_scene_specs(SCENE_TARGET_SPECS)
    country_ids = parse_id_list(COUNTRY_TARGET_IDS)
    region_ids = parse_id_list(REGION_TARGET_IDS)
    products, product_tile_keys = parse_catalog()
    by_id = {str(product.get("id") or "").strip().lower(): product for product in products}
    workload_error = validate_regular_workload(scene_specs, country_ids + region_ids, by_id)
    if workload_error:
        return report_and_return(workload_error)

    import addon_utils  # noqa: PLC0415
    addon_utils.enable("bl_ext.user_default.Planetka", default_set=False)
    from bl_ext.user_default.Planetka import auth, credit_api  # noqa: PLC0415

    prefs = auth.get_prefs()
    email = auth.get_connected_email(prefs).strip().lower()
    if email != TARGET_EMAIL:
        return report_and_return({"ok": False, "error": "wrong_authenticated_account", "expected": TARGET_EMAIL, "actual": email})
    account = credit_api.get_credit_account(force=True)
    user_id = str(account.get("user_id") or "").strip()
    if not user_id:
        return report_and_return({"ok": False, "error": "missing_user_id", "account": account})

    stats = Stats()
    cleanup_error = ""
    if RESET_BEFORE:
        cleanup_e2e_state(user_id)
        credit_api.clear_credit_caches()

    try:
        for product_id, count in scene_specs:
            if product_id not in by_id:
                stats.fail("scene_setup", product_id, "unknown scene product target")
                continue
            keys = selected_scene_keys(product_id, product_tile_keys, count)
            verify_scene(stats, credit_api, user_id, product_id, keys)

        for product_id in country_ids:
            product = by_id.get(product_id)
            if not product:
                stats.fail("country_setup", product_id, "unknown country product target")
                continue
            if str(product.get("type") or "") != "country":
                stats.fail("country_setup", product_id, "target is not a country", product_type=product.get("type"))
                continue
            verify_pack(stats, credit_api, user_id, email, product, product_tile_keys.get(product_id, []), "country")

        for product_id in region_ids:
            product = by_id.get(product_id)
            if not product:
                stats.fail("region_setup", product_id, "unknown region product target")
                continue
            if str(product.get("type") or "") not in {"macro_region", "continent", "world"}:
                stats.fail("region_setup", product_id, "target is not a region", product_type=product.get("type"))
                continue
            verify_pack(stats, credit_api, user_id, email, product, product_tile_keys.get(product_id, []), "region")
    finally:
        if CLEANUP_AFTER:
            try:
                cleanup_e2e_state(user_id)
                credit_api.clear_credit_caches()
            except Exception as exc:  # noqa: BLE001
                cleanup_error = str(exc)

    paid_path_ok = stats.paid_scene_checks > 0 and stats.paid_pack_checks > 0
    if REQUIRE_PAID_PATH and not paid_path_ok:
        stats.fail(
            "coverage",
            "paid_path",
            "paid scene and paid pack paths were not both exercised; choose targets not already licenced by the test account",
            paid_scene_checks=stats.paid_scene_checks,
            paid_pack_checks=stats.paid_pack_checks,
        )

    report = {
        "ok": not stats.failures and not cleanup_error,
        "account": email,
        "user_id": user_id,
        "targets": {
            "scene_targets": scene_specs,
            "country_targets": country_ids,
            "region_targets": region_ids,
            "pace_sec": PACE_SEC,
            "quote_wait_timeout_sec": QUOTE_WAIT_TIMEOUT_SEC,
        },
        "passed": {
            "scene_checks": stats.scene_checks,
            "country_checks": stats.country_checks,
            "region_checks": stats.region_checks,
            "paid_scene_checks": stats.paid_scene_checks,
            "paid_pack_checks": stats.paid_pack_checks,
            "checkout_sessions": stats.checkout_sessions,
            "checkout_redirects": stats.checkout_redirects,
            "direct_granted_tiles": stats.direct_granted_tiles,
            "synthetic_pack_purchases": stats.synthetic_pack_purchases,
            "skipped_already_owned": stats.skipped_already_owned,
        },
        "queue_after_test": queue_summary(),
        "cleanup_after": CLEANUP_AFTER,
        "cleanup_error": cleanup_error,
        "timings": stats.timings,
        "failures": [
            {"phase": failure.phase, "target": failure.target, "message": failure.message, "details": failure.details}
            for failure in stats.failures
        ],
        "failure_count": len(stats.failures),
    }
    return report_and_return(report)


if __name__ == "__main__":
    raise SystemExit(main())
