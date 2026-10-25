import pandas as pd
import pytest

from comps_pipeline.ingest.mapper import InputError, map_rows, read_csv, suggest_mapping
from tests.conftest import SAMPLES

MAPPING = {
    "mls_number": ["MLS #"],
    "close_price": ["Close Price"],
    "close_date": ["Close Date"],
    "living_area": ["SqFt Living", "GLA"],
    "subdivision_raw": ["Subdivision"],
}


def test_read_csv_keeps_text(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("MLS #,Zip,Note\n00123,07001,NA\n", encoding="utf-8")
    df = read_csv(path)
    row = df.iloc[0]
    assert (row["MLS #"], row["Zip"], row["Note"]) == ("00123", "07001", "NA")


def test_mapping_is_case_and_whitespace_insensitive():
    found = suggest_mapping(["  sqft living ", "gla"], {"living_area": ["SqFt Living", "GLA"]})
    assert found == {"living_area": "  sqft living "}


def test_unmapped_columns_go_to_extras():
    df = pd.DataFrame(
        [["1", "$1", "1/1/2026", "1500", "X", "Y"]],
        columns=["MLS #", "Close Price", "Close Date", "GLA", "Subdivision", "Pool"],
    )
    (row,) = map_rows(df, MAPPING)
    assert row["living_area"] == "1500"
    assert row["extras"] == {"Pool": "Y"}


def test_missing_required_column_lists_available_headers():
    df = pd.DataFrame([["1", "2"]], columns=["MLS #", "Weird Size"])
    with pytest.raises(InputError) as e:
        map_rows(df, MAPPING)
    msg = str(e.value)
    assert "living_area" in msg
    assert "MLS #" in msg and "Weird Size" in msg


def test_sample_maps_with_repo_mapping(settings):
    rows = map_rows(read_csv(SAMPLES / "mls_sample.csv"), settings.column_mapping)
    assert len(rows) == 300
    assert {"Status", "Beds", "Pool"} <= set(rows[0]["extras"])
