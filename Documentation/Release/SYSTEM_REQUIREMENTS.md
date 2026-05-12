# Planetka System Requirements

These are user-facing requirements for Planetka public release use.

## Supported Blender versions

- Primary supported version: Blender 5.0.
- Blender 4.5 LTS and newer Blender versions may work, but should be tested before production use.

## Operating systems

Planetka is developed and tested primarily on macOS. Windows and Linux may work if Blender, Python, graphics drivers, and network access are correctly configured, but should be verified before production use.

## Internet access

Planetka is an online streaming product. Creating Earth, resolving Preview textures, checking Full Quality prices, purchasing Full Quality data, downloading licenced tiles, and opening Planetka web pages require internet access.

If the computer is offline or Planetka services cannot be reached, the add-on should show a connection warning and online workflows may be unavailable.

## Disk space

Planetka uses local cache storage for streamed and licenced texture data. Required space depends on the selected scene, quality mode, data packs, and download choices. Full Quality data packs can require substantial disk space.

## GPU and rendering

Planetka can be used with Blender EEVEE and Cycles. Higher-resolution textures, close camera views, high render resolutions, and animation workflows require more GPU memory and system memory.

## Account and payments

Preview texture access is free for personal, non-commercial use. Full Quality texture data requires a completed licence purchase, promotional grant, or other authorised entitlement.
