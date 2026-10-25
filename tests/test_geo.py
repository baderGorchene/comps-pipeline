import pytest

from comps_pipeline.filters.geo import compute_distances, haversine_miles
from comps_pipeline.models import FlagReason
from tests.conftest import make_comp


def test_haversine_one_degree_latitude():
    assert haversine_miles(30.0, -97.0, 31.0, -97.0) == pytest.approx(69.09, abs=0.01)
    assert haversine_miles(30.5, -97.7, 30.5, -97.7) == 0


def test_distance_computed(subject, settings):
    comp = make_comp("1", latitude=30.51, longitude=-97.7)
    out = compute_distances([comp], subject, settings)
    assert out.comps[0].distance_miles.value == pytest.approx(0.691, abs=0.001)
    assert out.comps[0].distance_miles.source == "COMPUTED"
    assert not out.flags


def test_missing_coordinates_flagged_not_guessed(subject, settings):
    comp = make_comp("1", latitude=30.51, longitude=None)
    out = compute_distances([comp], subject, settings)
    cell = out.comps[0].distance_miles
    assert cell.value is None and cell.flag is FlagReason.NO_COORDINATES
    assert [f.reason for f in out.flags] == [FlagReason.NO_COORDINATES]
