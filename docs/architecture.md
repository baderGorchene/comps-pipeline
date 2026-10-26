# Architecture

## Principles

1. **Python owns all math and decisions.** Gemini never filters, ranks, computes, or adds properties. It only returns flags.
2. **Never guess.** Missing or uncertain data becomes value `null` plus a Flag with a reason. Nothing is imputed.
3. **Determinism.** Same input + same config -> identical shortlist and ranking. No randomness, stable sorts, explicit tie-breaks. The reference date is the subject's `effective_date`, not today.
4. **Validation gate.** Every LLM response passes `validation/gate.py` before it can affect any output. Failures become flags, never crashes.
5. **No hardcoded business rules.** Every threshold lives in `config/settings.yaml`.
6. **Offline by default.** Fully runnable and testable with no API key (`MockLLMClient`).
7. **Local on Windows 11.** `pathlib` everywhere. The only data leaving the machine is the Gemini review payload, limited to `llm.fields_sent`.
8. **Standard field names.** Client CSV headers are mapped in `config/column_mapping.yaml`.

## Stages (`pipeline.run`)

```
load inputs (subject YAML, LLM client)          pipeline.py, llm/__init__.py
  -> ingest       CSV as text, header mapping   ingest/mapper.py
  -> clean        typed Cells + flags, dedupe,  ingest/cleaner.py
                  status -> sold | listing pool
  -> geo          haversine, else MLS Distance  filters/geo.py
  -> subdivision  normalize, tier, score        matching/normalize.py, subdivision.py
  -> hard filters sale date (sold), GLA, lot,   filters/hard_filters.py
     + escalation distance, subdivision,        filters/escalation.py
                  features; relaxed step by step
                  while sold < min_shortlist_size
  -> rank         per pool: buckets by          ranking/ranker.py
                  hierarchy, tie-breakers
  -> final pick   5 sold + 1 listing, swaps     selection/final.py
                  until the subject is bracketed
  -> llm review   batches of fields_sent only   llm/review.py (+ gemini_client / mock_client, cache)
  -> gate         schema, ID, quote, reason     validation/gate.py
  -> write        CSV/JSON/JSONL outputs        outputs/writers.py
  -> manifest     hashes, config, timings       outputs/writers.py
```

Each stage returns its kept comps plus `flags`, `excluded` and `audit` entries. Every stage is timed in the manifest, and every exclusion has an audit entry. Subdivision matching runs before the hard filters, but it only annotates. The subdivision filter is one of the hard filters, so a row that fails several rules gets every reason recorded (see `decisions.md`).

The LLM stage receives the ranked shortlist and can only add flags. `tests/test_review.py` checks that the shortlist, ranks and comp values are byte-identical with the LLM off, clean, hallucinating, faking quotes, malformed or erroring.

## Data model

- `Cell[T]`: `value`, `source` (MLS, COUNTY, COMPUTED, VISION, MANUAL, NONE), `flag`, `note`.
- `Comp`: standard fields as Cells, unmapped columns in `extras`, plus computed metrics, `rank` and `sort_key`.
- `Flag`: who it is about (`mls_number`, `"SUBJECT"`, or `None` for run-level), reason, severity, origin (RULE, LLM, GATE), message, evidence.
- `AuditEntry`: stage, decision (KEPT, EXCLUDED, FLAGGED, RANKED), rule, detail.
- `RunManifest`: run id, input hashes, config snapshot, version, LLM mode, row counts, durations.

## Where later phases plug in

| Phase | Module | Hooks into |
|---|---|---|
| Geocoding | `geocoding/` (`Geocoder` protocol) | Before `geo`: fill `latitude`/`longitude` Cells with `source=COUNTY`/`COMPUTED`; low confidence keeps `NO_COORDINATES` |
| Photos | `photos/` | After `rank`: fetch for shortlisted MLS numbers only |
| Condition | `condition/` | After photos: new Cells with `source=VISION`; results go through the gate; uses reserved reasons `INSUFFICIENT_EVIDENCE`, `ADJACENT_DISAGREEMENT`, `CONFLICTING_EVIDENCE` |
| Calibration | `calibration/` | Offline: runs the condition engine on Sam's labelled set |
| UAD 3.6 | `uad/` | After the gate: `build_grid(subject, shortlist, flags)` -> `grid.json` |
| Feedback | `feedback/` | Dashboard: record overrides to `overrides.jsonl` |
| Aivre | `integrations/aivre/` | After UAD: export or import into Aivre |
| Extensions | `extensions/` | Suggestions only, never auto-applied |
