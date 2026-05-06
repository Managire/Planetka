#!/usr/bin/env python3
"""Live EUR pricing E2E gate for Planetka Worker/D1.

This test intentionally uses the live API and remote D1 database. It mutates
only the dedicated EUR-pricing test account and restores that account to a
clean standard €100 balance state at the end.

Run from the add-on root:
  python3 tools/planetka_land_credit_live_e2e.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE_URL = os.getenv("PLANETKA_API_BASE_URL", "https://api.planetka.io").rstrip("/")
DEFAULT_KEY_JSON = Path("/Volumes/SSDA/Renders/credits_planetka_io_api_key.json")
TEST_EMAIL = "credits@planetka.io"
STANDARD_BALANCE = 100.0

ANIMATION_SECOND_TILE = "x339_y143_z001_d002"
FULL_TILE = "x075_y149_z001_d001"
UPGRADE_FINE_TILE = "x074_y149_z001_d001"
UPGRADE_COARSE_TILE = "x074_y149_z001_d002"
UPGRADE_FREE_TILE = "x074_y149_z001_d004"
INSUFFICIENT_TILE = "x121_y051_z001_d001"
FREE_TILE = "x000_y000_z360_d000"
PREVIEW_TILE = FREE_TILE


class E2EFailure(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[Planetka EUR Pricing E2E] {message}", flush=True)


def assert_true(condition, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


def assert_close(actual, expected, message: str, tolerance: float = 1e-6) -> None:
    if abs(float(actual) - float(expected)) > float(tolerance):
        raise E2EFailure(f"{message}: actual={actual} expected={expected}")


def load_key_payload(path: Path) -> dict:
    if not path.is_file():
        raise E2EFailure(f"Missing test API key JSON: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    api_key = str(payload.get("api_key", "") or "").strip()
    device_id = str(payload.get("device_id", "") or "").strip()
    email = str(payload.get("email", "") or "").strip().lower()
    assert_true(api_key, "Test API key JSON does not contain api_key")
    assert_true(device_id, "Test API key JSON does not contain device_id")
    assert_true(email == TEST_EMAIL, f"Unexpected test key email: {email}")
    return payload


def request_json(method: str, url: str, headers=None, body=None, expected_status=200, timeout=30) -> dict:
    payload = None
    safe_headers = dict(headers or {})
    if body is not None:
        payload = json.dumps(body, ensure_ascii=True).encode("utf-8")
        safe_headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, method=method.upper(), headers=safe_headers, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read() or b"{}"
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        status = int(exc.code)
    text = raw.decode("utf-8", errors="replace")
    try:
        decoded = json.loads(text or "{}")
    except json.JSONDecodeError:
        decoded = {"raw": text}
    if status != int(expected_status):
        raise E2EFailure(f"{method} {url} returned HTTP {status}, expected {expected_status}: {decoded}")
    return decoded


def request_head(url: str, headers=None, expected_status=200, timeout=30) -> int:
    req = urllib.request.Request(url, method="HEAD", headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    if status != int(expected_status):
        raise E2EFailure(f"HEAD {url} returned HTTP {status}, expected {expected_status}")
    return status


def exchange_api_key(api_base_url: str, key_payload: dict) -> dict:
    return request_json(
        "POST",
        f"{api_base_url}/auth/api-key/exchange",
        body={
            "api_key": str(key_payload["api_key"]),
            "device_id": str(key_payload["device_id"]),
            "device_name": "Planetka EUR Pricing E2E",
        },
        expected_status=200,
    )


def auth_headers(auth_payload: dict, key_payload: dict) -> dict:
    token = str(auth_payload.get("access_token", "") or "").strip()
    assert_true(token, "Auth exchange did not return access_token")
    return {
        "Authorization": f"Bearer {token}",
        "X-Planetka-Device-Id": str(key_payload["device_id"]),
        "X-Planetka-Addon-Version": "land-credit-e2e",
        "User-Agent": "Planetka-Land-Credit-E2E",
    }


def wrangler_d1(command: str, cwd: Path) -> list[dict]:
    proc = subprocess.run(
        ["npx", "wrangler", "d1", "execute", "planetka-auth", "--remote", "--command", command],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise E2EFailure(f"wrangler d1 execute failed ({proc.returncode}):\n{proc.stdout}")
    output = proc.stdout.strip()
    start = output.find("[")
    end = output.rfind("]")
    if start < 0 or end < start:
        raise E2EFailure(f"Unable to parse wrangler JSON output:\n{output}")
    return json.loads(output[start : end + 1])


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def reset_test_account(cwd: Path, account_type="standard", balance=STANDARD_BALANCE) -> None:
    email_sql = sql_literal(TEST_EMAIL)
    account_type_sql = sql_literal(account_type)
    now_sql = sql_literal(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    command = f"""
      DELETE FROM user_tile_entitlements
      WHERE user_id = (SELECT id FROM users WHERE LOWER(email) = {email_sql});
      DELETE FROM credit_ledger
      WHERE user_id = (SELECT id FROM users WHERE LOWER(email) = {email_sql})
        AND reason = 'tile_unlock';
      UPDATE user_credit_accounts
      SET account_type = {account_type_sql},
          balance_credits = {float(balance):.6f},
          total_granted_credits = {float(balance):.6f},
          total_spent_credits = 0,
          updated_at = {now_sql}
      WHERE user_id = (SELECT id FROM users WHERE LOWER(email) = {email_sql});
    """
    wrangler_d1(command, cwd)


def account_row(cwd: Path) -> dict:
    rows = wrangler_d1(
        f"""
        SELECT u.id, u.email, c.account_type, c.balance_credits, c.total_spent_credits,
          (SELECT COUNT(*) FROM user_tile_entitlements e WHERE e.user_id = u.id) AS unlocked
        FROM users u
        JOIN user_credit_accounts c ON c.user_id = u.id
        WHERE LOWER(u.email) = {sql_literal(TEST_EMAIL)}
        LIMIT 1;
        """,
        cwd,
    )
    results = rows[0].get("results", []) if rows else []
    assert_true(results, "Test account not found in D1")
    return dict(results[0])


def tile_stat_rows(cwd: Path, tile_keys: list[str]) -> dict:
    key_list = ", ".join(sql_literal(key) for key in tile_keys)
    rows = wrangler_d1(
        f"""
        SELECT tile_key, billable_land_km2, free_reason
        FROM tile_land_stats
        WHERE tile_key IN ({key_list});
        """,
        cwd,
    )
    results = rows[0].get("results", []) if rows else []
    return {str(row["tile_key"]): row for row in results}


def get_me(api_base_url: str, headers: dict) -> dict:
    return request_json("GET", f"{api_base_url}/credits/me", headers=headers, expected_status=200)


def unlocked_tiles(api_base_url: str, headers: dict) -> list[dict]:
    payload = request_json("GET", f"{api_base_url}/credits/unlocked", headers=headers, expected_status=200)
    tiles = payload.get("tiles", [])
    assert_true(isinstance(tiles, list), "credits/unlocked did not return tile list")
    return tiles


def estimate(api_base_url: str, headers: dict, quality: str, tile_keys: list[str]) -> dict:
    return request_json(
        "POST",
        f"{api_base_url}/credits/estimate",
        headers=headers,
        body={"quality_mode": quality, "tile_keys": list(tile_keys)},
        expected_status=200,
    )


def session(api_base_url: str, headers: dict, quality: str, tile_keys: list[str], expected_status=200) -> dict:
    return request_json(
        "POST",
        f"{api_base_url}/tiles/session",
        headers=headers,
        body={
            "resolve_id": f"land-credit-e2e-{uuid.uuid4().hex}",
            "quality_mode": quality,
            "credit_protocol": "land_credits_v1",
            "tile_keys": list(tile_keys),
        },
        expected_status=expected_status,
    )


def head_s2(
    api_base_url: str,
    headers: dict,
    quality: str,
    tile_key: str,
    tile_token: str,
    resolve_id: str,
    expected_status=200,
) -> None:
    request_head(
        f"{api_base_url}/tiles/S2/S2_{tile_key}.exr",
        headers={
            **headers,
            "X-Planetka-Tile-Token": str(tile_token or ""),
            "X-Planetka-Quality-Mode": str(quality or "").lower(),
            "X-Planetka-Resolve-Id": str(resolve_id or ""),
        },
        expected_status=expected_status,
    )


def assert_balance(api_base_url: str, headers: dict, expected: float, context: str) -> None:
    payload = get_me(api_base_url, headers)
    assert_close(payload.get("balance_credits", 0), expected, f"Balance mismatch after {context}")


def run(api_base_url: str, key_json: Path, wrangler_cwd: Path) -> dict:
    report = {"cases": []}
    key_payload = load_key_payload(key_json)

    reset_test_account(wrangler_cwd, "standard", STANDARD_BALANCE)
    auth_payload = exchange_api_key(api_base_url, key_payload)
    headers = auth_headers(auth_payload, key_payload)

    stats = tile_stat_rows(
        wrangler_cwd,
        [
            ANIMATION_SECOND_TILE,
            FULL_TILE,
            UPGRADE_FINE_TILE,
            UPGRADE_COARSE_TILE,
            UPGRADE_FREE_TILE,
            INSUFFICIENT_TILE,
            PREVIEW_TILE,
            FREE_TILE,
        ],
    )
    for tile_key in [
        ANIMATION_SECOND_TILE,
        FULL_TILE,
        UPGRADE_FINE_TILE,
        UPGRADE_COARSE_TILE,
        UPGRADE_FREE_TILE,
        INSUFFICIENT_TILE,
        PREVIEW_TILE,
        FREE_TILE,
    ]:
        assert_true(tile_key in stats, f"Missing D1 tile_land_stats row for {tile_key}")
    log("D1 pricing metadata present for selected test tiles.")

    me = get_me(api_base_url, headers)
    assert_true(me.get("account_type") == "standard", f"Expected standard account, got {me}")
    assert_true(not bool(me.get("unlimited_credits")), "Standard test account unexpectedly unlimited")
    assert_balance(api_base_url, headers, STANDARD_BALANCE, "reset")

    # 1. Preview Resolve: free, no entitlement or charge.
    preview_estimate = estimate(api_base_url, headers, "preview", [PREVIEW_TILE])
    assert_close(preview_estimate.get("credits", 0), 0, "Preview estimate should be free")
    preview_session = session(api_base_url, headers, "preview", [PREVIEW_TILE])
    assert_close(preview_session.get("credits_charged", 0), 0, "Preview session charged EUR")
    assert_true(str(preview_session.get("quality_mode")) == "preview", "Preview session quality mismatch")
    head_s2(
        api_base_url,
        headers,
        "preview",
        PREVIEW_TILE,
        preview_session.get("tile_token", ""),
        preview_session.get("resolve_id", ""),
    )
    assert_balance(api_base_url, headers, STANDARD_BALANCE, "preview resolve")
    assert_true(len(unlocked_tiles(api_base_url, headers)) == 0, "Preview resolve should not unlock paid tiles")
    report["cases"].append({"name": "preview_free", "ok": True})
    log("PASS preview resolve free/no charge.")
    balance_after_preview = STANDARD_BALANCE

    # 2. Same-family entitlement model:
    # A finer tile unlocks coarser d-levels. A coarser tile does not unlock a
    # finer tile, but its previous price is credited against the upgrade.
    coarse_estimate = estimate(api_base_url, headers, "full", [UPGRADE_COARSE_TILE])
    coarse_cost = float(coarse_estimate.get("credits", 0) or 0)
    fine_estimate_before = estimate(api_base_url, headers, "full", [UPGRADE_FINE_TILE])
    fine_gross_cost = float(fine_estimate_before.get("credits", 0) or 0)
    preview_detail_estimate = estimate(api_base_url, headers, "full", [UPGRADE_FREE_TILE])
    assert_true(coarse_cost > 0, f"Coarser upgrade tile should have a positive cost: {coarse_estimate}")
    assert_true(fine_gross_cost > coarse_cost, f"Fine tile should cost more than coarse tile: {fine_estimate_before}")
    assert_close(preview_detail_estimate.get("credits", 0), 0, "d/z >= 4 tile should be free")
    coarse_session = session(api_base_url, headers, "full", [UPGRADE_COARSE_TILE])
    assert_close(coarse_session.get("credits_charged", 0), coarse_cost, "Coarse session charge mismatch")
    balance_after_coarse = balance_after_preview - coarse_cost
    assert_balance(api_base_url, headers, balance_after_coarse, "coarse same-family unlock")

    upgrade_estimate = estimate(api_base_url, headers, "full", [UPGRADE_FINE_TILE])
    upgrade_cost = float(upgrade_estimate.get("credits", 0) or 0)
    assert_close(upgrade_cost, fine_gross_cost - coarse_cost, "Fine upgrade should charge only the difference")
    upgrade_session = session(api_base_url, headers, "full", [UPGRADE_FINE_TILE])
    assert_close(upgrade_session.get("credits_charged", 0), upgrade_cost, "Fine upgrade session charge mismatch")
    balance_after_upgrade = balance_after_coarse - upgrade_cost
    assert_balance(api_base_url, headers, balance_after_upgrade, "fine same-family upgrade")

    coarser_after_fine = session(api_base_url, headers, "full", [UPGRADE_COARSE_TILE])
    assert_close(coarser_after_fine.get("credits_charged", 0), 0, "Finer entitlement should cover coarser tile")
    head_s2(
        api_base_url,
        headers,
        "full",
        UPGRADE_COARSE_TILE,
        coarser_after_fine.get("tile_token", ""),
        coarser_after_fine.get("resolve_id", ""),
    )
    report["cases"].append({
        "name": "same_family_upgrade_difference",
        "ok": True,
        "coarse_credits": coarse_cost,
        "upgrade_credits": upgrade_cost,
    })
    log(
        "PASS same-family entitlement cascade and upgrade difference "
        f"(coarse={coarse_cost:.6f}, upgrade={upgrade_cost:.6f})."
    )

    # 3. Full Resolve: charge only new full tile.
    full_estimate = estimate(api_base_url, headers, "full", [FULL_TILE])
    full_cost = float(full_estimate.get("credits", 0) or 0)
    assert_true(full_cost > 0, f"Full estimate should be positive: {full_estimate}")
    full_session = session(api_base_url, headers, "full", [FULL_TILE])
    assert_close(full_session.get("credits_charged", 0), full_cost, "Full session charge mismatch")
    balance_after_full = balance_after_upgrade - full_cost
    assert_balance(api_base_url, headers, balance_after_full, "full resolve")
    head_s2(
        api_base_url,
        headers,
        "full",
        FULL_TILE,
        full_session.get("tile_token", ""),
        full_session.get("resolve_id", ""),
    )
    assert_true(any(t.get("tile_key") == FULL_TILE for t in unlocked_tiles(api_base_url, headers)), "Full tile not unlocked")
    repeat_full = session(api_base_url, headers, "full", [FULL_TILE])
    assert_close(repeat_full.get("credits_charged", 0), 0, "Repeat full session charged again")
    assert_balance(api_base_url, headers, balance_after_full, "repeat full resolve")
    repeat_estimate = estimate(api_base_url, headers, "full", [FULL_TILE])
    assert_close(repeat_estimate.get("credits", 0), 0, "Repeat full estimate should be zero")
    report["cases"].append({"name": "full_new_tile_charge", "ok": True, "credits": full_cost})
    log(f"PASS full resolve charged EUR {full_cost:.6f} and repeat was free.")

    # 4. Insufficient balance: session blocked cleanly and tile is not unlocked.
    reset_test_account(wrangler_cwd, "standard", 0.0)
    auth_payload = exchange_api_key(api_base_url, key_payload)
    headers = auth_headers(auth_payload, key_payload)
    insufficient_estimate = estimate(api_base_url, headers, "full", [INSUFFICIENT_TILE])
    insufficient_cost = float(insufficient_estimate.get("credits", 0) or 0)
    assert_true(insufficient_cost > 0, f"Insufficient test tile should cost EUR: {insufficient_estimate}")
    insufficient = session(api_base_url, headers, "full", [INSUFFICIENT_TILE], expected_status=402)
    assert_true(insufficient.get("error") == "insufficient_credits", f"Unexpected insufficient response: {insufficient}")
    assert_true(not insufficient.get("tile_token"), "Insufficient response must not include a tile token")
    assert_true(not any(t.get("tile_key") == INSUFFICIENT_TILE for t in unlocked_tiles(api_base_url, headers)), "Insufficient tile was unlocked")
    assert_balance(api_base_url, headers, 0.0, "insufficient-credit block")
    report["cases"].append({"name": "insufficient_clean_block", "ok": True, "required": insufficient_cost})
    log("PASS insufficient balance cleanly blocked before tile download.")

    # 5. Final Animation Render pricing/unlocking model:
    # The render preflight estimates all segment tiles before render; each segment
    # session then unlocks only newly encountered tiles. This mirrors the current
    # Final Animation sequence without needing to render image frames in this
    # backend-specific gate.
    reset_test_account(wrangler_cwd, "standard", STANDARD_BALANCE)
    auth_payload = exchange_api_key(api_base_url, key_payload)
    headers = auth_headers(auth_payload, key_payload)
    animation_tiles = [ANIMATION_SECOND_TILE, FULL_TILE]
    animation_estimate = estimate(api_base_url, headers, "full", animation_tiles)
    animation_cost = float(animation_estimate.get("credits", 0) or 0)
    assert_true(animation_cost > 0, f"Animation estimate should be positive: {animation_estimate}")
    segment_one = session(api_base_url, headers, "full", [ANIMATION_SECOND_TILE])
    segment_two = session(api_base_url, headers, "full", [ANIMATION_SECOND_TILE, FULL_TILE])
    charged_total = float(segment_one.get("credits_charged", 0) or 0) + float(segment_two.get("credits_charged", 0) or 0)
    assert_close(charged_total, animation_cost, "Segment unlocks did not match pre-render animation estimate")
    repeat_segment = session(api_base_url, headers, "full", animation_tiles)
    assert_close(repeat_segment.get("credits_charged", 0), 0, "Animation repeat segment charged after all tiles unlocked")
    unlocked_keys = {str(t.get("tile_key", "") or "") for t in unlocked_tiles(api_base_url, headers)}
    assert_true(set(animation_tiles).issubset(unlocked_keys), f"Animation tiles not unlocked: {unlocked_keys}")
    assert_balance(api_base_url, headers, STANDARD_BALANCE - animation_cost, "animation segment unlocks")
    report["cases"].append({"name": "animation_estimate_and_segment_unlocking", "ok": True, "credits": animation_cost})
    log(f"PASS animation estimate matched segment unlocking (EUR {animation_cost:.6f}).")

    reset_test_account(wrangler_cwd, "standard", STANDARD_BALANCE)
    final_row = account_row(wrangler_cwd)
    assert_true(final_row.get("account_type") == "standard", f"Final account type not restored: {final_row}")
    assert_close(final_row.get("balance_credits", 0), STANDARD_BALANCE, "Final account balance not restored")
    assert_true(int(final_row.get("unlocked", 0) or 0) == 0, f"Final unlocked tiles not reset: {final_row}")
    report["restored_account"] = final_row
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run live Planetka EUR pricing E2E tests.")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--key-json", default=str(DEFAULT_KEY_JSON))
    parser.add_argument("--wrangler-cwd", default=str(ROOT / "cloudflare-api"))
    parser.add_argument("--report", default=str(Path("/tmp") / "planetka_land_credit_live_e2e_report.json"))
    args = parser.parse_args(argv)

    report_path = Path(args.report).expanduser()
    try:
        report = run(
            api_base_url=str(args.api_base_url).rstrip("/"),
            key_json=Path(args.key_json).expanduser(),
            wrangler_cwd=Path(args.wrangler_cwd).expanduser(),
        )
        report["status"] = "passed"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log(f"PASS all live EUR pricing E2E cases. Report: {report_path}")
        return 0
    except Exception as exc:
        try:
            reset_test_account(Path(args.wrangler_cwd).expanduser(), "standard", STANDARD_BALANCE)
        except Exception:
            pass
        failure = {"status": "failed", "error": str(exc)}
        report_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
