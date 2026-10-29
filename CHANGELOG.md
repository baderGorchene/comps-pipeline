# Changelog

All notable features, architectural milestones, and fixes in `comps-pipeline` are documented below in chronological order.

---

## [2026-10-29] — Pipeline Audit Fixes, Hardening & Dependency Slimming

### Fixed
- **Bracketing Swap Rank Preservation (`selection/final.py`):** Kept `chosen` sorted by rank after every accepted swap so multi-swap runs always replace the lowest-ranked remaining comp first.
- **Exact Distance Bucket Arithmetic (`ranking/ranker.py`):** Converted distances to exact decimals via `Fraction(str(distance))` instead of `Fraction(distance)` so binary floating-point approximations (e.g., `0.3` miles with a `0.1`-mile band) never drop a comp into a lower tie bucket.
- **Subject vs. Comp Missing-Metric Attribution (`ranking/ranker.py`):** Stopped `compute_metrics` from stamping comp cells with `MISSING_REQUIRED_FIELD` when the *subject* property omitted optional `year_built` or `lot_size`, and prevented duplicate missing-lot flags when `lot_size_acres` was already flagged.
- **Hard-Filter Culprit Reporting (`ranking/ranker.py`, `filters/hard_filters.py`):** Scoped `_top_exclusion_rule` on `SHORTLIST_BELOW_MINIMUM` flags to `hard_filters` exclusions (ignoring `clean`-stage `STATUS_NOT_USED` and `DUPLICATE_LISTING` counts) and omitted contradictory `FLAGGED ("... kept")` audit entries when a row was excluded by another hard filter.
- **Sample Mode & Fill Sample Alignment (`web/templates/new_run.html`):** Updated the client-side `SAMPLE` subject values to match `data/samples/subject.yaml` (`2,000` sq ft, effective date `2026-10-01`, GPS `30.5083, -97.6789`) and auto-populated them when selecting the synthetic sample dataset.
- **Web Input & Encoding Resilience (`web/forms.py`, `pipeline.py`, `config/loader.py`, `web/views.py`):** Caught `yaml.YAMLError` and non-scalar values in escalation step parsing, added `utf-8-sig` and Windows `cp1252` fallback when loading `subject.yaml` and config files, and surfaced subject form validation errors in the top alert banner on `/`.
- **Temporary Directory Cleanup & Upload Filename Preservation (`web/views.py`):** Wrapped web run inputs in `tempfile.TemporaryDirectory` so temp files are removed after each run, and preserved the uploaded CSV's original filename in `run_manifest.json`, Results, and Past Runs.
- **DOM XSS Escaping (`web/templates/config.html`):** Escaped user input before rendering HTML in the visual escalation step builder and ranking hierarchy reorder widget.
- **Run Log Export (`web/views.py`):** Included `run.log` in the Results page download links as documented.

### Removed
- **Dropped `pandas` & `numpy` (`ingest/mapper.py`, `pyproject.toml`, `uv.lock`):** Replaced `pandas.read_csv` with Python's standard library `csv.reader`, removing `pandas`, `numpy`, `python-dateutil`, and `six` from runtime dependencies.
- **Dead Files & Unused Code:** Deleted orphaned `tests/test_synthetic.py`, unused `src/comps_pipeline/logging_setup.py`, unused `.env`, and dead `RulesForm` handling on `/`.

---

## [2026-10-28] — Studio Web Interface, Full Configuration Editor & Scope Refinement

### Added
- **6-Module Configuration Studio (`f788f94`, `d9a9587`):**
  - Added `/config/` (`ConfigForm`, `config.html`) to edit all pipeline settings in the browser and write back to `config/settings.yaml`, `config/column_mapping.yaml`, and `config/subdivision_aliases.yaml` with automatic `.yaml.bak` backups.
  - Added interactive visual builders for cumulative escalation steps, 7-key ranking hierarchy reordering, searchable 18-field CSV column mappings, subdivision alias rules, and per-flag severity selectors.
- **Under-the-Hood Execution Walkthrough (`f788f94`, `d9a9587`):**
  - Added an interactive 6-stage architecture explorer and live execution overlay on the New Run page (`new_run.html`).
  - Added an executive pipeline funnel strip and a 6-stage visual trace (`_build_pipeline_trace` in `web/views.py`, `results.html`) showing matched CSV headers, cleaning drop counts, distance/subdivision stats, filter exclusion bars, tolerance bands, and bracketing swaps.
- **Local Django Web Application (`fd3132e`):**
  - Created the database-free Django web app (`manage.py`, `web/settings.py`, `web/urls.py`, `web/views.py`, `web/forms.py`, `web/templates/`) with New Run (`/`), Results (`/runs/<run_id>/`), Past Runs (`/runs/`), and whitelisted artifact downloads (`/runs/<run_id>/files/<name>`).
  - Added the appraisal Sales Comparison Grid view with `▲` / `▼` / `=` subject comparisons and per-attribute bracketing badges.
  - Updated `run.bat` to sync dependencies with `uv` and launch the local Django server on `http://127.0.0.1:8000/`.

### Removed
- **Narrowed Scope to Deterministic Shortlisting (`fd3132e`, `f788f94`):** Removed the optional Gemini LLM review stage, validation gate, CLI entry point, Streamlit dashboard, synthetic generator script, and Phase 2+ placeholder folders (ADR-025).

---

## [2026-10-26] — Sold/Listing Pools, Auto-Escalation, Final 6 Bracketing & Real MLS Formats

### Added
- **Sold vs. Listing Pool Split (`f294d1e`):**
  - Added `status.sold` and `status.listing` routing in `cleaner.py` and `config/schema.py` so sold comps and active/option/pending listings are validated and ranked as separate pools (ADR-020).
  - Required `close_price` and `close_date` only for sold comps; excluded unused statuses (`Expired`, `Withdrawn`, etc.) with `STATUS_NOT_USED`.
- **Cumulative Rule Escalation (`f294d1e`):**
  - Added `filters/escalation.py` (`filter_with_escalation`) to relax hard filters step by step (`4.0` mi -> `5.0` mi -> `±30%` GLA -> `24` months) while sold candidates fall below `run.min_shortlist_size` (20), recording `CRITERIA_RELAXED` flags and manifest attempt summaries (ADR-021).
- **Final 5 Sold + 1 Listing Selection with Subject Bracketing (`f294d1e`):**
  - Added `selection/final.py` (`select_final`) to pick the top 5 sold comps and 1 active/option/pending listing and perform strict-improvement swaps from the sold shortlist until the subject is bracketed above and below on `gla`, `lot`, `age`, `beds`, and `baths` (ADR-022).
  - Added `final_selection.csv` and `final_selection.json` outputs.
- **Lot Acreage Bracket, Room Ranking Keys & MLS Distance Fallback (`f294d1e`):**
  - Added exact-fraction lot size bracketing (`lot_filter`, `lot_acres` converting sq ft at `43,560` sq ft/acre or reading `Acreage`) and `total_baths` (`full + 0.5 * half`) (ADR-023).
  - Expanded ranking hierarchy to 7 keys (`subdivision, distance, gla, age, lot, beds, baths`).
  - Added fallback to the MLS export's reported `Distance` column when GPS coordinates are absent (ADR-024) and `#2` -> `UNIT 2` subdivision normalization (`tests/test_real_format.py`).
- **Subject Form Input & Prefill (`13ef752`, `35aa32b`, `9c31566`):**
  - Added form-based subject property entry alongside YAML upload and automatic prefill from `data/input/subject.yaml` when present.

---

## [2026-10-25] — Initial Core Pipeline & Foundation

### Added
- **Project Skeleton, Strict Config & Data Models (`91212ce`):**
  - Initialized `pyproject.toml` with `uv`, strict Pydantic config validation (`config/schema.py`, `config/loader.py`), and core data models (`Cell[T]`, `Comp`, `Subject`, `Flag`, `AuditEntry`, `RunManifest`).
  - Created `config/settings.yaml`, `config/column_mapping.yaml`, and `config/subdivision_aliases.yaml`.
- **Synthetic Benchmark Dataset (`d5d9c69`, `a93fae2`):**
  - Added the deterministic 300-row Round Rock, TX sample dataset (`data/samples/mls_sample.csv`, `data/samples/subject.yaml`) and hand-crafted ranking demo (`data/samples/ranking_demo.csv`) with planted boundary, subdivision, and cleaning edge cases.
- **CSV Ingestion & Cleaning (`cedfee5`):**
  - Added `ingest/mapper.py` (case-insensitive header mapping, preserving unmapped columns in `extras`) and `ingest/cleaner.py` (price, integer, float, and multi-format date parsing against `subject.effective_date`, plus duplicate MLS detection).
- **Haversine Distance & Hard Filters (`34d671d`):**
  - Added `filters/geo.py` (`haversine_miles`) and `filters/hard_filters.py` (`gla_filter` with exact integer math, `distance_filter`, `subdivision_filter`, `required_features_filter`), evaluating all filters per comp so every failing reason is recorded.
- **Subdivision Normalization & 4-Tier Fuzzy Matching (`25d32e6`):**
  - Added `matching/normalize.py` and `matching/subdivision.py` supporting Roman numerals, phase/section/unit abbreviations, noise-word stripping, number-conflict guards, manual aliases, and `rapidfuzz` `token_sort_ratio` scoring.
- **Tolerance-Band Ranking (`6f6e0ae`):**
  - Added `ranking/ranker.py` with exact `Fraction` tolerance-band bucketing, missing-value last-sorting, tie-breakers (`distance`, `|gla_diff_pct|`, `mls_number`), and `SHORTLIST_BELOW_MINIMUM` detection.
- **Output Writers, End-to-End Orchestrator & Documentation (`38cb416`, `b7aae62`, `7b2d548`, `db0a35a`, `bef0a8d`, `786cacc`):**
  - Added `outputs/writers.py` (`utf-8-sig` CSVs, JSONs, `audit.jsonl`, `run_manifest.json`) and `pipeline.py` (`pipeline.run`).
  - Added initial project documentation (`README.md`, `config/README.md`, `data/README.md`, `docs/architecture.md`, `docs/decisions.md`, `docs/open_questions.md`) and Windows launcher scripts.

