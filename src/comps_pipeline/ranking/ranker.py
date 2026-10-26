"""Deterministic ranking by the configured hierarchy with tolerance bands.

For each hierarchy key the comp gets a bucket floor(|value| / band); values in the same band
tie and the next key decides. Final tie-breakers: raw distance, raw |GLA diff %|, mls_number.
Missing values sort last within their key. Bucket math uses exact fractions.
Sold comps and active/option/pending listings are ranked separately (one call per pool).
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import (
    AuditEntry,
    Cell,
    Comp,
    Decision,
    Excluded,
    Flag,
    FlagReason,
    Source,
    Subject,
)

STAGE = "rank"
MISSING = (1, 0)  # sorts after every (0, value)


@dataclass
class RankOutput:
    ranked: list[Comp] = field(default_factory=list)
    shortlist: list[Comp] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


def _pct_diff(value: Fraction | int | None, base: Fraction | int | None) -> Fraction | None:
    """Signed percent difference vs the subject, exact."""
    if value is None or base is None:
        return None
    return Fraction(value - base) * 100 / base


def _diff(value: Fraction | int | None, base: Fraction | int | None) -> Fraction | None:
    return None if value is None or base is None else Fraction(value - base)


def subject_gaps(subject: Subject, settings: Settings) -> list[Flag]:
    """One flag per subject attribute the ranking (and bracketing) cannot use."""
    flags = []
    for name, value in (
        ("year_built", subject.year_built),
        ("lot_size", subject.lot_acres()),
        ("bedrooms", subject.bedrooms),
        ("baths", subject.total_baths()),
    ):
        if value is None:
            flags.append(
                settings.flag(
                    FlagReason.MISSING_REQUIRED_FIELD,
                    "SUBJECT",
                    f"subject {name} missing; every comp ties on that ranking key "
                    "and it cannot be bracketed",
                    name,
                )
            )
    return flags


def compute_metrics(
    comps: list[Comp], subject: Subject, settings: Settings
) -> tuple[list[Comp], list[Flag]]:
    """GLA / age / lot differences. Missing inputs -> null + flag (unless already flagged)."""
    flags: list[Flag] = []
    out = []
    for c in comps:
        gla = _pct_diff(c.living_area.value, subject.living_area)
        lot = _pct_diff(c.lot_acres(), subject.lot_acres())
        yb, syb = c.year_built.value, subject.year_built
        age = None if yb is None or syb is None else yb - syb
        update = {}
        for metric, source_field, value in (
            ("gla_diff_pct", "living_area", None if gla is None else float(gla)),
            ("age_diff_years", "year_built", age),
            ("lot_diff_pct", "lot_size_sqft", None if lot is None else float(lot)),
        ):
            if value is not None:
                update[metric] = Cell(value=value, source=Source.COMPUTED)
                continue
            src: Cell = getattr(c, source_field)
            note = f"{source_field} unknown; sorted last on this key"
            update[metric] = Cell(
                source=Source.NONE, flag=FlagReason.MISSING_REQUIRED_FIELD, note=note
            )
            if src.flag is None and src.value is None:  # not flagged by an earlier stage yet
                flags.append(
                    settings.flag(
                        FlagReason.MISSING_REQUIRED_FIELD, c.mls_number, note, source_field
                    )
                )
        out.append(c.model_copy(update=update))
    return out, flags


def _bucket(value: Fraction | int | None, band: float) -> tuple[int, int]:
    if value is None:
        return MISSING
    return (0, math.floor(abs(Fraction(value)) / Fraction(str(band))))


def _raw(value: float | None) -> tuple[int, float]:
    return (1, 0.0) if value is None else (0, abs(value))


def sort_key(c: Comp, subject: Subject, settings: Settings) -> tuple[Any, ...]:
    bands = settings.ranking.tolerance_bands
    tier = c.subdivision_tier.value
    distance = c.distance_miles.value
    buckets = {
        "subdivision": MISSING if tier is None else (0, tier),
        "distance": _bucket(None if distance is None else Fraction(distance), bands.distance_miles),
        "gla": _bucket(_pct_diff(c.living_area.value, subject.living_area), bands.gla_pct),
        "age": _bucket(c.age_diff_years.value, bands.age_years),
        "lot": _bucket(_pct_diff(c.lot_acres(), subject.lot_acres()), bands.lot_pct),
        "beds": _bucket(_diff(c.bedrooms.value, subject.bedrooms), bands.beds_count),
        "baths": _bucket(_diff(c.total_baths(), subject.total_baths()), bands.baths_count),
    }
    return (
        *(buckets[k] for k in settings.ranking.hierarchy),
        _raw(distance),
        _raw(c.gla_diff_pct.value),
        c.mls_number,
    )


def _top_exclusion_rule(prior_audit: list[AuditEntry]) -> tuple[str, int] | None:
    counts = Counter(a.rule for a in prior_audit if a.decision == Decision.EXCLUDED and a.rule)
    if not counts:
        return None
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))  # most rows, then name


def rank(
    comps: list[Comp],
    subject: Subject,
    settings: Settings,
    size: int,
    minimum: int = 0,
    pool: str = "sold",
    prior_audit: list[AuditEntry] | None = None,
) -> RankOutput:
    """Rank one pool; keep the top `size`; flag when fewer than `minimum` remain."""
    out = RankOutput()
    with_metrics, out.flags = compute_metrics(comps, subject, settings)
    keyed = [(sort_key(c, subject, settings), c) for c in with_metrics]
    keyed.sort(key=lambda kc: kc[0])  # stable sort; mls_number makes every key unique anyway
    for position, (key, c) in enumerate(keyed, start=1):
        stored = [list(k) if isinstance(k, tuple) else k for k in key]
        ranked = c.model_copy(update={"rank": position, "sort_key": stored})
        out.ranked.append(ranked)
        out.audit.append(
            AuditEntry(
                mls_number=c.mls_number,
                stage=STAGE,
                decision=Decision.RANKED,
                rule="hierarchy",
                detail={
                    "rank": position,
                    "sort_key": stored,
                    "pool": pool,
                    "hierarchy": settings.ranking.hierarchy,
                    "shortlisted": position <= size,
                },
            )
        )
        if position <= size:
            out.shortlist.append(ranked)
        else:
            out.excluded.append(
                Excluded(
                    c.source_row,
                    c.mls_number,
                    STAGE,
                    [f"RANK_BEYOND_SHORTLIST: {pool} rank {position} > shortlist size {size}"],
                )
            )

    if len(out.shortlist) < minimum:
        top = _top_exclusion_rule(prior_audit or [])
        culprit = f"; filter that excluded the most rows: {top[0]} ({top[1]} rows)" if top else ""
        msg = (
            f"{pool} shortlist has {len(out.shortlist)} comps after every escalation step, "
            f"minimum is {minimum}{culprit}"
        )
        out.flags.append(settings.flag(FlagReason.SHORTLIST_BELOW_MINIMUM, None, msg))
        out.audit.append(
            AuditEntry(
                mls_number=None,
                stage=STAGE,
                decision=Decision.FLAGGED,
                rule=FlagReason.SHORTLIST_BELOW_MINIMUM.value,
                detail={"message": msg, "top_exclusion_rule": top[0] if top else None},
            )
        )
    return out
