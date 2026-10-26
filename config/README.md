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
| `shortlist_size` | How many ranked **sold** comps to keep | `30` |
| `min_shortlist_size` | Fewer sold candidates than this triggers `escalation`. Still fewer after the last step gives a BLOCKING flag (exit code 2) naming the filter that removed the most rows | `20` |
| `listing_shortlist_size` | How many ranked active/option/pending listings to keep | `10` |

### status
| Setting | Meaning |
|---|---|
| `sold` | Status values (any case) ranked as sold comps. Need a close price and close date |
| `listing` | Status values ranked as current listings (active, option, pending). No close data needed |

Any other status (expired, withdrawn, blank) is excluded with `STATUS_NOT_USED`. A value may not appear in both lists.

### ingest
| Setting | Meaning |
|---|---|
| `date_formats` | Date formats to try, in order. `%m/%d/%Y` = 06/15/2026 |

### filters
| Setting | Meaning | Example |
|---|---|---|
| `gla_bracket_pct` | Keep comps whose living area is within this percent of the subject (whole number) | `25`: subject 2,000 sq ft keeps 1,500-2,500 |
| `gla_bracket_inclusive` | `true` keeps comps exactly on the edge (1,500 and 2,500) | `true` |
| `missing_gla` | Comp with no usable living area: `exclude` or `keep_and_flag` | `exclude` |
| `lot_bracket_pct` / `lot_bracket_inclusive` | Same rule for the lot, compared in acres (square feet are converted; `Acreage` is used when there are no square feet) | `25` |
| `missing_lot` | Comp with no lot size: `exclude` or `keep_and_flag` | `keep_and_flag` |
| `max_distance_miles` | Distance limit: straight-line from coordinates, else the export's `Distance` column | `3.0` |
| `missing_distance` | Comp with neither coordinates nor a reported distance: `exclude` or `keep_and_flag` | `exclude` |
| `require_subdivision_match` | `true` drops comps whose subdivision doesn't match (tier 3). `false` keeps them; same subdivision still ranks first | `false` |
| `subdivision_min_score` | Fuzzy similarity (0-100) needed to count as a possible match (tier 2, flagged for review) | `90` |
| `sale_date_max_months` | Sold comps closed longer ago than this, counted back from the subject's effective date, are excluded. Listings are not affected | `12` |
| `missing_close_date` | Sold comp with no usable close date: `exclude` or `keep_and_flag` | `exclude` |
| `required_features` | Exact values a comp must have. Works with standard fields or any CSV column | `{ foundation_type: "Crawl Space" }` |

### escalation
`steps` is a list of filter overrides. While there are fewer than `min_shortlist_size` sold candidates, the steps are applied one at a time, **cumulatively**: step 2 keeps step 1's change. The default order follows the rule "distance first, then GLA, then lookback":

```yaml
steps:
  - { max_distance_miles: 4.0 }
  - { max_distance_miles: 5.0 }
  - { gla_bracket_pct: 30 }
  - { sale_date_max_months: 24 }
```

Each step applied adds a `CRITERIA_RELAXED` flag, and the manifest lists every level tried with its sold/listing counts.

### selection
| Setting | Meaning | Example |
|---|---|---|
| `sold_count` / `listing_count` | The final pick | `5` sold + `1` listing |
| `bracket_attributes` | The subject needs at least one pick above and one below on each | `[gla, lot, age, beds, baths]` |
| `equal_counts_as_bracketed` | `true`: a pick equal to the subject counts as both above and below | `false` |

The top-ranked picks are taken first. If an attribute is not bracketed, lower-ranked sold comps from the shortlist are tried in place of the lowest-ranked sold picks; a swap is accepted only if it leaves strictly fewer unbracketed attributes (and adds none). The listing pick is not swapped. What can't be fixed gets a `NOT_BRACKETED` flag. Baths count as full + 0.5 x half.

### matching
| Setting | Meaning |
|---|---|
| `noise_words` | Words ignored when comparing subdivision names. `ESTATES` is not included by default, because "Oak Estates" and "Oak" may be different places. Add it only if you want it ignored |

Subdivision tiers: **0** same name after cleanup (case, "Ph"/"Phase", "II"/"2", punctuation), **1** listed in `subdivision_aliases.yaml`, **2** close spelling (flagged `SUBDIVISION_UNCERTAIN`), **3** different. If both names carry a phase, section or unit number and the numbers differ, the match is never tier 0 or 1.

### ranking
| Setting | Meaning |
|---|---|
| `hierarchy` | Priority order. Must contain each of `subdivision, distance, gla, age, lot, beds, baths` exactly once. Sold comps and listings are ranked separately with the same order |
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
| REVIEW | MISSING_REQUIRED_FIELD, INVALID_VALUE, NO_COORDINATES, SUBDIVISION_UNCERTAIN, POSSIBLE_NON_ARMS_LENGTH, REMARKS_CONCERN, LLM_SCHEMA_FAILURE, CRITERIA_RELAXED, NOT_BRACKETED, NO_LISTING_COMP |
| INFO | DUPLICATE_LISTING, STATUS_NOT_USED, LLM_UNKNOWN_ID, LLM_EVIDENCE_NOT_FOUND, LLM_DISALLOWED_REASON, LLM_UNAVAILABLE |

The dashboard's "Save as default" rewrites `settings.yaml` without these comments. The previous version is kept as `settings.yaml.bak`.
