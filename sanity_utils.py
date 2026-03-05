import os
import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

_REQUIRED_TEXTURE_SOURCE_RULES = {
    "S2": {"prefix": "S2_", "ext": ".exr", "min_count": 2},
}
_OPTIONAL_TEXTURE_SOURCE_RULES = {
    "EL": {"prefix": "EL_", "ext": ".exr"},
    "WT": {"prefix": "WT_", "ext": ".exr"},
    "PO": {"prefix": "PO_", "ext": ".tif"},
}
_KNOWN_GOOD_S2_SENTINELS = (
    "S2_x000_y000_z180_d180.exr",
    "S2_x180_y000_z180_d180.exr",
)
_TEXTURE_SOURCE_VALIDATION_CACHE = {}
_TEXTURE_SOURCE_HEALTH_CACHE = {}


def invalidate_texture_source_health_cache(path=None):
    if not path:
        _TEXTURE_SOURCE_HEALTH_CACHE.clear()
        return
    normalized_path = _normalize_texture_source_path(path)
    if normalized_path:
        _TEXTURE_SOURCE_HEALTH_CACHE.pop(normalized_path, None)


def _normalize_texture_source_path(path):
    if not path:
        return ""

    abs_path = bpy.path.abspath(path)
    if os.path.isdir(abs_path):
        return abs_path

    if os.path.isfile(abs_path):
        return os.path.dirname(abs_path)

    _, ext = os.path.splitext(abs_path)
    if ext:
        return os.path.dirname(abs_path)

    return abs_path


def _count_texture_source_files(folder_path, prefix, ext):
    count = 0
    try:
        entries = os.scandir(folder_path)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return 0

    with entries as it:
        for entry in it:
            try:
                if not entry.is_file():
                    continue
                name = entry.name
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            if not name.startswith(prefix):
                continue
            if not name.lower().endswith(ext):
                continue
            count += 1
    return count


def _has_min_texture_source_files(folder_path, prefix, ext, min_count):
    found = 0
    target = max(1, int(min_count))
    try:
        entries = os.scandir(folder_path)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False

    with entries as it:
        for entry in it:
            try:
                if not entry.is_file():
                    continue
                name = entry.name
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            if not name.startswith(prefix):
                continue
            if not name.lower().endswith(ext):
                continue
            found += 1
            if found >= target:
                return True
    return False


def _texture_source_validation_signature(normalized_path):
    try:
        root_stat = os.stat(normalized_path)
        root_sig = (root_stat.st_mtime_ns, root_stat.st_size)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        root_sig = (None, None)

    folders = []
    all_folders = tuple(_REQUIRED_TEXTURE_SOURCE_RULES) + tuple(_OPTIONAL_TEXTURE_SOURCE_RULES)
    for folder_name in all_folders:
        folder_path = os.path.join(normalized_path, folder_name)
        if not os.path.isdir(folder_path):
            folders.append((folder_name, None, None))
            continue
        try:
            st = os.stat(folder_path)
            folders.append((folder_name, st.st_mtime_ns, st.st_size))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            folders.append((folder_name, None, None))
    return (root_sig, tuple(folders))


def _validate_texture_source_path(base_path):
    issues = []
    normalized_path = _normalize_texture_source_path(base_path)

    if not normalized_path:
        issues.append(("ERROR", "TEXTURE_PATH_MISSING", "Texture source directory is not set."))
        return normalized_path, issues

    if not os.path.isdir(normalized_path):
        issues.append(("ERROR", "TEXTURE_PATH_INVALID", f"Texture source directory is not a valid path: {normalized_path}"))
        return normalized_path, issues

    sig = _texture_source_validation_signature(normalized_path)
    cached = _TEXTURE_SOURCE_VALIDATION_CACHE.get(normalized_path)
    if cached and cached.get("signature") == sig:
        return normalized_path, list(cached.get("issues", ()))

    for folder_name, rule in _REQUIRED_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if not os.path.isdir(folder_path):
            issues.append((
                "ERROR",
                "TEXTURE_SOURCE_INVALID",
                f"Texture source is invalid: missing required folder '{folder_name}'.",
            ))
            continue

        count = _count_texture_source_files(folder_path, rule["prefix"], rule["ext"])
        if count < rule["min_count"]:
            issues.append((
                "ERROR",
                "TEXTURE_SOURCE_INVALID",
                (
                    f"Texture source is invalid: folder '{folder_name}' must contain at least "
                    f"{rule['min_count']} files named '{rule['prefix']}*{rule['ext']}'."
                ),
            ))

    for folder_name, rule in _OPTIONAL_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if not os.path.isdir(folder_path):
            issues.append((
                "WARNING",
                "TEXTURE_SUPPORTING_FOLDER_MISSING",
                (
                    f"Folder '{folder_name}' is missing. Planetka will use fallback "
                    f"{folder_name} textures where needed."
                ),
            ))
            continue

        count = _count_texture_source_files(folder_path, rule["prefix"], rule["ext"])
        if count == 0:
            issues.append((
                "WARNING",
                "TEXTURE_SUPPORTING_FILES_MISSING",
                (
                    f"Folder '{folder_name}' has no files matching "
                    f"'{rule['prefix']}*{rule['ext']}'. Planetka will use fallback textures."
                ),
            ))

    _TEXTURE_SOURCE_VALIDATION_CACHE[normalized_path] = {
        "signature": sig,
        "issues": list(issues),
    }
    return normalized_path, issues


def get_texture_source_health(base_path):
    normalized_path = _normalize_texture_source_path(base_path)
    if not normalized_path:
        return {"status": "NOT_SET", "normalized_path": "", "issues": []}

    cached = _TEXTURE_SOURCE_HEALTH_CACHE.get(normalized_path)
    if cached:
        return {
            "status": cached.get("status", "INVALID"),
            "normalized_path": normalized_path,
            "issues": list(cached.get("issues", ())),
        }

    if not os.path.isdir(normalized_path):
        return {"status": "INVALID", "normalized_path": normalized_path, "issues": []}

    issues = []
    has_errors = False
    has_warnings = False

    for folder_name, rule in _REQUIRED_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if not os.path.isdir(folder_path):
            has_errors = True
            issues.append(("ERROR", "TEXTURE_SOURCE_INVALID"))
            continue
        if not _has_min_texture_source_files(folder_path, rule["prefix"], rule["ext"], rule["min_count"]):
            has_errors = True
            issues.append(("ERROR", "TEXTURE_SOURCE_INVALID"))

    for folder_name, rule in _OPTIONAL_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if not os.path.isdir(folder_path):
            has_warnings = True
            issues.append(("WARNING", "TEXTURE_SUPPORTING_FOLDER_MISSING"))
            continue
        if not _has_min_texture_source_files(folder_path, rule["prefix"], rule["ext"], 1):
            has_warnings = True
            issues.append(("WARNING", "TEXTURE_SUPPORTING_FILES_MISSING"))

    s2_folder = os.path.join(normalized_path, "S2")
    if os.path.isdir(s2_folder):
        missing_sentinels = []
        for sentinel_name in _KNOWN_GOOD_S2_SENTINELS:
            if not os.path.isfile(os.path.join(s2_folder, sentinel_name)):
                missing_sentinels.append(sentinel_name)
        if missing_sentinels:
            has_warnings = True
            issues.append(("WARNING", "TEXTURE_SOURCE_SENTINEL_MISSING"))

    status = "INVALID" if has_errors else ("PARTIAL" if has_warnings else "READY")
    _TEXTURE_SOURCE_HEALTH_CACHE[normalized_path] = {
        "status": status,
        "issues": list(issues),
    }
    return {"status": status, "normalized_path": normalized_path, "issues": list(issues)}


def validate_known_good_texture_source(base_path):
    normalized_path, issues = _validate_texture_source_path(base_path)
    details = {
        "normalized_path": normalized_path,
        "issues": list(issues),
        "folder_counts": {},
        "known_good_s2_present": [],
        "known_good_s2_missing": [],
    }

    if not normalized_path or not os.path.isdir(normalized_path):
        return details

    for folder_name, rule in _REQUIRED_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if os.path.isdir(folder_path):
            details["folder_counts"][folder_name] = _count_texture_source_files(
                folder_path,
                rule["prefix"],
                rule["ext"],
            )
        else:
            details["folder_counts"][folder_name] = 0

    for folder_name, rule in _OPTIONAL_TEXTURE_SOURCE_RULES.items():
        folder_path = os.path.join(normalized_path, folder_name)
        if os.path.isdir(folder_path):
            details["folder_counts"][folder_name] = _count_texture_source_files(
                folder_path,
                rule["prefix"],
                rule["ext"],
            )
        else:
            details["folder_counts"][folder_name] = 0

    s2_folder = os.path.join(normalized_path, "S2")
    for name in _KNOWN_GOOD_S2_SENTINELS:
        sentinel_path = os.path.join(s2_folder, name)
        if os.path.isfile(sentinel_path):
            details["known_good_s2_present"].append(name)
        else:
            details["known_good_s2_missing"].append(name)

    if details["known_good_s2_missing"]:
        details["issues"].append((
            "WARNING",
            "TEXTURE_SOURCE_SENTINEL_MISSING",
            (
                "Known-good S2 sentinel tiles are missing "
                f"({len(details['known_good_s2_missing'])}/2). "
                "Source may be partial or misconfigured."
            ),
        ))

    return details
