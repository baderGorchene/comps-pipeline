from enum import StrEnum

from pydantic import BaseModel


class Source(StrEnum):
    MLS = "MLS"
    COUNTY = "COUNTY"
    COMPUTED = "COMPUTED"
    VISION = "VISION"
    MANUAL = "MANUAL"
    NONE = "NONE"


class FlagReason(StrEnum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_VALUE = "INVALID_VALUE"
    DUPLICATE_LISTING = "DUPLICATE_LISTING"
    OUT_OF_DATE_RANGE = "OUT_OF_DATE_RANGE"
    NO_COORDINATES = "NO_COORDINATES"
    SUBDIVISION_UNCERTAIN = "SUBDIVISION_UNCERTAIN"
    POSSIBLE_NON_ARMS_LENGTH = "POSSIBLE_NON_ARMS_LENGTH"
    REMARKS_CONCERN = "REMARKS_CONCERN"
    SHORTLIST_BELOW_MINIMUM = "SHORTLIST_BELOW_MINIMUM"
    LLM_SCHEMA_FAILURE = "LLM_SCHEMA_FAILURE"
    LLM_UNKNOWN_ID = "LLM_UNKNOWN_ID"
    LLM_EVIDENCE_NOT_FOUND = "LLM_EVIDENCE_NOT_FOUND"
    LLM_DISALLOWED_REASON = "LLM_DISALLOWED_REASON"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    # Reserved for Phase 2 (condition engine); defined now, unused.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ADJACENT_DISAGREEMENT = "ADJACENT_DISAGREEMENT"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class Severity(StrEnum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCKING = "BLOCKING"


class FlagOrigin(StrEnum):
    RULE = "RULE"
    LLM = "LLM"
    GATE = "GATE"


class Flag(BaseModel):
    id: str = ""  # assigned sequentially by the pipeline once all stages ran
    mls_number: str | None  # "SUBJECT" for the subject property, None = run-level
    field: str | None = None
    reason: FlagReason
    severity: Severity
    origin: FlagOrigin
    message: str
    evidence: str | None = None
