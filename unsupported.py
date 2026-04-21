"""Unsupported advanced overrides for Planetka.

This file is intentionally not exposed in the normal addon UI.

These switches are UNSUPPORTED and used at your own risk:
- Planetka may not validate every edge case for these combinations.
- Planetka support should treat bugs reproduced only with these overrides as unsupported.
- Values here are applied automatically on addon register and on every Blender file load/new file.

Edit only the constants below.
"""

from __future__ import annotations

import logging
import os

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)


# Texture source override.
# Allowed values: "CLOUD", "LOCAL"
TEXTURE_SOURCE_MODE_UNSUPPORTED = "LOCAL"

# Used only when TEXTURE_SOURCE_MODE_UNSUPPORTED = "LOCAL".
LOCAL_TEXTURES_ROOT_UNSUPPORTED = "/Volumes/SSDA/Planetka Assets/"


_UNSUPPORTED_WARNING_EMITTED = False


def _normalize_token(value: str, allowed: set[str], default: str) -> str:
    token = str(value or "").strip().upper()
    if token not in allowed:
        return str(default)
    return token


def get_unsupported_texture_source_mode() -> str:
    return _normalize_token(
        TEXTURE_SOURCE_MODE_UNSUPPORTED,
        {"CLOUD", "LOCAL"},
        "CLOUD",
    )


def get_unsupported_texture_base_path() -> str:
    if get_unsupported_texture_source_mode() == "LOCAL":
        return os.path.abspath(os.path.expanduser(str(LOCAL_TEXTURES_ROOT_UNSUPPORTED or "").strip()))
    return "planetka-remote"


def has_unsupported_overrides_enabled() -> bool:
    return get_unsupported_texture_source_mode() != "CLOUD"


def _warn_once_if_enabled() -> None:
    global _UNSUPPORTED_WARNING_EMITTED
    if _UNSUPPORTED_WARNING_EMITTED or not has_unsupported_overrides_enabled():
        return
    _UNSUPPORTED_WARNING_EMITTED = True
    logger.warning(
        "Planetka: unsupported overrides from unsupported.py are active "
        "(texture_source=%s). Use at your own risk.",
        get_unsupported_texture_source_mode(),
    )


def apply_runtime_unsupported_overrides() -> None:
    """Apply unsupported texture-source overrides to prefs."""
    _warn_once_if_enabled()

    try:
        from .extension_prefs import get_prefs
        from .r2_source import on_cache_settings_updated, reset_config_cache
        from .sanity_utils import invalidate_texture_source_health_cache
    except ImportError:
        return

    prefs = get_prefs()
    texture_base_path = str(get_unsupported_texture_base_path() or "").strip()

    if prefs is not None:
        try:
            if str(getattr(prefs, "texture_base_path", "") or "").strip() != texture_base_path:
                prefs.texture_base_path = texture_base_path
                invalidate_texture_source_health_cache(texture_base_path)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying unsupported texture source override", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
            logger.debug("Planetka: failed applying unsupported texture source override", exc_info=True)

    try:
        reset_config_cache()
        on_cache_settings_updated(force_prune=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed refreshing cache config after unsupported overrides", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka: failed refreshing cache config after unsupported overrides", exc_info=True)
