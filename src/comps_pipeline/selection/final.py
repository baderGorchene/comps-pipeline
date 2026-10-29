"""Final pick: top sold comps + top listing(s), swapped until the subject is bracketed.

Bracketed on an attribute = at least one pick above the subject and one below (strictly,
unless selection.equal_counts_as_bracketed). Start from the top-ranked picks; while some
attribute is not bracketed, try the next-ranked sold candidates in place of the lowest-ranked
sold picks and accept the first swap whose remaining gaps are a strict subset of the current
ones. Gaps shrink on every swap, so the loop ends. The listing pick is never swapped.
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


@dataclass
class FinalSelection:
    picks: list[Comp] = field(default_factory=list)  # sold by rank, then listings by rank
    gaps: list[str] = field(default_factory=list)
    swaps: list[dict] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


def select_final(
    sold: list[Comp], listings: list[Comp], subject: Subject, settings: Settings
) -> FinalSelection:
    """sold / listings: each pool's shortlist in rank order."""
    sel = settings.selection
    out = FinalSelection()
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
    out.picks, out.gaps = chosen + fixed, current
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
            detail={"picks": [c.mls_number for c in out.picks], "not_bracketed": current},
        )
    )
    return out
