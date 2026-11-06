"""Optional vision stage: photo-based Q/C scoring of the shortlist, between ranking and selection.

Only the shortlisted comps (plus the subject) are scored, never the raw MLS import, so a run
sends at most ~(shortlist + 1) x max_photos_per_property images.
"""

import json
import logging
import re
from typing import Any

from comps_pipeline.ai.parsers import VisionScore
from comps_pipeline.ai.prompts import VISION_QC_SYSTEM
from comps_pipeline.ai.router import AIModelRouter, _clean_json_text
from comps_pipeline.config.schema import Settings
from comps_pipeline.models import AuditEntry, Comp, Decision, FlagReason, StageOutput, Subject

log = logging.getLogger(__name__)
STAGE = "vision"
SUBJECT_ID = "SUBJECT"


def photo_urls(raw: Any, limit: int) -> list[str]:
    """Photo URLs from an MLS cell: a list, or a string split on commas/pipes/semicolons/space."""
    items = raw if isinstance(raw, list) else re.split(r"[,|;\s]+", str(raw or ""))
    urls = [u.strip() for u in items if str(u).strip().lower().startswith(("http://", "https://"))]
    return list(dict.fromkeys(urls))[:limit]  # dedupe, keep order


def _rating(value: str | None) -> int | None:
    m = re.fullmatch(r"[CQ]([1-6])", (value or "").strip().upper())
    return int(m.group(1)) if m else None


def score_property(
    router: AIModelRouter, label: str, remarks: str, urls: list[str]
) -> VisionScore | None:
    """One vision call per property. None when there are no photos or no model answered."""
    if not urls:
        return None
    prompt = (
        f"Property: {label}\nListing remarks:\n{remarks or '(none)'}\n\n{len(urls)} photos follow."
    )
    raw, model = router.execute(VISION_QC_SYSTEM, prompt, images=urls)
    if not raw:
        return None
    try:
        data = json.loads(_clean_json_text(raw))
        return VisionScore.model_validate(
            {**data, "photos_analyzed": len(urls), "model_used": model}
        )
    except Exception as e:  # bad JSON or out-of-range rating: no score beats a wrong one
        log.warning("vision score for %s unusable: %s", label, e)
        return None


def qc_delta(score: VisionScore | None, target_c: int | None, target_q: int | None) -> int:
    """Total C + Q steps between a comp's visual rating and the subject (0 when unknown)."""
    if score is None:
        return 0
    c, q = _rating(score.visual_condition_rating), _rating(score.visual_quality_rating)
    return (abs(c - target_c) if target_c is not None else 0) + (
        abs(q - target_q) if target_q is not None else 0
    )


def rerank(
    shortlist: list[Comp], target_c: int | None, target_q: int | None, settings: Settings
) -> list[Comp]:
    """Stable demotion: confident scores >= rerank_min_delta steps off the subject move behind
    the rest; everything else keeps its deterministic rank order. Ranks are renumbered 1..n."""
    cfg = settings.vision

    def demoted(c: Comp) -> bool:
        s = c.vision
        return (
            s is not None
            and s.confidence_score >= cfg.min_confidence
            and qc_delta(s, target_c, target_q) >= cfg.rerank_min_delta
        )

    ordered = sorted(shortlist, key=lambda c: (demoted(c), c.rank or 0))
    return [c.model_copy(update={"rank": i}) for i, c in enumerate(ordered, 1)]


def run_vision(
    shortlists: dict[str, list[Comp]],
    subject: Subject,
    settings: Settings,
    router: AIModelRouter | None = None,
) -> tuple[dict[str, list[Comp]], VisionScore | None, StageOutput]:
    """Score subject + shortlisted comps, re-rank each pool, emit flags and audit entries."""
    cfg = settings.vision
    out = StageOutput()
    router = router or AIModelRouter(timeout=90.0)

    def urls_for(c: Comp) -> list[str]:
        return photo_urls(c.extra_str(*cfg.photo_columns), cfg.max_photos_per_property)

    subject_urls = photo_urls(subject.extras.get("photo_urls"), cfg.max_photos_per_property)
    comps = [c for pool in shortlists.values() for c in pool]
    jobs = [
        (SUBJECT_ID, subject.address, str(subject.extras.get("public_remarks", "")), subject_urls)
    ]
    jobs += [
        (
            c.mls_number,
            c.address_display() or c.mls_number,
            c.public_remarks.value or "",
            urls_for(c),
        )
        for c in comps
    ]
    # ponytail: thread pool of 4 shared with the router; raise max_workers if runs get slow
    results = dict(
        zip(
            [j[0] for j in jobs],
            router._executor.map(lambda j: score_property(router, *j[1:]), jobs),
            strict=True,
        )
    )

    subject_score = results.pop(SUBJECT_ID)
    # Target: the subject's own photos when confident, else its declared UAD ratings.
    use_photos = subject_score is not None and subject_score.confidence_score >= cfg.min_confidence
    target_c = _rating(subject_score.visual_condition_rating if use_photos else subject.condition)
    target_q = _rating(subject_score.visual_quality_rating if use_photos else subject.quality)

    for mls, score in [(SUBJECT_ID, subject_score), *results.items()]:
        out.audit.append(
            AuditEntry(
                mls_number=mls,
                stage=STAGE,
                decision=Decision.FLAGGED
                if score and score.remarks_mismatch_flag
                else Decision.KEPT,
                rule="vision_qc_score" if score else "vision_unscored",
                detail=score.model_dump() if score else {},
            )
        )
        if score is None:
            continue
        if score.remarks_mismatch_flag:
            out.flags.append(
                settings.flag(
                    FlagReason.VISUAL_REMARKS_MISMATCH,
                    mls,
                    "Listing photos contradict the public remarks.",
                    field="public_remarks",
                    evidence=score.mismatch_detail or None,
                )
            )
        delta = qc_delta(score, target_c, target_q)
        if mls != SUBJECT_ID and delta >= cfg.rerank_min_delta:
            out.flags.append(
                settings.flag(
                    FlagReason.VISUAL_QC_MISMATCH,
                    mls,
                    f"Photos rate {score.visual_condition_rating}/{score.visual_quality_rating}, "
                    f"{delta} steps from the subject (confidence {score.confidence_score:.2f}).",
                    evidence=", ".join(score.detected_features) or None,
                )
            )

    new_shortlists = {}
    for pool, members in shortlists.items():
        scored = [c.model_copy(update={"vision": results.get(c.mls_number)}) for c in members]
        new_shortlists[pool] = rerank(scored, target_c, target_q, settings)
        before = [c.mls_number for c in members]
        after = [c.mls_number for c in new_shortlists[pool]]
        if before != after:
            out.audit.append(
                AuditEntry(
                    mls_number=None,
                    stage=STAGE,
                    decision=Decision.RANKED,
                    rule="vision_rerank",
                    detail={"pool": pool, "before": before, "after": after},
                )
            )
    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail={
                "properties": len(jobs),
                "scored": sum(s is not None for s in [subject_score, *results.values()]),
                "photos_sent": sum(len(j[3]) for j in jobs),
                "target_condition": target_c,
                "target_quality": target_q,
                "target_source": "subject_photos" if use_photos else "subject_declared",
            },
        )
    )
    return new_shortlists, subject_score, out
