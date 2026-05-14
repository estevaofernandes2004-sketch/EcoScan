# EcoScan — Group H

**EcoScan** is a proof-of-concept SaaS that helps **European environmental
inspection agencies** prioritise where to send their field teams. Inspectors
have limited resources; EcoScan aggregates public geospatial data and runs
local AI models to produce a per-location **risk report**, so site visits
target the cases most likely to involve a real infraction.

This is the Deliverable 2 (Full-Stack Deployable Solution) of the
"Build an AI-Driven Startup" final project.

---

## Group Members

| Name | Student Number | Email |
|---|---|---|
| Afonso Freitas | 56668 | 56668@novasbe.pt |
| Estêvão Fernandes | 70576 | 70576@novasbe.pt |
| Miguel Xu | 56323 | 56323@novasbe.pt |

**Outlook quick-copy:**
`56668@novasbe.pt; 70576@novasbe.pt; 56323@novasbe.pt`

---

## Two workflows

### 1. Manual investigation (user-initiated)
Inspector clicks a point on an interactive map, sets a buffer radius, and
picks the categories of interest (waste, water, air, biodiversity). EcoScan
queries Overpass (OSM), GBIF, OpenAQ, and Nominatim in parallel, optionally
runs a satellite-image AI analysis, and synthesises the findings into a risk
report (score 0–100 + summary + drivers + recommendations).

### 2. Complaint-driven investigation (system-initiated)
Inspector picks a complaint from a dropdown (simulated from
`database/complaints.xlsx` for the MVP). The location, category, and
description auto-fill, the same investigation pipeline runs, and the report
validates the complaint against external evidence.

---

## Quick start

EcoScan runs locally on your laptop using Python and Ollama — no cloud,
no paid API keys. See [`SETUP.md`](SETUP.md) for the full step-by-step
install guide (prerequisites, virtual env, dependencies, Ollama models,
optional OpenAQ key).

Once installed, run:

```bash
streamlit run app/dashboard.py
```

---

## How AI was used

This project uses generative AI as both a **build-time** assistant
(Claude Code helped design and implement the codebase) and a **runtime**
component (Ollama runs local vision + reasoning models inside the app).
Every step is documented in [`GENAI_TRANSPARENCY_LOG.md`](GENAI_TRANSPARENCY_LOG.md).

---

## Repository layout

```
EcoScan/
├── app/                        # Python source: orchestrator, data clients, Streamlit pages
├── assets/                     # Branding (sidebar logo + browser favicon)
├── database/                   # Local persistence: investigations, complaints, satellite cache
├── images/                     # Cached satellite tile PNGs
├── .streamlit/                 # Streamlit theme
├── models.yaml                 # AI model + prompt configuration
├── requirements.txt            # Python dependencies
├── SETUP.md                    # Install + run guide
├── GENAI_TRANSPARENCY_LOG.md   # How AI was used to build the project
├── CLAUDE.md                   # Architecture brief + file-by-file map
└── README.md                   # You are here
```

See [`CLAUDE.md`](CLAUDE.md) for the per-file annotations inside `app/`.
