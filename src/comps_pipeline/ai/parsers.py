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


class RunOverviewResult(BaseModel):
    executive_summary: str = ""
    search_parameters_analysis: str = ""
    bracketing_evaluation: str = ""
    new_construction_and_flags_review: str = ""
    valuation_bracket_conclusion: str = ""
    indicated_value_low: int | None = None
    indicated_value_high: int | None = None
    model_used: str = "gpt-6.1-terra"


