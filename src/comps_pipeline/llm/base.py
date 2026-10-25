from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


@dataclass
class LLMResult:
    raw_text: str | None  # None = the call itself failed (API/network); nothing came back
    parsed: BaseModel | None = None
    error: str | None = None
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    model: str

    def generate_json(
        self, system: str, payload: dict[str, Any], schema: type[BaseModel]
    ) -> LLMResult: ...


def parse_json(raw_text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    try:
        return schema.model_validate_json(raw_text), None
    except ValidationError as e:
        return None, str(e)
