# Planetka Codebase Audit (2026-03-24)

## Scope
- Runtime resolve consistency (manual vs auto trigger paths).
- Background download pipeline finalization.
- Telemetry/status visibility during long-running operations.
- Packaging/runtime hygiene for Blender 5.1.

## Key outcomes
- Fixed queued-resolve finalization stall caused by epoch handling (`epoch=0` being treated as `-1`).
- Restored non-blocking resolve behavior (downloads in background, finalize afterward).
- Added user-facing runtime Status telemetry (queued/downloading/finalizing/idle).
- Stabilized manual-trigger intent in deduplicated queue jobs.
- Added module-level annotations for core modules (`state`, `render_prep`, `r2_source`, `ui`).

## Validation performed
- `compileall` over full extension source.
- Focused Blender background sanity scripts for:
  - queue dedupe behavior,
  - completion payload retention,
  - epoch persistence on worker finalize,
  - auto trigger path calling queue pipeline.

## Known weak areas
1. Large monolithic orchestrator
- `state.py` is large and carries multiple responsibilities (state sync, timers, queueing, handlers, telemetry).
- Recommendation: split into focused modules (`resolve_runtime.py`, `manual_resolve.py`, `scene_sync.py`).

2. Timer + context coupling
- Blender timer/context behavior is brittle and can regress quietly.
- Recommendation: keep explicit stage markers in scene diagnostics (not only console) and add automated UI-path regression scripts.

3. Blender 6.0 API deprecations
- Repeated `Material.use_nodes`/`World.use_nodes` deprecation warnings observed in Blender 5.1.
- Recommendation: migrate checks to node-tree existence patterns that are forward-safe for 6.0.

4. Heavy reliance on network/runtime conditions
- Resolve correctness depends on remote auth/session/stream health and network quality.
- Recommendation: add deterministic mock-mode tests for queue/finalize paths independent of live network.

## Production readiness
- Current readiness: **7.5 / 10** for controlled production testing.
- Strengths:
  - Core resolve now completes reliably in tested scenarios.
  - User feedback loop improved via live status telemetry.
  - Non-blocking background downloads restored.
- Gaps before broad public release:
  - Add Blender 6.0 deprecation cleanup.
  - Expand automated regression coverage for timer/queue races.
  - Reduce orchestration complexity in `state.py`.
