# comps-pipeline

A local tool that turns an MLS export (CSV) into a ranked shortlist of comparable sales for one subject property.

In plain language, it:

1. Reads the CSV exactly as exported, as text, and maps your column names to standard names.
2. Cleans the values: prices, dates, square footage. A bad or missing value is never guessed. It is left blank and flagged.
3. Removes rows that fail your rules: living area bracket, distance, subdivision, sale date, required features. Every removed row is listed with **every** reason it failed.
4. Ranks the rest by your priority order (subdivision, distance, GLA, age, lot) with tolerance bands, so small differences count as ties.
5. Optionally asks Google Gemini to **flag** remarks worth a second look (estate sale, family sale, investor special...). Gemini cannot change, rank, or add anything. Each flag must quote the remarks word for word, and the validation gate throws out any flag that doesn't check out.
6. Writes everything to `data/output/<run_id>/`: shortlist, excluded rows, flags, a full audit trail and a run manifest.

The same input and the same settings always give the same shortlist.

## Setup with uv (recommended)

In PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# or: winget install --id=astral-sh.uv -e
uv sync
copy .env.example .env
uv run python -m comps_pipeline demo
uv run pytest
```

`uv sync` installs Python 3.13 automatically if missing, creates `.venv`, and installs the exact versions from `uv.lock` (dev group included by default).

### Fallback without uv (pip 25.1+)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install --group dev
```

### Gemini (optional)

Put your key and model name in `.env`:

```
GEMINI_API_KEY=...
GEMINI_MODEL=...
```

Without them the pipeline still runs. It logs a clear error at startup, skips the review, and adds an `LLM_UNAVAILABLE` info flag. Use `--llm mock` for the offline reviewer or `--llm off` to skip review on purpose. Only the fields listed in `llm.fields_sent` are sent to Gemini. Nothing else leaves your machine.

## Running

| What | Command |
|---|---|
| Synthetic sample | `run.bat` |
| Dashboard | `run_dashboard.bat` |
| Your data | `uv run python -m comps_pipeline run --input data\input\export.csv --subject data\input\subject.yaml` |
| Choose LLM | add `--llm gemini`, `--llm mock` or `--llm off` |
| Other config | add `--config path\to\settings.yaml` |
| Check config | `uv run python -m comps_pipeline validate-config` |
| Check a CSV's columns | `uv run python -m comps_pipeline inspect-csv --input data\input\export.csv` |
| Gate demo | `uv run python -m comps_pipeline demo` |
| New synthetic data | `uv run python scripts/generate_synthetic.py --rows 300 --seed 42 --out data/samples` |

Exit codes: `0` ok, `1` config or input error, `2` completed but with BLOCKING flags (for example, fewer comps than `min_shortlist_size`).

### Running on real data

1. Copy the MLS export into `data\input\` (that folder is git-ignored and never committed).
2. Copy `config\subject.example.yaml` to `data\input\subject.yaml` and fill in the subject, including the appraisal `effective_date`.
3. Run `inspect-csv` on the export. Every required field should show a CSV header.
4. Run the pipeline. Open `shortlist.csv` and `flags.csv` in Excel.

### A new CSV layout: edit `config/column_mapping.yaml`

Each standard field lists the header names it may appear under:

```yaml
living_area: ["SqFt Living", "LivingArea", "GLA", "Sq Ft", "Total SqFt"]
```

If your export calls it `Apx SqFt`, add `"Apx SqFt"` to that list. Matching ignores case and surrounding spaces. If a required column is missing, the error lists every header the CSV does have. Columns that aren't mapped are kept per comp under `extras`, and you can still use them in `filters.required_features`.

## Outputs (`data/output/<run_id>/`)

| File | Contents |
|---|---|
| `shortlist.csv` / `.json` | Ranked comps. The JSON keeps every value with its source and flag |
| `excluded.csv` | Every row not shortlisted, with all reasons |
| `flags.csv` / `.json` | Every flag: rule, LLM (accepted by the gate) and GATE (rejected LLM output) |
| `audit.jsonl` | One line per decision, including each comp's full sort key |
| `run_manifest.json` | Input hashes, config snapshot, version, LLM mode, row counts, timings |

CSV files are UTF-8 with BOM so Excel opens them correctly.

## Folder guide

```
config/            settings.yaml, column_mapping.yaml, subdivision_aliases.yaml, subject.example.yaml
data/              input/ (yours, ignored), samples/ (synthetic), output/, cache/
src/comps_pipeline/
  ingest/          CSV -> standard fields -> typed, cleaned comps
  filters/         distance + hard filters
  matching/        subdivision normalization and tiers
  ranking/         deterministic ranking
  llm/             Gemini + mock clients, cache, review prompt
  validation/      the gate every LLM response must pass
  outputs/         file writers
  pipeline.py      runs the stages in order
  cli.py           command line
  geocoding/ uad/ photos/ condition/ calibration/ feedback/ integrations/ extensions/
                   placeholders for later phases (README only)
dashboard/         Streamlit app
scripts/           synthetic data generator, gate demo
tests/             pytest suite (no API key needed)
docs/              architecture, decisions, open questions, UAD notes, condition checklist draft
```

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Ingest, clean, filter, match, rank, LLM flags + gate, outputs, CLI, dashboard | **Built** |
| 1.x | Geocoding when the CSV has no coordinates | Placeholder: waiting on Sam's real CSV |
| 2 | Photos, condition evidence and C-rating, calibration | Placeholder: waiting on photo source and checklist approval |
| 2 | UAD 3.6 grid mapping | Placeholder: waiting on Sam's field list |
| 2+ | Feedback / override log | Placeholder: starts once Phase 1 is in real use |
| 3 | Aivre integration | Not scoped |
| — | Extensions (adjustments, market trends, comp history) | Ideas only |

See `docs/architecture.md` for how the stages fit together and `docs/open_questions.md` for what we still need from Sam.
