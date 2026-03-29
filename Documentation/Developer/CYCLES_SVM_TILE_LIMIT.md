# Cycles SVM Tile Limit (Planetka Earth Material)

Last updated: `2026-03-29`

## Summary

Blender Cycles can hit:

`ERROR Shader graph: out of SVM stack space, shader "Planetka Earth Material" too big.`

for camera views that require too many dynamic tiles in one resolve.

In Planetka tests (`Cairo.blend`, Blender `5.1.0`, Cycles), the practical threshold was:

- `<= 12` tiles: stable
- `>= 13` tiles: overflow risk

## Root Cause (Observed)

The overflow is not caused by tile file size itself. The critical factor is total compiled shader complexity when both:

- Surface output is connected, and
- Displacement path is active with per-tile EL branch participation.

## Implemented Mitigation

Tile budget is enforced upstream in `tile_utils.py` before shader assignment:

- `MAX_SHADER_TILE_BUDGET = 12`
- `_enforce_shader_tile_budget(...)` merges sibling tiles into parent tiles until `<= 12`.

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
2. Cycles render completes without SVM overflow.
3. No coverage holes are introduced by merge replacements.
