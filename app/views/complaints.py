"""Complaint-driven investigation page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import storage
from app.investigation import run_complaint_investigation
from app.views._helpers import (
    category_label,
    goto_detail,
    render_map,
)

st.title("Complaint-driven Investigation")
st.caption(
    "Pick a received complaint. Location and category are auto-filled from "
    "the record."
)

complaints_df: pd.DataFrame = storage.load_complaints()

if complaints_df.empty:
    st.info(
        "No complaints registered. Edit `database/complaints.xlsx` or delete "
        "the file to regenerate the simulated data."
    )
    st.stop()

# Build dropdown options. Most recent first.
complaints_df = complaints_df.sort_values("timestamp_received", ascending=False)
options = {
    f"{row['id']} · {row.get('location_text', '—')} · {category_label(str(row['category']))}": row["id"]
    for _, row in complaints_df.iterrows()
}

label = st.selectbox(
    "Complaint",
    options=list(options.keys()),
    index=0,
)
complaint_id = options[label]
complaint = storage.get_complaint(complaint_id)
assert complaint is not None  # selectbox guarantees this

# ---------------------------------------------------------------------------
# Complaint detail card
# ---------------------------------------------------------------------------

col_meta, col_body = st.columns([1, 2])

with col_meta:
    st.markdown(f"**ID:** `{complaint['id']}`")
    st.markdown(f"**Received:** {complaint.get('timestamp_received', '—')}")
    st.markdown(f"**Channel:** {complaint.get('channel', '—')}")
    st.markdown(f"**Reported by:** {complaint.get('reporter_name', '—')}")
    st.markdown(f"**Category:** {category_label(str(complaint['category']))}")
    status = str(complaint.get("status", "—"))
    if status == "Pending":
        st.warning(f"Status: {status}")
    elif status == "Under investigation":
        st.info(f"Status: {status}")
    else:
        st.success(f"Status: {status}")

with col_body:
    st.markdown(f"**Location:** {complaint.get('location_text', '—')}")
    st.markdown("**Complaint description:**")
    st.write(complaint.get("description", ""))

# ---------------------------------------------------------------------------
# Map preview + investigation parameters
# ---------------------------------------------------------------------------

lat = float(complaint["latitude"])
lon = float(complaint["longitude"])

st.divider()
st.subheader("Configure investigation")

col_left, col_right = st.columns([2, 1])

with col_right:
    radius_m = st.slider(
        "Analysis radius (metres)",
        min_value=200,
        max_value=10_000,
        value=1_500,
        step=100,
    )
    vision_enabled = st.toggle(
        "Include satellite analysis",
        value=False,
        help="May take 1–2 minutes.",
    )
    zoom = None
    if vision_enabled:
        zoom = st.slider("Image zoom", min_value=5, max_value=17, value=14)
    run_btn = st.button(
        "Validate complaint",
        type="primary",
        use_container_width=True,
    )

with col_left:
    render_map(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        key=f"complaint_map_{complaint_id}",
        interactive=False,
    )

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------

if run_btn:
    with st.spinner("Running investigation — this may take 1–2 minutes..."):
        try:
            inv_id = run_complaint_investigation(
                complaint_id=complaint_id,
                radius_m=radius_m,
                vision_enabled=vision_enabled,
                zoom=zoom,
            )
        except Exception as e:
            st.error(f"Investigation failed: {e}")
            st.stop()
    st.success("Investigation complete.")
    goto_detail(inv_id)
