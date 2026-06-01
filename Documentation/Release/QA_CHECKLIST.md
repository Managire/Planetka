# Planetka QA Checklist

## Core Workflow

- [ ] Create Earth works in a new `.blend` file.
- [ ] Rebuild Earth keeps atmosphere and clouds intact.
- [ ] Search, navigation presets, camera movement, and clipping controls work.
- [ ] Scene Health Check reports valid state for a clean scene.

## Data Control

- [ ] Preview resolve completes.
- [ ] Balanced resolve completes.
- [ ] Full Quality resolve completes.
- [ ] Quality level changes update Earth surface, texture-based clouds, and VDB cloud LODs consistently.
- [ ] Data Control progress displays surface data, texture-based cloud data, and VDB cloud data separately when downloading.
- [ ] Long-open scenes do not get stuck in a prepare/finalize resolve loop.

## Licence Model

- [ ] UI and docs show Personal / Commercial, not obsolete feature-tier names.
- [ ] Personal and Commercial licences have identical feature access.
- [ ] Commercial-use wording is clear: commercial use requires Commercial Licence.
- [ ] Analytics displays Personal / Commercial / Total metrics.
- [ ] Licence/API activation and recovery work if cloud access is gated.

## Rendering And Export

- [ ] Final Animation Render starts, stops safely, and can restart after interruption.
- [ ] Panoramic camera support works.
- [ ] Standalone file export works.
- [ ] Optimize Render Settings applies expected EEVEE/Cycles settings.

## Clouds And Atmosphere

- [ ] Global Clouds load by default and use reference material defaults.
- [ ] Texture-based clouds add, display, resolve LOD, and update LOD when size/position changes.
- [ ] VDB clouds add, display, resolve LOD, and update LOD when size/position changes.
- [ ] Clouds remain parented to Planetka Root.
- [ ] Atmosphere switches correctly when auto-switch atmosphere is enabled.
