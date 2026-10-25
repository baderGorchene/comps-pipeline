# data

| Folder | Purpose | In git? |
|---|---|---|
| `input/` | Real client files: MLS exports and subject YAML | **No.** Ignored. Real client data is never committed |
| `samples/` | Synthetic CSV and subject from `scripts/generate_synthetic.py` (seed 42) | Yes |
| `output/` | One folder per run (`<run_id>/`) with shortlist, excluded, flags, audit, manifest | No |
| `cache/` | Cached LLM responses (JSON, keyed by model + prompt + payload hash) | No |

The synthetic sample contains planted edge cases on purpose: GLA exactly on both 30% boundaries and 1 sq ft beyond each, subdivision spelling variants (case, Ph/Phase, Roman numerals, a typo, a different phase), missing and zero GLA, missing coordinates, future and old close dates, duplicate MLS numbers, "$"-formatted prices, and remarks such as "estate sale" and "sold to family member".

Delete old run folders in `output/` whenever you like. The cache can also be cleared at any time.
