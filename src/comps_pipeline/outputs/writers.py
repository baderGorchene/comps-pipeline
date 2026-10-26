"""Write one run's outputs. CSVs are UTF-8 with BOM so Excel on Windows reads them correctly."""

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from comps_pipeline.models import STANDARD_FIELDS, AuditEntry, Comp, Excluded, Flag, RunManifest

SHORTLIST_COLUMNS = [
    "pool",
    "rank",
    "mls_number",
    "status",
    "close_price",
    "close_date",
    "list_price",
    "living_area",
    "year_built",
    "lot_size_sqft",
    "lot_acres",
    "bedrooms",
    "baths_full",
    "baths_half",
    "subdivision_raw",
    "subdivision_normalized",
    "subdivision_tier",
    "subdivision_score",
    "distance_miles",
    "gla_diff_pct",
    "age_diff_years",
    "lot_diff_pct",
    "latitude",
    "longitude",
    "foundation_type",
    "public_remarks",
]
DISPLAY_DECIMALS = {"distance_miles": 3, "gla_diff_pct": 2, "lot_diff_pct": 2, "lot_acres": 4}
FLAG_COLUMNS = ["id", "mls_number", "field", "reason", "severity", "origin", "message", "evidence"]
OUTPUT_FILES = (
    "shortlist.csv",
    "shortlist.json",
    "final_selection.csv",
    "final_selection.json",
    "excluded.csv",
    "flags.json",
    "flags.csv",
    "audit.jsonl",
    "run_manifest.json",
)


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _display(name: str, value: Any) -> Any:
    if value is None:
        return ""
    if name in DISPLAY_DECIMALS:
        return round(value, DISPLAY_DECIMALS[name])
    return value


def shortlist_rows(shortlist: list[Comp], flags: list[Flag]) -> list[dict[str, Any]]:
    by_comp: dict[str, list[str]] = defaultdict(list)
    for f in flags:
        if f.mls_number and f.origin != "GATE":  # gate rejections are not facts about the comp
            by_comp[f.mls_number].append(f"{f.severity.value}:{f.reason.value}")
    rows = []
    for c in shortlist:
        row: dict[str, Any] = {"pool": c.pool, "rank": c.rank, "mls_number": c.mls_number}
        for name in SHORTLIST_COLUMNS[3:]:
            if name == "lot_acres":
                acres = c.lot_acres()
                value = None if acres is None else float(acres)
            else:
                value = getattr(c, name).value
            row[name] = _display(name, value)
        row["flags"] = "; ".join(by_comp.get(c.mls_number, []))
        rows.append(row)
    return rows


def excluded_rows(excluded: list[Excluded], raw_rows: dict[int, dict[str, Any]]) -> list[dict]:
    rows = []
    for e in excluded:
        raw = raw_rows.get(e.source_row, {})
        row = {
            "source_row": e.source_row,
            "mls_number": e.mls_number or "",
            "stage": e.stage,
            "reasons": " | ".join(e.reasons),
        }
        row.update({f: raw.get(f, "") for f in STANDARD_FIELDS if f != "mls_number"})
        rows.append(row)
    return rows


def write_outputs(
    out_dir: Path,
    shortlist: list[Comp],
    final: list[Comp],
    excluded: list[Excluded],
    flags: list[Flag],
    audit: list[AuditEntry],
    raw_rows: dict[int, dict[str, Any]],
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: out_dir / name for name in OUTPUT_FILES if name != "run_manifest.json"}

    _write_csv(
        paths["shortlist.csv"], [*SHORTLIST_COLUMNS, "flags"], shortlist_rows(shortlist, flags)
    )
    _write_json(paths["shortlist.json"], [c.model_dump(mode="json") for c in shortlist])
    _write_csv(
        paths["final_selection.csv"], [*SHORTLIST_COLUMNS, "flags"], shortlist_rows(final, flags)
    )
    _write_json(paths["final_selection.json"], [c.model_dump(mode="json") for c in final])
    excluded_cols = ["source_row", "mls_number", "stage", "reasons"] + [
        f for f in STANDARD_FIELDS if f != "mls_number"
    ]
    _write_csv(paths["excluded.csv"], excluded_cols, excluded_rows(excluded, raw_rows))
    flag_dicts = [f.model_dump(mode="json") for f in flags]
    _write_json(paths["flags.json"], flag_dicts)
    _write_csv(paths["flags.csv"], FLAG_COLUMNS, flag_dicts)
    with paths["audit.jsonl"].open("w", encoding="utf-8") as f:
        for entry in audit:
            f.write(entry.model_dump_json() + "\n")
    return paths


def write_manifest(out_dir: Path, manifest: RunManifest) -> Path:
    """Written last, so it can include the duration of writing the other outputs."""
    path = out_dir / "run_manifest.json"
    _write_json(path, manifest.model_dump(mode="json"))
    return path
