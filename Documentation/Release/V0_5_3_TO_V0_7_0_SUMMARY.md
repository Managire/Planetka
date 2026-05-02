# Planetka: What Changed from v0.5.3 to v0.7.0

Last updated: 2026-05-01
Audience: users, testers, support

## Quick Overview

`v0.7.0` is a major quality and workflow upgrade over `v0.5.3`.

The focus was:

- safer scene/camera behavior
- much better animation workflow
- clearer status/warnings
- stronger stability for long renders

## Biggest User-Facing Changes

### 1) Final Animation Render now uses normal Blender UI rendering

This is one of the biggest changes.

Before, animation rendering used a separate non-UI render path.
Now it runs through normal Blender render UI behavior.

What this means for users:

- Rendering behaves more like standard Blender render flow.
- You can stop render in the usual way (closing render window / stopping render in UI flow).
- Output and progress are easier to follow visually.

### 2) Animation setup is clearer and more controllable

Animation tools were simplified so users have clearer control over when keyframes are generated and how frame ranges are used.

Improvements include:

- explicit camera keyframe generation flow
- clearer frame-range handling for preview vs final render behavior
- better protection against accidental edits during active final rendering

### 3) Final render stability got major hardening

A lot of work was done to reduce common animation failures:

- resolve/finalize hang handling improved
- safer cleanup after stop/cancel
- better recovery back to normal addon state after render ends
- less chance of endless retry/loop behavior in render-time resolve pipeline

### 4) Scene and camera safety improved

`Create Earth` and related actions were made much safer:

- Planetka now uses dedicated Planetka-owned camera flow
- less chance of unexpectedly changing user’s existing camera setup
- better preservation of existing scene content
- improved `Rebuild Earth` behavior that preserves more user context

### 5) New health checks and clearer warnings

Troubleshooting is much easier now:

- `Scene Health Check` added
- clearer warnings for invalid states (for example below-surface/too-low cases)
- better status reporting in Data Control and resolve lifecycle

## Rendering and Visual Continuity Improvements

### 6) Better segment-boundary consistency for animation

A lot of effort went into reducing subtle flicker/drift/edge artifacts between animation segments.

This includes:

- safer subdivision behavior in Cycles animation workflows
- stronger tile continuity rules across segment boundaries
- better handling of difficult horizon/edge tile visibility cases

### 7) Better handling when tile count is too high

When a view is too demanding, tile selection/reduction now follows a more robust strategy to preserve visual quality as much as possible before any destructive fallback is used.

Result for users:

- fewer broken frames from tile budget pressure
- more predictable output in extreme camera shots

## UI and Workflow Quality Improvements

### 8) Stronger UI guarding during active render

While Final Animation Render is active, critical controls are locked more consistently to prevent accidental destructive actions.

### 9) Camera keyframe awareness in navigation workflows

When camera keyframes are present, the UI behavior is clearer so users understand why camera movement controls may be constrained until keyframes are cleared.

## Account / Access / Release-State Changes

### 10) Clearer account state messaging

Account/tier/connectivity messaging in UI was improved (especially around API-key/session state and upgrade path visibility).

### 11) v0.7.0 beta policy note

For this beta phase, documentation and release flow were aligned around the current `v0.7.0` beta candidate state (private candidate, public channel still on `v0.5.3` until explicit publish decision).

## Reliability and Maintainability (High-Level)

Even though users do not see all of this directly, these changes matter:

- large internal refactor to reduce fragile monolithic code paths
- better test gates for animation/render critical paths
- improved error logging and diagnostics for faster issue resolution

## Practical Upgrade Advice (v0.5.3 -> v0.7.0)

1. Open a copy of your production `.blend` first.
2. Run `Create Earth` once in the new version.
3. Run `Scene Health Check` and resolve warnings.
4. Test short `Quick Preview` and short `Final Animation Render` before long production jobs.
5. Validate segment transitions visually in your real shot path.

## Summary in One Line

`v0.7.0` is a workflow-and-reliability release: safer scene behavior, much improved UI-based animation rendering, and significantly stronger stability for long segmented Earth animations.

## Reference Sources

- `CHANGELOG.md`
- `Documentation/Release/COMPATIBILITY_MATRIX.md`
- `Documentation/Release/FREE_TEST_GROUP_RELEASE_CHECKLIST.md`
- `Documentation/Developer/CYCLES_SVM_TILE_LIMIT.md`
- `Documentation/Developer/TILE_LOADING_STATIC_12_DESIGN.md`
