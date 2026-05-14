"""Investigation history page."""

from __future__ import annotations

import streamlit as st

from app import storage
from app.views._helpers import (
    categories_label,
    goto_detail,
    risk_color,
    risk_label,
)

st.title("History")
st.caption("All past investigations, newest first.")

df = storage.load_investigations()

if df.empty:
    st.info("No investigations recorded yet. Start one from Manual Investigation or Complaints.")
    st.stop()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

col_f1, col_f2 = st.columns([1, 2])
with col_f1:
    source_filter = st.selectbox(
        "Source",
        options=["All", "Manual", "Complaint"],
        index=0,
    )

source_map = {"Manual": "manual", "Complaint": "complaint"}
if source_filter in source_map:
    df = df[df["source"] == source_map[source_filter]]

if df.empty:
    st.info("No results for the selected filter.")
    st.stop()

# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

for _, row in df.iterrows():
    inv_id = str(row["id"])
    title = str(row.get("title") or "(untitled)")
    timestamp = str(row.get("timestamp", ""))
    source = "Complaint" if row.get("source") == "complaint" else "Manual"
    score_raw = row.get("risk_score")
    try:
        score: int | None = int(score_raw)
    except (TypeError, ValueError):
        score = None
    cats = str(row.get("categories") or "")
    cats_list = [c for c in cats.split(";") if c]

    color = risk_color(score)
    label = risk_label(score)
    score_text = "—" if score is None else str(score)

    with st.container(border=True):
        col_score, col_meta, col_action = st.columns([1, 4, 1])
        with col_score:
            st.markdown(
                f"<div style='text-align:center; padding:0.5rem; border-radius:0.5rem; "
                f"background:{color}; color:white;'>"
                f"<div style='font-size:1.6rem; font-weight:700;'>{score_text}</div>"
                f"<div style='font-size:0.75rem;'>{label}</div></div>",
                unsafe_allow_html=True,
            )
        with col_meta:
            st.markdown(f"**{title}**")
            st.caption(
                f"{timestamp} · {source}"
                + (f" · {row.get('complaint_id')}" if source == "Complaint" else "")
            )
            st.caption(
                f"Coordinates: {row.get('latitude'):.4f}, {row.get('longitude'):.4f} · "
                f"Radius: {row.get('radius_m')} m · "
                f"Categories: {categories_label(cats_list)}"
            )
        with col_action:
            if st.button("Open", key=f"open_{inv_id}", use_container_width=True):
                goto_detail(inv_id)
