# Planetka Error Handling Standard

## Scope

This note defines how runtime errors should be handled in Planetka Python modules.

## Rules

1. Do not use broad `except Exception` in addon runtime code.
2. Use typed exception handling with `PLANETKA_RECOVERABLE_EXCEPTIONS` from:
   - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/error_utils.py`
3. For operator failures, use `fail(...)` from:
   - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/operator_utils.py`
4. Always include a stable error code (`PKA-...`) for user-facing error reports.
5. Log internal details with `logger.exception(...)` only when needed for debugging.
6. Keep warnings recoverable and non-blocking where possible (for non-core steps).

## Error Code Format

- Format: `[PKA-<AREA>-<NNN>] Message`
- Example: `[PKA-RES-006] Planetka refresh failed: <details>`

## Current Code Areas

- `PKA-CORE-*` shared core prechecks
- `PKA-ADD-*` Create Earth
- `PKA-RES-*` Resolve Earth
- `PKA-IO-*` import/export settings
- `PKA-VAL-*` validation/repair

## Typical Pattern

```python
from .operator_utils import ErrorCode, fail
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

try:
    risky_call()
except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
    return fail(
        self,
        f"Operation failed: {exc}",
        code=ErrorCode.SOME_CODE,
        logger=logger,
        exc=exc,
    )
```

## Notes for Future Changes

1. When adding a new operator error path, add a new code in `ErrorCode`.
2. Keep code meanings stable; do not repurpose existing codes.
3. If a failure is expected and harmless, downgrade to warning and avoid canceling core flow.
4. Run smoke/schema scripts after changing exception handling:
   - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_smoke_test.py`
   - `/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_schema_migration_test.py`
