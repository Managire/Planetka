"""
Planetka large-tile resolve speed benchmark.

- Picks the largest S2_*_z001_d001.exr tiles from local Planetka Assets.
- Positions camera above a tile-corner target so resolve is pushed to fetch a multi-tile neighborhood.
- Runs Resolve (no render) and captures download metrics.
- Compares with local network quality test output (run separately in shell).

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_large_tile_speed_test.py

Optional env:
  PLANETKA_MODULE=<module name>
  PLANETKA_AUTH_PAYLOAD=/tmp/planetka_auth_payload_largebench.json
  PLANETKA_ASSETS_DIR=/Volumes/SSDA/Planetka Assets
  PLANETKA_SPEED_TEST_COUNT=6
  PLANETKA_SPEED_TEST_ALT_KM=30
  PLANETKA_SPEED_TEST_REPORT=/Volumes/SSDA/Renders/planetka_large_tile_speed_report.json
"""

from __future__ import annotations

import heapq
import importlib
import json
import math
import os
import re
import sys
import time
import traceback
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

import addon_utils
import bpy
from mathutils import Matrix, Quaternion, Vector

TAG = "[Planetka Large Tile Speed]"
DEFAULT_ASSETS_DIR = "/Volumes/SSDA/Planetka Assets"
DEFAULT_REPORT_PATH = "/Volumes/SSDA/Renders/planetka_large_tile_speed_report.json"
TILE_RE = re.compile(r"^S2_x(\d{3})_y(\d{3})_z001_d001\.exr$", re.IGNORECASE)
CACHE_FOLDERS = ("S2", "EL", "WT", "PO", "DT")


def _log(message: str) -> None:
    print(f"{TAG} {message}")


def _fail(message: str) -> None:
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _enable_module():
    candidates = _unique(
        [
            os.environ.get("PLANETKA_MODULE"),
            "bl_ext.user_default.Planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue

    addon_root = _addon_root()
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
        module = importlib.import_module(package_name)
        if hasattr(module, "register"):
            try:
                module.unregister()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            module.register()
        if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
            _log(f"Enabled addon module via local import: {package_name}")
            return package_name
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    return None


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.Planetka.{submodule_name}",
            f"Planetka.{submodule_name}",
            f"planetka.{submodule_name}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    _fail(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new("Planetka Speed Camera")
    camera_obj = bpy.data.objects.new("Planetka Speed Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _earth_radius_bu(earth_obj):
    try:
        stored = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except TOOL_RECOVERABLE_EXCEPTIONS:
        stored = 0.0
    if stored > 1e-9:
        try:
            max_scale = max(abs(float(v)) for v in earth_obj.scale)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            max_scale = 1.0
        return float(stored) * float(max_scale)
    try:
        values = [Vector(corner).length for corner in earth_obj.bound_box]
        if values:
            return max(values)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    return 1.0


def _set_camera_direct(camera, earth_obj, lon_deg, lat_deg, altitude_km, azimuth_deg=35.0, tilt_deg=20.0, roll_deg=0.0):
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    az = math.radians(float(azimuth_deg))
    tilt = math.radians(float(tilt_deg))
    roll = math.radians(float(roll_deg))

    center = earth_obj.matrix_world.translation.copy()
    radius = max(1e-6, float(_earth_radius_bu(earth_obj)))
    altitude_bu = (max(0.0, float(altitude_km)) / 6371.0) * radius

    normal = Vector((
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ))
    if normal.length_squared <= 1e-12:
        normal = Vector((0.0, 0.0, 1.0))
    normal.normalize()

    world_up = Vector((0.0, 0.0, 1.0))
    east = world_up.cross(normal)
    if east.length_squared <= 1e-12:
        east = Vector((0.0, 1.0, 0.0))
    east.normalize()
    north = normal.cross(east)
    if north.length_squared <= 1e-12:
        north = Vector((1.0, 0.0, 0.0))
    north.normalize()

    tangent = (north * math.cos(az)) + (east * math.sin(az))
    if tangent.length_squared <= 1e-12:
        tangent = north
    tangent.normalize()

    cam_pos = center + normal * (radius + altitude_bu)
    look_dir = ((-normal) * math.cos(tilt)) + (tangent * math.sin(tilt))
    if look_dir.length_squared <= 1e-12:
        look_dir = -normal
    look_dir.normalize()

    rotation = look_dir.to_track_quat("-Z", "Y")
    if abs(roll) > 1e-9:
        rotation = Quaternion(look_dir, roll) @ rotation

    _location, _rot, scale = camera.matrix_world.decompose()
    camera.matrix_world = Matrix.LocRotScale(cam_pos, rotation, scale)


def _wrap_x(x):
    return int(x) % 360


def _clamp_y(y):
    return int(max(0, min(179, int(y))))


def _tile_corner_target(x: int, y: int):
    # Northeast corner of the tile (shared by up to 4 neighboring z001 tiles).
    corner_x = _wrap_x(int(x) + 1)
    corner_y = _clamp_y(int(y) + 1)
    lon = float(corner_x - 180.0)
    lat = float(corner_y - 90.0)
    return lon, lat


def _corner_neighbor_tiles(x: int, y: int):
    # 4 tiles touching the selected northeast corner.
    return (
        (_wrap_x(x), _clamp_y(y)),
        (_wrap_x(x + 1), _clamp_y(y)),
        (_wrap_x(x), _clamp_y(y + 1)),
        (_wrap_x(x + 1), _clamp_y(y + 1)),
    )


def _pick_largest_tiles(assets_dir: str, count: int):
    s2_dir = os.path.join(assets_dir, "S2")
    if not os.path.isdir(s2_dir):
        _fail(f"S2 folder not found: {s2_dir}")

    top = []
    with os.scandir(s2_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            name = entry.name
            match = TILE_RE.match(name)
            if not match:
                continue
            try:
                size = int(entry.stat().st_size)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                continue
            if len(top) < count:
                heapq.heappush(top, (size, name))
            else:
                if size > top[0][0]:
                    heapq.heapreplace(top, (size, name))

    if not top:
        _fail("No S2_*_z001_d001.exr files found.")

    rows = sorted(top, key=lambda item: item[0], reverse=True)
    out = []
    for size, name in rows:
        m = TILE_RE.match(name)
        x = int(m.group(1))
        y = int(m.group(2))
        lon = (x + 0.5) - 180.0
        lat = (y + 0.5) - 90.0
        out.append({
            "name": name,
            "size_bytes": size,
            "x": x,
            "y": y,
            "lon": lon,
            "lat": lat,
        })
    return out


def _default_cache_root():
    home = os.path.abspath(os.path.expanduser("~"))
    return os.path.join(home, "Library", "Caches", "Planetka", "r2_cache")


def _resolve_cache_root(r2_source_module):
    env_override = str(os.environ.get("PLANETKA_R2_CACHE_DIR") or "").strip()
    if env_override:
        return env_override
    getter = getattr(r2_source_module, "get_config", None)
    if callable(getter):
        try:
            cfg = getter()
            value = str(getattr(cfg, "cache_root", "") or "").strip()
            if value:
                return value
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
    return _default_cache_root()


def _load_auth_payload(path):
    if not path:
        return None
    if not os.path.isfile(path):
        _fail(f"Auth payload file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
        _fail("Auth payload is invalid (missing access_token/refresh_token).")
    return payload


def _purge_cached_tile_variants(cache_root: str, x: int, y: int):
    if not cache_root or not os.path.isdir(cache_root):
        return []
    removed = []
    token = f"_x{x:03d}_y{y:03d}_z001_d001"
    for folder in CACHE_FOLDERS:
        folder_path = os.path.join(cache_root, folder)
        if not os.path.isdir(folder_path):
            continue
        try:
            for fname in os.listdir(folder_path):
                if token not in fname:
                    continue
                fpath = os.path.join(folder_path, fname)
                try:
                    os.remove(fpath)
                    removed.append(fpath)
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    continue
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    return removed


def _purge_cached_multi_tile_variants(cache_root: str, tile_coords):
    removed = []
    seen = set()
    for x, y in tile_coords:
        for path in _purge_cached_tile_variants(cache_root, int(x), int(y)):
            if path in seen:
                continue
            seen.add(path)
            removed.append(path)
    return removed


def main():
    started = time.time()
    assets_dir = str(os.environ.get("PLANETKA_ASSETS_DIR") or DEFAULT_ASSETS_DIR).strip()
    count = max(1, int(os.environ.get("PLANETKA_SPEED_TEST_COUNT") or "6"))
    altitude_km = float(os.environ.get("PLANETKA_SPEED_TEST_ALT_KM") or "30")
    report_path = str(os.environ.get("PLANETKA_SPEED_TEST_REPORT") or DEFAULT_REPORT_PATH).strip()
    auth_payload_path = str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip()

    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module")

        auth_module = _import_submodule(base_module_name, "auth")
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        diagnostics = _import_submodule(base_module_name, "diagnostics")
        r2_source = _import_submodule(base_module_name, "r2_source")
        state_module = _import_submodule(base_module_name, "state")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable")

        auth_payload = _load_auth_payload(auth_payload_path)
        if auth_payload:
            auth_module._apply_auth_payload(prefs, auth_payload)  # noqa: SLF001
        _assert(auth_module.is_authenticated(prefs), "Planetka Cloud session is not active in this Blender profile")

        scene = bpy.context.scene
        props = scene.planetka
        camera = _ensure_active_camera(scene)
        if getattr(camera, "data", None) is not None:
            try:
                camera.data.lens = 18.0
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

        props.texture_quality_mode = "FULL"
        props.show_earth_preview = False
        scene.render.engine = "CYCLES"
        prefs.texture_base_path = "planetka-remote"

        create_result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in create_result, f"Create Earth failed: {create_result}")

        cache_root = _resolve_cache_root(r2_source)

        tiles = _pick_largest_tiles(assets_dir, count)
        _log(f"Selected {len(tiles)} largest S2 z001_d001 tiles")
        for t in tiles:
            _log(f"  {t['name']} size={t['size_bytes']} ({t['size_bytes']/(1024**2):.2f} MB)")

        results = []
        for i, tile in enumerate(tiles, start=1):
            x = int(tile["x"])
            y = int(tile["y"])
            target_lon, target_lat = _tile_corner_target(x, y)
            neighbor_tiles = _corner_neighbor_tiles(x, y)

            removed = _purge_cached_multi_tile_variants(cache_root, neighbor_tiles)

            earth_obj = extension_prefs.get_earth_object()
            _assert(earth_obj is not None, f"Earth object missing before case {i}")

            state_module.suspend_navigation_shot_updates()
            try:
                props.nav_longitude_deg = target_lon
                props.nav_latitude_deg = target_lat
                props.nav_altitude_km = altitude_km
                props.nav_azimuth_deg = 45.0
                props.nav_tilt_deg = 0.0
                props.nav_roll_deg = 0.0
            finally:
                state_module.resume_navigation_shot_updates()

            _set_camera_direct(camera, earth_obj, target_lon, target_lat, altitude_km, azimuth_deg=45.0, tilt_deg=0.0)

            resolve_start = time.perf_counter()
            resolve_result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
            resolve_wall_ms = (time.perf_counter() - resolve_start) * 1000.0
            _assert("FINISHED" in resolve_result, f"Resolve failed for {tile['name']}: {resolve_result}")

            diag = diagnostics.read_diagnostics(scene)
            downloaded_mb_local = float(diag.get("resolve_downloaded_mb") or 0.0)
            downloaded_ms_local = float(diag.get("resolve_download_ms") or 0.0)
            speed_mb_s_local = 0.0
            if downloaded_ms_local > 0.0:
                speed_mb_s_local = downloaded_mb_local / (downloaded_ms_local / 1000.0)

            row = {
                "case": i,
                "tile_name": tile["name"],
                "tile_size_mb": round(tile["size_bytes"] / (1024.0 * 1024.0), 3),
                "target_corner_longitude_deg": round(target_lon, 6),
                "target_corner_latitude_deg": round(target_lat, 6),
                "neighbor_tiles_xy": [f"x{nx:03d}_y{ny:03d}" for nx, ny in neighbor_tiles],
                "altitude_km": altitude_km,
                "cache_files_removed": len(removed),
                "resolve_wall_ms": round(resolve_wall_ms, 3),
                "resolve_downloaded_mb_local": round(downloaded_mb_local, 6),
                "resolve_download_ms_local": round(downloaded_ms_local, 6),
                "resolve_speed_mb_s_local": round(speed_mb_s_local, 6),
                "resolve_tile_count": diag.get("last_tile_count"),
                "resolve_textures_mb": diag.get("resolve_textures_mb"),
            }
            results.append(row)
            _log(
                f"Case {i:02d} {tile['name']}: local={row['resolve_speed_mb_s_local']:.2f} MB/s, "
                f"download(all tiles/types)={row['resolve_downloaded_mb_local']:.2f} MB, "
                f"resolved_tiles={row['resolve_tile_count']}"
            )

        valid_speeds = [r["resolve_speed_mb_s_local"] for r in results if r["resolve_speed_mb_s_local"] > 0]
        avg_speed = sum(valid_speeds) / float(len(valid_speeds)) if valid_speeds else 0.0
        total_downloaded_mb = sum(float(row.get("resolve_downloaded_mb_local", 0.0) or 0.0) for row in results)

        report = {
            "ok": True,
            "assets_dir": assets_dir,
            "count": len(results),
            "altitude_km": altitude_km,
            "cache_root": cache_root,
            "elapsed_sec": round(time.time() - started, 3),
            "avg_resolve_speed_mb_s": round(avg_speed, 6),
            "total_downloaded_mb_local": round(total_downloaded_mb, 6),
            "cases": results,
        }

        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=True)

        _log(f"Report written: {report_path}")
        _log(f"Average resolve speed: {avg_speed:.2f} MB/s")
        _log(f"Total downloaded (all tiles/types): {total_downloaded_mb:.2f} MB")
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        _log(f"Unhandled error: {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
