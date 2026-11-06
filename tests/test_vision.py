"""Vision Q/C stage: scoring, mismatch flags, re-ranking, pipeline wiring."""

import json
from concurrent.futures import ThreadPoolExecutor

from comps_pipeline import pipeline
from comps_pipeline.ai.vision import photo_urls, run_vision
from comps_pipeline.models import FlagReason
from tests.conftest import SAMPLES, make_comp


class StubRouter:
    """Answers each vision call from a canned table keyed by the property label."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []
        self._executor = ThreadPoolExecutor(max_workers=2)

    def execute(self, system, prompt, images=None):
        label = prompt.splitlines()[0].removeprefix("Property: ")
        self.calls.append((label, images))
        ans = self.answers.get(label)
        return (json.dumps(ans), "stub-vision") if ans else ("", "heuristic_fallback")


def _score(c, q, conf=0.9, mismatch=False):
    return {
        "visual_condition_rating": c,
        "visual_quality_rating": q,
        "confidence_score": conf,
        "detected_features": ["UPGRADED_KITCHEN"],
        "remarks_mismatch_flag": mismatch,
        "mismatch_detail": "Remarks claim renovated kitchen; photos show laminate."
        if mismatch
        else "",
    }


def _comp(mls, rank, urls="https://x/1.jpg|https://x/2.jpg"):
    c = make_comp(mls, public_remarks="Fully renovated kitchen")
    return c.model_copy(update={"rank": rank, "pool": "sold", "extras": {"Photo URLs": urls}})


def test_photo_urls_split_dedupe_cap():
    raw = "https://a/1.jpg, https://a/2.jpg|https://a/1.jpg ftp://bad /local.jpg"
    assert photo_urls(raw, 25) == ["https://a/1.jpg", "https://a/2.jpg"]
    assert photo_urls(raw, 1) == ["https://a/1.jpg"]
    assert photo_urls(None, 5) == []


def test_vision_scores_flags_and_reranks(subject, settings):
    subj = subject.model_copy(
        update={"extras": {"photo_urls": ["https://s/1.jpg"]}, "condition": "C1", "quality": "Q3"}
    )
    shortlists = {
        "sold": [_comp("A", 1), _comp("B", 2), _comp("C", 3), _comp("D", 4, urls="")],
        "listing": [],
    }
    router = StubRouter(
        {
            "1 Test St": _score("C2", "Q3"),  # subject photos override declared C1
            "A": _score("C4", "Q4", mismatch=True),  # 3 steps off -> demoted + both flags
            "B": _score("C2", "Q3"),
            "C": _score("C5", "Q5", conf=0.3),  # low confidence -> stays put
        }
    )
    new, subject_score, out = run_vision(shortlists, subj, settings, router)

    assert subject_score.visual_condition_rating == "C2"
    assert [c.mls_number for c in new["sold"]] == ["B", "C", "D", "A"]
    assert [c.rank for c in new["sold"]] == [1, 2, 3, 4]
    by = {c.mls_number: c for c in new["sold"]}
    assert by["A"].vision.remarks_mismatch_flag and by["D"].vision is None
    assert not any(label == "D" for label, _ in router.calls)  # no photos -> no API call

    reasons = {(f.mls_number, f.reason) for f in out.flags}
    assert ("A", FlagReason.VISUAL_REMARKS_MISMATCH) in reasons
    assert ("A", FlagReason.VISUAL_QC_MISMATCH) in reasons
    assert ("C", FlagReason.VISUAL_QC_MISMATCH) in reasons  # flagged, just not moved
    assert not any(m == "B" for m, _ in reasons)
    summary = [a for a in out.audit if a.rule == "stage_summary"][0].detail
    assert summary["target_source"] == "subject_photos" and summary["scored"] == 4


def test_pipeline_vision_enabled_without_keys_is_harmless(settings):
    s = settings.model_copy(update={"vision": settings.vision.model_copy(update={"enabled": True})})
    result = pipeline.run(SAMPLES / "mls_sample.csv", SAMPLES / "subject.yaml", s)
    assert "vision" in result.manifest.stage_durations_s
    assert all(c.vision is None for c in result.shortlist)  # no network under pytest
    assert result.final.picks
