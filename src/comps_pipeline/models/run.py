from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from comps_pipeline.models.audit import AuditEntry
from comps_pipeline.models.comp import Comp
from comps_pipeline.models.flag import Flag


class RunManifest(BaseModel):
    run_id: str
    started_at: str
    input_file: str
    input_sha256: str
    subject_file: str
    subject_sha256: str
    config_snapshot: dict[str, Any]
    package_version: str
    llm_mode: str  # gemini model name | mock:<mode> | off
    row_counts: dict[str, int] = Field(default_factory=dict)
    stage_durations_s: dict[str, float] = Field(default_factory=dict)
    escalation_level: int = 0  # how many escalation steps were applied
    escalation_attempts: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class Excluded:
    """A row removed from consideration, with every reason it failed."""

    source_row: int
    mls_number: str | None
    stage: str
    reasons: list[str]


@dataclass
class StageOutput:
    comps: list[Comp] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
