# calibration

## Purpose
Measure the condition engine against Sam's own past ratings before he relies on it.

## Status
PLACEHOLDER, Phase 2.

## Waiting on
30-50 past comps with Sam's condition ratings and their listing photos.

## Planned design
- Run the engine on the set.
- Report confusion matrix C1-C6, auto-accept rate, flag rate, and agreement on accepted ratings.
- Tune checklist-to-rating rules in config, never in code.
- Re-run on every rules change as a regression test.
- Report as CSV + HTML.

## Interface
`evaluate(dataset_path: Path, config: Settings) -> CalibrationReport`
