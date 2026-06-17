import logging
import json
import os
import sys
import tempfile
import threading
import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

EARTH_OBJECT_DEFAULT_NAME = "Planetka Earth Surface"
EARTH_ROLE_KEY = "planetka_role"
EARTH_ROLE_VALUE = "earth_preview"

logger = logging.getLogger(__name__)
_SESSION_STORE = None
_SESSION_STORE_LOCK = threading.Lock()


def _session_store_path():
    override = str(os.getenv("PLANETKA_SESSION_FILE") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "Planetka", "cloud_session.json")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "Planetka", "cloud_session.json")
    base = os.getenv("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "planetka", "cloud_session.json")


class PlanetkaSessionStore:
    _defaults = {
        "cloud_install_id": "",
        "cloud_session_access_token": "",
        "cloud_session_refresh_token": "",
        "cloud_session_status_message": "",
        "cloud_session_edition": "free",
        "cloud_service_status_message": "",
        "cloud_service_status_url": "",
        "cloud_service_status_severity": "info",
        "cloud_service_status_updated_at": "",
    }

    def __init__(self, path):
        object.__setattr__(self, "_path", str(path or ""))
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_data", dict(self._defaults))
        self._load()

    def _load(self):
        path = object.__getattribute__(self, "_path")
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.debug("Planetka: failed reading cloud session store", exc_info=True)
            return
        if not isinstance(payload, dict):
            return
        with object.__getattribute__(self, "_lock"):
            data = object.__getattribute__(self, "_data")
            for key in self._defaults:
                if key in payload:
                    data[key] = str(payload.get(key, "") or "")

    def _save(self):
        path = object.__getattribute__(self, "_path")
        if not path:
            return
        directory = os.path.dirname(path)
        try:
            os.makedirs(directory, exist_ok=True)
            data = dict(object.__getattribute__(self, "_data"))
            fd, tmp_path = tempfile.mkstemp(prefix=".cloud_session.", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (OSError, TypeError, ValueError):
            logger.debug("Planetka: failed writing cloud session store", exc_info=True)

    def __getattr__(self, name):
        if name in self._defaults:
            with object.__getattribute__(self, "_lock"):
                return object.__getattribute__(self, "_data").get(name, self._defaults[name])
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name not in self._defaults:
            object.__setattr__(self, name, value)
            return
        with object.__getattribute__(self, "_lock"):
            object.__getattribute__(self, "_data")[name] = str(value or "")
            self._save()


def mark_earth_object(obj):
    if not obj:
        return
    try:
        obj[EARTH_ROLE_KEY] = EARTH_ROLE_VALUE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass


def get_earth_surface_candidates():
    data = getattr(bpy, "data", None)
    objects = getattr(data, "objects", None) if data is not None else None
    if objects is None:
        return []

    # Strict identity rule:
    # Only an object with the canonical name is considered the active Earth surface.
    # If the user renames it, Planetka treats the surface as missing.
    by_name = objects.get(EARTH_OBJECT_DEFAULT_NAME)
    if by_name and getattr(by_name, "type", None) == 'MESH':
        return [by_name]
    return []


def get_earth_object():
    candidates = get_earth_surface_candidates()
    return candidates[0] if candidates else None


def get_prefs():
    global _SESSION_STORE
    with _SESSION_STORE_LOCK:
        if _SESSION_STORE is None:
            _SESSION_STORE = PlanetkaSessionStore(_session_store_path())
        return _SESSION_STORE
