"""Relax the hard filters step by step while there are too few sold candidates.

Level 0 is the baseline in `filters`; level n applies the first n `escalation.steps`
cumulatively. The first level that keeps >= run.min_shortlist_size sold comps wins; if none
does, the last level is used and ranking raises SHORTLIST_BELOW_MINIMUM.
"""

from dataclasses import dataclass

from comps_pipeline.config.schema import Settings
from comps_pipeline.filters.hard_filters import apply_hard_filters
from comps_pipeline.models import AuditEntry, Comp, Decision, FlagReason, StageOutput, Subject

STAGE = "escalation"


@dataclass
class EscalationResult:
    out: StageOutput  # the chosen level's kept / excluded / audit, plus CRITERIA_RELAXED flags
    level: int
    attempts: list[dict]  # one summary per level tried, for the manifest


def filter_with_escalation(
    comps: list[Comp], subject: Subject, settings: Settings
) -> EscalationResult:
    steps = settings.escalation.steps
    minimum = settings.run.min_shortlist_size
    c1_mode = subject.is_new_construction
    attempts: list[dict] = []
    for level in range(len(steps) + 1):
        filters = settings.filters_at(level)
        out = apply_hard_filters(comps, subject, settings.model_copy(update={"filters": filters}))
        sold = sum(c.pool == "sold" for c in out.comps)
        attempt: dict = {
            "level": level,
            "overrides": dict(steps[level - 1]) if level else {},
            "sold_kept": sold,
            "listing_kept": len(out.comps) - sold,
        }

        c1_satisfied = True
        if c1_mode:
            in_s = sum(c.pool == "sold" and c.subdivision_tier.value in (0, 1) for c in out.comps)
            in_l = sum(c.pool == "listing" and c.subdivision_tier.value in (0, 1) for c in out.comps)
            out_s = sum(c.pool == "sold" and c.subdivision_tier.value not in (0, 1) for c in out.comps)
            out_l = sum(c.pool == "listing" and c.subdivision_tier.value not in (0, 1) for c in out.comps)
            attempt["c1_inside_sold"] = in_s
            attempt["c1_inside_listing"] = in_l
            attempt["c1_outside_sold"] = out_s
            attempt["c1_outside_listing"] = out_l
            # New Construction Subdivision Quota: >= 2 in-sub sold, >= 1 in-sub listing,
            # >= 1 out-of-sub sold, >= 1 out-of-sub listing
            if in_s < 2 or in_l < 1 or out_s < 1 or out_l < 1:
                c1_satisfied = False

        attempts.append(attempt)
        if sold >= minimum and (not c1_mode or c1_satisfied):
            break

    for i, step in enumerate(steps[:level], start=1):
        prev = attempts[i - 1]
        reasons: list[str] = []
        if prev["sold_kept"] < minimum:
            reasons.append(f"fewer than {minimum} sold comps ({prev['sold_kept']})")
        if c1_mode and not (
            prev.get("c1_inside_sold", 2) >= 2
            and prev.get("c1_inside_listing", 1) >= 1
            and prev.get("c1_outside_sold", 1) >= 1
            and prev.get("c1_outside_listing", 1) >= 1
        ):
            reasons.append("new construction subdivision quota not met")
        reason_str = " and ".join(reasons) if reasons else f"fewer than {minimum} sold comps ({prev['sold_kept']})"
        msg = f"step {i} applied {step}: {reason_str} at the previous level"
        out.flags.append(settings.flag(FlagReason.CRITERIA_RELAXED, None, msg))

    if c1_mode:
        final_in_s = sum(c.pool == "sold" and c.subdivision_tier.value in (0, 1) for c in out.comps)
        final_in_l = sum(c.pool == "listing" and c.subdivision_tier.value in (0, 1) for c in out.comps)
        final_out_s = sum(c.pool == "sold" and c.subdivision_tier.value not in (0, 1) for c in out.comps)
        final_out_l = sum(c.pool == "listing" and c.subdivision_tier.value not in (0, 1) for c in out.comps)
        deficits: list[str] = []
        if final_in_s < 2:
            deficits.append(f"in-subdivision sold ({final_in_s} < 2)")
        if final_in_l < 1:
            deficits.append(f"in-subdivision active/pending ({final_in_l} < 1)")
        if final_out_s < 1:
            deficits.append(f"out-of-subdivision sold ({final_out_s} < 1)")
        if final_out_l < 1:
            deficits.append(f"out-of-subdivision active/pending ({final_out_l} < 1)")
        if deficits:
            deficit_msg = (
                f"New construction subdivision quota deficit after escalation: {', '.join(deficits)}. "
                "Guidance requires at least 2 sold + 1 active in-subdivision and 1 sold + 1 active out-of-subdivision."
            )
            out.flags.append(settings.flag(FlagReason.NEW_CONST_SUBDIVISION_DEFICIT, None, deficit_msg))
            out.audit.append(
                AuditEntry(
                    mls_number=None,
                    stage=STAGE,
                    decision=Decision.FLAGGED,
                    rule=FlagReason.NEW_CONST_SUBDIVISION_DEFICIT.value,
                    detail={
                        "message": deficit_msg,
                        "inside_sold": final_in_s,
                        "inside_listing": final_in_l,
                        "outside_sold": final_out_s,
                        "outside_listing": final_out_l,
                    },
                )
            )

    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail={"level_used": level, "attempts": attempts, "filters": filters.model_dump()},
        )
    )
    return EscalationResult(out=out, level=level, attempts=attempts)
