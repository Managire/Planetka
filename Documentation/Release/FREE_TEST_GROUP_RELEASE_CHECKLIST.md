# Planetka v0.7.0 Beta Release Checklist

Scope: `v0.7.0` beta release candidate for a small tester group, optimized for single-developer support.
Public update channel remains on `v0.5.3` until explicit publish.

## 1. Release Freeze

- [ ] Freeze scope to bug fixes only (no new features).
- [ ] Tag current commit and record the previous known-good commit.
- [ ] Build and archive the exact `0.7.0` addon package planned for testers.

## 2. Rollback Readiness

- [ ] Keep one-click rollback notes: previous git commit, previous Worker Version ID, previous addon zip.
- [ ] Verify rollback command path for Worker deploy is known and tested once.
- [ ] Confirm `Documentation/Release/ROLLBACK_SAFE_UPDATE_TESTING.md` has been executed for current candidate.

## 3. Core Product Gates

- [ ] `Create Earth` works on a clean new scene.
- [ ] `Create Earth` works in an already-used scene without mutating non-Planetka objects or the user's active camera.
- [ ] `Remove Default Cube Scene` is enabled only for pristine default scenes and stays disabled elsewhere.
- [ ] `Resolve Earth` works from Place Search.
- [ ] Auto-resolve works from camera movement.
- [ ] Texture Quality buttons trigger correct resolves and size estimates.
- [ ] `Rebuild Earth` recreates the Earth while preserving Earth settings and camera state.
- [ ] `Quick Preview` builds successfully for a valid animation preset.
- [ ] `Render Animation` works through Planetka segmented full-quality rendering.

## 4. Public Beta Access Rules

- [ ] Beta build is marked personal-use beta in Terms and user-facing docs.
- [ ] Current beta policy is stated explicitly: `v0.7.0` beta runs in `unrestricted` access mode, so beta users receive Commercial-equivalent hosted-service access during testing regardless of stored account tier.
- [ ] Account/tier messaging in UI matches the current backend beta policy.
- [ ] Core workflows needed for tester validation are available under the current beta policy.
- [ ] Future public tier rollout (Free / Personal / Commercial) is clearly described as a later enforcement step, not the current beta-onboarding behavior.
- [ ] No public auto-update upload is performed for `v0.7.0` before explicit publish approval.
- [ ] Fair-usage and anti-abuse protections remain active in backend.

## 5. API Security Basics (Right-Sized)

- [ ] `/auth/api-key/request` and `/auth/api-key/exchange` match the intended beta entitlement policy.
- [ ] `/admin/analytics` rejects query token (`query_token_not_allowed`) and requires Bearer/cookie admin auth.
- [ ] Legacy magic-link auth routes (`/auth/start`, `/device/*`) are disabled in production.
- [ ] Tile-session auth (`X-Planetka-Tile-Token`) is active and tile hot path remains lightweight.
- [ ] Account throttling / abuse protections remain active for abnormal download behavior.
- [ ] DB cleanup cron is active for `magic_links`, `refresh_sessions`, `device_sessions`, and tile telemetry retention tables.

## 6. Observability and Support

- [ ] Worker logs are reachable and monitored during release day.
- [ ] Error spikes can be identified quickly (`5xx`, auth failures, tile failures).
- [ ] Addon bug report path is tested end-to-end once.
- [ ] Support template is ready (request: version, OS, Blender version, repro steps, logs).

## 7. Data Safety

- [ ] D1 backup/export routine exists.
- [ ] At least one restore has been tested in a non-production environment.

## 8. Tester Communication

- [ ] Share a short known-issues list with testers.
- [ ] Tell testers that `v0.7.0` beta currently runs in `unrestricted` access mode, even though the long-term product model still defines Free / Personal / Commercial tiers.
- [ ] Provide clear expected behavior for Preview / Balanced / Full Quality access under the current beta policy.
- [ ] Tell testers that `v0.7.0` is a private beta candidate and is not in the public update channel yet.
- [ ] Provide support contact path and expected response time.

## 9. Release-Day Runbook

- [ ] Record release timestamp, commit hash, and Worker Version ID.
- [ ] Monitor first 60 minutes after release and note incidents.
- [ ] If blocker occurs, execute rollback and post tester update.

## 10. Exit Criteria (Go / No-Go)

- [ ] No blocker in `Create Earth` / `Resolve Earth`.
- [ ] Authentication and tile delivery are stable for tester baseline.
- [ ] Changelog, compatibility matrix, and package version all reference `v0.7.0`.
- [ ] Rollback path verified.
- [ ] Decision logged: `GO` or `NO-GO`.
