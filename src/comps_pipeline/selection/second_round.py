"""Second round ("find more comps"): keep the usable shortlist, drop the flagged comps,
refill only from properties never shortlisted that pass slightly looser rules. If that still
leaves fewer comps than the final pick needs, top up with the closest properties that break
only relaxable rules (never `never_relax`, e.g. stories / sub-type), flagged to be replaced."""

import logging
from collections import Counter

from comps_pipeline.config.schema import Settings
from comps_pipeline.filters.hard_filters import apply_hard_filters
from comps_pipeline.models import (
    AuditEntry,
    Comp,
    Decision,
    Excluded,
    Flag,
    FlagReason,
    StageOutput,
    Subject,
)
from comps_pipeline.ranking.ranker import rank

STAGE = "second_round"
log = logging.getLogger(__name__)


def unusable(flags: list[Flag], settings: Settings) -> dict[str, list[str]]:
    """mls_number -> flag reasons that make a comp not comparable."""
    bad: dict[str, list[str]] = {}
    for f in flags:
        if f.mls_number and f.reason in settings.second_round.remove_if_flagged:
            bad.setdefault(f.mls_number, []).append(f.reason.value)
    return bad


def needs_more(picks: list[Comp], flags: list[Flag], settings: Settings) -> bool:
    wanted = settings.selection.sold_count + settings.selection.listing_count
    bad = unusable(flags, settings)
    return len(picks) < wanted or any(c.mls_number in bad for c in picks)


def find_more(
    candidates: list[Comp],
    shortlists: dict[str, list[Comp]],
    flags: list[Flag],
    subject: Subject,
    settings: Settings,
    level: int,
) -> tuple[dict[str, list[Comp]], StageOutput, dict]:
    """candidates: every comp that reached the hard filters (blocked rows are already gone)."""
    out = StageOutput()
    bad = unusable(flags, settings)
    seen = {c.mls_number for pool in shortlists.values() for c in pool}
    new_level = min(level + settings.second_round.extra_relax_steps, len(settings.escalation.steps))
    relaxed = settings.model_copy(update={"filters": settings.filters_at(new_level)})
    passed = apply_hard_filters(candidates, subject, relaxed)
    fresh = [c for c in passed.comps if c.mls_number not in seen]
    # Why the never-shortlisted properties still fail: every rule hit, and rules that were
    # the *only* miss (one more loosening of that rule would let them in).
    misses = [e.reasons for e in passed.excluded if e.mls_number not in seen]
    rule = lambda r: r.split(":", 1)[0]  # noqa: E731
    blocked_by = Counter(rule(r) for reasons in misses for r in reasons)
    only_miss = Counter(rule(reasons[0]) for reasons in misses if len(reasons) == 1)
    never = set(settings.second_round.never_relax)
    breaks = {  # mls -> rules it breaks, for properties that break only relaxable ones
        e.mls_number: e.reasons
        for e in passed.excluded
        if e.mls_number not in seen and not never & {rule(r) for r in e.reasons}
    }
    fallback = [c for c in candidates if c.mls_number in breaks]
    picks_needed = {"sold": settings.selection.sold_count, "listing": settings.selection.listing_count}

    sizes = {"sold": settings.run.shortlist_size, "listing": settings.run.listing_shortlist_size}
    new_shortlists: dict[str, list[Comp]] = {}
    kept: list[str] = []
    added: list[str] = []
    filled: list[str] = []
    for pool, size in sizes.items():
        keep = [c for c in shortlists.get(pool, []) if c.mls_number not in bad]
        room = max(size - len(keep), 0)
        pool_fresh = [c for c in fresh if c.pool == pool]
        new = rank(pool_fresh, subject, settings, max(room, 1), pool=pool).ranked[:room]
        new = [c.model_copy(update={"found_in_round": 2}) for c in new]
        short = picks_needed[pool] - len(keep) - len(new)
        fill: list[Comp] = []
        if short > 0 and settings.second_round.fill_to_pick_count:
            pool_fb = [c for c in fallback if c.pool == pool]
            fill = rank(pool_fb, subject, settings, max(short, 1), pool=pool).ranked[:short]
            fill = [c.model_copy(update={"found_in_round": 2}) for c in fill]
        # Order = stricter rules first: round-1 comps, then round-2 finds, then fillers.
        merged = keep + new + fill
        new_shortlists[pool] = [c.model_copy(update={"rank": i}) for i, c in enumerate(merged, 1)]
        kept += [c.mls_number for c in keep]
        added += [c.mls_number for c in new]
        filled += [c.mls_number for c in fill]

    added_set = set(added)
    out.flags = [f for f in passed.flags if f.mls_number in added_set]
    for mls in filled:
        why = "; ".join(breaks[mls])
        out.flags.append(
            settings.flag(
                FlagReason.OUTSIDE_RULES_PICK,
                mls,
                f"Used only to reach {sum(picks_needed.values())} comps; it breaks your rules "
                f"({why}). Replace it if a better comp is available.",
            )
        )
    removed = {m: r for m, r in bad.items() if m in seen}
    for pool in shortlists.values():
        for c in pool:
            if c.mls_number in removed:
                why = ", ".join(removed[c.mls_number])
                out.excluded.append(
                    Excluded(c.source_row, c.mls_number, STAGE, [f"SECOND_ROUND_REMOVED: {why}"])
                )
    for mls, rule, decision in (
        *((m, "kept_from_round_1", Decision.KEPT) for m in kept),
        *((m, "removed_not_comparable", Decision.EXCLUDED) for m in removed),
        *((m, "added_in_round_2", Decision.KEPT) for m in added),
        *((m, "filled_outside_rules", Decision.FLAGGED) for m in filled),
    ):
        detail = {"reasons": removed.get(mls) or breaks.get(mls, [])} if rule != "kept_from_round_1" else {}
        out.audit.append(
            AuditEntry(mls_number=mls, stage=STAGE, decision=decision, rule=rule, detail=detail)
        )
    steps = len(settings.escalation.steps)
    summary = {
        "level_round_1": level,
        "level_used": new_level,
        "steps_available": steps,
        "no_looser_rules": new_level == level,
        "kept": kept,
        "removed": sorted(removed),
        "added": added,
        "filled": filled,
        "never_relax": sorted(never),
        "reached_filters": len(candidates),
        "never_shortlisted": len(candidates) - len(seen & {c.mls_number for c in candidates}),
        "passed_rules": len(passed.comps),
        "candidates_checked": len(fresh),
        "blocked_by": dict(blocked_by.most_common()),
        "only_miss": {r: only_miss[r] for r in blocked_by},
    }
    log.info(
        "second round: rules step %d -> %d of %d%s",
        level,
        new_level,
        steps,
        " (no looser step left)" if new_level == level else "",
    )
    log.info(
        "second round: %d reached the rules, %d never shortlisted, %d pass at step %d, %d new",
        summary["reached_filters"],
        summary["never_shortlisted"],
        len(passed.comps),
        new_level,
        len(fresh),
    )
    log.info("second round: kept %d, removed %d %s", len(kept), len(removed), sorted(removed))
    for r, n in blocked_by.most_common():
        log.info("second round: blocked by %s: %d (only reason for %d)", r, n, only_miss[r])
    log.info("second round: added %d %s", len(added), added)
    for mls in filled:
        log.info("second round: filled %s outside the rules: %s", mls, "; ".join(breaks[mls]))
    if any(len(new_shortlists[p]) < n for p, n in picks_needed.items()):
        log.info("second round: still short; only %s rules block the rest", sorted(never))
    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail=summary,
        )
    )
    return new_shortlists, out, summary
