"""Tests for AI Pipeline Specification (Version 3.6)."""

import csv

from comps_pipeline import pipeline
from comps_pipeline.ai.router import AIModelRouter
from comps_pipeline.ingest.cleaner import clean
from comps_pipeline.models import FlagReason
from tests.conftest import SAMPLES

CSV, SUBJECT = SAMPLES / "mls_sample.csv", SAMPLES / "subject.yaml"


def test_ai_router_owner_classification():
    router = AIModelRouter()
    res_builder, _ = router.classify_owner("Lennar Homes LLC")
    assert res_builder.owner_type == "BUILDER"
    assert res_builder.confidence > 0.5

    res_individual, _ = router.classify_owner("John & Jane Smith")
    assert res_individual.owner_type == "INDIVIDUAL"


def test_ai_router_lease_detection():
    router = AIModelRouter()
    text_leased = "Great tenant occupied investment property with active lease in place paying $2,400/mo."
    res_leased, _ = router.detect_lease(text_leased)
    assert res_leased.has_lease_indicator is True

    text_clean = "Beautiful owner occupied home in pristine condition with open floor plan."
    res_clean, _ = router.detect_lease(text_clean)
    assert res_clean.has_lease_indicator is False


def test_new_build_lease_and_owner_flags(subject, settings):
    # Year built 2026 with lease terms -> LEASED_NEW_BUILD_REVIEW
    # Year built 2026 with individual owner -> INDIVIDUAL_OWNER_NEW_BUILD
    rows = [
        {
            "mls_number": "1001",
            "status": "Closed",
            "close_price": "$350,000",
            "close_date": "06/15/2026",
            "living_area": "2000",
            "year_built": "2026",
            "subdivision_raw": "Brushy Creek Phase 2",
            "latitude": "30.51",
            "longitude": "-97.68",
            "public_remarks": "Brand new 2026 build, active lease in place with tenant occupied rights.",
            "extras": {"Owners Name": "John Doe"},
        },
        {
            "mls_number": "1002",
            "status": "Closed",
            "close_price": "$360,000",
            "close_date": "06/15/2026",
            "living_area": "2000",
            "year_built": "2026",
            "subdivision_raw": "Brushy Creek Phase 2",
            "latitude": "30.51",
            "longitude": "-97.68",
            "public_remarks": "Brand new 2026 builder delivery, pristine never occupied.",
            "extras": {"Owners Name": "DR Horton Construction LLC"},
        },
    ]
    subj = subject.model_copy(update={"construction_status": "new_construction"})
    out = clean(rows, subj, settings)
    by_mls = {c.mls_number: c for c in out.comps}

    # 1001 has lease -> LEASED_NEW_BUILD_REVIEW and INDIVIDUAL_OWNER_NEW_BUILD
    flags_1001 = {f.reason for f in out.flags if f.mls_number == "1001"}
    assert FlagReason.LEASED_NEW_BUILD_REVIEW in flags_1001
    assert FlagReason.INDIVIDUAL_OWNER_NEW_BUILD in flags_1001
    assert by_mls["1001"].owner_type == "INDIVIDUAL"
    assert by_mls["1001"].remarks_signals.get("_detected_condition") == "C2"

    # 1002 has builder owner and no lease -> no lease/owner flags
    flags_1002 = {f.reason for f in out.flags if f.mls_number == "1002"}
    assert FlagReason.LEASED_NEW_BUILD_REVIEW not in flags_1002
    assert FlagReason.INDIVIDUAL_OWNER_NEW_BUILD not in flags_1002
    assert by_mls["1002"].owner_type == "BUILDER"
    assert by_mls["1002"].remarks_signals.get("_detected_condition") == "C1"


def test_version_36_artifacts_written(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    v36_csv = result.out_dir / "shortlist_v36.csv"
    v36_json = result.out_dir / "shortlist_v36.json"

    assert v36_csv.is_file()
    assert v36_json.is_file()

    with v36_csv.open(encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == len(result.shortlist)
        # Check required v3.6 columns
        assert "selection_status" in reader[0]
        assert "ai_rejection_justification" in reader[0]
        assert "ai_model_used" in reader[0]

        # Final 6 should be marked FINAL_COMP_1..FINAL_COMP_6
        final_statuses = [r["selection_status"] for r in reader if r["selection_status"].startswith("FINAL_COMP_")]
        assert len(final_statuses) == len(result.final.picks)

        # Rejected shortlist rows should have rejection justification
        rejected = [r for r in reader if r["selection_status"] == "SHORTLIST_REJECTED"]
        assert len(rejected) > 0
        for r in rejected:
            assert r["ai_rejection_justification"] != ""
            assert len(r["ai_rejection_justification"]) > 10

