import datetime as dt

import pytest

from comps_pipeline.ingest.cleaner import clean, months_before, parse_int
from comps_pipeline.models import FlagReason


def raw(mls="100", **overrides):
    row = {
        "mls_number": mls,
        "status": "Closed",
        "close_price": "$412,500",
        "close_date": "06/15/2026",
        "living_area": "1,980",
        "year_built": "2004",
        "lot_size_sqft": "7800",
        "subdivision_raw": "Brushy Creek Phase 2",
        "latitude": "30.51",
        "longitude": "-97.68",
        "foundation_type": "Slab",
        "public_remarks": "Nice home",
        "extras": {"Pool": "N"},
    }
    row.update(overrides)
    return row


def reasons(out, mls):
    return {(f.field, f.reason) for f in out.flags if f.mls_number == mls}


def test_parses_money_numbers_dates(subject, settings):
    out = clean([raw(close_price="$412,500.00")], subject, settings)
    (c,) = out.comps
    assert c.close_price.value == 412500
    assert c.living_area.value == 1980
    assert c.close_date.value == dt.date(2026, 6, 15)
    assert c.extras == {"Pool": "N"}
    assert not out.flags


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1850.5"])
def test_bad_living_area_is_null_and_flagged(subject, settings, bad):
    out = clean([raw(living_area=bad)], subject, settings)
    (c,) = out.comps
    assert c.living_area.value is None
    assert c.living_area.flag is FlagReason.INVALID_VALUE
    assert ("living_area", FlagReason.INVALID_VALUE) in reasons(out, "100")


def test_missing_values_are_flagged_never_imputed(subject, settings):
    out = clean([raw(living_area="", close_price="", year_built="")], subject, settings)
    (c,) = out.comps
    assert c.living_area.value is None and c.close_price.value is None
    assert c.year_built.value is None
    r = reasons(out, "100")
    assert ("living_area", FlagReason.MISSING_REQUIRED_FIELD) in r
    assert ("close_price", FlagReason.MISSING_REQUIRED_FIELD) in r


def test_future_close_date_invalid(subject, settings):
    out = clean([raw(close_date="10/21/2026")], subject, settings)
    (c,) = out.comps
    assert c.close_date.value is None
    assert ("close_date", FlagReason.INVALID_VALUE) in reasons(out, "100")


def test_status_decides_pool(subject, settings):
    rows = [
        raw("1", status="S"),
        raw("2", status="Active", close_price="", close_date=""),
        raw("3", status="option pending", close_price="", close_date=""),
        raw("4", status="Expired"),
        raw("5", status=""),
    ]
    out = clean(rows, subject, settings)
    assert [(c.mls_number, c.pool) for c in out.comps] == [
        ("1", "sold"),
        ("2", "listing"),
        ("3", "listing"),
    ]
    assert not reasons(out, "2")  # listings need no close price/date
    assert [e.mls_number for e in out.excluded] == ["4", "5"]
    assert all("STATUS_NOT_USED" in e.reasons[0] for e in out.excluded)


def test_reported_distance_and_rooms_parsed(subject, settings):
    row = raw(reported_distance_miles="4.0 mi", bedrooms="3", baths_full="2", baths_half="1")
    (c,) = clean([row], subject, settings).comps
    assert c.reported_distance_miles.value == 4.0
    assert c.total_baths() == 2.5 and c.bedrooms.value == 3


def test_duplicates_keep_first(subject, settings):
    out = clean([raw("7"), raw("8"), raw("7", living_area="999")], subject, settings)
    assert [c.mls_number for c in out.comps] == ["7", "8"]
    assert out.comps[0].living_area.value == 1980
    (ex,) = out.excluded
    assert ex.source_row == 3 and "DUPLICATE_LISTING" in ex.reasons[0]


def test_every_exclusion_has_audit_entry(subject, settings):
    rows = [raw(""), raw("1"), raw("1"), raw("2", status="Withdrawn")]
    out = clean(rows, subject, settings)
    excluded_audit = [a for a in out.audit if a.decision == "EXCLUDED"]
    assert len(excluded_audit) == len(out.excluded) == 3


def test_months_before_clamps_day():
    assert months_before(dt.date(2026, 3, 31), 1) == dt.date(2026, 2, 28)
    assert months_before(dt.date(2026, 10, 1), 12) == dt.date(2025, 10, 1)


def test_parse_int_rejects_fractions():
    assert parse_int("$1,234.00") == 1234
    with pytest.raises(ValueError):
        parse_int("12.5")
