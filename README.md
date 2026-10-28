# comps-pipeline

A local web app that turns an MLS export (CSV) into a shortlist of comparable sales for one subject property, and picks the final 5 sold comps + 1 active/option/pending listing.

What a run does:

1. Reads the CSV exactly as exported, as text, and maps your column names to standard names (`config/column_mapping.yaml`).
2. Cleans prices, dates, square footage and room counts. A bad or missing value is never guessed: it is left blank and flagged. The status column splits sold comps from active/option/pending listings; other statuses are excluded.
3. Removes comps that fail your rules: living area ±25%, lot ±25% (in acres), within 3 miles, sold in the last 12 months, required features. Every removed row is listed with every reason it failed.
4. If fewer than 20 sold comps are left, relaxes the rules one step at a time, in order: 4 miles, 5 miles, living area ±30%, 24 months. Each step is recorded.
5. Ranks sold comps and listings separately: same subdivision first, then distance, living area, age, lot, beds, baths, with tolerance bands so small differences tie.
6. Picks the top 5 sold + 1 listing, and swaps in lower-ranked sold comps when needed so the subject is bracketed (one comp above and one below) on living area, lot, year built, beds and baths.

The same input and the same rules always give the same result. All thresholds live in `config/settings.yaml`, and the web form can change them per run.

## Start it

Double-click `run.bat`. It installs what's needed (first time only), starts the app and opens http://127.0.0.1:8000/ in your browser. Close the window to stop it.

`run.bat` needs [uv](https://docs.astral.sh/uv/):

```powershell
winget install --id=astral-sh.uv -e
```

`uv sync` installs Python 3.13 if missing and the exact versions from `uv.lock`.

## Using the app

- **New run:** upload the MLS export (or use the synthetic sample), then type the subject in or upload a `subject.yaml`. The rules on the right start from `config/settings.yaml`. Tick "Save these rules as the default" to write them back (the old file is kept as `settings.yaml.bak`).
- **Results:** the final 6 laid out like the sales comparison grid, with ▲/▼ against the subject and a bracket check per row; which rule steps were used; the ranked sold and listing shortlists; flags; every excluded row with its reasons; downloads.
- **Past runs:** every run is kept in `data/output/<run_id>/`.

If `data/input/subject.yaml` exists, the subject form starts with it. `data/input/` is git-ignored, so real client files are never committed.

### A new CSV layout

Each standard field in `config/column_mapping.yaml` lists the header names it may appear under:

```yaml
living_area: ["SqFt Living", "LivingArea", "GLA", "Sq Ft", "Total SqFt", "Living Area", "Living Sq Ft"]
```

Add your export's header to the right list. Matching ignores case and surrounding spaces. If a required column is missing, the error lists every header the CSV does have.

## Outputs (`data/output/<run_id>/`)

| File | Contents |
|---|---|
| `final_selection.csv` / `.json` | The final 5 sold + 1 listing |
| `shortlist.csv` / `.json` | Ranked sold comps, then ranked listings (`pool` column) |
| `excluded.csv` | Every row not shortlisted, with all reasons |
| `flags.csv` / `.json` | Every flag, with severity |
| `audit.jsonl` | One line per decision, including each comp's sort key and every swap |
| `run_manifest.json` | Input hashes, rules used, rule steps tried, row counts, timings |
| `subject.json`, `run.log` | The subject as used, and the run's log |

CSV files are UTF-8 with BOM so Excel opens them correctly.

## Folder guide

```
run.bat            starts the app
manage.py, web/    Django app: forms, pages, styles (no database)
config/            settings.yaml, column_mapping.yaml, subdivision_aliases.yaml, subject.example.yaml
data/              input/ (yours, ignored), samples/ (synthetic), output/ (runs)
src/comps_pipeline/
  ingest/          CSV -> standard fields -> typed, cleaned comps
  filters/         distance, hard filters, rule relaxation
  matching/        subdivision normalization and tiers
  ranking/         ranking per pool
  selection/       final 6 with bracketing
  outputs/         file writers
  pipeline.py      runs the stages in order
scripts/           synthetic data generator
tests/             pytest suite
docs/              architecture, decisions, open questions
```

## Development

```powershell
uv run pytest
uv run ruff check .
uv run python scripts/generate_synthetic.py --rows 300 --seed 42 --out data/samples
```

See `docs/architecture.md` for how the stages fit together and `docs/open_questions.md` for what we still need from Sam.
