# condition

## Purpose
Produce condition evidence and material improvements from photos and text, and derive a C-rating with rules Sam approves. The AI observes; Python rates.

## Status
PLACEHOLDER, Phase 2.

## Waiting on
- Photo source.
- Sam's approval of `docs/condition_checklist_draft.md`.
- Calibration dataset.

## Planned design
- **Pass A:** Gemini fills a closed-value checklist (kitchen updated, visible wear, deferred maintenance, ...), each item citing the photo it is based on. Python rules in config convert the checklist to C1-C6.
- **Pass B:** Gemini rates condition directly on a DISJOINT photo subset (optionally a different model).
- **Text signal:** remarks + remodel year, no photos.
- **Decision rule (Python):**
  - all signals agree -> accept;
  - adjacent disagreement (e.g. C3 vs C4) -> null + `ADJACENT_DISAGREEMENT`;
  - spread of 2+ steps -> null + `CONFLICTING_EVIDENCE`;
  - key rooms missing from photos -> null + `INSUFFICIENT_EVIDENCE`.
- Model self-reported confidence is never trusted alone.
- **Materiality:** improvements limited to a closed list from Sam's rules; price-relative thresholds enforced in Python; anything notable outside the list -> flagged for review with a photo reference.
- All outputs pass the validation gate (cited photos must exist, values must be in allowed sets).

## Interface
`assess(comp: Comp, photos: list[Path]) -> ConditionResult(cell, evidence, flags)`
