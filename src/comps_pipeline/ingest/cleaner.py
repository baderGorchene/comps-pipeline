"""Parse raw strings into typed Comps. Bad values become null Cells plus a Flag, never guesses."""

import calendar
import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import (
    AuditEntry,
    Cell,
    Comp,
    Decision,
    Excluded,
    Flag,
    FlagReason,
    Source,
    StageOutput,
    Subject,
)

STAGE = "clean"


def months_before(day: dt.date, months: int) -> dt.date:
    total = day.year * 12 + (day.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_int(text: str) -> int:
    """'1,850' -> 1850, '$412,500.00' -> 412500. Non-whole numbers raise ValueError."""
    try:
        number = Decimal(text.replace("$", "").replace(",", "").strip())
    except InvalidOperation as e:
        raise ValueError(f"not a number: {text!r}") from e
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"not a whole number: {text!r}")
    return int(number)


def parse_float(text: str) -> float:
    try:
        return float(text.replace(",", "").strip())
    except ValueError as e:
        raise ValueError(f"not a number: {text!r}") from e


def parse_miles(text: str) -> float:
    """'4.0 mi', '0.35 miles', '1.2' -> float miles."""
    t = text.strip().lower()
    for unit in ("miles", "mile", "mi"):
        if t.endswith(unit):
            t = t[: -len(unit)]
            break
    return parse_float(t)


def parse_date(text: str, formats: list[str]) -> dt.date:
    for fmt in formats:
        try:
            return dt.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date {text!r} (accepted formats: {formats})")


class _RowParser:
    """Collects flags while turning one raw row into Cells."""

    def __init__(self, settings: Settings, mls: str, row: dict[str, Any]):
        self.settings, self.mls, self.row = settings, mls, row
        self.flags: list[Flag] = []

    def _bad(self, field: str, reason: FlagReason, message: str) -> Cell:
        raw = self.row.get(field, "")
        self.flags.append(self.settings.flag(reason, self.mls, message, field=field, evidence=raw))
        return Cell(value=None, source=Source.NONE, flag=reason, note=f"raw value: {raw!r}")

    def cell(self, field: str, parse, required: bool = False, check=None) -> Cell:
        raw = str(self.row.get(field, "")).strip()
        if not raw:
            if required:
                return self._bad(field, FlagReason.MISSING_REQUIRED_FIELD, f"{field} is empty")
            return Cell(note="not provided")
        try:
            value = parse(raw)
        except ValueError as e:
            return self._bad(field, FlagReason.INVALID_VALUE, f"{field}: {e}")
        problem = check(value) if check else None
        if problem:
            return self._bad(field, FlagReason.INVALID_VALUE, f"{field}: {problem}")
        return Cell(value=value, source=Source.MLS)


def _positive(v: int) -> str | None:
    return None if v > 0 else f"must be greater than 0, got {v}"


def parse_comp(
    row: dict[str, Any], source_row: int, subject: Subject, settings: Settings, pool: str
) -> tuple[Comp, list[Flag]]:
    """pool 'sold' needs close price/date; 'listing' (active/option/pending) does not."""
    mls = str(row["mls_number"]).strip()
    p = _RowParser(settings, mls, row)
    sold = pool == "sold"
    effective = subject.effective_date
    formats = settings.ingest.date_formats

    def not_future(d: dt.date) -> str | None:
        return f"{d} is after the effective date {effective}" if d > effective else None

    def valid_year(y: int) -> str | None:
        return f"{y} is after the effective date year" if y > effective.year or y <= 0 else None

    def lat_range(v: float) -> str | None:
        return None if -90 <= v <= 90 else f"latitude {v} out of range"

    def lon_range(v: float) -> str | None:
        return None if -180 <= v <= 180 else f"longitude {v} out of range"

    def non_negative(v: float) -> str | None:
        return None if v >= 0 else f"must not be negative, got {v}"

    def positive_float(v: float) -> str | None:
        return None if v > 0 else f"must be greater than 0, got {v}"

    comp = Comp(
        mls_number=mls,
        source_row=source_row,
        pool=pool,
        status=p.cell("status", str),
        close_price=p.cell("close_price", parse_int, required=sold, check=_positive),
        close_date=p.cell(
            "close_date",
            lambda t: parse_date(t, formats),
            required=sold,
            check=not_future if sold else None,
        ),
        list_price=p.cell("list_price", parse_int, check=_positive),
        living_area=p.cell("living_area", parse_int, required=True, check=_positive),
        year_built=p.cell("year_built", parse_int, check=valid_year),
        lot_size_sqft=p.cell("lot_size_sqft", parse_int, check=_positive),
        lot_size_acres=p.cell("lot_size_acres", parse_float, check=positive_float),
        bedrooms=p.cell("bedrooms", parse_int, check=non_negative),
        baths_full=p.cell("baths_full", parse_int, check=non_negative),
        baths_half=p.cell("baths_half", parse_int, check=non_negative),
        subdivision_raw=p.cell("subdivision_raw", str, required=True),
        latitude=p.cell("latitude", parse_float, check=lat_range),
        longitude=p.cell("longitude", parse_float, check=lon_range),
        reported_distance_miles=p.cell("reported_distance_miles", parse_miles, check=non_negative),
        foundation_type=p.cell("foundation_type", str),
        public_remarks=p.cell("public_remarks", str),
        extras=row.get("extras", {}),
    )
    return comp, p.flags


def clean(rows: list[dict[str, Any]], subject: Subject, settings: Settings) -> StageOutput:
    out = StageOutput()
    seen: set[str] = set()

    def exclude(source_row: int, mls: str | None, reason: FlagReason, message: str) -> None:
        out.flags.append(settings.flag(reason, mls, message))
        out.excluded.append(Excluded(source_row, mls, STAGE, [f"{reason.value}: {message}"]))
        out.audit.append(
            AuditEntry(
                mls_number=mls,
                stage=STAGE,
                decision=Decision.EXCLUDED,
                rule=reason.value,
                detail={"source_row": source_row, "message": message},
            )
        )

    for source_row, row in enumerate(rows, start=1):
        mls = str(row.get("mls_number", "")).strip()
        if not mls:
            exclude(source_row, None, FlagReason.MISSING_REQUIRED_FIELD, "mls_number is empty")
            continue
        if mls in seen:
            exclude(
                source_row,
                mls,
                FlagReason.DUPLICATE_LISTING,
                f"MLS number {mls} already seen in an earlier row; first occurrence kept",
            )
            continue
        seen.add(mls)
        status = str(row.get("status", "")).strip()
        pool = settings.status.pool_of(status)
        if pool is None:
            exclude(
                source_row,
                mls,
                FlagReason.STATUS_NOT_USED,
                f"status {status!r} is neither sold nor active/option/pending (config status.*)",
            )
            continue

        comp, flags = parse_comp(row, source_row, subject, settings, pool)
        out.flags.extend(flags)
        for f in flags:
            out.audit.append(
                AuditEntry(
                    mls_number=mls,
                    stage=STAGE,
                    decision=Decision.FLAGGED,
                    rule=f.reason.value,
                    detail={"field": f.field, "message": f.message},
                )
            )
        out.comps.append(comp)

    out.audit.append(
        AuditEntry(
            mls_number=None,
            stage=STAGE,
            decision=Decision.KEPT,
            rule="stage_summary",
            detail={"rows_in": len(rows), "kept": len(out.comps), "excluded": len(out.excluded)},
        )
    )
    return out
