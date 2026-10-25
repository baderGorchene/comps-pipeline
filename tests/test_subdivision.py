import pytest

from comps_pipeline.matching.normalize import normalize, numbered_parts
from comps_pipeline.matching.subdivision import match_all, match_subdivision
from comps_pipeline.models import FlagReason
from tests.conftest import make_comp

NOISE = ["SUBDIVISION", "SUBD", "SUB", "ADDN", "ADDITION"]


@pytest.mark.parametrize(
    "raw",
    [
        "Brushy Creek Phase 2",
        "brushy creek ph 2",
        "Brushy Creek Ph. II",
        "BRUSHY CREEK PHS 2",
        "Brushy Creek Ph2",
        "Brushy  Creek,  Phase #2",
        "Brushy Creek Subdivision Phase 2",
    ],
)
def test_normalize_variants(raw):
    assert normalize(raw, NOISE) == "BRUSHY CREEK PHASE 2"


def test_normalize_section_unit_and_optional_noise():
    assert normalize("Oak Hills Sect. IV Unit 3") == "OAK HILLS SECTION 4 UNIT 3"
    assert normalize("Oak Estates", NOISE) == "OAK ESTATES"
    assert normalize("Oak Estates", [*NOISE, "ESTATES"]) == "OAK"


def test_numbered_parts():
    assert numbered_parts("OAK SECTION 4 UNIT 3") == {"SECTION": "4", "UNIT": "3"}


def test_tiers(settings):
    subject = "Brushy Creek Phase 2"
    assert match_subdivision("BRUSHY CREEK PH II", subject, settings).tier == 0
    typo = match_subdivision("Brushy Crek Phase 2", subject, settings)
    assert typo.tier == 2 and typo.score >= 90
    assert match_subdivision("Forest Creek", subject, settings).tier == 3


def test_alias_is_tier_1(settings):
    s = settings.model_copy(update={"subdivision_aliases": {"Brushy Creek Phase 2": ["BC Ph 2"]}})
    assert match_subdivision("bc phase 2", "Brushy Creek Phase 2", s).tier == 1


@pytest.mark.parametrize(
    ("comp", "subject"),
    [
        ("Brushy Creek Phase 3", "Brushy Creek Phase 2"),
        ("Brushy Creek Ph III", "Brushy Creek Phase II"),
        ("Oak Hills Section 1", "Oak Hills Sec 2"),
        ("Oak Hills Unit 5", "Oak Hills Unit 6"),
    ],
)
def test_different_numbers_never_tier_0_or_1(settings, comp, subject):
    # Even an alias that explicitly maps the names together cannot override the number rule.
    s = settings.model_copy(update={"subdivision_aliases": {subject: [comp]}})
    m = match_subdivision(comp, subject, s)
    assert m.tier >= 2
    assert m.number_conflict


def test_match_all_flags_uncertain(subject, settings):
    comps = [
        make_comp("1", subdivision_raw="Brushy Creek Phase 3"),
        make_comp("2", subdivision_raw="BRUSHY CREEK PHASE 2"),
        make_comp("3", subdivision_raw=None),
    ]
    out = match_all(comps, subject, settings)
    tiers = [c.subdivision_tier.value for c in out.comps]
    assert tiers == [2, 0, None]
    (flag,) = out.flags
    assert flag.reason is FlagReason.SUBDIVISION_UNCERTAIN and flag.mls_number == "1"
    assert "PHASE 3 vs 2" in flag.message
