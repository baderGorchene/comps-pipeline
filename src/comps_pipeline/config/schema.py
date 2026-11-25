from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from comps_pipeline.models.comp import STANDARD_FIELDS
from comps_pipeline.models.flag import Flag, FlagOrigin, FlagReason, Severity

RANKING_KEYS = ("subdivision", "distance", "gla", "age", "lot", "beds", "baths")
BRACKET_ATTRIBUTES = ("gla", "lot", "age", "beds", "baths")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSettings(Strict):
    output_dir: Path
    shortlist_size: int = Field(gt=0)
    min_shortlist_size: int = Field(ge=0)  # fewer sold candidates -> escalation, then BLOCKING
    listing_shortlist_size: int = Field(gt=0)


class StatusSettings(Strict):
    """MLS status values (case-insensitive) for each pool. Anything else is excluded."""

    sold: list[str] = Field(min_length=1)
    listing: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _disjoint(self) -> "StatusSettings":
        overlap = {s.upper() for s in self.sold} & {s.upper() for s in self.listing}
        if overlap:
            raise ValueError(f"status values in both sold and listing: {sorted(overlap)}")
        return self

    def pool_of(self, status: str) -> str | None:
        key = status.strip().upper()
        if key in {s.upper() for s in self.sold}:
            return "sold"
        if key in {s.upper() for s in self.listing}:
            return "listing"
        return None


class IngestSettings(Strict):
    date_formats: list[str] = Field(min_length=1)


class FilterSettings(Strict):
    gla_bracket_pct: int = Field(ge=0, le=100)  # int on purpose: boundary math stays exact
    gla_bracket_inclusive: bool
    missing_gla: Literal["exclude", "keep_and_flag"]
    lot_bracket_pct: int = Field(ge=0, le=100)  # measured in acres; int keeps math exact
    lot_bracket_inclusive: bool
    missing_lot: Literal["exclude", "keep_and_flag"]
    max_distance_miles: float = Field(gt=0)
    missing_distance: Literal["exclude", "keep_and_flag"]
    price_bracket_pct: int | None = Field(default=None, ge=0, le=100)
    price_bracket_inclusive: bool = True
    missing_price: Literal["exclude", "keep_and_flag"] = "exclude"
    adjusted_price_bracket_pct: int | None = Field(default=None, ge=0, le=100)
    max_gross_adjustment_pct: float | None = Field(default=None, gt=0, le=200)
    max_age_diff_years: int | None = Field(default=None, ge=0)
    missing_age: Literal["exclude", "keep_and_flag"] = "keep_and_flag"
    require_subdivision_match: bool
    subdivision_min_score: float = Field(ge=0, le=100)
    sale_date_max_months: int = Field(gt=0)  # sold pool only
    missing_close_date: Literal["exclude", "keep_and_flag"]
    required_features: dict[str, str]
    # Master Guidance Hard Gate & Guardrail Controls (safe defaults):
    exclude_distressed: bool = True  # exclude REO, Short Sale, Foreclosure, cash-only fixers
    enforce_55_plus: bool = True  # separate 55+ age-restricted communities from non-restricted
    require_story_match: bool = True  # when both subject and comp report stories, require match
    require_sub_type_match: bool = True  # never mix SFR with mobile/manufactured/condo
    enforce_foundation_compatibility: bool = True  # Slab vs Crawl Space / Pier & Beam
    require_school_district_match: bool = True  # require same ISD when both are known
    require_water_sewer_match: bool = True  # never mix City Sewer with Septic when both are known
    max_active_dom: int = Field(default=365, gt=0)  # filter out stale Active listings over max DOM


class EscalationSettings(Strict):
    """Cumulative filter overrides tried in order while sold candidates < min_shortlist_size."""

    steps: list[dict[str, Any]]

    @field_validator("steps")
    @classmethod
    def _known_keys(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, step in enumerate(v, start=1):
            unknown = [k for k in step if k not in FilterSettings.model_fields]
            if not step or unknown:
                raise ValueError(f"escalation step {i}: empty or unknown filter keys {unknown}")
        return v


class MatchingSettings(Strict):
    noise_words: list[str]


class ToleranceBands(Strict):
    distance_miles: float = Field(gt=0)
    gla_pct: float = Field(gt=0)
    age_years: float = Field(gt=0)
    lot_pct: float = Field(gt=0)
    beds_count: float = Field(gt=0)
    baths_count: float = Field(gt=0)


class RankingSettings(Strict):
    hierarchy: list[str]
    tolerance_bands: ToleranceBands
    holistic_defensibility: bool = True

    @field_validator("hierarchy")
    @classmethod
    def _permutation(cls, v: list[str]) -> list[str]:
        if sorted(v) != sorted(RANKING_KEYS):
            raise ValueError(f"hierarchy must be a permutation of {list(RANKING_KEYS)}, got {v}")
        return v


class ValuationSettings(Strict):
    """Deterministic UAD 3.6 component adjustments for closing vs. adjusted price convergence."""

    enabled: bool = True
    gla_adj_factor: float = Field(default=0.38, ge=0, le=1)
    min_gla_rate: int = Field(default=45, ge=0)
    max_gla_rate: int = Field(default=120, ge=0)
    gla_deadband_sqft: int = Field(default=50, ge=0)
    lot_deadband_pct: float = Field(default=10.0, ge=0, le=100)
    max_lot_adj_pct: float = Field(default=15.0, ge=0, le=100)
    bedroom_adj_pct: float = Field(default=0.008, ge=0, le=0.2)
    min_bedroom_adj: int = Field(default=2500, ge=0)
    full_bath_adj_pct: float = Field(default=0.012, ge=0, le=0.2)
    min_full_bath_adj: int = Field(default=5000, ge=0)
    garage_adj_pct: float = Field(default=0.015, ge=0, le=0.2)
    min_garage_adj: int = Field(default=4000, ge=0)
    pool_adj_pct: float = Field(default=0.033, ge=0, le=0.3)
    min_pool_adj: int = Field(default=12000, ge=0)
    max_pool_adj: int = Field(default=35000, ge=0)
    adu_adj_pct: float = Field(default=0.047, ge=0, le=0.3)
    min_adu_adj: int = Field(default=15000, ge=0)
    max_adu_adj: int = Field(default=45000, ge=0)


class SelectionSettings(Strict):
    """Final pick: sold_count sold + listing_count active/option/pending, subject bracketed."""

    sold_count: int = Field(gt=0)
    listing_count: int = Field(ge=0)
    bracket_attributes: list[str]
    # false = the rule as written: one comp strictly above AND one strictly below.
    equal_counts_as_bracketed: bool
    # Guardrails so bracketing swaps never pull in extreme price or age outliers.
    max_swap_price_diff_pct: int | None = Field(default=18, ge=0, le=100)
    max_swap_age_diff_years: int | None = Field(default=15, ge=0)
    max_swap_rank_gap: int | None = Field(default=8, ge=1)

    @field_validator("bracket_attributes")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = [a for a in v if a not in BRACKET_ATTRIBUTES]
        if unknown or len(set(v)) != len(v):
            raise ValueError(
                f"bracket_attributes must be unique values of {list(BRACKET_ATTRIBUTES)}"
            )
        return v


class VisionSettings(Strict):
    enabled: bool = False
    max_photos_per_property: int = Field(default=25, gt=0)
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    rerank_min_delta: int = Field(default=2, gt=0)
    photo_columns: list[str] = Field(
        default_factory=lambda: ["Photo URLs", "PhotoURLs", "Photos", "Media URLs", "Image URLs"]
    )


class SecondRoundSettings(Strict):
    """ "Find more comps": drop unusable shortlist comps, refill from near misses, pick again."""

    auto: bool = True  # run it automatically when picks come up short (else: button in the UI)
    extra_relax_steps: int = Field(default=1, ge=0)  # how far past round 1's level to look
    fill_to_pick_count: bool = True  # still short? top up with flagged out-of-rules comps
    never_relax: list[str] = Field(default_factory=lambda: ["property_sub_type"])
    remove_if_flagged: list[FlagReason] = Field(
        default_factory=lambda: [
            FlagReason.VISUAL_QC_MISMATCH,
            FlagReason.VISUAL_REMARKS_MISMATCH,
            FlagReason.NON_CONFORMING_CONVERSION,
        ]
    )


class Settings(Strict):
    run: RunSettings
    ingest: IngestSettings
    status: StatusSettings
    filters: FilterSettings
    escalation: EscalationSettings
    matching: MatchingSettings
    ranking: RankingSettings
    valuation: ValuationSettings = Field(default_factory=ValuationSettings)
    selection: SelectionSettings
    vision: VisionSettings = Field(default_factory=VisionSettings)
    second_round: SecondRoundSettings = Field(default_factory=SecondRoundSettings)
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
        for level in range(1, len(self.escalation.steps) + 1):
            self.filters_at(level)  # every cumulative step must itself be valid
        return self

    def filters_at(self, level: int) -> FilterSettings:
        """Filters with the first `level` escalation steps applied cumulatively (0 = baseline)."""
        merged = self.filters.model_dump()
        for step in self.escalation.steps[:level]:
            merged.update(step)
        return FilterSettings.model_validate(merged)

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
