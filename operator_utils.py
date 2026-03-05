from .error_utils import with_error_code


class ErrorCode:
    NO_ACTIVE_SCENE = "PKA-CORE-001"
    PROPS_MISSING = "PKA-CORE-002"

    ADD_EARTH_IMPORT_FAILED = "PKA-ADD-002"
    ADD_EARTH_SHORTCUT_FAILED = "PKA-ADD-003"

    RESOLVE_PREFS_MISSING = "PKA-RES-001"
    RESOLVE_PATH_INVALID = "PKA-RES-002"
    RESOLVE_PRECHECK_FAILED = "PKA-RES-003"
    RESOLVE_REFRESH_FAILED = "PKA-RES-006"

    NAV_PRECHECK_FAILED = "PKA-NAV-001"
    NAV_APPLY_FAILED = "PKA-NAV-002"

    RENDER_FAILED = "PKA-REN-001"

    IO_DEBUG_REPORT_FAILED = "PKA-IO-003"


def fail(operator, message, code=None, logger=None, exc=None, log_message=None):
    coded_message = with_error_code(code, message)
    if logger:
        if exc is not None:
            logger.exception(log_message or coded_message)
        else:
            logger.error(log_message or coded_message)
    operator.report({'ERROR'}, coded_message)
    return {'CANCELLED'}


def get_scene(context):
    return getattr(context, "scene", None) if context else None


def require_scene(operator, context, logger=None):
    scene = get_scene(context)
    if scene is None:
        fail(operator, "No active scene found.", code=ErrorCode.NO_ACTIVE_SCENE, logger=logger)
        return None
    return scene


def require_planetka_props(operator, context, logger=None):
    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        fail(
            operator,
            "Planetka settings not found on the active scene.",
            code=ErrorCode.PROPS_MISSING,
            logger=logger,
        )
        return None
    return props
