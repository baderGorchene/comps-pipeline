"""Send the ranked shortlist to the LLM in batches. Only llm.fields_sent leave the machine.

The responses are NOT trusted here: every one goes through validation/gate.py before any
flag can reach the outputs.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from comps_pipeline.config.schema import Settings
from comps_pipeline.llm.base import LLMClient, LLMResult, parse_json
from comps_pipeline.llm.cache import ResponseCache
from comps_pipeline.models import Comp

log = logging.getLogger(__name__)

ALLOWED_REASONS = ("POSSIBLE_NON_ARMS_LENGTH", "REMARKS_CONCERN", "SUBDIVISION_UNCERTAIN")
PROMPT_PATH = Path(__file__).parent / "prompts" / "review_system.md"


class ReviewFlag(BaseModel):
    mls_number: str
    # The enum constrains Gemini's output; parsing accepts any string so the gate can
    # reject a disallowed reason explicitly (LLM_DISALLOWED_REASON) instead of failing the batch.
    reason: str = Field(json_schema_extra={"enum": list(ALLOWED_REASONS)})
    evidence_quote: str
    comment: str = Field(max_length=300)


class ReviewResponse(BaseModel):
    flags: list[ReviewFlag]


@dataclass
class BatchResult:
    index: int
    batch: list[Comp]
    result: LLMResult
    attempts: int


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _value(comp: Comp, field: str) -> Any:
    if field == "mls_number":
        return comp.mls_number
    value = getattr(comp, field).value
    return value.isoformat() if hasattr(value, "isoformat") else value


def build_payload(batch: list[Comp], fields: list[str]) -> dict[str, Any]:
    return {"comps": [{f: _value(c, f) for f in fields} for c in batch]}


def _call(
    client: LLMClient, system: str, payload: dict[str, Any], cache: ResponseCache | None
) -> LLMResult:
    if cache is not None and (hit := cache.get(client.model, system, payload)) is not None:
        log.info("LLM cache hit")
        return hit
    result = client.generate_json(system, payload, ReviewResponse)
    parses = result.raw_text is not None and parse_json(result.raw_text, ReviewResponse)[1] is None
    if cache is not None and parses:
        cache.put(system, payload, result)
    return result


def review(
    shortlist: list[Comp], client: LLMClient, settings: Settings, system: str | None = None
) -> list[BatchResult]:
    cfg = settings.llm
    system = system or load_system_prompt()
    cache = ResponseCache(cfg.cache_dir) if cfg.cache else None
    results = []
    for index, start in enumerate(range(0, len(shortlist), cfg.batch_size)):
        batch = shortlist[start : start + cfg.batch_size]
        payload = build_payload(batch, cfg.fields_sent)
        log.debug("LLM payload batch %d: %s", index, json.dumps(payload, ensure_ascii=False))
        result = _call(client, system, payload, cache)
        attempts = 1
        while result.raw_text is not None and attempts <= cfg.max_retries:
            error = parse_json(result.raw_text, ReviewResponse)[1]
            if error is None:
                break
            log.warning("batch %d: response failed the schema, retrying", index)
            retry_system = (
                f"{system}\n\nYour previous response failed validation:\n{error[:1000]}\n"
                "Return only JSON that matches the response schema."
            )
            result = _call(client, retry_system, payload, cache)
            attempts += 1
        log.info(
            "batch %d: %d comps, model %s, tokens in/out %s/%s",
            index,
            len(batch),
            result.model,
            result.input_tokens,
            result.output_tokens,
        )
        results.append(BatchResult(index, batch, result, attempts))
    return results
