# Architecture

## Principles

1. **Python owns all math and decisions.** No AI model is involved; every filter, distance, rank and pick is computed from the rules.
2. **Never guess.** Missing or uncertain data becomes value `null` plus a Flag with a reason. Nothing is imputed.
3. **Determinism.** Same input + same rules -> identical shortlist and final pick. No randomness, stable sorts, explicit tie-breaks. The reference date is the subject's `effective_date`, not today.
4. **No hardcoded business rules.** Every threshold lives in `config/settings.yaml`.
5. **Local on Windows 11.** `pathlib` everywhere. Nothing leaves the machine.
6. **Standard field names.** Client CSV headers are mapped in `config/column_mapping.yaml`.
7. **The web app only collects inputs and shows results.** `web/` builds a Settings object from the form and calls `pipeline.run()`; result pages read the files the run wrote, so past runs open the same way after a restart. No database.

## Stages (`pipeline.run`)

```
load subject                                    pipeline.py
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
  -> write        CSV/JSON/JSONL outputs        outputs/writers.py
  -> manifest     hashes, config, timings       outputs/writers.py
```

Each stage returns its kept comps plus `flags`, `excluded` and `audit` entries. Every stage is timed in the manifest, and every exclusion has an audit entry. Subdivision matching runs before the hard filters, but it only annotates. The subdivision filter is one of the hard filters, so a row that fails several rules gets every reason recorded (see `decisions.md`).

## Web app (`web/`)

| Page | View | What it does |
|---|---|---|
| `/` | `new_run` | Inputs form (CSV or sample, subject typed or YAML) and rules form. Valid input -> run -> redirect to results |
| `/runs/<id>/` | `results` | Comparison grid of the final 6, rule steps, shortlists, flags, exclusions, log, downloads |
| `/runs/` | `history` | Every run folder in `data/output` |
| `/runs/<id>/files/<name>` | `download` | One of the run's output files (fixed list of names) |

## Data model

- `Cell[T]`: `value`, `source` (MLS, COMPUTED, NONE), `flag`, `note`.
- `Comp`: standard fields as Cells, unmapped columns in `extras`, plus `pool`, computed metrics, `rank` and `sort_key`.
- `Flag`: who it is about (`mls_number`, `"SUBJECT"`, or `None` for run-level), reason, severity, message, evidence.
- `AuditEntry`: stage, decision (KEPT, EXCLUDED, FLAGGED, RANKED), rule, detail.
- `RunManifest`: run id, input hashes, config snapshot, version, row counts, rule steps tried, durations.
