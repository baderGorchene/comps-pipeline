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
    attempts: list[dict] = []
    for level in range(len(steps) + 1):
        filters = settings.filters_at(level)
        out = apply_hard_filters(comps, subject, settings.model_copy(update={"filters": filters}))
        sold = sum(c.pool == "sold" for c in out.comps)
        attempts.append(
            {
                "level": level,
                "overrides": dict(steps[level - 1]) if level else {},
                "sold_kept": sold,
                "listing_kept": len(out.comps) - sold,
            }
        )
        if sold >= minimum:
            break
    for i, step in enumerate(steps[:level], start=1):
        msg = (
            f"step {i} applied {step}: fewer than {minimum} sold comps "
            f"({attempts[i - 1]['sold_kept']}) at the previous level"
        )
        out.flags.append(settings.flag(FlagReason.CRITERIA_RELAXED, None, msg))
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
