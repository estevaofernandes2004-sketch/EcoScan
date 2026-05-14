"""
AI workflow module for EcoScan.

Handles satellite image download from ESRI World Imagery and
Ollama-based environmental risk assessment.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
import yaml
from PIL import Image

import ollama


# ---------------------------------------------------------------------------
# Satellite image download
# ---------------------------------------------------------------------------

def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert latitude/longitude to WMTS tile (x, y) at a given zoom level."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _download_tile(x: int, y: int, zoom: int) -> Optional[Image.Image]:
    """Download a single 256×256 ESRI World Imagery tile."""
    url = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        f"World_Imagery/MapServer/tile/{zoom}/{y}/{x}"
    )
    headers = {"User-Agent": "EcoScan/0.1 (academic project; contact: 70576@novasbe.pt)"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception:
        return None


def download_satellite_image(
    lat: float,
    lon: float,
    zoom: int,
    images_dir: str = "images",
    grid_size: int = 3,
) -> Path:
    """
    Download a satellite image from ESRI World Imagery for the given coordinates.

    Downloads a grid_size × grid_size grid of tiles centred on lat/lon and
    stitches them into a single PNG file.

    Parameters
    ----------
    lat : float
        Latitude of the centre point.
    lon : float
        Longitude of the centre point.
    zoom : int
        Zoom level (1–19).
    images_dir : str
        Directory where the image will be saved.
    grid_size : int
        Number of tiles per side (default 3 → 3×3 grid, 768×768 px).

    Returns
    -------
    Path
        Path to the saved image file.
    """
    images_path = Path(images_dir)
    images_path.mkdir(parents=True, exist_ok=True)

    image_filename = f"{lat}_{lon}_{zoom}.png"
    image_path = images_path / image_filename

    if image_path.exists():
        return image_path

    center_x, center_y = _lat_lon_to_tile(lat, lon, zoom)
    half = grid_size // 2
    tile_size = 256

    stitched = Image.new("RGB", (tile_size * grid_size, tile_size * grid_size))
    for row, dy in enumerate(range(-half, half + 1)):
        for col, dx in enumerate(range(-half, half + 1)):
            tile = _download_tile(center_x + dx, center_y + dy, zoom)
            if tile:
                stitched.paste(tile, (col * tile_size, row * tile_size))

    stitched.save(image_path)
    return image_path


# ---------------------------------------------------------------------------
# Models config
# ---------------------------------------------------------------------------

def load_models_config(config_path: str = "models.yaml") -> Dict[str, Any]:
    """Load model configuration from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def ensure_model(model_name: str) -> None:
    """Pull a model from Ollama if it is not already installed locally."""
    try:
        installed = ollama.list()
        installed_names = [m.model for m in installed.models]
        if not any(name.startswith(model_name) for name in installed_names):
            ollama.pull(model_name)
    except Exception:
        ollama.pull(model_name)


def analyze_image(image_path: Path, config: Dict[str, Any]) -> str:
    """
    Use the vision model to generate a description of the satellite image.

    Parameters
    ----------
    image_path : Path
        Path to the satellite image file.
    config : Dict[str, Any]
        Full models config loaded from models.yaml.

    Returns
    -------
    str
        Text description produced by the vision model.
    """
    model_name: str = config["image_model"]["name"]
    prompt: str = config["image_model"]["prompt"]

    ensure_model(model_name)

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = ollama.chat(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_bytes],
            }
        ],
    )
    return response.message.content.strip()


def assess_danger(description: str, config: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Use the text model to assess environmental danger from the image description.

    Parameters
    ----------
    description : str
        Image description from the vision model.
    config : Dict[str, Any]
        Full models config loaded from models.yaml.

    Returns
    -------
    Tuple[str, bool]
        Full assessment text and True if the area is flagged as at risk.
    """
    model_name: str = config["text_model"]["name"]
    prompt_template: str = config["text_model"]["prompt"]
    prompt = prompt_template.replace("{description}", description)

    ensure_model(model_name)

    response = ollama.chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.message.content.strip()
    danger = "DANGER: YES" in text.upper()
    return text, danger


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

DB_COLUMNS = [
    "timestamp",
    "latitude",
    "longitude",
    "zoom",
    "image_path",
    "image_description",
    "image_prompt",
    "image_model",
    "text_description",
    "text_prompt",
    "text_model",
    "danger",
]


def load_database(db_path: str = "database/images.csv") -> list:
    """Load the images database CSV into a list of dicts."""
    path = Path(db_path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_cache(
    lat: float,
    lon: float,
    zoom: int,
    db_path: str = "database/images.csv",
) -> Optional[Dict[str, Any]]:
    """
    Check if a result for lat/lon/zoom already exists in the database.

    Returns the cached row as a dict, or None if not found.
    """
    for row in load_database(db_path):
        try:
            if (
                float(row["latitude"]) == lat
                and float(row["longitude"]) == lon
                and int(row["zoom"]) == zoom
            ):
                return row
        except (ValueError, KeyError):
            continue
    return None


def save_to_database(
    record: Dict[str, Any],
    db_path: str = "database/images.csv",
) -> None:
    """Append a new record to the images database CSV."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in DB_COLUMNS})


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    lat: float,
    lon: float,
    zoom: int,
    config_path: str = "models.yaml",
    images_dir: str = "images",
    db_path: str = "database/images.csv",
) -> Dict[str, Any]:
    """
    Run the full AI assessment pipeline for the given coordinates.

    Checks the cache first; if a matching record is found the stored result
    is returned without re-running any models.

    Parameters
    ----------
    lat, lon : float
        Geographic coordinates of the area to assess.
    zoom : int
        Zoom level for the satellite image (1–19).
    config_path : str
        Path to models.yaml.
    images_dir : str
        Directory used to save satellite images.
    db_path : str
        Path to the images database CSV.

    Returns
    -------
    Dict[str, Any]
        Result dict with keys matching DB_COLUMNS plus 'from_cache' (bool).
    """
    cached = check_cache(lat, lon, zoom, db_path)
    if cached:
        cached["from_cache"] = True
        return cached

    config = load_models_config(config_path)

    image_path = download_satellite_image(lat, lon, zoom, images_dir)
    image_description = analyze_image(image_path, config)
    text_description, danger = assess_danger(image_description, config)

    def _oneline(text: str) -> str:
        """Collapse newlines so each CSV record stays on a single row."""
        return " ".join(text.replace("\r", "").split())

    record: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "latitude": lat,
        "longitude": lon,
        "zoom": zoom,
        "image_path": str(image_path),
        "image_description": _oneline(image_description),
        "image_prompt": _oneline(config["image_model"]["prompt"]),
        "image_model": config["image_model"]["name"],
        "text_description": _oneline(text_description),
        "text_prompt": _oneline(config["text_model"]["prompt"]),
        "text_model": config["text_model"]["name"],
        "danger": "Y" if danger else "N",
    }

    save_to_database(record, db_path)
    record["from_cache"] = False
    return record
