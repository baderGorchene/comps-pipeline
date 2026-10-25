from typing import Any

from pydantic import BaseModel, Field


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
