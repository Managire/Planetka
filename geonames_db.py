import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import zipfile

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

_ZIP_MEMBER_NAME = "allCountries.txt"
_PREBUILT_INDEX_NAME = "allCountries.idx.sqlite3"
_EXTRA_PLACES_NAME = "planetka_places_extra.json"
_MIN_QUERY_LENGTH = 3
_RECENT_BY_DISPLAY = {}
_RECENT_BY_DISPLAY_LOWER = {}
_RECENT_LIMIT = 5000
_INDEX_BATCH_SIZE = 20000
_INDEX_SCHEMA_VERSION = "4"
_FILTER_PROFILE = "planetka_places_v1"
_POPULATED_MIN_POPULATION = 15000
_ADMIN_ALWAYS_CODES = {"PCLI", "ADM1"}
_ADMIN_POP_FILTERED_CODES = {"ADM2"}
_WATER_KEEP_CODES = {"LKS", "BAY", "STRT"}
_TOP_TERRAIN_COUNT = 5000
_QUERY_CACHE = {}
_QUERY_CACHE_DB_PATH = ""
_QUERY_CACHE_LIMIT = 256
_COUNTRY_HINT_RE = re.compile(r"^[A-Za-z]{2}$")
_PLACE_TYPE_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)\s*-\s*(?P<ptype>country|state|city|island|mountain|place)\s*$",
    flags=re.IGNORECASE,
)

_INDEX_LOCK = threading.Lock()
_INDEX_THREAD = None
_INDEX_STATE = "idle"
_INDEX_ERROR = ""
_INDEX_DB_PATH = ""
_INDEX_SOURCE_PATH = ""
_READ_CONNECTION = None
_READ_CONNECTION_PATH = ""
_EXTRA_PLACES = []
_EXTRA_PLACES_BY_DISPLAY = {}
_EXTRA_PLACES_BY_DISPLAY_LOWER = {}
_EXTRA_PLACES_BY_GEOID = {}
_EXTRA_LOADED = False
_EXTRA_LOADED_PATH = ""


def _effective_min_query_length(query_text):
    text = str(query_text or "").strip()
    if len(text) >= 2 and any(ch.isdigit() for ch in text):
        return 2
    return _MIN_QUERY_LENGTH


def _candidate_database_paths():
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return (
        os.path.join(addon_dir, "Resources", "GeoNames", _PREBUILT_INDEX_NAME),
        os.path.join(addon_dir, "Resources", "GeoNames", "allCountries.txt"),
        os.path.join(addon_dir, "Resources", "GeoNames", "allCountries.zip"),
    )


def _extra_places_path():
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, "Resources", "GeoNames", _EXTRA_PLACES_NAME)


def get_database_path():
    for path in _candidate_database_paths():
        if path and os.path.isfile(path):
            return path
    return ""


def database_available():
    return bool(get_database_path())


def _source_signature(path):
    try:
        stat = os.stat(path)
        payload = f"{os.path.abspath(path)}|{int(stat.st_size)}|{int(stat.st_mtime)}"
    except OSError:
        payload = os.path.abspath(path)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _temp_db_path(source_signature):
    base = os.path.join(tempfile.gettempdir(), "planetka_geonames_index")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{source_signature}.sqlite3")


def _sidecar_db_path(source_path):
    return f"{source_path}.planetka.idx.sqlite3"


def _prebuilt_db_path(source_path):
    return os.path.join(os.path.dirname(source_path), _PREBUILT_INDEX_NAME)


def _candidate_index_paths(source_path, source_signature):
    candidates = (
        _prebuilt_db_path(source_path),
        _sidecar_db_path(source_path),
        _temp_db_path(source_signature),
    )
    unique = []
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _iter_source_lines(path):
    lower_path = str(path or "").lower()
    if lower_path.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as archive:
            member = _ZIP_MEMBER_NAME if _ZIP_MEMBER_NAME in archive.namelist() else None
            if member is None:
                for name in archive.namelist():
                    if name.lower().endswith("allcountries.txt"):
                        member = name
                        break
            if member is None:
                return
            with archive.open(member, "r") as handle:
                for raw in handle:
                    try:
                        yield raw.decode("utf-8")
                    except (UnicodeDecodeError, TypeError, ValueError):
                        continue
        return

    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            yield line


def _parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _terrain_elevation_from_fields(elevation_raw, dem_raw):
    elevation = None
    try:
        if elevation_raw:
            elevation = int(float(elevation_raw))
    except (TypeError, ValueError):
        elevation = None
    try:
        dem = int(float(dem_raw)) if dem_raw else None
    except (TypeError, ValueError):
        dem = None
    if elevation is None:
        return dem
    if dem is not None and dem > elevation:
        return dem
    return elevation


def _should_keep_feature(feature_class, feature_code, population, geoname_id, top_terrain_ids):
    if feature_class == "P":
        return int(population) >= _POPULATED_MIN_POPULATION
    if feature_class == "A":
        if feature_code in _ADMIN_ALWAYS_CODES:
            return True
        if feature_code in _ADMIN_POP_FILTERED_CODES:
            return int(population) >= _POPULATED_MIN_POPULATION
        return False
    if feature_class == "T":
        return geoname_id in top_terrain_ids
    if feature_class == "H":
        return feature_code in _WATER_KEEP_CODES
    return False


def _parse_geonames_line(line, top_terrain_ids):
    fields = line.strip().split("\t")
    if len(fields) < 19:
        return None
    try:
        geoname_id = int(fields[0])
        name = str(fields[1]).strip()
        ascii_name = str(fields[2]).strip()
        feature_class = str(fields[6]).strip().upper()
        feature_code = str(fields[7]).strip().upper()
        latitude = float(fields[4])
        longitude = float(fields[5])
        country_code = str(fields[8]).strip()
        admin1_code = str(fields[10]).strip()
        population = _parse_int(fields[14], default=0)
    except (TypeError, ValueError):
        return None

    if not name:
        return None

    if not _should_keep_feature(feature_class, feature_code, population, geoname_id, top_terrain_ids):
        return None

    search_name = ascii_name or name
    return (
        geoname_id,
        name,
        admin1_code,
        country_code,
        str(search_name).lower(),
        latitude,
        longitude,
        population,
    )


def _display_name(name, admin1_code, country_code):
    if country_code:
        return f"{name}, {country_code}"
    return str(name)


def _index_has_rows(db_path):
    if not db_path or not os.path.isfile(db_path):
        return False
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM places LIMIT 1")
        row = cursor.fetchone()
        connection.close()
        return row is not None
    except (sqlite3.Error, TypeError, ValueError, OSError):
        return False


def _places_table_has_expected_layout(cursor):
    try:
        cursor.execute("PRAGMA table_info(places)")
        rows = cursor.fetchall()
    except sqlite3.Error:
        return False
    expected = (
        ("geonameid", "INTEGER"),
        ("name", "TEXT"),
        ("admin1_code", "TEXT"),
        ("country_code", "TEXT"),
        ("search_lower", "TEXT"),
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("population", "INTEGER"),
    )
    actual = tuple((str(row[1]), str(row[2]).upper()) for row in rows)
    return actual == expected


def _repair_prebuilt_index_metadata(db_path):
    if not db_path or not os.path.isfile(db_path):
        return False
    connection = None
    try:
        connection = sqlite3.connect(db_path, timeout=1.0)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='places' LIMIT 1"
        )
        if cursor.fetchone() is None:
            connection.close()
            return False
        if not _places_table_has_expected_layout(cursor):
            connection.close()
            return False
        cursor.execute("SELECT 1 FROM places LIMIT 1")
        if cursor.fetchone() is None:
            connection.close()
            return False
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        cursor.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (_INDEX_SCHEMA_VERSION,),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('filter_profile', ?)",
            (_FILTER_PROFILE,),
        )
        cursor.execute("SELECT value FROM meta WHERE key='source_signature' LIMIT 1")
        signature_row = cursor.fetchone()
        if not signature_row or not str(signature_row[0]).strip():
            cursor.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('source_signature', ?)",
                (_source_signature(db_path),),
            )
        connection.commit()
        connection.close()
        connection = None
        return _db_is_ready(db_path)
    except (sqlite3.Error, OSError, TypeError, ValueError):
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        return False


def _db_is_ready(db_path, expected_signature=None):
    if not db_path or not os.path.isfile(db_path):
        return False
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='places' LIMIT 1"
        )
        if cursor.fetchone() is None:
            connection.close()
            return False
        cursor.execute("SELECT value FROM meta WHERE key='schema_version' LIMIT 1")
        schema_row = cursor.fetchone()
        if not schema_row or str(schema_row[0]) != _INDEX_SCHEMA_VERSION:
            connection.close()
            return False
        cursor.execute("SELECT value FROM meta WHERE key='filter_profile' LIMIT 1")
        profile_row = cursor.fetchone()
        if not profile_row or str(profile_row[0]) != _FILTER_PROFILE:
            connection.close()
            return False
        if expected_signature:
            cursor.execute("SELECT value FROM meta WHERE key='source_signature' LIMIT 1")
            signature_row = cursor.fetchone()
            if not signature_row or str(signature_row[0]) != str(expected_signature):
                connection.close()
                return False
        cursor.execute("SELECT 1 FROM places LIMIT 1")
        ready = cursor.fetchone() is not None
        connection.close()
        return ready
    except (sqlite3.Error, TypeError, ValueError, OSError):
        return False


def _collect_top_terrain_ids(source_path, limit):
    if int(limit) <= 0:
        return set()
    import heapq

    heap = []
    for line in _iter_source_lines(source_path):
        fields = line.strip().split("\t")
        if len(fields) < 19:
            continue
        feature_class = str(fields[6] or "").strip().upper()
        if feature_class != "T":
            continue
        geoname_id = _parse_int(fields[0], default=0)
        if geoname_id <= 0:
            continue
        elevation = _terrain_elevation_from_fields(fields[15], fields[16])
        if elevation is None:
            continue
        item = (int(elevation), int(geoname_id))
        if len(heap) < int(limit):
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return {int(geoname_id) for _elevation, geoname_id in heap}


def _prepare_db(db_path, source_signature):
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute("PRAGMA cache_size = -100000")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS places (
            geonameid INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            admin1_code TEXT NOT NULL,
            country_code TEXT NOT NULL,
            search_lower TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            population INTEGER NOT NULL
        ) WITHOUT ROWID
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_places_search_pop ON places(search_lower, population DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    cursor.execute("DELETE FROM places")
    cursor.execute("DELETE FROM meta")
    cursor.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (_INDEX_SCHEMA_VERSION,),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('filter_profile', ?)",
        (_FILTER_PROFILE,),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('source_signature', ?)",
        (str(source_signature),),
    )
    connection.commit()
    return connection


def _build_index(source_path, db_path, source_signature):
    global _INDEX_STATE, _INDEX_ERROR, _INDEX_DB_PATH, _INDEX_SOURCE_PATH
    connection = None
    try:
        _close_read_connection()
        top_terrain_ids = _collect_top_terrain_ids(source_path, _TOP_TERRAIN_COUNT)
        connection = _prepare_db(db_path, source_signature)
        cursor = connection.cursor()
        batch = []

        for line in _iter_source_lines(source_path):
            parsed = _parse_geonames_line(line, top_terrain_ids)
            if not parsed:
                continue
            batch.append(parsed)
            if len(batch) >= _INDEX_BATCH_SIZE:
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO places (
                        geonameid, name, admin1_code, country_code, search_lower,
                        latitude, longitude, population
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                connection.commit()
                batch.clear()

        if batch:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO places (
                    geonameid, name, admin1_code, country_code, search_lower,
                    latitude, longitude, population
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            connection.commit()

        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cursor.execute("PRAGMA optimize")
        cursor.execute("VACUUM")
        connection.close()
        connection = None

        with _INDEX_LOCK:
            _INDEX_STATE = "ready"
            _INDEX_ERROR = ""
            _INDEX_DB_PATH = db_path
            _INDEX_SOURCE_PATH = source_path
    except (sqlite3.Error, OSError, zipfile.BadZipFile) + PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        with _INDEX_LOCK:
            _INDEX_STATE = "error"
            _INDEX_ERROR = str(exc)
            _INDEX_DB_PATH = db_path
            _INDEX_SOURCE_PATH = source_path


def _choose_build_target(source_path, source_signature):
    preferred_paths = (_prebuilt_db_path(source_path), _sidecar_db_path(source_path))
    for path in preferred_paths:
        directory = os.path.dirname(path)
        if directory and os.access(directory, os.W_OK):
            return path
    return _temp_db_path(source_signature)


def _start_index_if_needed(source_path):
    global _INDEX_THREAD, _INDEX_STATE, _INDEX_ERROR, _INDEX_DB_PATH, _INDEX_SOURCE_PATH

    if not source_path:
        with _INDEX_LOCK:
            _INDEX_STATE = "idle"
            _INDEX_ERROR = ""
            _INDEX_DB_PATH = ""
            _INDEX_SOURCE_PATH = ""
        return False

    if str(source_path).lower().endswith(".idx.sqlite3"):
        if _db_is_ready(source_path):
            with _INDEX_LOCK:
                _INDEX_STATE = "ready"
                _INDEX_ERROR = ""
                _INDEX_DB_PATH = source_path
                _INDEX_SOURCE_PATH = source_path
            return True
        if _repair_prebuilt_index_metadata(source_path) and _db_is_ready(source_path):
            with _INDEX_LOCK:
                _INDEX_STATE = "ready"
                _INDEX_ERROR = ""
                _INDEX_DB_PATH = source_path
                _INDEX_SOURCE_PATH = source_path
            return True
        with _INDEX_LOCK:
            _INDEX_STATE = "error"
            _INDEX_ERROR = "GeoNames index file is invalid or empty."
            _INDEX_DB_PATH = source_path
            _INDEX_SOURCE_PATH = source_path
        return False

    source_signature = _source_signature(source_path)

    with _INDEX_LOCK:
        active_state = _INDEX_STATE
        active_source = _INDEX_SOURCE_PATH
        active_db = _INDEX_DB_PATH
        active_thread = _INDEX_THREAD

    if active_state == "ready" and active_source == source_path and active_db and os.path.isfile(active_db):
        return True

    if active_thread is not None and active_thread.is_alive() and active_source == source_path:
        return False

    for db_path in _candidate_index_paths(source_path, source_signature):
        if _db_is_ready(db_path, source_signature):
            with _INDEX_LOCK:
                _INDEX_STATE = "ready"
                _INDEX_ERROR = ""
                _INDEX_DB_PATH = db_path
                _INDEX_SOURCE_PATH = source_path
            return True

    target_db = _choose_build_target(source_path, source_signature)
    with _INDEX_LOCK:
        _INDEX_STATE = "indexing"
        _INDEX_ERROR = ""
        _INDEX_DB_PATH = target_db
        _INDEX_SOURCE_PATH = source_path
        _INDEX_THREAD = threading.Thread(
            target=_build_index,
            args=(source_path, target_db, source_signature),
            daemon=True,
            name="PlanetkaGeoNamesIndex",
        )
        _INDEX_THREAD.start()
    return False


def get_search_status():
    source_path = get_database_path()
    if not source_path:
        return "missing"
    _start_index_if_needed(source_path)
    with _INDEX_LOCK:
        return str(_INDEX_STATE)


def get_search_status_text():
    status = get_search_status()
    if status == "missing":
        return "GeoNames allCountries not configured."
    if status == "indexing":
        return "GeoNames index is building in background..."
    if status == "error":
        with _INDEX_LOCK:
            error_text = str(_INDEX_ERROR or "").strip()
        if error_text:
            return f"GeoNames index failed: {error_text}"
        return "GeoNames index failed."
    return ""


def load_geonames_database():
    source_path = get_database_path()
    if not source_path:
        return False
    return _start_index_if_needed(source_path)


def _remember_entry(entry):
    if not isinstance(entry, dict):
        return
    key = str(entry.get("display_name", "") or "")
    if not key:
        return
    if key in _RECENT_BY_DISPLAY:
        _RECENT_BY_DISPLAY.pop(key, None)
    _RECENT_BY_DISPLAY[key] = entry
    lower_key = key.lower()
    if lower_key in _RECENT_BY_DISPLAY_LOWER:
        _RECENT_BY_DISPLAY_LOWER.pop(lower_key, None)
    _RECENT_BY_DISPLAY_LOWER[lower_key] = entry
    while len(_RECENT_BY_DISPLAY) > _RECENT_LIMIT:
        oldest_key, oldest_entry = next(iter(_RECENT_BY_DISPLAY.items()))
        del _RECENT_BY_DISPLAY[oldest_key]
        oldest_lower = str(oldest_key).lower()
        if _RECENT_BY_DISPLAY_LOWER.get(oldest_lower) is oldest_entry:
            _RECENT_BY_DISPLAY_LOWER.pop(oldest_lower, None)


def get_cached_place_by_display(display_name):
    key = str(display_name or "").strip()
    if not key:
        return None
    entry = _RECENT_BY_DISPLAY.get(key)
    if entry:
        return entry
    key_lower = key.lower()
    entry = _RECENT_BY_DISPLAY_LOWER.get(key_lower)
    if entry:
        return entry
    normalized_key = _normalize_display_lookup_key(key)
    if normalized_key and normalized_key.lower() != key_lower:
        return _RECENT_BY_DISPLAY_LOWER.get(normalized_key.lower())
    return None


def _entry_from_row(row):
    name = str(row[1])
    admin1_code = str(row[2])
    country_code = str(row[3])
    population = _parse_int(row[6], default=0) if len(row) > 6 else 0
    return {
        "geonameid": str(row[0]),
        "name": str(name),
        "admin1_code": str(admin1_code),
        "country_code": str(country_code),
        "population": int(population),
        "display_name": _display_name(name, admin1_code, country_code),
        "latitude": float(row[4]),
        "longitude": float(row[5]),
    }


def _normalize_extra_place_entry(raw):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "") or "").strip()
    if not name:
        return None
    country_code = str(raw.get("country_code", "") or "").strip().upper()
    admin1_code = str(raw.get("admin1_code", "") or "").strip()
    geonameid = str(raw.get("geonameid", "") or "").strip()
    if not geonameid:
        return None
    try:
        latitude = float(raw.get("latitude", 0.0))
        longitude = float(raw.get("longitude", 0.0))
    except (TypeError, ValueError):
        return None
    population = _parse_int(raw.get("population", 0), default=0)
    aliases = []
    for alias in raw.get("aliases", []) or []:
        text = str(alias or "").strip()
        if len(text) < _effective_min_query_length(text):
            continue
        aliases.append(text)
    display_name = _display_name(name, admin1_code, country_code)
    entry = {
        "geonameid": geonameid,
        "name": name,
        "admin1_code": admin1_code,
        "country_code": country_code,
        "population": int(population),
        "display_name": display_name,
        "latitude": latitude,
        "longitude": longitude,
        "aliases": aliases,
        "category": str(raw.get("category", "") or "").strip().lower(),
    }
    return entry


def _load_extra_places():
    global _EXTRA_LOADED, _EXTRA_PLACES, _EXTRA_PLACES_BY_DISPLAY
    global _EXTRA_PLACES_BY_DISPLAY_LOWER, _EXTRA_PLACES_BY_GEOID, _EXTRA_LOADED_PATH
    extra_path = _extra_places_path()
    if _EXTRA_LOADED and _EXTRA_LOADED_PATH == extra_path:
        return

    _EXTRA_PLACES = []
    _EXTRA_PLACES_BY_DISPLAY = {}
    _EXTRA_PLACES_BY_DISPLAY_LOWER = {}
    _EXTRA_PLACES_BY_GEOID = {}
    _EXTRA_LOADED = True
    _EXTRA_LOADED_PATH = extra_path
    if not os.path.isfile(extra_path):
        return
    try:
        with open(extra_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return

    entries = payload if isinstance(payload, list) else []
    for raw in entries:
        entry = _normalize_extra_place_entry(raw)
        if not entry:
            continue
        geonameid = str(entry.get("geonameid", "") or "")
        if geonameid in _EXTRA_PLACES_BY_GEOID:
            continue
        _EXTRA_PLACES.append(entry)
        _EXTRA_PLACES_BY_GEOID[geonameid] = entry
        display_name = str(entry.get("display_name", "") or "")
        if display_name:
            _EXTRA_PLACES_BY_DISPLAY[display_name] = entry
            _EXTRA_PLACES_BY_DISPLAY_LOWER[display_name.lower()] = entry


def _search_extra_places(query, country_hint="", limit=20):
    _load_extra_places()
    if not _EXTRA_PLACES:
        return []
    q = str(query or "").strip().lower()
    if len(q) < _effective_min_query_length(q):
        return []
    safe_country_hint = str(country_hint or "").strip().upper()

    matched = []
    for entry in _EXTRA_PLACES:
        country_code = str(entry.get("country_code", "") or "").strip().upper()
        if safe_country_hint and country_code != safe_country_hint:
            continue
        name = str(entry.get("name", "") or "").strip()
        name_lower = name.lower()
        aliases = [str(alias or "").strip() for alias in entry.get("aliases", []) or []]
        alias_lowers = [alias.lower() for alias in aliases if alias]
        alias_match = any(alias.startswith(q) for alias in alias_lowers)
        name_match = name_lower.startswith(q)
        if not (name_match or alias_match):
            continue
        exact = 0 if (name_lower == q or q in alias_lowers) else 1
        population_rank = -int(entry.get("population", 0) or 0)
        matched.append((exact, population_rank, entry))

    matched.sort(key=lambda item: (item[0], item[1], str(item[2].get("name", "")).lower()))
    results = []
    seen_geonameids = set()
    for _exact, _population_rank, entry in matched:
        geonameid = str(entry.get("geonameid", "") or "")
        if not geonameid or geonameid in seen_geonameids:
            continue
        seen_geonameids.add(geonameid)
        results.append(entry)
        if len(results) >= int(limit):
            break
    return results


def _get_extra_place_by_display(display_name):
    key = str(display_name or "").strip()
    if not key:
        return None
    _load_extra_places()
    if not _EXTRA_PLACES:
        return None
    entry = _EXTRA_PLACES_BY_DISPLAY.get(key)
    if entry:
        return entry
    entry = _EXTRA_PLACES_BY_DISPLAY_LOWER.get(key.lower())
    if entry:
        return entry
    name_hint_raw, country_hint, _admin1_hint_raw = _split_display_lookup_hints(key)
    name_hint = str(name_hint_raw or "").strip().lower()
    if len(name_hint) < _effective_min_query_length(name_hint):
        return None
    matches = _search_extra_places(name_hint, country_hint=country_hint, limit=10)
    for item in matches:
        if str(item.get("display_name", "") or "").lower() == key.lower():
            return item
        if str(item.get("name", "") or "").strip().lower() == name_hint:
            return item
        for alias in item.get("aliases", []) or []:
            if str(alias or "").strip().lower() == name_hint:
                return item
    return None


def _entry_base_label(entry):
    name = str(entry.get("name", "") or "").strip()
    admin1_code = str(entry.get("admin1_code", "") or "").strip()
    country_code = str(entry.get("country_code", "") or "").strip()
    return _display_name(name, admin1_code, country_code)


def _result_label_for_entry(entry, duplicate_display_names):
    base_label = _entry_base_label(entry)
    if duplicate_display_names.get(base_label, 0) <= 1:
        return base_label

    name = str(entry.get("name", "") or "").strip()
    admin1_code = str(entry.get("admin1_code", "") or "").strip()
    country_code = str(entry.get("country_code", "") or "").strip()

    if admin1_code and country_code:
        return f"{name}, {admin1_code}, {country_code}"
    if admin1_code:
        return f"{name}, {admin1_code}"
    return base_label


def _entry_query_rank(entry, query_text):
    query = str(query_text or "").strip().lower()
    if not query:
        return (2, 0, "")
    name = str(entry.get("name", "") or "").strip().lower()
    aliases = [str(alias or "").strip().lower() for alias in entry.get("aliases", []) or []]

    if name == query or query in aliases:
        bucket = 0
    elif name.startswith(query) or any(alias.startswith(query) for alias in aliases):
        bucket = 1
    else:
        bucket = 2
    population = int(entry.get("population", 0) or 0)
    return (bucket, -population, name)


def _close_read_connection():
    global _READ_CONNECTION, _READ_CONNECTION_PATH
    if _READ_CONNECTION is not None:
        try:
            _READ_CONNECTION.close()
        except sqlite3.Error:
            pass
    _READ_CONNECTION = None
    _READ_CONNECTION_PATH = ""
    _clear_query_cache()


def _clear_query_cache(db_path=""):
    global _QUERY_CACHE_DB_PATH
    _QUERY_CACHE.clear()
    _QUERY_CACHE_DB_PATH = str(db_path or "")


def _get_read_connection(db_path):
    global _READ_CONNECTION, _READ_CONNECTION_PATH
    if not db_path:
        return None
    if _READ_CONNECTION is not None and _READ_CONNECTION_PATH == db_path:
        return _READ_CONNECTION

    _close_read_connection()
    try:
        _READ_CONNECTION = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=0.2,
        )
    except sqlite3.Error:
        _READ_CONNECTION = None
        _READ_CONNECTION_PATH = ""
        return None

    _READ_CONNECTION_PATH = db_path
    _clear_query_cache(db_path)
    return _READ_CONNECTION


def _prefix_bounds(prefix):
    normalized = str(prefix or "")
    return normalized, f"{normalized}\uffff"


def _normalized_result_limit(max_results, default=20):
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        value = int(default)
    return max(1, min(200, value))


def _split_query_country_hint(query_text):
    raw = str(query_text or "").strip()
    if not raw:
        return "", ""

    def _explicit_country_hint(token):
        raw_token = str(token or "").strip()
        if not _COUNTRY_HINT_RE.fullmatch(raw_token):
            return ""
        # Avoid false positives for common lowercase particles in place names
        # (e.g. "Rio de Janeiro", "Sierra de ..."). Country suffix matching
        # should be explicit (uppercase), such as "Paris FR" or "Paris, FR".
        if raw_token != raw_token.upper():
            return ""
        return raw_token.upper()

    if "," in raw:
        left, right = raw.rsplit(",", 1)
        country_hint = _explicit_country_hint(right)
        place_hint = str(left or "").strip()
        if country_hint and place_hint:
            return place_hint, country_hint
        return raw, ""

    parts = raw.rsplit(" ", 1)
    if len(parts) == 2:
        country_hint = _explicit_country_hint(parts[1])
        place_hint = str(parts[0] or "").strip()
        if country_hint and place_hint:
            return place_hint, country_hint

    return raw, ""


def _strip_place_type_suffix(display_name):
    key = str(display_name or "").strip()
    if not key:
        return ""
    match = _PLACE_TYPE_SUFFIX_RE.match(key)
    if match:
        return str(match.group("base") or "").strip()
    return key


def _normalize_display_lookup_key(display_name):
    key = _strip_place_type_suffix(display_name)
    if not key:
        return ""
    place_hint, country_hint = _split_query_country_hint(key)
    if country_hint:
        return f"{place_hint}, {country_hint}"
    return key


def _entry_place_type(entry):
    category = str(entry.get("category", "") or "").strip().lower()
    if category == "country":
        return "Country"
    if category == "state":
        return "State"
    if category == "island":
        return "Island"
    if category.startswith("mountain"):
        return "Mountain"
    population = _parse_int(entry.get("population", 0), default=0)
    if population > 0:
        return "City"
    return "Place"


def _split_display_lookup_hints(display_name):
    raw = _strip_place_type_suffix(display_name)
    if not raw:
        return "", "", ""

    parts = [str(part or "").strip() for part in raw.split(",")]
    parts = [part for part in parts if part]
    if len(parts) >= 3:
        country_hint = str(parts[-1] or "").strip().upper()
        if _COUNTRY_HINT_RE.fullmatch(country_hint):
            name_hint = str(parts[0] or "").strip()
            admin1_hint = str(parts[1] or "").strip()
            return name_hint, country_hint, admin1_hint

    name_hint, country_hint = _split_query_country_hint(raw)
    admin1_hint = ""
    if "," in str(name_hint or ""):
        left, right = str(name_hint).split(",", 1)
        name_hint = str(left or "").strip()
        admin1_hint = str(right or "").strip()
    return str(name_hint or "").strip(), str(country_hint or "").strip(), admin1_hint


def search_places(query_text, max_results=20):
    if not load_geonames_database():
        return []

    raw_query = str(query_text or "").strip()
    query_name, country_hint = _split_query_country_hint(raw_query)
    query = str(query_name or "").strip().lower()
    if len(query) < _effective_min_query_length(query):
        return []

    with _INDEX_LOCK:
        db_path = _INDEX_DB_PATH
    if not db_path:
        return []

    if _QUERY_CACHE_DB_PATH != db_path:
        _clear_query_cache(db_path)

    limit = _normalized_result_limit(max_results)
    cache_key = (query, str(country_hint or ""), limit)
    results = []
    cached = _QUERY_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    lower_bound, upper_bound = _prefix_bounds(query)
    try:
        connection = _get_read_connection(db_path)
        if connection is None:
            return []
        cursor = connection.cursor()
        if country_hint:
            fetch_limit = max(100, min(500, int(limit * 10)))
            cursor.execute(
                """
                SELECT geonameid, name, admin1_code, country_code, latitude, longitude, population
                FROM places
                WHERE search_lower >= ? AND search_lower < ? AND country_code = ?
                ORDER BY
                    CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                    population DESC
                LIMIT ?
                """,
                (lower_bound, upper_bound, country_hint, query, fetch_limit),
            )
        else:
            cursor.execute(
                """
                SELECT geonameid, name, admin1_code, country_code, latitude, longitude, population
                FROM places
                WHERE search_lower >= ? AND search_lower < ?
                ORDER BY
                    CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                    population DESC
                LIMIT ?
                """,
                (lower_bound, upper_bound, query, limit),
            )
        rows = cursor.fetchall()
    except (sqlite3.Error, OSError) + PLANETKA_RECOVERABLE_EXCEPTIONS:
        _close_read_connection()
        return []

    entries = [_entry_from_row(row) for row in rows]
    extras = _search_extra_places(query, country_hint=country_hint, limit=limit * 4)
    if extras:
        existing_by_geonameid = {
            str(entry.get("geonameid", "") or ""): entry
            for entry in entries
            if str(entry.get("geonameid", "") or "")
        }
        for extra in extras:
            geonameid = str(extra.get("geonameid", "") or "")
            if geonameid and geonameid in existing_by_geonameid:
                base_entry = existing_by_geonameid.get(geonameid)
                if isinstance(base_entry, dict):
                    extra_category = str(extra.get("category", "") or "").strip().lower()
                    if extra_category:
                        base_entry["category"] = extra_category
                    extra_aliases = list(extra.get("aliases", []) or [])
                    if extra_aliases:
                        base_aliases = list(base_entry.get("aliases", []) or [])
                        merged = []
                        seen_alias = set()
                        for alias in base_aliases + extra_aliases:
                            text = str(alias or "").strip()
                            if not text:
                                continue
                            key = text.lower()
                            if key in seen_alias:
                                continue
                            seen_alias.add(key)
                            merged.append(text)
                        if merged:
                            base_entry["aliases"] = merged
                continue
            entries.append(extra)
    entries.sort(key=lambda entry: _entry_query_rank(entry, query))
    duplicate_display_names = {}
    for entry in entries:
        label = _entry_base_label(entry)
        duplicate_display_names[label] = int(duplicate_display_names.get(label, 0)) + 1

    used_labels = set()
    for entry in entries:
        label = _result_label_for_entry(entry, duplicate_display_names)
        place_type = _entry_place_type(entry)
        if place_type:
            label = f"{label} - {place_type}"

        # Deduplicate by the final user-facing label so users never see
        # indistinguishable duplicates in the dropdown.
        if label in used_labels:
            continue
        used_labels.add(label)
        entry["display_name"] = label
        _remember_entry(entry)
        results.append((entry["display_name"], entry["geonameid"]))
    _QUERY_CACHE[cache_key] = list(results)
    while len(_QUERY_CACHE) > _QUERY_CACHE_LIMIT:
        oldest = next(iter(_QUERY_CACHE))
        del _QUERY_CACHE[oldest]
    return results


def search_cities(query_text, max_results=20):
    return search_places(query_text, max_results=max_results)


def get_place_by_display(display_name):
    key = _normalize_display_lookup_key(display_name)
    if not key:
        return None

    cached = get_cached_place_by_display(key)
    if cached:
        return cached

    extra = _get_extra_place_by_display(key)
    if extra:
        _remember_entry(extra)
        return extra

    if not load_geonames_database():
        return None

    with _INDEX_LOCK:
        db_path = _INDEX_DB_PATH
    if not db_path:
        return None

    name_hint_raw, country_hint, admin1_hint_raw = _split_display_lookup_hints(key)
    name_hint = str(name_hint_raw or "").strip().lower()
    admin1_hint = str(admin1_hint_raw or "").strip().lower()
    if not name_hint:
        return None
    lower_bound, upper_bound = _prefix_bounds(name_hint)

    try:
        connection = _get_read_connection(db_path)
        if connection is None:
            return None
        cursor = connection.cursor()
        if country_hint:
            cursor.execute(
                """
                SELECT geonameid, name, admin1_code, country_code, latitude, longitude, population
                FROM places
                WHERE search_lower >= ? AND search_lower < ? AND country_code = ?
                ORDER BY
                    CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                    population DESC
                LIMIT 400
                """,
                (lower_bound, upper_bound, country_hint, name_hint),
            )
        else:
            cursor.execute(
                """
                SELECT geonameid, name, admin1_code, country_code, latitude, longitude, population
                FROM places
                WHERE search_lower >= ? AND search_lower < ?
                ORDER BY
                    CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                    population DESC
                LIMIT 200
                """,
                (lower_bound, upper_bound, name_hint),
            )
        rows = cursor.fetchall()
    except (sqlite3.Error, OSError) + PLANETKA_RECOVERABLE_EXCEPTIONS:
        _close_read_connection()
        return None

    key_lower = key.lower()
    best_candidate = None
    best_rank = None
    best_admin_candidate = None
    best_admin_rank = None
    for row in rows:
        entry = _entry_from_row(row)
        entry_display_lower = str(entry["display_name"]).lower()
        if entry_display_lower == key_lower:
            _remember_entry(entry)
            return entry
        entry_name_lower = str(entry.get("name", "")).strip().lower()
        if country_hint and str(entry.get("country_code", "")).strip().upper() != country_hint:
            continue
        if entry_name_lower != name_hint:
            continue
        rank = (0, -int(entry.get("population", 0) or 0))
        entry_admin1 = str(entry.get("admin1_code", "") or "").strip().lower()
        if admin1_hint and entry_admin1 == admin1_hint:
            if best_admin_rank is None or rank < best_admin_rank:
                best_admin_rank = rank
                best_admin_candidate = entry
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_candidate = entry
    if best_admin_candidate:
        _remember_entry(best_admin_candidate)
        return best_admin_candidate
    if best_candidate:
        _remember_entry(best_candidate)
        return best_candidate
    extra = _get_extra_place_by_display(key)
    if extra:
        _remember_entry(extra)
        return extra
    return None


def get_city_by_display(display_name):
    return get_place_by_display(display_name)
