# Condition checklist (DRAFT, structure only)

This is the **structure** of the closed-value checklist the Phase 2 condition engine will fill (Pass A). It is not a rating method. Python rules in config will map answers to C1-C6 only after Sam approves them.

None of the definitions below are official. Every one is marked:
**TODO: verify against official UAD 3.6 documentation and confirm with Sam.**

## Checklist items

| Item | Allowed values | Required photo type | Definition |
|---|---|---|---|
| kitchen_updated | yes / no / unknown | Kitchen, wide view | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| kitchen_update_age | 0-5 yrs / 6-15 yrs / 15+ yrs / unknown | Kitchen, wide view | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| bathrooms_updated | yes / no / unknown | Each bathroom | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| flooring_condition | good / worn / damaged / unknown | Living areas, bedrooms | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| visible_wear | none / minor / significant / unknown | Any interior | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| deferred_maintenance | none / minor / significant / unknown | Exterior, roof, interior | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| structural_concern_visible | yes / no / unknown | Exterior, foundation, ceilings | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| roof_condition | good / worn / damaged / not visible | Exterior with roof | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| exterior_condition | good / worn / damaged / unknown | Front and rear exterior | TODO: verify against official UAD 3.6 documentation and confirm with Sam |
| new_construction_or_gut_rehab | yes / no / unknown | Kitchen, baths, exterior | TODO: verify against official UAD 3.6 documentation and confirm with Sam |

## Rules for every answer
- Each answer cites the photo(s) it is based on (file name). The validation gate checks that the cited photos exist.
- `unknown` is always allowed and preferred to a guess.
- Key rooms missing from the photos (kitchen, at least one bathroom, main living area, exterior) -> no rating, `INSUFFICIENT_EVIDENCE`.

## Open for Sam
- Which items to keep, add or remove.
- How the items map to C1-C6 (written as config rules, never code).
- Which improvements count as material (closed list) and any price-relative thresholds.
