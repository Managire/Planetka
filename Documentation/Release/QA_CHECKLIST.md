# Planetka QA Checklist

## 1. Pre-Flight

- [ ] Extension loads without Python errors in Blender.
- [ ] `Create New Earth`, `Resolve`, and `Knowledge Base` panels are visible.
- [ ] Basic texture samples exist in `Resources/Basic Textures`.

## 2. Core Functional Gates (Must Pass)

- [ ] `Create Earth` completes.
- [ ] `Resolve Earth` completes with a valid texture source.
- [ ] Resolved object is named `Planetka Earth Surface`.
- [ ] `Create Earth` places surface only in `Planetka - Earth Surface Collection`.
- [ ] `Resolve Earth` preserves the previous surface collection placement.
- [ ] Adaptive subdivision modifier exists and uses Catmull-Clark.

## 3. Automated Validation

- [ ] Release gate pass:
  - `python3 tools/release_gate.py`
- [ ] Smoke test pass:
  - `tools/run_smoke.sh`
- [ ] Regression test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_regression_test.py`
- [ ] Schema migration test pass:
  - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_schema_migration_test.py`

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

## 8. Release Decision

- [ ] No unresolved blocker issue in core path (`Create Earth`, `Resolve Earth`).
- [ ] Compatibility matrix updated for tested Blender versions.
- [ ] Changelog entry added for current version.
- [ ] Release notes drafted from template with semver rationale.
