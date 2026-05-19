# Planetka Pricing System Reference

Last updated: 2026-05-19

## Current 0.8.1 Add-on Model

Planetka 0.8.1 does not use tile-by-tile pricing, data-pack pricing, scene-specific pricing, animation pricing, quote rows, or checkout quotes for Blender add-on access.

The active add-on pricing/access model is intentionally simple:

```text
Personal account -> free -> selected free locations only
Professional account -> paid or manually granted -> worldwide streaming
```

Preview, Balanced, and Full Quality are quality modes, not purchasable products.

## What Is No Longer Active In The Add-on

Do not use the legacy pricing system for the 0.8.1 Blender add-on:

- no in-addon tile purchases;
- no scene-specific Full Quality purchases;
- no animation Full Quality purchases;
- no data-pack purchases from Blender;
- no purchase-history UI;
- no licenced-data download/archive UI;
- no client-side or backend tile-price calculation for add-on resolves;
- no checkout quote required before Full Quality resolve for Professional accounts.

## Legacy Website/Data-Pack System

The previous data-pack catalogue, map pages, quote jobs, Stripe checkout, and product-pricing controls may remain in Cloudflare for future reference or a separate website/data product.

That system is not authoritative for 0.8.1 Blender add-on streaming access. If it is used later, it must remain clearly separated from the add-on account-tier model.

## Authoritative Add-on Access Components

Active access decisions for 0.8.1 are made by:

- `cloudflare-api/src/worker/entitlements.js`
- `cloudflare-api/src/worker/tile_routes.js`
- `cloudflare-api/src/tile_worker.js`
- `auth.py`
- `r2_source.py`

The Blender client sends the current navigation point when creating a tile session. The tile Worker enforces whether that account can stream the requested region and quality.

## Professional Checkout Status

Professional checkout is not currently ready for public release. The current upgrade URL is a placeholder/missing page and must be implemented before paid Professional upgrades are offered.

Until checkout is implemented, Professional access must be granted manually or through controlled backend test setup.
