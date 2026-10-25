"""Gemini via the official google-genai SDK. Never raises into the pipeline; never logs the key."""

import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from comps_pipeline.llm.base import LLMResult, parse_json

log = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: str, model: str, temperature: float = 0):
        if not api_key or not model:
            raise ValueError("Gemini needs both an API key and a model name")
        self._api_key = api_key
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***")

    def generate_json(
        self, system: str, payload: dict[str, Any], schema: type[BaseModel]
    ) -> LLMResult:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=self.temperature,
                ),
            )
            raw = response.text
            usage = response.usage_metadata
        except Exception as e:  # any SDK/network failure becomes a flag, never a crash
            error = self._redact(f"{type(e).__name__}: {e}")[:500]
            log.warning("Gemini call failed: %s", error)
            return LLMResult(raw_text=None, error=error, model=self.model)
        if raw is None:
            return LLMResult(
                raw_text=None, error="empty response (blocked or no candidates)", model=self.model
            )
        parsed, error = parse_json(raw, schema)
        return LLMResult(
            raw_text=raw,
            parsed=parsed,
            error=error,
            model=self.model,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )
