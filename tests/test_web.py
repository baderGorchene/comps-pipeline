"""The Django pages: start a run from the form, read its results, list it, download a file."""

import os
import shutil

import django
import pytest
import yaml

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
django.setup()

from django.test import Client, override_settings  # noqa: E402

from tests.conftest import CONFIG  # noqa: E402

SUBJECT = {
    "address": "1708 Hidden Glen Dr, Round Rock, TX 78681",
    "subdivision": "Brushy Creek Phase 2",
    "living_area": "2000",
    "effective_date": "2026-10-01",
    "year_built": "2005",
    "lot_size_sqft": "7800",
    "bedrooms": "3",
    "baths_full": "2",
    "baths_half": "1",
    "latitude": "30.5083",
    "longitude": "-97.6789",
}
RULES = {
    "gla_bracket_pct": "25",
    "lot_bracket_pct": "25",
    "max_distance_miles": "3.0",
    "sale_date_max_months": "12",
    "subdivision_min_score": "90",
    "missing_gla": "exclude",
    "missing_lot": "keep_and_flag",
    "missing_distance": "exclude",
    "missing_close_date": "exclude",
    "shortlist_size": "30",
    "min_shortlist_size": "20",
    "listing_shortlist_size": "10",
    "escalation": "max_distance_miles = 4\nmax_distance_miles = 5\ngla_bracket_pct = 30",
    "hierarchy": "subdivision, distance, gla, age, lot, beds, baths",
    "sold_count": "5",
    "listing_count": "1",
    "bracket_attributes": ["gla", "lot", "age", "beds", "baths"],
    "status_sold": "S, SOLD, CLOSED",
    "status_listing": "A, ACTIVE, P, PENDING, OPTION PENDING",
}


@pytest.fixture
def client(tmp_path):
    for name in ("settings.yaml", "column_mapping.yaml", "subdivision_aliases.yaml"):
        shutil.copy(CONFIG.parent / name, tmp_path / name)
    cfg = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    cfg["run"]["output_dir"] = str(tmp_path / "out")
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with override_settings(
        CONFIG_FILE=tmp_path / "settings.yaml",
        INPUT_SUBJECT=tmp_path / "none.yaml",
        ALLOWED_HOSTS=["testserver"],
    ):
        yield Client()


def _post(client, **extra):
    data = {"csv_source": "sample", "subject_source": "form", **SUBJECT, **RULES, **extra}
    return client.post("/", data)


def test_form_page_loads_with_defaults(client):
    page = client.get("/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Build shortlist" in html and 'value="25"' in html
    assert "max_distance_miles = 4.0" in html  # escalation steps from settings.yaml


def test_run_from_form_then_results_history_download(client):
    res = _post(client)
    assert res.status_code == 302, res.content.decode()[:2000]
    url = res["Location"]
    page = client.get(url).content.decode()
    assert "Final selection" in page and "Comp 5" in page and "Listing" in page
    assert "Bracketed on every attribute" in page
    run_id = url.rstrip("/").split("/")[-1]
    assert run_id in client.get("/runs/").content.decode()
    csv_file = client.get(f"/runs/{run_id}/files/final_selection.csv")
    assert csv_file.status_code == 200
    assert b"".join(csv_file.streaming_content).count(b"\n") == 7  # header + 6 picks
    assert client.get(f"/runs/{run_id}/files/settings.yaml").status_code == 404


def test_escalation_is_shown(client):
    res = _post(client, max_distance_miles="0.05", escalation="max_distance_miles = 3")
    page = client.get(res["Location"]).content.decode()
    assert "Relaxed: distance 3 mi" in page and "Used" in page


def test_bad_inputs_are_explained(client):
    page = _post(client, csv_source="upload").content.decode()
    assert "Choose the CSV exported from your MLS" in page
    page = _post(client, hierarchy="distance, gla").content.decode()
    assert "exactly once" in page
    page = _post(client, escalation="max_distnce_miles = 4").content.decode()
    assert "The run did not start" in page and "max_distnce_miles" in page


def test_unknown_run_is_404(client):
    assert client.get("/runs/../../etc/").status_code == 404
    assert client.get("/runs/20990101-000000-000000/").status_code == 404
