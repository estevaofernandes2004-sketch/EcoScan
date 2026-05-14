"""
EcoScan — Streamlit entry point.

Builds the multi-page navigation. Each page lives in ``app/views/`` so it
does not collide with Streamlit's automatic ``pages/`` folder convention.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running with ``streamlit run app/dashboard.py`` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

SIDEBAR_LOGO_PATH = ROOT / "assets" / "screen 5_2.png"
PAGE_ICON_PATH = ROOT / "assets" / "5_3.png"

st.set_page_config(
    page_title="EcoScan",
    page_icon=str(PAGE_ICON_PATH) if PAGE_ICON_PATH.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

if SIDEBAR_LOGO_PATH.exists():
    st.logo(str(SIDEBAR_LOGO_PATH), size="large")
    st.markdown(
        """
        <style>
        [data-testid="stSidebarHeader"] {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
        }
        [data-testid="stLogo"], [data-testid="stSidebarHeader"] img {
            height: 9rem !important;
            max-height: 9rem !important;
            width: auto !important;
            max-width: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

home = st.Page("views/home.py", title="Home", default=True)
manual = st.Page("views/manual.py", title="Manual Investigation")
complaints = st.Page("views/complaints.py", title="Complaints")
history = st.Page("views/history.py", title="History")
detail = st.Page("views/detail.py", title="Investigation Detail")

navigation = st.navigation(
    {
        "EcoScan": [home],
        "Investigate": [manual, complaints],
        "Results": [history, detail],
    }
)

navigation.run()
