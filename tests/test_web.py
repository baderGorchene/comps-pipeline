"""The Django pages: start a run from the form, read its results, list it, download a file."""

import os
import shutil

import django
import pytest
import yaml

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
django.setup()

from django.conf import settings as django_settings  # noqa: E402
from django.test import Client, override_settings  # noqa: E402

from comps_pipeline.config.loader import load_settings  # noqa: E402
from tests.conftest import CONFIG  # noqa: E402
from web.forms import ConfigForm  # noqa: E402

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
    data = {"csv_source": "sample", "subject_source": "form", **SUBJECT, **extra}
    return client.post("/", data)


def _cfg_post(client, **overrides):
    cfg = load_settings(django_settings.CONFIG_FILE).model_dump(mode="json")
    data = ConfigForm.initial_from(cfg)
    data.update(overrides)
    return client.post("/config/", data)


def test_form_page_loads_with_defaults(client):
    page = client.get("/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Build shortlist" in html and "±25%" in html
    assert 'name="gla_bracket_pct"' not in html  # config is separated from the main page

    history_page = client.get("/runs/")
    assert history_page.status_code == 200

    cfg_page = client.get("/config/").content.decode()
    assert 'value="25"' in cfg_page
    assert "max_distance_miles = 4.0" in cfg_page  # escalation steps from settings.yaml


def test_run_from_form_then_results_history_download(client):
    res = _post(client)
    assert res.status_code == 302, res.content.decode()[:2000]
    url = res["Location"]
    page = client.get(url).content.decode()
    assert "Final selection" in page and "Comp 5" in page and "Listing" in page
    assert "Bracketed on every attribute" in page
    assert "run.log" in page
    run_id = url.rstrip("/").split("/")[-1]
    assert run_id in client.get("/runs/").content.decode()
    csv_file = client.get(f"/runs/{run_id}/files/final_selection.csv")
    assert csv_file.status_code == 200
    assert b"".join(csv_file.streaming_content).count(b"\n") == 7  # header + 6 picks
    assert client.get(f"/runs/{run_id}/files/settings.yaml").status_code == 404


def test_escalation_is_shown(client):
    cfg_res = _cfg_post(client, max_distance_miles="0.05", escalation="max_distance_miles = 3")
    assert cfg_res.status_code == 302
    res = _post(client)
    page = client.get(res["Location"]).content.decode()
    assert "Relaxed: distance 3 mi" in page and "Used" in page


def test_bad_inputs_are_explained(client):
    page = _post(client, csv_source="upload").content.decode()
    assert "The run did not start" in page and "Choose the CSV exported from your MLS" in page
    page = _post(client, living_area="").content.decode()
    assert "The run did not start" in page and "living_area" in page
    page = _cfg_post(client, hierarchy="distance, gla").content.decode()
    assert "exactly once" in page
    page = _cfg_post(client, escalation="max_distnce_miles = 4").content.decode()
    assert "Configuration could not be saved" in page and "max_distnce_miles" in page
    page = _cfg_post(client, escalation="max_distance_miles = [unclosed").content.decode()
    assert "invalid value" in page


def test_unknown_run_is_404(client):
    assert client.get("/runs/../../etc/").status_code == 404
    assert client.get("/runs/20990101-000000-000000/").status_code == 404


def test_config_page_loads_and_saves_all_files(client):
    page = client.get("/config/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "<h1>Settings</h1>" in html
    assert "CSV columns" in html

    # Build a full POST payload from initial form values and modify settings, mappings, and aliases
    from django.conf import settings as django_settings

    from comps_pipeline.config.loader import load_settings
    from web.forms import ConfigForm

    cfg = load_settings(django_settings.CONFIG_FILE).model_dump(mode="json")
    post_data = ConfigForm.initial_from(cfg)
    post_data["gla_bracket_pct"] = 20
    post_data["map_mls_number"] = "MLS #, ListingId, CustomMLS"
    post_data["subdivision_aliases"] = "BRUSHY CREEK PHASE 2 = BC PH 2, BRUSHYCREEK 2"
    post_data["band_distance_miles"] = 0.5

    res = client.post("/config/", post_data)
    assert res.status_code == 302
    assert res["Location"] == "/config/?saved=1"

    saved_page = client.get("/config/?saved=1").content.decode()
    assert "Configuration saved." in saved_page

    reloaded = load_settings(django_settings.CONFIG_FILE)
    assert reloaded.filters.gla_bracket_pct == 20
    assert "CustomMLS" in reloaded.column_mapping["mls_number"]
    assert reloaded.subdivision_aliases["BRUSHY CREEK PHASE 2"] == ["BC PH 2", "BRUSHYCREEK 2"]
    assert reloaded.ranking.tolerance_bands.distance_miles == 0.5


def test_under_the_hood_steps_shown_on_results(client):
    res = client.post("/", {"csv_source": "sample", "subject_source": "form", **SUBJECT})
    assert res.status_code == 302
    page = client.get(res["Location"]).content.decode()
    assert "CSV Ingestion &amp; Column Mapping" in page
    assert "Validation, Deduplication &amp; Status Split" in page
    assert "Eligibility Filtering &amp; Auto-Relaxation" in page
    assert "Multi-Criteria Tolerance Ranking" in page
    assert "Subject Bracketing &amp; Final Selection" in page


def test_ai_overview_endpoint_and_results_display(client):
    res = _post(client)
    assert res.status_code == 302
    run_id = res["Location"].rstrip("/").split("/")[-1]

    # Test async AI overview endpoint
    resp = client.get(f"/runs/{run_id}/ai-overview/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "overview" in data
    assert "executive_summary" in data["overview"]
    assert "valuation_bracket_conclusion" in data["overview"]
    assert data["overview"]["model_used"] in ("gpt-6.1-terra", "gemini-flash-latest", "heuristic_fallback")

    # Second call should return cached overview
    resp2 = client.get(f"/runs/{run_id}/ai-overview/")
    assert resp2.status_code == 200
    assert resp2.json()["cached"] is True

    # Check results page renders overview and detailed flags with human labels
    page = client.get(f"/runs/{run_id}/").content.decode()
    assert "AI summary" in page
    assert "Warnings" in page
    assert "ai-overview-panel" in page
    assert "flag-chip" in page
    # Ensure human-readable flag label is rendered rather than raw SCREAMING_SNAKE_CASE
    assert "flag-chip-label" in page
    assert "INDIVIDUAL_OWNER_NEW_BUILD" not in data["overview"]["new_construction_and_flags_review"]


def test_how_it_works_uses_live_settings(client):
    html = client.get("/how-it-works/").content.decode()
    assert "How it works" in html
    assert "±25%" in html and "Distance 2.0 mi" in html  # filter + first relaxation step
    assert "Check the photos" in html and "Off" in html  # vision disabled by default
    assert 'href="/how-it-works/"' in client.get("/").content.decode()  # linked from nav


def test_all_templates_compile_cleanly():
    """Verify that every template in web/templates parses without TemplateSyntaxError."""
    from pathlib import Path

    from django.template.loader import get_template

    template_dir = Path("web/templates")
    for tmpl in template_dir.glob("*.html"):
        loaded = get_template(tmpl.name)
        assert loaded is not None



