# EcoScan — Setup & Run

## 1. Prerequisites

- **Python 3.10+** (Windows, macOS or Linux)
- **Ollama** — local AI runtime: <https://ollama.com>

EcoScan never calls a paid LLM. All AI runs locally through Ollama.

## 2. Install Python dependencies

From the project root:

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Pull the AI models

After installing Ollama and starting it (`ollama serve`, or just running the
Ollama desktop app), pull the two models EcoScan uses:

```bash
ollama pull moondream      # vision model (used only for satellite analysis)
ollama pull llama3.2       # risk classifier + synthesis
```

If you forget this step, the app will pull the models on first use — but
that may take several minutes. Pulling beforehand keeps the demo snappy.

## 4. Run the app

```bash
streamlit run app/dashboard.py
```

Streamlit prints a local URL (usually `http://localhost:8501`) — open it
in your browser.

## 5. First run

- **Complaints data** — the file `database/complaints.xlsx` is auto-seeded
  the first time you open the *Complaints* page. Edit it freely afterwards;
  delete it to regenerate the seed list.
- **Investigations log** — `database/investigations.csv` is created on the
  first investigation.
- **Satellite cache** — `database/satellite_cache.csv` and the `images/`
  folder hold the cached results of the optional satellite branch.

## 6. Configuration

All AI behaviour is controlled by [`models.yaml`](models.yaml):

- `image_model` — the vision model used to describe satellite images.
- `text_model` — the model that answers structured risk questions.
- `synthesis` — the model that writes the final risk report (JSON).

You can swap models, edit prompts, or tune temperatures without touching
the Python code. After saving the file, refresh the Streamlit tab.

## 7. Public-data rate limits

The app calls five free public sources. They have soft rate limits:

| Source | Limit | Note |
|---|---|---|
| Nominatim (OSM) | 1 request/sec | Used for reverse geocoding and place search. |
| Overpass (OSM) | 25-second query timeout | Used for POIs near the inspection point. |
| GBIF | Generous, but be polite | Used for biodiversity occurrences. |
| OpenAQ v3 | **Requires a free API key** | Optional. Set `OPENAQ_API_KEY` to enable. Without it the app skips this source gracefully. |
| ESRI World Imagery | Per-IP fair-use | Tile service used for the optional satellite branch. No key required. |

A failure on any single source is logged and skipped — the investigation
continues with whatever evidence the others returned.

### Enabling OpenAQ (optional)

All four public-data sources EcoScan uses are free. Three of them
(Nominatim, Overpass, GBIF) are fully anonymous and need no setup. OpenAQ
v3 is the only one that asks you to register for a (still free) API key,
which is then sent as a request header so the service can rate-limit per
user instead of per IP.

Without the key, the OpenAQ panel shows a friendly note and the rest of
the pipeline (OpenStreetMap, GBIF, satellite vision, synthesis) runs as
usual — so the app remains fully usable.

To enable air-quality data:

1. Register a free account at <https://explore.openaq.org/register>.
2. From your account page, generate and copy an **API key**.
3. Expose the key to EcoScan as the `OPENAQ_API_KEY` environment variable.

**Option A — session-only (Windows / PowerShell):**

```powershell
$env:OPENAQ_API_KEY = "your-key-here"
streamlit run app/dashboard.py
```

The key lasts only as long as that terminal window stays open.

**Option B — persistent (Windows, recommended):**

1. Press the Windows key → type *"Edit environment variables for your account"* → open it.
2. Under **User variables**, click **New…**.
3. Variable name: `OPENAQ_API_KEY` — Variable value: your key — **OK**.
4. Close and reopen your terminal so it picks up the new value.
5. Verify with `echo $env:OPENAQ_API_KEY`.

**macOS / Linux:**

```bash
export OPENAQ_API_KEY="your-key-here"
streamlit run app/dashboard.py
```

Add the `export` line to your `~/.zshrc` or `~/.bashrc` to make it
persistent across sessions.

> 🔒 Treat the API key like a password. Never commit it to git, never paste
> it into screenshots or slides.

## 8. Troubleshooting

- **"Connection refused" when running Ollama** — the Ollama service isn't
  running. Start the Ollama desktop app or run `ollama serve`.
- **Pages don't appear in the sidebar** — Streamlit ≥ 1.36 is required for
  `st.navigation`. Upgrade with `pip install -U streamlit`.
- **The interactive map looks empty** — that means `streamlit-folium`
  failed to install. Re-run `pip install -r requirements.txt`.
- **Investigation hangs on the synthesis step** — the first call to
  `llama3.2` after a system reboot can be slow as Ollama warms up. Give
  it a minute.
