"""Investigation detail page."""

from __future__ import annotations

import streamlit as st

from app import storage
from app.views._helpers import (
    categories_label,
    render_findings,
    render_map,
    risk_color,
    risk_label,
)

st.title("Investigation Detail")

investigation_id = st.session_state.get("selected_investigation_id")
if not investigation_id:
    st.info(
        "No investigation selected. Open one from **History** or run a new one."
    )
    if st.button("Go to history"):
        st.switch_page("views/history.py")
    st.stop()

record = storage.get_investigation(str(investigation_id))
if record is None:
    st.error(f"Investigation {investigation_id} not found.")
    st.stop()

result = record.get("result") or {}
synthesis = result.get("synthesis") or {}
findings = result.get("findings") or {}

score = synthesis.get("risk_score")
try:
    score_int = int(score) if score is not None else None
except (TypeError, ValueError):
    score_int = None

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

col_header_left, col_header_right = st.columns([3, 1])
with col_header_left:
    st.subheader(record.get("title") or "(untitled)")
    st.caption(
        f"ID: `{record['id']}` · {record.get('timestamp', '—')} · "
        f"Source: {'Complaint' if record.get('source') == 'complaint' else 'Manual'}"
    )
    if record.get("complaint_id"):
        st.caption(f"Linked complaint: `{record['complaint_id']}`")
    if record.get("description"):
        st.write(record["description"])

with col_header_right:
    color = risk_color(score_int)
    st.markdown(
        f"<div style='text-align:center; padding:1rem; border-radius:0.75rem; "
        f"background:{color}; color:white;'>"
        f"<div style='font-size:2.6rem; font-weight:700;'>"
        f"{'—' if score_int is None else score_int}</div>"
        f"<div>{risk_label(score_int)}</div></div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

st.markdown("### Summary")
summary = synthesis.get("summary")
if summary:
    st.write(summary)
else:
    st.info("No summary available.")

drivers = synthesis.get("drivers") or []
recs = synthesis.get("recommendations") or []
col_drivers, col_recs = st.columns(2)
with col_drivers:
    st.markdown("**Risk drivers**")
    if drivers:
        for d in drivers:
            st.markdown(f"- {d}")
    else:
        st.caption("—")
with col_recs:
    st.markdown("**Recommendations**")
    if recs:
        for r in recs:
            st.markdown(f"- {r}")
    else:
        st.caption("—")

# ---------------------------------------------------------------------------
# Map + parameters
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("### Location and parameters")

col_map, col_params = st.columns([2, 1])
with col_map:
    try:
        lat = float(record["latitude"])
        lon = float(record["longitude"])
        radius_m = int(record.get("radius_m") or 1000)
        render_map(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            key=f"detail_map_{record['id']}",
            score=score_int,
            interactive=False,
        )
    except (TypeError, ValueError):
        st.caption("No valid coordinates.")

with col_params:
    st.markdown(
        f"**Coordinates:** `{record.get('latitude')}, {record.get('longitude')}`"
    )
    st.markdown(f"**Radius:** {record.get('radius_m')} m")
    st.markdown(f"**Categories:** {categories_label(record.get('categories') or [])}")
    st.markdown(
        f"**Satellite analysis:** {'yes' if record.get('vision_enabled') else 'no'}"
    )
    if record.get("vision_enabled") and record.get("zoom"):
        st.markdown(f"**Zoom:** {record['zoom']}")

# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("### Evidence")
render_findings(findings)
