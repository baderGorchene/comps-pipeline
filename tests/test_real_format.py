"""A fictional export in the shape of a real MLS download: status codes, 'Living Sq Ft',
a Distance column instead of coordinates, acreage, an unnamed column, '#2' unit numbers."""

from comps_pipeline import pipeline
from comps_pipeline.models import Source

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_real_format_runs(settings):
    result = pipeline.run(
        FIXTURES / "real_format.csv", FIXTURES / "real_format_subject.yaml", settings
    )
    by_mls = {c.mls_number: c for c in result.shortlist}
    assert set(by_mls) == {"900001", "900002"}  # status X excluded
    sold, listing = by_mls["900001"], by_mls["900002"]
    assert (sold.pool, listing.pool) == ("sold", "listing")
    assert sold.distance_miles.value == 0.4 and sold.distance_miles.source is Source.MLS
    assert sold.living_area.value == 1410 and float(sold.lot_acres()) == 0.12
    assert sold.subdivision_tier.value == listing.subdivision_tier.value == 0
    assert result.exit_code == 2  # far fewer than 20 sold comps: BLOCKING, as it should be
