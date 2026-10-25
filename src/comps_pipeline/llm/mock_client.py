"""Deterministic offline stand-in for Gemini. Used by tests, the demo and --llm mock."""

import json
from typing import Any

from pydantic import BaseModel

from comps_pipeline.llm.base import LLMResult, parse_json

# Phrase found in remarks -> reason the mock reviewer reports (clean behaviour).
TRIGGERS = (
    ("sold to family member", "POSSIBLE_NON_ARMS_LENGTH"),
    ("estate sale", "POSSIBLE_NON_ARMS_LENGTH"),
    ("investor special", "REMARKS_CONCERN"),
)
HALLUCINATED_ID = "0000000-HALLUCINATED"
FAKE_QUOTE = "motivated seller, will consider all offers below appraisal"


class MockLLMClient:
    """Modes: clean, hallucinate_id, fake_quote, malformed, error."""

    def __init__(self, mode: str = "clean"):
        self.mode = mode
        self.model = f"mock:{mode}"
        self.calls = 0

    def _clean_flags(self, comps: list[dict[str, Any]]) -> list[dict[str, str]]:
        flags = []
        for comp in comps:
            remarks = comp.get("public_remarks") or ""
            for phrase, reason in TRIGGERS:
                pos = remarks.casefold().find(phrase)
                if pos >= 0:
                    flags.append(
                        {
                            "mls_number": comp["mls_number"],
                            "reason": reason,
                            "evidence_quote": remarks[pos : pos + len(phrase)],
                            "comment": f"Remarks mention '{phrase}'; verify the sale conditions.",
                        }
                    )
        return flags

    def generate_json(
        self, system: str, payload: dict[str, Any], schema: type[BaseModel]
    ) -> LLMResult:
        self.calls += 1
        if self.mode == "error":
            return LLMResult(raw_text=None, error="mock API failure (mode=error)", model=self.model)
        comps = payload.get("comps", [])
        if self.mode == "malformed":
            raw = '{"flags": [{"mls_number": "'  # truncated, invalid JSON
        else:
            flags = self._clean_flags(comps)
            if comps and self.mode == "hallucinate_id":
                first = comps[0]
                quote = (first.get("public_remarks") or first.get("subdivision_raw") or "")[:25]
                flags.append(
                    {
                        "mls_number": HALLUCINATED_ID,
                        "reason": "REMARKS_CONCERN",
                        "evidence_quote": quote,
                        "comment": "Flag for a listing that is not in the batch.",
                    }
                )
            if comps and self.mode == "fake_quote":
                flags.append(
                    {
                        "mls_number": comps[0]["mls_number"],
                        "reason": "REMARKS_CONCERN",
                        "evidence_quote": FAKE_QUOTE,
                        "comment": "Quote that does not appear in the remarks.",
                    }
                )
            raw = json.dumps({"flags": flags})
        parsed, error = parse_json(raw, schema)
        return LLMResult(
            raw_text=raw,
            parsed=parsed,
            error=error,
            model=self.model,
            input_tokens=len(json.dumps(payload)) // 4,
            output_tokens=len(raw) // 4,
        )
