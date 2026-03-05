#!/usr/bin/env python3
"""Planetka release-gate checks for versioning and release docs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHANGELOG_RELEASE_RE = re.compile(r"^##\s+\[(v?\d+\.\d+\.\d+)\]\s+-\s+(\d{4}-\d{2}-\d{2})\s*$")


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


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    manifest_path = root / "blender_manifest.toml"
    changelog_path = root / "CHANGELOG.md"
    compatibility_path = root / "Documentation" / "Release" / "COMPATIBILITY_MATRIX.md"
    checklist_path = root / "Documentation" / "Release" / "QA_CHECKLIST.md"
    template_path = root / "Documentation" / "Release" / "RELEASE_NOTES_TEMPLATE.md"

    errors: list[str] = []
    warnings: list[str] = []

    # 1) Manifest version semantic format
    try:
        manifest_version = parse_manifest_version(manifest_path)
    except Exception as exc:  # noqa: BLE001 - release gate hard-fail
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

    print("Planetka Release Gate")
    print(f"- manifest version: {manifest_version or '<unavailable>'}")
    if warnings:
        for warning in warnings:
            print(f"[WARN] {warning}")
    if errors:
        for err in errors:
            print(f"[FAIL] {err}")
        print(f"Release gate failed: {len(errors)} issue(s)")
        return 1

    print("Release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
