import shutil

import pytest
import yaml

from comps_pipeline.config.loader import ConfigError, apply_llm_override, load_settings
from comps_pipeline.models import FlagReason, Severity
from tests.conftest import CONFIG


def test_repo_settings_load():
    s = load_settings(CONFIG)
    assert s.filters.gla_bracket_pct == 30
    assert s.ranking.hierarchy == ["subdivision", "distance", "gla", "age", "lot"]
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
    order = ["distance", "subdivision", "lot", "gla", "age"]
    path = _write_config(tmp_path, lambda d: d["ranking"].update(hierarchy=order))
    assert load_settings(path).ranking.hierarchy == order


def test_unknown_fields_sent_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: d["llm"].update(fields_sent=["mls_number", "ssn"]))
    with pytest.raises(ConfigError, match="ssn"):
        load_settings(path)


def test_unknown_mapping_field_rejected(tmp_path):
    path = _write_config(tmp_path, lambda d: None)
    (tmp_path / "column_mapping.yaml").write_text("bedrooms: [Beds]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="bedrooms"):
        load_settings(path)


def test_severity_override_is_partial(tmp_path):
    path = _write_config(tmp_path, lambda d: d.update(severity={"NO_COORDINATES": "BLOCKING"}))
    s = load_settings(path)
    assert s.sev(FlagReason.NO_COORDINATES) is Severity.BLOCKING
    assert s.sev(FlagReason.LLM_UNAVAILABLE) is Severity.INFO


def test_llm_override():
    s = load_settings(CONFIG)
    assert apply_llm_override(s, "off").llm.enabled is False
    assert apply_llm_override(s, "mock").llm.provider == "mock"
    with pytest.raises(ConfigError):
        apply_llm_override(s, "gpt")
