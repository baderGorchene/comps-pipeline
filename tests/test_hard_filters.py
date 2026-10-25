import pytest

from comps_pipeline.filters.hard_filters import (
    apply_hard_filters,
    distance_filter,
    gla_filter,
    gla_in_bracket,
    required_features_filter,
)
from comps_pipeline.models import Cell
from tests.conftest import make_comp, with_filters


@pytest.mark.parametrize(
    ("gla", "inclusive", "kept"),
    [
        (1400, True, True),  # exact lower boundary
        (1399, True, False),
        (1401, True, True),
        (2600, True, True),  # exact upper boundary
        (2601, True, False),
        (2599, True, True),
        (1400, False, False),
        (1401, False, True),
        (2600, False, False),
        (2599, False, True),
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
    assert distance_filter([_at(1.0)], subject, settings).kept
    assert not distance_filter([_at(1.0001)], subject, settings).kept
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
            "distance_miles": Cell(value=3.0, source="COMPUTED"),
            "subdivision_tier": Cell(value=3, source="COMPUTED"),
        }
    )
    out = apply_hard_filters([comp], subject, settings)
    assert not out.comps
    (ex,) = out.excluded
    rules = {r.split(":")[0] for r in ex.reasons}
    assert rules == {"gla_bracket", "max_distance", "subdivision_match"}
