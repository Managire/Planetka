#!/usr/bin/env python3
import argparse
import hashlib
import heapq
import os
import sqlite3
import zipfile

ZIP_MEMBER_NAME = "allCountries.txt"
BATCH_SIZE = 20000
INDEX_SCHEMA_VERSION = "4"
FILTER_PROFILE = "planetka_lite_v1"
POPULATED_MIN_POPULATION = 15000
ADMIN_ALWAYS_CODES = {"PCLI", "ADM1"}
ADMIN_POP_FILTERED_CODES = {"ADM2"}
WATER_KEEP_CODES = {"LKS", "BAY", "STRT"}
TOP_TERRAIN_COUNT = 5000


def source_signature(path):
    stat = os.stat(path)
    payload = f"{os.path.abspath(path)}|{int(stat.st_size)}|{int(stat.st_mtime)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def iter_source_lines(path):
    lower_path = str(path).lower()
    if lower_path.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as archive:
            member = ZIP_MEMBER_NAME if ZIP_MEMBER_NAME in archive.namelist() else None
            if member is None:
                for name in archive.namelist():
                    if name.lower().endswith("allcountries.txt"):
                        member = name
                        break
            if member is None:
                raise RuntimeError("allCountries.txt not found in zip archive")
            with archive.open(member, "r") as handle:
                for raw in handle:
                    try:
                        yield raw.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
        return

    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            yield line


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def terrain_elevation_from_fields(elevation_raw, dem_raw):
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


def should_keep_feature(feature_class, feature_code, population, geoname_id, top_terrain_ids):
    if feature_class == "P":
        return int(population) >= POPULATED_MIN_POPULATION
    if feature_class == "A":
        if feature_code in ADMIN_ALWAYS_CODES:
            return True
        if feature_code in ADMIN_POP_FILTERED_CODES:
            return int(population) >= POPULATED_MIN_POPULATION
        return False
    if feature_class == "T":
        return int(geoname_id) in top_terrain_ids
    if feature_class == "H":
        return feature_code in WATER_KEEP_CODES
    return False


def parse_line(line, top_terrain_ids):
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
        population = parse_int(fields[14], default=0)
    except (TypeError, ValueError):
        return None

    if not name:
        return None
    if not should_keep_feature(feature_class, feature_code, population, geoname_id, top_terrain_ids):
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


def collect_top_terrain_ids(source_path, limit):
    heap = []
    if int(limit) <= 0:
        return set()
    for line in iter_source_lines(source_path):
        fields = line.strip().split("\t")
        if len(fields) < 19:
            continue
        feature_class = str(fields[6] or "").strip().upper()
        if feature_class != "T":
            continue
        geoname_id = parse_int(fields[0], default=0)
        if geoname_id <= 0:
            continue
        elevation = terrain_elevation_from_fields(fields[15], fields[16])
        if elevation is None:
            continue
        item = (int(elevation), int(geoname_id))
        if len(heap) < int(limit):
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return {int(geoname_id) for _elevation, geoname_id in heap}


def build_index(source_path, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_output_path = f"{output_path}.tmp"
    if os.path.isfile(temp_output_path):
        os.remove(temp_output_path)

    top_terrain_ids = collect_top_terrain_ids(source_path, TOP_TERRAIN_COUNT)
    connection = sqlite3.connect(temp_output_path)
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
        (INDEX_SCHEMA_VERSION,),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('filter_profile', ?)",
        (FILTER_PROFILE,),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('source_signature', ?)",
        (source_signature(source_path),),
    )
    connection.commit()

    batch = []
    for line in iter_source_lines(source_path):
        parsed = parse_line(line, top_terrain_ids)
        if not parsed:
            continue
        batch.append(parsed)
        if len(batch) >= BATCH_SIZE:
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

    os.replace(temp_output_path, output_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Build Planetka GeoNames SQLite index")
    parser.add_argument("source", help="Path to allCountries.txt or allCountries.zip")
    parser.add_argument(
        "--output",
        default="",
        help="Output SQLite path (default: alongside source as allCountries.idx.sqlite3)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    source = os.path.abspath(args.source)
    if not os.path.isfile(source):
        raise SystemExit(f"Source not found: {source}")

    output = str(args.output or "").strip()
    if not output:
        output = os.path.join(os.path.dirname(source), "allCountries.idx.sqlite3")
    output = os.path.abspath(output)

    build_index(source, output)
    size_mb = os.path.getsize(output) / (1024.0 * 1024.0)
    print(f"Built index: {output}")
    print(f"Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
