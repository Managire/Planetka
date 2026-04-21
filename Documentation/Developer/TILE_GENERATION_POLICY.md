# Tile Generation Policy (Higher-Z / Higher-D)

This is a hard rule for Planetka source tile generation.

## Interpolation / Resampling

- **EL and S2**: use **area/box downsampling** (`INTER_AREA`) for higher-z and higher-d generation.
- **EL and S2**: if area/box is not available for a specific resize path, use **linear** (`INTER_LINEAR`) fallback.
- **WT**: use **linear** (`INTER_LINEAR`) for higher-z and higher-d generation (to match Blender interpolation expectations).
- Do **not** use bicubic/cubic interpolation for higher-z/higher-d generation.

## Mip Chain

- **S2**: higher-d is generated from the **single lowest-d source available for that z** (not step-by-step mip chaining).
  - For `z001`, generate all higher-d directly from `z001_d001`.
  - For other z levels, generate all higher-d directly from `z{N}_d{N}` (or the mapped lowest source described below).
- **EL**: keep strict mip-chain behavior from the previous d level.

## S2 Source Mapping (Higher-Z Base Tiles)

- `z002_d002`, `z004_d004`, `z008_d008`, `z015_d015` are built from `z001_d001` sources.
- `z016_d016` and `z032_d032` are built from `z008_d008` sources.
- `z030_d030`, `z060_d060`, `z090_d090`, `z180_d180`, `z360_d360` are built from `z015_d015` sources.

## Image Processing Between Levels

- Do **not** add sharpening.
- Do **not** add contrast tweaks.
- Do **not** add noise reduction.

## WT Fallback Policy (Generation)

- Default WT fallback for missing source tiles: **blue**
  - `/Volumes/SSDA/Planetka Assets Extra/FB/blue_pixel_20.exr`
- Red lake overrides (use **red** fallback, not blue), by tile-index regions:
  - Caspian Sea: `x226-x236`, `y125-y139`
  - Lake Superior: `x086-x098`, `y134-y142`
  - `/Volumes/SSDA/Planetka Assets Extra/FB/red_pixel_20.exr`
- Pacific blue override (force **blue** in this region): `x046-x055`, `y125-y140`
- Antarctica override: use **black** fallback only where `y <= 9`
  - `/Volumes/SSDA/Planetka Assets Extra/FB/black_pixel_20.exr`
- For Antarctica tiles with `y >= 10`, use the usual **blue** fallback unless another explicit override applies.

Current implementation reference:

- `tools/s2_clamp_rebuild.py`
- `tools/wt_fix_rebuild.py`
