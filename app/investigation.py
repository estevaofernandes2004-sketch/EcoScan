"""
Investigation orchestrator for EcoScan.

Given an investigation request (lat/lon/radius/categories/+optional satellite
analysis), this module:

1. Checks the satellite cache (when applicable) so we never pay twice for the
   same area.
2. Fans out to the public sources (Nominatim, Overpass, GBIF, OpenAQ).
3. Optionally runs the satellite-vision pipeline through Ollama.
4. Hands the aggregated findings to ``llama3.2`` (via Ollama) for synthesis.
5. Persists the result to ``database/investigations.csv``.

The module exports two functions:

* ``run_manual_investigation`` — for the map-based workflow.
* ``run_complaint_investigation`` — wraps a complaint id and reuses the same
  pipeline, recording the link back to the originating complaint.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

import ollama

from app import sources, storage
from app.ai_workflow import (
    analyze_image,
    assess_danger,
    download_satellite_image,
    ensure_model,
)
from app.storage import IMAGES_DIR

ROOT = Path(__file__).resolve().parent.parent
MODELS_CONFIG = ROOT / "models.yaml"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_models_config(path: Path = MODELS_CONFIG) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Satellite branch (uses the existing ai_workflow + storage cache)
# ---------------------------------------------------------------------------


def _run_satellite_branch(
    lat: float, lon: float, zoom: int, config: Dict[str, Any]
) -> Dict[str, Any]:
    cached = storage.check_satellite_cache(lat, lon, zoom)
    if cached is not None:
        return {
            "ok": True,
            "from_cache": True,
            "image_path": cached.get("image_path"),
            "vision_model": cached.get("vision_model"),
            "vision_description": cached.get("vision_description"),
            "risk_model": cached.get("risk_model"),
            "risk_response": cached.get("risk_response"),
            "danger": str(cached.get("danger", "")).upper() == "Y",
        }

    try:
        image_path = download_satellite_image(lat, lon, zoom, str(IMAGES_DIR))
        description = analyze_image(image_path, config)
        risk_text, danger = assess_danger(description, config)
    except Exception as e:
        return {"ok": False, "error": f"Satellite pipeline failed: {e}"}

    # Persist only the filename — the absolute path is reconstructed at read
    # time from IMAGES_DIR, so renaming or moving the project folder doesn't
    # invalidate the cache.
    image_filename = image_path.name

    record = {
        "latitude": lat,
        "longitude": lon,
        "zoom": zoom,
        "image_path": image_filename,
        "vision_model": config["image_model"]["name"],
        "vision_prompt": _oneline(config["image_model"]["prompt"]),
        "vision_description": _oneline(description),
        "risk_model": config["text_model"]["name"],
        "risk_prompt": _oneline(config["text_model"]["prompt"]),
        "risk_response": _oneline(risk_text),
        "danger": "Y" if danger else "N",
    }
    storage.save_satellite_cache(record)

    return {
        "ok": True,
        "from_cache": False,
        "image_path": image_filename,
        "vision_model": config["image_model"]["name"],
        "vision_description": description,
        "risk_model": config["text_model"]["name"],
        "risk_response": risk_text,
        "danger": danger,
    }


# ---------------------------------------------------------------------------
# Synthesis (Ollama llama3.2 → JSON)
# ---------------------------------------------------------------------------


def _summarise_overpass(payload: Dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"  - Overpass FAILED: {payload.get('error', 'unknown')}"
    grouped = payload.get("grouped") or {}
    if not grouped:
        return "  - Overpass: no relevant POIs found in the selected categories."
    lines: List[str] = []
    for cat, items in grouped.items():
        sample = []
        for it in items[:5]:
            tag_summary = ", ".join(
                f"{k}={v}"
                for k, v in (it.get("tags") or {}).items()
                if k in {"amenity", "landuse", "man_made", "waterway", "natural", "leisure", "boundary", "name"}
            )
            sample.append(tag_summary or f"id={it.get('id')}")
        lines.append(f"  - {cat}: {len(items)} POIs (examples: {'; '.join(sample)})")
    return "\n".join(lines)


def _summarise_gbif(payload: Dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"  - GBIF FAILED: {payload.get('error', 'unknown')}"
    threatened = payload.get("threatened") or []
    total = payload.get("species_total", 0)
    if not threatened:
        return f"  - GBIF: {total} species recorded; none with IUCN VU/EN/CR status."
    sample = ", ".join(
        f"{s['species']} ({s['iucn']})" for s in threatened[:8]
    )
    return f"  - GBIF: {total} species recorded; {len(threatened)} threatened — {sample}."


def _summarise_openaq(payload: Dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"  - OpenAQ FAILED: {payload.get('error', 'unknown')}"
    if payload.get("note"):
        return f"  - OpenAQ: {payload['note']}"
    count = payload.get("station_count", 0)
    if count == 0:
        return "  - OpenAQ: no nearby air-quality stations."

    measurements = payload.get("measurements") or []
    if measurements:
        # Group readings by station for a compact, LLM-friendly summary.
        by_station: Dict[str, List[Dict[str, Any]]] = {}
        for m in measurements:
            by_station.setdefault(m.get("station") or "—", []).append(m)
        lines = [f"  - OpenAQ: {count} nearby stations with latest readings:"]
        for station, items in list(by_station.items())[:5]:
            readings = ", ".join(
                f"{m.get('parameter', '?')}={m.get('value')} {m.get('unit', '')}".strip()
                for m in items[:6]
            )
            lines.append(f"    • {station}: {readings}")
        return "\n".join(lines)

    stations = payload.get("stations") or []
    sample = "; ".join(
        f"{s.get('name', 'unnamed')} ({', '.join((s.get('parameters') or [])[:3])})"
        for s in stations[:5]
    )
    return f"  - OpenAQ: {count} nearby stations (no recent readings) — {sample}."


def _summarise_nominatim(payload: Dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"  - Nominatim FAILED: {payload.get('error', 'unknown')}"
    return (
        f"  - Location: {payload.get('display_name') or 'unknown'} "
        f"({payload.get('country_code', '').upper()})."
    )


def _summarise_satellite(payload: Optional[Dict[str, Any]]) -> str:
    if payload is None:
        return "  - Satellite analysis: NOT requested for this investigation."
    if not payload.get("ok"):
        return f"  - Satellite analysis FAILED: {payload.get('error', 'unknown')}"
    flag = "DANGER" if payload.get("danger") else "No significant danger"
    desc = payload.get("vision_description", "").strip().replace("\n", " ")
    desc = desc[:600] + ("..." if len(desc) > 600 else "")
    risk = payload.get("risk_response", "").strip().replace("\n", " ")
    risk = risk[:600] + ("..." if len(risk) > 600 else "")
    return (
        f"  - Visual analysis: {flag}.\n"
        f"    Image description: {desc}\n"
        f"    Visual assessment: {risk}"
    )


def _build_synthesis_prompt(
    title: str,
    description: str,
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    findings: Dict[str, Any],
    template: str,
) -> str:
    findings_text = "\n".join(
        [
            _summarise_nominatim(findings.get("nominatim", {})),
            _summarise_overpass(findings.get("overpass", {})),
            _summarise_gbif(findings.get("gbif", {})),
            _summarise_openaq(findings.get("openaq", {})),
            _summarise_satellite(findings.get("satellite")),
        ]
    )
    placeholders = {
        "{title}": title or "(untitled)",
        "{description}": description or "(no description)",
        "{lat}": f"{lat:.5f}",
        "{lon}": f"{lon:.5f}",
        "{radius_m}": str(radius_m),
        "{categories}": ", ".join(categories) if categories else "(none)",
        "{findings}": findings_text,
    }
    prompt = template
    for key, value in placeholders.items():
        prompt = prompt.replace(key, value)
    return prompt


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_synthesis_json(text: str) -> Dict[str, Any]:
    """Parse the model's JSON output, falling back to a safe structure."""
    raw = text.strip()
    # Strip markdown code fences if the model wrapped its JSON.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        return _fallback_synthesis(text)
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _fallback_synthesis(text)

    score = parsed.get("risk_score")
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = 50

    return {
        "risk_score": score,
        "summary": str(parsed.get("summary", "")).strip()
        or "No summary available.",
        "drivers": [str(d) for d in (parsed.get("drivers") or [])][:10],
        "recommendations": [
            str(r) for r in (parsed.get("recommendations") or [])
        ][:10],
    }


def _fallback_synthesis(text: str) -> Dict[str, Any]:
    return {
        "risk_score": 50,
        "summary": (
            "The model did not return a parseable response. "
            "Raw output: " + text.strip()[:400]
        ),
        "drivers": [],
        "recommendations": [
            "Review the raw evidence below manually.",
        ],
    }


def _synthesise(
    title: str,
    description: str,
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    findings: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    synth_cfg = config.get("synthesis") or {}
    model_name = synth_cfg.get("name") or config.get("text_model", {}).get("name", "llama3.2")
    template = synth_cfg.get("prompt") or _DEFAULT_SYNTHESIS_PROMPT

    ensure_model(model_name)

    prompt = _build_synthesis_prompt(
        title, description, lat, lon, radius_m, categories, findings, template
    )

    options: Dict[str, Any] = {}
    settings = synth_cfg.get("settings") or {}
    if "temperature" in settings:
        options["temperature"] = settings["temperature"]
    if "num_predict" in settings:
        options["num_predict"] = settings["num_predict"]

    try:
        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            options=options or None,
            format="json",
        )
        content = response.message.content
    except Exception as e:
        return _fallback_synthesis(f"Error calling the synthesis model: {e}")

    return _parse_synthesis_json(content)


# Default synthesis prompt — overridden if models.yaml contains one.
_DEFAULT_SYNTHESIS_PROMPT = """\
You are an environmental risk analyst working for a European environmental
inspection agency. You are given a preliminary investigation with the
location, context, and all evidence collected from public sources
(OpenStreetMap, GBIF, OpenAQ, and optionally a visual analysis of a
satellite image).

INVESTIGATION CONTEXT
Title: {title}
Description: {description}
Coordinates: ({lat}, {lon}) — radius {radius_m} m
Selected categories: {categories}

EVIDENCE COLLECTED
{findings}

TASK
Return EXCLUSIVELY a valid JSON object (no extra text, no markdown) with the
following structure, in English:

{
  "risk_score": <integer 0-100, where 100 is the highest risk>,
  "summary": "<2-4 sentences explaining your assessment>",
  "drivers": ["<risk driver 1>", "<risk driver 2>", ...],
  "recommendations": ["<concrete action 1>", "<concrete action 2>", ...]
}

Be conservative: if the evidence is weak or contradictory, lower the score
and justify. Focus the recommendations on actionable next steps for an
inspection team (site visit, sample collection, contact with the local
authority, etc.).
"""


def _oneline(text: str) -> str:
    return " ".join((text or "").replace("\r", "").split())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_manual_investigation(
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    title: str = "",
    description: str = "",
    vision_enabled: bool = False,
    zoom: Optional[int] = None,
) -> str:
    """
    Run a manual investigation and persist it. Returns the new investigation id.
    """
    return _run(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        categories=categories,
        title=title,
        description=description,
        vision_enabled=vision_enabled,
        zoom=zoom,
        source="manual",
        complaint_id=None,
    )


def run_complaint_investigation(
    complaint_id: str,
    radius_m: int,
    vision_enabled: bool = False,
    zoom: Optional[int] = None,
) -> str:
    """
    Run an investigation triggered by a complaint. The complaint's stored
    location, category and description seed the request.
    """
    complaint = storage.get_complaint(complaint_id)
    if complaint is None:
        raise ValueError(f"Unknown complaint: {complaint_id}")

    inv_id = _run(
        lat=float(complaint["latitude"]),
        lon=float(complaint["longitude"]),
        radius_m=radius_m,
        categories=[complaint["category"]],
        title=f"Complaint {complaint_id} — {complaint.get('location_text', '')}",
        description=str(complaint.get("description", "")),
        vision_enabled=vision_enabled,
        zoom=zoom,
        source="complaint",
        complaint_id=complaint_id,
    )

    storage.mark_complaint_status(complaint_id, "Under investigation")
    return inv_id


# ---------------------------------------------------------------------------
# Internal: shared pipeline
# ---------------------------------------------------------------------------


def _run(
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    title: str,
    description: str,
    vision_enabled: bool,
    zoom: Optional[int],
    source: str,
    complaint_id: Optional[str],
) -> str:
    config = load_models_config()
    findings = _collect_findings(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        categories=categories,
        vision_enabled=vision_enabled,
        zoom=zoom,
        config=config,
    )
    synthesis = _synthesise(
        title=title,
        description=description,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        categories=categories,
        findings=findings,
        config=config,
    )

    record = {
        "source": source,
        "complaint_id": complaint_id or "",
        "title": title,
        "description": description,
        "latitude": lat,
        "longitude": lon,
        "radius_m": radius_m,
        "categories": categories,
        "vision_enabled": vision_enabled,
        "zoom": zoom or "",
        "risk_score": synthesis["risk_score"],
        "result_json": {
            "synthesis": synthesis,
            "findings": findings,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return storage.save_investigation(record)


def _collect_findings(
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    vision_enabled: bool,
    zoom: Optional[int],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Run all data sources in parallel and gather their results."""
    tasks: Dict[str, Callable[[], Any]] = {
        "nominatim": lambda: sources.reverse_geocode(lat, lon),
        "overpass": lambda: sources.query_overpass(lat, lon, radius_m, categories),
        "gbif": lambda: sources.query_gbif(lat, lon, radius_m),
        "openaq": lambda: sources.query_openaq(lat, lon, radius_m),
    }
    if vision_enabled and zoom is not None:
        tasks["satellite"] = lambda: _run_satellite_branch(lat, lon, zoom, config)

    findings: Dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        future_map = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in concurrent.futures.as_completed(future_map):
            name = future_map[fut]
            try:
                findings[name] = fut.result()
            except Exception as e:
                findings[name] = {"ok": False, "error": str(e), "source": name}
    return findings
