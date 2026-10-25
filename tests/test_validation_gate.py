import json

import pytest

from comps_pipeline.llm.base import LLMResult
from comps_pipeline.llm.mock_client import MockLLMClient
from comps_pipeline.llm.review import review
from comps_pipeline.models import FlagOrigin, FlagReason
from comps_pipeline.validation.gate import validate_review
from tests.conftest import make_comp, with_llm

BATCH = [
    make_comp(
        "111", public_remarks="Estate sale,  sold AS-IS.", subdivision_raw="Brushy Creek Ph 2"
    ),
    make_comp("222", public_remarks="Nice home near the park.", subdivision_raw="Brushy Creek"),
]


def result_with(*flags: dict) -> LLMResult:
    return LLMResult(raw_text=json.dumps({"flags": list(flags)}), model="test")


def flag(
    mls="111", reason="POSSIBLE_NON_ARMS_LENGTH", quote="estate sale, sold as-is", comment="x"
):
    return {"mls_number": mls, "reason": reason, "evidence_quote": quote, "comment": comment}


def test_accepts_valid_flag_with_normalized_quote(settings):
    out = validate_review(result_with(flag()), BATCH, settings)
    (accepted,) = out.accepted_flags
    assert accepted.origin is FlagOrigin.LLM
    assert accepted.reason is FlagReason.POSSIBLE_NON_ARMS_LENGTH
    assert accepted.field == "public_remarks"
    assert not out.gate_flags


def test_quote_from_subdivision_field_accepted(settings):
    out = validate_review(
        result_with(flag(reason="SUBDIVISION_UNCERTAIN", quote="ph 2")), BATCH, settings
    )
    assert out.accepted_flags[0].field == "subdivision_raw"


def test_empty_flags_list_is_valid(settings):
    out = validate_review(result_with(), BATCH, settings)
    assert not out.accepted_flags and not out.gate_flags


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (flag(mls="999"), FlagReason.LLM_UNKNOWN_ID),
        (flag(quote="motivated seller"), FlagReason.LLM_EVIDENCE_NOT_FOUND),
        (flag(quote="   "), FlagReason.LLM_EVIDENCE_NOT_FOUND),
        (flag(mls="222"), FlagReason.LLM_EVIDENCE_NOT_FOUND),  # quote belongs to another comp
        (flag(reason="OVERPRICED"), FlagReason.LLM_DISALLOWED_REASON),
    ],
)
def test_rejections(settings, item, expected):
    out = validate_review(result_with(item), BATCH, settings)
    assert not out.accepted_flags
    (rejected,) = out.gate_flags
    assert rejected.reason is expected
    assert rejected.origin is FlagOrigin.GATE
    assert json.loads(rejected.evidence)["evidence_quote"] == item["evidence_quote"]
    assert any(a.decision == "EXCLUDED" for a in out.audit)


def test_evidence_check_can_be_disabled(settings):
    s = settings.model_copy(
        update={
            "validation": settings.validation.model_copy(update={"require_evidence_quote": False})
        }
    )
    assert validate_review(result_with(flag(quote="made up")), BATCH, s).accepted_flags


def test_mixed_batch_keeps_good_rejects_bad(settings):
    out = validate_review(result_with(flag(), flag(mls="999")), BATCH, settings)
    assert len(out.accepted_flags) == 1 and len(out.gate_flags) == 1


def test_comment_over_300_chars_is_schema_failure(settings):
    out = validate_review(result_with(flag(comment="x" * 301)), BATCH, settings)
    (f,) = out.gate_flags
    assert f.reason is FlagReason.LLM_SCHEMA_FAILURE


def test_malformed_json_retries_once_then_schema_failure(settings):
    client = MockLLMClient("malformed")
    s = with_llm(settings, enabled=True, provider="mock", cache=False)
    (batch_result,) = review(BATCH, client, s)
    assert client.calls == 2  # original + exactly one retry
    assert batch_result.attempts == 2
    out = validate_review(batch_result.result, BATCH, s, attempts=batch_result.attempts)
    (f,) = out.gate_flags
    assert f.reason is FlagReason.LLM_SCHEMA_FAILURE and f.mls_number is None
    assert not out.accepted_flags


def test_api_error_becomes_unavailable(settings):
    out = validate_review(LLMResult(raw_text=None, error="boom"), BATCH, settings)
    (f,) = out.gate_flags
    assert f.reason is FlagReason.LLM_UNAVAILABLE and f.severity == "INFO"
