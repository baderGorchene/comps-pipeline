from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Decision(StrEnum):
    KEPT = "KEPT"
    EXCLUDED = "EXCLUDED"
    FLAGGED = "FLAGGED"
    RANKED = "RANKED"


class AuditEntry(BaseModel):
    mls_number: str | None
    stage: str
    decision: Decision
    rule: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
