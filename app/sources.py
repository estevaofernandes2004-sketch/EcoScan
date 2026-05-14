"""
Public-data source clients used by the EcoScan investigation pipeline.

Every function here is best-effort: external APIs sometimes time out or rate-
limit. On any failure the function returns a structured "error" dict instead
of raising, so the orchestrator can keep going with whatever evidence it
managed to collect.

Sources:
* Nominatim (OpenStreetMap) — reverse geocoding.
* Overpass (OpenStreetMap) — POIs near the inspection point.
* GBIF — species occurrences, with IUCN-flagged ones isolated.
* OpenAQ v3 — nearby air-quality monitoring stations.
"""

from __future__ import annotations

import concurrent.futures
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

USER_AGENT = "EcoScan/0.1 (academic project; contact: 70576@novasbe.pt)"
DEFAULT_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bbox_from_radius(lat: float, lon: float, radius_m: int) -> Dict[str, float]:
    """
    Compute a rough lat/lon bounding box from a centre point and a radius.

    Uses a flat-earth approximation (good enough for radii up to a few tens
    of kilometres at non-polar latitudes).
    """
    lat_delta = radius_m / 111_320.0
    lon_delta = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return {
        "south": lat - lat_delta,
        "north": lat + lat_delta,
        "west": lon - lon_delta,
        "east": lon + lon_delta,
    }


def _error(source: str, message: str) -> Dict[str, Any]:
    return {"source": source, "ok": False, "error": message}


def _ok(source: str, **payload: Any) -> Dict[str, Any]:
    return {"source": source, "ok": True, **payload}


# ---------------------------------------------------------------------------
# Nominatim — reverse geocoding
# ---------------------------------------------------------------------------


def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """Return a human-readable address + country for a coordinate."""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14}
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return _error("nominatim", str(e))

    return _ok(
        "nominatim",
        display_name=data.get("display_name", ""),
        country=(data.get("address") or {}).get("country", ""),
        country_code=(data.get("address") or {}).get("country_code", ""),
        municipality=(data.get("address") or {}).get("municipality", "")
        or (data.get("address") or {}).get("city", "")
        or (data.get("address") or {}).get("town", "")
        or (data.get("address") or {}).get("village", ""),
        raw=data,
    )


def search_place(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Forward-geocode a place name to a list of candidates."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "jsonv2", "limit": limit}
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json() or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Overpass — POIs by category
# ---------------------------------------------------------------------------

# Each category maps to a list of Overpass selectors. The orchestrator queries
# only the categories the inspector chose. Selectors target features that are
# directly relevant to the kind of infraction implied by the category.
_CATEGORY_SELECTORS: Dict[str, List[str]] = {
    "waste": [
        'node["amenity"="waste_transfer_station"]',
        'way["amenity"="waste_transfer_station"]',
        'node["amenity"="recycling"]',
        'way["landuse"="landfill"]',
        'node["man_made"="waste_disposal"]',
    ],
    "water": [
        # Always relevant: major waterways and treatment infrastructure.
        'way["waterway"~"river|canal"]',
        'node["man_made"="wastewater_plant"]',
        'way["man_made"="wastewater_plant"]',
        # Smaller waterways and water bodies only when named (filters out
        # the long tail of unnamed brooks and tiny farm reservoirs that
        # otherwise drown the signal).
        'way["waterway"~"stream|drain"]["name"]',
        'way["natural"="water"]["name"]',
    ],
    "air": [
        'way["landuse"="industrial"]',
        'node["man_made"="chimney"]',
        'way["man_made"="works"]',
        'node["man_made"="works"]',
    ],
    "biodiversity": [
        'way["boundary"="protected_area"]',
        'relation["boundary"="protected_area"]',
        'way["leisure"="nature_reserve"]',
        'way["natural"="wood"]',
    ],
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


_OVERPASS_PER_CATEGORY_LIMIT = 150


def _build_overpass_query(
    bbox: Dict[str, float], categories: Iterable[str]
) -> Optional[str]:
    """
    Build an Overpass-QL query that gives each category its own result set
    and its own output limit.

    A single union query with a global `out N` cap is unfair in dense areas
    (e.g. Lisbon with all four categories): the first categories iterated
    saturate the cap, leaving later ones empty. By assigning every category
    to a named set (``-> .water`` etc.) and calling ``out`` once per set,
    each category is guaranteed up to ``_OVERPASS_PER_CATEGORY_LIMIT``
    elements regardless of the others.
    """
    bbox_str = f"({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']})"
    active_categories = [c for c in categories if _CATEGORY_SELECTORS.get(c)]
    if not active_categories:
        return None

    body_blocks: List[str] = []
    out_lines: List[str] = []
    for cat in active_categories:
        selector_lines = "\n  ".join(
            f"{selector}{bbox_str};" for selector in _CATEGORY_SELECTORS[cat]
        )
        body_blocks.append(f"(\n  {selector_lines}\n) -> .{cat};")
        out_lines.append(
            f".{cat} out center tags {_OVERPASS_PER_CATEGORY_LIMIT};"
        )

    return (
        "[out:json][timeout:25];\n"
        + "\n".join(body_blocks)
        + "\n"
        + "\n".join(out_lines)
    )


def query_overpass(
    lat: float, lon: float, radius_m: int, categories: Iterable[str]
) -> Dict[str, Any]:
    """Query Overpass for POIs within ``radius_m`` of (lat, lon) per category."""
    bbox = _bbox_from_radius(lat, lon, radius_m)
    query = _build_overpass_query(bbox, categories)
    if not query:
        return _ok("overpass", elements=[], grouped={}, total=0)
    try:
        r = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": USER_AGENT},
            timeout=60,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        return _error("overpass", str(e))

    elements = payload.get("elements", [])

    # Group elements back into the inspector's category buckets so the UI
    # can show per-category counts.
    grouped: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in categories}
    for el in elements:
        tags = el.get("tags", {}) or {}
        for cat in categories:
            if _matches_category(tags, cat):
                grouped[cat].append(
                    {
                        "id": el.get("id"),
                        "type": el.get("type"),
                        "lat": el.get("lat") or (el.get("center") or {}).get("lat"),
                        "lon": el.get("lon") or (el.get("center") or {}).get("lon"),
                        "tags": tags,
                    }
                )
                break

    # Deduplicate by name within each category (a single named river is often
    # split into many OSM ways) and sort by relevance to the inspector.
    grouped = {cat: _refine_category_items(cat, items) for cat, items in grouped.items()}

    return _ok(
        "overpass",
        elements=elements,
        grouped={k: v for k, v in grouped.items() if v},
        total=sum(len(v) for v in grouped.values()),
    )


def _refine_category_items(
    category: str, items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Collapse same-named items into one and sort by inspection priority.

    - Items with the same ``tags["name"]`` are merged into a single row that
      records how many OSM segments fed into it (``segments`` field).
    - Items without a name are kept individually.
    - Within ``water``, wastewater treatment plants are surfaced first
      (they are the highest-signal evidence for an inspector).
    """
    seen: Dict[str, Dict[str, Any]] = {}
    unnamed: List[Dict[str, Any]] = []
    for it in items:
        name = (it.get("tags") or {}).get("name", "").strip()
        if not name:
            unnamed.append(dict(it, segments=1))
            continue
        if name in seen:
            seen[name]["segments"] += 1
        else:
            seen[name] = dict(it, segments=1)

    refined = list(seen.values()) + unnamed

    if category == "water":
        refined.sort(key=_water_priority)
    return refined


def _water_priority(item: Dict[str, Any]) -> int:
    tags = item.get("tags") or {}
    if tags.get("man_made") == "wastewater_plant":
        return 0
    if tags.get("waterway") in {"river", "canal"}:
        return 1
    if tags.get("waterway") in {"stream", "drain"}:
        return 2
    return 3


def _matches_category(tags: Dict[str, str], category: str) -> bool:
    if category == "waste":
        return (
            tags.get("amenity") in {"waste_transfer_station", "recycling"}
            or tags.get("landuse") == "landfill"
            or tags.get("man_made") == "waste_disposal"
        )
    if category == "water":
        # Underground/piped waterways are infrastructure, not surface water.
        if tags.get("tunnel") in {"culvert", "yes"}:
            return False
        if tags.get("man_made") == "wastewater_plant":
            return True
        waterway = tags.get("waterway")
        if waterway in {"river", "canal"}:
            return True
        if waterway in {"stream", "drain"} and tags.get("name"):
            return True
        if tags.get("natural") == "water" and tags.get("name"):
            return True
        return False
    if category == "air":
        return (
            tags.get("landuse") == "industrial"
            or tags.get("man_made") in {"chimney", "works"}
        )
    if category == "biodiversity":
        return (
            tags.get("boundary") == "protected_area"
            or tags.get("leisure") == "nature_reserve"
            or tags.get("natural") == "wood"
        )
    return False


# ---------------------------------------------------------------------------
# GBIF — biodiversity occurrences
# ---------------------------------------------------------------------------

GBIF_URL = "https://api.gbif.org/v1/occurrence/search"
_THREATENED_STATUSES = {"VULNERABLE", "ENDANGERED", "CRITICALLY_ENDANGERED"}


def query_gbif(
    lat: float, lon: float, radius_m: int, limit: int = 100
) -> Dict[str, Any]:
    """Fetch recent species occurrences in the bounding box and isolate IUCN-flagged ones."""
    bbox = _bbox_from_radius(lat, lon, radius_m)
    geometry = (
        f"POLYGON(({bbox['west']} {bbox['south']},"
        f"{bbox['east']} {bbox['south']},"
        f"{bbox['east']} {bbox['north']},"
        f"{bbox['west']} {bbox['north']},"
        f"{bbox['west']} {bbox['south']}))"
    )
    params = {"geometry": geometry, "limit": limit, "hasCoordinate": "true"}
    try:
        r = requests.get(
            GBIF_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        return _error("gbif", str(e))

    results = payload.get("results", []) or []
    species_seen: Dict[str, Dict[str, Any]] = {}
    for occ in results:
        name = occ.get("species") or occ.get("scientificName")
        if not name:
            continue
        existing = species_seen.get(name)
        status = (occ.get("iucnRedListCategory") or "").upper()
        if existing is None:
            species_seen[name] = {
                "species": name,
                "vernacular": occ.get("vernacularName", ""),
                "kingdom": occ.get("kingdom", ""),
                "iucn": status,
                "count": 1,
            }
        else:
            existing["count"] += 1
            if not existing["iucn"] and status:
                existing["iucn"] = status

    species = list(species_seen.values())
    threatened = [s for s in species if s["iucn"] in _THREATENED_STATUSES]
    return _ok(
        "gbif",
        species_total=len(species),
        species=species[:50],
        threatened=threatened,
    )


# ---------------------------------------------------------------------------
# OpenAQ v3 — air-quality stations
# ---------------------------------------------------------------------------

OPENAQ_URL = "https://api.openaq.org/v3/locations"
OPENAQ_LATEST_URL = "https://api.openaq.org/v3/locations/{location_id}/latest"


def query_openaq(lat: float, lon: float, radius_m: int) -> Dict[str, Any]:
    """
    List air-quality monitoring stations within ``radius_m`` of (lat, lon)
    AND fetch the latest reading per sensor at each station.

    OpenAQ v3 requires a (free) API key. Set the ``OPENAQ_API_KEY``
    environment variable to enable this source. Without it, this function
    returns an empty result rather than a hard error so the rest of the
    investigation continues unaffected.

    The follow-up "latest" calls are made in parallel and are best-effort:
    if a single station fails, the station still appears in the result but
    with no measurements attached.
    """
    api_key = os.environ.get("OPENAQ_API_KEY", "").strip()
    if not api_key:
        return _ok(
            "openaq",
            station_count=0,
            stations=[],
            measurements=[],
            note="OpenAQ disabled: set OPENAQ_API_KEY to enable air-quality data.",
        )

    # OpenAQ v3 caps radius at 25 000 m.
    capped = min(radius_m, 25_000)
    params = {
        "coordinates": f"{lat},{lon}",
        "radius": capped,
        "limit": 25,
    }
    headers = {"User-Agent": USER_AGENT, "X-API-Key": api_key}
    try:
        r = requests.get(OPENAQ_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 401:
            return _ok(
                "openaq",
                station_count=0,
                stations=[],
                measurements=[],
                note="OpenAQ rejected the API key (401). Check OPENAQ_API_KEY.",
            )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        return _error("openaq", str(e))

    results = payload.get("results", []) or []

    # Parse stations and build a sensor_id → metadata lookup so we can attach
    # parameter / unit / station name to each "latest" measurement later.
    stations: List[Dict[str, Any]] = []
    sensor_lookup: Dict[int, Dict[str, str]] = {}

    for loc in results:
        loc_id = loc.get("id")
        loc_name = loc.get("name") or "unnamed"

        country_obj = loc.get("country") or {}
        country = (
            country_obj.get("name", "") if isinstance(country_obj, dict) else str(country_obj or "")
        )

        param_names: List[str] = []
        for sensor in (loc.get("sensors") or []):
            sensor_id = sensor.get("id")
            param_obj = sensor.get("parameter") or {}
            pname = param_obj.get("name") or param_obj.get("displayName") or ""
            punit = param_obj.get("units") or param_obj.get("unit") or ""
            if pname:
                param_names.append(pname)
            if sensor_id is not None:
                sensor_lookup[sensor_id] = {
                    "parameter": pname,
                    "unit": punit,
                    "location_id": loc_id,
                    "location_name": loc_name,
                }

        stations.append(
            {
                "id": loc_id,
                "name": loc_name,
                "country": country,
                "parameters": param_names,
                "coordinates": loc.get("coordinates"),
            }
        )

    measurements = _fetch_openaq_latest(stations, sensor_lookup, headers)

    return _ok(
        "openaq",
        station_count=len(stations),
        stations=stations,
        measurements=measurements,
    )


def _fetch_openaq_latest(
    stations: List[Dict[str, Any]],
    sensor_lookup: Dict[int, Dict[str, str]],
    headers: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Fan out to ``/v3/locations/{id}/latest`` for every station in parallel
    and return a flat list of ``{station, parameter, value, unit, when}``.

    Best-effort: any per-station failure is silently skipped so the rest of
    the investigation is unaffected. Sensor IDs from the latest response are
    looked up against ``sensor_lookup`` to attach the parameter name + unit
    that the location response declared.
    """
    location_ids = [s.get("id") for s in stations if s.get("id") is not None]
    if not location_ids:
        return []

    def _fetch_one(location_id: int) -> List[Dict[str, Any]]:
        url = OPENAQ_LATEST_URL.format(location_id=location_id)
        try:
            r = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            return r.json().get("results", []) or []
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(8, len(location_ids))
    ) as ex:
        per_location_results = list(ex.map(_fetch_one, location_ids))

    flat: List[Dict[str, Any]] = []
    for loc_results in per_location_results:
        for m in loc_results:
            sensor_id = m.get("sensorsId")
            value = m.get("value")
            dt_obj = m.get("datetime")
            when = ""
            if isinstance(dt_obj, dict):
                when = dt_obj.get("utc", "") or dt_obj.get("local", "")
            elif isinstance(dt_obj, str):
                when = dt_obj

            meta = sensor_lookup.get(sensor_id, {})
            param = meta.get("parameter", "")
            unit = meta.get("unit", "")
            station_name = meta.get("location_name", "")

            if value is None or not param:
                continue

            flat.append(
                {
                    "station": station_name,
                    "parameter": param,
                    "value": value,
                    "unit": unit,
                    "when": when,
                }
            )

    return flat
