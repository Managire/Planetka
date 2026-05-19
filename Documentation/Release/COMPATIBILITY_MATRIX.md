# Planetka Compatibility Matrix

Last updated: 2026-05-19

This internal matrix records the current compatibility baseline for public-release QA.

| Planetka version | Blender versions | Smoke status | Notes |
| --- | --- | --- | --- |
| v0.8.1 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Future update candidate: simplified Personal/Professional streaming model, Preview/Balanced/Full Quality as quality modes, Personal limited to New Zealand/Iceland, Professional worldwide streaming. Professional checkout remains a known blocker before paid public launch. |
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
- Verify Personal account restrictions: New Zealand and Iceland allowed; other locations blocked clearly.
- Verify Professional account access: worldwide Preview, Balanced, and Full Quality streaming allowed.
- Run animation preview/preflight and final render in the active quality modes.
- Confirm no in-addon data-pack pricing, scene-specific purchase, purchase-history, or licenced-data download workflow is visible in the active 0.8.1 UI.
- Build the explicit public zip with `tools/build_addon_zip.py`.
- Confirm each split Worker `wrangler deploy --config ... --dry-run` shows restricted public access and current updater/legal metadata.
