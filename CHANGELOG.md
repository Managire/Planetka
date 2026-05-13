# Changelog

All notable public changes to Planetka are documented in this file.

## [v0.7.2] - 2026-05-13

### Changed
- Simplified beta wording in the Licenced Data account section.
- Moved Log Out directly below the account connection controls.
- Removed zero-price labels from the Final Animation Render button and animation price summaries.
- Removed nonessential "New Full Quality Tiles" labels from animation render UI.

### Fixed
- Final Animation Render now removes its temporary Full Quality cache files after a successful render so large animation downloads do not remain idle on disk.

## [v0.7.1] - 2026-05-13

### Changed
- Temporarily disabled manual Full Quality data downloads during beta while Full Quality streaming access is free.

## [v0.7.0] - 2026-05-12

### Added
- Public-release licensing model with free Preview access and paid Full Quality texture licences.
- Direct Stripe checkout for scene-specific Full Quality, animation Full Quality, and Full Quality data-pack purchases.
- Full Quality data-pack web pages with visual tile maps, pricing breakdowns, already-licenced tile deductions, and similar data-pack options.
- Relevant Data Packs section in the Blender UI for country, region, continent, and world Full Quality packs.
- Purchase-history and entitlement handling so previously licenced Full Quality texture data is not charged again where supported by the current product rules.
- Full Quality animation purchase workflow using the same tile-licence model as scene-specific purchases, with a separate custom animation licence fee.
- Public legal, privacy, attribution, fair-usage, and system-requirements documents included with the add-on package.

### Changed
- The Blender UI now focuses on two public quality modes: Preview and Full Quality.
- Full Quality pricing is shown consistently as Full Price, existing licence deductions, volume/product discounts, and Final Price.
- Data-pack pricing controls and product-specific discounts are managed through the analytics/product-pricing workflow.
- Account and data-download UI wording was simplified for public release.
- Preview is documented as personal, non-commercial streamed/cached use only.
- Full Quality is documented as including the commercial texture licence for licenced Full Quality data.

### Fixed
- Improved Full Quality Data Pack refresh behaviour so it runs after successful camera-view resolve rather than during camera movement.
- Improved consistency between Blender UI prices, web map prices, payment-success pages, and Stripe checkout prices.
- Improved map-page handling for large packs, similar options, product hierarchy, and user-specific already-licenced tile colouring.
- Improved animation preflight/download validation so required texture files are checked before segmented animation rendering starts.
- Removed internal release checklists and runbooks from the public package allowlist.
