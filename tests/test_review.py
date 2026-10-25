from comps_pipeline import pipeline
from comps_pipeline.llm.cache import cache_key
from comps_pipeline.llm.mock_client import HALLUCINATED_ID, MockLLMClient
from comps_pipeline.llm.review import build_payload, review
from comps_pipeline.models import FlagOrigin, FlagReason
from tests.conftest import SAMPLES, make_comp, with_llm

CSV, SUBJECT = SAMPLES / "mls_sample.csv", SAMPLES / "subject.yaml"


def test_payload_contains_only_fields_sent(settings):
    comp = make_comp("1", public_remarks="hi", latitude=30.1, close_price=100, living_area=2000)
    payload = build_payload([comp], ["mls_number", "public_remarks", "close_date"])
    assert payload == {"comps": [{"mls_number": "1", "public_remarks": "hi", "close_date": None}]}


def test_batches_follow_batch_size(settings):
    comps = [make_comp(str(i), public_remarks="x") for i in range(25)]
    client = MockLLMClient("clean")
    results = review(comps, client, with_llm(settings, enabled=True, batch_size=10, cache=False))
    assert [len(r.batch) for r in results] == [10, 10, 5]
    assert client.calls == 3


def test_cache_reuses_response(settings):
    s = with_llm(settings, enabled=True, cache=True)
    comps = [make_comp("1", public_remarks="Estate sale")]
    client = MockLLMClient("clean")
    review(comps, client, s)
    review(comps, client, s)
    assert client.calls == 1
    assert len(list(s.llm.cache_dir.glob("*.json"))) == 1
    assert cache_key("m", "s", {"b": 1, "a": 2}) == cache_key("m", "s", {"a": 2, "b": 1})


def test_llm_off_completes_with_unavailable(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    assert result.manifest.llm_mode == "off"
    assert [f.reason for f in result.flags if f.reason is FlagReason.LLM_UNAVAILABLE]


def test_llm_error_completes_with_unavailable(settings):
    s = with_llm(settings, enabled=True, provider="mock", mock_mode="error")
    result = pipeline.run(CSV, SUBJECT, s)
    unavailable = [f for f in result.flags if f.reason is FlagReason.LLM_UNAVAILABLE]
    assert len(unavailable) == 3  # one per batch of 10
    assert result.exit_code == 0


def test_gemini_without_key_completes_with_unavailable(settings, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    result = pipeline.run(CSV, SUBJECT, with_llm(settings, enabled=True, provider="gemini"))
    (f,) = [f for f in result.flags if f.reason is FlagReason.LLM_UNAVAILABLE]
    assert "GEMINI_API_KEY" in f.message
    assert result.manifest.llm_mode == "gemini (unavailable)"


def test_clean_mock_flags_planted_remarks(settings):
    result = pipeline.run(CSV, SUBJECT, with_llm(settings, enabled=True, provider="mock"))
    accepted = [f for f in result.flags if f.origin is FlagOrigin.LLM]
    quotes = {f.evidence.casefold() for f in accepted}
    assert {"estate sale", "sold to family member", "investor special"} <= quotes
    assert not [f for f in result.flags if f.origin is FlagOrigin.GATE]


def test_review_never_changes_ranks_or_values(settings):
    off = pipeline.run(CSV, SUBJECT, settings)
    for mode in ("clean", "hallucinate_id", "fake_quote", "malformed", "error"):
        on = pipeline.run(
            CSV, SUBJECT, with_llm(settings, enabled=True, provider="mock", mock_mode=mode)
        )
        assert [c.model_dump() for c in on.shortlist] == [c.model_dump() for c in off.shortlist], (
            mode
        )
        assert (on.out_dir / "shortlist.json").read_bytes() == (
            off.out_dir / "shortlist.json"
        ).read_bytes()
        assert [c.model_dump() for c in on.ranked] == [c.model_dump() for c in off.ranked]


def test_hallucinated_id_and_fake_quote_rejected_in_pipeline(settings):
    for mode, reason in (
        ("hallucinate_id", FlagReason.LLM_UNKNOWN_ID),
        ("fake_quote", FlagReason.LLM_EVIDENCE_NOT_FOUND),
    ):
        s = with_llm(settings, enabled=True, provider="mock", mock_mode=mode)
        result = pipeline.run(CSV, SUBJECT, s)
        gate = [f for f in result.flags if f.origin is FlagOrigin.GATE]
        assert gate and {f.reason for f in gate} == {reason}
        assert all(f.mls_number != HALLUCINATED_ID for f in result.flags)
