# Cloud Global Access Optimization Checklist

Last updated: 2026-03-27

## What was implemented in code now

These changes are already applied in the Worker source:

- Tile cache policy is now centralized and environment-configurable.
- Default tile cache policy increased to:
  - Browser cache (`max-age`): 86400 seconds (1 day)
  - Edge cache (`s-maxage`): 604800 seconds (7 days)
  - `immutable` enabled
- The same cache policy is now applied consistently to both:
  - edge-cached object responses
  - final user responses
- Worker env vars are now split across `wrangler.auth.toml`, `wrangler.tiles.toml`, and `wrangler.analytics.toml`:
  - `TILE_BROWSER_MAX_AGE_SECONDS = "86400"`
  - `TILE_EDGE_MAX_AGE_SECONDS = "604800"`
  - `TILE_CACHE_IMMUTABLE = "1"`
  - `ANALYTICS_ADMIN_EMAILS = "info@planetka.io,tom.griger@gmail.com"`

## Analytics dashboard (implemented)

New admin endpoints:

- `GET /admin/analytics` (live dashboard UI)
- `GET /admin/analytics/data?minutes=60` (JSON payload)

Access control:

- requires Bearer token (query token is rejected by design)
- email must be listed in `ANALYTICS_ADMIN_EMAILS`

Tracked telemetry:

- per-tile request events: user, tile key, status code, bytes served, cache hit/miss, request duration, country, ray id, optional resolve id
- active users (5/15/60 min)
- live tile event rate (last 10 seconds)
- top users, top tiles, recent failures

## Deploy these code changes

From:
`/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka`

1. Deploy the split Workers explicitly
   - `cd cloudflare-api`
   - `npx wrangler deploy --config wrangler.auth.toml`
   - `npx wrangler deploy --config wrangler.tiles.toml`
   - `npx wrangler deploy --config wrangler.analytics.toml`
2. Verify cache header on a tile request
   - Confirm `Cache-Control` contains `max-age=86400, s-maxage=604800, immutable`.

## Cloud dashboard settings you should enable (step-by-step)

These are account/zone settings I cannot reliably enforce from this repo alone.

### 1) Tiered Cache (high impact)

1. Open Cloud Dashboard -> `planetka.io`.
2. Go to `Caching` -> `Tiered Cache`.
3. Enable `Tiered Cache`.
4. If available, enable `Smart Tiered Cache`.

Expected result: better cache hit ratio outside Europe, fewer R2 miss fetches.

### 2) Cache Reserve (high impact for large tiles)

1. Go to `Caching` -> `Cache Reserve`.
2. Enable `Cache Reserve` for `planetka.io`.
3. Keep default retention initially.

Expected result: fewer expensive refetches for less-frequently-requested large EXR/TIF assets.

### 3) Ensure modern transport settings

1. Go to `Network`.
2. Ensure `HTTP/3` is ON.
3. Go to `Speed` or `Compression`.
4. Ensure `Brotli` is ON.
5. Go to `SSL/TLS`.
6. Ensure `TLS 1.3` is ON.
7. Set minimum TLS version to `1.2` (or `1.3` only if your clients all support it).

### 4) Add explicit cache rule for `/tiles/*`

1. Go to `Rules` -> `Cache Rules` -> `Create rule`.
2. Condition: URI Path starts with `/tiles/`.
3. Actions:
   - Cache eligibility: `Eligible` (Cache Everything equivalent for this route)
   - Edge TTL: `Respect existing headers` (recommended with current Worker),
     or set explicit Edge TTL >= 7 days.
4. Save and deploy rule.

### 5) Verify WAF/Bot settings do not break auth

1. Go to `Security` -> `WAF` and `Bots`.
2. Keep protections enabled for API.
3. If login/device flow fails, add narrow exceptions only for required auth endpoints.

## Recommended next performance steps (not implemented yet)

### A) Range request support for tile streaming

Why: large tile files recover better on unstable networks and improve partial retries.

Implementation target:
- Add proper `Range` handling in `/tiles/*`.
- Return `206 Partial Content` with `Content-Range` and `Accept-Ranges: bytes`.

### B) Multi-region data strategy for R2 misses

Current bucket location is `WEUR`.

For better first-byte latency globally:
- Option 1: Keep single bucket + strong edge/tiered cache (simpler).
- Option 2: Add regional buckets (EU/US/APAC) and route by geography in Worker.

## Quick verification checklist

- `api.planetka.io` responses include Cloud edge headers.
- Authenticated tile request returns:
  - `200`
  - expected `Cache-Control`
  - `ETag`
  - `X-Planetka-Cache` (`MISS` then `HIT` on repeat)
- No regressions in Blender tile downloads.

## Rollback

If needed:

1. In the Worker project folder, run `npx wrangler deployments list --name planetka-auth`, `npx wrangler deployments list --name planetka-tiles`, or `npx wrangler deployments list --name planetka-analytics`.
2. Roll back the affected split Worker to the prior stable deployment/version.
