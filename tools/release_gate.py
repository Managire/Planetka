#!/usr/bin/env python3
"""Planetka release-gate checks for docs, auth hardening, release safety, and runtime E2E smoke."""

from __future__ import annotations

import re
import sys
from pathlib import Path
import os
import json
import shutil
import subprocess
import tempfile

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHANGELOG_RELEASE_RE = re.compile(r"^##\s+\[(v?\d+\.\d+\.\d+)\]\s+-\s+(\d{4}-\d{2}-\d{2})\s*$")
DEFAULT_BLENDER_CANDIDATES = (
    "/Applications/Blender5.0.app/Contents/MacOS/Blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_manifest_version(manifest_path: Path) -> str:
    if tomllib is None:
        raise RuntimeError("Python tomllib is required (Python 3.11+).")
    data = tomllib.loads(read_text(manifest_path))
    version = str(data.get("version", "")).strip()
    if not version:
        raise RuntimeError("Missing 'version' in blender_manifest.toml")
    return version


def find_changelog_releases(changelog_text: str) -> list[str]:
    versions = []
    for line in changelog_text.splitlines():
        match = CHANGELOG_RELEASE_RE.match(line.strip())
        if match:
            versions.append(match.group(1))
    return versions


def parse_bool_like(value: object) -> bool | None:
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def find_blender_bin() -> str:
    candidates = []
    for value in (
        os.environ.get("PLANETKA_RELEASE_GATE_BLENDER_BIN"),
        os.environ.get("BLENDER_BIN"),
    ):
        path = str(value or "").strip()
        if path:
            candidates.append(path)
    candidates.extend(DEFAULT_BLENDER_CANDIDATES)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def read_json_if_exists(path: Path) -> dict[str, object] | None:
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return None


def find_latest_short_report(render_root: Path) -> Path | None:
    candidates = sorted(
        render_root.glob("planetka_e2e_short_*/planetka_e2e_short_report.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0.0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def run_blender_gate_check(
    *,
    blender_bin: str,
    script_path: Path,
    label: str,
    background: bool,
    timeout_sec: int,
    env_updates: dict[str, str] | None = None,
    report_path: Path | None = None,
) -> tuple[bool, str, dict[str, object] | None]:
    env = os.environ.copy()
    if isinstance(env_updates, dict):
        env.update(env_updates)

    cmd = [blender_bin]
    if background:
        cmd.append("--background")
    cmd.extend(["--python", str(script_path)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=int(timeout_sec),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        summary = f"{label} timed out after {timeout_sec}s"
        stdout = str(getattr(exc, "stdout", "") or "").strip()
        stderr = str(getattr(exc, "stderr", "") or "").strip()
        if stdout:
            summary += f"\nstdout:\n{stdout[-2000:]}"
        if stderr:
            summary += f"\nstderr:\n{stderr[-2000:]}"
        return False, summary, None
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        return False, f"{label} failed to launch Blender: {exc}", None

    payload = read_json_if_exists(report_path) if report_path else None
    if result.returncode != 0:
        summary = (
            f"{label} failed with exit code {result.returncode}\n"
            f"stdout:\n{(result.stdout or '').strip()[-4000:]}\n"
            f"stderr:\n{(result.stderr or '').strip()[-4000:]}"
        )
        if report_path:
            summary += f"\nreport: {report_path}"
        return False, summary, payload

    if isinstance(payload, dict):
        if payload.get("ok") is False or str(payload.get("status", "") or "").lower() == "error":
            return False, f"{label} reported failure in {report_path}", payload

    return True, f"{label} passed.", payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    static_only = parse_bool_like(os.environ.get("PLANETKA_RELEASE_GATE_STATIC_ONLY")) is True
    if "--static-only" in sys.argv[1:]:
        static_only = True

    manifest_path = root / "blender_manifest.toml"
    changelog_path = root / "CHANGELOG.md"
    compatibility_path = root / "Documentation" / "Release" / "COMPATIBILITY_MATRIX.md"
    checklist_path = root / "Documentation" / "Release" / "QA_CHECKLIST.md"
    template_path = root / "Documentation" / "Release" / "RELEASE_NOTES_TEMPLATE.md"
    worker_path = root / "cloudflare-api" / "src" / "index.js"
    worker_tile_routes_path = root / "cloudflare-api" / "src" / "worker" / "tile_routes.js"
    worker_admin_analytics_path = root / "cloudflare-api" / "src" / "worker" / "admin_analytics_handlers.js"
    worker_maintenance_path = root / "cloudflare-api" / "src" / "worker" / "maintenance_jobs.js"
    wrangler_path = root / "cloudflare-api" / "wrangler.toml"
    fallback_dir = root / "Resources" / "Fallback Images"

    errors: list[str] = []
    warnings: list[str] = []

    # 1) Manifest version semantic format
    try:
        manifest_version = parse_manifest_version(manifest_path)
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001 - release gate hard-fail
        errors.append(f"Manifest read failed: {exc}")
        manifest_version = ""

    if manifest_version and not SEMVER_RE.match(manifest_version):
        errors.append(
            "Manifest version is not semantic MAJOR.MINOR.PATCH: "
            f"'{manifest_version}'"
        )

    manifest_v = f"v{manifest_version}" if manifest_version else ""

    # 2) Changelog discipline
    if not changelog_path.exists():
        errors.append("Missing CHANGELOG.md at repository root")
    else:
        changelog_text = read_text(changelog_path)
        releases = find_changelog_releases(changelog_text)
        if not releases:
            errors.append("CHANGELOG.md has no release sections like '## [vX.Y.Z] - YYYY-MM-DD'")
        elif manifest_v and releases[0] != manifest_v:
            errors.append(
                "Top changelog release does not match manifest version: "
                f"top='{releases[0]}', manifest='{manifest_v}'"
            )

    # 3) Compatibility matrix includes current extension version
    if not compatibility_path.exists():
        errors.append("Missing Documentation/Release/COMPATIBILITY_MATRIX.md")
    else:
        compatibility_text = read_text(compatibility_path)
        if manifest_v and manifest_v not in compatibility_text:
            errors.append(
                "Compatibility matrix does not reference current extension version: "
                f"{manifest_v}"
            )

    # 4) Rollback-safe update testing present in checklist
    if not checklist_path.exists():
        errors.append("Missing Documentation/Release/QA_CHECKLIST.md")
    else:
        checklist_text = read_text(checklist_path)
        if "Rollback-Safe Update Testing" not in checklist_text:
            errors.append("QA checklist missing 'Rollback-Safe Update Testing' section")

    # 5) Release template includes semver rationale + rollback notes
    if not template_path.exists():
        errors.append("Missing Documentation/Release/RELEASE_NOTES_TEMPLATE.md")
    else:
        template_text = read_text(template_path)
        if "Semantic Versioning Rationale" not in template_text:
            errors.append("Release notes template missing 'Semantic Versioning Rationale' section")
        if "Rollback and Migration Notes" not in template_text:
            errors.append("Release notes template missing 'Rollback and Migration Notes' section")

    # Soft advisory: pre-1.0 semantic expectations
    if manifest_version and manifest_version.startswith("0."):
        warnings.append(
            "Version is pre-1.0; MINOR bumps may still include breaking changes, "
            "but release notes must document them explicitly."
        )

    worker_src = ""
    worker_tile_routes_src = ""
    worker_admin_analytics_src = ""
    worker_maintenance_src = ""
    worker_auth_api_key_src = ""
    worker_auth_api_key_path = root / "cloudflare-api" / "src" / "worker" / "auth_api_key_handlers.js"
    if not worker_path.exists():
        errors.append("Missing cloudflare-api/src/index.js")
    else:
        worker_src = read_text(worker_path)
    if worker_tile_routes_path.exists():
        worker_tile_routes_src = read_text(worker_tile_routes_path)
    if worker_admin_analytics_path.exists():
        worker_admin_analytics_src = read_text(worker_admin_analytics_path)
    if worker_maintenance_path.exists():
        worker_maintenance_src = read_text(worker_maintenance_path)
    if worker_auth_api_key_path.exists():
        worker_auth_api_key_src = read_text(worker_auth_api_key_path)
    combined_worker_src = "\n".join(
        part
        for part in [
            worker_src,
            worker_tile_routes_src,
            worker_admin_analytics_src,
            worker_maintenance_src,
            worker_auth_api_key_src,
        ]
        if part
    )

    # 6) Worker access model must match the 0.7.0 plan-based product
    if combined_worker_src:
        required_worker_markers = [
            (
                "public API key request forces Free plan",
                [
                    "const requestedPlan = PLAN_CODE_FREE;",
                    "const requestedPlan = deps.PLAN_CODE_FREE;",
                ],
            ),
        ]
        for label, markers in required_worker_markers:
            if not any(marker in combined_worker_src for marker in markers):
                errors.append(
                    "Worker safeguard missing: "
                    f"{label} ({' or '.join(repr(marker) for marker in markers)})"
                )
    tile_quality_marker_present = (
        "X-Planetka-Quality-Mode" in worker_src
        or "X-Planetka-Quality-Mode" in worker_tile_routes_src
    )
    if not tile_quality_marker_present:
        errors.append(
            "Worker safeguard missing: tile requests read quality mode header "
            "('X-Planetka-Quality-Mode')"
        )

    # 7) Admin analytics must reject token query params
    if worker_src:
        query_token_reject_count = (
            worker_src.count("query_token_not_allowed")
            + worker_admin_analytics_src.count("query_token_not_allowed")
        )
        if query_token_reject_count < 2:
            errors.append(
                "Admin analytics query-token rejection appears incomplete "
                "(expected checks for both /admin/analytics and /admin/analytics/data)."
            )

    # 8) Legacy auth/throttle/claim systems must be absent from the worker surface
    if worker_src:
        forbidden_worker_markers = [
            ("legacy auth route", '"/auth/start"'),
            ("legacy auth route", '"/auth/verify"'),
            ("legacy device-login route", '"/device/start"'),
            ("legacy device-login route", '"/device/poll"'),
            ("legacy device-login route", '"/device/login"'),
            ("legacy download table", "user_download_counters"),
            ("download throttle config", "DOWNLOAD_THROTTLE_"),
            ("download throttle response", "download_throttled"),
            ("legacy paid-claim workflow", "paid_claim_workflow_disabled"),
            ("legacy provisional claim audit", "provisional_claim_audit"),
            ("claim rejection alert", "PROD_ALERT_CLAIM_REJECTION"),
        ]
        for label, marker in forbidden_worker_markers:
            if marker in worker_src:
                errors.append(f"Worker still contains {label} marker: '{marker}'")

    if wrangler_path.exists() and tomllib is not None:
        try:
            wrangler = tomllib.loads(read_text(wrangler_path))
            vars_table = wrangler.get("vars", {}) if isinstance(wrangler, dict) else {}
            forbidden_vars = [
                "ENABLE_MAGIC_LINK_AUTH",
                "DOWNLOAD_THROTTLE_FREE_DAILY_GB",
                "DOWNLOAD_THROTTLE_PRO_DAILY_GB",
                "DOWNLOAD_THROTTLE_DURATION_MINUTES",
                "DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE",
                "DOWNLOAD_THROTTLED_DELAY_MS",
                "PERMANENT_PRO_EMAILS",
            ]
            if isinstance(vars_table, dict):
                for var_name in forbidden_vars:
                    if var_name in vars_table:
                        errors.append(f"wrangler.toml still defines legacy var '{var_name}'")
        except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001 - release gate hard-fail
            errors.append(f"wrangler.toml parse failed: {exc}")

    # 9) Required fallback assets must exist; deprecated red fallback must be absent
    required_fallback_assets = [
        "black_pixel_20.exr",
        "blue_pixel_20.exr",
        "ocean_pixel_final_20.exr",
    ]
    for name in required_fallback_assets:
        asset_path = fallback_dir / name
        if not asset_path.exists():
            errors.append(f"Missing required fallback asset: Resources/Fallback Images/{name}")

    deprecated_red_asset = fallback_dir / "red_pixel_20.exr"
    if deprecated_red_asset.exists():
        errors.append(
            "Deprecated fallback asset still present: Resources/Fallback Images/red_pixel_20.exr "
            "(remove it to avoid packaging drift)."
        )

    # 10) Telemetry retention cleanup must be present and wired to scheduled job
    if combined_worker_src:
        retention_markers = [
            "CLEANUP_TILE_EVENT_RETENTION_DAYS",
            "DELETE FROM tile_request_events",
            "DELETE FROM tile_request_rollup_hourly_account",
            "DELETE FROM tile_request_rollup_daily_account",
            "runScheduledMaintenanceJobs(",
            "async scheduled(",
        ]
        for marker in retention_markers:
            if marker not in combined_worker_src:
                errors.append(f"Retention/cleanup guard missing in worker source: '{marker}'")

    print("Planetka Release Gate")
    print(f"- manifest version: {manifest_version or '<unavailable>'}")
    if not static_only:
        print("- runtime checks: enabled")
    else:
        print("- runtime checks: skipped (--static-only)")
    if warnings:
        for warning in warnings:
            print(f"[WARN] {warning}")
    if errors:
        for err in errors:
            print(f"[FAIL] {err}")
        print(f"Release gate failed: {len(errors)} issue(s)")
        return 1

    if static_only:
        print("Release gate passed.")
        return 0

    blender_bin = find_blender_bin()
    if not blender_bin:
        print("[FAIL] Blender binary not found for runtime release-gate checks.")
        print("Release gate failed: 1 issue(s)")
        return 1

    runtime_errors: list[str] = []
    runtime_root = Path(tempfile.gettempdir()) / "planetka_release_gate"
    runtime_root.mkdir(parents=True, exist_ok=True)

    queued_report = Path(tempfile.gettempdir()) / "planetka_ui_queued_resolve_test_report.json"
    try:
        queued_report.unlink(missing_ok=True)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    ok, summary, payload = run_blender_gate_check(
        blender_bin=blender_bin,
        script_path=root / "tools" / "planetka_create_earth_ui_queued_resolve_test.py",
        label="UI queued Create Earth test",
        background=False,
        timeout_sec=90,
        report_path=queued_report,
    )
    print(f"- {summary}")
    if isinstance(payload, dict) and queued_report.exists():
        print(f"  report: {queued_report}")
    if not ok:
        runtime_errors.append(summary)

    short_render_root = runtime_root / "short_e2e"
    if short_render_root.exists():
        try:
            shutil.rmtree(short_render_root)
        except TOOL_RECOVERABLE_EXCEPTIONS as exc:
            runtime_errors.append(f"Could not reset short E2E artifact dir: {exc}")
    short_render_root.mkdir(parents=True, exist_ok=True)

    ok, summary, payload = run_blender_gate_check(
        blender_bin=blender_bin,
        script_path=root / "tools" / "planetka_e2e_short.py",
        label="Short E2E render test",
        background=True,
        timeout_sec=240,
        env_updates={"PLANETKA_RENDER_DIR": str(short_render_root)},
    )
    short_report = find_latest_short_report(short_render_root)
    if isinstance(payload, dict) and short_report is not None:
        pass
    else:
        payload = read_json_if_exists(short_report) if short_report else None
    print(f"- {summary}")
    if short_report is not None:
        print(f"  report: {short_report}")
    if isinstance(payload, dict):
        renders = payload.get("renders", {})
        if isinstance(renders, dict):
            quick_preview = renders.get("quick_preview_eevee", {})
            if isinstance(quick_preview, dict):
                print(
                    "  quick_preview_eevee:"
                    f" pink={quick_preview.get('has_pink_corrupt')}"
                    f" mostly_black={quick_preview.get('has_mostly_black')}"
                )
    if not ok:
        runtime_errors.append(summary)

    if runtime_errors:
        for err in runtime_errors:
            print(f"[FAIL] {err}")
        print(f"Release gate failed: {len(runtime_errors)} runtime issue(s)")
        return 1

    print("Release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
