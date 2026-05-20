# Planetka Pricing System Reference

Last updated: 2026-05-19

## Current 0.8.2 Add-on Model

Planetka 0.8.2 does not use tile-by-tile pricing, data-pack pricing, scene-specific pricing, animation pricing, quote rows, or checkout quotes for Blender add-on access.

The active add-on pricing/access model is intentionally simple:

```text
Free account -> free -> Preview texture quality worldwide
Indie account -> EUR 70 one-time or manually granted -> Preview and Balanced texture quality worldwide
Pro account -> EUR 280 one-time or manually granted -> Preview, Balanced, and Full texture quality worldwide
Indie to Pro upgrade -> EUR 210 one-time
```

Preview, Balanced, and Full Quality are quality modes, not purchasable products.

## What Is No Longer Active In The Add-on

Do not use the legacy pricing system for the 0.8.2 Blender add-on:

- no in-addon tile purchases;
- no scene-specific Full Quality purchases;
- no animation Full Quality purchases;
- no data-pack purchases from Blender;
- no purchase-history UI;
- no licenced-data download/archive UI;
- no client-side or backend tile-price calculation for add-on resolves;
- no checkout quote required before Full Quality resolve for Pro accounts.

## Legacy Website/Data-Pack System

The previous data-pack catalogue, map pages, quote jobs, Stripe checkout, and product-pricing controls may remain in Cloudflare for future reference or a separate website/data product.

That system is not authoritative for 0.8.2 Blender add-on streaming access. If it is used later, it must remain clearly separated from the add-on account-tier model.

## Authoritative Add-on Access Components

Active access decisions for 0.8.2 are made by:

- `cloudflare-api/src/worker/entitlements.js`
- `cloudflare-api/src/worker/tile_routes.js`
- `cloudflare-api/src/tile_worker.js`
- `auth.py`
- `r2_source.py`

The Blender client sends the requested texture quality when creating a tile session. The tile Worker enforces whether that account tier can stream that quality for the duration of the short-lived session.

## Indie/Pro Checkout Status

Indie/Pro checkout is not currently ready for public release. The current upgrade URL is a placeholder/missing page and must be implemented before paid upgrades are offered.

Until checkout is implemented, Indie and Pro access must be granted manually or through controlled backend test setup.
