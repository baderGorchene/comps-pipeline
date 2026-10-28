# data

| Folder | Purpose | In git? |
|---|---|---|
| `input/` | Real client files: MLS exports and subject YAML | **No.** Ignored. Real client data is never committed |
| `samples/` | Synthetic CSV and subject from `scripts/generate_synthetic.py` (seed 42) | Yes |
| `output/` | One folder per run (`<run_id>/`) with final selection, shortlist, excluded, flags, audit, manifest, log | No |

The synthetic sample contains planted edge cases on purpose: GLA exactly on both 25% boundaries and 1 sq ft beyond each, subdivision spelling variants (case, Ph/Phase, Roman numerals, a typo, a different phase), missing and zero GLA, missing coordinates, future and old close dates, duplicate MLS numbers, "$"-formatted prices, active/pending listings, and expired or blank statuses.

Delete old run folders in `output/` whenever you like. The Past runs page lists whatever is there.
