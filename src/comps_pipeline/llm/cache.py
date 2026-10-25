"""On-disk cache of LLM responses that passed schema parsing. One JSON file per key."""

import hashlib
import json
from pathlib import Path
from typing import Any

from comps_pipeline.llm.base import LLMResult


def cache_key(model: str, system: str, payload: dict[str, Any]) -> str:
    blob = model + system + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, model: str, system: str, payload: dict[str, Any]) -> Path:
        return self.directory / f"{cache_key(model, system, payload)}.json"

    def get(self, model: str, system: str, payload: dict[str, Any]) -> LLMResult | None:
        path = self._path(model, system, payload)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(
            raw_text=data["raw_text"],
            model=data["model"],
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
        )

    def put(self, system: str, payload: dict[str, Any], result: LLMResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "model": result.model,
            "raw_text": result.raw_text,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
        path = self._path(result.model, system, payload)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
