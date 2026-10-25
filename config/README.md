# config

Every business rule the pipeline applies lives in these files, never in the code. Check your edits with:

```powershell
uv run python -m comps_pipeline validate-config
```

A typo in a setting name, or a missing setting, is an error. There are no hidden defaults in the code.

## Files

| File | What it is |
|---|---|
| `settings.yaml` | Thresholds, ranking order, LLM options |
| `column_mapping.yaml` | Which CSV header feeds which standard field |
| `subdivision_aliases.yaml` | Names you have confirmed mean the same subdivision (empty by default) |
| `subject.example.yaml` | Template for a subject property |

## settings.yaml

### run
| Setting | Meaning | Example |
|---|---|---|
| `output_dir` | Where run folders are created | `data/output` |
| `shortlist_size` | How many ranked comps to keep | `30` |
| `min_shortlist_size` | Fewer than this gives a BLOCKING flag (exit code 2) naming the filter that removed the most rows | `25` |

### ingest
| Setting | Meaning |
|---|---|
| `date_formats` | Date formats to try, in order. `%m/%d/%Y` = 06/15/2026 |

### filters
| Setting | Meaning | Example |
|---|---|---|
| `gla_bracket_pct` | Keep comps whose living area is within this percent of the subject (whole number) | `30`: subject 2,000 sq ft keeps 1,400-2,600 |
| `gla_bracket_inclusive` | `true` keeps comps exactly on the edge (1,400 and 2,600) | `true` |
| `missing_gla` | Comp with no usable living area: `exclude` or `keep_and_flag` | `exclude` |
| `max_distance_miles` | Straight-line distance limit | `1.0` |
| `missing_distance` | Comp with no coordinates: `exclude` or `keep_and_flag` | `exclude` |
| `require_subdivision_match` | Drop comps whose subdivision doesn't match (tier 3) | `true` |
| `subdivision_min_score` | Fuzzy similarity (0-100) needed to count as a possible match (tier 2, flagged for review) | `90` |
| `sale_date_max_months` | Sales closed longer ago than this, counted back from the subject's effective date, are excluded | `12` |
| `required_features` | Exact values a comp must have. Works with standard fields or any CSV column | `{ foundation_type: "Crawl Space" }` |

### matching
| Setting | Meaning |
|---|---|
| `noise_words` | Words ignored when comparing subdivision names. `ESTATES` is not included by default, because "Oak Estates" and "Oak" may be different places. Add it only if you want it ignored |

Subdivision tiers: **0** same name after cleanup (case, "Ph"/"Phase", "II"/"2", punctuation), **1** listed in `subdivision_aliases.yaml`, **2** close spelling (flagged `SUBDIVISION_UNCERTAIN`), **3** different. If both names carry a phase, section or unit number and the numbers differ, the match is never tier 0 or 1.

### ranking
| Setting | Meaning |
|---|---|
| `hierarchy` | Priority order. Must contain each of `subdivision, distance, gla, age, lot` exactly once |
| `tolerance_bands` | Differences inside the same band count as a tie, so the next key decides. With `distance_miles: 0.25`, comps at 0.31 and 0.32 mi tie on distance and GLA decides |

Final tie-breakers, always in this order: exact distance, exact GLA difference, MLS number.

### llm
| Setting | Meaning |
|---|---|
| `enabled` | `false` skips the review (an `LLM_UNAVAILABLE` info flag is added) |
| `provider` | `gemini` or `mock` (offline, for tests and demos) |
| `mock_mode` | `clean`, `hallucinate_id`, `fake_quote`, `malformed`, `error` |
| `model_env` / `api_key_env` | Names of the environment variables (in `.env`) holding the model and key |
| `temperature` | `0` for repeatable answers |
| `max_retries` | Retries after a response that doesn't match the schema |
| `batch_size` | Comps per request |
| `fields_sent` | The only fields that leave your machine. `mls_number` is required |
| `cache` / `cache_dir` | Reuse identical answers instead of paying for them again |

### validation
| Setting | Meaning |
|---|---|
| `require_evidence_quote` | An LLM flag must quote the comp's remarks or subdivision text word for word, or it is rejected |

### severity
How serious each flag reason is: `INFO`, `REVIEW` or `BLOCKING`. Every reason must be listed. Any BLOCKING flag makes the run exit with code 2. Shipped values:

| Severity | Reasons |
|---|---|
| BLOCKING | SHORTLIST_BELOW_MINIMUM |
| REVIEW | MISSING_REQUIRED_FIELD, INVALID_VALUE, NO_COORDINATES, SUBDIVISION_UNCERTAIN, POSSIBLE_NON_ARMS_LENGTH, REMARKS_CONCERN, LLM_SCHEMA_FAILURE |
| INFO | DUPLICATE_LISTING, OUT_OF_DATE_RANGE, LLM_UNKNOWN_ID, LLM_EVIDENCE_NOT_FOUND, LLM_DISALLOWED_REASON, LLM_UNAVAILABLE |

The dashboard's "Save as default" rewrites `settings.yaml` without these comments. The previous version is kept as `settings.yaml.bak`.
