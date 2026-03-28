# Planetka Free Test Group Release Checklist

Scope: free-version pilot release for a small tester group, optimized for single-developer support.

## 1. Release Freeze

- [ ] Freeze scope to bug fixes only (no new features).
- [ ] Tag current commit and record the previous known-good commit.
- [ ] Build and archive the exact addon package planned for testers.

## 2. Rollback Readiness

- [ ] Keep one-click rollback notes: previous git commit, previous Worker Version ID, previous addon zip.
- [ ] Verify rollback command path for Worker deploy is known and tested once.
- [ ] Confirm `Documentation/Release/ROLLBACK_SAFE_UPDATE_TESTING.md` has been executed for current candidate.

## 3. Core Product Gates

- [ ] `Create Earth` works on a clean scene.
- [ ] `Resolve Earth` works from Place Search.
- [ ] Auto-resolve works from camera movement.
- [ ] Texture quality switch updates resolve behavior as expected.
- [ ] Animation render path still works and warns correctly when non-full texture quality is selected.

## 4. Free-Tier Access Rules

- [ ] Free users can use `Half` texture quality.
- [ ] Free users cannot use `Full` texture quality.
- [ ] Free users can authenticate and use the product without time limits.
- [ ] No subscription-renewal/trial logic is required for free users in this release.

## 5. API Security Basics (Right-Sized)

- [ ] `/auth/api-key/request` plan-tampering protection enabled (`paid_claim_order_id_required` on paid claim without order ID).
- [ ] `/admin/analytics` rejects query token (`query_token_not_allowed`) and requires Bearer/cookie admin auth.
- [ ] Legacy magic-link auth routes (`/auth/start`, `/device/*`) are disabled in production.
- [ ] Stripe webhook allowlist + signature validation enabled.
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
- [ ] Provide clear expected behavior for free tier (Half quality).
- [ ] Provide support contact path and expected response time.

## 9. Release-Day Runbook

- [ ] Record release timestamp, commit hash, and Worker Version ID.
- [ ] Monitor first 60 minutes after release and note incidents.
- [ ] If blocker occurs, execute rollback and post tester update.

## 10. Exit Criteria (Go / No-Go)

- [ ] No blocker in `Create Earth` / `Resolve Earth`.
- [ ] Authentication and tile delivery are stable for tester baseline.
- [ ] Rollback path verified.
- [ ] Decision logged: `GO` or `NO-GO`.
