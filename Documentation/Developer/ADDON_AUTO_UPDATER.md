# Planetka Addon Auto-Updater

Last updated: `2026-04-01`

## Overview

Planetka now supports safe staged auto-updates:

1. Addon checks Cloudflare manifest endpoint in background.
2. If newer version exists, addon package zip is downloaded to local updater cache.
3. Update is staged and applied automatically on next Blender start.
4. If apply fails, updater rolls files back from local backup.

This avoids remote live-code execution while still reducing manual update friction.

## Manifest Endpoint

Worker route:

- `GET /addon/update-manifest`

Expected payload:

```json
{
  "ok": true,
  "addon_id": "planetka",
  "channel": "stable",
  "version": "0.2.1",
  "download_url": "https://.../planetka-0.2.1.zip",
  "sha256": "64-char-lowercase-hex",
  "release_notes_url": "https://www.planetka.io/blender/documentation/",
  "min_blender_version": "4.5.7",
  "mandatory": false,
  "published_at": "2026-04-01T08:00:00Z",
  "available": true
}
```

## Safety Rules

- `addon_id` must match `planetka`.
- If `sha256` is provided, package hash must match exactly.
- Package must contain `blender_manifest.toml`.
- Failed apply triggers file rollback from backup snapshot.

## Runtime Behavior

- Background check is kicked off:
  - during addon `register()`
  - when user clicks `Create Earth`
  - manually via `Check for Updates` button in Account panel
- Checks are rate-limited by `PLANETKA_UPDATE_CHECK_INTERVAL_SECONDS` (default: 6h).
- Downloaded updates show status in Account panel:
  - `Update X.Y.Z downloaded. Restart Blender to apply.`

## Local Paths

Updater cache root:

- macOS: `~/Library/Caches/Planetka/updater`
- other OS: `~/.cache/planetka/updater`

Structure:

- `state.json` — updater state
- `downloads/` — downloaded update zips
- `backups/` — file backups for rollback
