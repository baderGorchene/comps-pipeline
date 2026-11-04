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


def test_c1_swaps_strictly_preserve_in_sub_quota(subject, settings):
    from comps_pipeline.models import Cell
    c1_subj = subject.model_copy(
        update={
            "construction_status": "new_construction",
            "bedrooms": 3,
            "baths_full": 2,
            "baths_half": 0,
        }
    )

    def _c1_comp(mls, rank, tier, pool="sold", beds=3):
        return comp(mls, rank, beds=beds, pool=pool).model_copy(
            update={
                "subdivision_tier": Cell(value=tier, source="COMPUTED"),
                "distance_miles": Cell(value=0.5, source="COMPUTED"),
                "gla_diff_pct": Cell(value=0.0, source="COMPUTED"),
            }
        )

    # Initial C1 picks will be: S_IN_1, S_IN_2, S_OUT_1, S_OUT_2 (4 sold) + L_IN_1, L_OUT_1 (2 listings) = 6
    # S_IN_1 and S_IN_2 both have 4 beds (unbracketed below on beds)
    sold = [
        _c1_comp("S_IN_1", 1, 0, beds=4),
        _c1_comp("S_IN_2", 2, 0, beds=4),
        _c1_comp("S_OUT_1", 3, 3, beds=4),
        _c1_comp("S_OUT_2", 4, 3, beds=4),
        # S_OUT_3 is a competing comp outside subdivision with 2 beds (could fix the bed gap!)
        _c1_comp("S_OUT_3", 5, 3, beds=2),
    ]
    listings = [
        _c1_comp("L_IN_1", 1, 0, pool="listing", beds=4),
        _c1_comp("L_OUT_1", 2, 3, pool="listing", beds=4),
    ]

    s = settings.model_copy(
        update={
            "selection": settings.selection.model_copy(update={"bracket_attributes": ["beds"]})
        }
    )
    final = select_final(sold, listings, c1_subj, s)
    # The swap must replace an out-of-sub comp (S_OUT_2), NEVER an in-sub comp (S_IN_1 or S_IN_2)
    # because dropping an in-sub comp would drop in-sub solds below 2!
    picked_mls = [c.mls_number for c in final.picks]
    in_solds = [c for c in final.picks if c.pool == "sold" and c.subdivision_tier.value in (0, 1)]
    assert len(in_solds) >= 2
    assert "S_IN_1" in picked_mls and "S_IN_2" in picked_mls
    assert "S_OUT_3" in picked_mls  # swapped in for S_OUT_2


def test_c1_deficit_flag_when_insufficient_in_sub_or_out_sub(subject, settings):
    from comps_pipeline.models import Cell
    c1_subj = subject.model_copy(update={"construction_status": "new_construction"})

    def _c1_comp(mls, rank, tier, pool="sold"):
        return comp(mls, rank, pool=pool).model_copy(
            update={
                "subdivision_tier": Cell(value=tier, source="COMPUTED"),
                "distance_miles": Cell(value=0.5, source="COMPUTED"),
                "gla_diff_pct": Cell(value=0.0, source="COMPUTED"),
            }
        )

    # Only 1 in-sub sold, 0 in-sub listings
    sold = [
        _c1_comp("S_IN_1", 1, 0),
        _c1_comp("S_OUT_1", 2, 3),
        _c1_comp("S_OUT_2", 3, 3),
    ]
    listings = [
        _c1_comp("L_OUT_1", 1, 3, pool="listing"),
    ]
    final = select_final(sold, listings, c1_subj, settings)
    reasons = [f.reason for f in final.flags]
    assert FlagReason.NEW_CONST_SUBDIVISION_DEFICIT in reasons

