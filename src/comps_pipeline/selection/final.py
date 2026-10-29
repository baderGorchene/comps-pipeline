"""Final pick: top sold comps + top listing(s), swapped until the subject is bracketed.

Supports both:
- Standard Path (C2-C6): 5 Sold + 1 Active/Pending Listing (favoring Pending/Option).
- New Construction (C1) Path: 2 Sold + 1 Listing inside Subject's subdivision,
  1 Sold + 1 Listing from competing subdivisions ("outside"), plus 1 additional Sold.

Also generates:
- `selection_rationale` for every Final 6 pick (Table 1).
- `deselection_reason` (1-sentence UAD 3.6 "Analyzed, Not Used" audit log) for every
  shortlisted comp not chosen for the Final 6 (Table 2).
"""

from dataclasses import dataclass, field
from fractions import Fraction

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import AuditEntry, Comp, Decision, Flag, FlagReason, Subject

STAGE = "final_selection"


def comp_value(c: Comp, attr: str) -> Fraction | int | None:
    return {
        "gla": lambda: c.living_area.value,
        "lot": c.lot_acres,
        "age": lambda: c.year_built.value,  # newer/older than the subject
        "beds": lambda: c.bedrooms.value,
        "baths": c.total_baths,
    }[attr]()


def subject_value(s: Subject, attr: str) -> Fraction | int | None:
    return {
        "gla": lambda: s.living_area,
        "lot": s.lot_acres,
        "age": lambda: s.year_built,
        "beds": lambda: s.bedrooms,
        "baths": s.total_baths,
    }[attr]()


def gaps(picks: list[Comp], subject: Subject, settings: Settings) -> list[str]:
    """Attributes (in config order) the picks do not bracket. Unknown values don't count."""
    sel = settings.selection
    missing = []
    for attr in sel.bracket_attributes:
        target = subject_value(subject, attr)
        if target is None:
            continue  # flagged once by ranking.subject_gaps
        values = [v for v in (comp_value(c, attr) for c in picks) if v is not None]
        eq = sel.equal_counts_as_bracketed
        above = any(v > target or (eq and v == target) for v in values)
        below = any(v < target or (eq and v == target) for v in values)
        if not (above and below):
            missing.append(attr)
    return missing


def _bracketed_contributions(comp: Comp, subject: Subject, attrs: list[str]) -> list[str]:
    """Describe which subject attributes this comp brackets above/below/equal."""
    notes: list[str] = []
    labels = {"gla": "GLA", "lot": "Lot", "age": "Year Built", "beds": "Beds", "baths": "Baths"}
    for attr in attrs:
        target = subject_value(subject, attr)
        val = comp_value(comp, attr)
        if target is None or val is None:
            continue
        lbl = labels.get(attr, attr)
        if val > target:
            notes.append(f"brackets {lbl} above")
        elif val < target:
            notes.append(f"brackets {lbl} below")
    return notes


def _build_selection_rationale(
    comp: Comp,
    subject: Subject,
    settings: Settings,
    swapped_in_for: dict[str, list[str]],
    c1_mode: bool,
) -> str:
    tier = comp.subdivision_tier.value
    sub_desc = (
        "Exact subdivision match"
        if tier in (0, 1)
        else "Fuzzy subdivision match"
        if tier == 2
        else "Competing outside subdivision"
    )
    dist = comp.distance_miles.value
    dist_desc = f"{dist:.2f} mi" if dist is not None else "distance N/A"
    gla_pct = comp.gla_diff_pct.value
    gla_desc = f"{gla_pct:+.1f}% GLA" if gla_pct is not None else "GLA N/A"
    pool_label = (
        "Closed Sale"
        if comp.pool == "sold"
        else f"Active/Pending Listing ({comp.status.value or 'Listing'})"
    )
    base = f"Rank #{comp.rank} {pool_label} ({sub_desc}, {dist_desc}, {gla_desc})"
    if c1_mode:
        loc_tag = (
            "in-subdivision builder/resale comp"
            if tier in (0, 1)
            else "competing subdivision outside comp (C1 requirement)"
        )
        base += f"; fulfills New Construction C1 {loc_tag}"
    if comp.mls_number in swapped_in_for:
        fixed = ", ".join(swapped_in_for[comp.mls_number])
        base += f"; swapped into Final 6 specifically to bracket {fixed}"
    else:
        contribs = _bracketed_contributions(comp, subject, settings.selection.bracket_attributes)
        if contribs:
            base += f"; {', '.join(contribs[:3])}"
    return base + "."


def _build_deselection_reason(
    comp: Comp,
    final_picks: list[Comp],
    swapped_out: set[str],
    remaining_gaps: list[str],
) -> str:
    """1-sentence UAD 3.6 'Analyzed, Not Used' explanation for why a shortlisted comp was unused."""
    dist = comp.distance_miles.value
    dist_str = f"{dist:.2f} mi" if dist is not None else "distance N/A"
    gla_pct = comp.gla_diff_pct.value
    gla_str = f"{gla_pct:+.1f}% GLA" if gla_pct is not None else "GLA N/A"
    tier = comp.subdivision_tier.value
    sub_str = "same subdivision" if tier in (0, 1) else f"subdivision tier {tier}"
    pool_name = "sold" if comp.pool == "sold" else "active/pending"

    if comp.mls_number in swapped_out:
        return (
            f"Ranked #{comp.rank} in {pool_name} shortlist ({sub_str}, {dist_str}, {gla_str}), "
            "but was swapped out of the initial top picks so a lower-ranked candidate could "
            "bracket a missing subject attribute."
        )
    if comp.pool == "listing":
        top_listing_mls = next(
            (p.mls_number for p in final_picks if p.pool == "listing"), "top listing"
        )
        return (
            f"Ranked #{comp.rank} in active/pending shortlist ({sub_str}, {dist_str}, {gla_str}); "
            "passed all eligibility filters but outranked by higher-priority listing "
            f"{top_listing_mls} for the active/pending slot."
        )
    gap_clause = (
        "did not resolve the remaining unbracketed attribute(s) without opening a new gap"
        if remaining_gaps
        else "all subject bracketing requirements were already satisfied by higher-ranked comps"
    )
    return (
        f"Ranked #{comp.rank} in sold shortlist ({sub_str}, {dist_str}, {gla_str}); "
        "passed all baseline/escalated filters but outranked by closer comparables in the "
        f"top picks and {gap_clause}."
    )


@dataclass
class FinalSelection:
    picks: list[Comp] = field(default_factory=list)  # sold by rank, then listings by rank
    analyzed_not_used: list[Comp] = field(default_factory=list)  # UAD 3.6 Table 2 comps
    gaps: list[str] = field(default_factory=list)
    swaps: list[dict] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


def _select_c1_new_construction(
    sold: list[Comp], listings: list[Comp], sel_sold_count: int
) -> tuple[list[Comp], list[Comp]]:
    """Step 5 Master Guidance New Construction (C1) Path:
    - 2 Sold + 1 Listing from Subject's exact subdivision (tier 0 or 1)
    - 1 Sold + 1 Listing from competing subdivisions (tier >= 2)
    - 1 additional Sold from either (total 4 Sold + 2 Listings = 6 Comps, or fallback).
    """
    inside_sold = [c for c in sold if c.subdivision_tier.value in (0, 1)]
    outside_sold = [c for c in sold if c.subdivision_tier.value not in (0, 1)]
    inside_list = [c for c in listings if c.subdivision_tier.value in (0, 1)]
    outside_list = [c for c in listings if c.subdivision_tier.value not in (0, 1)]

    chosen_list: list[Comp] = []
    if inside_list:
        chosen_list.append(inside_list[0])
    if outside_list:
        chosen_list.append(outside_list[0])
    # Fill up to 2 listings if available, else whatever is available
    for c in listings:
        if len(chosen_list) >= 2:
            break
        if c.mls_number not in {x.mls_number for x in chosen_list}:
            chosen_list.append(c)

    target_total = sel_sold_count + 1  # typically 6 total comps
    target_sold = max(1, target_total - len(chosen_list))

    chosen_sold: list[Comp] = []
    for c in inside_sold[:2]:
        chosen_sold.append(c)
    for c in outside_sold[:1]:
        if len(chosen_sold) < target_sold:
            chosen_sold.append(c)
    for c in sold:
        if len(chosen_sold) >= target_sold:
            break
        if c.mls_number not in {x.mls_number for x in chosen_sold}:
            chosen_sold.append(c)

    chosen_sold.sort(key=lambda c: c.rank or 0)
    chosen_list.sort(key=lambda c: c.rank or 0)
    return chosen_sold, chosen_list


def select_final(
    sold: list[Comp], listings: list[Comp], subject: Subject, settings: Settings
) -> FinalSelection:
    """sold / listings: each pool's shortlist in rank order."""
    sel = settings.selection
    out = FinalSelection()
    c1_mode = subject.construction_status == "new_construction"

    if c1_mode and (len(sold) + len(listings) > 0):
        chosen, fixed = _select_c1_new_construction(sold, listings, sel.sold_count)
    else:
        chosen = list(sold[: sel.sold_count])
        fixed = list(listings[: sel.listing_count])

    current = gaps(chosen + fixed, subject, settings)

    improved = True
    while current and improved:
        improved = False
        taken = {c.mls_number for c in chosen}
        candidates = [c for c in sold if c.mls_number not in taken]
        for cand in candidates:
            for i in range(len(chosen) - 1, -1, -1):  # lowest-ranked pick first
                trial = chosen[:i] + [cand] + chosen[i + 1 :]
                new = gaps(trial + fixed, subject, settings)
                if set(new) < set(current):
                    out.swaps.append(
                        {
                            "removed": chosen[i].mls_number,
                            "added": cand.mls_number,
                            "gaps_before": current,
                            "gaps_after": new,
                        }
                    )
                    chosen, current, improved = trial, new, True
                    chosen.sort(key=lambda c: c.rank or 0)
                    break
            if improved:
                break

    chosen.sort(key=lambda c: c.rank or 0)

    # Annotate selection_rationale on Final 6 picks
    swapped_in_for: dict[str, list[str]] = {}
    swapped_out: set[str] = set()
    for sw in out.swaps:
        fixed_attrs = [g for g in sw["gaps_before"] if g not in sw["gaps_after"]]
        swapped_in_for[sw["added"]] = fixed_attrs
        swapped_out.add(sw["removed"])

    raw_picks = chosen + fixed
    annotated_picks = [
        c.model_copy(
            update={
                "selection_rationale": _build_selection_rationale(
                    c, subject, settings, swapped_in_for, c1_mode
                )
            }
        )
        for c in raw_picks
    ]
    picked_mls = {c.mls_number for c in annotated_picks}

    # Build Table 2: UAD 3.6 "Analyzed, Not Used" shortlist audit log
    analyzed_not_used: list[Comp] = []
    for c in [*sold, *listings]:
        if c.mls_number not in picked_mls:
            reason = _build_deselection_reason(c, annotated_picks, swapped_out, current)
            analyzed_not_used.append(c.model_copy(update={"deselection_reason": reason}))

    out.picks, out.analyzed_not_used, out.gaps = annotated_picks, analyzed_not_used, current
    for attr in current:
        msg = f"no pick both above and below the subject on {attr} (picks cannot bracket it)"
        out.flags.append(settings.flag(FlagReason.NOT_BRACKETED, None, msg, attr))
    if len(fixed) < sel.listing_count:
        msg = f"{len(fixed)} active/option/pending comps available, {sel.listing_count} wanted"
        out.flags.append(settings.flag(FlagReason.NO_LISTING_COMP, None, msg))
    for s in out.swaps:
        out.audit.append(
            AuditEntry(
                mls_number=s["added"], stage=STAGE, decision=Decision.KEPT, rule="swap", detail=s
            )
        )
    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail={
                "picks": [c.mls_number for c in out.picks],
                "analyzed_not_used_count": len(out.analyzed_not_used),
                "not_bracketed": current,
                "construction_mode": subject.construction_status,
            },
        )
    )
    return out
