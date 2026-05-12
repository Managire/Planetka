# Planetka Internal Pricing System Reference

This document describes the current EUR land-detail pricing system from a technical point of view. It is an internal implementation reference, not public legal text.

Last updated: 2026-05-10

## 1. Design Goals

The pricing system sells licenced access to Full Quality land-detail texture tiles while keeping Preview data free.

Core goals:

- Preview quality is free and unlimited from the user-experience point of view, subject to fair-usage monitoring.
- Full Quality is paid/licenced per tile, but users are charged only once for the same tile detail entitlement.
- Price is based on land area and delivered texture detail, not on raw file size or number of downloads.
- Once a tile is licenced, the user can download it again without paying again.
- Pricing must be backend-authoritative. The Blender client may display estimates, but must not be trusted to decide the final charge.
- Missing or inconsistent backend pricing metadata must never overcharge users. Such cases are charged at EUR 0.00 and logged as pricing integrity events.
- Animation render should pre-licence and pre-download all required Full Quality data before frame rendering starts.

## 2. User-Facing Terminology

User-facing UI should use these terms:

- `EUR` / `€`: The displayed price currency.
- `Licenced`: A tile the user has paid for or otherwise received rights to use.
- `Full Quality Textures`: The primary paid action for the current Camera View.
- `Preview`: Free low-detail data used for normal browsing and Quick Preview animation.

Some internal API fields still use `credits` for historical reasons. In the current implementation they mean EUR price values, not a user-held balance.

## 3. Authoritative Components

### Backend Worker

Primary files:

- `cloudflare-api/src/worker/credit_routes.js`
- `cloudflare-api/src/worker/tile_routes.js`
- `cloudflare-api/src/worker/billing_handlers.js`
- `cloudflare-api/src/index.js`

The Cloudflare Worker is the authority for:

- Tile licence/entitlement state.
- Full Quality price calculation.
- Stripe Checkout session creation.
- Stripe webhook processing.
- Blocking unauthorised Full Quality tile requests.
- Preview fair-usage telemetry and alerts.

### Blender Client

Primary files:

- `credit_api.py`
- `planetka_runtime/view_telemetry.py`
- `operators.py`
- `ui.py`
- `animation_tools.py`
- `r2_source.py`
- `streaming_utils.py`

The Blender client is responsible for:

- Computing the current visible tile set for the Camera View.
- Asking the backend for authoritative EUR estimates.
- Displaying prices, data sizes, and breakdowns.
- Starting Stripe Checkout when needed.
- Starting paid Full Quality resolves only after backend licence/session confirmation.
- Downloading licenced assets from Cloudflare R2 or from Local Source.

The client must not calculate final charge locally.

## 4. Data Model

The backend D1 database contains the authoritative account, licence, pricing, and ledger tables.

### `user_credit_accounts`

Created in `ensureCreditTables()` in `cloudflare-api/src/index.js`.

Important columns:

- `user_id`: Primary key.
- `account_type`: Currently always `standard`.
- `world_full_quality_unlocked_at`, `world_full_quality_paid_eur`: World-pack entitlement summary.
- `pricing_version`: Incremented when user entitlements change so pricing caches invalidate.
- `created_at`, `updated_at`.

Current account model:

- There is only one account type: `standard`.
- New accounts do not receive or hold prepaid balance.
- Old account state is coerced back to `standard`.

### `user_tile_entitlements`

Stores licenced tiles.

Important columns:

- `user_id`.
- `tile_key`: Example `x075_y149_z001_d001`.
- `quality_mode`: Currently `full` for paid/licenced data.
- `credits_spent`: EUR value assigned to this entitlement row at unlock time.
- `land_km2`, `billable_land_km2`: Backend metadata snapshot at unlock time.
- `source`: `backend_d1`, `stripe_checkout`, etc.
- `unlocked_at`.

Primary key:

- `(user_id, tile_key)`.

Important rule:

- Entitlement is evaluated by tile family `x/y/z` and `d` level. A finer licence covers coarser variants in the same family.

### `credit_ledger`

Financial audit trail.

Important columns:

- `amount_eur`: Amount actually paid for this purchase event.
- `reason`: Examples `stripe_scene_purchase`, `stripe_region_pack_purchase`, `region_pack_no_payment`.
- `metadata_json`: Resolve ID, quality mode, tile count, Stripe session ID, etc.

### `tile_land_stats`

Authoritative pricing metadata in backend D1.

Important columns:

- `tile_key`.
- `x`, `y`, `z`, `d`.
- `land_km2`.
- `billable_land_km2`.
- `free_reason`.
- `updated_at`.

This table is the backend source for pricing. The local `Resources/tile_sizes.sqlite` may contain land metadata for tooling/reference, but Blender runtime pricing must not rely on local SQLite because backend prices/rules may change.

### `tile_commercial_value`

Internal analysis table in `Resources/tile_sizes.sqlite`.

This table stores experimental GeoNames/population-derived commercial value tiers and multipliers. It is kept for future pricing analysis only.

Active public pricing must ignore `tile_commercial_value`. The live formula uses only backend `tile_land_stats.billable_land_km2`, tile `d` detail, free-tile rules, licence coverage, and the region-pack volume discount.

### `pricing_integrity_events`

Records backend pricing metadata problems.

Current critical case:

- `pricing_metadata_missing`: A requested, non-free S2 tile key has no matching backend pricing metadata.

In that case, the affected tile is charged EUR 0.00 and the event is recorded for investigation.

### Stripe Webhook Events

`stripe_webhook_events` stores processed Stripe event IDs so webhooks are idempotent.

## 5. Tile Key and Asset Model

Canonical tile key format:

```text
xNNN_yNNN_zNNN_dNNN
```

Example:

```text
x075_y149_z001_d001
```

Asset files for one tile normally include:

```text
S2/S2_x075_y149_z001_d001.exr
EL/EL_x075_y149_z001_d001.exr
WT/WT_x075_y149_z001_d001.exr
PO/PO_x075_y149_z001_d001.tif
```

`defaultAssetsForTile()` in `credit_routes.js` defines the default asset list.

Special EL alias:

- For `z001_d002`, EL uses the `d001` file internally.
- `isTileUnlockedForUser()` handles this so EL aliasing does not create a separate entitlement problem.

Pricing is always associated with the S2 tile key, not with individual EL/WT/PO support files.

## 6. Land Metadata Generation

Tool:

```text
tools/build_tile_land_stats.py
```

Primary input source:

```text
/Volumes/SSDA/Planetka Assets/S2
```

S2 ocean reference:

```text
Resources/Fallback Images/ocean_pixel_final_20.exr
```

Special Antarctica/Greenland support source:

```text
/Volumes/SSDA/Planetka Assets/WT
```

Rules:

- Every S2 pixel is counted as land unless it matches the S2 ocean fallback RGB value within tolerance `1e-5`.
- Land includes normal land, rivers, lakes, snow/ice, and any non-ocean S2 pixel.
- Ocean-only pixels do not contribute to `land_km2` or `billable_land_km2`.
- For Antarctica tiles (`north edge <= 60°S`) and all Greenland product tiles, the land mask is stricter:
- WT blue (`RGB 0,0,1`) is treated as ocean.
- S2 white pixels (`R >= 1`, `G >= 1`, `B >= 1`) are removed from land, so ice/snow does not become billable land.
- If a special Antarctica/Greenland WT tile is missing, S2 ocean plus S2 white exclusion is used as the fallback and recorded in `source`.
- Latitude no longer makes a tile free by itself.

Area calculation:

- The tool calculates spherical row areas from tile bounds using Earth radius `6371.0088 km`.
- It accumulates land area per scanline using the fraction of non-ocean pixels in that row.
- `billable_land_km2` is equal to `land_km2` unless the tile is globally free by d-level.

Free metadata reasons generated by the tool:

- `d000_global_free`
- `coarse_detail_free`

The local build table contains more metadata fields (`land_fraction`, `paid_lat_fraction`, `source`), but the Worker currently needs only `tile_key`, coordinates, land areas, `free_reason`, and `updated_at`. `paid_lat_fraction` is retained for schema compatibility; it is now `1.0` for paid tiles and `0.0` for globally free tiles because latitude is no longer a free-pricing rule. The `source` value is still useful for audits:

- `S2`: normal S2 ocean-color exclusion.
- `WT_S2_WHITE`: special Antarctica/Greenland WT ocean exclusion plus S2 white exclusion.
- `S2_WHITE_FALLBACK`: special Antarctica/Greenland fallback when matching WT is missing.

## 7. Free Tile Rules

Implemented in `freeReasonForTile()` in `credit_routes.js` and mirrored in `tools/build_tile_land_stats.py`.

A tile is free when any of the following is true:

- Invalid tile key: `invalid_tile_key`.
- `d <= 0`: `d000_global_free`.
- `d >= 60`: `coarse_detail_free`.
- Quality mode is Preview: `preview_quality`.
- Tile is already covered by an existing licence: `already_unlocked` / user-facing `already licenced`.
- Tile is ocean fallback / ocean-only and therefore has `billable_land_km2 = 0`.

Important current rule:

- `z015_d030` is not free just because `z=015`. Only `d >= 060` is coarse-detail free.
- Antarctica and Greenland are not automatically free by latitude. They become free or cheaper only when the WT/S2-white land mask produces zero or low billable land area. High Arctic tiles outside Greenland use the normal S2 ocean-color rule.

## 8. Price Formula

Implemented in `creditsForTileStats()` in `cloudflare-api/src/worker/credit_routes.js`.

Constants:

```js
DATASET_BASE_MPP = 10.0
EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2
FULL_QUALITY_PRICE_COEFFICIENT = 1.20
```

Delivered metres per pixel:

```text
delivered_mpp = 10m * d
```

For `d <= 0`, the internal fallback delivered MPP is `1440`, but `d000` is free anyway.

Base price before detail factor:

```text
base_eur = billable_land_km2 / EQUATOR_Z001_AREA_KM2
```

Detail factor:

```text
quality_factor = (10 / max(10, delivered_mpp)) ^ 2
```

Base gross price before the internal coefficient:

```text
base_gross_price_eur = round_to_cents(base_eur * quality_factor)
```

Final gross price:

```text
gross_price_eur = round_to_cents(base_gross_price_eur * FULL_QUALITY_PRICE_COEFFICIENT)
```

`FULL_QUALITY_PRICE_COEFFICIENT` is an internal global multiplier in `cloudflare-api/src/worker/credit_routes.js`. It is currently `1.20`. Changing it scales all Full Quality scene tile prices, generated tile prices, data-pack gross prices, volume-discounted pack prices, Stripe checkout totals, and map/catalog page prices. It does not change land-area metrics, free-tile rules, entitlement coverage, or volume-discount percentages.

Examples by d-level for the same land area:

- `d001`: full 10 m/px price.
- `d002`: one quarter of `d001` price.
- `d004`: one sixteenth of `d001` price.
- `d060+`: free by rule, not just cheaper.

All backend money output is rounded to cents using `MONEY_SCALE = 100`. The client also rounds all received price fields to two decimals before display and summation, so the UI total matches the visible row prices.

## 9. Region-Pack Volume Discounts

Implemented in `tools/build_region_pack_catalog.py` and exported as static region-pack metadata.

Region-pack discounts are size-based, not category-based. The builder calculates each product's `d001` billable land area and compares it with the `World` product's `d001` billable land area. `d001` is used so the same ground is not double-counted through lower-detail tile levels.

The active discount buckets are:

| Product share of World `d001` billable land | Volume discount |
|---:|---:|
| `< 5%` | `20%` |
| `5% - < 7%` | `25%` |
| `7% - < 10%` | `30%` |
| `10% - < 12.5%` | `35%` |
| `12.5% - < 25%` | `40%` |
| `25% - < 75%` | `45%` |
| `>= 75%` | `50%` |

The World pack is fixed at `50%`.

This creates a non-linear volume curve: small countries remain at the baseline discount, medium/large countries move higher, continent-scale products get materially larger volume discounts, and World remains the maximum-value purchase.

## 10. Licence Cascade and Upgrade Logic

Implemented in `estimateNewCredits()` and `isTileUnlockedForUser()`.

Terminology:

- Smaller `d` means finer texture detail.
- Larger `d` means coarser texture detail.

Family key:

```text
xNNN_yNNN_zNNN
```

A licence for a finer tile covers coarser variants in the same family:

- Licenced `x075_y149_z001_d001` covers `d002`, `d004`, ..., `d060`.
- Licenced `x075_y149_z001_d002` does not cover `d001`.

Upgrade pricing:

- If the user previously licenced a coarser tile and later needs a finer tile in the same family, the backend charges only the difference.
- The existing coarser gross price is reported as `upgrade_credit_applied`.

Example:

```text
Previously licenced: z001_d002 gross price €0.13
New requested:       z001_d001 gross price €0.50
Charge now:          €0.37
```

The estimate response includes both:

- `credits` / `price_eur`: charge now.
- `gross_credits` / `gross_price_eur`: original tile price before entitlement/upgrade deductions.

## 11. Resolve Price Estimation Flow

### Client-side visible tile planning

File:

```text
planetka_runtime/view_telemetry.py
```

Functions:

- `build_resolve_cost_breakdown()`
- `estimate_credits_for_visible_tiles()`
- `_pricing_tiles_for_visible_tiles()`

Flow:

1. Tile selection computes visible tiles for the current Camera View using `tile_utils.main()`.
2. Streaming planning resolves the actual downloadable tile set via `streaming_utils.build_resolve_download_requests_for_visible_tiles()`.
3. Ocean fallback tiles are excluded from pricing with `ocean_tiles` from the download plan.
4. The resulting pricing tile list is sent to the backend `/credits/estimate` endpoint.
5. The UI receives authoritative price rows and combines them with asset sizes for the breakdown popup.

Important UI rule:

- Full Quality is locked to Camera View.
- Active View shows a `Bring Camera` action instead of allowing Full Quality purchase directly.
- Quick Preview prepared state disables Full Quality until Quick Preview is cleared.

### Backend estimate endpoint

Endpoint:

```text
POST /credits/estimate
```

Handler:

```text
handleCreditEstimate() in credit_routes.js
```

Request fields:

```json
{
  "quality_mode": "full",
  "tile_keys": ["x075_y149_z001_d001"]
}
```

Response includes:

- `credits` / `price_eur`: total charge now.
- `paid_tile_count`.
- `free_tile_count`.
- `tile_count`.
- `tiles`: all priced rows.
- `new_tiles`: rows that would create new licences.
- `excluded_tiles`: already licenced rows.
- `integrity_warnings`.
- `metadata_missing_tile_keys`.

## 12. Full Quality Resolve Purchase/Unlock Flow

Primary files:

- `operators.py`
- `streaming_utils.py`
- `r2_source.py`
- `cloudflare-api/src/worker/tile_routes.js`
- `cloudflare-api/src/worker/credit_routes.js`

Direct-payment path:

1. User clicks `Full Quality Textures`.
2. `PLANETKA_OT_SetTextureQualityAndResolve` checks Camera View, Quick Preview state, account, and authoritative price.
3. If price is positive, it opens Stripe scene checkout.
4. If price is zero because all tiles are already licenced/free, it starts `bpy.ops.planetka.load_textures(... texture_quality_mode_override="FULL")`.
5. Streaming creates a resolve request context containing:
   - `resolve_id`
   - `texture_quality_mode = full`
   - `pricing_tiles`
6. `ensure_resolve_pricing_session()` posts to `/tiles/session` with:

```json
{
  "resolve_id": "...",
  "quality_mode": "full",
  "credit_protocol": "land_credits_v1",
  "tile_keys": ["..."]
}
```

7. Backend calls `unlockTilesForSession()` before issuing the tile token.
8. If all required Full Quality tiles are already licenced/free, backend returns a short-lived tile token.
9. Subsequent R2 tile GETs include `X-Planetka-Tile-Token` and are allowed only if the tile is free or licenced.

Payment rule:

- Paid Full Quality scene/data-pack purchases go through direct Stripe Checkout.
- `/tiles/session` does not deduct money. It only verifies that requested Full Quality tiles are already licenced/free.
- Preview and already-free/already-licenced Full Quality resolves do not require payment.

## 13. Stripe Checkout Flow

Primary files:

- `operators.py`
- `credit_api.py`
- `cloudflare-api/src/worker/credit_routes.js`
- `cloudflare-api/src/worker/billing_handlers.js`

Checkout endpoint:

```text
POST /credits/checkout
```

Supported options:

- `scene`: Pay current Full Quality scene price with scene-specific payment policy applied.
- `region_pack` / `broader_pack`: Pay exact current user-specific data-pack price.
- `animation`: Pay the current dynamic Full Quality animation price with animation segment policy applied.

### Scene Purchase

Request:

```json
{
  "option": "scene",
  "quality_mode": "full",
  "tile_keys": ["x075_y149_z001_d001"]
}
```

Backend behavior:

1. Recalculates the scene price authoritatively in D1.
2. Applies scene-specific payment policy after all existing-licence and partial-licence deductions.
3. If the post-deduction tile price is `0`, it unlocks any free/no-charge tiles immediately and returns `no_payment_required: true`.
4. If the post-deduction tile price is below `€0.50`, it licences the scene at no charge and returns `no_payment_required: true`.
5. If the post-deduction tile price is `€0.50` or higher, it adds the `€1.50` `Custom scene-specific licence` line item into the Checkout amount. Minimum direct scene payment is therefore `€2.00`.
6. For paid scenes, creates a Stripe Checkout Session with product name `Planetka Custom Scene-Specific Licence`.
7. Metadata includes:
   - `planetka_purchase_type = scene_tiles`
   - `planetka_user_id`
   - `planetka_email`
   - `planetka_quality_mode = full`
   - `planetka_tile_keys_json`
   - `planetka_price_eur`
   - `planetka_scene_tile_price_eur`
   - `planetka_custom_scene_licence_eur`
   - `planetka_scene_payable_eur`
   - `planetka_paid_tile_count`

Webhook behavior:

1. `/stripe/webhook` verifies Stripe signature.
2. `checkout.session.completed` is idempotently claimed in `stripe_webhook_events`.
3. For `scene_tiles`, it calls `grantPaidSceneTileEntitlements()`.
4. Entitlements are inserted with source `stripe_checkout`.
5. A ledger row is added with reason `stripe_scene_purchase` and metadata containing nominal/paid EUR.
6. No user balance exists or changes.

After returning to Blender:

- The client monitors the scene price.
- Once backend estimate returns `€0.00`, it automatically starts the Full Quality resolve for the Camera View.

### Removed Payment Surfaces

Planetka currently does not use prepaid balance, monthly billing, or Standard/Balanced unlock purchases. Unsupported checkout options are rejected; the only customer payment path is direct Stripe Checkout for scene-specific Full Quality data, dynamic animation Full Quality data, or Full Quality data packs.

## 14. Animation Render Pricing Flow

Primary files:

```text
animation_tools.py
credit_api.py
cloudflare-api/src/worker/credit_routes.js
cloudflare-api/src/worker/billing_handlers.js
```

Important functions:

- `_plan_animation_segments()`
- `_unique_tiles_for_segments()`
- `update_animation_credit_estimate()`
- `_build_animation_credit_breakdown()`
- `_unlock_animation_tiles_before_download()`
- `_start_animation_data_preload()`

User-facing workflow:

1. Camera keyframes/animation segment plan are generated.
2. Planetka calculates all Full Quality tiles needed by all time segments.
3. It asks the backend for an authoritative price for the unique tile set.
4. Client-side animation pricing uses the authoritative per-tile rows from `/credits/estimate`, not the scene-level `credits` field, because scene-level estimates include the still-scene custom licence policy.
5. UI displays:
   - New Tiles to be Licenced and Downloaded.
   - Full Quality tile price.
   - Custom animation licence total, if any.
   - Final price.
   - Details popup with per-segment tile rows.
6. If the price is positive, UI shows `Buy Animation (€X.XX)`.
7. `planetka.animation_checkout` sends the segment tile plan to `POST /credits/checkout` with `option = animation`.
8. Backend recalculates the animation price from authoritative D1 pricing rows, stores the full segment/pricing snapshot in `animation_checkout_sessions`, and creates a Stripe Checkout Session carrying only the short `planetka_animation_checkout_id` metadata value.
9. Stripe webhook and the payment-success page both call `grantPaidAnimationTileEntitlements()` idempotently for `planetka_purchase_type = animation_tiles`.
10. Entitlements are inserted with source `stripe_animation` or `animation_segment_small_free`.
11. Blender monitors the animation price after opening Checkout; once the estimate returns `€0.00`, the UI is ready for `Render Animation (€0.00)`.
12. Before frame rendering starts, Planetka verifies the already-licenced Full Quality tiles, pre-downloads all required texture files into cache, and then renders segment-by-segment.
13. If the user cancels or Blender crashes after payment, the licenced tiles remain licenced and can be reused later without extra charge.

Animation breakdown rule:

- Each tile is charged once across the full animation.
- Later segments using the same tile show `€0.00` with reason `already counted in an earlier animation segment`.
- Tiles licenced before the render show `€0.00` with reason `already licenced before this render`.
- Each animation segment has its own post-deduction tile value.
- If a segment's new tile value is below `€0.50`, that segment is licenced at no charge.
- If a segment's new tile value is greater than `€0.50`, charge the segment tile value and add a `€1.00` `Custom animation licence` fee for that segment.
- Segments at exactly `€0.50` charge the tile value but do not add the custom animation licence fee.
- Final animation price is:

```text
sum(payable segment Full Quality tile prices after small-segment waivers)
+ (number of segments with new tile value > €0.50 * €1.00)
```

Important implementation rule:

- Stripe metadata is not the animation pricing authority and must not contain the full tile/segment plan. It carries only `planetka_animation_checkout_id`; the backend loads the frozen authoritative record from `animation_checkout_sessions` during webhook/payment-success processing.

## 15. Downloading Licenced Tiles and Local Source

Primary file:

```text
credit_api.py
```

Features:

- `GET /credits/unlocked` returns licenced tile rows and default asset lists.
- User can download licenced tiles to a chosen Local Source folder.
- Download ranges currently include Today, This Week, This Month, and All Data.
- Download progress is tracked separately from Resolve download progress.
- Downloaded assets are not meant to create additional charges because they are tied to already licenced tile keys.

Local Source behavior:

- Local Source is searched before cloud download.
- Local files are used directly when valid.
- If cloud data is newer or local metadata is stale, the user should be notified to re-download, without being charged again.

## 16. Preview Fair-Usage Separation

Preview quality is free, but backend telemetry tracks it separately from Full Quality.

Primary tables:

- `tile_request_rollup_hourly_account_quality`
- `tile_request_rollup_daily_account_quality`
- `preview_usage_hourly_account`

Rules:

- Preview usage monitoring counts only successful `GET` requests with effective quality mode `preview`.
- Full Quality/licenced traffic is not part of Preview fair-usage limits.
- Current strict fair-usage thresholds are alert-only unless explicitly changed to enforce holds.
- Preview fair-usage hold state is separate from hard account block.

Tile route behavior:

- Preview fair-usage hold blocks Preview tile-session creation.
- Preview fair-usage hold also blocks Preview tile GETs even if an old tile session token exists.
- Full Quality licenced data remains available while Preview is on hold.

## 17. Pricing Integrity and Failure Rules

### Backend unavailable on client

If `/credits/estimate` fails or returns an incomplete response, `credit_api.py` returns a non-authoritative zero-price payload:

```text
authoritative = False
pricing_source = backend_unavailable | backend_rejected | backend_incomplete
credits = 0.0
```

The Full Quality UI must not treat this as a valid free purchase. For paid modes, UI and animation code require `authoritative = True`.

### Missing backend pricing metadata

If a requested non-free tile is missing from `tile_land_stats`:

- Backend prices it as `€0.00`.
- `free_reason = pricing_metadata_missing`.
- `pricing_integrity_events` row is written.
- Worker logs `planetka_pricing_metadata_missing`.

This prevents overcharging while making the data problem visible.

Expected state for production:

- `pricing_integrity_events` should normally stay at zero.
- R2 S2 tile keys and D1 `tile_land_stats` rows should match exactly.

### Ocean fallback tiles

The client excludes tiles listed as `ocean_tiles` by the streaming plan from the pricing tile list. Ocean fallback assets should not contribute to price.

### S2 required, support files fallback

S2 is the paid/detail base. Missing EL/WT/PO support files can fall back when the tile is not expected in the database; they should not create pricing failures. Missing required S2 data is a separate resolve/data availability problem.

## 18. Analytics and Admin Controls

Relevant backend/admin behavior:

- Analytics user list includes paid EUR, unlocked tile count, paid Full Quality resolve count, licenced download totals, Preview usage, and Full Quality usage.
- Account plans and unrestricted modes are deprecated/removed from the pricing model.

## 19. Validation and Test Coverage

Primary live pricing E2E test:

```text
tools/planetka_land_credit_live_e2e.py
```

Covered cases:

- Preview resolve is free and does not create entitlement.
- Same-family entitlement cascade and upgrade difference.
- `d >= 060` tiles are free.
- Full Quality new tile charges once.
- Repeat Full Quality resolve is free.
- Paid Full Quality tiles cannot stream until a direct Stripe purchase has created entitlements.
- Animation estimate matches segment unlocking.

Recommended checks before release or after pricing changes:

```bash
python3 tools/planetka_land_credit_live_e2e.py --report /tmp/planetka_land_credit_live_e2e.json
python3 -m compileall -q .
node --check cloudflare-api/src/worker/credit_routes.js
node --check cloudflare-api/src/worker/billing_handlers.js
node --check cloudflare-api/src/index.js
git diff --check
```

Recommended D1 integrity checks:

```sql
SELECT COUNT(*) AS pricing_integrity_events FROM pricing_integrity_events;
SELECT COUNT(*) AS tile_land_stats_rows FROM tile_land_stats;
SELECT free_reason, COUNT(*) FROM tile_land_stats GROUP BY free_reason ORDER BY free_reason;
```

R2/D1 metadata alignment should be checked after any dataset update:

- Every S2 object in R2 should have a `tile_land_stats` row.
- Every `tile_land_stats` row should correspond to an S2 object in R2.

## 20. Operational Rules for Future Changes

Do not violate these invariants:

- Do not reintroduce local client pricing as authoritative.
- Do not charge for missing pricing metadata.
- Do not charge Preview quality.
- Do not charge `d >= 060` tiles.
- Do not allow Full Quality tile GETs for unlicenced non-free tiles under the `land_credits_v1` protocol.
- Do not allow paid Full Quality tile streaming before Stripe checkout has created the required entitlements.
- Do not silently change price formula constants without regenerating/revalidating backend pricing behavior and updating this document.
- Do not count Full Quality/licenced traffic into Preview fair-usage enforcement.
- Do not use Stripe Checkout metadata as the pricing authority; webhook processing must re-evaluate/grant using backend logic.

## 21. File/Function Map

Backend pricing:

- `cloudflare-api/src/worker/credit_routes.js`
- `creditsForTileStats()`
- `estimateNewCredits()`
- `unlockTilesForSession()`
- `grantPaidSceneTileEntitlements()`
- `handleCreditEstimate()`
- `handleCreditCheckout()`
- `handleCreditUnlocked()`

Tile access enforcement:

- `cloudflare-api/src/worker/tile_routes.js`
- `handleTileSessionStart()`
- `handleTileRequest()`
- `isTileUnlockedForUser()`

Stripe:

- `cloudflare-api/src/worker/billing_handlers.js`
- `handleStripeWebhook()`
- `claimStripeWebhookEvent()`
- `grantPaidSceneTileEntitlements()`

Blender client API:

- `credit_api.py`
- `estimate_credits_for_tiles()`
- `estimate_credit_breakdown_for_tiles()`
- `create_checkout_session()`
- `get_credit_account()`
- `get_unlocked_tiles()`

Resolve UI and action flow:

- `operators.py`
- `PLANETKA_OT_SetTextureQualityAndResolve`
- `PLANETKA_OT_OpenCreditCheckout`
- `PLANETKA_OT_DataCostBreakdown`
- `ui.py`

Camera View cost breakdown:

- `planetka_runtime/view_telemetry.py`
- `build_resolve_cost_breakdown()`
- `estimate_credits_for_visible_tiles()`
- `update_resolve_size_estimates()`

Animation pricing:

- `animation_tools.py`
- `update_animation_credit_estimate()`
- `_build_animation_credit_breakdown()`
- `_unlock_animation_tiles_before_download()`
- `_start_animation_data_preload()`
- `PLANETKA_OT_AnimationRenderCostBreakdown`

Metadata build:

- `tools/build_tile_land_stats.py`
- `tools/build_tile_commercial_value.py` for inactive internal commercial-value analysis only.

Live E2E verification:

- `tools/planetka_land_credit_live_e2e.py`
