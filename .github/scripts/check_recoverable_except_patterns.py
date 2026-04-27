#!/usr/bin/env python3
"""Fail CI when nested recoverable-exception except tuples are introduced."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


PATTERN = re.compile(
    r"except\s*\(\s*PLANETKA_(?:IMPORT_)?RECOVERABLE_EXCEPTIONS\s*,",
    re.MULTILINE,
)


def _tracked_python_files(repo_root: Path) -> list[Path]:
    cmd = ["git", "ls-files", "*.py"]
    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    files: list[Path] = []
    for raw in (result.stdout or "").splitlines():
        rel = str(raw or "").strip()
        if not rel:
            continue
        files.append(repo_root / rel)
    return files


def _line_for_offset(text: str, offset: int) -> int:
    return int(text.count("\n", 0, max(0, int(offset))) + 1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for invalid nested recoverable-exception except tuples.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (defaults to current directory)",
    )
    args = parser.parse_args()

    repo_root = Path(str(args.repo_root)).resolve()
    if not repo_root.exists():
        print(f"[except-pattern-check] repo root not found: {repo_root}", file=sys.stderr)
        return 2

    offenders: list[str] = []
    for file_path in _tracked_python_files(repo_root):
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[except-pattern-check] warning: could not read {file_path}: {exc}", file=sys.stderr)
            continue
        for match in PATTERN.finditer(text):
            line = _line_for_offset(text, match.start())
            rel = file_path.relative_to(repo_root)
            offenders.append(f"{rel}:{line}")

    if offenders:
        print("[except-pattern-check] Found invalid nested recoverable except patterns:")
        for item in offenders:
            print(f"  - {item}")
        print(
            "[except-pattern-check] Replace with `except PLANETKA_*_RECOVERABLE_EXCEPTIONS:` "
            "or a flattened tuple expression."
        )
        return 1

    print("[except-pattern-check] PASS: no nested recoverable except patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
