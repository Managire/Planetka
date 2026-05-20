# Planetka Compatibility Matrix

Last updated: 2026-05-20

This internal matrix records the current compatibility baseline for public-release QA.

| Planetka version | Blender versions | Smoke status | Notes |
| --- | --- | --- | --- |
| v0.8.3 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: Atmosphere panel restored, Create Earth adds Atmosphere by default, EEVEE/Cycles atmosphere mode selection follows render engine, Clouds panel remains disabled. |
| v0.8.2 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: per-resolve analytics instead of per-tile Queue messages, single-path Texture Quality resolves, animation stop safety, and no Atmosphere UI in this release. |
| v0.8.1 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Future update candidate: simplified Free/Indie/Pro streaming model, Preview/Balanced/Full as quality modes, Free limited to Preview, Indie limited to Preview/Balanced, Pro allowed all qualities. Paid checkout remains a known blocker before paid public launch. |
| v0.7.8 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: release metadata consistency, split-worker release-gate checks, animation checkout cancellation safety, and current web UI colour/wording updates. |
| v0.7.6 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: quote-only Full Quality data-pack pricing/checkout across Blender, web pages, catalog, Stripe, and webhook fulfilment. |
| v0.7.5 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: D1-backed exact data-pack pricing and reduced Worker runtime bundle for large pack pricing routes. |
| v0.7.4 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: Full Quality post-purchase sidebar recovery and Relevant Data Packs background refresh safety. |
| v0.7.3 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: account page, UI wording/icon refinements, pricing refresh consistency, and Worker map-page CPU reduction. |
| v0.7.2 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: account-panel wording/layout refinements, animation zero-price display cleanup, and successful Final Animation Render cache cleanup. |
| v0.7.1 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: manual Full Quality data downloads are disabled while beta accounts have free Full Quality streaming access. |
| v0.7.0 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Earlier public-release model: Preview plus paid Full Quality tile/data-pack purchases. Superseded for the add-on by the 0.8.1 streaming model. |

## Required checks before publication

- Open Blender 5.0 and confirm the Planetka sidebar opens without visible panel flicker.
- Create Earth in a clean scene.
- Resolve Preview, Balanced, and Full Quality at several camera positions.
- Verify Free account restrictions: Preview allowed worldwide; Balanced and Full blocked clearly.
- Verify Indie account restrictions: Preview and Balanced allowed worldwide; Full blocked clearly.
- Verify Pro account access: worldwide Preview, Balanced, and Full streaming allowed.
- Run animation preview/preflight and final render in the active quality modes.
- Confirm no in-addon data-pack pricing, scene-specific purchase, purchase-history, or licenced-data download workflow is visible in the active 0.8.3 UI.
- Confirm Atmosphere is visible in the active 0.8.3 UI and Clouds remains hidden.
- Build the explicit public zip with `tools/build_addon_zip.py`.
- Confirm each split Worker `wrangler deploy --config ... --dry-run` shows restricted public access and current updater/legal metadata.
