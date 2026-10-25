# uad

## Purpose
Map the validated subject and shortlist into the UAD 3.6 Sales Comparison grid as strict JSON.

## Status
PLACEHOLDER, Phase 2.

Context: UAD 3.6 is mandatory for new appraisal reports submitted to the GSE portal (UCDP) on or after November 2, 2026. Official specs are published by Fannie Mae and Freddie Mac.

## Waiting on
Sam's UAD 3.6 field list and which fields are required for his reports.

## Planned design
- `uad/schema.py` with pydantic models mirroring the grid; every field is a Cell (value, source, flag).
- `uad/mapper.py` converts Comp -> GridRow.
- Hard facts come from MLS, then county.
- A required field with no source -> null + `MISSING_REQUIRED_FIELD`.
- Outputs `grid.json` and `alerts.json`.

## Interface
`build_grid(subject: Subject, comps: list[Comp], flags: list[Flag]) -> UadGrid`
