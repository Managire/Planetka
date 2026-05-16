#!/usr/bin/env python3
"""Comprehensive Planetka release-gate orchestrator.

This script intentionally tests customer-visible workflows and state
transitions, not only isolated backend functions. It runs existing gates plus
targeted checks for Blender UI state, live Worker/update endpoints, packaging,
and sandbox pricing consistency.

Profiles:
  quick    short developer smoke; use before small commits
  release  normal pre-deploy gate; default, models ordinary user behavior
  full     same live workload as release, but keeps all non-live gates enabled
  stress   heavy Worker capacity test; do not run against production casually

Example:
  python3 tools/planetka_full_release_gate.py --profile release
  python3 tools/planetka_full_release_gate.py --profile full
  PLANETKA_ALLOW_LIVE_STRESS=1 python3 tools/planetka_full_release_gate.py --profile stress

Operational note:
  Live stress testing can push the production Worker into Cloudflare 1102/503
  resource-limit responses. When that happens, Blender cannot reliably fetch
  Full Quality prices either, so this can temporarily affect real users. Keep
  stress runs separate from release validation and run them only in a controlled
  maintenance/testing window or against an isolated Worker/database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE_DIR = ROOT / "cloudflare-api"
BLENDER_BIN_DEFAULT = "/Applications/Blender5.0.app/Contents/MacOS/Blender"
REPORT_ROOT_DEFAULT = Path(tempfile.gettempdir()) / "planetka_full_release_gate"
UPDATE_MANIFEST_URL = "https://api.planetka.io/addon/update-manifest"
LEGAL_URLS = (
    "https://api.planetka.io/legal/terms-of-service.pdf",
    "https://api.planetka.io/legal/privacy-policy.pdf",
)

OPERATIONAL_NOTES = (
    "Live stress testing can push the production Cloudflare Worker into 1102/503 resource-limit responses. "
    "When that happens, Blender Full Quality price calculation can fail for real users too, because the add-on depends on the same Worker endpoints. "
    "The regular release profile must model ordinary user pacing; the guarded stress profile is only for controlled capacity testing.",
)


PROFILE_LIVE_TARGETS = {
    "quick": {
        "scene_targets": "slovakia:1",
        "country_targets": "belize",
        "region_targets": "",
    },
    "release": {
        "scene_targets": "slovakia:2,belgium:2",
        "country_targets": "belize",
        "region_targets": "central_europe",
    },
    "full": {
        "scene_targets": "slovakia:2,belgium:2",
        "country_targets": "belize",
        "region_targets": "central_europe",
    },
    # Still deterministic, but intentionally larger. Requires PLANETKA_ALLOW_LIVE_STRESS=1.
    "stress": {
        "scene_targets": "slovakia:2,belgium:2,italy:2,germany:2,spain:2",
        "country_targets": "belize,costa_rica,slovakia,belgium",
        "region_targets": "central_europe,southern_europe",
    },
}


@dataclass
class Step:
    name: str
    category: str
    command: list[str] | None = None
    cwd: str = str(ROOT)
    env: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 300
    required: bool = True


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_local_version() -> str:
    text = (ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.M)
    if not match:
        raise RuntimeError("Could not read version from blender_manifest.toml")
    return match.group(1).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tail(text: str, max_chars: int = 5000) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _run_step(step: Step) -> dict[str, Any]:
    started = time.time()
    env = os.environ.copy()
    env.update(step.env or {})
    result = {
        "name": step.name,
        "category": step.category,
        "required": bool(step.required),
        "started_at": _now_iso(),
        "cwd": step.cwd,
        "command": step.command,
    }
    try:
        proc = subprocess.run(
            step.command or [],
            cwd=step.cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=step.timeout_sec,
        )
        output = proc.stdout or ""
        result.update(
            {
                "status": "ok" if proc.returncode == 0 else "failed",
                "returncode": int(proc.returncode),
                "elapsed_sec": round(time.time() - started, 3),
                "output_tail": _tail(output),
            }
        )
        return result
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        result.update(
            {
                "status": "timeout",
                "returncode": None,
                "elapsed_sec": round(time.time() - started, 3),
                "output_tail": _tail(output),
                "error": f"timed out after {step.timeout_sec}s",
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001 - report must survive tool failures.
        result.update(
            {
                "status": "error",
                "returncode": None,
                "elapsed_sec": round(time.time() - started, 3),
                "output_tail": "",
                "error": str(exc),
            }
        )
        return result


def _fetch_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "PlanetkaReleaseGate/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError(f"JSON endpoint did not return object: {url}")
        return payload


def _head(url: str, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "PlanetkaReleaseGate/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {
            "status": int(response.status),
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": response.headers.get("Content-Length", ""),
            "cache_control": response.headers.get("Cache-Control", ""),
        }


def _download_sha256(url: str, timeout: float = 120.0) -> tuple[str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": "PlanetkaReleaseGate/1.0"})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _check_update_manifest(local_version: str, package_path: Path) -> dict[str, Any]:
    payload = _fetch_json(UPDATE_MANIFEST_URL)
    local_build_sha = _sha256(package_path) if package_path.is_file() else ""
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("version") != local_version:
        errors.append(f"manifest version {payload.get('version')} != local version {local_version}")
    if not payload.get("download_url"):
        errors.append("manifest download_url is empty")
    zip_head = {}
    live_zip_sha = ""
    live_zip_bytes = 0
    if payload.get("download_url"):
        try:
            zip_head = _head(str(payload.get("download_url")))
            if int(zip_head.get("status", 0)) != 200:
                errors.append(f"download URL HEAD returned {zip_head.get('status')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"download URL HEAD failed: {exc}")
        try:
            live_zip_sha, live_zip_bytes = _download_sha256(str(payload.get("download_url")))
            if payload.get("sha256") != live_zip_sha:
                errors.append("downloaded update zip sha256 does not match manifest sha256")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"download URL sha256 check failed: {exc}")
    if local_build_sha and payload.get("sha256") != local_build_sha:
        message = "local rebuilt package sha256 does not match currently deployed manifest sha256"
        if str(os.environ.get("PLANETKA_STRICT_LOCAL_PACKAGE_SHA") or "").strip().lower() in {"1", "true", "yes", "on"}:
            errors.append(message)
        else:
            warnings.append(message)
    return {
        "status": "ok" if not errors else "failed",
        "payload": payload,
        "local_build_sha256": local_build_sha,
        "live_zip_sha256": live_zip_sha,
        "live_zip_bytes": live_zip_bytes,
        "download_head": zip_head,
        "errors": errors,
        "warnings": warnings,
    }


def _check_public_web_endpoints() -> dict[str, Any]:
    results = []
    errors = []
    for url in LEGAL_URLS:
        try:
            head = _head(url)
            ok = int(head.get("status", 0)) == 200
            results.append({"url": url, "ok": ok, **head})
            if not ok:
                errors.append(f"{url} returned {head.get('status')}")
        except Exception as exc:  # noqa: BLE001
            results.append({"url": url, "ok": False, "error": str(exc)})
            errors.append(f"{url} failed: {exc}")
    return {"status": "ok" if not errors else "failed", "results": results, "errors": errors}


def _build_steps(args: argparse.Namespace, package_path: Path) -> list[Step]:
    blender_bin = str(args.blender_bin or BLENDER_BIN_DEFAULT)
    profile = str(args.profile)
    live_targets = PROFILE_LIVE_TARGETS[profile]
    steps = [
        Step(
            name="python_compile",
            category="static",
            command=[
                "python3",
                "-m",
                "py_compile",
                "ui.py",
                "operators.py",
                "planetka_runtime/auto_resolve_pipeline.py",
                "auth.py",
                "render_prep.py",
                "planetka_ops/account_ops.py",
                "planetka_ops/earth_lifecycle_helpers.py",
                "updater.py",
            ],
            timeout_sec=120,
        ),
        Step(
            name="blender_compat_smoke",
            category="static",
            command=["python3", "tools/blender_compat_smoke_test.py"],
            timeout_sec=120,
        ),
        Step(
            name="release_gate_static",
            category="static",
            command=["python3", "tools/release_gate.py"],
            env={"PLANETKA_RELEASE_GATE_STATIC_ONLY": "1"},
            timeout_sec=180,
        ),
        Step(
            name="diff_check",
            category="static",
            command=["git", "diff", "--check"],
            timeout_sec=60,
        ),
        Step(
            name="no_sync_pricing_public_routes_smoke",
            category="worker",
            command=["node", "tools/planetka_no_sync_pricing_public_routes_smoke.mjs"],
            timeout_sec=120,
        ),
        Step(
            name="build_public_package",
            category="package",
            command=["python3", "tools/build_addon_zip.py", "--output", str(package_path)],
            timeout_sec=600,
        ),
        Step(
            name="worker_deploy_dry_run",
            category="worker",
            command=["npx", "wrangler", "deploy", "--dry-run"],
            cwd=str(CLOUDFLARE_DIR),
            timeout_sec=240,
        ),
    ]
    if not args.skip_blender:
        steps.extend(
            [
                Step(
                    name="blender_core_user_flow_gate",
                    category="blender",
                    command=[
                        blender_bin,
                        "--background",
                        "--factory-startup",
                        "--debug-python",
                        "--python",
                        "tools/planetka_core_user_flow_gate.py",
                    ],
                    timeout_sec=int(args.blender_timeout_sec),
                ),
                Step(
                    name="blender_ui_state_regression_gate",
                    category="blender",
                    command=[
                        blender_bin,
                        "--background",
                        "--factory-startup",
                        "--debug-python",
                        "--python",
                        "tools/planetka_ui_state_regression_gate.py",
                    ],
                    timeout_sec=240,
                ),
                Step(
                    name="stale_auth_recovery_gate",
                    category="auth",
                    command=[
                        blender_bin,
                        "--background",
                        "--factory-startup",
                        "--debug-python",
                        "--python",
                        "tools/planetka_stale_auth_recovery_gate.py",
                    ],
                    timeout_sec=180,
                ),
            ]
        )
    if not args.skip_live_pricing:
        live_env = {
            "PLANETKA_E2E_SCENE_TARGETS": str(args.live_scene_targets or live_targets["scene_targets"]),
            "PLANETKA_E2E_COUNTRY_TARGETS": str(args.live_country_targets or live_targets["country_targets"]),
            "PLANETKA_E2E_REGION_TARGETS": str(args.live_region_targets or live_targets["region_targets"]),
        }
        if profile == "stress":
            live_env.update(
                {
                    "PLANETKA_E2E_PACE_SEC": "0",
                }
            )
        steps.append(
            Step(
                name="live_pricing_stress_maintenance" if profile == "stress" else "bounded_live_health_gate",
                category="stress" if profile == "stress" else "live_health",
                command=[
                    blender_bin,
                    "--background",
                    "--debug-python",
                    "--python",
                    "tools/live_pricing_consistency_e2e.py",
                ],
                env=live_env,
                timeout_sec=int(args.live_pricing_timeout_sec),
            )
        )
    return steps


def _write_markdown(report_path: Path, report: dict[str, Any]) -> Path:
    md_path = report_path.with_suffix(".md")
    lines = [
        "# Planetka Full Release Gate Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Profile: `{report.get('profile')}`",
        f"- Started: `{report.get('started_at')}`",
        f"- Elapsed: `{report.get('elapsed_sec')}` seconds",
        f"- Local version: `{report.get('local_version')}`",
        "",
        "## Operational Notes",
        "",
    ]
    for note in report.get("operational_notes", []) or []:
        lines.append(f"- {note}")
    lines.extend([
        "",
        "## Steps",
        "",
        "| Step | Category | Status | Seconds |",
        "| --- | --- | --- | ---: |",
    ])
    for step in report.get("steps", []):
        lines.append(
            f"| `{step.get('name')}` | `{step.get('category')}` | `{step.get('status')}` | {step.get('elapsed_sec', '')} |"
        )
    lines.extend(["", "## Endpoint Checks", ""])
    for check_name in ("update_manifest", "public_web_endpoints"):
        check = report.get(check_name) or {}
        lines.append(f"- `{check_name}`: `{check.get('status')}`")
        for error in check.get("errors", []) or []:
            lines.append(f"  - {error}")
    failures = report.get("failures", []) or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('name')}`: {failure.get('status')} {failure.get('error') or ''}".rstrip())
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the comprehensive Planetka release gate.")
    parser.add_argument("--profile", choices=sorted(PROFILE_LIVE_TARGETS), default="release")
    parser.add_argument("--report-dir", default=str(REPORT_ROOT_DEFAULT))
    parser.add_argument("--blender-bin", default=str(os.environ.get("BLENDER_BIN") or BLENDER_BIN_DEFAULT))
    parser.add_argument("--skip-blender", action="store_true")
    parser.add_argument("--skip-live-pricing", action="store_true")
    parser.add_argument("--live-scene-targets", default=None, help="Comma-separated product_id:tile_count scene targets for the live pricing gate.")
    parser.add_argument("--live-country-targets", default=None, help="Comma-separated country product IDs for the live pricing gate.")
    parser.add_argument("--live-region-targets", default=None, help="Comma-separated region product IDs for the live pricing gate.")
    parser.add_argument("--scene-tests", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--country-tests", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--region-tests", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--blender-timeout-sec", type=int, default=900)
    parser.add_argument("--live-pricing-timeout-sec", type=int, default=7200)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if (
        args.profile == "stress"
        and not args.skip_live_pricing
        and str(os.environ.get("PLANETKA_ALLOW_LIVE_STRESS") or "").strip().lower() not in {"1", "true", "yes", "on"}
    ):
        print(
            "Refusing live stress profile without PLANETKA_ALLOW_LIVE_STRESS=1. "
            "Live stress runs can push the production Worker into 1102/503 and temporarily block Blender pricing.",
            file=sys.stderr,
        )
        return 2
    started = time.time()
    local_version = _read_local_version()
    report_dir = Path(args.report_dir).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"planetka_full_release_gate_{args.profile}_{stamp}.json"
    package_path = report_dir / f"Planetka_release_gate_{local_version}.zip"

    report: dict[str, Any] = {
        "status": "running",
        "profile": args.profile,
        "started_at": _now_iso(),
        "local_version": local_version,
        "package_path": str(package_path),
        "operational_notes": list(OPERATIONAL_NOTES),
        "steps": [],
        "failures": [],
    }

    steps = _build_steps(args, package_path)
    for step in steps:
        print(f"[Planetka Full Release Gate] START {step.name}", flush=True)
        result = _run_step(step)
        report["steps"].append(result)
        print(
            f"[Planetka Full Release Gate] {result.get('status', 'unknown').upper()} "
            f"{step.name} ({result.get('elapsed_sec')}s)",
            flush=True,
        )
        if result.get("status") != "ok" and step.required:
            report["failures"].append(
                {
                    "name": step.name,
                    "category": step.category,
                    "status": result.get("status"),
                    "error": result.get("error", ""),
                    "output_tail": result.get("output_tail", ""),
                }
            )

    print("[Planetka Full Release Gate] START update_manifest", flush=True)
    try:
        manifest_check = _check_update_manifest(local_version, package_path)
    except Exception as exc:  # noqa: BLE001
        manifest_check = {"status": "error", "errors": [str(exc)]}
    report["update_manifest"] = manifest_check
    if manifest_check.get("status") != "ok":
        report["failures"].append({"name": "update_manifest", "category": "web", "status": manifest_check.get("status"), "error": "; ".join(manifest_check.get("errors", []))})
    print(f"[Planetka Full Release Gate] {manifest_check.get('status', 'unknown').upper()} update_manifest", flush=True)

    print("[Planetka Full Release Gate] START public_web_endpoints", flush=True)
    try:
        web_check = _check_public_web_endpoints()
    except Exception as exc:  # noqa: BLE001
        web_check = {"status": "error", "errors": [str(exc)]}
    report["public_web_endpoints"] = web_check
    if web_check.get("status") != "ok":
        report["failures"].append({"name": "public_web_endpoints", "category": "web", "status": web_check.get("status"), "error": "; ".join(web_check.get("errors", []))})
    print(f"[Planetka Full Release Gate] {web_check.get('status', 'unknown').upper()} public_web_endpoints", flush=True)

    report["elapsed_sec"] = round(time.time() - started, 3)
    report["status"] = "ok" if not report["failures"] else "failed"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path = _write_markdown(report_path, report)
    print(f"[Planetka Full Release Gate] REPORT {report_path}", flush=True)
    print(f"[Planetka Full Release Gate] SUMMARY {md_path}", flush=True)
    print("PLANETKA_FULL_RELEASE_GATE_RESULT " + json.dumps({"status": report["status"], "failures": len(report["failures"]), "report": str(report_path), "summary": str(md_path)}, sort_keys=True), flush=True)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
