from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from comps_pipeline.models.comp import STANDARD_FIELDS
from comps_pipeline.models.flag import Flag, FlagOrigin, FlagReason, Severity

RANKING_KEYS = ("subdivision", "distance", "gla", "age", "lot")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSettings(Strict):
    output_dir: Path
    shortlist_size: int = Field(gt=0)
    min_shortlist_size: int = Field(ge=0)


class IngestSettings(Strict):
    date_formats: list[str] = Field(min_length=1)


class FilterSettings(Strict):
    gla_bracket_pct: int = Field(ge=0, le=100)  # int on purpose: boundary math stays exact
    gla_bracket_inclusive: bool
    missing_gla: Literal["exclude", "keep_and_flag"]
    max_distance_miles: float = Field(gt=0)
    missing_distance: Literal["exclude", "keep_and_flag"]
    require_subdivision_match: bool
    subdivision_min_score: float = Field(ge=0, le=100)
    sale_date_max_months: int = Field(gt=0)
    required_features: dict[str, str]


class MatchingSettings(Strict):
    noise_words: list[str]


class ToleranceBands(Strict):
    distance_miles: float = Field(gt=0)
    gla_pct: float = Field(gt=0)
    age_years: float = Field(gt=0)
    lot_pct: float = Field(gt=0)


class RankingSettings(Strict):
    hierarchy: list[str]
    tolerance_bands: ToleranceBands

    @field_validator("hierarchy")
    @classmethod
    def _permutation(cls, v: list[str]) -> list[str]:
        if sorted(v) != sorted(RANKING_KEYS):
            raise ValueError(f"hierarchy must be a permutation of {list(RANKING_KEYS)}, got {v}")
        return v


class LLMSettings(Strict):
    enabled: bool
    provider: Literal["gemini", "mock"]
    mock_mode: Literal["clean", "hallucinate_id", "fake_quote", "malformed", "error"]
    model_env: str
    api_key_env: str
    temperature: float = Field(ge=0, le=2)
    max_retries: int = Field(ge=0)
    batch_size: int = Field(gt=0)
    fields_sent: list[str]
    cache: bool
    cache_dir: Path

    @field_validator("fields_sent")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in STANDARD_FIELDS]
        if unknown:
            raise ValueError(f"unknown fields_sent {unknown}; allowed: {list(STANDARD_FIELDS)}")
        if "mls_number" not in v:
            raise ValueError("fields_sent must include mls_number")
        return v


class ValidationSettings(Strict):
    require_evidence_quote: bool


class Settings(Strict):
    run: RunSettings
    ingest: IngestSettings
    filters: FilterSettings
    matching: MatchingSettings
    ranking: RankingSettings
    llm: LLMSettings
    validation: ValidationSettings
    severity: dict[FlagReason, Severity]  # must list every FlagReason
    # Loaded from the files next to settings.yaml, not from settings.yaml itself.
    column_mapping: dict[str, list[str]]
    subdivision_aliases: dict[str, list[str]]

    @field_validator("severity")
    @classmethod
    def _all_reasons(cls, v: dict[FlagReason, Severity]) -> dict[FlagReason, Severity]:
        missing = [r.value for r in FlagReason if r not in v]
        if missing:
            raise ValueError(f"severity is missing reasons: {missing}")
        return v

    @field_validator("column_mapping")
    @classmethod
    def _mapping_fields(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        unknown = [k for k in v if k not in STANDARD_FIELDS]
        if unknown:
            raise ValueError(f"column_mapping has unknown fields {unknown}")
        return v

    @model_validator(mode="after")
    def _sizes(self) -> "Settings":
        if self.run.min_shortlist_size > self.run.shortlist_size:
            raise ValueError("run.min_shortlist_size cannot exceed run.shortlist_size")
        return self

    def sev(self, reason: FlagReason) -> Severity:
        return self.severity[reason]

    def flag(
        self,
        reason: FlagReason,
        mls_number: str | None,
        message: str,
        field: str | None = None,
        origin: FlagOrigin = FlagOrigin.RULE,
        evidence: str | None = None,
    ) -> Flag:
        """Build a Flag with the configured severity for its reason."""
        return Flag(
            mls_number=mls_number,
            field=field,
            reason=reason,
            severity=self.sev(reason),
            origin=origin,
            message=message,
            evidence=evidence,
        )
