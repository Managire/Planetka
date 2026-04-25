#!/usr/bin/env python3
"""Sync tile size index rows from Cloud R2 object metadata.

Updates `tile_sizes.sqlite` using actual object sizes reported by R2.
Supports compact schema: tile_sizes(folder, x, y, z, d, ext, size_bytes).

Example:
  python3 tools/sync_tile_sizes_from_r2.py \
    --db Resources/tile_sizes.sqlite \
    --folder S2 \
    --bucket planetka-data \
    --prefix planetka-assets \
    --profile planetka-r2 \
    --prune-missing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

ALLOWED_FOLDERS = {"S2", "EL", "WT", "PO"}
TILE_FILE_RE = re.compile(
    r"^(?P<folder>S2|EL|WT|PO)_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.(?P<ext>exr|tif)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TileRow:
    folder: str
    x: int
    y: int
    z: int
    d: int
    ext: str
    size_bytes: int


def _parse_account_id_from_secrets(secrets_path: Path) -> str:
    if not secrets_path.is_file():
        raise RuntimeError(f"Secrets file not found: {secrets_path}")
    with secrets_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            normalized = line.replace("\u00a0", " ")
            if "R2_ACCOUNT_ID" not in normalized:
                continue
            parts = normalized.split("=", 1)
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            val = parts[1].strip()
            if key == "R2_ACCOUNT_ID" and val:
                return val
    raise RuntimeError(f"R2_ACCOUNT_ID not found in secrets file: {secrets_path}")


def _resolve_endpoint(args: argparse.Namespace) -> str:
    endpoint = str(args.endpoint_url or "").strip()
    if endpoint:
        return endpoint
    account_id = _parse_account_id_from_secrets(Path(args.secrets_file).expanduser())
    return f"https://{account_id}.r2.cloudflarestorage.com"


def _run_aws_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or "Unknown aws cli error"
        raise RuntimeError(f"AWS CLI failed: {' '.join(cmd)}\n{msg}")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse AWS CLI JSON output") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected AWS CLI response payload")
    return payload


def _iter_r2_objects(
    *,
    aws_bin: str,
    bucket: str,
    prefix: str,
    profile: str,
    endpoint_url: str,
):
    continuation_token = ""
    while True:
        cmd = [
            aws_bin,
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
            "--max-keys",
            "1000",
            "--profile",
            profile,
            "--endpoint-url",
            endpoint_url,
            "--output",
            "json",
        ]
        if continuation_token:
            cmd.extend(["--continuation-token", continuation_token])
        payload = _run_aws_json(cmd)
        for entry in payload.get("Contents", []) or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("Key", "") or "").strip()
            try:
                size = int(entry.get("Size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            if key:
                yield key, max(0, size)
        if not bool(payload.get("IsTruncated", False)):
            break
        continuation_token = str(payload.get("NextContinuationToken", "") or "").strip()
        if not continuation_token:
            break


def _parse_tile_row_from_key(key: str, expected_folder: str) -> TileRow | None:
    # Expected key: <prefix>/<FOLDER>/<FOLDER>_xNNN_yNNN_zNNN_dNNN.<ext>
    file_name = key.rsplit("/", 1)[-1]
    match = TILE_FILE_RE.match(file_name)
    if not match:
        return None
    folder = str(match.group("folder") or "").upper()
    if folder != expected_folder:
        return None
    ext = str(match.group("ext") or "").lower()
    try:
        x = int(match.group("x"))
        y = int(match.group("y"))
        z = int(match.group("z"))
        d = int(match.group("d"))
    except (TypeError, ValueError):
        return None
    return TileRow(folder=folder, x=x, y=y, z=z, d=d, ext=ext, size_bytes=0)


def _ensure_compact_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(tile_sizes)").fetchall()
    cols = {str(row[1] or "").strip().lower() for row in rows if isinstance(row, (tuple, list)) and len(row) > 1}
    required = {"folder", "x", "y", "z", "d", "ext", "size_bytes"}
    if not required.issubset(cols):
        raise RuntimeError("Unsupported tile_sizes schema. Expected compact schema with folder/x/y/z/d/ext/size_bytes.")


def _count_folder_rows(conn: sqlite3.Connection, folder: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM tile_sizes WHERE folder = ?", (folder,)).fetchone()
    try:
        return int(row[0] if row else 0)
    except (TypeError, ValueError):
        return 0


def sync_folder_sizes(args: argparse.Namespace) -> None:
    folder = str(args.folder or "").strip().upper()
    if folder not in ALLOWED_FOLDERS:
        raise RuntimeError(f"Unsupported folder: {folder}. Use one of: {', '.join(sorted(ALLOWED_FOLDERS))}")

    aws_bin = shutil.which("aws")
    if not aws_bin:
        raise RuntimeError("aws CLI not found in PATH")

    endpoint_url = _resolve_endpoint(args)
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError(f"DB file not found: {db_path}")

    prefix_base = str(args.prefix or "planetka-assets").strip().strip("/")
    remote_prefix = f"{prefix_base}/{folder}/"

    print(f"[sync] db={db_path}")
    print(f"[sync] bucket={args.bucket} profile={args.profile}")
    print(f"[sync] endpoint={endpoint_url}")
    print(f"[sync] listing prefix={remote_prefix}")

    t0 = time.perf_counter()
    parsed_rows: list[tuple[str, int, int, int, int, str, int]] = []
    invalid_keys = 0
    duplicate_keys = 0
    seen = set()

    for key, size in _iter_r2_objects(
        aws_bin=aws_bin,
        bucket=str(args.bucket),
        prefix=remote_prefix,
        profile=str(args.profile),
        endpoint_url=endpoint_url,
    ):
        parsed = _parse_tile_row_from_key(key, expected_folder=folder)
        if parsed is None:
            invalid_keys += 1
            continue
        pk = (parsed.folder, parsed.x, parsed.y, parsed.z, parsed.d, parsed.ext)
        if pk in seen:
            duplicate_keys += 1
            continue
        seen.add(pk)
        parsed_rows.append((parsed.folder, parsed.x, parsed.y, parsed.z, parsed.d, parsed.ext, int(size)))

    list_elapsed = time.perf_counter() - t0
    print(
        f"[sync] listed rows={len(parsed_rows)} invalid_keys={invalid_keys} duplicates={duplicate_keys} elapsed={list_elapsed:.1f}s"
    )

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_compact_schema(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        existing_before = _count_folder_rows(conn, folder)
        print(f"[sync] existing {folder} rows in db={existing_before}")

        conn.execute("BEGIN")
        conn.execute("DROP TABLE IF EXISTS _r2_sizes_tmp")
        conn.execute(
            """
            CREATE TEMP TABLE _r2_sizes_tmp (
              folder TEXT NOT NULL,
              x INTEGER NOT NULL,
              y INTEGER NOT NULL,
              z INTEGER NOT NULL,
              d INTEGER NOT NULL,
              ext TEXT NOT NULL,
              size_bytes INTEGER NOT NULL,
              PRIMARY KEY(folder, x, y, z, d, ext)
            ) WITHOUT ROWID
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO _r2_sizes_tmp(folder, x, y, z, d, ext, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            parsed_rows,
        )

        changed_size = conn.execute(
            """
            SELECT COUNT(*)
            FROM _r2_sizes_tmp r
            JOIN tile_sizes t
              ON t.folder = r.folder
             AND t.x = r.x
             AND t.y = r.y
             AND t.z = r.z
             AND t.d = r.d
             AND t.ext = r.ext
            WHERE t.size_bytes != r.size_bytes
            """
        ).fetchone()[0]

        new_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM _r2_sizes_tmp r
            LEFT JOIN tile_sizes t
              ON t.folder = r.folder
             AND t.x = r.x
             AND t.y = r.y
             AND t.z = r.z
             AND t.d = r.d
             AND t.ext = r.ext
            WHERE t.folder IS NULL
            """
        ).fetchone()[0]

        missing_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM tile_sizes t
            LEFT JOIN _r2_sizes_tmp r
              ON t.folder = r.folder
             AND t.x = r.x
             AND t.y = r.y
             AND t.z = r.z
             AND t.d = r.d
             AND t.ext = r.ext
            WHERE t.folder = ?
              AND r.folder IS NULL
            """,
            (folder,),
        ).fetchone()[0]

        conn.execute(
            """
            INSERT OR REPLACE INTO tile_sizes(folder, x, y, z, d, ext, size_bytes)
            SELECT folder, x, y, z, d, ext, size_bytes
            FROM _r2_sizes_tmp
            """
        )

        deleted_rows = 0
        if bool(args.prune_missing):
            deleted_rows = conn.execute(
                """
                DELETE FROM tile_sizes
                WHERE folder = ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM _r2_sizes_tmp r
                    WHERE r.folder = tile_sizes.folder
                      AND r.x = tile_sizes.x
                      AND r.y = tile_sizes.y
                      AND r.z = tile_sizes.z
                      AND r.d = tile_sizes.d
                      AND r.ext = tile_sizes.ext
                  )
                """,
                (folder,),
            ).rowcount

        conn.execute("DROP TABLE IF EXISTS _r2_sizes_tmp")
        conn.commit()

        final_count = _count_folder_rows(conn, folder)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        conn.rollback()
        raise
    finally:
        conn.close()

    total_elapsed = time.perf_counter() - t0
    print(f"[sync] changed_size_rows={int(changed_size)}")
    print(f"[sync] new_rows={int(new_rows)}")
    print(f"[sync] missing_rows_detected={int(missing_rows)}")
    print(f"[sync] deleted_rows={int(deleted_rows)}")
    print(f"[sync] final {folder} rows in db={int(final_count)}")
    print(f"[sync] done elapsed={total_elapsed:.1f}s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync tile size sqlite rows from Cloud R2 object metadata")
    parser.add_argument("--db", required=True, help="Path to tile_sizes.sqlite")
    parser.add_argument("--folder", required=True, help="Tile folder to sync: S2, EL, WT, PO")
    parser.add_argument("--bucket", default="planetka-data", help="R2 bucket name")
    parser.add_argument("--prefix", default="planetka-assets", help="Root key prefix in R2")
    parser.add_argument("--profile", default="planetka-r2", help="AWS CLI profile for R2")
    parser.add_argument("--endpoint-url", default="", help="Optional explicit R2 endpoint URL")
    parser.add_argument(
        "--secrets-file",
        default=f"{Path.home()}/.planetka/secrets/Cloudflare_API_from_stash_2026-03-17.txt",
        help="Secrets file containing R2_ACCOUNT_ID (used when endpoint-url is not provided)",
    )
    parser.add_argument(
        "--prune-missing",
        action="store_true",
        help="Delete rows for selected folder that are not present in R2 listing",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        sync_folder_sizes(args)
        return 0
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
