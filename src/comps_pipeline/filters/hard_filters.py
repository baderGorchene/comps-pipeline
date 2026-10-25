"""Hard filters. Each is a pure function: (comps, subject, settings) -> kept + audit entries.

apply_hard_filters runs every filter on the same input so the audit records every rule a
row fails, not only the first one.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import AuditEntry, Comp, Decision, Excluded, StageOutput, Subject
from comps_pipeline.models.comp import STANDARD_FIELDS

STAGE = "hard_filters"


@dataclass
class FilterResult:
    kept: list[Comp] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


def _entry(comp: Comp, decision: Decision, rule: str, message: str, **detail: Any) -> AuditEntry:
    return AuditEntry(
        mls_number=comp.mls_number,
        stage=STAGE,
        decision=decision,
        rule=rule,
        detail={"message": message, **detail},
    )


def gla_in_bracket(living_area: int, subject_gla: int, pct: int, inclusive: bool) -> bool:
    """Integer math only: no float rounding at the exact boundary."""
    low, high = subject_gla * (100 - pct), subject_gla * (100 + pct)
    scaled = living_area * 100
    return low <= scaled <= high if inclusive else low < scaled < high


def gla_filter(comps: list[Comp], subject: Subject, settings: Settings) -> FilterResult:
    rule, f, res = "gla_bracket", settings.filters, FilterResult()
    for c in comps:
        gla = c.living_area.value
        if gla is None:
            if f.missing_gla == "exclude":
                res.audit.append(_entry(c, Decision.EXCLUDED, rule, "living_area unknown"))
            else:
                res.kept.append(c)
                res.audit.append(_entry(c, Decision.FLAGGED, rule, "living_area unknown, kept"))
        elif gla_in_bracket(gla, subject.living_area, f.gla_bracket_pct, f.gla_bracket_inclusive):
            res.kept.append(c)
        else:
            op = "inclusive" if f.gla_bracket_inclusive else "exclusive"
            msg = (
                f"living_area {gla} outside +/-{f.gla_bracket_pct}% ({op}) "
                f"of subject {subject.living_area}"
            )
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg, living_area=gla))
    return res


def distance_filter(comps: list[Comp], subject: Subject, settings: Settings) -> FilterResult:
    rule, f, res = "max_distance", settings.filters, FilterResult()
    for c in comps:
        d = c.distance_miles.value
        if d is None:
            if f.missing_distance == "exclude":
                res.audit.append(_entry(c, Decision.EXCLUDED, rule, "distance unknown"))
            else:
                res.kept.append(c)
                res.audit.append(_entry(c, Decision.FLAGGED, rule, "distance unknown, kept"))
        elif d <= f.max_distance_miles:
            res.kept.append(c)
        else:
            msg = f"{d:.3f} mi is beyond {f.max_distance_miles} mi"
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg, distance_miles=d))
    return res


def subdivision_filter(comps: list[Comp], subject: Subject, settings: Settings) -> FilterResult:
    """Needs subdivision matching to have set subdivision_tier (see matching/subdivision.py)."""
    rule, res = "subdivision_match", FilterResult()
    if not settings.filters.require_subdivision_match:
        return FilterResult(kept=list(comps))
    for c in comps:
        tier = c.subdivision_tier.value
        if tier is not None and tier <= 2:
            res.kept.append(c)
        else:
            msg = (
                "subdivision unknown"
                if tier is None
                else f"subdivision {c.subdivision_raw.value!r} does not match "
                f"{subject.subdivision!r} (score {c.subdivision_score.value})"
            )
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg, tier=tier))
    return res


def feature_value(comp: Comp, name: str) -> Any:
    if name in STANDARD_FIELDS:
        return getattr(comp, name).value if name != "mls_number" else comp.mls_number
    for key, value in comp.extras.items():
        if key.strip().casefold() == name.strip().casefold():
            return value or None
    return None


def required_features_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    rule, required, res = "required_features", settings.filters.required_features, FilterResult()
    for c in comps:
        failures = []
        for name, wanted in required.items():
            actual = feature_value(c, name)
            if actual is None or str(actual).strip().casefold() != wanted.strip().casefold():
                failures.append(f"{name}={actual!r}, required {wanted!r}")
        if failures:
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, "; ".join(failures)))
        else:
            res.kept.append(c)
    return res


FILTERS: tuple[Callable[[list[Comp], Subject, Settings], FilterResult], ...] = (
    gla_filter,
    distance_filter,
    subdivision_filter,
    required_features_filter,
)


def apply_hard_filters(comps: list[Comp], subject: Subject, settings: Settings) -> StageOutput:
    out = StageOutput()
    failures: dict[str, list[str]] = {}
    for fn in FILTERS:
        res = fn(comps, subject, settings)
        out.audit.extend(res.audit)
        for a in res.audit:
            if a.decision == Decision.EXCLUDED and a.mls_number is not None:
                failures.setdefault(a.mls_number, []).append(f"{a.rule}: {a.detail['message']}")
    for c in comps:
        if c.mls_number in failures:
            out.excluded.append(Excluded(c.source_row, c.mls_number, STAGE, failures[c.mls_number]))
        else:
            out.comps.append(c)
    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail={"rows_in": len(comps), "kept": len(out.comps), "excluded": len(out.excluded)},
        )
    )
    return out
