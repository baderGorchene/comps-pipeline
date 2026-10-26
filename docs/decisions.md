# Decisions (ADR log)

Newest decisions at the bottom. Each one gives the context, the decision, and its consequence.

### ADR-001 Python owns all math
**Context:** LLMs are non-deterministic and can hallucinate numbers. **Decision:** Every filter, distance, difference, bucket, rank and threshold is computed in Python from config. The LLM only returns flags. **Consequence:** The ranking is reproducible and auditable, and the LLM can be switched off without losing the shortlist.

### ADR-002 rapidfuzz before any LLM for subdivision matching
**Context:** Subdivision names vary in case, abbreviation, numerals and typos. **Decision:** Deterministic normalization, then manual aliases, then rapidfuzz `token_sort_ratio` with a configured threshold. Uncertain matches are flagged for Sam, not decided by a model. **Consequence:** Free, fast and repeatable. Differing phase, section or unit numbers can never be an exact or alias match.

### ADR-003 Integer math for boundaries
**Context:** `1000 * (1 - 0.18)` is `820.0000000000001` in floating point, which would wrongly drop a comp sitting exactly on the boundary. **Decision:** The GLA bracket compares `living_area * 100` with `subject * (100 ± pct)` in integers, and `gla_bracket_pct` must be a whole number. Ranking buckets use exact `Fraction`s. **Consequence:** Boundaries behave exactly as configured (covered by tests).

### ADR-004 `dtype=str` ingestion
**Context:** pandas type inference can turn MLS numbers like `00123` into `123`, `NA` into NaN, and mixed columns into floats. **Decision:** `read_csv(dtype=str, keep_default_na=False)`. All parsing happens in `cleaner.py` with explicit rules. **Consequence:** What we parse is exactly what the file says, and parse failures become flags.

### ADR-005 Mock client for offline tests
**Decision:** `MockLLMClient` with scripted modes (clean, hallucinate_id, fake_quote, malformed, error). **Consequence:** The whole suite and the demo run with no API key, and every gate path is exercised deterministically.

### ADR-006 Evidence-quote substring check
**Context:** An LLM can invent quotes. **Decision:** A flag is accepted only if `evidence_quote`, case-insensitive and whitespace-normalized, is a substring of that comp's `public_remarks` or `subdivision_raw`. An empty quote is always rejected. **Consequence:** Every accepted flag points to real text Sam can see.

### ADR-007 UTF-8 BOM CSVs
**Decision:** All output CSVs are written as `utf-8-sig`. **Consequence:** Excel on Windows shows accents and symbols correctly when the file is double-clicked.

### ADR-008 No browser automation in Phase 1
**Context:** MLS terms of use, copyright, and the risk of account suspension. **Decision:** No playwright, selenium or similar dependency. Photo sourcing is decided in writing first (see `photos/README.md`). **Consequence:** Phase 1 only reads files Sam exports himself.

### ADR-009 uv for environment and dependency management
**Decision:** uv with `pyproject.toml`, a committed `uv.lock` and `.python-version` (3.13). Dependencies are added only with `uv add` using compatible ranges, and the lockfile pins exact versions. **Consequence:** Fast installs, automatic Python install, and Sam's machine runs exactly the tested versions (`uv sync --locked`). A pip fallback is documented in the README.

### ADR-010 Subject `effective_date` is the reference date
**Context:** "Future" and "older than 12 months" depend on a reference date. Using today's date would make the same input give different shortlists on different days, breaking determinism. **Decision:** The subject YAML requires `effective_date` (the appraisal effective date). **Consequence:** Runs are reproducible, and the date has a clear appraisal meaning.

### ADR-011 Subdivision matching annotates before the hard filters
**Context:** The spec lists the stages as hard filters, then subdivision matching, but also requires the audit to record every failing rule, and the subdivision filter is one of the hard filters. **Decision:** The matching stage only computes tier and score. The hard filter stage then evaluates GLA, distance, subdivision and required features on the same input. **Consequence:** A row failing three rules lists all three in `excluded.csv`.

### ADR-012 Missing Gemini key: logged error, run continues
**Context:** The default config uses `provider: gemini`, while `run.bat` must complete on a machine with no key. **Decision:** At startup a missing key or model is logged as a clear ERROR naming the variables. The run then continues without review and adds an `LLM_UNAVAILABLE` info flag. API errors during the run are handled the same way per batch. **Consequence:** Gemini is optional at runtime, and the manifest records `gemini (unavailable)`.

### ADR-013 Settings added beyond the initial list
`run`/`filters`/`ranking`/`llm`/`validation` follow the spec. Added: `ingest.date_formats` (client-specific date formats), `filters.missing_gla` (behaviour when living area is unknown, mirroring `missing_distance`), `matching.noise_words` ("ESTATES only if configured"), `llm.api_key_env`, `llm.cache_dir`, and `severity` (one entry per flag reason, so severities are not hardcoded business rules). The schema has no default values: every setting must be present in `settings.yaml`, so no threshold is duplicated as a literal in `src/`.

### ADR-014 Retry lives in the review loop, checks live in the gate
**Decision:** `llm/review.py` re-asks once (`llm.max_retries`) with the schema error appended to the system prompt. `validation/gate.py` then validates the final response independently and turns a second failure into `LLM_SCHEMA_FAILURE` for the batch. Only responses that parse are cached. **Consequence:** The gate needs no client, and nothing unvalidated is reused.

### ADR-015 `reason` is constrained for Gemini but parsed as text
**Decision:** The response schema sent to Gemini carries an enum of the three allowed reasons. Parsing accepts any string, so a disallowed reason is rejected item by item (`LLM_DISALLOWED_REASON`) instead of failing the whole batch. **Consequence:** Defense in depth, and valid flags in the same batch survive.

### ADR-016 `shortlist.json` holds comps only
**Decision:** Flags live in `flags.json`/`flags.csv`. `shortlist.csv` shows a flag summary column. **Consequence:** `shortlist.json` is byte-identical between LLM-off and LLM-on runs, which is the proof that the review cannot change ranking or values.

### ADR-017 Every input row is accounted for
**Decision:** Comps ranked below `shortlist_size` appear in `excluded.csv` with `RANK_BEYOND_SHORTLIST`. **Consequence:** shortlist + excluded = input rows, and every excluded row has at least one reason.

### ADR-018 Whole numbers only for price, GLA, lot, year
**Decision:** `"$412,500.00"` parses to 412500. A non-whole value such as `1850.5` sq ft becomes `INVALID_VALUE` rather than being rounded. **Consequence:** No silent rounding. Revisit if Sam's MLS exports fractional values.

### ADR-019 No python-dotenv
**Decision:** A dozen-line `.env` reader in `config/loader.py` (KEY=VALUE, existing environment wins). **Consequence:** One fewer dependency.

### ADR-020 Sold and listings are separate pools
**Context:** The final pick is 5 sold + 1 active/option/pending, and listings have no close price or date. **Decision:** `status.sold` / `status.listing` assign each row to a pool at cleaning; anything else is excluded (`STATUS_NOT_USED`). Close price/date are required for sold rows only. Each pool is filtered with the same rules (the sale-date window applies to sold only) and ranked separately; `run.shortlist_size` and the minimum apply to sold, `run.listing_shortlist_size` to listings. **Consequence:** `status` is a required column.

### ADR-021 Escalation is cumulative and config-driven
**Decision:** `escalation.steps` are filter overrides applied one at a time, each keeping the previous ones, until the sold pool reaches `run.min_shortlist_size`. Every cumulative level is validated at load time. Each applied step is a `CRITERIA_RELAXED` flag (REVIEW) and the manifest lists every level tried. If the last level still falls short, `SHORTLIST_BELOW_MINIMUM` (BLOCKING) as before. **Consequence:** Changing the order or adding a step is a YAML edit. The sale-date window moved from cleaning to the hard filters so it can be relaxed.

### ADR-022 Bracketing by strict-improvement swaps
**Decision:** Start from the top-ranked 5 sold + 1 listing. While some attribute is not bracketed, try shortlisted sold candidates in rank order in place of the lowest-ranked sold picks, and accept the first swap whose remaining gaps are a strict subset of the current ones. Gaps shrink with each swap, so it terminates, and a swap never trades one gap for another. The listing pick is fixed. Unknown values don't count toward bracketing; a subject value that is unknown skips that attribute (flagged once on the subject). **Consequence:** The final pick stays as close to the ranking as possible, and every swap is in the audit.

### ADR-023 Lot compared in acres, baths as full + half/2
**Decision:** Lot size in exact fractions of an acre (square feet / 43,560 when given, else the `Acreage` column). Baths = full + 0.5 x half; unknown half baths make the total unknown rather than assuming 0. **Consequence:** The lot bracket is exact at the boundary like GLA.

### ADR-024 Distance from coordinates, else the export's Distance column
**Decision:** Haversine when both the subject and the comp have coordinates. Otherwise the MLS export's `Distance` value ("4.0 mi") with source `MLS`. Neither gives `NO_COORDINATES`. Subject latitude/longitude are now optional. **Consequence:** Exports without coordinates work without geocoding.

### Dependencies
Runtime: pandas, pydantic, pyyaml, rapidfuzz, typer, rich, google-genai, streamlit. Dev: pytest, ruff. No additional direct dependencies were added beyond the agreed stack.
