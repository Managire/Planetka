# Planetka Release Documentation

Last updated: 2026-05-19

This folder contains release-support documents for Planetka. Only the files listed in `package_allowlist_public.txt` are included in the public add-on package.

## Public-package documents

The public package includes:

- `Documentation/Release/FAIR_USAGE_POLICY.md`
- `Documentation/Release/SYSTEM_REQUIREMENTS.md`
- user-facing licensing, privacy, attribution, and compliance documents from `Documentation/Licencing/`

Internal release checklists, runbooks, compatibility notes, developer notes, and QA notes are repository-maintenance documents only and must not be included in the user-facing package unless deliberately rewritten for users.

## Current 0.8.1 add-on model

Planetka 0.8.1 is prepared around a simplified streaming model:

- **Personal account**: free account access, limited to New Zealand and Iceland.
- **Professional account**: paid or manually granted account access, worldwide streaming.
- **Quality modes**: Preview, Balanced, and Full Quality are normal streaming quality choices. They are not separate purchases.
- **No in-addon data-pack commerce**: the Blender add-on no longer sells individual tiles, scene-specific texture licences, animation texture licences, or data packs.
- **No purchase history/download archive**: the active add-on workflow streams required data into a temporary working cache. It does not provide a supported raw-data download library.
- **Website data-pack pages**: existing product/catalog/map pages may remain available as a separate website/data-product system or future reference, but they are not the active Planetka add-on commerce model.

## Known blocker before public paid release

Professional checkout is not ready for public use yet. The current upgrade URL points to `https://www.planetka.io/blender/pricing`, which currently returns 404. Do not publish paid Professional upgrades until the checkout page and backend fulfilment are implemented and tested end-to-end.

## Public release checks

Before publishing a release:

- build the package through `tools/build_addon_zip.py` using `package_allowlist_public.txt`;
- verify the built file list contains no internal runbooks, checklists, developer notes, archived beta documents, or obsolete pricing internals;
- regenerate legal PDFs with `tools/generate_legal_pdfs.py` after any terms/privacy change;
- upload the release zip and legal PDFs to the configured R2 keys;
- deploy split Workers only with explicit `--config` files after confirming each `wrangler deploy --config ... --dry-run` shows restricted public access, current legal versions, and current updater metadata;
- run Blender smoke tests for Create Earth, Preview/Balanced/Full Quality resolves, Personal location restrictions, Professional worldwide access, animation preflight/rendering, update checks, and offline/error handling.
