# Planetka Studio Build Notes

`Planetka Studio` is the personal/internal Blender build used for production work and experiments.

## Branding

- Blender-facing name: `Planetka Studio`
- Sidebar tab: `Planetka Studio`
- Backend edition code: `pro`

The backend edition code intentionally remains `pro` so this build keeps full hosted-data access. The displayed edition label is read from `Resources/planetka_edition.json` and is set to `Studio`.

## Internal Names

Python package names, operator identifiers, custom properties, object prefixes, material names, and node group names still use `planetka` / `Planetka`.

Do not mechanically rename those identifiers for branding. They are runtime contracts used by:

- existing `.blend` files;
- Blender operator registration, for example `bpy.ops.planetka.resolve_planetka`;
- custom scene/object properties;
- material and node-group lookup code;
- backend telemetry and hosted-data authentication.

## Resolve Flow

`Resolve Planetka Studio` is the central data operation. It should remain deterministic:

1. read the current camera and Quality Level;
2. calculate required Earth surface tiles;
3. download/cache missing data;
4. rebuild/apply the Earth surface material and mesh assignment;
5. update texture-based cloud and VDB cloud assets.

Rendering should not trigger data downloads. Cloud transform edits and Quality Level toggles are inputs for the next manual resolve, not automatic resolve triggers.

## Public/Sale Build

The smaller public/sale add-on can be created from this codebase later by changing the Blender-facing branding and package marker while keeping shared runtime modules where appropriate.
