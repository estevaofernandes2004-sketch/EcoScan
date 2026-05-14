"""Shared helpers for the EcoScan Streamlit views."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import streamlit as st
from streamlit_folium import st_folium

from app.storage import IMAGES_DIR

CATEGORY_LABELS: Dict[str, str] = {
    "waste": "Waste",
    "water": "Water",
    "air": "Air",
    "biodiversity": "Biodiversity",
}

CATEGORY_OPTIONS: List[str] = list(CATEGORY_LABELS.keys())


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def categories_label(categories: List[str]) -> str:
    if not categories:
        return "—"
    return ", ".join(category_label(c) for c in categories)


def overpass_label(tags: Optional[Dict[str, str]]) -> str:
    """
    Human-readable label for an OSM element.

    Prefers the real ``name`` (or ``alt_name``) when OSM provides one,
    otherwise synthesises a label from the most informative tag so the UI
    never shows a blank cell (e.g. "Recycling container", "Wastewater plant",
    "Nature reserve"). The underlying OSM tags are not modified.
    """
    tags = tags or {}
    name = (tags.get("name") or "").strip()
    if name:
        return name
    alt = (tags.get("alt_name") or "").strip()
    if alt:
        # alt_name is often "Ecoponto;Ponto de Reciclagem" — take the first.
        return alt.split(";", 1)[0].strip()

    # ---- Waste ----------------------------------------------------------
    if tags.get("amenity") == "recycling":
        rtype = tags.get("recycling_type", "")
        if rtype == "centre":
            return "Recycling centre"
        if rtype == "container":
            return "Recycling container"
        materials = sorted(
            k.split(":", 1)[1]
            for k, v in tags.items()
            if k.startswith("recycling:") and v in {"yes", "1", "true"}
        )
        if materials:
            return f"Recycling point ({', '.join(materials[:3])})"
        return "Recycling point"
    if tags.get("amenity") == "waste_transfer_station":
        return "Waste transfer station"
    if tags.get("landuse") == "landfill":
        return "Landfill"
    if tags.get("man_made") == "waste_disposal":
        return "Waste disposal"

    # ---- Water ----------------------------------------------------------
    waterway = tags.get("waterway")
    if waterway:
        return waterway.capitalize()
    if tags.get("man_made") == "wastewater_plant":
        return "Wastewater plant"
    if tags.get("natural") == "water":
        return "Water body"

    # ---- Air ------------------------------------------------------------
    if tags.get("landuse") == "industrial":
        return "Industrial area"
    if tags.get("man_made") == "chimney":
        return "Chimney"
    if tags.get("man_made") == "works":
        return "Industrial works"

    # ---- Biodiversity ---------------------------------------------------
    if tags.get("boundary") == "protected_area":
        return "Protected area"
    if tags.get("leisure") == "nature_reserve":
        return "Nature reserve"
    if tags.get("natural") == "wood":
        return "Wood / forest"

    return "Unnamed feature"


def risk_color(score: Optional[int]) -> str:
    """Hex colour for a risk score, used in badges and map circles."""
    if score is None:
        return "#9CA3AF"  # gray
    score = max(0, min(100, int(score)))
    if score >= 75:
        return "#DC2626"  # red
    if score >= 50:
        return "#F59E0B"  # amber
    if score >= 25:
        return "#FBBF24"  # yellow
    return "#16A34A"  # green


def risk_label(score: Optional[int]) -> str:
    if score is None:
        return "—"
    score = max(0, min(100, int(score)))
    if score >= 75:
        return "High risk"
    if score >= 50:
        return "Moderate risk"
    if score >= 25:
        return "Low risk"
    return "Minimal risk"


def risk_badge_html(score: Optional[int]) -> str:
    color = risk_color(score)
    label = risk_label(score)
    text = "—" if score is None else str(int(score))
    return (
        f"<span style='display:inline-block; padding:0.15rem 0.6rem; "
        f"border-radius:0.4rem; background:{color}; color:white; "
        f"font-weight:600; font-size:0.85rem;'>"
        f"{text} · {label}</span>"
    )


def render_map(
    lat: float,
    lon: float,
    radius_m: int,
    *,
    key: str,
    score: Optional[int] = None,
    height: int = 480,
    interactive: bool = True,
) -> Optional[Tuple[float, float]]:
    """
    Render an interactive Leaflet map centred on (lat, lon) with a buffer
    circle of ``radius_m`` metres. Returns the new ``(lat, lon)`` if the user
    clicked elsewhere, else ``None``.
    """
    m = folium.Map(location=[lat, lon], zoom_start=12, control_scale=True)
    folium.TileLayer(
        tiles="OpenStreetMap",
        attr="© OpenStreetMap contributors",
        name="OSM",
    ).add_to(m)
    folium.Marker([lat, lon], tooltip="Analysis point").add_to(m)
    folium.Circle(
        location=[lat, lon],
        radius=radius_m,
        color=risk_color(score),
        weight=2,
        fill=True,
        fill_opacity=0.15,
    ).add_to(m)

    result = st_folium(
        m,
        height=height,
        width=None,
        returned_objects=["last_clicked"] if interactive else [],
        key=key,
    )

    if not interactive or not result:
        return None
    clicked = result.get("last_clicked")
    if not clicked:
        return None
    new_lat = clicked.get("lat")
    new_lng = clicked.get("lng")
    if new_lat is None or new_lng is None:
        return None
    if abs(new_lat - lat) < 1e-6 and abs(new_lng - lon) < 1e-6:
        return None
    return float(new_lat), float(new_lng)


def init_location_state(default_lat: float = 38.7223, default_lon: float = -9.1393) -> None:
    """Seed lat/lon in session_state (defaults: Lisbon)."""
    st.session_state.setdefault("lat", default_lat)
    st.session_state.setdefault("lon", default_lon)


def goto_detail(investigation_id: str) -> None:
    st.session_state["selected_investigation_id"] = investigation_id
    st.switch_page("views/detail.py")


def render_findings(findings: Dict[str, Any]) -> None:
    """Render the raw findings dict from an investigation in expandable blocks."""
    with st.expander("Location (Nominatim)", expanded=False):
        nom = findings.get("nominatim") or {}
        if nom.get("ok"):
            st.write(f"**Address:** {nom.get('display_name', '—')}")
            st.write(f"**Country:** {nom.get('country', '—')} ({(nom.get('country_code') or '').upper()})")
            municipality = nom.get("municipality") or "—"
            st.write(f"**Municipality:** {municipality}")
        else:
            st.warning(nom.get("error") or "No data from Nominatim.")

    with st.expander("OpenStreetMap (Overpass)", expanded=True):
        ov = findings.get("overpass") or {}
        if ov.get("ok"):
            grouped = ov.get("grouped") or {}
            if not grouped:
                st.info("No relevant POIs in the selected categories.")
            for cat, items in grouped.items():
                st.markdown(f"**{category_label(cat)}** — {len(items)} POIs")
                rows = []
                for it in items[:25]:
                    tags = it.get("tags") or {}
                    segments = int(it.get("segments") or 1)
                    rows.append(
                        {
                            "type": it.get("type"),
                            "name": overpass_label(tags),
                            "segments": segments,
                            "tags": ", ".join(
                                f"{k}={v}" for k, v in tags.items() if k != "name"
                            )[:200],
                            "lat": it.get("lat"),
                            "lon": it.get("lon"),
                        }
                    )
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.warning(ov.get("error") or "No data from Overpass.")

    with st.expander("Biodiversity (GBIF)", expanded=False):
        gb = findings.get("gbif") or {}
        if gb.get("ok"):
            st.write(f"Species recorded in the area: **{gb.get('species_total', 0)}**")
            threatened = gb.get("threatened") or []
            if threatened:
                st.warning(f"{len(threatened)} species with IUCN VU/EN/CR status.")
                st.dataframe(threatened, use_container_width=True, hide_index=True)
            else:
                st.info("No threatened (IUCN) species recorded.")
        else:
            st.warning(gb.get("error") or "No data from GBIF.")

    with st.expander("Air quality (OpenAQ)", expanded=False):
        oa = findings.get("openaq") or {}
        if oa.get("ok"):
            note = oa.get("note")
            count = oa.get("station_count", 0)
            if note:
                st.info(note)
            elif count == 0:
                st.info("No nearby air-quality stations.")
            else:
                st.write(f"Nearby stations: **{count}**")
                station_rows = []
                for s in oa.get("stations") or []:
                    coords = s.get("coordinates") or {}
                    station_rows.append(
                        {
                            "id": s.get("id"),
                            "name": s.get("name"),
                            "country": s.get("country"),
                            "parameters": ", ".join(s.get("parameters") or []),
                            "lat": coords.get("latitude"),
                            "lon": coords.get("longitude"),
                        }
                    )
                st.dataframe(station_rows, use_container_width=True, hide_index=True)

                measurements = oa.get("measurements") or []
                if measurements:
                    st.markdown("**Latest readings**")
                    st.dataframe(
                        measurements,
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption(
                        "No recent measurements available for these stations."
                    )
        else:
            st.warning(oa.get("error") or "No data from OpenAQ.")

    sat = findings.get("satellite")
    if sat is not None:
        with st.expander("Satellite analysis (AI vision)", expanded=True):
            if sat.get("ok"):
                col_img, col_text = st.columns([1, 1])
                with col_img:
                    img_path = sat.get("image_path")
                    if img_path:
                        # Cache stores just the filename; legacy rows may hold
                        # an absolute path. If the recorded path doesn't exist
                        # (e.g. project folder was renamed), fall back to
                        # IMAGES_DIR / basename.
                        candidate = Path(img_path)
                        if candidate.is_absolute() and candidate.exists():
                            resolved = candidate
                        else:
                            resolved = IMAGES_DIR / candidate.name
                        if resolved.exists():
                            st.image(str(resolved), use_container_width=True)
                        else:
                            st.warning(
                                f"Satellite image not found: `{candidate.name}`"
                            )
                with col_text:
                    danger = sat.get("danger")
                    if danger:
                        st.error("ENVIRONMENTAL DANGER DETECTED (visual analysis)")
                    else:
                        st.success("No significant danger (visual analysis)")
                    st.markdown(f"**Vision model:** `{sat.get('vision_model', '—')}`")
                    st.write(sat.get("vision_description") or "—")
                    st.markdown(f"**Risk model:** `{sat.get('risk_model', '—')}`")
                    st.write(sat.get("risk_response") or "—")
            else:
                st.warning(sat.get("error") or "Satellite analysis failed.")
