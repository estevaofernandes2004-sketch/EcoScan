"""Manual (map-based) investigation page."""

from __future__ import annotations

import streamlit as st

from app.investigation import run_manual_investigation
from app.sources import search_place
from app.views._helpers import (
    CATEGORY_OPTIONS,
    category_label,
    goto_detail,
    init_location_state,
    render_map,
)

st.title("Manual Investigation")
st.caption(
    "Click on the map to pick a location (or search by name) and configure "
    "the scope of the analysis in the sidebar."
)

init_location_state()

# ---------------------------------------------------------------------------
# Sidebar — investigation parameters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Investigation parameters")

    with st.form("place_search_form", border=False):
        query = st.text_input("Search for a place", placeholder="e.g. Sintra, Estarreja, Sines")
        submitted = st.form_submit_button("Search", use_container_width=True)
    if submitted and query.strip():
        candidates = search_place(query.strip(), limit=5)
        if not candidates:
            st.warning("No results.")
        else:
            best = candidates[0]
            try:
                st.session_state["lat"] = float(best["lat"])
                st.session_state["lon"] = float(best["lon"])
                st.success(f"Centred on: {best.get('display_name', '—')}")
                st.rerun()
            except (KeyError, ValueError, TypeError):
                st.error("Unexpected response from the geocoding service.")

    st.divider()

    # The widgets are NOT keyed to "lat"/"lon": those keys are the canonical
    # location state, written by the search form and the map-click handler.
    # If a widget owned them, neither writer could update them after the
    # widgets were instantiated (StreamlitAPIException).
    lat_input = st.number_input(
        "Latitude",
        min_value=-90.0,
        max_value=90.0,
        value=st.session_state["lat"],
        step=0.0001,
        format="%.5f",
    )
    lon_input = st.number_input(
        "Longitude",
        min_value=-180.0,
        max_value=180.0,
        value=st.session_state["lon"],
        step=0.0001,
        format="%.5f",
    )
    if lat_input != st.session_state["lat"] or lon_input != st.session_state["lon"]:
        st.session_state["lat"] = lat_input
        st.session_state["lon"] = lon_input
        st.rerun()

    radius_m = st.slider(
        "Analysis radius (metres)",
        min_value=200,
        max_value=10_000,
        value=1_500,
        step=100,
    )

    st.markdown("**Categories**")
    selected_categories = []
    for cat in CATEGORY_OPTIONS:
        default = cat in {"waste", "water"}
        if st.checkbox(category_label(cat), value=default, key=f"cat_{cat}"):
            selected_categories.append(cat)

    st.divider()
    title = st.text_input("Investigation title", placeholder="e.g. Suspected discharge in the Trancão river")
    description = st.text_area("Description (optional)", height=100)

    st.divider()
    vision_enabled = st.toggle(
        "Include satellite analysis",
        value=False,
        help=(
            "Downloads an ESRI World Imagery tile and runs the local Ollama "
            "vision and risk models. May take 1–2 minutes."
        ),
    )
    zoom = None
    if vision_enabled:
        zoom = st.slider("Satellite image zoom", min_value=5, max_value=17, value=13)

    run_btn = st.button(
        "Start investigation",
        type="primary",
        use_container_width=True,
        disabled=not selected_categories,
    )
    if not selected_categories:
        st.caption("Select at least one category.")

# ---------------------------------------------------------------------------
# Main — interactive map
# ---------------------------------------------------------------------------

st.markdown(
    f"**Coordinates:** `{st.session_state['lat']:.5f}, {st.session_state['lon']:.5f}` · "
    f"**Radius:** {radius_m} m · **Categories:** "
    f"{', '.join(category_label(c) for c in selected_categories) or '—'}"
)

clicked = render_map(
    lat=st.session_state["lat"],
    lon=st.session_state["lon"],
    radius_m=radius_m,
    key="manual_map",
)
if clicked:
    st.session_state["lat"], st.session_state["lon"] = clicked
    st.rerun()

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------

if run_btn:
    with st.spinner("Running investigation — this may take 1–2 minutes..."):
        try:
            inv_id = run_manual_investigation(
                lat=st.session_state["lat"],
                lon=st.session_state["lon"],
                radius_m=radius_m,
                categories=selected_categories,
                title=title,
                description=description,
                vision_enabled=vision_enabled,
                zoom=zoom,
            )
        except Exception as e:
            st.error(f"Investigation failed: {e}")
            st.stop()
    st.success("Investigation complete.")
    goto_detail(inv_id)
