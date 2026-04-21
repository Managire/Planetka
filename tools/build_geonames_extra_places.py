#!/usr/bin/env python3
import argparse
import json
import os
import re
import zipfile


ZIP_MEMBER_NAME = "allCountries.txt"
DEFAULT_ALLCOUNTRIES_URL = "https://download.geonames.org/export/dump/allCountries.zip"
DEFAULT_COUNTRYINFO_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
MIN_ALIAS_LENGTH = 3
MAX_ALIASES_PER_ENTRY = 16

COUNTRY_CODES = {"PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR"}
ISLAND_CODES = {"ISL", "ISLS", "ATOL", "ATLS", "ISLET"}
MOUNTAIN_CODES = {"MT", "PK", "MTS", "VOLC", "VLC"}

# Keep iconic mountains searchable even if they are not among the top N by
# elevation in a continent, or when GeoNames uses less common local names.
ICONIC_MOUNTAIN_OVERRIDES = {
    "7521863": {
        "name": "Mount Fuji",
        "aliases": ["Fuji", "Fuji-san", "Fujiyama"],
    },
    "2524810": {
        "name": "Mount Etna",
        "aliases": ["Etna", "Monte Etna"],
    },
    "3164481": {
        "name": "Mount Vesuvius",
        "aliases": ["Vesuvius", "Vesuvio", "Vesuv"],
    },
    "1114951": {
        "name": "K2",
        "aliases": ["Mount K2", "Godwin-Austen"],
    },
}

ICONIC_MOUNTAIN_FALLBACK_KEYS = {
    ("kenga-mine", "JP"),
    ("monte etna", "IT"),
    ("vesuvius", "IT"),
    ("k2", "PK"),
}

# Keep famous islands even if population in GeoNames is unknown/low.
ISLAND_NAME_KEEP = {
    "bali",
    "galapagos islands",
    "galapagos",
    "greenland",
    "iceland",
    "madagascar",
    "new guinea",
    "borneo",
    "sumatra",
    "java",
    "honshu",
    "hokkaido",
    "kyushu",
    "shikoku",
    "great britain",
    "ireland",
    "taiwan",
    "sri lanka",
    "tasmania",
    "canary islands",
    "hawaiian islands",
    "hispaniola",
    "sicily",
    "sardinia",
    "corsica",
    "cuba",
    "jamaica",
}

OFFICIAL_PREFIXES = (
    "republic of ",
    "kingdom of ",
    "state of ",
    "federation of ",
    "federal republic of ",
    "islamic republic of ",
    "democratic republic of ",
    "people's republic of ",
    "plurinational state of ",
    "commonwealth of ",
    "union of ",
    "the ",
)

CONTINENTS = ("AF", "AN", "AS", "EU", "NA", "OC", "SA")
CONTINENT_NAMES = {
    "AF": "Africa",
    "AN": "Antarctica",
    "AS": "Asia",
    "EU": "Europe",
    "NA": "North America",
    "OC": "Oceania",
    "SA": "South America",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build supplemental Planetka place-search dataset.")
    parser.add_argument(
        "--allcountries",
        default="",
        help="Path to allCountries.zip or allCountries.txt (default: auto-download allCountries.zip)",
    )
    parser.add_argument(
        "--countryinfo",
        default="",
        help="Path to countryInfo.txt (default: auto-download countryInfo.txt)",
    )
    parser.add_argument(
        "--output",
        default="Resources/GeoNames/planetka_places_extra.json",
        help="Output JSON path.",
    )
    return parser.parse_args()


def fetch_url(url, destination):
    import urllib.request

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    urllib.request.urlretrieve(url, destination)
    return destination


def ensure_input_file(path_or_empty, default_url, cache_name):
    if path_or_empty:
        source = os.path.abspath(path_or_empty)
        if not os.path.isfile(source):
            raise SystemExit(f"Input file not found: {source}")
        return source
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "planetka")
    os.makedirs(cache_dir, exist_ok=True)
    destination = os.path.join(cache_dir, cache_name)
    if not os.path.isfile(destination):
        fetch_url(default_url, destination)
    return destination


def iter_allcountries_lines(path):
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
        if default is None:
            return None
        return int(default)


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_alias(name):
    value = str(name or "").strip()
    if len(value) < MIN_ALIAS_LENGTH:
        return ""
    if re.search(r"[\d_]", value):
        return ""
    if value.count(",") > 1:
        return ""
    return value


def normalize_lookup_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def strip_official_prefix(name):
    candidate = str(name or "").strip()
    lower = candidate.lower()
    for prefix in OFFICIAL_PREFIXES:
        if lower.startswith(prefix):
            stripped = candidate[len(prefix):].strip()
            if len(stripped) >= MIN_ALIAS_LENGTH:
                return stripped
    return ""


def terrain_elevation(elevation_raw, dem_raw):
    elevation = parse_int(elevation_raw, default=None)
    dem = parse_int(dem_raw, default=None)
    if elevation is None:
        return dem
    if dem is not None and dem > elevation:
        return dem
    return elevation


def load_country_info(path):
    mapping = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            raw = str(line or "").strip()
            if not raw or raw.startswith("#"):
                continue
            fields = raw.split("\t")
            if len(fields) < 9:
                continue
            code = str(fields[0] or "").strip().upper()
            country_name = str(fields[4] or "").strip()
            continent = str(fields[8] or "").strip().upper()
            if code:
                mapping[code] = {
                    "continent": continent if continent in CONTINENTS else "",
                    "country_name": country_name,
                }
    return mapping


def continent_from_lat_lon(latitude, longitude):
    lat = parse_float(latitude, default=None)
    lon = parse_float(longitude, default=None)
    if lat is None or lon is None:
        return ""
    if lat <= -60.0:
        return "AN"
    if -20.0 <= lon <= 55.0 and -38.0 <= lat <= 38.0:
        return "AF"
    if -25.0 <= lon <= 60.0 and 34.0 <= lat <= 72.0:
        return "EU"
    if 25.0 <= lon <= 180.0 and -10.0 <= lat <= 80.0:
        return "AS"
    if -170.0 <= lon <= -30.0 and 7.0 <= lat <= 85.0:
        return "NA"
    if -95.0 <= lon <= -30.0 and -60.0 <= lat <= 15.0:
        return "SA"
    if (110.0 <= lon <= 180.0 or -180.0 <= lon <= -120.0) and -55.0 <= lat <= 25.0:
        return "OC"
    return ""


def choose_country_name(name, ascii_name, alternates):
    candidates = []
    for value in [name, ascii_name]:
        cleaned = clean_alias(value)
        if cleaned:
            candidates.append(cleaned)
    stripped = strip_official_prefix(name) or strip_official_prefix(ascii_name)
    if stripped:
        candidates.insert(0, stripped)
    for alt in alternates:
        cleaned = clean_alias(alt)
        if cleaned:
            candidates.append(cleaned)

    best = ""
    best_rank = None
    for candidate in candidates:
        lower = candidate.lower()
        has_prefix = any(lower.startswith(prefix) for prefix in OFFICIAL_PREFIXES)
        rank = (
            1 if has_prefix else 0,
            0 if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,60}", candidate) else 1,
            len(candidate),
            lower,
        )
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = candidate
    return best or str(name or "").strip()


def build_entries(allcountries_path, country_info_map):
    countries = {}
    states = {}
    islands = {}
    mountains_by_continent = {key: [] for key in CONTINENTS}
    mountains_by_geonameid = {}
    mountains_by_name_country = {}

    for line in iter_allcountries_lines(allcountries_path):
        fields = line.strip().split("\t")
        if len(fields) < 19:
            continue
        geonameid = parse_int(fields[0], default=0)
        if geonameid <= 0:
            continue
        name = str(fields[1] or "").strip()
        ascii_name = str(fields[2] or "").strip()
        if not name:
            continue
        alternates_raw = str(fields[3] or "").strip()
        alternates = [part.strip() for part in alternates_raw.split(",") if part.strip()]
        latitude = parse_float(fields[4], default=None)
        longitude = parse_float(fields[5], default=None)
        if latitude is None or longitude is None:
            continue
        feature_class = str(fields[6] or "").strip().upper()
        feature_code = str(fields[7] or "").strip().upper()
        country_code = str(fields[8] or "").strip().upper()
        admin1_code = str(fields[10] or "").strip()
        population = parse_int(fields[14], default=0)
        elevation = terrain_elevation(fields[15], fields[16])

        if feature_class == "A" and feature_code in COUNTRY_CODES:
            country_info = country_info_map.get(country_code, {})
            canonical = str(country_info.get("country_name", "") or "").strip() or choose_country_name(name, ascii_name, alternates)
            aliases = []
            for alias in [canonical, name, ascii_name] + alternates:
                cleaned = clean_alias(alias)
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
                if len(aliases) >= MAX_ALIASES_PER_ENTRY:
                    break
            key = str(country_code or geonameid)
            previous = countries.get(key)
            candidate = {
                "geonameid": str(geonameid),
                "name": canonical,
                "admin1_code": admin1_code,
                "country_code": country_code,
                "population": max(population, 0),
                "latitude": latitude,
                "longitude": longitude,
                "aliases": aliases,
                "category": "country",
            }
            if previous is None:
                countries[key] = candidate
            else:
                prev_score = (len(previous.get("name", "")), -int(previous.get("population", 0)))
                cand_score = (len(candidate.get("name", "")), -int(candidate.get("population", 0)))
                if cand_score < prev_score:
                    countries[key] = candidate

        if feature_class == "A" and feature_code == "ADM1":
            canonical_state = strip_official_prefix(name) or strip_official_prefix(ascii_name) or str(name).strip()
            aliases = []
            for alias in [canonical_state, name, ascii_name] + alternates:
                cleaned = clean_alias(alias)
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
                if len(aliases) >= MAX_ALIASES_PER_ENTRY:
                    break
            key = str(geonameid)
            states[key] = {
                "geonameid": str(geonameid),
                "name": canonical_state,
                "admin1_code": admin1_code,
                "country_code": country_code,
                "population": max(population, 0),
                "latitude": latitude,
                "longitude": longitude,
                "aliases": aliases,
                "category": "state",
            }

        if feature_class == "T" and feature_code in ISLAND_CODES:
            name_lower = str(name or "").strip().lower()
            keep = population >= 50000 or name_lower in ISLAND_NAME_KEEP
            if not keep:
                continue
            aliases = []
            for alias in [name, ascii_name] + alternates:
                cleaned = clean_alias(alias)
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
                if len(aliases) >= MAX_ALIASES_PER_ENTRY:
                    break
            key = str(geonameid)
            islands[key] = {
                "geonameid": str(geonameid),
                "name": str(name).strip(),
                "admin1_code": admin1_code,
                "country_code": country_code,
                "population": max(population, 0),
                "latitude": latitude,
                "longitude": longitude,
                "aliases": aliases,
                "category": "island",
            }

        if feature_class == "T" and feature_code in MOUNTAIN_CODES and elevation is not None:
            country_info = country_info_map.get(country_code, {})
            continent = str(country_info.get("continent", "") or "").strip().upper()
            if continent not in CONTINENTS:
                continent = continent_from_lat_lon(latitude, longitude)
            if continent not in CONTINENTS:
                continue
            aliases = []
            for alias in [name, ascii_name] + alternates:
                cleaned = clean_alias(alias)
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
                if len(aliases) >= MAX_ALIASES_PER_ENTRY:
                    break
            entry = {
                "geonameid": str(geonameid),
                "name": str(name).strip(),
                "admin1_code": admin1_code,
                "country_code": country_code,
                "population": max(population, 0),
                "latitude": latitude,
                "longitude": longitude,
                "aliases": aliases,
                "category": f"mountain_{CONTINENT_NAMES.get(continent, continent)}",
                "elevation_m": int(elevation),
            }
            override = ICONIC_MOUNTAIN_OVERRIDES.get(str(geonameid))
            if isinstance(override, dict):
                override_name = clean_alias(override.get("name", ""))
                if override_name:
                    entry["name"] = override_name
                merged_aliases = []
                for alias in list(entry.get("aliases", []) or []) + list(override.get("aliases", []) or []):
                    cleaned = clean_alias(alias)
                    if cleaned and cleaned not in merged_aliases:
                        merged_aliases.append(cleaned)
                    if len(merged_aliases) >= MAX_ALIASES_PER_ENTRY:
                        break
                entry["aliases"] = merged_aliases
            mountains_by_continent[continent].append(entry)
            mountains_by_geonameid[str(entry.get("geonameid", "") or "")] = entry
            name_key = normalize_lookup_key(entry.get("name", ""))
            country_key = str(entry.get("country_code", "") or "").strip().upper()
            if name_key and country_key:
                mountains_by_name_country[(name_key, country_key)] = entry

    selected_mountains = []
    for continent in CONTINENTS:
        entries = mountains_by_continent.get(continent, [])
        entries.sort(
            key=lambda item: (
                -int(item.get("elevation_m", 0) or 0),
                -int(item.get("population", 0) or 0),
                str(item.get("name", "")).lower(),
            )
        )
        selected_mountains.extend(entries[:100])
    selected_geonameids = {str(item.get("geonameid", "") or "") for item in selected_mountains}
    for geonameid, _override in ICONIC_MOUNTAIN_OVERRIDES.items():
        entry = mountains_by_geonameid.get(str(geonameid))
        if not entry:
            continue
        entry_id = str(entry.get("geonameid", "") or "")
        if not entry_id or entry_id in selected_geonameids:
            continue
        selected_mountains.append(entry)
        selected_geonameids.add(entry_id)
    for key in ICONIC_MOUNTAIN_FALLBACK_KEYS:
        entry = mountains_by_name_country.get(key)
        if not entry:
            continue
        entry_id = str(entry.get("geonameid", "") or "")
        if not entry_id or entry_id in selected_geonameids:
            continue
        selected_mountains.append(entry)
        selected_geonameids.add(entry_id)

    merged = []
    seen_geonameids = set()
    for bucket in (countries.values(), states.values(), islands.values(), selected_mountains):
        for entry in bucket:
            geonameid = str(entry.get("geonameid", "") or "")
            if not geonameid or geonameid in seen_geonameids:
                continue
            seen_geonameids.add(geonameid)
            merged.append(entry)
    merged.sort(key=lambda item: (str(item.get("category", "")), str(item.get("name", "")).lower()))
    return merged


def main():
    args = parse_args()
    allcountries_path = ensure_input_file(args.allcountries, DEFAULT_ALLCOUNTRIES_URL, "allCountries.zip")
    countryinfo_path = ensure_input_file(args.countryinfo, DEFAULT_COUNTRYINFO_URL, "countryInfo.txt")
    country_info_map = load_country_info(countryinfo_path)
    entries = build_entries(allcountries_path, country_info_map)

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)

    categories = {}
    for entry in entries:
        category = str(entry.get("category", "other"))
        categories[category] = int(categories.get(category, 0)) + 1
    print(f"Wrote {len(entries)} entries to {output_path}")
    for key in sorted(categories):
        print(f"  {key}: {categories[key]}")


if __name__ == "__main__":
    main()
