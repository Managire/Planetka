"""Scene-specific Full Quality licence helpers."""

from __future__ import annotations

import hashlib
import json


def canonical_scene_tiles(tiles):
    seen = set()
    result = []
    for tile in tiles or ():
        safe_tile = str(tile or "").strip()
        if not safe_tile or safe_tile in seen:
            continue
        seen.add(safe_tile)
        result.append(safe_tile)
    result.sort()
    return result


def scene_camera_payload(scene=None, props=None):
    payload = {}
    if props is not None:
        for key in (
            "nav_latitude_deg",
            "nav_longitude_deg",
            "nav_altitude_km",
            "earth_radius_bu",
        ):
            try:
                payload[key] = round(float(getattr(props, key, 0.0)), 6)
            except (TypeError, ValueError, RuntimeError, AttributeError):
                payload[key] = 0.0
        try:
            selected_place = str(getattr(props, "nav_city_selected_name", "") or "").strip()
            search_place = str(getattr(props, "nav_city_search", "") or "").strip()
            payload["place_name"] = selected_place or search_place
        except (TypeError, ValueError, RuntimeError, AttributeError):
            payload["place_name"] = ""
    camera = getattr(scene, "camera", None) if scene is not None else None
    if camera is not None:
        try:
            payload["camera_name"] = str(getattr(camera, "name", "") or "")
            payload["camera_matrix_world"] = [
                [round(float(value), 6) for value in row]
                for row in getattr(camera, "matrix_world", ())
            ]
        except (TypeError, ValueError, RuntimeError, AttributeError):
            payload["camera_matrix_world"] = []
        camera_data = getattr(camera, "data", None)
        if camera_data is not None:
            for key in ("lens", "angle", "sensor_width", "sensor_height", "type"):
                try:
                    value = getattr(camera_data, key, "")
                    payload[f"camera_{key}"] = round(float(value), 6) if isinstance(value, (int, float)) else str(value or "")
                except (TypeError, ValueError, RuntimeError, AttributeError):
                    payload[f"camera_{key}"] = ""
    return payload


def scene_license_payload(scene=None, props=None, full_quality_tiles=None):
    tiles = canonical_scene_tiles(full_quality_tiles)
    camera = scene_camera_payload(scene, props)
    tile_hash_source = "\n".join(tiles).encode("utf-8")
    tile_hash = hashlib.sha256(tile_hash_source).hexdigest()
    canonical_payload = {
        "version": 1,
        "camera": camera,
        "tiles": tiles,
        "tile_hash": tile_hash,
    }
    payload_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    scene_id = "scene_" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:32]
    return {
        "scene_id": scene_id,
        "camera": camera,
        "tiles": tiles,
        "tile_hash": tile_hash,
    }
