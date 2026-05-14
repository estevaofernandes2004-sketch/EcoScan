# Project Context — EcoScan

This folder contains the backend + frontend (via Streamlit) for **EcoScan**,
a SaaS proof-of-concept that helps **European environmental inspection
agencies** prioritise where to send field teams.

The project is the Deliverable 2 (Full-Stack Deployable Solution) of the
"Build an AI-Driven Startup" final project. The business plan (Deliverable 1)
is being handled by other group members and is **out of scope** for this
codebase.

---

## What EcoScan does

Inspection agencies have limited resources. EcoScan aggregates public
geospatial data, runs AI analysis on satellite imagery, and produces a risk
report that lets inspectors focus their site visits on the cases most likely
to involve a real infraction.

It supports **two workflows**:

### 1. Manual investigation (Tese — user-initiated)
The inspector clicks a point on an interactive map (or searches for a place,
or types coordinates), sets a buffer radius, and picks the categories of
interest (waste, water, air, biodiversity). The system runs a parallel
investigation across public sources and returns a synthesised risk report.

### 2. Complaint-driven investigation (Antítese — system-initiated)
The system surfaces a list of received complaints (for the MVP, these are
simulated from an Excel file). The inspector picks one from a dropdown; the
location, category, and description auto-fill, and the same investigation
pipeline runs to validate the complaint against external evidence.

---

## Architecture (high-level)

| Layer | Technology |
|---|---|
| Frontend | Streamlit (multi-page) + `streamlit-folium` for the interactive map |
| AI runtime | Ollama running locally (`moondream` for vision, `llama3.2` for risk + synthesis) |
| Public data | Overpass (OSM), GBIF, OpenAQ v3, Nominatim, ESRI World Imagery |
| Persistence | Local files: `database/investigations.csv`, `database/complaints.xlsx`, `database/satellite_cache.csv`, plus PNGs in `images/` |
| Configuration | `models.yaml` (model + prompt settings for vision / risk / synthesis) |

No cloud accounts, no paid API keys, no database server. Everything runs on
the inspector's laptop.

---

## Pipeline (shared between both workflows)

Given `{lat, lon, radius_m, categories, vision_enabled?, zoom?}`:

1. **Fan-out (parallel) public sources:**
   - Nominatim → reverse geocoding + readable address.
   - Overpass → infrastructure points of interest, query varies per category.
     Each category is queried into its own result set so dense categories
     don't starve sparse ones.
   - GBIF → threatened species (IUCN VU/EN/CR) in the bounding box.
   - OpenAQ v3 → nearby air-quality stations **plus the latest pollutant
     reading per sensor** (parallel follow-up calls to `/locations/{id}/latest`).
2. **(Optional) Satellite module** — ESRI WMTS tiles → 3×3 stitched PNG →
   Ollama vision (`moondream`) → Ollama risk classifier (`llama3.2`,
   `DANGER: YES` / `DANGER: NO`). Cached per `(lat, lon, zoom)` in
   `database/satellite_cache.csv` so repeated runs skip both model calls.
3. **Synthesis** — `llama3.2` receives all findings and returns a JSON
   `{risk_score 0-100, summary, drivers[], recommendations[]}` in English.
4. **Persist** the result and surface it on the detail page.

Failures from any single source are logged and skipped, never break the run.

---

## Project layout

```
EcoScan/
├── app/
│   ├── dashboard.py            # Streamlit entry: page registration via st.navigation
│   ├── sources.py              # Nominatim / Overpass / GBIF / OpenAQ clients
│   ├── investigation.py        # Pipeline orchestrator + Ollama synthesis
│   ├── ai_workflow.py          # Satellite download + Ollama vision/risk
│   ├── storage.py              # CSV/Excel persistence + cache + complaint seed
│   └── views/                  # Multi-page UI (declared explicitly, not via pages/)
│       ├── home.py             # Landing page
│       ├── manual.py           # Manual map-based investigation
│       ├── complaints.py       # Complaint-driven investigation
│       ├── history.py          # Past investigations list
│       ├── detail.py           # Investigation detail view
│       └── _helpers.py         # Shared map renderer, badges, label fallbacks
├── assets/                     # Branding (sidebar logo + browser favicon)
├── .streamlit/
│   └── config.toml             # Theme colours (sampled from the EcoScan logo)
├── database/
│   ├── investigations.csv
│   ├── complaints.xlsx
│   └── satellite_cache.csv
├── images/                     # Cached satellite PNGs
├── models.yaml                 # AI configuration (vision / risk / synthesis)
├── requirements.txt
├── SETUP.md                    # Install + run instructions
├── GENAI_TRANSPARENCY_LOG.md   # Required deliverable: how AI was used
└── README.md
```

---

## Out of scope (do not add)

- Authentication / multi-tenancy (single-user demo).
- Real complaint API integrations (the MVP uses an Excel file).
- Cloud storage / cloud DB.
- Paid LLM APIs (everything runs through local Ollama).
