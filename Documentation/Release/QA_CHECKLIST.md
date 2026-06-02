# Planetka QA Checklist

## Core Workflow

- [ ] Create Earth works in a new `.blend` file.
- [ ] Search, navigation presets, camera movement, and clipping controls work.
- [ ] Scene Health Check reports valid state for a clean scene.

## Data Control

- [ ] Preview resolve completes.
- [ ] Balanced resolve completes.
- [ ] Full Quality resolve completes.
- [ ] Quality level changes update Earth surface, texture-based clouds, and VDB cloud LODs consistently.
- [ ] Data Control progress displays surface data, texture-based cloud data, and VDB cloud data separately when downloading.
- [ ] Long-open scenes do not get stuck in a prepare/finalize resolve loop.

## Cloud Access Model

- [ ] The add-on connects to Planetka Cloud automatically without account, email, or API-key prompts.
- [ ] All quality levels and feature panels remain available in the UI.
- [ ] Admin block/unblock is the only runtime access-control branch.
- [ ] Analytics reports total cloud_installs and usage without feature-class splits.

## Rendering And Export

- [ ] Final Animation Render starts, stops safely, and can restart after interruption.
- [ ] Panoramic camera support works.
- [ ] Standalone file export works.

## Rollback-Safe Update Testing

- [ ] Update manifest points to a downloadable ZIP with matching SHA-256.
- [ ] Legal document endpoints return HTTP 200.
- [ ] Previously installed addon can be disabled, updated, re-enabled, and still auto-connects anonymously.
- [ ] If update validation fails, the previous installed addon remains usable.

## Clouds And Atmosphere

- [ ] Global Clouds load by default and use reference material defaults.
- [ ] Texture-based clouds add, display, resolve LOD, and update LOD when size/position changes.
- [ ] VDB clouds add, display, resolve LOD, and update LOD when size/position changes.
- [ ] Clouds remain parented to Planetka Root.
- [ ] Atmosphere switches correctly when auto-switch atmosphere is enabled.
