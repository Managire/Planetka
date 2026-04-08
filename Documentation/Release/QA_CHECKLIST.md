# Planetka QA Checklist

## 1. Pre-Flight

- [ ] Extension loads without Python errors in Blender.
- [ ] `Create New Earth`, `Resolve`, and `Knowledge Base` panels are visible.
- [ ] Fallback texture samples exist in `Resources/Fallback Images`.

## 2. Core Functional Gates (Must Pass)

- [ ] `Create Earth` completes.
- [ ] `Resolve Earth` completes with a valid texture source.
- [ ] Resolved object is named `Planetka Earth Surface`.
- [ ] `Create Earth` places surface only in `Planetka - Earth Surface Collection`.
- [ ] `Resolve Earth` preserves the previous surface collection placement.
- [ ] Adaptive subdivision modifier exists and uses Catmull-Clark (fallback to Simple only if Blender enum compatibility requires it).
- [ ] Dynamic tile window enforcement active (`5..12` tiles at shader stage when dynamic tiles are present) with no missing visible coverage.

## 3. Automated Validation

- [ ] Release gate pass:
  - `python3 tools/release_gate.py`
- [ ] Smoke test pass:
  - `tools/run_smoke.sh`
- [ ] Regression test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_regression_test.py`
- [ ] Schema migration test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_schema_migration_test.py`
- [ ] Worker auth/device integration test pass:
  - `python3 tools/worker_auth_integration_test.py`
- [ ] Worker abuse simulation pass (plan tampering, token-query rejection, legacy-auth disabled, high-volume tile flood sanity):
  - `python3 tools/worker_abuse_simulation.py --base-url https://api.planetka.io`
- [ ] Addon auto-updater manifest endpoint responds:
  - `curl -sS https://api.planetka.io/addon/update-manifest | jq .`
- [ ] Cloudflare API env vars reviewed against:
  - `Documentation/Developer/CLOUDFLARE_API_ENV_VARS.md`

## 4. Texture Source Validation

- [ ] Invalid source path is rejected with a clear error.
- [ ] Valid source path resolves Earth surface.
- [ ] Missing S2 tiles trigger fallback warnings, not crashes.
- [ ] Missing EL/WT/PO tiles use fallback support textures, not crashes.

## 5. Driver-Free Integrity

- [ ] No Planetka-created object/material/node-group has animation drivers.
- [ ] Scene remains stable after save/reopen without driver rebuild steps.

## 6. Rollback-Safe Update Testing (A -> B -> A)

- [ ] Start from released extension `A` and a representative `.blend`.
- [ ] Open file in extension `A`, run `Create Earth`/`Resolve Earth` workflow.
- [ ] Upgrade to candidate extension `B`, reopen same file, rerun core workflow.
- [ ] Downgrade back to extension `A`, reopen same file, verify no blocker errors.
- [ ] Document any non-reversible behavior explicitly in release notes.

## 7. Manual Visual Spot Checks

- [ ] Resolved surface shading appears with expected texture blending.
- [ ] Repeated close-range resolves do not shrink Earth size.
- [ ] High-detail camera view (e.g. Cairo reproduction) resolves and renders in Cycles without SVM stack overflow.

## 8. Release Decision

- [ ] No unresolved blocker issue in core path (`Create Earth`, `Resolve Earth`).
- [ ] Compatibility matrix updated for tested Blender versions.
- [ ] Changelog entry added for current version.
- [ ] Release notes drafted from template with semver rationale.
