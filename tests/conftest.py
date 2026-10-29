import datetime as dt
from pathlib import Path

import pytest

from comps_pipeline.config.loader import load_settings
from comps_pipeline.config.schema import Settings
from comps_pipeline.models import Cell, Comp, Source, Subject

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "settings.yaml"
SAMPLES = ROOT / "data" / "samples"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Repo settings with every output redirected to tmp_path."""
    s = load_settings(CONFIG)
    return s.model_copy(update={"run": s.run.model_copy(update={"output_dir": tmp_path / "out"})})


def with_filters(s: Settings, **update) -> Settings:
    return s.model_copy(update={"filters": s.filters.model_copy(update=update)})


@pytest.fixture
def subject() -> Subject:
    return Subject(
        address="1 Test St",
        latitude=30.5,
        longitude=-97.7,
        living_area=2000,
        subdivision="Brushy Creek Phase 2",
        effective_date=dt.date(2026, 10, 1),
        year_built=2005,
        lot_size_sqft=8000,
    )


def make_comp(mls: str, **values) -> Comp:
    """Comp with MLS-sourced cells for every keyword given (value None -> empty cell)."""
    cells = {
        k: Cell(value=v, source=Source.MLS) if v is not None else Cell() for k, v in values.items()
    }
    return Comp(mls_number=mls, source_row=1, **cells)
