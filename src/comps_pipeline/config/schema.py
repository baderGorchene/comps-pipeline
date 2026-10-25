from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from comps_pipeline.models.comp import STANDARD_FIELDS
from comps_pipeline.models.flag import Flag, FlagOrigin, FlagReason, Severity

RANKING_KEYS = ("subdivision", "distance", "gla", "age", "lot")

DEFAULT_SEVERITY: dict[FlagReason, Severity] = {
    FlagReason.MISSING_REQUIRED_FIELD: Severity.REVIEW,
    FlagReason.INVALID_VALUE: Severity.REVIEW,
    FlagReason.DUPLICATE_LISTING: Severity.INFO,
    FlagReason.OUT_OF_DATE_RANGE: Severity.INFO,
    FlagReason.NO_COORDINATES: Severity.REVIEW,
    FlagReason.SUBDIVISION_UNCERTAIN: Severity.REVIEW,
    FlagReason.POSSIBLE_NON_ARMS_LENGTH: Severity.REVIEW,
    FlagReason.REMARKS_CONCERN: Severity.REVIEW,
    FlagReason.SHORTLIST_BELOW_MINIMUM: Severity.BLOCKING,
    FlagReason.LLM_SCHEMA_FAILURE: Severity.REVIEW,
    FlagReason.LLM_UNKNOWN_ID: Severity.INFO,
    FlagReason.LLM_EVIDENCE_NOT_FOUND: Severity.INFO,
    FlagReason.LLM_DISALLOWED_REASON: Severity.INFO,
    FlagReason.LLM_UNAVAILABLE: Severity.INFO,
    FlagReason.INSUFFICIENT_EVIDENCE: Severity.REVIEW,
    FlagReason.ADJACENT_DISAGREEMENT: Severity.REVIEW,
    FlagReason.CONFLICTING_EVIDENCE: Severity.REVIEW,
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSettings(Strict):
    output_dir: Path = Path("data/output")
    shortlist_size: int = Field(30, gt=0)
    min_shortlist_size: int = Field(25, ge=0)


class IngestSettings(Strict):
    date_formats: list[str] = Field(
        default_factory=lambda: ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"], min_length=1
    )


class FilterSettings(Strict):
    gla_bracket_pct: int = Field(30, ge=0, le=100)  # int on purpose: boundary math stays exact
    gla_bracket_inclusive: bool = True
    missing_gla: Literal["exclude", "keep_and_flag"] = "exclude"
    max_distance_miles: float = Field(1.0, gt=0)
    missing_distance: Literal["exclude", "keep_and_flag"] = "exclude"
    require_subdivision_match: bool = True
    subdivision_min_score: float = Field(90, ge=0, le=100)
    sale_date_max_months: int = Field(12, gt=0)
    required_features: dict[str, str] = Field(default_factory=dict)


class MatchingSettings(Strict):
    noise_words: list[str] = Field(
        default_factory=lambda: ["SUBDIVISION", "SUBD", "SUB", "ADDN", "ADDITION"]
    )


class ToleranceBands(Strict):
    distance_miles: float = Field(0.25, gt=0)
    gla_pct: float = Field(5, gt=0)
    age_years: float = Field(5, gt=0)
    lot_pct: float = Field(10, gt=0)


class RankingSettings(Strict):
    hierarchy: list[str] = Field(default_factory=lambda: list(RANKING_KEYS))
    tolerance_bands: ToleranceBands = Field(default_factory=ToleranceBands)

    @field_validator("hierarchy")
    @classmethod
    def _permutation(cls, v: list[str]) -> list[str]:
        if sorted(v) != sorted(RANKING_KEYS):
            raise ValueError(f"hierarchy must be a permutation of {list(RANKING_KEYS)}, got {v}")
        return v


class LLMSettings(Strict):
    enabled: bool = True
    provider: Literal["gemini", "mock"] = "gemini"
    mock_mode: Literal["clean", "hallucinate_id", "fake_quote", "malformed", "error"] = "clean"
    model_env: str = "GEMINI_MODEL"
    api_key_env: str = "GEMINI_API_KEY"
    temperature: float = Field(0, ge=0, le=2)
    max_retries: int = Field(1, ge=0)
    batch_size: int = Field(10, gt=0)
    fields_sent: list[str] = Field(
        default_factory=lambda: [
            "mls_number",
            "subdivision_raw",
            "public_remarks",
            "close_price",
            "close_date",
        ]
    )
    cache: bool = True
    cache_dir: Path = Path("data/cache")

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
    require_evidence_quote: bool = True


class Settings(Strict):
    run: RunSettings = Field(default_factory=RunSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    ranking: RankingSettings = Field(default_factory=RankingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    # Partial overrides allowed; missing reasons fall back to DEFAULT_SEVERITY.
    severity: dict[FlagReason, Severity] = Field(default_factory=dict)
    # Loaded from the files next to settings.yaml, not from settings.yaml itself.
    column_mapping: dict[str, list[str]] = Field(default_factory=dict)
    subdivision_aliases: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("severity")
    @classmethod
    def _fill_severity(cls, v: dict[FlagReason, Severity]) -> dict[FlagReason, Severity]:
        return {**DEFAULT_SEVERITY, **v}

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
