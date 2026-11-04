# comps-pipeline

A deterministic residential appraisal shortlisting engine and web studio that turns an MLS export (CSV) into a high-confidence comparable shortlist and selects the final appraisal comparison grid (5 sold comps + 1 active/option/pending listing, or 4 sold + 2 listings in New Construction mode).

## Key Features

1. **Deterministic Execution:** Every distance calculation, filter boundary, tolerance band, ranking metric, and bracketing swap is calculated with exact integer and fraction math in Python. Zero black-box or non-reproducible selections.
2. **7-Rule Hard Filtering & Strict Price Gate:**
   - Living area (GLA) within ±25% (exact integer boundary arithmetic).
   - Lot size within ±25% (exact `Fraction` acreage arithmetic).
   - Proximity within 1.0 mile baseline research range before escalation.
   - Hard Price Bracket Gate: excludes properties outside ±50% of the subject benchmark valuation (`contract_price` / `appraised_value`).
   - Sale recency within 12 months (or up to 24 months via escalation).
   - Strict market guardrails: property sub-type, stories, foundation, and 55+ community gating.
3. **New Construction Subdivision Allocation Quotas (C1 Mode):**
   - Automatically detects New Construction subjects (`construction_status: "new"` or recent build year).
   - Stage 4 Escalation continues until in-subdivision ($\ge 2$ sold, $\ge 1$ active) and out-of-subdivision ($\ge 1$ sold, $\ge 1$ active) candidate quotas are satisfied or all steps exhaust, logging `NEW_CONST_SUBDIVISION_DEFICIT` if deficient.
   - Stage 5 Shortlisting actively protects out-of-subdivision comps from being crowded out by in-subdivision comps within the 25–30 shortlist cap.
   - Stage 6 Selection picks 2 Sold + 1 Active inside the subdivision, 1 Sold + 1 Active outside the subdivision, plus 1 Sold remainder (6 comps total). Bracketing swaps strictly preserve these quotas.
4. **Dynamic 25–30 Shortlist:**
   - Guarantees 25 high-quality comps, dynamically expanding to 30 for comps within the 1.0-mile baseline research range with matching subdivision and quality metrics.
5. **AI Model Router & UAD 3.6 Rationales:**
   - Hot failover layer (`gpt-6.1-terra` with automatic fallback to `gemini-flash-latest`) and instant heuristic offline fallback.
   - Generates plain-English appraisal selection and deselection rationales for every shortlisted property.
   - Exports `shortlist_v36.csv` and `shortlist_v36.json` for UAD 3.6 appraisal software integration.
6. **Stateless Web Application:**
   - Zero database required (`DATABASES = {}`).
   - Interactive intake form, 6-module Configuration Studio, appraisal sales comparison grid with visual bracket indicators (`▲`, `▼`, `=`), and run history archive.

---

## Quick Start (Local)

### Option A: Windows 1-Click (`run.bat`)

Double-click `run.bat`. It installs dependencies via `uv`, runs migrations/checks, and opens `http://127.0.0.1:8000/` in your browser.

Requires [uv](https://docs.astral.sh/uv/):
```powershell
winget install --id=astral-sh.uv -e
```

### Option B: Python Virtual Environment

```bash
# Create virtualenv and install dependencies
uv sync

# Run the Django local server
.venv/Scripts/python manage.py runserver
```

---

## Deployment & Cloud Hosting

### Docker Container (Hugging Face Spaces & Cloud)

The repository includes a ready-to-deploy [Dockerfile](file:///d:/upwork/sam%20safak/comps-pipeline/Dockerfile) optimized for container platforms (such as Hugging Face Spaces):
- Runs as a non-root user (UID `1000`).
- Exposes port `7860` (HF Spaces default).
- Pre-compiles and serves static assets with `whitenoise`.
- Runs with production Gunicorn workers (`web.wsgi:application`).

```bash
# Build the Docker image
docker build -t comps-pipeline .

# Run container locally on port 7860
docker run -p 7860:7860 -e PORT=7860 comps-pipeline
```

### Environment Variables

Copy `.env.example` to `.env` or set environment variables in your deployment dashboard:

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key for primary `gpt-6.1-terra` AI inference | *Optional (heuristics fallback used if unset)* |
| `GEMINI_API_KEY` | Google Gemini API key for `gemini-flash-latest` hot failover | *Optional* |
| `SECRET_KEY` | Django cryptographic signing key | *Auto-generated random key* |
| `DEBUG` | Enable/disable Django debug mode | `True` locally, set `False` in production |
| `PORT` | Listening web port | `7860` in Docker, `8000` locally |

---

## Outputs (`data/output/<run_id>/`)

Every pipeline run creates an isolated, auditable output folder:

| File | Contents |
|---|---|
| `final_selection.csv` / `.json` | The final 5 sold + 1 listing (or 4 sold + 2 listings in C1 mode) with bracketing metrics |
| `shortlist_v36.csv` / `.json` | Full 25–30 shortlist with UAD 3.6 selection status and AI selection/deselection rationales |
| `shortlist.csv` / `.json` | Ranked sold comps followed by ranked listings (`pool` column) |
| `excluded.csv` | Every excluded input row with source row number, stage, and all failing reasons |
| `flags.csv` / `.json` | Sequential diagnostic flags (`F0001`, `F0002`, ...) with severity and evidence |
| `audit.jsonl` | Line-by-line machine-readable decision log recording every `KEPT`, `EXCLUDED`, `FLAGGED`, and `RANKED` action |
| `run_manifest.json` | Run metadata, SHA-256 input file hashes, configuration snapshot, stage durations, and escalation attempts |
| `ai_overview.json` | Executive appraisal summary narrative, search scope evaluation, bracketing analysis, and valuation bracket |
| `subject.json` | Validated subject property specification used for the run |
| `run.log` | Complete formatted pipeline execution log |

*Note: All CSV files are encoded in UTF-8 with BOM (`utf-8-sig`) for immediate compatibility with Microsoft Excel.*

---

## Repository Structure

```text
comps-pipeline/
├── Dockerfile                      # Production container image (HF Spaces port 7860, user 1000)
├── .dockerignore                   # Docker build exclusions
├── run.bat                         # One-click Windows launcher
├── manage.py                       # Django management entry point
├── pyproject.toml                  # Dependencies & tool configurations
├── config/
│   ├── settings.yaml               # Baseline filter thresholds, escalation steps, and ranking hierarchy
│   ├── column_mapping.yaml         # MLS CSV header alias candidate mapping
│   ├── subdivision_aliases.yaml    # Canonical subdivision name alias variants
│   └── subject.example.yaml        # Annotated template for subject YAML files
├── data/
│   ├── input/                      # User input files (git-ignored)
│   ├── samples/                    # Built-in sample datasets (Round Rock & McAllen benchmarks)
│   └── output/                     # Immutable run artifacts (<run_id>/)
├── src/comps_pipeline/
│   ├── ai/                         # AI Model Router (GPT-6.1 Terra -> Gemini Flash) & prompt parsers
│   ├── ingest/                     # CSV reader, column mapper, data cleaner & remarks NLP
│   ├── filters/                    # Distance (Haversine), hard filters & cumulative escalation
│   ├── matching/                   # Subdivision normalization, Roman numerals & 4-tier matching
│   ├── ranking/                    # Tolerance-band metric ranking & dynamic 25-30 shortlisting
│   ├── selection/                  # Final comp selection & strict-improvement bracketing swaps
│   └── outputs/                    # CSV/JSON/JSONL artifact writers & UAD 3.6 exporter
├── web/                            # Django web app (stateless, zero-database)
│   ├── views.py                    # New Run, Configuration Studio, Results & History views
│   ├── forms.py                    # Multi-module subject intake & rules forms
│   ├── static/app.css              # App styling
│   └── templates/                  # Responsive HTML templates
├── tests/                          # 135 passing unit, integration, and end-to-end tests
└── docs/                           # System architecture, changelog, and decisions
```

---

## Testing & Quality Assurance

```powershell
# Run the complete test suite (135 tests)
.venv\Scripts\python.exe -m pytest

# Run linter
.venv\Scripts\ruff check .
```
