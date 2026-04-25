"""Typed context objects for the navigation runtime.

``state.py`` owns the singleton context and installs it into
``navigation_runtime`` so safe runtime slices can stop depending on facade
``globals()`` directly.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NavigationRuntimeDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    scene_key: Any
    camera_control_sync_signature: Any
    get_earth_object: Any
    sunlight_object_name: str
    sync_idprops_from_props: Any
    suspend_adaptive_viewport_during_navigation: Any
    request_auto_resolve: Any


@dataclass(slots=True)
class NavigationRuntimeState:
    nav_camera_control_last_signature: dict = field(default_factory=dict)
    navigation_adaptive_suspended: Any = None
    navigation_adaptive_last_touch: float = 0.0
    navigation_adaptive_timer_running: bool = False
    navigation_adaptive_idle_sec: float = 0.5


@dataclass(slots=True)
class NavigationRuntimeContext:
    deps: NavigationRuntimeDeps
    state: NavigationRuntimeState
