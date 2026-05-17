# Planetka Internal Pricing System Reference

This document describes the current Planetka pricing system from a technical point of view. It is an internal implementation reference, not public legal text.

Last updated: 2026-05-15

## 1. Current Product Model

Planetka currently has two customer-facing texture access modes:

- `Preview`: free streaming quality for browsing, tests, and preview work.
- `Full Quality`: paid/licenced texture data with commercial licence included for the licenced data.

The removed or inactive models are intentionally not part of the current customer flow:

- No prepaid balance.
- No monthly billing.
- No Standard/Balanced paid unlock.
- No account tier that changes pricing.
- No client-side authoritative pricing.

The live model is simple:

```text
Price is calculated by backend -> user pays direct Stripe Checkout -> backend grants tile entitlements -> user can reuse/download those tiles later without paying again.
```

## 2. Core Pricing Principles

The current pricing system is built around these invariants:

- Full Quality pricing is backend-authoritative.
- The Blender client may display estimates, but the backend recalculates before any payment or entitlement grant.
- Users pay only for newly licenced Full Quality tile coverage.
- A finer tile licence covers coarser tiles in the same tile family.
- A coarser tile licence gives upgrade credit when the user later buys a finer tile in the same tile family.
- Scene-specific purchases and animation purchases are direct Stripe payments.
- Region/data-pack purchases are direct Stripe payments.
- Region/data-pack gross totals are static generated catalog values, then adjusted at request time by the live pricing settings and user entitlements.
- Missing pricing metadata must never overcharge users; affected tiles are priced at `€0.00` and logged as integrity events.
- Preview telemetry and Full Quality/licenced telemetry are separate products operationally.

## 3. User-Facing Terms

Use these terms consistently in UI and web pages:

- `Preview`: free lower-detail streaming.
- `Full Quality`: paid/licenced high-detail texture data.
- `Relevant Data Packs`: data-pack suggestions for the current view.
- `Licenced`: tile data already paid for, granted, or covered by World entitlement.
- `Full Price`: price before user-specific entitlement deductions and volume discount.
- `Already Licenced`: value deducted because the user already owns equivalent/finer tiles.
- `Partially Licenced`: value deducted because the user owns a coarser tile in the same family and is paying only the upgrade difference.
- `Volume Discount`: data-pack percentage discount applied after entitlement deductions.
- `Final Price`: actual amount due now.

Historical API fields still use `credits`. In the current implementation, `credits` means EUR price/charge, not user-held balance.

## 4. Authoritative Components

### Backend Worker

Primary files:

- `cloudflare-api/src/worker/credit_routes.js`
- `cloudflare-api/src/worker/tile_routes.js`
- `cloudflare-api/src/worker/billing_handlers.js`
- `cloudflare-api/src/worker/admin_analytics_handlers.js`

The Worker is authoritative for:

- Runtime pricing settings.
- Tile land metadata lookup.
- Full Quality price calculation.
- Existing entitlement and partial-upgrade deductions.
- Region/data-pack volume discounts.
- Stripe Checkout session creation.
- Stripe webhook processing.
- Purchase history and ledger records.
- Full Quality tile access enforcement.
- Preview fair-usage telemetry and alerting.

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

- Computing visible/pricing tile candidates for Camera View or animation segments.
- Asking the backend for authoritative EUR estimates.
- Displaying price, size, and breakdown information.
- Opening Stripe Checkout or no-payment unlock flows.
- Waiting until backend entitlements are visible after payment.
- Downloading licenced assets from Cloudflare R2 or Local Source.

The client must not calculate final charge locally.

## 5. Runtime Pricing Settings

Runtime pricing settings are stored in D1 `app_settings` and managed in Analytics -> Product Pricing.

Table:

```sql
app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by_user_id TEXT
)
```

Current setting keys:

- `full_quality_price_coefficient`
- `region_pack_discount_min_percent`
- `region_pack_discount_max_percent`
- `region_pack_discount_share_buckets_json`
- `custom_scene_licence_fee_eur`
- `custom_animation_licence_fee_eur`
- `region_pack_discount_override:<product_id>`

Defaults in `credit_routes.js`:

```js
DEFAULT_FULL_QUALITY_PRICE_COEFFICIENT = 5.00
DEFAULT_REGION_PACK_DISCOUNT_MIN_PERCENT = 0
DEFAULT_REGION_PACK_DISCOUNT_MAX_PERCENT = 75
DEFAULT_SCENE_CUSTOM_LICENCE_FEE_EUR = 1.50
DEFAULT_ANIMATION_CUSTOM_LICENCE_FEE_EUR = 4.50
SCENE_SMALL_FREE_THRESHOLD_CENTS = 50
```

Important runtime behavior:

- `getRuntimePricingSettings()` loads settings from D1.
- `ensureRuntimePricingSettings()` is called before public pricing/checkout routes.
- Worker isolates cache settings briefly with `PRICING_SETTINGS_CACHE_TTL_MS = 30 seconds`.
- Saving pricing settings invalidates pricing caches.
- Pricing cache keys include coefficient, discount range, discount buckets, custom fees, and product overrides.

## 6. Price Coefficient Semantics

The Analytics-facing `Price coefficient` is defined as:

```text
coefficient 1.00 = €1.00 per 10,000 km² at d001 / 10 m per pixel, before free rules, licence deductions, custom scene/animation fees, and pack discounts.
```

Current default:

```text
coefficient = 5.00
```

That means:

```text
d001 gross base = €5.00 per 10,000 km² of billable land
```

Generated data-pack catalogs store static coefficient-1.0 gross prices from the older base:

```js
EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2
```

To keep generated catalog files static while changing the meaning of the public coefficient, the Worker converts the public coefficient to an internal generated-catalog multiplier:

```js
PUBLIC_COEFFICIENT_TO_LEGACY_GROSS_MULTIPLIER = EQUATOR_Z001_AREA_KM2 / 10000
internal_multiplier = public_coefficient * PUBLIC_COEFFICIENT_TO_LEGACY_GROSS_MULTIPLIER
```

This is why data-pack prices can update instantly without rebuilding the generated catalog.

Do not add a separate `price per 10,000 km²` setting. The coefficient is the single global tile-price control.

## 7. Tile Land Metadata

Authoritative backend table:

```sql
tile_land_stats (
  tile_key TEXT PRIMARY KEY,
  x INTEGER NOT NULL,
  y INTEGER NOT NULL,
  z INTEGER NOT NULL,
  d INTEGER NOT NULL,
  land_km2 REAL NOT NULL DEFAULT 0,
  billable_land_km2 REAL NOT NULL DEFAULT 0,
  free_reason TEXT,
  updated_at TEXT NOT NULL
)
```

Generated by:

```text
tools/build_tile_land_stats.py
```

Primary texture source:

```text
/Volumes/SSDA/Planetka Assets/S2
```

Normal land/ocean rule:

- S2 ocean fallback pixels are excluded from land.
- Non-ocean S2 pixels count as land.
- `billable_land_km2` is normally equal to `land_km2`, unless the tile is globally free.

Antarctica and Greenland rule:

- Latitude itself no longer makes tiles free.
- For Antarctica and Greenland, WT and S2-white masking removes ocean/ice areas from billable land.
- Pure white S2 pixels are removed from land for these special areas.
- This makes most Antarctica/Greenland ice tiles free or very cheap because their billable land becomes zero or low.

Free metadata reasons generated by tooling include:

- `d000_global_free`
- `coarse_detail_free`

## 8. Free Tile Rules

Implemented in `freeReasonForTile()` and pricing metadata generation.

A tile is free when:

- It is invalid or non-priceable.
- `d <= 0` (`d000_global_free`).
- `d >= 60` (`coarse_detail_free`).
- It is Preview quality (`preview_quality`).
- It has `billable_land_km2 = 0`.
- It is already covered by the user's existing Full Quality licence.
- The user has World Full Quality unlocked.
- Backend pricing metadata is missing; this is not a valid expected free case, but it is priced at `€0.00` to avoid overcharging and logged as an integrity event.

Important current rules:

- High latitude is not a free rule.
- `z015_d030` is not automatically free.
- Only `d >= 060` is coarse-detail free.
- Ocean fallback tiles should be excluded from pricing candidates before reaching checkout.

## 9. Scene Tile Price Formula

Implemented in `creditsForTileStats()`.

Constants:

```js
DATASET_BASE_MPP = 10.0
EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2
```

Delivered metres per pixel:

```text
delivered_mpp = 10 * d
```

Base land price before detail factor:

```text
base_eur = billable_land_km2 / EQUATOR_Z001_AREA_KM2
```

Detail factor:

```text
quality_factor = (10 / max(10, delivered_mpp)) ^ 2
```

Coefficient-1.0 generated gross before public coefficient conversion:

```text
base_gross_eur = round_to_cents(base_eur * quality_factor)
```

Final current gross price:

```text
final_gross_eur = round_to_cents(base_gross_eur * internal_multiplier)
```

Because `internal_multiplier = public_coefficient * EQUATOR_Z001_AREA_KM2 / 10000`, the practical d001 meaning is:

```text
d001 gross = billable_land_km2 / 10000 * public_coefficient
```

Examples at coefficient `1.00`:

- `10,000 km²` at `d001` -> `€1.00` before deductions/discounts.
- `10,000 km²` at `d002` -> about `€0.25` before rounding/deductions.
- `10,000 km²` at `d004` -> about `€0.06` before rounding/deductions.

Examples at coefficient `5.00`:

- `10,000 km²` at `d001` -> `€5.00` before deductions/discounts.
- `10,000 km²` at `d002` -> about `€1.25` before rounding/deductions.
- `10,000 km²` at `d004` -> about `€0.31` before rounding/deductions.

All displayed prices must use two decimals. The backend rounds monetary values to cents with `MONEY_SCALE = 100`.

## 10. Entitlements, Families, and Partial Upgrades

Canonical tile key:

```text
xNNN_yNNN_zNNN_dNNN
```

Tile family:

```text
xNNN_yNNN_zNNN
```

Important rule:

```text
smaller d = finer texture detail
larger d = coarser texture detail
```

Coverage rule:

- A licenced finer tile covers coarser variants in the same family.
- A licenced coarser tile does not cover finer variants.

Examples:

```text
Licenced x075_y149_z001_d001 covers d002, d004, d008, ...
Licenced x075_y149_z001_d002 does not cover d001.
```

Partial upgrade rule:

```text
charge_now = finer_gross_price - best_existing_coarser_gross_price
```

Example:

```text
Existing coarser licence: d002 gross €0.13
New requested finer tile: d001 gross €0.50
Upgrade charge: €0.37
```

Estimate fields:

- `gross_price_eur`: full tile price before entitlement deductions.
- `price_eur`: charge now.
- `upgrade_credit_applied`: amount deducted because of existing coarser licence.
- `partially_licenced`: true when an upgrade credit is applied and a positive upgrade price remains.

Map colors:

- Red: new in this pack/purchase.
- Yellow: partially licenced, upgrade price only.
- Green: already licenced.
- Grey: free/not charged.

## 11. Main Data Tables

### `user_credit_accounts`

Despite the historical name, this table is not a prepaid balance table in the current model.

Important columns:

- `user_id`
- `account_type`: retained as a compatibility column and coerced to `account`.
- `world_full_quality_unlocked_at`
- `world_full_quality_checkout_session_id`
- `world_full_quality_paid_eur`
- `pricing_version`
- `created_at`
- `updated_at`

`pricing_version` is incremented when entitlements change. It invalidates user-specific pricing caches.

### `user_tile_entitlements`

Stores licenced Full Quality tiles.

Important columns:

- `user_id`
- `tile_key`
- `quality_mode`
- `credits_spent`: EUR value of this entitlement row.
- `land_km2`
- `billable_land_km2`
- `source`
- `unlocked_at`

Primary key:

```sql
(user_id, tile_key)
```

### `user_entitlement_summaries`

Compact per-user entitlement summary cache.

Purpose:

- Avoid repeatedly loading thousands of entitlement rows for region-pack price estimates.
- Versioned by account entitlement state.
- Invalidated when entitlements or pricing version change.

### `credit_ledger`

Financial audit trail.

Important columns:

- `amount_eur`
- `reason`
- `metadata_json`
- `created_at`

Examples of `reason`:

- `stripe_scene_purchase`
- `stripe_animation_purchase`
- `stripe_region_pack_purchase`
- `region_pack_no_payment`

### `purchase_history`

User-facing/admin purchase history summary.

Important columns:

- `purchase_type`
- `stripe_session_id`
- `amount_paid_eur`
- `nominal_eur`
- `gross_eur`
- `discount_eur`
- `discount_percent`
- `region_pack_id`
- `region_pack_name`
- `tile_count_total`
- `tile_count_new`
- `tile_count_already_licenced`
- `metadata_json`

There is a unique index on `stripe_session_id` for idempotency.

### `purchase_history_tiles`

Per-tile purchase detail for scene/animation and when needed for audit.

Important columns:

- `purchase_id`
- `tile_key`
- `tile_status`
- `price_eur`
- `gross_price_eur`
- `land_km2`
- `billable_land_km2`
- `quality_mode`

### `pricing_integrity_events`

Records pricing metadata failures such as missing backend metadata.

Expected production state:

```text
COUNT(*) should normally be 0 or investigated quickly.
```

### `user_product_quotes`

Planned materialized data-pack pricing source of truth.

Primary key:

```sql
(user_id, product_id, catalog_version)
```

Important columns:

- `quote_id`: stable quote identifier used by pages and checkout.
- `status`: `ready`, `stale`, `recalculating`, or `error`.
- `pricing_version`: runtime pricing-settings version/hash.
- `entitlement_version`: user entitlement version.
- `full_price_cents`
- `already_licenced_cents`
- `partial_licence_credit_cents`
- `discount_percent`
- `discount_cents`
- `final_price_cents`
- tile-count fields used by catalog/map UI.
- `summary_json`: complete top-line quote payload.
- `map_state_status` / `map_state_json`: optional precomputed map overlay state.

This table is intended to replace request-time data-pack quote calculation for
catalog pages, data-pack pages, Relevant Data Packs, Similar Options, and
Stripe data-pack checkout.

### `user_product_quote_batches`

Groups recalculation jobs caused by a single trigger such as a successful
purchase or pricing-settings change.

Important columns:

- `user_id`
- `trigger_type`
- `trigger_purchase_id`
- `source_product_id`
- `pricing_version`
- `entitlement_version`
- `catalog_version`
- `status`
- job counters.

### `user_product_quote_jobs`

Serialized queue of small data-pack quote recalculation jobs.

Important columns:

- `batch_id`
- `user_id`
- `product_id`
- `source_product_id`
- `job_round`
- `priority`
- `status`: `queued`, `running`, `done`, `failed`, or `cancelled`.
- `attempts`
- lock fields.

The queue order must prioritize lower `job_round` globally before higher
rounds. This is what prevents one large purchase recalculation from blocking
round-one updates from a newer purchase.

### `user_product_quote_job_locks`

Global lock table for quote processing.

Purpose:

```text
Guarantee only one data-pack quote recalculation job runs at a time.
```

## 12. Price Estimate Endpoint

Endpoint:

```text
POST /credits/estimate
```

Handler:

```text
handleCreditEstimate() in credit_routes.js
```

Typical scene request:

```json
{
  "quality_mode": "full",
  "pricing_context": "scene",
  "tile_keys": ["x075_y149_z001_d001"]
}
```

Typical animation request:

```json
{
  "quality_mode": "full",
  "pricing_context": "animation",
  "tile_keys": ["x075_y149_z001_d001", "x076_y149_z001_d001"]
}
```

Response includes:

- `credits` / `price_eur`: final public payable amount for the requested context.
- `raw_credits` / `raw_price_eur`: raw tile amount before scene/animation custom licence policy.
- `scene_tile_price_eur` or `animation_tile_price_eur`: tile subtotal after entitlement deductions.
- `custom_scene_licence_eur` or `custom_animation_licence_eur`: custom licence fee applied if applicable.
- `scene_small_free_threshold_applied` / `animation_small_free_threshold_applied`.
- `tiles`: priced tile rows.
- `new_tiles`: rows that would create or upgrade entitlements.
- `excluded_tiles`: already covered tiles.
- `partial_licence_tile_count`.
- `partial_licence_credit_eur`.
- `integrity_warnings`.
- `metadata_missing_tile_keys`.

Important:

- `/credits/estimate` applies the scene or animation custom licence policy only to the public total.
- Tile rows still expose per-tile gross/current price for detailed breakdowns.

## 13. Scene-Specific Purchase Policy

Scene purchase uses direct Stripe Checkout.

Endpoint:

```text
POST /credits/checkout
```

Request:

```json
{
  "option": "scene",
  "quality_mode": "full",
  "tile_keys": ["x075_y149_z001_d001"]
}
```

Backend flow:

1. Recalculate current tile price with `estimateNewCredits()`.
2. Apply entitlement and partial-upgrade deductions.
3. Apply scene custom licence policy with `scenePaymentPolicyForEstimate()`.
4. If final payable is `€0.00`, unlock no-payment/free tiles immediately.
5. If payable is positive, create Stripe Checkout.
6. Stripe webhook grants entitlements after successful payment.
7. Blender monitors price until it becomes `€0.00`, then starts Full Quality resolve.

Policy:

```text
if post-deduction tile price is 0:
  payable = 0
elif post-deduction tile price is below €0.50:
  payable = 0
  tiles are licenced at no charge
else:
  payable = post-deduction tile price + Custom scene-specific licence fee
```

Current default:

```text
Custom scene-specific licence fee = €1.50
Small scene free threshold = below €0.50
Minimum paid scene checkout = €2.00
```

The scene fee is configurable in Analytics -> Product Pricing.

Stripe product name:

```text
Planetka Custom Scene-Specific Licence
```

Stripe metadata includes:

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

Webhook grant function:

```text
grantPaidSceneTileEntitlements()
```

## 14. Animation Purchase Policy

Animation uses the same tile entitlement model as scene purchases.

Primary client flow:

1. Animation tools create a segment plan.
2. Client builds the unique set of all Full Quality tile keys needed by all segments.
3. Client asks `/credits/estimate` with `pricing_context = animation`.
4. Backend calculates one price for the unique tile set.
5. Backend applies animation custom licence policy.
6. Client opens Stripe Checkout if payable is positive.
7. Stripe webhook grants entitlements to all newly licenced animation tiles.
8. Blender waits until estimate becomes `€0.00`, then preloads Full Quality data before rendering.

Current policy:

```text
if post-deduction unique animation tile price is 0:
  payable = 0
elif post-deduction unique animation tile price is below €0.50:
  payable = 0
  tiles are licenced at no charge
else:
  payable = post-deduction unique animation tile price + Custom animation licence fee
```

Current default:

```text
Custom animation licence fee = €4.50
Small animation free threshold = below €0.50
Minimum paid animation checkout = €5.00
```

The animation fee is configurable in Analytics -> Product Pricing.

Important implementation details:

- Animation checkout currently sends unique tile keys, not the full heavy segment pricing snapshot.
- `create_animation_checkout_session()` posts `option = animation`, `tile_keys`, and `segment_count`.
- Backend limits animation checkout to `ANIMATION_CHECKOUT_MAX_UNIQUE_TILES = 5000`.
- Backend stores a short-lived scene/detail token for the tile set and passes token metadata to Stripe.
- Webhook resolves the token and grants the tile entitlements.
- The segment plan is used for user-facing breakdown only; entitlement purchase is by unique tile set.

Stripe product name:

```text
Planetka Custom Animation Licence
```

Stripe metadata includes:

- `planetka_purchase_type = animation_tiles`
- `planetka_tile_set_token`
- `planetka_raw_tile_price_eur`
- `planetka_animation_tile_price_eur`
- `planetka_custom_animation_licence_eur`
- `planetka_custom_animation_licence_fee_eur`
- `planetka_segment_count`

Webhook grant path:

```text
applyStripeCreditPurchaseFromSession()
-> checkoutTileKeysFromMetadata()
-> grantPaidSceneTileEntitlements(... purchaseType: "animation_tiles", customLicenceCents: customAnimationLicenceCents())
```

## 15. Region/Data-Pack Catalog

Generated by:

```text
tools/build_region_pack_catalog.py
```

Generated Worker product file:

```text
cloudflare-api/src/worker/region_packs.products.generated.js
```

Each product contains static catalog metadata:

- `id`
- `name`
- `type`
- `tile_count`
- `paid_tile_count`
- `free_tile_count`
- `licensable_tile_count`
- `gross_cents` / `gross_eur` at coefficient-1.0 generated base.
- `volume_discount_basis.world_land_share`
- `countries` / `adm0_codes` / `adm1_codes`

The large generated tile-membership file is intentionally not imported by the
production Worker:

```text
cloudflare-api/src/worker/region_packs.tile_data.generated.js
```

That file is used by offline tooling to seed D1 and build map assets. Runtime
pack pricing reads exact product tile rows from D1:

```text
region_pack_tile_entries
```

The table stores one row per `(catalog_version, region_pack_id, tile_key)` with
the tile family, parsed coordinates, coefficient-1.0 base gross cents, and the
global-free flag. This keeps large packs such as World and Asia out of the
Worker JavaScript bundle while preserving exact per-tile pricing and entitlement
deductions.

Runtime region/data-pack pricing does not recalculate gross pack price from
polygons on every request. It reads D1 tile rows and applies:

1. Current price coefficient.
2. Current user entitlement deductions.
3. Current volume discount or product override.

This keeps pack estimates fast and consistent across Blender, map pages, catalog pages, and Stripe Checkout.

## 16. Region/Data-Pack Price Breakdown

For any data pack, user-facing breakdown must follow this order:

```text
New Tiles / Total Tiles
Full Price
Already Licenced - N tiles (-€X.XX)
Volume Discount - P% (-€Y.YY)
Final Price
```

For partially licenced tiles, the partial-upgrade value is included in the already-licenced deduction value. Detailed hover/breakdown can call it `Partially licenced` where useful.

Do not show zero-value deduction rows. If a deduction does not affect price, omit it.

Definitions:

- `Full Price`: gross pack price with current coefficient, before user deductions and volume discount.
- `Already Licenced`: gross value already covered by the user's entitlements, including partial-upgrade credits.
- `Volume Discount`: discount applied to the remaining chargeable amount after user entitlement deductions.
- `Final Price`: actual amount due now.

Formula:

```text
chargeable_before_discount = full_price - already_licenced_value - partial_licence_credit
volume_discount_value = chargeable_before_discount * effective_discount_percent
final_price = chargeable_before_discount - volume_discount_value
```

All values are rounded to cents.

## 17. Region/Data-Pack Discount System

Runtime discount settings:

```text
min discount percent = default 0
max discount percent = default 75
```

Default discount buckets:

| Product share of World d001 billable land | Ratio of min-to-max range |
|---:|---:|
| `>= 40%` | `100%` |
| `>= 20%` | `5/6` |
| `>= 10%` | `4/6` |
| `>= 5%` | `3/6` |
| `>= 2.5%` | `2/6` |
| `>= 1.25%` | `1/6` |
| `< 1.25%` | minimum discount |

Calculation:

```text
default_discount = round_to_nearest_5(min_discount + ((max_discount - min_discount) * bucket_ratio))
```

World product rule:

```text
World always uses max_discount unless manually overridden.
```

Per-product override:

- Stored as `region_pack_discount_override:<product_id>` in `app_settings`.
- Valid range `0%` to `100%`.
- Overrides default bucket discount completely.
- Used for product-specific promotions, including temporary free country/product offers.

Admin page:

```text
/admin/analytics/products
```

Supports:

- Editing price coefficient.
- Editing discount min/max.
- Editing bucket thresholds/ratios.
- Editing custom scene and animation fees.
- Editing per-product discount overrides.
- Sorting product pricing table.
- Viewing `% of land`, full price, discount, and final price.

## 18. Region/Data-Pack Purchase Flow

Blender region/data-pack checkout request:

```json
{
  "option": "region_pack",
  "region_pack_id": "italy"
}
```

Current backend behavior:

1. `POST /credits/checkout` does not immediately create Stripe Checkout for region packs.
2. It creates a short-lived detail token.
3. It returns a browser `checkout_url` for `/credits/region-pack-checkout`.
4. The browser page recalculates current user-specific price authoritatively.
5. User clicks Buy/Checkout on the web page.
6. Backend creates Stripe Checkout for the current final price.
7. Stripe webhook grants all new pack entitlements.
8. Payment-success page shows the purchased pack or a related upsell map.

This web step exists so users can see the map and current price before paying.

## 19. Region/Data-Pack Map Pages

Main endpoints/functions:

- `/credits/region-pack-map`
- `/credits/region-pack-map-asset`
- `/credits/region-pack-map-background.jpg`
- `regionPackStaticMapPayload()`
- `regionPackStaticMapHtml()`

Map pages show:

- Current user-specific price breakdown.
- Zoom/detail selector (`Zoom 1 - closest`, `Zoom 2`, etc.).
- Tile overlay by state: new, partially licenced, already licenced, free.
- Included country/area labels with neutrality disclaimer.
- Similar Options.
- Buy Now button for the current pack.

Map hover must show complete price explanation:

```text
Full Price: €X.XX
Licenced: - €Y.YY                 only if applicable
Partially licenced: - €Z.ZZ       only if applicable
Volume Discount (P%): - €A.AA     only if applicable
Final Price: €B.BB
```

Do not show zero-value deduction lines.

## 20. Similar Options

Similar Options are a sales/navigation aid, not a pricing authority.

They should include contextually useful alternatives such as:

- Parent macro regions/continents.
- Neighbouring countries for country pages.
- Contained states/territories for countries that have state-level products.
- Macro regions for continent pages.

They must use the same backend pricing summary as the main product. They must not use stale page-local prices.

## 21. World Pack

World is special:

- It unlocks effectively all Full Quality licensable tiles.
- Once World is purchased, Full Quality paid options should no longer be offered because all Full Quality data is free for that user.
- `world_full_quality_unlocked_at` on `user_credit_accounts` is the fast entitlement flag.
- `isWorldFullQualityUnlocked()` makes tile access checks return true.

Pricing:

- World gross comes from the generated catalog.
- World default discount is the current max discount.
- Existing user entitlements must be deducted before calculating final price.
- Per-product override can still be used if configured.

Operational note:

- Avoid expanding full World into hundreds of thousands of entitlement rows unless a specific download workflow needs it.
- Access checks should use the account-level World flag.

## 22. Purchase History and Audit Requirements

Every paid purchase must leave enough data to reconstruct what happened.

For scene purchases:

- Store top-line purchase in `purchase_history`.
- Store purchased tile rows in `purchase_history_tiles`.
- Store purchased tile keys and price breakdown metadata in ledger metadata.

For animation purchases:

- Store top-line purchase in `purchase_history` with `purchase_type = animation_tiles`.
- Store the unique purchased tile rows.
- Store segment count and animation fee metadata.

For region/data-pack purchases:

- Store top-line purchase with `region_pack_id`, name, type, catalog version, discount, gross, final price, and tile counts.
- Full tile list can be reconstructed from static catalog plus purchase timestamp/catalog version.
- Newly granted entitlement rows are stored in `user_tile_entitlements`.

For World purchases:

- Store purchase history and set account-level World entitlement.

## 23. Stripe Processing and Idempotency

Stripe webhook processing must be idempotent.

Mechanisms:

- `stripe_webhook_events` records processed event IDs.
- `purchase_history.stripe_session_id` has a unique index.
- `grantPaidSceneTileEntitlements()` checks existing purchase/ledger rows for the same session.
- `INSERT OR IGNORE` protects `user_tile_entitlements` from duplicate tile inserts.

Supported purchase types:

- `scene_tiles`
- `animation_tiles`
- `region_pack`

Unsupported old payment types must fail rather than silently doing legacy work.

## 24. Tile Access Enforcement

Full Quality tile GETs must only succeed when the tile is:

- globally free,
- already licenced/covered by finer entitlement,
- covered by World entitlement,
- covered by a valid short-lived tile session token after backend verification.

Main enforcement path:

```text
streaming_utils.py / r2_source.py
-> /tiles/session
-> unlockTilesForSession()
-> tile token
-> tile_routes.js GET authorization
```

Important rule:

```text
/tiles/session does not deduct money.
```

It only verifies that all requested paid Full Quality tiles are already licenced/free, or it returns `payment_required`.

## 25. Full Quality Resolve Flow in Blender

Still-image Full Quality flow:

1. User selects/clicks `Full Quality` in Camera View.
2. Client checks account/auth status and authoritative price estimate.
3. If payable amount is positive, client opens direct purchase workflow.
4. If no payment is required, client requests tile session and starts resolve.
5. Backend verifies entitlements before issuing tile token.
6. Client downloads S2/EL/WT/PO assets or uses Local Source/cache.
7. UI refreshes price and Relevant Data Packs after successful resolve/payment.

Full Quality must stay Camera View oriented. Active View should not trigger direct Full Quality purchasing.

## 26. Downloading Licenced Tiles

Primary file:

```text
credit_api.py
```

Backend endpoint:

```text
GET /credits/unlocked
```

Behavior:

- Returns licenced tile rows and default asset lists.
- Manual download is in the Account panel.
- Downloaded files do not create additional charges.
- Local Source is searched before cloud download.
- Download telemetry records total files/tiles/bytes, not every detailed file forever.

Tables:

- `user_licenced_download_stats`
- `user_licenced_download_events`

## 27. Preview Fair Usage

Preview is free but monitored.

Relevant tables:

- `tile_request_rollup_hourly_account_quality`
- `tile_request_rollup_daily_account_quality`
- `preview_usage_hourly_account`

Rules:

- Preview limits observe Preview quality only.
- Full Quality/licenced traffic is separate and must not trigger Preview fair-usage enforcement.
- Current fair-usage enforcement should be alert-only unless explicitly changed.
- Preview hold must not block already-licenced Full Quality access.

## 28. Pricing Integrity Failure Rules

### Backend unavailable

If backend estimate fails, Blender may receive a non-authoritative zero-like fallback:

```text
authoritative = False
pricing_source = backend_unavailable | backend_rejected | backend_incomplete
```

Full Quality purchase/resolve must not treat that as a real free price.

### Missing metadata

If a requested non-free tile is missing from `tile_land_stats`:

- Price it at `€0.00`.
- Mark `free_reason = pricing_metadata_missing`.
- Record `pricing_integrity_events`.
- Log `planetka_pricing_metadata_missing`.

This prevents overcharging, but it is still a production data bug and should be investigated.

### R2/data availability

Pricing correctness does not guarantee R2 data availability. A paid tile should still be downloadable. Missing S2 assets are resolve/data integrity errors and must not cause charges without usable data.

## 29. Current Admin Operations

### Change global pricing

Use Analytics -> Product Pricing:

- Edit `Price coefficient (€/10,000 km²)`.
- Save pricing.
- Prices update through runtime settings and cache invalidation.
- No catalog rebuild is required.

### Change volume discount curve

Use Product Pricing:

- Edit min/max discount.
- Edit bucket thresholds/ratios.
- Save pricing.
- The system recalculates product effective discounts dynamically.

### Run a country promotion

Use Product Pricing:

- Set product discount override to `100` for that product.
- User-specific final price becomes `€0.00` for new chargeable tiles in that product.
- Remove override when promotion ends.

### Change scene/animation fees

Use Product Pricing:

- `Scene licence fee €` controls custom scene-specific licence fee.
- `Animation licence fee €` controls custom animation licence fee.
- Changes apply to future estimates/checkouts.

## 30. Required Consistency Rules

The same final price must appear in:

- Blender UI button.
- Blender details popup.
- Data-pack web map page.
- All data packs catalog page.
- Similar Options cards.
- Stripe Checkout amount.
- Payment-success page.
- Analytics Product Pricing page.

The price authority must be the backend calculation using current `app_settings`, current catalog, and current user entitlements.

If two surfaces show different prices for the same user/product/time after cache refresh, treat it as a critical pricing bug.

## 31. Planned Materialized User-Product Pricing

The next pricing architecture should move data-pack pricing away from public
request-time calculation and into a materialized user-product pricing table.

Core rule:

```text
Catalog pages, data-pack map pages, Blender Relevant Data Packs, Similar Options, and checkout should read the same materialized user-product pricing row.
```

This table is not a loose cache. It is the source of truth for data-pack
quotes until the user's entitlement version or the global pricing version
changes.

Planned behavior:

- Public requests must not perform heavy data-pack pricing work.
- Public requests may read materialized rows, enqueue missing/stale rows, and return `price updating` when a row is not ready.
- Checkout is disabled when the required product quote row is missing, stale, or recalculating.
- Stripe Checkout must use the existing quote/materialized row and must not calculate a separate price.
- Scene-specific and animation purchases remain dynamic because their tile sets are unique and small.

Purchase invalidation flow:

1. Successful purchase increments the user's entitlement version.
2. Related user-product pricing rows are marked stale/recalculating.
3. The purchased product itself is updated first and becomes `€0.00`.
4. Exact-contained children are updated next and become `€0.00`.
5. Parents, overlaps, continent-level products, and World are queued after that.

Recalculation queue ordering:

```text
All recalculation jobs must run through one serialized global queue.
No two pricing recalculation jobs may run simultaneously, even for different users.
```

If multiple purchases happen close together, recalculation ordering is by
round across all purchases, not by completing one purchase fully before the
next purchase starts.

Example:

```text
Purchase A is currently recalculating round 4.
Purchase B happens.
After the currently running job finishes, B round 1 is queued before A round 5.
Then B round 2, B round 3, and B round 4 are queued before either purchase runs round 5.
Then round 5 jobs for both purchases run, then round 6 jobs, etc.
```

Operational reason:

- A user or multiple users making purchases at the same time must not cause
  parallel recalculation bursts.
- The queue may take longer to finish, but it must stay below Worker/D1 limits.
- Freshly viewed products can be fast-tracked by moving their job to the front
  of the queue for the current round, but they must still run as queued jobs,
  never synchronously inside the public page/API request.

## 32. Validation Commands

Basic local checks:

```bash
node --check cloudflare-api/src/worker/credit_routes.js
node --check cloudflare-api/src/worker/admin_analytics_handlers.js
node --check cloudflare-api/src/worker/billing_handlers.js
node --check cloudflare-api/src/auth_worker.js
node --check cloudflare-api/src/tile_worker.js
node --check cloudflare-api/src/commerce_worker.js
node --check cloudflare-api/src/analytics_worker.js
python3 -m py_compile credit_api.py animation_tools.py ui.py operators.py
git diff --check
```

Recommended D1 integrity checks:

```sql
SELECT COUNT(*) AS pricing_integrity_events FROM pricing_integrity_events;
SELECT COUNT(*) AS tile_land_stats_rows FROM tile_land_stats;
SELECT free_reason, COUNT(*) FROM tile_land_stats GROUP BY free_reason ORDER BY free_reason;
```

R2/D1 metadata alignment should be checked after any dataset update:

- Every non-free S2 object in R2 should have a `tile_land_stats` row.
- Every `tile_land_stats` row should correspond to an expected S2 object.
- Region-pack generated tile memberships should reference valid tile keys.

## 33. Do-Not-Break Invariants

Do not violate these invariants:

- Do not reintroduce local client pricing as authoritative.
- Do not reintroduce prepaid balance or monthly billing without legal/accounting review and explicit product decision.
- Do not charge Preview quality.
- Do not charge `d >= 060` tiles.
- Do not charge missing pricing metadata.
- Do not allow unlicenced paid Full Quality tile GETs.
- Do not allow paid Full Quality resolve before backend licence/session confirmation.
- Do not use Stripe metadata as the only pricing authority.
- Do not let web pages, Blender, Analytics, and Stripe use different pricing branches.
- Do not run multiple data-pack pricing recalculation jobs concurrently.
- Do not show `Full Price -> Final Price` without showing non-zero deductions in between.
- Do not show zero-value deductions.
- Do not count Full Quality/licenced traffic into Preview fair-usage enforcement.

## 33. File and Function Map

Backend pricing/settings:

- `cloudflare-api/src/worker/credit_routes.js`
- `getRuntimePricingSettings()`
- `setRuntimePricingSettings()`
- `fullQualityPublicPriceCoefficient()`
- `fullQualityPriceCoefficient()`
- `creditsForTileStats()`
- `estimateNewCredits()`
- `sceneEstimateWithPaymentPolicy()`
- `animationEstimateWithScenePolicy()`
- `regionProductPricingSummary()`
- `regionProductDiscountPercent()`
- `estimateRegionPackSummaryCached()`

Admin Product Pricing:

- `cloudflare-api/src/worker/admin_analytics_handlers.js`
- `handleAdminAnalyticsProductsPage()`
- `handleAdminSetPricingSettings()`
- `handleAdminSetProductDiscount()`

Stripe and purchase grants:

- `cloudflare-api/src/worker/credit_routes.js`
- `handleCreditCheckout()`
- `applyStripeCreditPurchaseFromSession()`
- `grantPaidSceneTileEntitlements()`
- `grantRegionPackEntitlements()`
- `recordPurchaseHistoryBestEffort()`

Tile access enforcement:

- `cloudflare-api/src/worker/tile_routes.js`
- `handleTileSessionStart()`
- `handleTileRequest()`
- `isTileUnlockedForUser()`
- `unlockTilesForSession()`

Blender client API:

- `credit_api.py`
- `estimate_credits_for_tiles()`
- `create_checkout_session()`
- `create_animation_checkout_session()`
- `create_region_pack_detail_link()`
- `create_scene_detail_link()`
- `get_unlocked_tiles()`

Resolve UI and operations:

- `operators.py`
- `PLANETKA_OT_SetTextureQualityAndResolve`
- `PLANETKA_OT_OpenCreditCheckout`
- `PLANETKA_OT_DataCostBreakdown`
- `ui.py`

Camera View pricing:

- `planetka_runtime/view_telemetry.py`
- `build_resolve_cost_breakdown()`
- `estimate_credits_for_visible_tiles()`
- `update_resolve_size_estimates()`

Animation pricing:

- `animation_tools.py`
- `_estimate_animation_pricing_for_segments()`
- `_animation_pricing_from_credit_summary()`
- `update_animation_credit_estimate()`
- `_unlock_animation_tiles_before_download()`
- `_start_animation_data_preload()`
- `PLANETKA_OT_AnimationRenderCostBreakdown`

Metadata/catalog build:

- `tools/build_tile_land_stats.py`
- `tools/build_region_pack_catalog.py`
- `tools/build_tile_commercial_value.py` for inactive internal commercial-value analysis only.
