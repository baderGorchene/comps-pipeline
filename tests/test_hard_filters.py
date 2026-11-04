import datetime as dt
from fractions import Fraction

import pytest

from comps_pipeline.filters.hard_filters import (
    apply_hard_filters,
    distance_filter,
    gla_filter,
    gla_in_bracket,
    lot_filter,
    lot_in_bracket,
    price_filter,
    price_in_bracket,
    required_features_filter,
    sale_date_filter,
)
from comps_pipeline.models import Cell
from tests.conftest import make_comp, with_filters


@pytest.mark.parametrize(
    ("gla", "inclusive", "kept"),
    [
        (1500, True, True),  # exact lower boundary (25%)
        (1499, True, False),
        (1501, True, True),
        (2500, True, True),  # exact upper boundary
        (2501, True, False),
        (2499, True, True),
        (1500, False, False),
        (1501, False, True),
        (2500, False, False),
        (2499, False, True),
    ],
)
def test_gla_boundaries(subject, settings, gla, inclusive, kept):
    s = with_filters(settings, gla_bracket_inclusive=inclusive)
    res = gla_filter([make_comp("1", living_area=gla)], subject, s)
    assert bool(res.kept) is kept


def test_gla_integer_math_avoids_float_boundary_bug():
    # Float math: 1000 * (1 - 0.18) == 820.0000000000001, which would wrongly drop 820,
    # and 1000 * (1 + 0.36) == 1359.9999999999998, which would wrongly drop 1360.
    assert 1000 * (1 - 0.18) > 820 and 1000 * (1 + 0.36) < 1360
    assert gla_in_bracket(820, 1000, 18, inclusive=True)
    assert gla_in_bracket(1360, 1000, 36, inclusive=True)
    assert not gla_in_bracket(819, 1000, 18, inclusive=True)
    assert not gla_in_bracket(1361, 1000, 36, inclusive=True)


def test_missing_gla_follows_config(subject, settings):
    comp = make_comp("1", living_area=None)
    assert not gla_filter([comp], subject, settings).kept
    kept = gla_filter([comp], subject, with_filters(settings, missing_gla="keep_and_flag"))
    assert kept.kept and kept.audit[0].decision == "FLAGGED"


def _at(miles):
    c = make_comp("1")
    return c.model_copy(update={"distance_miles": Cell(value=miles, source="COMPUTED")})


def test_distance_filter(subject, settings):
    limit = settings.filters.max_distance_miles
    assert distance_filter([_at(limit)], subject, settings).kept
    assert not distance_filter([_at(limit + 0.0001)], subject, settings).kept
    assert not distance_filter([_at(None)], subject, settings).kept
    s = with_filters(settings, missing_distance="keep_and_flag")
    assert distance_filter([_at(None)], subject, s).kept


def test_required_features(subject, settings):
    s = with_filters(settings, required_features={"foundation_type": "Crawl Space", "Pool": "Y"})
    ok = make_comp("1", foundation_type="crawl space ").model_copy(update={"extras": {"Pool": "Y"}})
    bad = make_comp("2", foundation_type="Slab")
    res = required_features_filter([ok, bad], subject, s)
    assert [c.mls_number for c in res.kept] == ["1"]
    assert "foundation_type" in res.audit[0].detail["message"]
    assert "Pool" in res.audit[0].detail["message"]


def test_audit_records_every_failing_rule(subject, settings):
    comp = make_comp("9", living_area=5000).model_copy(
        update={
            "distance_miles": Cell(value=6.0, source="COMPUTED"),
            "subdivision_tier": Cell(value=3, source="COMPUTED"),
        }
    )
    out = apply_hard_filters(
        [comp], subject, with_filters(settings, require_subdivision_match=True)
    )
    assert not out.comps
    (ex,) = out.excluded
    rules = {r.split(":")[0] for r in ex.reasons}
    assert rules == {"gla_bracket", "max_distance", "subdivision_match"}


def test_subdivision_not_required_by_default(subject, settings):
    comp = make_comp("9", living_area=2000).model_copy(
        update={
            "distance_miles": Cell(value=1.0, source="COMPUTED"),
            "subdivision_tier": Cell(value=3, source="COMPUTED"),
        }
    )
    assert apply_hard_filters([comp], subject, settings).comps


def test_lot_bracket_in_acres(subject, settings):
    # subject lot 8000 sqft; 25% band = 6000..10000 sqft, compared in exact acres
    assert lot_in_bracket(Fraction(6000, 43560), Fraction(8000, 43560), 25, inclusive=True)
    assert not lot_in_bracket(Fraction(5999, 43560), Fraction(8000, 43560), 25, inclusive=True)
    acres_ok = make_comp("1", lot_size_acres=0.2)  # 8712 sqft
    too_big = make_comp("2", lot_size_sqft=10001)
    unknown = make_comp("3")
    res = lot_filter([acres_ok, too_big, unknown], subject, settings)
    assert [c.mls_number for c in res.kept] == ["1", "3"]  # missing_lot: keep_and_flag
    res = lot_filter([unknown], subject, with_filters(settings, missing_lot="exclude"))
    assert not res.kept


def test_sale_date_window_sold_only(subject, settings):
    def sold(mls, day):
        return make_comp(mls, close_date=day).model_copy(update={"pool": "sold"})

    listing = make_comp("L").model_copy(update={"pool": "listing"})
    comps = [sold("old", dt.date(2025, 9, 30)), sold("edge", dt.date(2025, 10, 1)), listing]
    res = sale_date_filter(comps, subject, settings)
    assert [c.mls_number for c in res.kept] == ["edge", "L"]  # exactly 12 months is kept
    res = sale_date_filter(comps, subject, with_filters(settings, sale_date_max_months=24))
    assert len(res.kept) == 3


@pytest.mark.parametrize(
    ("price", "inclusive", "kept"),
    [
        (200_000, True, True),   # exact lower boundary (50% of 400k)
        (199_999, True, False),
        (200_001, True, True),
        (600_000, True, True),   # exact upper boundary (50% of 400k)
        (600_001, True, False),
        (599_999, True, True),
        (200_000, False, False),
        (200_001, False, True),
        (600_000, False, False),
        (599_999, False, True),
    ],
)
def test_price_boundaries(subject, settings, price, inclusive, kept):
    subj = subject.model_copy(update={"contract_price": 400_000})
    s = with_filters(settings, price_bracket_pct=50, price_bracket_inclusive=inclusive)
    comp = make_comp("1", close_price=price).model_copy(update={"pool": "sold"})
    res = price_filter([comp], subj, s)
    assert bool(res.kept) is kept


def test_price_outliers_dropped(subject, settings):
    subj = subject.model_copy(update={"contract_price": 400_000})
    c_low = make_comp("outlier_low", close_price=100_000).model_copy(update={"pool": "sold"})
    c_high = make_comp("outlier_high", close_price=2_000_000).model_copy(update={"pool": "sold"})
    c_good = make_comp("good_comp", close_price=380_000).model_copy(update={"pool": "sold"})
    c_active = make_comp("good_active", list_price=410_000).model_copy(update={"pool": "listing"})
    c_active_high = make_comp("active_high", list_price=1_500_000).model_copy(update={"pool": "listing"})

    res = price_filter([c_low, c_high, c_good, c_active, c_active_high], subj, settings)
    assert [c.mls_number for c in res.kept] == ["good_comp", "good_active"]
    assert len(res.audit) == 3
    for a in res.audit:
        assert a.decision == "EXCLUDED"
        assert a.rule == "price_bracket"


def test_price_missing_handling(subject, settings):
    subj = subject.model_copy(update={"contract_price": 400_000})
    comp = make_comp("noprice")
    # Default is missing_price: exclude
    res = price_filter([comp], subj, settings)
    assert not res.kept
    assert res.audit[0].decision == "EXCLUDED"

    # keep_and_flag
    s = with_filters(settings, missing_price="keep_and_flag")
    res2 = price_filter([comp], subj, s)
    assert len(res2.kept) == 1
    assert res2.audit[0].decision == "FLAGGED"


def test_price_filter_skipped_without_subject_benchmark(subject, settings):
    # subject fixture has no contract_price or estimated_value
    assert subject.benchmark_price is None
    c_low = make_comp("outlier_low", close_price=100_000)
    c_high = make_comp("outlier_high", close_price=2_000_000)
    res = price_filter([c_low, c_high], subject, settings)
    assert len(res.kept) == 2

