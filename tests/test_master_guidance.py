"""Comprehensive tests for the Master Guidance & UAD 3.6 pipeline extensions (Steps 0–7)."""

import csv
import datetime as dt

from comps_pipeline import pipeline
from comps_pipeline.filters.hard_filters import (
    age_restriction_filter,
    distressed_filter,
    foundation_compatibility_filter,
    school_and_utility_guardrail_filter,
    sub_type_and_story_filter,
)
from comps_pipeline.ingest.cleaner import clean
from comps_pipeline.matching.subdivision import match_all
from comps_pipeline.models import Cell, FlagReason, Subject
from comps_pipeline.ranking.ranker import rank
from comps_pipeline.selection.final import select_final
from tests.conftest import ROOT, make_comp


def _raw(mls="100", **overrides):
    row = {
        "mls_number": mls,
        "status": "Closed",
        "close_price": "$320,000",
        "close_date": "06/15/2026",
        "living_area": "1,980",
        "year_built": "2018",
        "lot_size_sqft": "7800",
        "subdivision_raw": "Brushy Creek Phase 2",
        "latitude": "30.51",
        "longitude": "-97.68",
        "foundation_type": "Slab",
        "public_remarks": "Beautiful home in McAllen ISD with quartz countertops.",
        "extras": {},
    }
    row.update(overrides)
    return row


def test_step3_nlp_remarks_flags_and_signals(subject, settings):
    rows = [
        _raw(
            "1",
            public_remarks=(
                "Garage has been converted to 4th bedroom. Leased solar panels included. "
                "Guest house casita in back on resaca waterfront."
            ),
        ),
        _raw(
            "2",
            public_remarks=(
                "Brand new construction 2026, never occupied! Owned solar panels paid off."
            ),
            extras={"New Construction": "Yes"},
        ),
        _raw(
            "3",
            public_remarks=(
                "55+ active adult community in Sharyland ISD. Investor special cash only."
            ),
        ),
    ]
    out = clean(rows, subject, settings)
    by_mls = {c.mls_number: c for c in out.comps}

    c1 = by_mls["1"]
    assert c1.remarks_signals.get("_garage_conversion")
    assert c1.remarks_signals.get("_has_adu") is True
    assert c1.remarks_signals.get("_solar_status") == "leased_or_unverified"
    assert "waterfront/resaca" in c1.remarks_signals.get("_site_influences", "")

    flag_reasons_1 = {f.reason for f in out.flags if f.mls_number == "1"}
    assert FlagReason.NON_CONFORMING_CONVERSION in flag_reasons_1
    assert FlagReason.ADU_DETECTED in flag_reasons_1
    assert FlagReason.SOLAR_LEASE_REVIEW in flag_reasons_1
    assert FlagReason.SITE_INFLUENCE_NOTE in flag_reasons_1

    c2 = by_mls["2"]
    assert c2.remarks_signals.get("_detected_condition") == "C1"
    assert c2.remarks_signals.get("_solar_status") == "owned"
    flag_reasons_2 = {f.reason for f in out.flags if f.mls_number == "2"}
    assert FlagReason.SOLAR_LEASE_REVIEW not in flag_reasons_2

    c3 = by_mls["3"]
    assert c3.remarks_signals.get("_is_55_plus") is True
    assert c3.remarks_signals.get("_distressed_remarks")
    assert c3.remarks_signals.get("_extracted_isd", "").lower() == "sharyland"


def test_step2_distressed_and_55_plus_filters(subject, settings):
    reo_comp = make_comp("REO1").model_copy(update={"extras": {"REO": "Yes"}})
    short_comp = make_comp("SS1").model_copy(update={"extras": {"Short Sale": "Y"}})
    fixer_comp = make_comp("FIX1").model_copy(
        update={"remarks_signals": {"_distressed_remarks": "cash_only_fixer"}}
    )
    clean_comp = make_comp("OK1").model_copy(update={"extras": {"REO": "No", "Short Sale": "No"}})

    res = distressed_filter([reo_comp, short_comp, fixer_comp, clean_comp], subject, settings)
    assert [c.mls_number for c in res.kept] == ["OK1"]

    age55_comp = make_comp("SEN1", public_remarks="55+ senior community").model_copy(
        update={"remarks_signals": {"_is_55_plus": True}}
    )
    std_comp = make_comp("STD1", public_remarks="Family home")
    res_std = age_restriction_filter([age55_comp, std_comp], subject, settings)
    assert [c.mls_number for c in res_std.kept] == ["STD1"]

    subj_55 = subject.model_copy(update={"is_55_plus": True})
    res_55 = age_restriction_filter([age55_comp, std_comp], subj_55, settings)
    assert [c.mls_number for c in res_55.kept] == ["SEN1"]


def test_step2_stories_subtype_foundation_and_guardrails(subject, settings):
    subj = subject.model_copy(
        update={
            "property_sub_type": "Single Family",
            "stories": 1.0,
            "foundation_type": "Slab",
            "school_district": "McAllen ISD",
            "water_sewer": "City Sewer",
        }
    )
    ok = make_comp("OK", foundation_type="Slab", status="A").model_copy(
        update={
            "pool": "listing",
            "extras": {
                "Property Sub-Type": "Single Family",
                "# Stories": "1",
                "School District": "McAllen ISD",
                "Water Sewer": "City Sewer",
                "DOM": "45",
            },
        }
    )
    two_story = make_comp("2ST", foundation_type="Slab").model_copy(
        update={"extras": {"# Stories": "2"}}
    )
    mobile = make_comp("MOB", foundation_type="Slab").model_copy(
        update={"extras": {"Property Sub-Type": "Manufactured Home"}}
    )
    pier_beam = make_comp("PB", foundation_type="Pier & Beam")
    wrong_isd = make_comp("ISD").model_copy(update={"extras": {"School District": "Sharyland ISD"}})
    septic = make_comp("SEP").model_copy(update={"extras": {"Water Sewer": "Septic System"}})
    stale_active = make_comp("DOM", status="Active").model_copy(
        update={"pool": "listing", "extras": {"DOM": "450"}}
    )

    assert [
        c.mls_number
        for c in sub_type_and_story_filter([ok, two_story, mobile], subj, settings).kept
    ] == ["OK"]
    assert [
        c.mls_number for c in foundation_compatibility_filter([ok, pier_beam], subj, settings).kept
    ] == ["OK"]
    assert [
        c.mls_number
        for c in school_and_utility_guardrail_filter(
            [ok, wrong_isd, septic, stale_active], subj, settings
        ).kept
    ] == ["OK"]


def test_step4_subdivision_legal_description_dual_match(subject, settings):
    # Comp has an abbreviated or marketing subdivision_raw that fails, but Legal Description matches
    comp = make_comp("LEG1", subdivision_raw="UNKN MKT NAME").model_copy(
        update={"extras": {"Legal Description": "LOT 12 BRUSHY CREEK PHASE 2"}}
    )
    out = match_all([comp], subject, settings)
    assert out.comps[0].subdivision_tier.value in (0, 2)


def test_step1_and_step2_pending_priority_and_financing_ranking(subject, settings):
    active_near = make_comp("ACT1", status="Active", living_area=2000).model_copy(
        update={
            "pool": "listing",
            "subdivision_tier": Cell(value=0, source="COMPUTED"),
            "distance_miles": Cell(value=0.2, source="COMPUTED"),
        }
    )
    pending_far = make_comp("PND1", status="Pending", living_area=2100).model_copy(
        update={
            "pool": "listing",
            "subdivision_tier": Cell(value=0, source="COMPUTED"),
            "distance_miles": Cell(value=0.9, source="COMPUTED"),
        }
    )
    out_list = rank([active_near, pending_far], subject, settings, 10, pool="listing")
    assert [c.mls_number for c in out_list.ranked] == ["PND1", "ACT1"]

    owner_fin = make_comp("OWN1", living_area=2000).model_copy(
        update={
            "pool": "sold",
            "subdivision_tier": Cell(value=0, source="COMPUTED"),
            "distance_miles": Cell(value=0.1, source="COMPUTED"),
            "extras": {"Financing": "Owner Financing"},
        }
    )
    conv_fin = make_comp("CNV1", living_area=2150).model_copy(
        update={
            "pool": "sold",
            "subdivision_tier": Cell(value=0, source="COMPUTED"),
            "distance_miles": Cell(value=0.8, source="COMPUTED"),
            "extras": {"Financing": "Conventional"},
        }
    )
    out_sold = rank([owner_fin, conv_fin], subject, settings, 10, pool="sold")
    assert [c.mls_number for c in out_sold.ranked] == ["CNV1", "OWN1"]


def test_step5_new_construction_c1_path_and_table2_audit_log(subject, settings):
    c1_subj = subject.model_copy(
        update={
            "construction_status": "new_construction",
            "bedrooms": 3,
            "baths_full": 2,
            "baths_half": 0,
        }
    )

    def _mk(mls, rank_num, tier, pool="sold", gla=2000, year=2026, lot=8000, beds=3, full=2):
        c = make_comp(
            mls,
            living_area=gla,
            year_built=year,
            lot_size_sqft=lot,
            bedrooms=beds,
            baths_full=full,
            baths_half=0,
        )
        return c.model_copy(
            update={
                "rank": rank_num,
                "pool": pool,
                "subdivision_tier": Cell(value=tier, source="COMPUTED"),
                "distance_miles": Cell(value=0.2 * rank_num, source="COMPUTED"),
                "gla_diff_pct": Cell(value=0.0, source="COMPUTED"),
            }
        )

    sold = [
        _mk("S_IN_1", 1, 0, gla=2100, lot=8500, year=2026, beds=4, full=3),
        _mk("S_IN_2", 2, 0, gla=1900, lot=7500, year=2024, beds=2, full=1),
        _mk("S_IN_3", 3, 0),
        _mk("S_IN_4", 4, 0),
        _mk("S_OUT_1", 5, 3),
        _mk("S_OUT_2", 6, 3),
    ]
    listings = [
        _mk("L_IN_1", 1, 0, pool="listing"),
        _mk("L_OUT_1", 2, 3, pool="listing"),
        _mk("L_OUT_2", 3, 3, pool="listing"),
    ]

    final = select_final(sold, listings, c1_subj, settings)
    picked_mls = [c.mls_number for c in final.picks]
    # C1 path picks 2 in-sub sold + 1 competing sold + 1 extra sold + 2 listings = 6
    assert len(final.picks) == 6
    assert "S_IN_1" in picked_mls and "S_IN_2" in picked_mls
    assert "S_OUT_1" in picked_mls
    assert "L_IN_1" in picked_mls and "L_OUT_1" in picked_mls
    assert all(c.selection_rationale for c in final.picks)
    assert len(final.analyzed_not_used) == 3
    assert all(c.deselection_reason for c in final.analyzed_not_used)


def test_real_mcallen_dataset_runs_end_to_end(tmp_path, settings):
    mcallen_csv = ROOT / "data" / "4508 comps all 3 miles.csv"
    if not mcallen_csv.is_file():
        return
    subj_path = tmp_path / "mcallen_subject.yaml"
    subj = Subject(
        address="4508 N 1st Ln, McAllen, TX 78504",
        subdivision="Parkhill Terrace",
        living_area=1404,
        effective_date=dt.date(2026, 4, 18),
        year_built=2015,
        lot_size_sqft=5368,
        bedrooms=3,
        baths_full=2,
        baths_half=0,
        foundation_type="Slab",
    )
    subj_path.write_text(subj.model_dump_json(), encoding="utf-8")
    result = pipeline.run(mcallen_csv, subj_path, settings)
    assert result.manifest.row_counts["input_rows"] == 1466
    assert len(result.final.picks) == 6
    assert len(result.final.analyzed_not_used) > 0
    assert (result.out_dir / "analyzed_not_used.csv").is_file()
    with (result.out_dir / "analyzed_not_used.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(result.final.analyzed_not_used)
    assert all(r["deselection_reason"].strip() for r in rows)
