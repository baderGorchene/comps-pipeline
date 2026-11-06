"""Pydantic schemas for structured LLM parsing across AI pipeline tasks."""

from typing import Literal

from pydantic import BaseModel, Field


class LeaseAnalysisResult(BaseModel):
    has_lease_indicator: bool = False
    lease_phrases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""


class OwnerClassificationResult(BaseModel):
    owner_type: Literal["BUILDER", "INDIVIDUAL"] = "INDIVIDUAL"
    confidence: float = 0.0
    reasoning: str = ""


class CompRejectionJustification(BaseModel):
    mls_number: str
    justification: str


class VisionScore(BaseModel):
    """Photo-based UAD Q/C verdict for one property (subject or shortlisted comp)."""

    visual_condition_rating: Literal["C1", "C2", "C3", "C4", "C5", "C6"]
    visual_quality_rating: Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    detected_features: list[str] = Field(default_factory=list)
    photo_categories: list[str] = Field(default_factory=list)  # EXTERIOR_FRONT, KITCHEN, ...
    remarks_mismatch_flag: bool = False
    mismatch_detail: str = ""
    photos_analyzed: int = 0
    model_used: str = ""


class RunOverviewResult(BaseModel):
    executive_summary: str = ""
    search_parameters_analysis: str = ""
    bracketing_evaluation: str = ""
    new_construction_and_flags_review: str = ""
    valuation_bracket_conclusion: str = ""
    indicated_value_low: int | None = None
    indicated_value_high: int | None = None
    model_used: str = "gpt-6.1-terra"


