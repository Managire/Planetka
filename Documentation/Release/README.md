# Planetka Release Documentation

Last updated: 2026-05-12

This folder contains release-support documents for Planetka. Only the files listed in `package_allowlist_public.txt` are included in the public add-on package.

## Public-package documents

The public package includes:

- `Documentation/Release/FAIR_USAGE_POLICY.md`
- `Documentation/Release/SYSTEM_REQUIREMENTS.md`
- user-facing licensing, privacy, attribution, and compliance documents from `Documentation/Licencing/`

Internal release checklists, runbooks, compatibility notes, and QA notes are repository-maintenance documents only and must not be included in the user-facing package unless deliberately rewritten for users.

## Current public-release model

- Preview access is free and personal / non-commercial.
- Full Quality access is paid or explicitly granted, with commercial texture rights for licenced Full Quality data.
- Standard/Balanced, prepaid balance, monthly billing, and unrestricted-quality access are not public-release products.
- Data-pack, scene-specific, and animation purchases must show consistent prices across Blender UI, web pages, success pages, and Stripe checkout.
- Legal PDFs served from the Worker must match `Documentation/Licencing/TERMS_OF_SERVICE.md` and `Documentation/Licencing/PRIVACY_POLICY.md`.

## Public release checks

Before publishing a release:

- build the package through `tools/build_addon_zip.py` using `package_allowlist_public.txt`;
- verify the built file list contains no internal runbooks, checklists, developer notes, or archived beta documents;
- regenerate legal PDFs with `tools/generate_legal_pdfs.py` after any terms/privacy change;
- upload the release zip and legal PDFs to the configured R2 keys;
- deploy the split Workers only with explicit `--config` files after confirming each `wrangler deploy --config ... --dry-run` shows restricted public access, current legal versions, and current updater metadata;
- run Blender smoke tests for Create Earth, Preview resolve, Full Quality purchase flow, data-pack page opening, animation preflight, and offline/error handling.
