"""
Persistence layer for EcoScan.

Handles three local data files:

* ``database/complaints.xlsx`` — simulated environmental complaints used by
  the complaint-driven workflow. Auto-seeded if missing.
* ``database/investigations.csv`` — log of every investigation run by the app.
* ``database/satellite_cache.csv`` — cached results of the optional satellite
  module (avoids re-running Ollama for the same coordinates).
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"
IMAGES_DIR = ROOT / "images"
COMPLAINTS_PATH = DB_DIR / "complaints.xlsx"
INVESTIGATIONS_PATH = DB_DIR / "investigations.csv"
SATELLITE_CACHE_PATH = DB_DIR / "satellite_cache.csv"

INVESTIGATION_COLUMNS = [
    "id",
    "timestamp",
    "source",
    "complaint_id",
    "title",
    "description",
    "latitude",
    "longitude",
    "radius_m",
    "categories",
    "vision_enabled",
    "zoom",
    "risk_score",
    "result_json",
]

SATELLITE_CACHE_COLUMNS = [
    "latitude",
    "longitude",
    "zoom",
    "image_path",
    "vision_model",
    "vision_prompt",
    "vision_description",
    "risk_model",
    "risk_prompt",
    "risk_response",
    "danger",
    "timestamp",
]

# ---------------------------------------------------------------------------
# Complaints (Excel) — read & seed
# ---------------------------------------------------------------------------

# Realistic-but-fictional complaints across mainland Portugal, written in
# English for international audiences. Used to seed database/complaints.xlsx
# the first time the app runs. The user can edit the Excel file freely
# afterwards; the seed only triggers if the file is missing.
_SEED_COMPLAINTS: List[Dict[str, Any]] = [
    {
        "id": "REP-2026-001",
        "timestamp_received": "2026-04-28T09:14:00",
        "channel": "Citizen Portal",
        "reporter_name": "Maria Silva",
        "location_text": "Trancão River, Loures",
        "latitude": 38.8094,
        "longitude": -9.1456,
        "category": "water",
        "description": "Discharge of a whitish liquid from a pipe next to the riverbank. Strong chemical smell.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-002",
        "timestamp_received": "2026-04-28T11:42:00",
        "channel": "Phone",
        "reporter_name": "João Pereira",
        "location_text": "Setúbal industrial zone",
        "latitude": 38.5260,
        "longitude": -8.8345,
        "category": "air",
        "description": "Thick, dark fumes continuously rising from an industrial chimney since 6 a.m. Visibility reduced in the surrounding area.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-003",
        "timestamp_received": "2026-04-29T08:05:00",
        "channel": "Email",
        "reporter_name": "Anonymous",
        "location_text": "Sintra hills, next to road EN247",
        "latitude": 38.7892,
        "longitude": -9.4310,
        "category": "waste",
        "description": "Accumulation of construction debris dumped inside a protected forest area. At least five piles visible.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-004",
        "timestamp_received": "2026-04-29T15:23:00",
        "channel": "Mobile App",
        "reporter_name": "Rita Almeida",
        "location_text": "Aveiro lagoon, Mira channel",
        "latitude": 40.6010,
        "longitude": -8.7430,
        "category": "water",
        "description": "Oily slick visible on the surface of the lagoon, around 50 metres long. Dead fish along the shoreline.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-005",
        "timestamp_received": "2026-04-30T10:11:00",
        "channel": "Citizen Portal",
        "reporter_name": "Carlos Mendes",
        "location_text": "Sines, next to the industrial port",
        "latitude": 37.9510,
        "longitude": -8.8702,
        "category": "air",
        "description": "Strong, persistent hydrocarbon smell during the night. Several residents reporting eye irritation symptoms.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-006",
        "timestamp_received": "2026-04-30T14:45:00",
        "channel": "Phone",
        "reporter_name": "Ana Sousa",
        "location_text": "Ave Valley, Vila Nova de Famalicão",
        "latitude": 41.4090,
        "longitude": -8.5180,
        "category": "water",
        "description": "Reddish discoloration in a tributary stream of the Ave river. Always happens after 10 p.m.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-007",
        "timestamp_received": "2026-05-01T07:30:00",
        "channel": "Mobile App",
        "reporter_name": "Luís Tavares",
        "location_text": "Panasqueiras mine, Covilhã",
        "latitude": 40.1730,
        "longitude": -7.7600,
        "category": "water",
        "description": "Yellowish runoff coming from old mining waste piles after heavy rain. Suspected acid mine drainage.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-008",
        "timestamp_received": "2026-05-01T12:01:00",
        "channel": "Email",
        "reporter_name": "Patrícia Lopes",
        "location_text": "Quinta do Anjo, Palmela",
        "latitude": 38.5615,
        "longitude": -8.9382,
        "category": "biodiversity",
        "description": "Recent felling of centuries-old cork oaks on a plot inside a Natura 2000 area. No permit signage visible.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-009",
        "timestamp_received": "2026-05-02T09:48:00",
        "channel": "Citizen Portal",
        "reporter_name": "Anonymous",
        "location_text": "Vila Franca de Xira, Tagus riverbank",
        "latitude": 38.9540,
        "longitude": -8.9920,
        "category": "water",
        "description": "Abnormally dark water along the shore in recent weeks. Persistent white foam at several points.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-010",
        "timestamp_received": "2026-05-02T16:22:00",
        "channel": "Phone",
        "reporter_name": "Tiago Marques",
        "location_text": "Estarreja, next to the EB1 primary school",
        "latitude": 40.7570,
        "longitude": -8.5710,
        "category": "air",
        "description": "Nightly release of strong chemical-smelling gases from the industrial complex. Children reporting respiratory complaints.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-011",
        "timestamp_received": "2026-05-03T08:15:00",
        "channel": "Mobile App",
        "reporter_name": "Beatriz Costa",
        "location_text": "Ria Formosa, Olhão",
        "latitude": 37.0270,
        "longitude": -7.8410,
        "category": "water",
        "description": "Vessel observed discharging liquids into the channel during the night. Grey slick visible at dawn.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-012",
        "timestamp_received": "2026-05-03T13:09:00",
        "channel": "Citizen Portal",
        "reporter_name": "Hugo Ribeiro",
        "location_text": "Costa da Caparica, Mata beach",
        "latitude": 38.6320,
        "longitude": -9.2360,
        "category": "waste",
        "description": "Large quantity of plastics and fishing nets piled up on the beach, possibly abandoned by illegal fishing operations.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-013",
        "timestamp_received": "2026-05-04T10:55:00",
        "channel": "Email",
        "reporter_name": "Sofia Vieira",
        "location_text": "Montemor-o-Novo, livestock farm",
        "latitude": 38.6480,
        "longitude": -8.2150,
        "category": "water",
        "description": "Slurry runoff directed into a watercourse with no treatment of any kind. Strong smell carrying several kilometres.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-014",
        "timestamp_received": "2026-05-04T17:34:00",
        "channel": "Phone",
        "reporter_name": "Anonymous",
        "location_text": "Trás-os-Montes, near Mirandela",
        "latitude": 41.4920,
        "longitude": -7.1830,
        "category": "biodiversity",
        "description": "Open burning on private land with no visible authorization. Risk of spreading into a native oak woodland.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-015",
        "timestamp_received": "2026-05-05T09:02:00",
        "channel": "Mobile App",
        "reporter_name": "Marta Rosa",
        "location_text": "Maia, near the A4 motorway",
        "latitude": 41.2380,
        "longitude": -8.6210,
        "category": "air",
        "description": "Thick black smoke released from an industrial unit twice a week, always in the late afternoon.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-016",
        "timestamp_received": "2026-05-05T11:48:00",
        "channel": "Citizen Portal",
        "reporter_name": "Pedro Antunes",
        "location_text": "Beja, rural area",
        "latitude": 38.0150,
        "longitude": -7.8650,
        "category": "waste",
        "description": "Illegal dumping of metal drums containing unknown substances on an abandoned agricultural property.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-017",
        "timestamp_received": "2026-05-06T08:30:00",
        "channel": "Email",
        "reporter_name": "Inês Domingues",
        "location_text": "Cascais, Quinta do Pisão",
        "latitude": 38.7460,
        "longitude": -9.4410,
        "category": "biodiversity",
        "description": "Invasive species (acacias) sighted rapidly expanding inside the park. No control measures in recent months.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-018",
        "timestamp_received": "2026-05-06T14:17:00",
        "channel": "Mobile App",
        "reporter_name": "Rui Carvalho",
        "location_text": "Castelo Branco, unmarked quarry",
        "latitude": 39.8240,
        "longitude": -7.4910,
        "category": "waste",
        "description": "Quarry operating with no identification sign or safety markings. Trucks coming in and out during the night.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-019",
        "timestamp_received": "2026-05-07T10:23:00",
        "channel": "Phone",
        "reporter_name": "Catarina Nunes",
        "location_text": "Algarve, Sagres — protected area",
        "latitude": 37.0150,
        "longitude": -8.9410,
        "category": "biodiversity",
        "description": "Construction works ongoing inside the perimeter of the Southwest Alentejo and Vicentine Coast Natural Park.",
        "status": "Pending",
    },
    {
        "id": "REP-2026-020",
        "timestamp_received": "2026-05-07T16:05:00",
        "channel": "Citizen Portal",
        "reporter_name": "Anonymous",
        "location_text": "Mondego river, near Coimbra",
        "latitude": 40.2050,
        "longitude": -8.4290,
        "category": "water",
        "description": "Marked greenish discoloration with algal blooms. Suspected eutrophication from agricultural discharges.",
        "status": "Pending",
    },
]


def _ensure_db_dir() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)


def _seed_complaints_file() -> None:
    """Write database/complaints.xlsx from the seed list."""
    _ensure_db_dir()
    df = pd.DataFrame(_SEED_COMPLAINTS)
    df.to_excel(COMPLAINTS_PATH, index=False)


def load_complaints() -> pd.DataFrame:
    """
    Load complaints from the Excel file. Auto-seeds the file the first time.

    Returns
    -------
    pd.DataFrame
        One row per complaint, columns matching the seed schema.
    """
    if not COMPLAINTS_PATH.exists():
        _seed_complaints_file()
    return pd.read_excel(COMPLAINTS_PATH)


def get_complaint(complaint_id: str) -> Optional[Dict[str, Any]]:
    """Return a single complaint by id, or None if not found."""
    df = load_complaints()
    rows = df[df["id"] == complaint_id]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def mark_complaint_status(complaint_id: str, status: str) -> None:
    """Update the status of a complaint in the Excel file."""
    df = load_complaints()
    df.loc[df["id"] == complaint_id, "status"] = status
    df.to_excel(COMPLAINTS_PATH, index=False)


# ---------------------------------------------------------------------------
# Investigations (CSV)
# ---------------------------------------------------------------------------


def _ensure_investigations_file() -> None:
    _ensure_db_dir()
    if INVESTIGATIONS_PATH.exists() and INVESTIGATIONS_PATH.stat().st_size > 0:
        return
    with open(INVESTIGATIONS_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=INVESTIGATION_COLUMNS).writeheader()


def save_investigation(record: Dict[str, Any]) -> str:
    """
    Append a new investigation to investigations.csv.

    The record may omit ``id`` and ``timestamp``; both are filled in here.
    Returns the assigned investigation id.
    """
    _ensure_investigations_file()
    inv_id = record.get("id") or str(uuid.uuid4())
    timestamp = record.get("timestamp") or datetime.now(timezone.utc).isoformat()

    row = {col: "" for col in INVESTIGATION_COLUMNS}
    row.update(record)
    row["id"] = inv_id
    row["timestamp"] = timestamp

    # Coerce non-string values (lists, dicts, booleans) to safe CSV strings.
    if isinstance(row.get("categories"), (list, tuple)):
        row["categories"] = ";".join(row["categories"])
    if isinstance(row.get("result_json"), (dict, list)):
        row["result_json"] = json.dumps(row["result_json"], ensure_ascii=False)
    row["vision_enabled"] = "true" if row.get("vision_enabled") else "false"

    with open(INVESTIGATIONS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVESTIGATION_COLUMNS)
        writer.writerow({k: row.get(k, "") for k in INVESTIGATION_COLUMNS})

    return inv_id


def load_investigations() -> pd.DataFrame:
    """Load all investigations as a DataFrame (newest first)."""
    _ensure_investigations_file()
    if INVESTIGATIONS_PATH.stat().st_size == 0:
        return pd.DataFrame(columns=INVESTIGATION_COLUMNS)
    df = pd.read_csv(INVESTIGATIONS_PATH)
    if df.empty:
        return df
    df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    return df


def get_investigation(investigation_id: str) -> Optional[Dict[str, Any]]:
    """Return a single investigation by id, with result_json parsed."""
    df = load_investigations()
    rows = df[df["id"] == investigation_id]
    if rows.empty:
        return None
    record = rows.iloc[0].to_dict()

    # pandas turns empty CSV cells into NaN; coerce missing string fields back
    # to "" so downstream `if record.get(...)` checks don't see NaN as truthy.
    for key in ("title", "description", "complaint_id"):
        value = record.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            record[key] = ""

    raw = record.get("result_json")
    if isinstance(raw, str) and raw.strip():
        try:
            record["result"] = json.loads(raw)
        except json.JSONDecodeError:
            record["result"] = None
    else:
        record["result"] = None
    record["vision_enabled"] = str(record.get("vision_enabled", "")).lower() == "true"
    cats = record.get("categories")
    if isinstance(cats, str) and cats:
        record["categories"] = [c for c in cats.split(";") if c]
    else:
        record["categories"] = []
    return record


# ---------------------------------------------------------------------------
# Satellite-analysis cache (CSV)
# ---------------------------------------------------------------------------


def _ensure_satellite_cache_file() -> None:
    _ensure_db_dir()
    if SATELLITE_CACHE_PATH.exists() and SATELLITE_CACHE_PATH.stat().st_size > 0:
        return
    with open(SATELLITE_CACHE_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=SATELLITE_CACHE_COLUMNS).writeheader()


def check_satellite_cache(
    lat: float, lon: float, zoom: int
) -> Optional[Dict[str, Any]]:
    """Return a cached satellite analysis for these exact coords, or None."""
    _ensure_satellite_cache_file()
    if SATELLITE_CACHE_PATH.stat().st_size == 0:
        return None
    df = pd.read_csv(SATELLITE_CACHE_PATH)
    match = df[
        (df["latitude"] == lat) & (df["longitude"] == lon) & (df["zoom"] == zoom)
    ]
    if match.empty:
        return None
    return match.iloc[-1].to_dict()


def save_satellite_cache(record: Dict[str, Any]) -> None:
    """Append a satellite-analysis record to the cache."""
    _ensure_satellite_cache_file()
    row = {col: record.get(col, "") for col in SATELLITE_CACHE_COLUMNS}
    row["timestamp"] = row.get("timestamp") or datetime.now(timezone.utc).isoformat()
    with open(SATELLITE_CACHE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SATELLITE_CACHE_COLUMNS)
        writer.writerow(row)
