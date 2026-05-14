# GenAI Transparency Log — EcoScan

This document records exactly how generative AI tools were used during the
ideation, design, and implementation of EcoScan, in chronological order.

---

## 0. Tools used

| Tool | Role | Where it was used |
|---|---|---|
| **Lovable** (web) | Prompt synthesizer | Generated the initial spec/prompt that was then handed to Claude Code. |
| **Claude Code** (Claude Opus 4.7, 1M context) | Pair-programmer | Repository cleanup, planning, full implementation of the EcoScan app. |
| **Ollama — `moondream`** | Vision model (runtime) | Ships with the app: describes downloaded satellite images. |
| **Ollama — `llama3.2`** | Reasoning model (runtime) | Ships with the app: assesses environmental risk and synthesises the final report. |

**On model selection.** `moondream` (≈1.7 B parameters, vision) and
`llama3.2` (≈3 B parameters, text) were chosen because they are small
enough to run on a consumer laptop without a dedicated GPU. Larger or
more capable models (e.g. `llava`, larger Llama variants) would likely
produce richer outputs, but the design constraint *"runs on the
inspector's laptop"* made hardware footprint a first-order requirement.
Quality is recovered through prompt engineering (§3) rather than model
scale.

**Human contributions.** The user was the project's decision-maker and
reviewer throughout. Concretely: choosing the overall scope and stack
(rejecting the Lovable-generated React/Supabase spec in favour of
Python + Streamlit + local Ollama, §1.1); selecting which architectural
option to follow when Claude proposed alternatives (e.g. OpenAQ Fix B
over Fix A in §2.11; keeping all recycling POIs instead of filtering
them in §2.13); catching wording bugs in shipped documentation (the
ambiguous "free API key" phrasing in §2.10); identifying every bug
surfaced in §2.8–§2.14 through hands-on testing and screenshots;
curating the demo data and deciding which test investigations to ship;
choosing the final demo language and audience framing. Claude Code did
the typing; the design and judgement decisions documented above are the
user's.

---

## 1. Ideation

### 1.1 Concept refinement (Lovable, then Claude Code)

The user described the high-level idea verbally and asked Lovable to generate
a structured build prompt. The prompt that came back targeted a TanStack Start
(React + TypeScript) full-stack app with Supabase, the Lovable AI gateway, and
optional Ollama integration.

**Decision logged:** the prompt was rejected as overengineered for the
deliverable. The school's own slide explicitly lists Streamlit as an accepted
platform for the user-facing demo. Claude Code proposed (and the user accepted)
a simplified path:

- Build the app on Python + Streamlit.
- Drop Supabase / Google OAuth / cloud LLM gateway.
- Use Ollama locally for **all** AI calls (vision, risk, synthesis).
- Persist data in local files (CSV / Excel) — no cloud DB.

**Rationale:** zero accounts, zero API keys, zero cost; matches the user's
existing skills and their stated preference for Streamlit; satisfies the
"Full-Stack Deployable Solution" deliverable because the slide explicitly
permits Streamlit.

### 1.2 Two-workflow architecture

After the user shared the project's "deconstrução da visão do produto" notes,
the scope was expanded to model the two use cases described there:

- **Tese — manual investigation via map** (inspector picks the area).
- **Antítese — investigation triggered by a complaint** (system surfaces a
  list of complaints; inspector picks one and the platform validates it).

For the MVP, complaints are simulated from an Excel file (per the user's spec)
rather than fetched from a real API.

---

## 2. Implementation

Each entry below documents one build step: what was generated, what the AI
was prompted to produce, and any human review/edits applied.

### 2.1 Documentation scaffolding

- **What:** Wrote `CLAUDE.md` to give future Claude Code sessions a concise
  description of EcoScan, the two workflows, the architecture layers, and
  the explicit out-of-scope list. Wrote `README.md` as the public pitch
  (group members, two-workflow summary, quick-start TL;DR). Wrote
  `SETUP.md` with install + run instructions.
- **Prompt summary (Claude Code):** "Write the project documentation to
  reflect EcoScan: SaaS for European environmental inspection agencies,
  two workflows (manual investigation via map and complaint-driven),
  Streamlit + Ollama stack, public data sources (Overpass / GBIF / OpenAQ
  / Nominatim / ESRI World Imagery)."
- **Human review:** the group member list and contact emails were
  supplied by the user verbatim. All prose was reviewed by the user
  before being committed.

### 2.2 Persistence layer + simulated complaints (`app/storage.py`)

- **What was generated:** A self-contained module that owns three local
  files: `database/complaints.xlsx`, `database/investigations.csv`, and
  `database/satellite_cache.csv`. The complaints file is auto-seeded the
  first time the app loads it.
- **Prompt to Claude Code (paraphrased):** "Write `app/storage.py` with
  `load_complaints / get_complaint / mark_complaint_status`,
  `save_investigation / load_investigations / get_investigation`, and
  `check_satellite_cache / save_satellite_cache`. Auto-seed
  `database/complaints.xlsx` from a hardcoded list of ~20 realistic Portuguese
  environmental complaints across mainland Portugal — varied locations,
  channels, categories, descriptions in PT-PT."
- **AI-generated content fully reviewed:** the 20 simulated complaints were
  produced by Claude Code based on the user's spec. They are fictional but
  use real coordinates of plausible inspection sites (Setúbal industrial
  zone, Aveiro lagoon, Sines port, Estarreja chemical complex, Panasqueiras
  mine, etc.). The user is encouraged to edit `database/complaints.xlsx`
  before any demo to make sure the descriptions match the agency context
  they want to showcase.

### 2.3 Public-data clients (`app/sources.py`)

- **What was generated:** Resilient clients for Nominatim (reverse geocoding
  + place search), Overpass (OSM POIs by category), GBIF (biodiversity
  occurrences with IUCN flags), and OpenAQ v3 (air-quality stations).
- **Design decisions reviewed by the user:** the four EcoScan categories
  (`waste`, `water`, `air`, `biodiversity`) each map to a curated list of
  Overpass tag selectors. Network errors are caught and returned as
  structured `{"ok": False, "error": ...}` dicts so a single failed source
  never aborts the whole investigation.
- **Compliance note:** Nominatim usage policy requires a User-Agent header
  identifying the application — set to `EcoScan/0.1 (academic project;
  contact: 70576@novasbe.pt)`.

### 2.4 Investigation orchestrator + LLM synthesis (`app/investigation.py`)

- **What was generated:** A pipeline that fans out to all four public
  sources in parallel (using `concurrent.futures.ThreadPoolExecutor`),
  optionally runs the satellite-vision branch, summarises each block of
  findings into a compact text summary, and feeds them to a single prompt
  that asks `llama3.2` for a JSON object with
  `risk_score / summary / drivers / recommendations`.
- **Prompt engineering:** the synthesis prompt is in `models.yaml` under
  `synthesis.prompt` and can be edited without touching code. It is in
  English (an early PT-PT draft was switched to English to make the demo
  legible for international audiences), instructs the model to be
  conservative on weak evidence, and forbids markdown/extra text in the
  output. The Python parser strips optional ```json fences and falls
  back to a "synthesis failed" structure if the JSON is malformed.
- **`format="json"`** is passed to `ollama.chat`, which forces the model
  to emit valid JSON when supported.

### 2.5 Streamlit multi-page UI (`app/dashboard.py` + `app/views/`)

- **What was generated:**
  - `app/dashboard.py` — entry point. Uses `st.navigation` (Streamlit ≥ 1.36)
    with three groups: *EcoScan*, *Investigate*, *Results*.
  - `app/views/home.py` — landing page with two CTAs.
  - `app/views/manual.py` — interactive map (`streamlit-folium`),
    place-name search via Nominatim, lat/lon inputs, radius slider,
    category checkboxes, optional satellite toggle + zoom slider.
  - `app/views/complaints.py` — dropdown of complaints with auto-fill,
    read-only map preview, same investigation parameters.
  - `app/views/history.py` — paginated card list with colour-coded risk
    badges, filterable by source.
  - `app/views/detail.py` — score panel, synthesis text, drivers + recs,
    map preview, expandable evidence sections per source.
  - `app/views/_helpers.py` — shared map renderer, category labels, badge
    helpers, `goto_detail` navigation helper.
- **Design choices the user asked Claude Code to apply:** keep the existing
  satellite-image AI flow (`ai_workflow.py`) intact; integrate it as **one
  of several evidence sources** rather than the main feature.

### 2.6 Configuration (`models.yaml`)

- **What was generated:** Added a top-level `synthesis` block to
  `models.yaml` (model + prompt + temperature). Every AI behaviour in
  the app is now governed by this single file.

### 2.7 Smoke test

- **What was run:** `python -c "import app.storage, app.sources, app.investigation, app.ai_workflow, app.views._helpers"` from the project
  root, plus a one-shot call to `storage.load_complaints()` to verify the
  Excel seed file is created correctly. All imports succeeded; 20 complaints
  loaded; investigation DataFrame is empty (expected on first run).

### 2.8 End-to-end runtime test + fixes

The user ran the manual workflow against Sintra (lat 38.8355, lon -9.3522,
1500 m radius, Waste + Water categories, satellite analysis off). Pipeline
worked end-to-end and produced a sensible report (score 40 / "Low risk",
1 waste POI + 116 water POIs from Overpass, 92 GBIF species with no IUCN
flags, AI-generated summary referencing all sources). The user shared
screenshots back to Claude Code, which surfaced three issues to fix:

1. **Streamlit widget state bug** — when a user searched for a place via
   Nominatim, the latitude/longitude inputs in the sidebar didn't update.
   Cause: the `st.number_input` widget had both a `value=` and a separate
   `key=` parameter, so Streamlit ignored writes to `st.session_state["lat"]`
   after the first render. Fix: bind the widget directly to `key="lat"`
   (and `"lon"`) so updates from search/map-click propagate cleanly.
2. **`Linked complaint: nan` cosmetic bug** — pandas reads empty CSV cells
   as NaN; the detail page's truthiness check on `complaint_id` was
   passing because `bool(float('nan'))` is `True`. Fix: in
   `storage.get_investigation`, coerce missing string fields
   (`title`, `description`, `complaint_id`) back to empty string.
3. **OpenAQ 401 Unauthorized** — OpenAQ v3 now requires a free API key,
   which broke the "zero API keys" promise of the demo. Fix: make OpenAQ
   optional. If `OPENAQ_API_KEY` is set, the source runs as before; if
   not, it returns an empty result with a friendly note, and the rest of
   the investigation continues unaffected. SETUP.md was updated to
   document the env var.

All fixes were proposed and applied by Claude Code based on the screenshots
the user shared; the user reviewed the diffs before re-running the app.

### 2.9 Branding polish — sidebar logo + browser tab icon

- **What:** Replaced the old `ecoscan-icon-1024.png` reference (the file no
  longer existed on disk) with two new branded assets: `assets/screen 5_2.png`
  bound to `st.logo()` for the sidebar, and `assets/5_3.png` bound to
  `page_icon` for the browser tab favicon.
- **Debug iteration:** After the first deploy the user reported via
  screenshot that the sidebar logo was barely visible at the maximum
  built-in size (`size="large"`). Claude Code applied a CSS override
  scoped to `[data-testid="stLogo"]` and `[data-testid="stSidebarHeader"] img`
  setting the logo height to 9 rem (~144 px) with `!important`, plus a
  little vertical padding on the sidebar header so the logo had room to
  grow. User confirmed visually.
- **Files touched:** `app/dashboard.py`.

### 2.10 Documentation refinement for the GitHub push

- **What:** Reviewed `README.md` and `SETUP.md` together with the user and
  decided to keep them as two separate files (README = pitch, SETUP =
  manual). The reasoning: merging would bury the elevator pitch under
  shell commands and is non-standard for open-source repos.
- **OpenAQ section in SETUP.md** was expanded so any user (including
  professors testing the project at home) can enable air-quality data on
  their own machine without ever needing the author's key:
  - Pointed to the correct registration URL
    (`https://explore.openaq.org/register`) instead of the docs landing
    page that was previously linked.
  - Added a persistent-env-var setup walkthrough for Windows ("Edit
    environment variables for your account") and a matching `export` +
    shell-rc note for macOS / Linux.
  - Added a security note: treat the key like a password, never commit it.
- **Wording correction (caught by the user):** the original phrasing
  "OpenAQ is the only data source that requires a (free) API key" was
  ambiguous — it implied the other sources might not be free APIs.
  Rewrote to make explicit that **all sources are free**, and the
  distinction is only that OpenAQ requires registration for per-user
  rate-limiting (vs the anonymous Nominatim / Overpass / GBIF).

### 2.11 OpenAQ v3 enhancement — real measurements feeding the LLM

- **Problem reported by the user (with screenshot):** an investigation in
  Lisbon returned the OpenAQ panel populated with two stations
  ("Entrecampos" and "Morais Soares, Lisbon") but the `parameters`
  column was empty for both, and there was **no numeric pollutant
  reading anywhere on the detail page**.
- **Two distinct issues diagnosed:**
  1. **Schema mismatch.** `query_openaq` in `app/sources.py` read
     `loc["parameters"]`, which is a v2-era field name. OpenAQ v3 moved
     parameter info under `loc["sensors"][].parameter.{name,units}`. The
     old parser silently produced empty lists for every station.
  2. **No measurements endpoint was being called.** `/v3/locations`
     returns station metadata only, never the actual pollutant values.
     So even fixing the schema bug would only have produced labels like
     "no2, pm25" without numbers behind them — and the synthesis LLM was
     getting no quantitative air-quality evidence at all.
- **Resolution (Fix B, chosen by the user over a label-only Fix A):**
  - Endpoint validated up-front by fetching the OpenAQ OpenAPI spec at
    `https://api.openaq.org/openapi.json` (via Claude Code's WebFetch
    tool) before writing any code, confirming the exact field names
    `coordinates.latitude/longitude`, `country.name`,
    `sensors[].id/parameter.{name,units}`, and on
    `/v3/locations/{id}/latest` → `results[].{sensorsId, value, datetime.utc}`.
  - `app/sources.py` now parses the v3 schema correctly and, after the
    locations request, fans out one `/v3/locations/{id}/latest` call per
    station in parallel (`concurrent.futures.ThreadPoolExecutor`, max 8
    workers). A `sensor_id → {parameter, unit, station_name}` lookup is
    built from the locations response so each latest reading can be
    enriched with its parameter name, unit, and station of origin. All
    follow-up calls are best-effort: any single failure is silently
    skipped and the station still appears in the result.
  - `_summarise_openaq` in `app/investigation.py` was extended to format
    measurements per station for the synthesis prompt — e.g.
    `• Entrecampos: no2=23.4 µg/m³, pm25=11.2 µg/m³` — so `llama3.2`
    now reasons over real pollutant numbers when computing `risk_score`.
  - The Air quality panel in `app/views/_helpers.py` now renders a
    cleaner stations table (with `lat`/`lon` columns broken out from
    the nested `coordinates` object) and a new "Latest readings" table
    below it.

### 2.12 Overpass starvation bug — per-category result sets

- **Problem reported by the user (with screenshot):** an investigation in
  Lisbon with all four categories enabled returned waste and air results
  from the Overpass panel but **no water and no biodiversity results**,
  even though Lisbon obviously contains both (the Tagus river,
  Monsanto Forest Park, etc.).
- **Root cause diagnosed in `app/sources.py`:** the previous query unioned
  every selector from every selected category into a single Overpass
  request capped with one global `out center tags 200;` statement. In a
  dense urban bbox, the early-iterated categories (waste, air) easily
  saturated the 200-element budget on their own, so the server never
  emitted any water or biodiversity features. The selectors themselves
  were correct — the data exists in OSM — the query simply wasn't asking
  the server to send it back.
- **Fix:** rewrite `_build_overpass_query` to assign every category to
  its own named Overpass set (`-> .waste`, `-> .water`, `-> .air`,
  `-> .biodiversity`) and call `out center tags 150;` once per set. Each
  category is now guaranteed its own per-category quota independent of
  the others. Maximum response size grows from 200 → at most 600
  elements when all four categories are selected — still well within
  Overpass's server-side `timeout:25` budget and a trivial payload
  client-side.

### 2.13 Overpass POI labels — synthesised fallback names

- **Problem reported by the user (with screenshot):** after the fix in
  §2.12 made the Overpass response fairly populate every category, the
  Waste category for Lisbon returned 99 POIs but ~80% of them showed an
  empty `name` column. Most were unnamed recycling nodes (Ecopontos,
  street glass bins, bottle banks) where OSM contributors simply hadn't
  filled in the `name` tag.
- **User's design preference:** keep the recycling POIs (they are
  meaningful signal that the area has recycling infrastructure) but
  populate the `name` column with something readable instead of leaving
  it blank.
- **Resolution:** added `overpass_label(tags)` to `app/views/_helpers.py`.
  It prefers the real `name`, then falls back to `alt_name` (splitting
  on `;` since OSM sometimes encodes Portuguese / English variants like
  `Ecoponto;Ponto de Reciclagem`), and finally synthesises a label from
  the most informative tag — e.g. `recycling_type=container` becomes
  "Recycling container", `recycling:glass=yes / recycling:cans=yes`
  becomes "Recycling point (cans, glass)", `landuse=industrial` becomes
  "Industrial area", `boundary=protected_area` becomes "Protected area".
  The original OSM tags are **not** modified — only the rendered label
  changes, so the LLM still sees the raw evidence and downstream cache /
  CSV records are untouched.
- **Why not filter the recycling POIs out instead:** an earlier option
  was to filter `amenity=recycling` to keep only `recycling_type=centre`
  (real recycling facilities), since street bins are environmental
  infrastructure rather than risk signals. The user chose to keep them
  because their presence still tells the inspector something useful
  about the area; the readability problem could be solved without
  pruning evidence.

### 2.14 Localisation of seed complaints to English

- **Why:** the demo will be shown to a non-Portuguese-speaking audience.
  The 20 simulated complaints in `app/storage.py::_SEED_COMPLAINTS` were
  originally written in Portuguese (descriptions + location labels) so
  the complaint-driven workflow felt realistic for a domestic agency
  context. For the international presentation, every `description` and
  every `location_text` field was translated to English, while keeping
  Portuguese toponyms intact where they are proper nouns (e.g. *Ria de
  Aveiro* → *Aveiro lagoon*; *Mina das Panasqueiras* → *Panasqueiras
  mine*; *Sintra*, *Sines*, *Cascais*, etc. left as-is).
- **Reporter names** (Maria Silva, João Pereira, …) were kept in
  Portuguese — they are identifiers, not content — to preserve the
  *"Portuguese agency"* framing on the Complaints page.
- **Cache invalidation:** `_seed_complaints_file()` only writes
  `database/complaints.xlsx` when the file is missing. To make the new
  English seed take effect, the existing (Portuguese-seeded) Excel file
  was deleted; the next call to `load_complaints()` regenerates it from
  the updated seed list. Any in-progress status updates on previously
  used complaints are lost — acceptable for the demo since complaints
  are simulated.

### 2.15 Debugging methodology used in this session

The fixes in 2.11 and 2.12 followed a consistent loop that the user
explicitly asked to record for transparency:

1. **User runs the app and shares a screenshot** of the unexpected
   output (empty parameters column, missing categories).
2. **Claude Code reads the relevant source files** (`app/sources.py`,
   `app/investigation.py`, `app/views/_helpers.py`) instead of guessing
   from the screenshot alone.
3. **Claude Code states a hypothesis** about the root cause in plain
   language (schema drift; global quota saturation) **before** writing
   any code, so the user can challenge it.
4. **Where an external API contract is involved**, Claude Code verifies
   it against the authoritative source (the OpenAPI spec for OpenAQ; the
   Overpass-QL semantics for the set-based query) **before** editing.
5. **The fix is applied with `Edit`**, scoped to the minimum surface
   area needed, and the user is given concrete reproduction steps to
   confirm it worked.

No fix in this session was applied without the user explicitly approving
it after reading the diagnosis.

---

## 3. Prompt engineering

Every AI behaviour in EcoScan is driven by three prompts living in
[`models.yaml`](models.yaml). They were deliberately designed for three
different jobs, with different output guarantees, output formats, and
decoding settings. This section walks through each as a design artefact:
what choice was made, and why.

### 3.1 Vision prompt — `moondream`

The full prompt is in `models.yaml` under `image_model.prompt`:

```
Describe this satellite image in detail. Focus on: land cover type
(forest, urban, agricultural, water, desert, etc.), vegetation density
and health, signs of human activity or development, visible environmental
changes such as deforestation, erosion, or pollution, and any other
notable features visible from above.
```

- **Role:** translate satellite pixels into a textual description so a
  text-only LLM (the risk classifier) can reason about the image.
- **Open-ended on purpose.** No yes/no questions, no schema. The
  downstream model decides what's risk-relevant; the vision model's job
  is to faithfully describe what it sees.
- **Anchor list of categories** (land cover / vegetation / human
  activity / environmental change) prevents `moondream` from drifting
  into unrelated observations such as aesthetics, weather, or sky colour.
- **Temperature 0.5** — middle ground. Vision is naturally interpretive;
  zero randomness would force the model to commit to one phrasing where
  it might legitimately be uncertain.
- **No output-format constraints** because this prompt's output is text
  consumed by another LLM, not by Python.

### 3.2 Risk classifier prompt — `llama3.2`

Lives in `models.yaml` under `text_model.prompt`:

```
You are an environmental risk assessment expert. You have received the
following description of a satellite image: "{description}"

Based on this description, answer each of the following questions briefly:
1. Is there evidence of deforestation or significant loss of vegetation?
2. Are there signs of urban sprawl or infrastructure encroachment on natural areas?
3. Is there visible pollution, industrial activity, or waste dumping?
4. Are there signs of soil erosion, land degradation, or desertification?
5. Are there signs of water stress, flooding, or reduced water bodies?

After answering the questions, provide a short overall risk summary.
Your final line must be exactly one of the following two options:
DANGER: YES
DANGER: NO
```

- **Persona** ("environmental risk assessment expert") sets vocabulary
  and tone.
- **Five fixed structured questions** force a consistent reasoning
  pattern. Every run answers the same five axes, so the model can't
  choose which risks to consider — that decision is moved into the
  prompt design.
- **Forced final line `DANGER: YES` / `DANGER: NO`** — the single most
  load-bearing prompt choice in this branch. It lets the Python code
  detect the verdict with a trivial `"DANGER: YES" in text.upper()`
  check instead of natural-language parsing. The literal acts as a
  contract between the LLM and the rest of the system.
- **`{description}` placeholder** is replaced at runtime in
  `app/ai_workflow.py::assess_danger` with the vision model's output —
  the two prompts are chained.
- **Temperature 0.2 + `max_tokens: 500`.** Low randomness so the same
  vision description doesn't flip between YES and NO across runs.

### 3.3 Synthesis prompt — `llama3.2`

The most engineered of the three. Lives in `models.yaml` under
`synthesis.prompt`:

```
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
Return EXCLUSIVELY a valid JSON object (no extra text, no markdown) with
the following structure, in English:

{
  "risk_score": <integer 0-100, where 100 is the highest risk>,
  "summary": "<2-4 sentences explaining your assessment>",
  "drivers": ["<risk driver 1>", "<risk driver 2>", ...],
  "recommendations": ["<concrete action 1>", "<concrete action 2>", ...]
}

Be conservative: if the evidence is weak or contradictory, lower the
score and justify. Focus the recommendations on actionable next steps
for an inspection team (site visit, sample collection, contact with the
local authority, etc.).
```

- **Persona + agency context** primes the model to reason in inspector
  vocabulary, not generic prose.
- **Labelled sections** (`INVESTIGATION CONTEXT` / `EVIDENCE COLLECTED`
  / `TASK`) prevent the model from confusing inputs with instructions.
  Without these labels, the model can hallucinate that the inspector's
  notes are part of the task.
- **Templated placeholders** (`{title}`, `{lat}`, `{findings}`, etc.)
  are filled at runtime by `_build_synthesis_prompt` in
  `app/investigation.py`. The `{findings}` block is itself a
  pre-formatted summary produced by helpers like `_summarise_overpass`
  and `_summarise_openaq` — so the synthesis model sees a compact
  reduction of all evidence, not raw API JSON.
- **Exact JSON schema specified inline.** The model is told precisely
  which fields to return, with type hints (`<integer 0-100, ...>`).
  This is enforced both at the prompt level AND at the API level (see
  §3.4 below).
- **`Be conservative` bias instruction.** Without it, LLMs tend to
  inflate risk scores when given many bullet points of evidence even
  when those bullets are non-confirmatory. Anchoring the model toward
  caution counteracts this and aligns the model's behaviour with what
  an inspection agency actually wants (false positives are expensive).
- **Language constraint (`in English`)** added partway through the
  project when the demo audience became international (see §3.5).
- **Temperature 0.2 + `num_predict: 800`.** Low randomness so risk
  scores are stable across runs on identical evidence; predict budget
  large enough for a multi-paragraph summary plus several drivers and
  recommendations without truncation.

### 3.4 Belt-and-suspenders enforcement

Prompt engineering alone is never 100% reliable with open-weight models.
EcoScan layers three independent defences against malformed output:

1. **Prompt-level schema** (§3.3) — the synthesis prompt explicitly
   states the JSON object's structure inline, with type hints.
2. **API-level format mode** — `ollama.chat(..., format="json")` in
   `app/investigation.py::_synthesise` instructs the Ollama runtime
   itself to guarantee syntactically valid JSON output, even if the
   prompt's instruction were partially ignored.
3. **Python validation + clamping** — `_parse_synthesis_json` strips
   optional ```json fences, regex-extracts the JSON block, clamps
   `risk_score` to `[0, 100]`, coerces missing fields to safe defaults,
   and falls back to a neutral `risk_score: 50` "synthesis failed"
   structure if parsing raises. Last line of defence.

Together these three layers ensure the Streamlit UI **never** receives
malformed data, regardless of model behaviour.

### 3.5 Iterations during the project

Prompts evolved during the build. Notable changes:

- **Synthesis prompt switched from PT-PT to English** (also noted in
  §2.4). Reason: the demo audience became international; an English
  prompt produces an English JSON, which the UI renders without further
  translation.
- **Risk classifier originally returned freeform prose.** The forced
  final-line `DANGER: YES / DANGER: NO` contract was added so Python
  could detect the verdict without natural-language parsing.
- **OpenAQ findings summary was expanded in §2.11.** Before Fix B, the
  synthesis prompt saw only station counts (e.g. *"2 nearby stations"*).
  After Fix B, it sees per-station pollutant readings (e.g.
  *"Entrecampos: no2=23.4 µg/m³, pm25=11.2 µg/m³"*). This was a
  prompt-*adjacent* engineering change — the prompt template itself
  didn't change, but the evidence the prompt receives became
  dramatically richer, which directly affects synthesis quality.

All three prompts can be edited in `models.yaml` without touching any
Python code, and the changes take effect on the next Streamlit reload.

---

## 4. Runtime AI usage

When an inspector starts a manual investigation or validates a complaint,
the app makes the following AI calls (all local, via Ollama):

| Step | Model | Trigger | Where the prompt lives |
|---|---|---|---|
| Image description | `moondream` | Optional (only if the inspector enables satellite analysis) | `models.yaml` → `image_model.prompt` |
| Visual risk classification | `llama3.2` | Same as above (chained after image description) | `models.yaml` → `text_model.prompt` |
| Risk synthesis (JSON report) | `llama3.2` | Always, after public sources finish | `models.yaml` → `synthesis.prompt` |

No cloud LLM is called. No data leaves the user's machine other than the
plain HTTPS GETs to Nominatim, Overpass, GBIF, OpenAQ, and ESRI World
Imagery — all of which are public, free APIs.
