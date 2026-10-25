"""Gemini client behaviour without network or a real key."""

from types import SimpleNamespace

import pytest

from comps_pipeline.llm.gemini_client import GeminiClient
from comps_pipeline.llm.review import ReviewResponse

FAKE_KEY = "AIza-not-a-real-key-123"


def test_requires_key_and_model():
    with pytest.raises(ValueError):
        GeminiClient(api_key="", model="gemini-x")
    with pytest.raises(ValueError):
        GeminiClient(api_key=FAKE_KEY, model="")


def test_api_exception_becomes_result_error_and_hides_key(monkeypatch):
    client = GeminiClient(api_key=FAKE_KEY, model="gemini-x")

    def boom(**_):
        raise RuntimeError(f"401 invalid key {FAKE_KEY}")

    monkeypatch.setattr(client._client.models, "generate_content", boom)
    result = client.generate_json("sys", {"comps": []}, ReviewResponse)
    assert result.raw_text is None and result.parsed is None
    assert "RuntimeError" in result.error and FAKE_KEY not in result.error


def test_success_parses_and_counts_tokens(monkeypatch):
    client = GeminiClient(api_key=FAKE_KEY, model="gemini-x", temperature=0)
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        usage = SimpleNamespace(prompt_token_count=12, candidates_token_count=3)
        return SimpleNamespace(text='{"flags": []}', usage_metadata=usage)

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    result = client.generate_json("sys", {"comps": []}, ReviewResponse)
    assert result.parsed == ReviewResponse(flags=[])
    assert (result.input_tokens, result.output_tokens) == (12, 3)
    cfg = seen["config"]
    assert cfg.response_mime_type == "application/json" and cfg.temperature == 0
    assert cfg.response_schema is ReviewResponse
