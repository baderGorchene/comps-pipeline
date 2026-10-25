from comps_pipeline.models import AuditEntry, Cell, FlagReason
from comps_pipeline.ranking.ranker import rank
from tests.conftest import make_comp


def comp(mls, tier=0, miles=0.1, gla=2000, year=2005, lot=8000):
    c = make_comp(mls, living_area=gla, year_built=year, lot_size_sqft=lot)
    return c.model_copy(
        update={
            "subdivision_tier": Cell(value=tier, source="COMPUTED"),
            "distance_miles": Cell(value=miles, source="COMPUTED"),
        }
    )


def order(out):
    return [c.mls_number for c in out.ranked]


def test_tolerance_band_lets_gla_decide(subject, settings):
    # 0.31 and 0.32 mi share the 0.25-0.50 band, so GLA (next key) decides, not distance.
    near_but_bigger = comp("A", miles=0.31, gla=2300)
    farther_but_closer_gla = comp("B", miles=0.32, gla=2010)
    out = rank([near_but_bigger, farther_but_closer_gla], subject, settings)
    assert order(out) == ["B", "A"]


def test_hierarchy_order_changes_ranking(subject, settings):
    same_sub_far = comp("A", tier=0, miles=0.9)
    fuzzy_sub_near = comp("B", tier=2, miles=0.05)
    assert order(rank([same_sub_far, fuzzy_sub_near], subject, settings)) == ["A", "B"]
    s = settings.model_copy(
        update={
            "ranking": settings.ranking.model_copy(
                update={"hierarchy": ["distance", "subdivision", "gla", "age", "lot"]}
            )
        }
    )
    assert order(rank([same_sub_far, fuzzy_sub_near], subject, s)) == ["B", "A"]


def test_final_tie_breakers(subject, settings):
    a = comp("A", miles=0.12)
    b = comp("B", miles=0.11)
    c = comp("C", miles=0.11)  # identical to B except mls_number
    assert order(rank([a, c, b], subject, settings)) == ["B", "C", "A"]


def test_missing_values_sort_last_and_are_flagged(subject, settings):
    missing_year = comp("A", year=None)
    complete = comp("B", year=2030)  # 25 years off is still better than unknown
    out = rank([missing_year, complete], subject, settings)
    assert order(out) == ["B", "A"]
    a = out.ranked[1]
    assert a.age_diff_years.value is None
    assert a.age_diff_years.flag is FlagReason.MISSING_REQUIRED_FIELD
    assert a.year_built.value is None  # never imputed
    assert any(f.mls_number == "A" and f.field == "year_built" for f in out.flags)


def test_sort_key_stored_and_ranks_assigned(subject, settings):
    out = rank([comp("A"), comp("B", miles=0.6)], subject, settings)
    assert [c.rank for c in out.ranked] == [1, 2]
    assert out.ranked[0].sort_key[-1] == "A"
    assert out.audit[0].detail["sort_key"] == out.ranked[0].sort_key


def test_shortlist_size_and_minimum(subject, settings):
    s = settings.model_copy(
        update={
            "run": settings.run.model_copy(update={"shortlist_size": 2, "min_shortlist_size": 2})
        }
    )
    out = rank([comp(str(i), miles=0.1 * i) for i in range(1, 4)], subject, s)
    assert [c.mls_number for c in out.shortlist] == ["1", "2"]
    assert "RANK_BEYOND_SHORTLIST" in out.excluded[0].reasons[0]
    assert not [f for f in out.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]

    prior = [
        AuditEntry(mls_number="x", stage="hard_filters", decision="EXCLUDED", rule="gla_bracket"),
        AuditEntry(mls_number="y", stage="hard_filters", decision="EXCLUDED", rule="max_distance"),
        AuditEntry(mls_number="z", stage="hard_filters", decision="EXCLUDED", rule="max_distance"),
    ]
    out = rank([comp("1")], subject, s, prior)
    (flag,) = [f for f in out.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]
    assert flag.mls_number is None and "max_distance (2 rows)" in flag.message
