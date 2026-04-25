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
    is_idprop_syncing: Any
    is_camera_control_syncing: Any
    get_camera_control_sync_suspend_count: Any
    nav_force_camera_once_key: str
    nav_sync_active_view_once_key: str
    sunlight_object_name: str
    sync_idprops_from_props: Any
    sync_navigation_idprops_from_props: Any
    suspend_adaptive_viewport_during_navigation: Any
    request_auto_resolve: Any


@dataclass(slots=True)
class NavigationRuntimeState:
    nav_camera_control_last_signature: dict = field(default_factory=dict)
    navigation_adaptive_suspended: Any = None
    navigation_adaptive_last_touch: float = 0.0
    navigation_adaptive_timer_running: bool = False
    navigation_adaptive_idle_sec: float = 0.5
    navigation_shot_update_pending: bool = False
    navigation_shot_update_reentrant: bool = False
    navigation_shot_suspend_count: int = 0
    navigation_user_edit_last_touch: float = 0.0


@dataclass(slots=True)
class NavigationRuntimeContext:
    deps: NavigationRuntimeDeps
    state: NavigationRuntimeState
