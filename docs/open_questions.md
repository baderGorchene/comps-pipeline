# Open questions for Sam

| # | Question | Why it matters | Current default |
|---|---|---|---|
| 1 | Which MLS board do you export from? | Header names, date formats, data rules, photo access terms | Mapping covers common header names |
| 2 | Does your CSV include latitude/longitude? | Without them, distance needs geocoding (Phase 1.x) | Missing coordinates -> `NO_COORDINATES`, excluded |
| 3 | Is the GLA bracket inclusive (exactly 30% off is kept)? | Boundary comps | Inclusive |
| 4 | Tie-break preferences after the hierarchy? | Order of near-identical comps | Exact distance, then exact GLA difference, then MLS number |
| 5 | Missing distance: exclude, or keep and flag? | Comps without coordinates | Exclude (`filters.missing_distance`) |
| 6 | Missing GLA: exclude, or keep and flag? | Comps without living area | Exclude (`filters.missing_gla`) |
| 7 | What counts as material (improvements, concessions)? | Condition engine, remarks flags | Not implemented (Phase 2) |
| 8 | Photo source, and does your MLS agreement permit it? | Phase 2 photos | Nothing built (see `photos/README.md`) |
| 9 | Your UAD 3.6 field list, and which fields are required for your reports? | Phase 2 grid | Not implemented (see `uad36_notes.md`) |
| 10 | Which parameters do you want to change per assignment (dynamic list)? | Dashboard sidebar | GLA %, radius, subdivision rules, hierarchy, bands, shortlist size, LLM mode |
| 11 | A calibration set: 30-50 past comps with your condition ratings and photos | Measure the condition engine before relying on it | Waiting |
| 12 | Is the appraisal effective date the right reference for "future" and "12 months old"? | Date window | Yes, `effective_date` in the subject YAML |
| 13 | A close date after the effective date: pending sale or data error? | Currently set to null and flagged, row kept | Flag `INVALID_VALUE` |
| 14 | Duplicate MLS numbers: keep the first row, or the most recent? | Re-listed properties | Keep the first |
| 15 | Should ESTATES (and similar words) be ignored in subdivision names? | Matching | Not ignored |
| 16 | Which columns are truly required in your export? | Error vs warning | mls_number, close_price, close_date, living_area, subdivision |
