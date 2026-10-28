# Open questions for Sam

| # | Question | Why it matters | Current default |
|---|---|---|---|
| 1 | Which MLS board do you export from? | Header names, date formats, data rules, photo access terms | Mapping covers common header names |
| 2 | Does your CSV include latitude/longitude, or always a Distance column? | How distance is measured | Coordinates if present, else the export's Distance column; neither -> excluded |
| 3 | Is the GLA bracket inclusive (exactly 25% off is kept)? | Boundary comps | Inclusive |
| 4 | Tie-break preferences after the hierarchy? | Order of near-identical comps | Exact distance, then exact GLA difference, then MLS number |
| 5 | Missing distance: exclude, or keep and flag? | Comps without coordinates | Exclude (`filters.missing_distance`) |
| 6 | Missing GLA: exclude, or keep and flag? | Comps without living area | Exclude (`filters.missing_gla`) |
| 10 | Which rules do you want to change per assignment? | Web rules form | GLA %, lot %, radius, months, relaxation steps, ranking order, final pick, status codes |
| 12 | Is the appraisal effective date the right reference for "future" and "12 months old"? | Date window | Yes, `effective_date` in the subject YAML |
| 13 | A close date after the effective date: pending sale or data error? | Currently set to null and flagged, row kept | Flag `INVALID_VALUE` |
| 14 | Duplicate MLS numbers: keep the first row, or the most recent? | Re-listed properties | Keep the first |
| 15 | Should ESTATES (and similar words) be ignored in subdivision names? | Matching | Not ignored |
| 16 | Which columns are truly required in your export? | Error vs warning | mls_number, status, living_area, subdivision (close price/date per sold row) |
| 17 | Does "shortlist of 20-30" mean sold comps only? | Escalation trigger | Yes: 20-30 sold; listings are a separate list of up to 10 |
| 18 | Should escalation steps add up (5 mi + 30% GLA + 24 months)? | Which comps appear in a thin market | Yes, cumulative |
| 19 | Same subdivision: preferred or required? | Comps from nearby subdivisions | Preferred (ranked first), not required |
| 20 | No active/option/pending comp available: block or flag? | Final 6 | REVIEW flag `NO_LISTING_COMP`, pick is 5 sold |
| 21 | Does a comp equal to the subject (same beds) count as bracketing? | Bracketing | No, one strictly above and one strictly below |
| 22 | May the listing pick be swapped to fix bracketing? | Final 6 | No, the best-ranked listing is always kept |
| 23 | Is "age" bracketing on year built? | Bracketing | Yes, one newer and one older |
| 24 | Which status codes does your MLS use (S, A, O, P, ...)? | Pools | `status.*` in settings.yaml |
