import shutil

import pytest
import yaml

from comps_pipeline.config.loader import ConfigError, apply_llm_override, load_settings
from comps_pipeline.models import FlagReason, Severity
from tests.conftest import CONFIG


def test_repo_settings_load():
    s = load_settings(CONFIG)
    assert s.filters.gla_bracket_pct == 25
    assert s.ranking.hierarchy == ["subdivision", "distance", "gla", "age", "lot", "beds", "baths"]
    assert s.filters_at(0) == s.filters
    last = s.filters_at(len(s.escalation.steps))
    assert (last.max_distance_miles, last.gla_bracket_pct, last.sale_date_max_months) == (5, 30, 24)
    assert "living_area" in s.column_mapping
    assert s.sev(FlagReason.SHORTLIST_BELOW_MINIMUM) is Severity.BLOCKING


def _write_config(tmp_path, mutate):
    for name in ("settings.yaml", "column_mapping.yaml", "subdivision_aliases.yaml"):
        shutil.copy(CONFIG.parent / name, tmp_path / name)
    data = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    mutate(data)
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path / "settings.yaml"


def test_unknown_top_level_key_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d.update(surprise=1))
    with pytest.raises(ConfigError, match="surprise"):
        load_settings(path)


def test_unknown_nested_key_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d["filters"].update(gla_braket_pct=20))
    with pytest.raises(ConfigError, match="gla_braket_pct"):
        load_settings(path)


@pytest.mark.parametrize(
    "hierarchy",
    [
        ["subdivision", "distance", "gla", "age"],
        ["subdivision", "distance", "gla", "age", "age"],
        ["subdivision", "distance", "gla", "age", "price"],
    ],
)
def test_invalid_hierarchy_rejected(tmp_path, hierarchy):
    path = _write_config(tmp_path, lambda d: d["ranking"].update(hierarchy=hierarchy))
    with pytest.raises(ConfigError, match="permutation"):
        load_settings(path)


def test_reordered_hierarchy_accepted(tmp_path):
    order = ["distance", "subdivision", "lot", "gla", "age", "baths", "beds"]
    path = _write_config(tmp_path, lambda d: d["ranking"].update(hierarchy=order))
    assert load_settings(path).ranking.hierarchy == order


def test_unknown_fields_sent_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d["llm"].update(fields_sent=["mls_number", "ssn"]))
    with pytest.raises(ConfigError, match="ssn"):
        load_settings(path)


def test_unknown_mapping_field_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: None)
    (tmp_path / "column_mapping.yaml").write_text("garage: [Garage]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="garage"):
        load_settings(path)


def test_severity_override(tmp_path):
    path = _write_config(tmp_path, lambda d: d["severity"].update(NO_COORDINATES="BLOCKING"))
    assert load_settings(path).sev(FlagReason.NO_COORDINATES) is Severity.BLOCKING


def test_severity_must_cover_every_reason(tmp_path):
    path = _write_config(tmp_path, lambda d: d["severity"].pop("LLM_UNAVAILABLE"))
    with pytest.raises(ConfigError, match="LLM_UNAVAILABLE"):
        load_settings(path)


def test_missing_threshold_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d["filters"].pop("max_distance_miles"))
    with pytest.raises(ConfigError, match="max_distance_miles"):
        load_settings(path)


@pytest.mark.parametrize("steps", [[{"max_distnce_miles": 4}], [{}], [{"gla_bracket_pct": 150}]])
def test_bad_escalation_step_rejected(tmp_path, steps):
    path = _write_config(tmp_path, lambda d: d["escalation"].update(steps=steps))
    with pytest.raises(ConfigError):
        load_settings(path)


def test_overlapping_status_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d["status"]["listing"].append("sold"))
    with pytest.raises(ConfigError, match="SOLD"):
        load_settings(path)


def test_llm_override():
    s = load_settings(CONFIG)
    assert apply_llm_override(s, "off").llm.enabled is False
    assert apply_llm_override(s, "mock").llm.provider == "mock"
    with pytest.raises(ConfigError):
        apply_llm_override(s, "gpt")
