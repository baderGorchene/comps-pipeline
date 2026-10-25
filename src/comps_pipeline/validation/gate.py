"""The only door from LLM output to pipeline output.

Checks, per batch then per item:
  a) the response parses against ReviewResponse (review.py already retried once with the
     error appended; a second failure becomes LLM_SCHEMA_FAILURE for the batch)
  b) mls_number is one of the batch's IDs, else LLM_UNKNOWN_ID
  c) evidence_quote is a case-insensitive, whitespace-normalized substring of that comp's
     public_remarks or subdivision_raw, else LLM_EVIDENCE_NOT_FOUND
  d) reason is in the allowed set, else LLM_DISALLOWED_REASON
The gate only creates flags. It never touches comps, values or ranks.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from comps_pipeline.config.schema import Settings
from comps_pipeline.llm.base import LLMResult
from comps_pipeline.llm.review import ALLOWED_REASONS, ReviewFlag, ReviewResponse
from comps_pipeline.models import AuditEntry, Comp, Decision, Flag, FlagOrigin, FlagReason

STAGE = "validation_gate"
QUOTE_FIELDS = ("public_remarks", "subdivision_raw")


@dataclass
class GateOutput:
    accepted_flags: list[Flag] = field(default_factory=list)
    gate_flags: list[Flag] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def find_quote(quote: str, comp: Comp) -> str | None:
    """Name of the field that contains the quote, or None."""
    q = _norm(quote)
    if not q:
        return None
    for name in QUOTE_FIELDS:
        value = getattr(comp, name).value
        if value and q in _norm(value):
            return name
    return None


def _check_item(
    item: ReviewFlag, ids: dict[str, Comp], settings: Settings
) -> tuple[list[tuple[FlagReason, str]], str | None]:
    problems: list[tuple[FlagReason, str]] = []
    comp = ids.get(item.mls_number)
    if comp is None:
        problems.append((FlagReason.LLM_UNKNOWN_ID, f"mls_number {item.mls_number!r} not in batch"))
    if item.reason not in ALLOWED_REASONS:
        problems.append((FlagReason.LLM_DISALLOWED_REASON, f"reason {item.reason!r} not allowed"))
    quote_field = find_quote(item.evidence_quote, comp) if comp else None
    if comp is not None and quote_field is None and settings.validation.require_evidence_quote:
        problems.append(
            (
                FlagReason.LLM_EVIDENCE_NOT_FOUND,
                f"evidence_quote not found in {item.mls_number}'s {' or '.join(QUOTE_FIELDS)}",
            )
        )
    return problems, quote_field


def validate_review(
    result: LLMResult,
    batch: list[Comp],
    settings: Settings,
    batch_index: int = 0,
    attempts: int = 1,
) -> GateOutput:
    out = GateOutput()
    batch_ids = [c.mls_number for c in batch]

    def audit(decision: Decision, rule: str, mls: str | None = None, **detail: object) -> None:
        out.audit.append(
            AuditEntry(
                mls_number=mls,
                stage=STAGE,
                decision=decision,
                rule=rule,
                detail={"batch": batch_index, **detail},
            )
        )

    if result.raw_text is None:
        msg = f"LLM call failed for batch {batch_index} ({len(batch)} comps): {result.error}"
        out.gate_flags.append(
            settings.flag(FlagReason.LLM_UNAVAILABLE, None, msg, origin=FlagOrigin.GATE)
        )
        audit(Decision.FLAGGED, FlagReason.LLM_UNAVAILABLE.value, message=msg, batch_ids=batch_ids)
        return out

    try:
        response = ReviewResponse.model_validate_json(result.raw_text)
    except ValidationError as e:
        msg = (
            f"batch {batch_index} ({len(batch)} comps) failed schema validation after "
            f"{attempts} attempt(s); not reviewed. {e.error_count()} error(s)"
        )
        out.gate_flags.append(
            settings.flag(
                FlagReason.LLM_SCHEMA_FAILURE,
                None,
                msg,
                origin=FlagOrigin.GATE,
                evidence=result.raw_text[:2000],
            )
        )
        audit(
            Decision.FLAGGED, FlagReason.LLM_SCHEMA_FAILURE.value, message=msg, batch_ids=batch_ids
        )
        return out

    ids = {c.mls_number: c for c in batch}
    for item in response.flags:
        problems, quote_field = _check_item(item, ids, settings)
        known = item.mls_number if item.mls_number in ids else None
        if problems:
            reason, _ = problems[0]
            message = "; ".join(p for _, p in problems)
            out.gate_flags.append(
                settings.flag(
                    reason,
                    known,
                    f"rejected LLM flag: {message}",
                    origin=FlagOrigin.GATE,
                    evidence=item.model_dump_json(),
                )
            )
            audit(
                Decision.EXCLUDED,
                reason.value,
                known,
                problems=[r.value for r, _ in problems],
                rejected=item.model_dump(),
            )
            continue
        out.accepted_flags.append(
            settings.flag(
                FlagReason(item.reason),
                item.mls_number,
                item.comment,
                field=quote_field,
                origin=FlagOrigin.LLM,
                evidence=item.evidence_quote,
            )
        )
        audit(Decision.FLAGGED, item.reason, item.mls_number, accepted=item.model_dump())
    audit(
        Decision.KEPT,
        "batch_summary",
        accepted=len(out.accepted_flags),
        rejected=len(out.gate_flags),
        attempts=attempts,
        model=result.model,
    )
    return out
