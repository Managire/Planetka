# Cloud API Environment Variables

Planetka uses three active Cloudflare Workers:

- `planetka-auth` for anonymous install sessions, refresh sessions, update manifests, support/legal endpoints, and admin session login.
- `planetka-tiles` for tile, cloud, VDB, and resolve-summary streaming.
- `planetka-analytics` for admin analytics and user licence management.

The add-on no longer uses API-key request flows, scene purchases, animation purchases, data-pack pricing, discounts, or standalone commerce/map Workers.

Active licence codes are:

- `personal` - personal-use licence.
- `commercial` - commercial-use licence.

Prices are managed only in external marketplaces/payment providers and are not hardcoded in Blender or Cloudflare runtime code.
