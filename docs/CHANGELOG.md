# Changelog

All notable features, architectural milestones, and fixes in `comps-pipeline` are documented below in chronological order.

---

## [2026-11-04] — Asynchronous AI Executive Run Overview & Full Diagnostic Flag Presentation

### Added
- **Asynchronous AI Executive Run Overview (`src/comps_pipeline/ai/`, `web/views.py`, `web/templates/results.html`):**
  - Added [`generate_run_overview`](file:///d:/upwork/sam%20safak/comps-pipeline/src/comps_pipeline/ai/router.py) connecting primary `gpt-6.1-terra` to `gemini-flash-latest` fallback, with deterministic appraisal heuristic synthesis for offline execution.
  - Generates a 5-pillar appraisal synthesis: Executive Summary narrative, Search Scope & Market Depth evaluation (40-comp shortlist breakdown), Subject Bracketing Analysis across core physical features, New Construction & Underwriting Flags review, and Indicated Market Valuation Bracket.
  - Added dedicated endpoint [`GET /runs/<run_id>/ai-overview/`](file:///d:/upwork/sam%20safak/comps-pipeline/web/views.py) that generates and caches `data/output/<run_id>/ai_overview.json`.
  - Built progressive frontend rendering on [`results.html`](file:///d:/upwork/sam%20safak/comps-pipeline/web/templates/results.html): displays the results page immediately, loads the AI overview card asynchronously with an animated status indicator, and provides a 1-click "Regenerate" button.
- **Diagnostic Flag Visibility Across All Tables & Open Audit Panel:**
  - Replaced the bare flag count number in [`comp_table.html`](file:///d:/upwork/sam%20safak/comps-pipeline/web/templates/comp_table.html) with interactive, color-coded flag chips (`[REVIEW]`, `[BLOCKING]`, `[INFO]`) displaying reason codes and full descriptive tooltips.
  - Added Diagnostic Flags columns to Table 1 (Final Selection Comparables) and Table 2 (Analyzed, Not Used Shortlist).
  - Elevated the collapsed Flags details into an open, permanent **Underwriting Audit Panel** with instant severity filters (`All`, `Review`, `Blocking`, `Info`), reason codes, target fields, detailed underwriting messages, and evidence.
- **40-Comp Shortlist Clarification:**
  - Explicitly labeled the 40-comp shortlist breakdown across the executive funnel, section headers, and AI overview as **30 Sold comps + 10 Active/Pending listing comps**.

### Changed
- Expanded automated test suite from 135 to **136 passing tests** in `tests/test_web.py`.

---

## [2026-11-04] — Stage 4 Hard Price Gate, End-to-End New Construction Quotas & Production Hardening

### Added
- **Stage 4 Hard Price Bracket Gate (`filters/hard_filters.py`, `models/subject.py`, `config/schema.py`):**
  - Added strict integer-scaled price bracket filtering: excludes properties whose price deviates by more than `±price_bracket_pct`% (default `50%`) from `subject.benchmark_price` (evaluated from `contract_price`, `appraised_value`, or `estimated_value`).
  - Preserves exact boundary math (`comp_price * 100` vs `benchmark * (100 ± pct)`), avoiding floating-point boundary anomalies.
  - Added 13 dedicated unit tests in [`tests/test_hard_filters.py`](file:///d:/upwork/sam%20safak/comps-pipeline/tests/test_hard_filters.py).
- **Full-Pipeline New Construction (C1) Subdivision Quota Engine:**
  - **Stage 4 Escalation (`filters/escalation.py`):** Progressive escalation continues until both in-subdivision ($\ge 2$ sold, $\ge 1$ active) and out-of-subdivision ($\ge 1$ sold, $\ge 1$ active) quotas are satisfied or all 6 escalation steps exhaust. Emits `NEW_CONST_SUBDIVISION_DEFICIT` if criteria remain deficient.
  - **Stage 5 Anti-Crowding Shortlisting (`ranking/ranker.py`):** Implemented `_ensure_c1_shortlist_quotas` to prevent in-subdivision candidates from crowding out required out-of-subdivision candidates in the 25–30 shortlist cap.
  - **Stage 6 Selection & Swap Protection (`selection/final.py`):** Enforces 2 Sold + 1 Active in-sub, 1 Sold + 1 Active out-of-sub, and 1 Sold remainder. Bracketing swaps strictly reject candidates that would violate in-sub or out-of-sub quotas.
- **Production Deployment Hardening (`Dockerfile`, `web/settings.py`, `.env.example`):**
  - Added explicit `STATIC_ROOT` configuration in `web/settings.py` for seamless static asset handling.
  - Added automated `collectstatic --noinput` build step in `Dockerfile` for production serving via `whitenoise`.
  - Added comprehensive `.env.example` covering OpenAI, Gemini, and Django production variables.

### Fixed
- **Django Template Parsing in UI (`web/templates/new_run.html`):** Re-joined split newlines inside `{{ radio.choice_label }}` template tags that previously caused literal Django syntax to render in the browser.
- **UI & Mock Cleanup (`web/templates/new_run.html`, `data/`):** Removed hardcoded sample buttons (`Fill Bedr Sample`, `Fill RR Sample`), deleted scratch test YAML files, and renamed test suites for clean maintainability.

### Changed
- Expanded automated test suite from 118 to **135 passing unit, integration, and end-to-end tests**.

---

## [2026-11-04] — Architecture & AI Pipeline Specification (Version 3.6)

### Added
- **AI Model Router & Hot Failover Layer (`src/comps_pipeline/ai/`):**
  - Added [`AIModelRouter`](file:///d:/upwork/sam%20safak/comps-pipeline/src/comps_pipeline/ai/router.py) connecting primary `gpt-6.1-terra` to immediate fallback `gemini-flash-latest` with zero-downtime hot failover logging (`[AI_ROUTER_FALLBACK_TRIGGERED: gpt-6.1-terra -> gemini-flash-latest]`).
  - Added structured Pydantic schemas in [`parsers.py`](file:///d:/upwork/sam%20safak/comps-pipeline/src/comps_pipeline/ai/parsers.py) and prompt engineering in [`prompts.py`](file:///d:/upwork/sam%20safak/comps-pipeline/src/comps_pipeline/ai/prompts.py) for lease detection, entity owner classification, and rejection explanations.
  - Added instantaneous local heuristic fallbacks ensuring full zero-crash reliability during offline operations and test executions.
- **AI C1 vs. C2 Lease & Tenant Detection (`ingest/remarks.py`):**
  - Integrated keyword mining and AI lease analysis across remarks; flags properties (`LEASED_NEW_BUILD_REVIEW`) when 2026 / new builds have active lease or rental indicators, re-indexing condition from C1 to C2.
- **AI Owner Type Classification (`ingest/remarks.py`, `models/comp.py`):**
  - Automatic entity classification from `Owners Name` into `BUILDER` vs. `INDIVIDUAL`; flags new builds owned by private individuals (`INDIVIDUAL_OWNER_NEW_BUILD`).
- **New Construction Condition Priority & Bracketing Distribution Quotas (`ranking/ranker.py`, `selection/final.py`):**
  - Prioritizes verified builder C1 comps over tenant-occupied C2s in Stage 5 ranking.
  - Enforces the 6-comp quota distribution in Stage 6 (2 Sold + 1 Listing in-subdivision, 1 Sold + 1 Listing out-of-subdivision, 1 Sold remainder).
- **AI Rejection Justifications & Version 3.6 Data Artifacts (`outputs/writers.py`, `pipeline.py`):**
  - Added generation of mandatory 1-to-2 sentence plain-English appraisal justifications for all non-selected shortlisted comps.
  - Generated `shortlist_v36.csv` and `shortlist_v36.json` with `selection_status` (`FINAL_COMP_1`..`FINAL_COMP_6` vs `SHORTLIST_REJECTED`), `ai_rejection_justification`, and `ai_model_used`.
  - Added UI visualization in `results.html` rendering AI justifications in the "Analyzed, Not Used" workfile table.
- **1-Mile Baseline Research Range & Dynamic 25–30 Shortlist:**
  - Configured baseline research range to 1.0 mile before progressive escalation (`2.0` → `3.0` → `4.0` → `5.0` mi → `30%` GLA → `24` mo).
  - Implemented dynamic shortlisting keeping 25 guaranteed comps and expanding up to 30 based on proximity (< 1.0 mi) and quality metrics.
- Expanded test suite to **118 passing unit & integration tests** in `tests/test_ai_pipeline.py`.

---

## [2026-11-04] — Master Guidance & UAD 3.6 Alignment, Multi-Module UI & Hugging Face Deployment

### Added
- **Master Guidance & UAD 3.6 Domain Features (`src/comps_pipeline/`):**
  - **Module A (Location & Perimeter):** Added support for combined `City, State Zip` strings (`city_state_zip`) in `models/subject.py`, `models/comp.py`, and `ingest/cleaner.py`. Added optional strict `school_district` filtering with case-insensitive matching.
  - **Module B (Characteristics & Specifications):** Added property taxonomy filters (`property_type`, `property_sub_type`), story brackets (`stories`), foundation matching (`foundation_type`), and normalized UAD 3.6 condition (`C1`–`C6`) and quality (`Q1`–`Q6`) ratings with appraisal penalty matrices in `ranking/ranker.py`.
  - **Module C (Features & Amenities):** Added pool filtering & ranking prioritization (`pool`), ADU detection (`has_adu`), garage/carport space counts (`garage_spaces`, `carport_spaces`), utility fields (`water_sewer`, `hvac`, `energy_features`, `exterior_features`), and strict 55+ active adult community gating via both structured amenities (`Certified 55+ Community`) and keyword mining in `ingest/remarks.py`.
  - **Module D (Transaction Context):** Added transaction validation for financing types, seller concessions, ownership interest, and listing terms.
- **Multi-Module Appraisal Web UI (`web/templates/new_run.html`, `web/forms.py`):**
  - Restructured the New Run page into 4 accordion-style appraisal sections (Modules A, B, C, and D) matching standard appraisal intake forms.
  - Added sample prefill buttons (`Fill Round Rock Sample`, `Fill 3100 S 2nd St #33 (Chateau Heights)`, `Clear`) for rapid scenario testing.
- **Cloud & Container Deployment Ready:**
  - Added [Dockerfile](file:///d:/upwork/sam%20safak/comps-pipeline/Dockerfile) and [.dockerignore](file:///d:/upwork/sam%20safak/comps-pipeline/.dockerignore) tailored for non-root execution (`user:1000`) on Hugging Face Spaces (port 7860).
  - Updated [web/settings.py](file:///d:/upwork/sam%20safak/comps-pipeline/web/settings.py) to support `whitenoise` static serving, wild-card hosts, and CSRF trusted origins for Hugging Face Spaces.
  - Updated [.gitignore](file:///d:/upwork/sam%20safak/comps-pipeline/.gitignore) to exclude local `.claude/` artifacts and runtime `data/*.yaml` files while keeping canonical samples.

### Changed
- Expanded test suite to **112 passing unit & integration tests** covering UAD 3.6 ratings, 55+ community guards, remarks mining, and multi-module web runs.

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

