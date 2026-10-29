"""Hard filters. Each is a pure function: (comps, subject, settings) -> kept + audit entries.

apply_hard_filters runs every filter on the same input so the audit records every rule a
row fails, not only the first one.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from comps_pipeline.config.schema import Settings
from comps_pipeline.ingest.cleaner import months_before
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


def lot_in_bracket(
    comp_acres: Fraction, subject_acres: Fraction, pct: int, inclusive: bool
) -> bool:
    """Exact fractions: no float rounding at the boundary."""
    low, high = subject_acres * (100 - pct), subject_acres * (100 + pct)
    scaled = comp_acres * 100
    return low <= scaled <= high if inclusive else low < scaled < high


def lot_filter(comps: list[Comp], subject: Subject, settings: Settings) -> FilterResult:
    rule, f = "lot_bracket", settings.filters
    subject_acres = subject.lot_acres()
    if subject_acres is None:  # nothing to compare against; flagged at selection
        return FilterResult(kept=list(comps))
    res = FilterResult()
    for c in comps:
        acres = c.lot_acres()
        if acres is None:
            if f.missing_lot == "exclude":
                res.audit.append(_entry(c, Decision.EXCLUDED, rule, "lot size unknown"))
            else:
                res.kept.append(c)
                res.audit.append(_entry(c, Decision.FLAGGED, rule, "lot size unknown, kept"))
        elif lot_in_bracket(acres, subject_acres, f.lot_bracket_pct, f.lot_bracket_inclusive):
            res.kept.append(c)
        else:
            op = "inclusive" if f.lot_bracket_inclusive else "exclusive"
            msg = (
                f"lot {float(acres):.4f} ac outside +/-{f.lot_bracket_pct}% ({op}) "
                f"of subject {float(subject_acres):.4f} ac"
            )
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg, lot_acres=float(acres)))
    return res


def sale_date_filter(comps: list[Comp], subject: Subject, settings: Settings) -> FilterResult:
    """Sold pool only: listings have no close date and are always current."""
    rule, f, res = "sale_date_window", settings.filters, FilterResult()
    cutoff = months_before(subject.effective_date, f.sale_date_max_months)
    for c in comps:
        close = c.close_date.value
        if c.pool != "sold":
            res.kept.append(c)
        elif close is None:
            if f.missing_close_date == "exclude":
                res.audit.append(_entry(c, Decision.EXCLUDED, rule, "close date unknown"))
            else:
                res.kept.append(c)
                res.audit.append(_entry(c, Decision.FLAGGED, rule, "close date unknown, kept"))
        elif close >= cutoff:
            res.kept.append(c)
        else:
            msg = (
                f"closed {close}, before cutoff {cutoff} "
                f"({f.sale_date_max_months} months before {subject.effective_date})"
            )
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg, close_date=str(close)))
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


def _is_truthy(val: str) -> bool:
    return val.strip().casefold() in {"y", "yes", "true", "1"}


def distressed_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    """Step 2 Master Guidance: Exclude REO, Short Sale, Foreclosure, Relocation, or fixers."""
    if not settings.filters.exclude_distressed:
        return FilterResult(kept=list(comps))
    rule, res = "distressed_sale", FilterResult()
    for c in comps:
        reasons: list[str] = []
        reo_val = c.extra_str("REO", "Bank Owned", "Foreclosure", "REO Y/N", "REO/Bank Owned")
        if _is_truthy(reo_val):
            reasons.append("REO/Bank Owned=Yes")
        if _is_truthy(c.extra_str("Short Sale", "ShortSale", "Short Sale Y/N")):
            reasons.append("Short Sale=Yes")
        fin = c.extra_str("Financing", "Buyer Financing", "Sale Terms", "Terms").casefold()
        if any(bad in fin for bad in ("foreclos", "reo", "relocation", "short sale")):
            reasons.append(f"Financing={fin!r}")
        nlp_distressed = c.remarks_signals.get("_distressed_remarks") or c.extras.get(
            "_distressed_remarks"
        )
        if nlp_distressed:
            reasons.append(f"remarks indicate distressed/uninhabitable ({nlp_distressed})")
        if reasons:
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, "; ".join(reasons)))
        else:
            res.kept.append(c)
    return res


def age_restriction_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    """Step 2 Master Guidance: Separate 55+ age-restricted communities from non-restricted."""
    if not settings.filters.enforce_55_plus:
        return FilterResult(kept=list(comps))
    rule, res = "age_restriction_55_plus", FilterResult()
    for c in comps:
        comp_55 = bool(c.remarks_signals.get("_is_55_plus") or c.extras.get("_is_55_plus"))
        if not subject.is_55_plus and comp_55:
            msg = "55+ age-restricted property excluded for standard subject"
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg))
        elif subject.is_55_plus and not comp_55 and c.public_remarks.value:
            msg = "non-55+ property excluded for 55+ age-restricted subject"
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, msg))
        else:
            res.kept.append(c)
    return res


def _normalize_sub_type(raw: str) -> str:
    s = raw.strip().casefold()
    sfr_names = {
        "r",
        "res",
        "residential",
        "sfr",
        "single family",
        "single family residence",
        "detached",
    }
    if s in sfr_names:
        return "single_family"
    if any(k in s for k in ("mobile", "manufactured", "modular")):
        return "manufactured"
    if any(k in s for k in ("condo", "condominium", "townhouse", "townhome")):
        return "attached"
    return s


def sub_type_and_story_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    """Step 2 Master Guidance: Enforce Property Sub-Type and Story Count matching when present."""
    rule, f, res = "sub_type_and_stories", settings.filters, FilterResult()
    subj_type = (
        _normalize_sub_type(subject.property_sub_type) if subject.property_sub_type else None
    )
    subj_stories = subject.stories
    for c in comps:
        reasons: list[str] = []
        raw_type = c.extra_str(
            "Property Sub-Type", "Property Sub Type", "PropertySubType", "Sub-Type", "PT"
        )
        if f.require_sub_type_match and raw_type:
            comp_type = _normalize_sub_type(raw_type)
            if comp_type == "manufactured" and (subj_type in (None, "single_family")):
                reasons.append(
                    f"manufactured/mobile home ({raw_type!r}) incompatible with site-built SFR"
                )
            elif subj_type and comp_type != subj_type:
                reasons.append(
                    f"property sub-type {raw_type!r} != subject {subject.property_sub_type!r}"
                )
        raw_stories = c.extra_str("# Stories", "Stories", "Levels", "Story Count", "StoriesTotal")
        if f.require_story_match and subj_stories is not None and raw_stories:
            try:
                comp_stories = float(raw_stories.split()[0])
                if abs(comp_stories - subj_stories) >= 0.5:
                    reasons.append(
                        f"stories {comp_stories:g} != subject stories {subj_stories:g}"
                    )
            except ValueError:
                pass
        if reasons:
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, "; ".join(reasons)))
        else:
            res.kept.append(c)
    return res


def foundation_compatibility_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    """Step 2 Master Guidance: If subject is Slab, exclude Crawl Space / Pier & Beam comps."""
    if not settings.filters.enforce_foundation_compatibility or not subject.foundation_type:
        return FilterResult(kept=list(comps))
    rule, res = "foundation_compatibility", FilterResult()
    subj_f = subject.foundation_type.strip().casefold()
    elevated_keywords = ("crawl", "pier", "beam", "piling", "stilts", "elevated")
    subj_is_slab = "slab" in subj_f and not any(k in subj_f for k in elevated_keywords)
    for c in comps:
        comp_f = (c.foundation_type.value or "").strip().casefold()
        if not comp_f:
            res.kept.append(c)
            continue
        comp_is_elevated = any(k in comp_f for k in elevated_keywords) and "slab" not in comp_f
        if subj_is_slab and comp_is_elevated:
            res.audit.append(
                _entry(
                    c,
                    Decision.EXCLUDED,
                    rule,
                    f"foundation {c.foundation_type.value!r} incompatible with Slab subject",
                )
            )
        else:
            res.kept.append(c)
    return res


def _core_isd(raw: str) -> str:
    return (
        raw.casefold()
        .replace("cisd", "")
        .replace("isd", "")
        .replace("school district", "")
        .strip()
    )


def school_and_utility_guardrail_filter(
    comps: list[Comp], subject: Subject, settings: Settings
) -> FilterResult:
    """Step 4 & 6 Master Guidance: School District (ISD) & Utility (Sewer vs Septic) guardrails."""
    rule, f, res = "market_guardrails", settings.filters, FilterResult()
    subj_isd = (subject.school_district or "").strip()
    subj_util = (subject.water_sewer or "").strip().casefold()
    for c in comps:
        reasons: list[str] = []
        if f.require_school_district_match and subj_isd:
            comp_isd = c.extra_str(
                "School District", "ISD", "SchoolDistrict", "High School District", "_extracted_isd"
            ).strip()
            if comp_isd:
                norm_s, norm_c = _core_isd(subj_isd), _core_isd(comp_isd)
                if norm_s and norm_c and norm_s != norm_c:
                    reasons.append(
                        f"school district {comp_isd!r} != subject {subject.school_district!r}"
                    )
        if f.require_water_sewer_match and subj_util:
            comp_util = c.extra_str("Water Sewer", "Water/Sewer", "Utilities", "Sewer").casefold()
            if comp_util:
                subj_septic = "septic" in subj_util
                comp_septic = "septic" in comp_util
                if subj_septic != comp_septic:
                    reasons.append(
                        f"utility {comp_util!r} conflicts with subject {subject.water_sewer!r}"
                    )
        if c.pool == "listing":
            raw_dom = c.extra_str("DOM", "Days On Market", "DaysOnMarket", "CDOM")
            status_val = (c.status.value or "").strip().upper()
            if status_val in {"A", "ACTIVE"} and raw_dom:
                try:
                    dom = int(float(raw_dom.replace(",", "").strip()))
                    if dom > f.max_active_dom:
                        reasons.append(
                            f"stale active listing DOM {dom} > max {f.max_active_dom} days"
                        )
                except ValueError:
                    pass
        if reasons:
            res.audit.append(_entry(c, Decision.EXCLUDED, rule, "; ".join(reasons)))
        else:
            res.kept.append(c)
    return res


FILTERS: tuple[Callable[[list[Comp], Subject, Settings], FilterResult], ...] = (
    sale_date_filter,
    gla_filter,
    lot_filter,
    distance_filter,
    subdivision_filter,
    required_features_filter,
    distressed_filter,
    age_restriction_filter,
    sub_type_and_story_filter,
    foundation_compatibility_filter,
    school_and_utility_guardrail_filter,
)


def apply_hard_filters(comps: list[Comp], subject: Subject, settings: Settings) -> StageOutput:
    out = StageOutput()
    failures: dict[str, list[str]] = {}
    raw_audit: list[AuditEntry] = []
    for fn in FILTERS:
        res = fn(comps, subject, settings)
        raw_audit.extend(res.audit)
        for a in res.audit:
            if a.decision == Decision.EXCLUDED and a.mls_number is not None:
                failures.setdefault(a.mls_number, []).append(f"{a.rule}: {a.detail['message']}")
    out.audit.extend(
        a for a in raw_audit if a.decision != Decision.FLAGGED or a.mls_number not in failures
    )
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
