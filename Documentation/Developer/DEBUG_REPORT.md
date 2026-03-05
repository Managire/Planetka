# Planetka Bug Report JSON

The `planetka.report_bug` operator exports a minimal JSON report and opens an email draft.

## Output Fields

Current payload includes:

- `generated_at_utc`
- `addon`
- `blender_version`
- `blender_version_string`
- `python_version`
- `platform`
- `scene_name`
- `render_engine`

## Runtime Location

- Operator implementation:
  - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/validation.py`

## Notes

- This is intentionally minimal for public support workflows.
- It does not include legacy driver/rig/atmosphere diagnostics.
