# Tile Loading Static-12 Design (Cycles + EEVEE)

Last updated: `2026-04-01`

## Purpose

This document describes the current stable tile-loading architecture for `Planetka Earth Material` and why the loader is intentionally static (12 slots) instead of dynamically rebuilt each resolve.

Scope is internal implementation detail for:

- `shader_utils.py`
- `tile_utils.py`
- animation segment-boundary resolve behavior

## Current Architecture

### 1) Upstream tile selection (real tiles only)

`tile_utils.py` computes visible tiles and applies hard rules:

- Keep visible coverage.
- Never reduce requested quality (`d` cannot be degraded).
- Merge to parent tiles when necessary to stay within shader budget.

Budget:

- `MAX_SHADER_TILE_BUDGET = 12`
- no synthetic floor padding

So shader assignment receives `0..12` real tiles only.

### 2) Static 12-slot texture loading group

`Planetka Textures Loading Group` is built once as a static graph with 12 tile slots:

- `Tile_001..Tile_012` (`ShaderNodeGroup`, placement only)
- per slot texture nodes:
  - `TileImg_###_S2`
  - `TileImg_###_EL`
  - `TileImg_###_WT`
  - `TileImg_###_PO`
- per slot active mask:
  - `TileActive_###` (`ShaderNodeValue`)
  - `TileAlpha_###` (`effective_alpha = placement_alpha * TileActive_###`)

Outputs are combined with balanced add trees:

- color channels (`S2`, `WT`, `SE`) are weighted by `effective_alpha`
- `EL` is scalar-weighted by `effective_alpha`
- global alpha is clamped/normalized, then color and EL are normalized by alpha denominator

Unused slots are not removed; they are deactivated:

- `TileActive_### = 0.0`
- fallback images assigned

This guarantees invisible slots contribute zero, independent of placeholder content.

### 3) Runtime update model

Per resolve, `update_shader_nodes(...)` only:

- writes slot transforms (`x,y,z,d`)
- swaps images/fallbacks
- toggles slot active state

It does **not** rebuild node topology during normal resolve.

## Why Static-12 (Observed Failures With Dynamic Slot Counts)

### Issue A: Cycles SVM overflow above real-tile threshold

Observed in Cairo repro:

- `<= 12` real tiles: stable
- `>= 13` real tiles: Cycles SVM overflow risk

This is solved by upstream real-tile budget enforcement in `tile_utils.py`.

### Issue B: EEVEE/Metal sampler instability with dynamic graph rebuild

When loader topology/sampler set changed per resolve (especially at animation segment boundaries), EEVEE could emit:

- `sampler attribute parameter is out of bounds: must be between 0 and 15`

and render black/skewed tile artifacts.

Static topology removed this class of boundary instability in our repros.

### Issue C: Placeholder leakage into visible result

When unused slots relied on mute/fallback behavior alone, segment-to-segment brightness drift could occur.

Explicit slot active masking (`TileActive_###`) fixed this by forcing zero alpha contribution for unused slots.

## Validation Checklist

For any tile-loader edit, verify:

1. Cairo repro, EEVEE, problematic frames/segments render without sampler errors.
2. Cairo repro, Cycles, no SVM overflow at valid tile counts.
3. Animation segment boundaries do not introduce brightness jumps from hidden slots.
4. Hidden-slot mutation test:
   - Change unused slot images aggressively.
   - Keep `TileActive_### = 0`.
   - Confirm visible output remains unchanged (aside from normal EEVEE run-to-run noise).

## Guardrails (Do Not Change Without Full Revalidation)

1. Do not reintroduce per-resolve topology rebuild in testing/static loader path.
2. Do not reintroduce synthetic floor padding as a primary mechanism.
3. Keep slot-active masking in the shader graph for unused slots.
4. Keep tile budget enforcement upstream in `tile_utils.py` (selection layer), not by silently dropping shader slots.

