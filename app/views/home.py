"""Landing page for EcoScan."""

from __future__ import annotations

import streamlit as st

st.title("EcoScan")
st.markdown("# Assess the environmental risk in seconds.")

st.markdown(
    """
EcoScan turns satellite imagery and open environmental data into a clear
risk score for any location in Portugal — so field teams can focus on the
cases most likely to involve real infractions.

The platform supports two workflows:
"""
)

col1, col2 = st.columns(2)

with col1:
    st.markdown("### Manual Investigation")
    st.markdown(
        """
The inspector picks an area on the map, sets the buffer radius and chooses
the categories of interest (waste, water, air, biodiversity). The system
queries OpenStreetMap, GBIF and OpenAQ — and, optionally, runs a visual
analysis of a satellite image — and returns a structured risk report.
"""
    )
    if st.button("Start manual investigation", use_container_width=True, type="primary"):
        st.switch_page("views/manual.py")

with col2:
    st.markdown("### Complaint-driven Investigation")
    st.markdown(
        """
From the list of received complaints (in this MVP, simulated from an Excel
file), the inspector selects one. The fields auto-fill, the same pipeline
validates the complaint against external evidence, and the report is
attached back to the originating complaint.
"""
    )
    if st.button("View received complaints", use_container_width=True):
        st.switch_page("views/complaints.py")

st.divider()

st.markdown(
    """
**How the engine works**

1. **Parallel cross-referencing of public sources** — Overpass (OSM), GBIF, OpenAQ, Nominatim.
2. **(Optional) Visual analysis** — downloads an image from ESRI World Imagery,
   describes it with `moondream`, classifies visual risk with `llama3.2`.
3. **Final synthesis** — `llama3.2` produces a structured JSON with `risk_score`
   (0–100), summary, risk drivers and concrete recommendations for the inspector.
4. **Persistence** — every investigation is logged and browsable in the
   history page.

Models and prompts are configurable in `models.yaml`. Everything runs
locally: no accounts, no API keys, zero inference cost.
"""
)
