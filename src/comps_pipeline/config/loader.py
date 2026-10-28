from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from comps_pipeline.config.schema import Settings

DEFAULT_CONFIG = Path("config/settings.yaml")


class ConfigError(Exception):
    """Invalid or missing configuration."""


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e


def load_settings(path: Path = DEFAULT_CONFIG) -> Settings:
    """Load settings.yaml plus column_mapping.yaml and subdivision_aliases.yaml beside it."""
    path = Path(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    for key in ("column_mapping", "subdivision_aliases"):
        if key in data:
            raise ConfigError(f"'{key}' belongs in {key}.yaml, not in {path.name}")
    data["column_mapping"] = _read_yaml(path.parent / "column_mapping.yaml")
    aliases_file = path.parent / "subdivision_aliases.yaml"
    aliases = _read_yaml(aliases_file) if aliases_file.exists() else {}
    data["subdivision_aliases"] = aliases.get("aliases") or {}
    return settings_from_dict(data, source=str(path))


def settings_from_dict(data: dict[str, Any], source: str = "<dict>") -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration in {source}:\n{e}") from e
