# Changelog

All notable public changes to Planetka are documented in this file.

## [v0.8.2] - 2026-05-20

### Changed
- Replaced per-tile Cloudflare Queue analytics with one resolve-summary event per completed resolve to reduce Queue usage and keep tile delivery lightweight.
- Final Animation Render now uses the currently selected Texture Quality mode instead of forcing Full Quality.
- Texture Quality switching now runs through the single shared resolve path instead of the removed quality-switch shortcut.
- The Data Control status line is used for resolve progress; quality buttons stay static.

### Fixed
- Fixed Preview/Balanced/Full resolves so the final shader textures match the selected quality mode rather than being overwritten by Preview resolves.
- Fixed competing auto-resolve jobs so stale completed resolves cannot override a newer explicit quality request.
- Fixed the Final Animation Render Stop control to stop cooperatively without directly cancelling Blender render from the UI operator.
- Removed the obsolete Active View lower-quality override.

### Release note
- Atmosphere integration is not included in this update.

## [v0.8.1] - 2026-05-19

### Changed
- Prepared the add-on for the simplified Personal / Professional streaming model.
- During beta, existing and newly requested accounts default to Professional so testers can use worldwide streaming without payment.
- Personal accounts can stream Planetka data only in the selected free locations: New Zealand and Iceland.
- Professional accounts can stream worldwide in Preview, Balanced, and Full Quality.
- The add-on model is now streaming-first: in-addon data-pack purchases, scene-specific tile purchases, purchase history, and licenced-data downloads are no longer part of the active Planetka add-on workflow.
- Full Quality now behaves like a normal quality mode for Professional accounts rather than a one-off purchase flow.
- Release documentation now separates the active add-on model from the legacy website/data-pack commerce system kept for future reference.

### Added
- Account-tier enforcement checks for Personal and Professional access at the tile-session / tile-delivery layer.
- Analytics All Users page controls for manually switching an account between Personal and Professional.
- Automated account-tier gate covering Personal location restrictions and Professional worldwide access.
- Resolve timing gate for Preview, Balanced, and Full Quality quality modes.

### Known limitation
- Professional checkout is not ready for public use yet. The current upgrade URL points to a missing pricing page and must be implemented before publishing paid Professional upgrades.

## [v0.7.8] - 2026-05-17

### Changed
- Released the current beta state with consistent add-on, updater, changelog, and compatibility metadata.
- Updated web Buy buttons to use the same red colour as new tiles.
- Updated animation render payment wording to say Render Animation instead of Buy Animation.

### Fixed
- Removed the abandoned-animation-payment polling loop that could keep recalculating animation pricing on Blender's main thread after a Stripe checkout page was closed.
- Updated release-gate backend checks for the current split Cloudflare Worker structure.

## [v0.7.6] - 2026-05-14

### Changed
- Data-pack checkout now uses a single backend quote object across Blender UI, web map pages, catalog rows, payment choice pages, Stripe metadata, and webhook fulfilment.
- Removed alternate data-pack checkout/pricing branches so Stripe can only charge an existing quote amount.

### Fixed
- Prevented data-pack checkout links from proceeding with stale or missing quote IDs after pricing or entitlement changes.

## [v0.7.5] - 2026-05-14

### Changed
- Moved exact Full Quality data-pack tile pricing to D1-backed product tile rows so large packs no longer require the Worker to load the generated tile-data module.
- Reduced Worker bundle size for data-pack pricing routes while preserving exact user-specific entitlement deductions.

### Fixed
- Fixed a cent-level residual pricing path where a fully licenced data pack could still show a tiny remaining checkout amount.

## [v0.7.4] - 2026-05-14

### Fixed
- Fixed the Blender Full Quality button getting stuck after a data-pack purchase while the sidebar price estimate was still refreshing.
- Fixed Full Quality resolve safety so missing authoritative pricing fails closed instead of being treated as free.
- Fixed a Relevant Data Packs background refresh context bug that could throw a thread exception during sidebar updates.

## [v0.7.3] - 2026-05-14

### Added
- Account page link from the Blender account panel with purchase history and a licenced-tile map.
- Light/dark browser theme support for Planetka web pages.
- Internal live pricing consistency harness for scene, country, and region purchase checks against the sandbox backend.

### Changed
- Beta accounts are treated as having Full Quality access while public payments remain disabled for beta testing.
- Refined Account, Navigation, Earth settings, and Animation UI labels/tooltips to remove internal tile terminology.
- Improved Full Quality resolve handling so manual Full Quality resolves do not remain selected for later automatic camera movement resolves.
- Simplified successful purchase pages and account page summaries.

### Fixed
- Fixed pack/scene price refresh after purchases so Blender UI, pack pages, success pages, and checkout estimates use the same current pricing state.
- Fixed account-page route handling and licenced-tile map display.
- Fixed Worker map-page CPU pressure by deferring expensive Similar Options pricing work from initial map responses.
- Fixed animation cost/detail summaries and cleaned up zero-value pricing rows.

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
