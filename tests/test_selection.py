from comps_pipeline.models import FlagReason
from comps_pipeline.selection.final import gaps, select_final
from tests.conftest import make_comp


def comp(mls, rank, gla=2000, year=2005, lot=8000, beds=3, full=2, half=1, pool="sold"):
    c = make_comp(
        mls,
        living_area=gla,
        year_built=year,
        lot_size_sqft=lot,
        bedrooms=beds,
        baths_full=full,
        baths_half=half,
    )
    return c.model_copy(update={"rank": rank, "pool": pool})


def subj(subject):
    return subject.model_copy(update={"bedrooms": 3, "baths_full": 2, "baths_half": 1})


def bracketing_set():
    """Five sold comps that bracket a 2000 sf / 2005 / 8000 sf / 3 bd / 2.5 ba subject."""
    return [
        comp("S1", 1, gla=2100, year=2006, lot=8500, beds=4, full=3),
        comp("S2", 2, gla=1900, year=2004, lot=7500, beds=2, full=2, half=0),
        comp("S3", 3),
        comp("S4", 4),
        comp("S5", 5),
    ]


def test_bracketed_top_picks_need_no_swaps(subject, settings):
    listing = comp("L1", 1, pool="listing")
    out = select_final(bracketing_set(), [listing], subj(subject), settings)
    assert [c.mls_number for c in out.picks] == ["S1", "S2", "S3", "S4", "S5", "L1"]
    assert out.gaps == [] and out.swaps == [] and not out.flags


def test_equal_values_do_not_bracket_by_default(subject, settings):
    picks = [comp(f"S{i}", i) for i in range(1, 6)]  # all identical to the subject
    assert gaps(picks, subj(subject), settings) == ["gla", "lot", "age", "beds", "baths"]
    eq = settings.model_copy(
        update={
            "selection": settings.selection.model_copy(update={"equal_counts_as_bracketed": True})
        }
    )
    assert gaps(picks, subj(subject), eq) == []


def test_swap_brings_in_lower_ranked_comp_to_bracket_gla(subject, settings):
    top = [comp(f"S{i}", i, gla=2050) for i in range(1, 6)]  # all above on GLA
    smaller = comp("S7", 7, gla=1950)
    other = comp("S6", 6, gla=2060)
    s = settings.model_copy(
        update={"selection": settings.selection.model_copy(update={"bracket_attributes": ["gla"]})}
    )
    out = select_final([*top, other, smaller], [], subj(subject), s)
    assert [c.mls_number for c in out.picks] == ["S1", "S2", "S3", "S4", "S7"]  # S5 replaced
    assert out.swaps == [{"removed": "S5", "added": "S7", "gaps_before": ["gla"], "gaps_after": []}]
    (flag,) = out.flags
    assert flag.reason is FlagReason.NO_LISTING_COMP


def test_unfixable_gap_is_flagged(subject, settings):
    picks = [comp(f"S{i}", i, beds=4) for i in range(1, 7)]  # nobody below 3 beds
    s = settings.model_copy(
        update={"selection": settings.selection.model_copy(update={"bracket_attributes": ["beds"]})}
    )
    out = select_final(picks, [comp("L1", 1, pool="listing", beds=4)], subj(subject), s)
    assert out.gaps == ["beds"] and not out.swaps
    (flag,) = out.flags
    assert flag.reason is FlagReason.NOT_BRACKETED and flag.field == "beds"


def test_subject_missing_attribute_is_skipped(subject, settings):
    picks = [comp(f"S{i}", i, beds=None) for i in range(1, 6)]
    s = settings.model_copy(
        update={"selection": settings.selection.model_copy(update={"bracket_attributes": ["beds"]})}
    )
    assert gaps(picks, subject, s) == []  # conftest subject has no bedrooms


def test_two_swaps_keep_higher_ranked_comp(subject, settings):
    # S5 is the only initial pick below on age, so swap 1 replaces S4 with S6 (fixes gla).
    # Swap 2 brings in S7 (below on gla/lot/age) and must replace S6 (rank 6), not S5 (rank 5).
    top = [
        comp("S1", 1, gla=2100, lot=9000, year=2010),
        comp("S2", 2, gla=2100, lot=9000, year=2010),
        comp("S3", 3, gla=2100, lot=9000, year=2010),
        comp("S4", 4, gla=2100, lot=9000, year=2010),
        comp("S5", 5, gla=2100, lot=9000, year=2000),
    ]
    s6 = comp("S6", 6, gla=1900, lot=9000, year=2010)
    s7 = comp("S7", 7, gla=1900, lot=7000, year=2000)
    s = settings.model_copy(
        update={
            "selection": settings.selection.model_copy(
                update={"bracket_attributes": ["gla", "lot", "age"]}
            )
        }
    )
    out = select_final([*top, s6, s7], [comp("L1", 1, pool="listing")], subj(subject), s)
    assert [c.mls_number for c in out.picks] == ["S1", "S2", "S3", "S5", "S7", "L1"]
