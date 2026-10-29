from comps_pipeline.models import AuditEntry, Cell, FlagReason
from comps_pipeline.ranking.ranker import rank
from tests.conftest import make_comp


def comp(mls, tier=0, miles=0.1, gla=2000, year=2005, lot=8000, beds=None, full=None, half=None):
    c = make_comp(
        mls,
        living_area=gla,
        year_built=year,
        lot_size_sqft=lot,
        bedrooms=beds,
        baths_full=full,
        baths_half=half,
    )
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
    out = rank([near_but_bigger, farther_but_closer_gla], subject, settings, 30)
    assert order(out) == ["B", "A"]


def test_hierarchy_order_changes_ranking(subject, settings):
    same_sub_far = comp("A", tier=0, miles=0.9)
    fuzzy_sub_near = comp("B", tier=2, miles=0.05)
    assert order(rank([same_sub_far, fuzzy_sub_near], subject, settings, 30)) == ["A", "B"]
    s = settings.model_copy(
        update={
            "ranking": settings.ranking.model_copy(
                update={
                    "hierarchy": ["distance", "subdivision", "gla", "age", "lot", "beds", "baths"]
                }
            )
        }
    )
    assert order(rank([same_sub_far, fuzzy_sub_near], subject, s, 30)) == ["B", "A"]


def test_final_tie_breakers(subject, settings):
    a = comp("A", miles=0.12)
    b = comp("B", miles=0.11)
    c = comp("C", miles=0.11)  # identical to B except mls_number
    assert order(rank([a, c, b], subject, settings, 30)) == ["B", "C", "A"]


def test_missing_values_sort_last_and_are_flagged(subject, settings):
    missing_year = comp("A", year=None)
    complete = comp("B", year=2030)  # 25 years off is still better than unknown
    out = rank([missing_year, complete], subject, settings, 30)
    assert order(out) == ["B", "A"]
    a = out.ranked[1]
    assert a.age_diff_years.value is None
    assert a.age_diff_years.flag is FlagReason.MISSING_REQUIRED_FIELD
    assert a.year_built.value is None  # never imputed
    assert any(f.mls_number == "A" and f.field == "year_built" for f in out.flags)


def test_sort_key_stored_and_ranks_assigned(subject, settings):
    out = rank([comp("A"), comp("B", miles=0.6)], subject, settings, 30)
    assert [c.rank for c in out.ranked] == [1, 2]
    assert out.ranked[0].sort_key[-1] == "A"
    assert out.audit[0].detail["sort_key"] == out.ranked[0].sort_key


def test_shortlist_size_and_minimum(subject, settings):
    s = settings
    out = rank([comp(str(i), miles=0.1 * i) for i in range(1, 4)], subject, s, 2, 2)
    assert [c.mls_number for c in out.shortlist] == ["1", "2"]
    assert "RANK_BEYOND_SHORTLIST" in out.excluded[0].reasons[0]
    assert not [f for f in out.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]

    prior = [
        AuditEntry(mls_number="x", stage="hard_filters", decision="EXCLUDED", rule="gla_bracket"),
        AuditEntry(mls_number="y", stage="hard_filters", decision="EXCLUDED", rule="max_distance"),
        AuditEntry(mls_number="z", stage="hard_filters", decision="EXCLUDED", rule="max_distance"),
    ]
    out = rank([comp("1")], subject, s, 2, 2, prior_audit=prior)
    (flag,) = [f for f in out.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]
    assert flag.mls_number is None and "max_distance (2 rows)" in flag.message


def test_beds_and_baths_break_ties(subject, settings):
    subj = subject.model_copy(update={"bedrooms": 3, "baths_full": 2, "baths_half": 1})
    two_beds_off = comp("A", beds=5, full=2, half=1)
    one_bath_off = comp("B", beds=3, full=3, half=1)  # beds rank before baths
    unknown_rooms = comp("C")
    out = rank([unknown_rooms, two_beds_off, one_bath_off], subj, settings, 30)
    assert order(out) == ["B", "A", "C"]


def test_distance_bucket_no_float_boundary_drop(subject, settings):
    # 0.3 as IEEE-754 float is 0.29999999999999998889...; with a 0.1 mi band it must be bucket 3.
    s = settings.model_copy(
        update={
            "ranking": settings.ranking.model_copy(
                update={
                    "tolerance_bands": settings.ranking.tolerance_bands.model_copy(
                        update={"distance_miles": 0.1}
                    )
                }
            )
        }
    )
    a = comp("A", miles=0.30, gla=2200)
    b = comp("B", miles=0.35, gla=2000)
    out = rank([a, b], subject, s, 30)
    assert order(out) == ["B", "A"]


def test_missing_subject_year_does_not_flag_comp(subject, settings):
    subj = subject.model_copy(update={"year_built": None})
    out = rank([comp("A", year=2005)], subj, settings, 30)
    assert out.ranked[0].age_diff_years.flag is None
    assert not [f for f in out.flags if f.mls_number == "A"]
