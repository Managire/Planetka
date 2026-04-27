#!/usr/bin/env python3
"""Fail CI when recoverable-exception tuples are nested inside except tuples."""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


RECOVERABLE_CONST_NAMES = {
    "PLANETKA_RECOVERABLE_EXCEPTIONS",
    "PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS",
    "recoverable_exceptions",
}


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


def _is_recoverable_symbol(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        identifier = str(node.id or "")
        return (
            identifier in RECOVERABLE_CONST_NAMES
            or identifier.endswith("RECOVERABLE_EXCEPTIONS")
        )
    if isinstance(node, ast.Attribute):
        attr = str(node.attr or "")
        return (
            attr == "recoverable_exceptions"
            or attr.endswith("RECOVERABLE_EXCEPTIONS")
        )
    return False


def _find_offending_handlers(text: str) -> list[int]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    offending_lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        exception_expr = node.type
        if not isinstance(exception_expr, ast.Tuple):
            continue
        if any(_is_recoverable_symbol(element) for element in exception_expr.elts):
            offending_lines.append(int(getattr(node, "lineno", 1)))
    return offending_lines


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
        for line in _find_offending_handlers(text):
            rel = file_path.relative_to(repo_root)
            offenders.append(f"{rel}:{line}")

    if offenders:
        print("[except-pattern-check] Found invalid nested recoverable except patterns:")
        for item in offenders:
            print(f"  - {item}")
        print(
            "[except-pattern-check] Do not place recoverable exception tuples inside except tuple literals. "
            "Use either a standalone recoverable except block or a flattened tuple expression via tuple concatenation."
        )
        return 1

    print("[except-pattern-check] PASS: no nested recoverable except patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
