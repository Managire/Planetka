#!/usr/bin/env python3
"""
Live Planetka pricing consistency harness.

Run with Blender Python so the installed add-on authentication is reused:

  /Applications/Blender5.0.app/Contents/MacOS/Blender --background --python tools/live_pricing_consistency_e2e.py

This intentionally targets the live sandbox backend and the currently
authenticated add-on account. It validates that estimate, checkout, entitlement
state, and post-purchase estimates stay cent-exact.

Default counts are deliberately bounded for regular release health checks:
10 scene quotes/purchases, 5 country packs, and 2 regions. Larger stress runs
must set PLANETKA_ALLOW_LIVE_STRESS=1 because they can push production Workers
into Cloudflare 1102/503 and temporarily affect real users.
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import addon_utils


ROOT = pathlib.Path(
    "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka"
)
CLOUDFLARE_DIR = ROOT / "cloudflare-api"
CATALOG_PATH = ROOT / "cloudflare-api/src/worker/region_packs.generated.js"
CATALOG_PRODUCTS_PATH = ROOT / "cloudflare-api/src/worker/region_packs.products.generated.js"
CATALOG_TILE_DATA_PATH = ROOT / "cloudflare-api/src/worker/region_packs.tile_data.generated.js"
API_BASE = "https://api.planetka.io"
TARGET_EMAIL = "tom.griger@gmail.com"
RANDOM_SEED = 20260513
BOUNDED_SCENE_TESTS = 10
BOUNDED_COUNTRY_TESTS = 5
BOUNDED_REGION_TESTS = 2
SCENE_TESTS = int(os.environ.get("PLANETKA_E2E_SCENE_TESTS", str(BOUNDED_SCENE_TESTS)) or str(BOUNDED_SCENE_TESTS))
COUNTRY_TESTS = int(os.environ.get("PLANETKA_E2E_COUNTRY_TESTS", str(BOUNDED_COUNTRY_TESTS)) or str(BOUNDED_COUNTRY_TESTS))
REGION_TESTS = int(os.environ.get("PLANETKA_E2E_REGION_TESTS", str(BOUNDED_REGION_TESTS)) or str(BOUNDED_REGION_TESTS))
RESET_E2E_ENTITLEMENTS = str(os.environ.get("PLANETKA_E2E_RESET_ENTITLEMENTS") or "1").strip().lower() not in {"0", "false", "no", "off"}
PACE_SEC = float(os.environ.get("PLANETKA_E2E_PACE_SEC", "3.0") or "3.0")
MAX_COUNTRY_TILES = int(os.environ.get("PLANETKA_E2E_MAX_COUNTRY_TILES", "1200") or "1200")
MAX_REGION_TILES = int(os.environ.get("PLANETKA_E2E_MAX_REGION_TILES", "1500") or "1500")
QUOTE_WAIT_TIMEOUT_SEC = float(os.environ.get("PLANETKA_E2E_QUOTE_WAIT_TIMEOUT_SEC", "240") or "240")
QUOTE_WAIT_POLL_SEC = float(os.environ.get("PLANETKA_E2E_QUOTE_WAIT_POLL_SEC", "6") or "6")


def stress_explicitly_allowed() -> bool:
    return str(os.environ.get("PLANETKA_ALLOW_LIVE_STRESS") or "").strip().lower() in {"1", "true", "yes", "on"}


def requested_live_workload_is_bounded() -> bool:
    return (
        SCENE_TESTS <= BOUNDED_SCENE_TESTS
        and COUNTRY_TESTS <= BOUNDED_COUNTRY_TESTS
        and REGION_TESTS <= BOUNDED_REGION_TESTS
        and PACE_SEC >= 1.0
        and MAX_COUNTRY_TILES <= 1200
        and MAX_REGION_TILES <= 1500
    )


@dataclass
class Failure:
    phase: str
    target: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stats:
    scenes: int = 0
    countries: int = 0
    regions: int = 0
    checkout_sessions: int = 0
    checkout_redirects: int = 0
    direct_granted_tiles: int = 0
    skipped_already_owned: int = 0
    failures: list[Failure] = field(default_factory=list)

    def fail(self, phase: str, target: str, message: str, **details: Any) -> None:
        self.failures.append(Failure(phase=phase, target=target, message=message, details=details))


def money_cents(value: Any) -> int:
    try:
        return int(round(float(value or 0) * 100))
    except (TypeError, ValueError):
        return 0


def sql_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def parse_catalog() -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    products_source = CATALOG_PRODUCTS_PATH if CATALOG_PRODUCTS_PATH.exists() else CATALOG_PATH
    tile_data_source = CATALOG_TILE_DATA_PATH if CATALOG_TILE_DATA_PATH.exists() else CATALOG_PATH
    products_text = products_source.read_text(encoding="utf-8")
    tile_text = tile_data_source.read_text(encoding="utf-8")
    products_match = re.search(
        r"GENERATED_REGION_PACK_PRODUCTS = (\[.*?\]);",
        products_text,
        re.S,
    )
    keys_match = re.search(r"GENERATED_REGION_PACK_TILE_KEYS = (\{.*?\});\n", tile_text, re.S)
    if not products_match or not keys_match:
        raise RuntimeError("generated region pack catalog could not be parsed")
    products = json.loads(products_match.group(1))
    keys_json = re.sub(r",\s*([}\]])", r"\1", keys_match.group(1))
    tile_keys = json.loads(keys_json)
    return products, tile_keys


def run_d1(sql: str) -> str:
    proc = subprocess.run(
        ["npx", "wrangler", "d1", "execute", "planetka-auth", "--remote", "--command", sql],
        cwd=str(CLOUDFLARE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip())
    return proc.stdout


def grant_entitlements(user_id: str, tile_keys: list[str], source: str) -> int:
    safe_keys = []
    seen = set()
    for key in tile_keys:
        key = str(key or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        safe_keys.append(key)
    if not safe_keys:
        return 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    inserted = 0
    for index in range(0, len(safe_keys), 80):
        chunk = safe_keys[index:index + 80]
        values = ",".join(
            "("
            + ",".join(
                [
                    sql_quote(user_id),
                    sql_quote(key),
                    "'full'",
                    "0",
                    "0",
                    "0",
                    sql_quote(source),
                    sql_quote(now),
                ]
            )
            + ")"
            for key in chunk
        )
        run_d1(
            """
            INSERT OR IGNORE INTO user_tile_entitlements (
              user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at
            )
            VALUES
            """
            + values
        )
        inserted += len(chunk)
    run_d1(
        """
        UPDATE user_credit_accounts
        SET pricing_version = COALESCE(pricing_version, 0) + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE user_id =
        """
        + sql_quote(user_id)
    )
    return inserted


def reset_e2e_entitlements(user_id: str) -> None:
    """Remove only entitlements created by this live E2E harness.

    Keeping old synthetic purchases makes later runs spend hundreds of attempts
    looking for unowned tiles and can itself overload the live Worker. This does
    not touch manual sandbox purchases or non-E2E account state.
    """

    run_d1(
        """
        DELETE FROM user_tile_entitlements
        WHERE user_id =
        """
        + sql_quote(user_id)
        + " AND source LIKE 'live_e2e_%'"
    )
    run_d1(
        """
        UPDATE user_credit_accounts
        SET pricing_version = COALESCE(pricing_version, 0) + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE user_id =
        """
        + sql_quote(user_id)
    )


def fetch_json_from_map_page(url: str, *, wait_for_price: bool = True) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, QUOTE_WAIT_TIMEOUT_SEC)
    last_data: dict[str, Any] | None = None
    last_error: str = ""
    while True:
        try:
            raw = urllib.request.urlopen(url, timeout=45).read().decode("utf-8", errors="replace")
            match = re.search(r"window\.PLANETKA_REGION_PACK_DATA=(\{.*?\});</script>", raw, re.S)
            if not match:
                raise RuntimeError("map page did not contain PLANETKA_REGION_PACK_DATA")
            data = json.loads(html.unescape(match.group(1)))
            last_data = data
            if not wait_for_price:
                return data
            if not bool(data.get("price_pending")) and data.get("quote"):
                return data
            last_error = f"quote pending, status={data.get('quote_status')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if time.monotonic() >= deadline:
            if last_data is not None:
                return last_data
            raise RuntimeError(f"map page quote did not become ready: {last_error}")
        time.sleep(max(1.0, QUOTE_WAIT_POLL_SEC))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


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


def verify_scene_purchase(stats: Stats, credit_api: Any, user_id: str, target: str, keys: list[str]) -> bool:
    estimate = credit_api.estimate_credits_for_tiles(keys, quality_mode="FULL", pricing_context="scene")
    expected_cents = money_cents(estimate.get("credits"))
    paid_count = int(estimate.get("paid_tile_count") or 0)
    if expected_cents <= 0 or paid_count <= 0:
        stats.skipped_already_owned += 1
        return False
    try:
        checkout = credit_api.create_checkout_session("scene", tiles=keys, quality_mode="FULL")
        stats.checkout_sessions += 1
    except Exception as exc:  # noqa: BLE001
        stats.fail("scene_checkout", target, "checkout creation failed", error=str(exc), keys=keys)
        return False
    checkout_cents = money_cents(checkout.get("price_eur"))
    if checkout_cents != expected_cents:
        stats.fail(
            "scene_checkout",
            target,
            "estimate and checkout amount differ",
            estimate_cents=expected_cents,
            checkout_cents=checkout_cents,
            keys=keys,
            estimate=estimate,
            checkout=checkout,
        )
        return False
    inserted = grant_entitlements(user_id, keys, "live_e2e_scene_purchase")
    stats.direct_granted_tiles += inserted
    credit_api.clear_credit_caches()
    post = credit_api.estimate_credits_for_tiles(keys, quality_mode="FULL", pricing_context="scene")
    post_cents = money_cents(post.get("credits"))
    post_paid = int(post.get("paid_tile_count") or 0)
    if post_cents != 0 or post_paid != 0:
        stats.fail(
            "scene_post_purchase",
            target,
            "scene did not reprice to zero after entitlement grant",
            post_cents=post_cents,
            post_paid_tile_count=post_paid,
            keys=keys,
            post=post,
        )
        return False
    try:
        post_checkout = credit_api.create_checkout_session("scene", tiles=keys, quality_mode="FULL")
        stats.checkout_sessions += 1
    except Exception as exc:  # noqa: BLE001
        stats.fail("scene_post_checkout", target, "post-purchase checkout failed", error=str(exc), keys=keys)
        return False
    if money_cents(post_checkout.get("price_eur")) != 0:
        stats.fail(
            "scene_post_checkout",
            target,
            "post-purchase checkout did not return zero",
            post_checkout=post_checkout,
            keys=keys,
        )
        return False
    stats.scenes += 1
    return True


def verify_pack_purchase(
    stats: Stats,
    credit_api: Any,
    user_id: str,
    product: dict[str, Any],
    product_keys: list[str],
    phase: str,
) -> bool:
    product_id = str(product.get("id") or "")
    try:
        detail = credit_api.create_region_pack_detail_link(product_id)
        data = fetch_json_from_map_page(detail["detail_url"])
        summary = data.get("summary") or {}
        quote_id = str(((data.get("quote") or {}).get("quote_id")) or "")
        checkout = credit_api.create_checkout_session("region_pack", region_pack_id=product_id, quote_id=quote_id)
        stats.checkout_sessions += 1
        checkout_cents, status, payload = fetch_checkout_redirect_cents(checkout["checkout_url"])
    except Exception as exc:  # noqa: BLE001
        stats.fail(f"{phase}_preflight", product_id, "pack preflight failed", error=str(exc))
        return False
    map_cents = int(summary.get("price_cents") or money_cents(summary.get("price_eur")))
    if map_cents <= 0:
        stats.skipped_already_owned += 1
        return False
    if status != 303 or checkout_cents is None:
        stats.fail(
            f"{phase}_checkout",
            product_id,
            "checkout did not redirect to Stripe for non-zero pack",
            status=status,
            map_cents=map_cents,
            payload=payload,
        )
        return False
    stats.checkout_redirects += 1
    if checkout_cents != map_cents:
        stats.fail(
            f"{phase}_checkout",
            product_id,
            "map page and checkout amount differ",
            map_cents=map_cents,
            checkout_cents=checkout_cents,
            summary=summary,
        )
        return False
    inserted = grant_entitlements(user_id, product_keys, f"live_e2e_{phase}_purchase")
    stats.direct_granted_tiles += inserted
    credit_api.clear_credit_caches()
    try:
        post_detail = credit_api.create_region_pack_detail_link(product_id)
        post_data = fetch_json_from_map_page(post_detail["detail_url"])
    except Exception as exc:  # noqa: BLE001
        stats.fail(f"{phase}_post_map", product_id, "post-purchase map failed", error=str(exc))
        return False
    post_summary = post_data.get("summary") or {}
    post_cents = int(post_summary.get("price_cents") or money_cents(post_summary.get("price_eur")))
    post_new = int(post_summary.get("new_tiles") or 0)
    post_total = int(post_summary.get("total_tiles") or 0)
    if post_cents != 0 or post_new != 0:
        stats.fail(
            f"{phase}_post_purchase",
            product_id,
            "pack did not reprice to zero/new=0 after entitlement grant",
            post_cents=post_cents,
            post_new_tiles=post_new,
            post_total_tiles=post_total,
            post_summary=post_summary,
        )
        return False
    if phase == "country":
        stats.countries += 1
    else:
        stats.regions += 1
    return True


def main() -> int:
    if not requested_live_workload_is_bounded() and not stress_explicitly_allowed():
        report = {
            "ok": False,
            "error": "live_stress_not_allowed",
            "message": (
                "Requested live workload exceeds the regular bounded health gate. "
                "Set PLANETKA_ALLOW_LIVE_STRESS=1 only during a controlled maintenance window."
            ),
            "targets": {
                "scenes": SCENE_TESTS,
                "countries": COUNTRY_TESTS,
                "regions": REGION_TESTS,
                "pace_sec": PACE_SEC,
                "max_country_tiles": MAX_COUNTRY_TILES,
                "max_region_tiles": MAX_REGION_TILES,
            },
        }
        print("PLANETKA_LIVE_PRICING_E2E_RESULT " + json.dumps(report, sort_keys=True))
        return 2

    addon_utils.enable("bl_ext.user_default.Planetka", default_set=False)
    from bl_ext.user_default.Planetka import auth, credit_api  # noqa: PLC0415

    prefs = auth.get_prefs()
    email = auth.get_connected_email(prefs)
    if email.strip().lower() != TARGET_EMAIL:
        print(json.dumps({"ok": False, "error": "wrong_authenticated_account", "email": email}))
        return 2
    account = credit_api.get_credit_account(force=True)
    user_id = str(account.get("user_id") or "").strip()
    if not user_id:
        print(json.dumps({"ok": False, "error": "missing_user_id", "account": account}))
        return 2
    if RESET_E2E_ENTITLEMENTS:
        reset_e2e_entitlements(user_id)
        credit_api.clear_credit_caches()

    products, product_tile_keys = parse_catalog()
    by_id = {str(p.get("id") or ""): p for p in products}
    rng = random.Random(RANDOM_SEED)
    stats = Stats()

    scene_products = [
        p for p in products
        if p.get("id") in product_tile_keys
        and p.get("id") != "world"
        and int(p.get("paid_tile_count") or 0) > 0
        and int(p.get("tile_count") or 0) >= 5
    ]
    attempts = 0
    while stats.scenes < SCENE_TESTS and attempts < SCENE_TESTS * 40:
        attempts += 1
        product = rng.choice(scene_products)
        keys = [k for k in product_tile_keys.get(str(product.get("id")), []) if "_d001" in k]
        if len(keys) < 2:
            keys = product_tile_keys.get(str(product.get("id")), [])
        if not keys:
            continue
        rng.shuffle(keys)
        sample = keys[: rng.randint(1, min(5, len(keys)))]
        verify_scene_purchase(stats, credit_api, user_id, str(product.get("id")), sample)
        if PACE_SEC > 0:
            time.sleep(PACE_SEC)
        if stats.scenes and stats.scenes % 10 == 0:
            print(json.dumps({"progress": "scenes", "passed": stats.scenes, "failures": len(stats.failures)}), flush=True)

    countries = [
        p for p in products
        if p.get("id") in product_tile_keys
        and str(p.get("type") or "") == "country"
        and not p.get("adm1_codes")
        and int(p.get("paid_tile_count") or 0) > 0
        and int(p.get("tile_count") or 0) <= MAX_COUNTRY_TILES
        and str(p.get("id") or "") not in {"world"}
    ]
    rng.shuffle(countries)
    for product in countries:
        if stats.countries >= COUNTRY_TESTS:
            break
        verify_pack_purchase(
            stats,
            credit_api,
            user_id,
            product,
            product_tile_keys.get(str(product.get("id")), []),
            "country",
        )
        if PACE_SEC > 0:
            time.sleep(PACE_SEC)
        if stats.countries and stats.countries % 10 == 0:
            print(json.dumps({"progress": "countries", "passed": stats.countries, "failures": len(stats.failures)}), flush=True)

    regions = [
        p for p in products
        if p.get("id") in product_tile_keys
        and str(p.get("type") or "") == "macro_region"
        and str(p.get("id") or "") != "world"
        and int(p.get("paid_tile_count") or 0) > 0
        and int(p.get("tile_count") or 0) <= MAX_REGION_TILES
    ]
    rng.shuffle(regions)
    for product in regions:
        if stats.regions >= REGION_TESTS:
            break
        verify_pack_purchase(
            stats,
            credit_api,
            user_id,
            product,
            product_tile_keys.get(str(product.get("id")), []),
            "region",
        )
        if PACE_SEC > 0:
            time.sleep(PACE_SEC)
        print(json.dumps({"progress": "regions", "passed": stats.regions, "failures": len(stats.failures)}), flush=True)

    report = {
        "ok": not stats.failures and stats.scenes >= SCENE_TESTS and stats.countries >= COUNTRY_TESTS and stats.regions >= REGION_TESTS,
        "account": email,
        "user_id": user_id,
        "targets": {
            "scenes": SCENE_TESTS,
            "countries": COUNTRY_TESTS,
            "regions": REGION_TESTS,
            "pace_sec": PACE_SEC,
            "max_country_tiles": MAX_COUNTRY_TILES,
            "max_region_tiles": MAX_REGION_TILES,
        },
        "passed": {
            "scenes": stats.scenes,
            "countries": stats.countries,
            "regions": stats.regions,
            "checkout_sessions": stats.checkout_sessions,
            "checkout_redirects": stats.checkout_redirects,
            "direct_granted_tiles": stats.direct_granted_tiles,
            "skipped_already_owned": stats.skipped_already_owned,
        },
        "failures": [
            {
                "phase": failure.phase,
                "target": failure.target,
                "message": failure.message,
                "details": failure.details,
            }
            for failure in stats.failures[:50]
        ],
        "failure_count": len(stats.failures),
    }
    print("PLANETKA_LIVE_PRICING_E2E_RESULT " + json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
