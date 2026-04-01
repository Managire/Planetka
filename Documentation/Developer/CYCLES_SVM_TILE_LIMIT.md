# Cycles SVM Tile Limit (Planetka Earth Material)

Last updated: `2026-04-01`

## Summary

Blender Cycles can hit:

`ERROR Shader graph: out of SVM stack space, shader "Planetka Earth Material" too big.`

for camera views that require too many dynamic tiles in one resolve.

In Planetka tests (`Cairo.blend`, Blender `5.1.0`, Cycles), the practical threshold was:

- `<= 12` tiles: stable
- `>= 13` tiles: overflow risk

Additional renderer stress observations (including EEVEE/Metal path) showed that dynamic slot-count topology changes and synthetic placeholder padding can trigger sampler overflow/instability in some camera states. Planetka now keeps only real resolved tiles and uses a static 12-slot loader with explicit slot-active masking:

- minimum floor: `0` (no synthetic placeholders)
- maximum budget: `12`
- static loader slots: `12` (topology fixed; only assignments/active masks change per resolve)

## Root Cause (Observed)

The overflow is not caused by tile file size itself. The critical factor is total compiled shader complexity when both:

- Surface output is connected, and
- Displacement path is active with per-tile EL branch participation.

## Implemented Mitigation

Tile count window is enforced upstream in `tile_utils.py` before shader assignment:

- `MAX_SHADER_TILE_BUDGET = 12`
- `MIN_SHADER_TILE_FLOOR = 0`
- `_enforce_shader_tile_budget(...)` merges sibling tiles into parent tiles until `<= 12`.
- `_enforce_shader_tile_floor(...)` is effectively disabled (`0`) to avoid placeholder-driven sampler overflow.
- texture loading group is kept static at 12 slots in `shader_utils.py` (testing loader path) to avoid per-resolve topology churn.
- unused slots are clipped via per-slot active mask (`effective_alpha = tile_alpha * slot_active`), so placeholders cannot influence visible color/displacement.

Guardrails used by the merge optimizer:

1. Visible coverage cannot be dropped.
2. Requested quality cannot be reduced (`d` cannot become worse).
3. If merging is not possible without violating quality constraints, tiles are kept and warning is logged.

## Diagnostics

`tile_utils.get_last_tile_budget_trace()` returns:

- input tiles
- output tiles
- exact merge replacements
- budget used

`shader_utils.py` also logs an error if shader stage receives more than the expected budget, to catch upstream regressions.

## Important Policy

Do not add shader-stage tile capping. Tile count control must stay in tile selection (`tile_utils.py`) so coverage/quality rules are explicit and testable.

## Regression Check

For material/tile logic changes, re-run a Cairo-style reproduction and confirm:

1. Resolve output tile count remains `<= 12`.
2. Resolve output contains only real resolved tiles (no synthetic placeholders).
3. Cycles render completes without SVM overflow.
4. No coverage holes are introduced by merge replacements.
5. EEVEE segment-boundary renders do not emit `sampler(...) out of bounds` and do not show placeholder-driven brightness shifts.

For wiring details, see:

- `Documentation/Developer/TILE_LOADING_STATIC_12_DESIGN.md`
