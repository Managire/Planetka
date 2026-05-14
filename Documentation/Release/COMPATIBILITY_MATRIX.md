# Planetka Compatibility Matrix

Last updated: 2026-05-14

This internal matrix records the current compatibility baseline for public-release QA.

| Planetka version | Blender versions | Smoke status | Notes |
| --- | --- | --- | --- |
| v0.7.4 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: Full Quality post-purchase sidebar recovery and Relevant Data Packs background refresh safety. |
| v0.7.3 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: account page, UI wording/icon refinements, pricing refresh consistency, and Worker map-page CPU reduction. |
| v0.7.2 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: account-panel wording/layout refinements, animation zero-price display cleanup, and successful Final Animation Render cache cleanup. |
| v0.7.1 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Beta patch: manual Full Quality data downloads are disabled while beta accounts have free Full Quality streaming access. |
| v0.7.0 | Blender 5.0 primary; Blender 4.5 LTS expected with verification | Pass required before publication | Public-release model: Preview plus paid Full Quality. Package/docs must use the public allowlist and current legal PDFs. |

## Required checks before publication

- Open Blender 5.0 and confirm the Planetka sidebar opens without visible panel flicker.
- Create Earth in a clean scene.
- Resolve Preview at several camera positions.
- Open Full Quality scene/details workflow and verify direct-payment pricing.
- Open Relevant Data Packs and verify web-map links.
- Run animation preview/preflight and confirm required texture files are downloaded before segmented render starts.
- Build the explicit public zip with `tools/build_addon_zip.py`.
- Confirm `wrangler deploy --dry-run` shows restricted public access and current updater/legal metadata.
