# Planetka: What Changed from v0.5.3 to v0.7.0

Last updated: 2026-05-12
Audience: support and release review

## Quick Overview

`v0.7.0` is a public-release candidate focused on safer scene handling, clearer Full Quality licensing, stronger animation workflows, and a more transparent payment/data-pack experience.

## Biggest User-Facing Changes

### 1) Public texture access model

Planetka now presents two public quality modes:

- Preview: free, streamed/cached, personal / non-commercial use.
- Full Quality: paid or explicitly granted, with commercial texture rights for licenced Full Quality data.

### 2) Direct Full Quality purchasing

Scene-specific, animation, and data-pack Full Quality purchases use direct checkout. Pricing is shown before payment and should match across Blender UI, web map pages, payment-success pages, and Stripe checkout.

### 3) Relevant Data Packs

The Blender UI can suggest relevant Full Quality data packs for the resolved camera view. Data-pack web pages show visual tile coverage, already-licenced deductions, discounts, and final price.

### 4) Animation workflow improvements

Animation tools were simplified and hardened:

- clearer camera-keyframe generation;
- Quick Preview for preview-quality segment preparation;
- Full Quality animation purchase workflow;
- stronger preflight checks before segmented animation rendering starts.

### 5) Safer scene and camera behavior

`Create Earth` and related actions now use Planetka-owned scene objects more consistently and avoid unnecessary mutation of user scene content.

### 6) Clearer warnings and diagnostics

The add-on has clearer warnings for invalid states, offline/unavailable service states, and scene-health issues.

## Release Requirements

Before publishing v0.7.0:

- build with `tools/build_addon_zip.py` and `package_allowlist_public.txt`;
- verify no internal release checklists, runbooks, developer docs, or archived tester notes are packaged;
- regenerate legal PDFs after any terms/privacy change;
- upload the release zip and legal PDFs to the configured R2 keys;
- confirm Worker dry-run shows restricted access, current legal versions, and current updater metadata;
- run Blender smoke tests for Create Earth, Preview resolve, Full Quality scene purchase, data-pack page opening, and animation preflight.

## Reference Sources

- `CHANGELOG.md`
- `Documentation/Release/README.md`
- `Documentation/Release/COMPATIBILITY_MATRIX.md`
- `Documentation/Licencing/TERMS_OF_SERVICE.md`
- `Documentation/Licencing/PRIVACY_POLICY.md`
