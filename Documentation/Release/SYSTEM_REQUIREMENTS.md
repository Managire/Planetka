# Planetka System Requirements

These are user-facing requirements for Planetka public release use.

Last updated: 2026-05-19

## Supported Blender versions

- Primary supported version: Blender 5.0.
- Blender 4.5 LTS and newer Blender versions may work, but should be tested before production use.

## Operating systems

Planetka is developed and tested primarily on macOS. Windows and Linux may work if Blender, Python, graphics drivers, and network access are correctly configured, but should be verified before production use.

## Internet access

Planetka is an online streaming product. Creating Earth, connecting an account, checking for updates, and resolving Preview, Balanced, or Full Quality textures require internet access.

If the computer is offline or Planetka services cannot be reached, the add-on should show a connection warning and online workflows may be unavailable.

## Disk space

Planetka uses temporary local cache storage for streamed texture data. Required space depends on the selected scene, quality mode, camera movement, and animation workflow.

The 0.8.2 add-on is not a raw-data download product. It does not provide a supported local archive of purchased data packs or licenced tiles.

## GPU and rendering

Planetka can be used with Blender EEVEE and Cycles. Higher-resolution textures, close camera views, high render resolutions, and animation workflows require more GPU memory and system memory.

## Account access

Planetka uses two account types:

- Free account: worldwide streaming in Preview and Balanced texture quality for personal use.
- Pro account: worldwide streaming in Preview, Balanced, and Full texture quality for commercial and personal use.

Pro checkout must be implemented and tested before paid public upgrades are offered.
