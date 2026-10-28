"""Read the raw CSV as text and rename client headers to standard field names."""

from pathlib import Path
from typing import Any

import pandas as pd

# The pipeline cannot shortlist without these columns.
# close_price/close_date are only needed for sold rows, so they are checked per row.
REQUIRED_COLUMNS = ("mls_number", "status", "living_area", "subdivision_raw")


class InputError(Exception):
    """Bad input file (unreadable CSV, missing column, invalid subject)."""


def read_csv(path: Path) -> pd.DataFrame:
    """dtype=str and no NA guessing: every cell stays exactly the text in the file.

    UTF-8 first; MLS exports saved by Excel on Windows are often cp1252 (curly quotes).
    """
    try:
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp1252")
    except FileNotFoundError as e:
        raise InputError(f"CSV not found: {path}") from e
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        raise InputError(f"Cannot read CSV {path}: {e}") from e


def suggest_mapping(headers: list[str], mapping: dict[str, list[str]]) -> dict[str, str]:
    """standard field -> CSV header. Case-insensitive, whitespace-trimmed, first candidate wins."""
    by_key: dict[str, str] = {}
    for h in headers:
        by_key.setdefault(h.strip().casefold(), h)
    found: dict[str, str] = {}
    for field, candidates in mapping.items():
        for candidate in candidates:
            header = by_key.get(candidate.strip().casefold())
            if header is not None and header not in found.values():
                found[field] = header
                break
    return found


def map_rows(df: pd.DataFrame, mapping: dict[str, list[str]]) -> list[dict[str, Any]]:
    """One dict per CSV row: standard fields as raw strings, unmapped columns under 'extras'."""
    headers = list(df.columns)
    found = suggest_mapping(headers, mapping)
    missing = [f for f in REQUIRED_COLUMNS if f not in found]
    if missing:
        raise InputError(
            f"Required column(s) not found: {', '.join(missing)}.\n"
            f"Available CSV headers: {', '.join(headers)}\n"
            "Add the matching header names to config/column_mapping.yaml."
        )
    mapped = set(found.values())
    rows = []
    for record in df.to_dict("records"):
        row: dict[str, Any] = {field: record[header] for field, header in found.items()}
        row["extras"] = {h: v for h, v in record.items() if h not in mapped}
        rows.append(row)
    return rows
