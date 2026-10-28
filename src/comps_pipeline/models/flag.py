from enum import StrEnum

from pydantic import BaseModel


class Source(StrEnum):
    MLS = "MLS"
    COMPUTED = "COMPUTED"
    NONE = "NONE"


class FlagReason(StrEnum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_VALUE = "INVALID_VALUE"
    DUPLICATE_LISTING = "DUPLICATE_LISTING"
    NO_COORDINATES = "NO_COORDINATES"
    SUBDIVISION_UNCERTAIN = "SUBDIVISION_UNCERTAIN"
    SHORTLIST_BELOW_MINIMUM = "SHORTLIST_BELOW_MINIMUM"
    STATUS_NOT_USED = "STATUS_NOT_USED"  # expired/withdrawn/unknown status
    CRITERIA_RELAXED = "CRITERIA_RELAXED"  # escalation step applied
    NOT_BRACKETED = "NOT_BRACKETED"  # final selection misses above/below on an attribute
    NO_LISTING_COMP = "NO_LISTING_COMP"  # no active/option/pending comp for the final pick


class Severity(StrEnum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCKING = "BLOCKING"


class FlagOrigin(StrEnum):
    RULE = "RULE"


class Flag(BaseModel):
    id: str = ""  # assigned sequentially by the pipeline once all stages ran
    mls_number: str | None  # "SUBJECT" for the subject property, None = run-level
    field: str | None = None
    reason: FlagReason
    severity: Severity
    origin: FlagOrigin
    message: str
    evidence: str | None = None
