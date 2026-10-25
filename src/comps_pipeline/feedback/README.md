# feedback

## Purpose
Record every override Sam makes in the dashboard to measure accuracy over time and build examples.

## Status
PLACEHOLDER, starts once Phase 1 is in real use.

## Waiting on
Phase 1 in real use.

## Planned design
- Append-only `overrides.jsonl` (run_id, mls_number, field, system value, Sam's value, reason, timestamp).
- Monthly accuracy stats.
- Optional, opt-in export of corrected cases as prompt examples.

## Interface
`record_override(...) -> None` ; `stats(period) -> FeedbackStats`
