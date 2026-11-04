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
    subj_lot = subject.lot_acres()
    for c in comps:
        gla = _pct_diff(c.living_area.value, subject.living_area)
        comp_lot = c.lot_acres()
        lot = _pct_diff(comp_lot, subj_lot)
        yb, syb = c.year_built.value, subject.year_built
        age = None if yb is None or syb is None else yb - syb
        update = {}
        for metric, source_field, value, comp_missing, already_flagged in (
            (
                "gla_diff_pct",
                "living_area",
                None if gla is None else float(gla),
                c.living_area.value is None,
                c.living_area.flag is not None,
            ),
            (
                "age_diff_years",
                "year_built",
                age,
                yb is None,
                c.year_built.flag is not None,
            ),
            (
                "lot_diff_pct",
                "lot_size_sqft",
                None if lot is None else float(lot),
                comp_lot is None,
                bool(c.lot_size_sqft.flag or c.lot_size_acres.flag),
            ),
        ):
            if value is not None:
                update[metric] = Cell(value=value, source=Source.COMPUTED)
            elif not comp_missing:
                update[metric] = Cell(note=f"subject {source_field} unknown; tied on this key")
            else:
                note = f"{source_field} unknown; sorted last on this key"
                update[metric] = Cell(
                    source=Source.NONE, flag=FlagReason.MISSING_REQUIRED_FIELD, note=note
                )
                if not already_flagged:
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


def _listing_status_priority(c: Comp) -> int:
    """Step 1 Master Guidance: In Pool B (listing), prioritize Pending/Option over Active."""
    if c.pool != "listing":
        return 0
    s = (c.status.value or "").strip().upper()
    pending_codes = {
        "P",
        "PENDING",
        "O",
        "OPTION",
        "OPTION PENDING",
        "AC",
        "ACTIVE CONTINGENT",
        "ACTIVE UNDER CONTRACT",
    }
    if s in pending_codes:
        return 0
    return 1


def _financing_priority(c: Comp) -> int:
    """Step 2 Master Guidance: Deprioritize Seller / Owner Financing behind Conventional/FHA/VA."""
    fin = c.extra_str("Financing", "Buyer Financing", "Sale Terms", "Terms").casefold()
    if any(k in fin for k in ("owner", "seller", "wrap", "contract for deed")):
        return 1
    return 0


def _contract_price_bucket(c: Comp, subject: Subject) -> tuple[int, int]:
    """Step 0 Master Guidance: When Purchase contract_price is set, rank by 5% price bands."""
    if subject.transaction_type != "purchase" or not subject.contract_price:
        return (0, 0)
    price = c.close_price.value or c.list_price.value
    if price is None:
        return MISSING
    pct = _pct_diff(price, subject.contract_price)
    return _bucket(pct, 5.0)


def _pool_priority(c: Comp, subject: Subject) -> int:
    """Prioritize comps matching the subject's pool status when specified."""
    if subject.pool is None:
        return 0
    p = c.extra_str("Poolyn", "Pool", "Pool Y/N", "Pool Private YN", "Private Pool")
    if not p:
        return 1
    has_pool = p.strip().casefold() in {"yes", "y", "true", "1"}
    return 0 if has_pool == subject.pool else 1


def _adu_priority(c: Comp, subject: Subject) -> int:
    """Prioritize comps matching the subject's ADU status when specified."""
    if subject.has_adu is None:
        return 0
    comp_has_adu = bool(c.remarks_signals.get("_has_adu") or c.extras.get("_has_adu"))
    return 0 if comp_has_adu == subject.has_adu else 1


def sort_key(c: Comp, subject: Subject, settings: Settings) -> tuple[Any, ...]:
    bands = settings.ranking.tolerance_bands
    tier = c.subdivision_tier.value
    distance = c.distance_miles.value
    buckets = {
        "subdivision": MISSING if tier is None else (0, tier),
        "distance": _bucket(
            None if distance is None else Fraction(str(distance)), bands.distance_miles
        ),
        "gla": _bucket(_pct_diff(c.living_area.value, subject.living_area), bands.gla_pct),
        "age": _bucket(c.age_diff_years.value, bands.age_years),
        "lot": _bucket(_pct_diff(c.lot_acres(), subject.lot_acres()), bands.lot_pct),
        "beds": _bucket(_diff(c.bedrooms.value, subject.bedrooms), bands.beds_count),
        "baths": _bucket(_diff(c.total_baths(), subject.total_baths()), bands.baths_count),
    }
    return (
        _listing_status_priority(c),
        _financing_priority(c),
        *(buckets[k] for k in settings.ranking.hierarchy),
        _contract_price_bucket(c, subject),
        _pool_priority(c, subject),
        _adu_priority(c, subject),
        _raw(distance),
        _raw(c.gla_diff_pct.value),
        c.mls_number,
    )


def _top_exclusion_rule(prior_audit: list[AuditEntry]) -> tuple[str, int] | None:
    counts = Counter(
        a.rule
        for a in prior_audit
        if a.stage == "hard_filters" and a.decision == Decision.EXCLUDED and a.rule
    )
    if not counts:
        return None
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))  # most rows, then name


def _is_close_and_good(
    c: Comp,
    subject: Subject,
    settings: Settings,
    base_comp: Comp | None = None,
) -> tuple[bool, str]:
    """Check if a comp beyond minimum shortlist size is close and good enough to include.

    Returns (is_good, reason_if_not).
    """
    dist = c.distance_miles.value
    if dist is None:
        return False, "distance unknown"

    max_close_dist = max(1.0, settings.filters.max_distance_miles)
    if dist > max_close_dist:
        return False, f"distance {dist:.2f} mi exceeds close range {max_close_dist:.2f} mi"

    if base_comp and base_comp.distance_miles.value is not None:
        jump_limit = base_comp.distance_miles.value + (settings.ranking.tolerance_bands.distance_miles * 2)
        if dist > jump_limit and dist > 0.75:
            return False, f"distance {dist:.2f} mi jumps significantly past base comp ({base_comp.distance_miles.value:.2f} mi)"

    if c.living_area.value is None or c.gla_diff_pct.value is None:
        return False, "living area unknown"
    if abs(c.gla_diff_pct.value) > float(settings.filters.gla_bracket_pct):
        return False, f"GLA diff {c.gla_diff_pct.value:.1f}% exceeds bracket {settings.filters.gla_bracket_pct}%"

    tier = c.subdivision_tier.value
    if base_comp and base_comp.subdivision_tier.value in (0, 1):
        if tier is not None and tier > 2 and dist > 0.5:
            return False, f"subdivision tier {tier} does not match while base comp is in-subdivision"

    return True, "ok"


def _ensure_c1_shortlist_quotas(out: RankOutput, pool: str, size: int) -> None:
    """Step 4.2 & 5 Master Guidance: In New Construction mode, guarantee that the shortlist
    preserves at least 2 sold / 1 listing in-subdivision comps and 1 sold / 1 listing out-of-subdivision
    comps if they are available in the ranked pool, rather than allowing one tier to monopolize
    the shortlist slots.
    """
    if pool == "sold":
        min_in, min_out = 2, 2  # target at least 2 inside and 2 outside sold for healthy choice
    else:
        min_in, min_out = 1, 1  # target at least 1 inside and 1 outside listing

    shortlist_mls = {c.mls_number for c in out.shortlist}
    inside_sl = [c for c in out.shortlist if c.subdivision_tier.value in (0, 1)]
    outside_sl = [c for c in out.shortlist if c.subdivision_tier.value not in (0, 1)]

    # If outside is under-represented, promote top outside candidates from out.ranked
    if len(outside_sl) < min_out:
        need = min_out - len(outside_sl)
        candidates = [
            c
            for c in out.ranked
            if c.mls_number not in shortlist_mls and c.subdivision_tier.value not in (0, 1)
        ]
        for c in candidates[:need]:
            # Displace lowest ranked surplus inside comp if inside quota won't be breached
            if len(inside_sl) > min_in:
                to_remove = inside_sl.pop()
                out.shortlist = [x for x in out.shortlist if x.mls_number != to_remove.mls_number]
                out.shortlist.append(c)
                shortlist_mls.add(c.mls_number)
                shortlist_mls.remove(to_remove.mls_number)
            elif len(out.shortlist) < size:
                out.shortlist.append(c)
                shortlist_mls.add(c.mls_number)

    # If inside is under-represented, promote top inside candidates from out.ranked
    inside_sl = [c for c in out.shortlist if c.subdivision_tier.value in (0, 1)]
    outside_sl = [c for c in out.shortlist if c.subdivision_tier.value not in (0, 1)]
    if len(inside_sl) < min_in:
        need = min_in - len(inside_sl)
        candidates = [
            c
            for c in out.ranked
            if c.mls_number not in shortlist_mls and c.subdivision_tier.value in (0, 1)
        ]
        for c in candidates[:need]:
            # Displace lowest ranked surplus outside comp if outside quota won't be breached
            if len(outside_sl) > min_out:
                to_remove = outside_sl.pop()
                out.shortlist = [x for x in out.shortlist if x.mls_number != to_remove.mls_number]
                out.shortlist.append(c)
                shortlist_mls.add(c.mls_number)
                shortlist_mls.remove(to_remove.mls_number)
            elif len(out.shortlist) < size:
                out.shortlist.append(c)
                shortlist_mls.add(c.mls_number)

    out.shortlist.sort(key=lambda c: c.rank or 0)
    final_sl_mls = {c.mls_number for c in out.shortlist}
    out.excluded = [
        Excluded(
            c.source_row,
            c.mls_number,
            STAGE,
            [f"RANK_BEYOND_SHORTLIST: {pool} rank {c.rank} > shortlist size {size}"],
        )
        for c in out.ranked
        if c.mls_number not in final_sl_mls
    ]


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
    base_comp: Comp | None = None
    cutoff_reached = False
    for position, (key, c) in enumerate(keyed, start=1):
        stored = [list(k) if isinstance(k, tuple) else k for k in key]
        ranked = c.model_copy(update={"rank": position, "sort_key": stored})
        out.ranked.append(ranked)

        shortlist_candidate = False
        exclusion_reason = ""
        if position <= minimum:
            shortlist_candidate = True
            if position == minimum:
                base_comp = ranked
        elif position <= size and not cutoff_reached and minimum > 0 and pool == "sold":
            is_good, reason = _is_close_and_good(ranked, subject, settings, base_comp)
            if is_good:
                shortlist_candidate = True
            else:
                cutoff_reached = True
                exclusion_reason = (
                    f"RANK_BEYOND_SHORTLIST: {pool} rank {position} not close/good enough for "
                    f"shortlist extension ({reason})"
                )
        elif position <= size and (minimum == 0 or pool != "sold"):
            shortlist_candidate = True
        else:
            exclusion_reason = f"RANK_BEYOND_SHORTLIST: {pool} rank {position} > shortlist size {size}"

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
                    "shortlisted": shortlist_candidate,
                },
            )
        )
        if shortlist_candidate:
            out.shortlist.append(ranked)
        else:
            out.excluded.append(
                Excluded(
                    c.source_row,
                    c.mls_number,
                    STAGE,
                    [exclusion_reason or f"RANK_BEYOND_SHORTLIST: {pool} rank {position} > shortlist size {size}"],
                )
            )

    if subject.is_new_construction:
        _ensure_c1_shortlist_quotas(out, pool, size)

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
