"""Typed context objects for the view telemetry runtime.

``state.py`` owns the singleton context and installs it into
``view_telemetry`` so low-level telemetry helpers can stop depending on the
facade's ``globals()`` dictionary.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ViewTelemetryDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    camera_inside_earth_warning_key: str
    get_earth_object: Any
    get_tile_utils: Any
    get_streaming_utils: Any
    normalize_texture_quality_mode: Any


@dataclass(slots=True)
class ViewTelemetryContext:
    deps: ViewTelemetryDeps
