# Planetka QA Checklist

## 1. Pre-Flight

- [ ] Extension loads without Python errors in Blender.
- [ ] Account, Create Earth, Data Control, Navigation, Animation, and Scene Health panels are visible.
- [ ] Fallback texture samples exist in `Resources/Fallback Images`.
- [ ] The active UI does not expose obsolete in-addon data-pack purchase, purchase-history, or licenced-data download workflows.

## 2. Core Functional Gates (Must Pass)

- [ ] `Create Earth` completes in a clean scene.
- [ ] Preview resolve completes with a valid Planetka Cloud texture source.
- [ ] Balanced resolve completes with a valid Planetka Cloud texture source.
- [ ] Full Quality resolve completes for a Pro account with a valid Planetka Cloud texture source.
- [ ] Resolved object is named `Planetka Earth Surface`.
- [ ] `Create Earth` places surface only in `Planetka - Earth Surface Collection`.
- [ ] Resolve preserves the previous surface collection placement.
- [ ] Adaptive subdivision modifier exists and defaults to Catmull-Clark for normal non-animation Earth workflow.
- [ ] CRITICAL (Animation): Cycles segmented animation paths (Quick Preview and Final Animation Render) force Adaptive Subdivision `subdivision_type = SIMPLE` to prevent tiny segment-boundary texture/surface drift.
- [ ] Dynamic tile window enforcement active (`5..12` tiles at shader stage when dynamic tiles are present) with no missing visible coverage.

## 3. Account-Tier Gates

- [ ] During beta, new account access requests default to Pro (`PLANETKA_BETA_DEFAULT_PRO=1`).
- [ ] Analytics can manually switch any user between Free and Pro for tier testing.
- [ ] Free account can stream worldwide in Preview and Balanced texture quality.
- [ ] Free account is blocked from Full texture quality with clear wording.
- [ ] Free account is blocked from Standalone file export, Final Animation Render, Panoramic camera rendering, Texture-Based Clouds, and VDB Clouds with clear Pro-only wording.
- [ ] Pro account can stream worldwide in Preview, Balanced, and Full texture quality.
- [ ] Account creation, access-key connection, logout, reconnect, and stale-auth recovery do not depend on commerce/product-map routes.

## 4. Automated Validation

- [ ] Static release gate pass:
  - `PLANETKA_RELEASE_GATE_STATIC_ONLY=1 python3 tools/release_gate.py`
- [ ] Account-tier live gate pass:
  - `/Applications/Blender5.0.app/Contents/MacOS/Blender --background --factory-startup --python tools/planetka_account_tier_gate.py`
- [ ] Resolve timing gate pass:
  - `/Applications/Blender5.0.app/Contents/MacOS/Blender --background --factory-startup --python tools/planetka_resolve_timing_gate.py`
- [ ] Smoke test pass:
  - `tools/run_smoke.sh`
- [ ] Regression test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_regression_test.py`
- [ ] Schema migration test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_schema_migration_test.py`
- [ ] Worker auth/device integration test pass:
  - `python3 tools/worker_auth_integration_test.py`
- [ ] Stale-auth recovery gate pass:
  - `/Applications/Blender5.0.app/Contents/MacOS/Blender --background --factory-startup --python tools/planetka_stale_auth_recovery_gate.py`
- [ ] Worker abuse/stress simulation pass only in a maintenance window or isolated backend:
  - `PLANETKA_ALLOW_LIVE_STRESS=1 python3 tools/worker_abuse_simulation.py --base-url https://api.planetka.io`
- [ ] Add-on auto-updater manifest endpoint responds:
  - `curl -sS https://api.planetka.io/addon/update-manifest | jq .`
- [ ] Cloud API env vars reviewed against:
  - `Documentation/Developer/CLOUD_API_ENV_VARS.md`

## 5. Texture Source Validation

- [ ] Invalid source path is rejected with a clear error.
- [ ] Valid source path resolves Earth surface.
- [ ] Ocean-only tiles may use bundled fallback textures by design; this is acceptable and must not be treated as a source-data defect.
- [ ] Missing S2 tiles inside covered land regions are treated as resolve-blocking source/entitlement defects.
- [ ] Missing EL/WT/PO tiles use fallback support textures silently; this is normal behavior and must not block resolve or animation render.

## 6. Driver-Free Integrity

- [ ] No Planetka-created object/material/node-group has animation drivers.
- [ ] Scene remains stable after save/reopen without driver rebuild steps.

## 7. Rollback-Safe Update Testing (A -> B -> A)

- [ ] Start from released extension `A` and a representative `.blend`.
- [ ] Open file in extension `A`, run `Create Earth` and all quality-mode resolve workflows.
- [ ] Upgrade to candidate extension `B`, reopen same file, rerun core workflow.
- [ ] Downgrade back to extension `A`, reopen same file, verify no blocker errors.
- [ ] Document any non-reversible behavior explicitly in release notes.

## 8. Manual Visual Spot Checks

- [ ] Resolved surface shading appears with expected texture blending.
- [ ] Repeated close-range resolves do not shrink Earth size.
- [ ] High-detail camera view resolves and renders in Cycles without SVM stack overflow.
- [ ] Animation render output uses the expected quality mode and does not leave excessive temporary cache files.

## 9. Release Decision

- [ ] No unresolved blocker issue in core path (`Create Earth`, Preview/Balanced/Full Quality resolves, account connection).
- [ ] Pro checkout implemented and tested before any paid public launch.
- [ ] Compatibility matrix updated for tested Blender versions.
- [ ] Changelog entry added for current version.
- [ ] Release notes drafted from template with semver rationale.
