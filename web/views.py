"""Pages: start a run, configure all pipeline settings, inspect a run's results, list past runs.
All shortlisting is done by comps_pipeline; these views collect inputs, save configurations,
and read the structured outputs a run wrote."""

import csv
import json
import logging
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings as django_settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from pydantic import ValidationError

from comps_pipeline import pipeline
from comps_pipeline.config.loader import ConfigError, load_settings, settings_from_dict
from comps_pipeline.ingest.mapper import InputError
from comps_pipeline.models import Subject
from comps_pipeline.models.comp import lot_acres, total_baths
from comps_pipeline.outputs.writers import OUTPUT_FILES
from web.forms import (
    ATTRIBUTE_LABELS,
    FIELD_LABELS,
    ConfigForm,
    InputsForm,
    SubjectForm,
)

FILE_ONLY_KEYS = ("column_mapping", "subdivision_aliases")  # live in their own YAML files
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}(-[0-9]+)?$")
DOWNLOADS = (*OUTPUT_FILES, "subject.json", "run.log")

RULE_LABELS = {
    "max_distance": "Distance beyond maximum limit",
    "gla_bracket": "Living area outside ±% bracket",
    "lot_bracket": "Lot size outside ±% bracket",
    "sale_date_window": "Sold before lookback window cutoff",
    "subdivision_match": "Subdivision did not match subject",
    "required_features": "Missing required property feature",
    "STATUS_NOT_USED": "Unused MLS status (Expired / Withdrawn / Other)",
    "DUPLICATE_LISTING": "Duplicate MLS listing number",
    "MISSING_REQUIRED_FIELD": "Missing required field (e.g. MLS #, GLA, Close Price)",
    "INVALID_VALUE": "Unparseable or out-of-range field value",
}

HIERARCHY_LABELS = {
    "subdivision": "Subdivision Match",
    "distance": "Proximity (Distance)",
    "gla": "Living Area (GLA)",
    "age": "Year Built (Age)",
    "lot": "Lot Acreage",
    "beds": "Bedroom Count",
    "baths": "Bathroom Count",
}


def _config() -> dict[str, Any]:
    return load_settings(django_settings.CONFIG_FILE).model_dump(mode="json")


def _output_dir() -> Path:
    path = Path(_config()["run"]["output_dir"])
    return path if path.is_absolute() else django_settings.BASE_DIR / path


def _subject_initial() -> dict[str, Any]:
    src = django_settings.INPUT_SUBJECT
    if not src.exists():
        src = django_settings.SAMPLE_SUBJECT
    try:
        try:
            text = src.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = src.read_text(encoding="cp1252")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in SubjectForm.base_fields}


def _backup_and_write(path: Path, data: Any) -> None:
    if path.exists():
        shutil.copy(path, path.with_suffix(".yaml.bak"))
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _save_all_configs(cfg: dict[str, Any]) -> None:
    """Save settings.yaml, column_mapping.yaml, and subdivision_aliases.yaml."""
    settings_path = Path(django_settings.CONFIG_FILE)
    config_dir = settings_path.parent
    settings_data = {k: v for k, v in cfg.items() if k not in FILE_ONLY_KEYS}
    _backup_and_write(settings_path, settings_data)
    if "column_mapping" in cfg:
        _backup_and_write(config_dir / "column_mapping.yaml", cfg["column_mapping"])
    if "subdivision_aliases" in cfg:
        _backup_and_write(
            config_dir / "subdivision_aliases.yaml", {"aliases": cfg["subdivision_aliases"]}
        )


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _run_pipeline(csv_path: Path, subject_path: Path, settings) -> pipeline.RunResult:
    capture, logger = _LogCapture(), logging.getLogger("comps_pipeline")
    previous = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        result = pipeline.run(csv_path, subject_path, settings)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous)
    (result.out_dir / "run.log").write_text("\n".join(capture.lines) + "\n", encoding="utf-8")
    return result


def _cfg_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    f, r, s = cfg["filters"], cfg["run"], cfg["selection"]
    return {
        "gla_pct": f["gla_bracket_pct"],
        "lot_pct": f["lot_bracket_pct"],
        "max_miles": f["max_distance_miles"],
        "max_months": f["sale_date_max_months"],
        "require_sub": f["require_subdivision_match"],
        "sold_count": s["sold_count"],
        "listing_count": s["listing_count"],
        "shortlist_size": r["shortlist_size"],
        "min_shortlist_size": r["min_shortlist_size"],
        "listing_shortlist_size": r["listing_shortlist_size"],
        "escalation_steps": len(cfg["escalation"]["steps"]),
        "hierarchy": [HIERARCHY_LABELS.get(k, k) for k in cfg["ranking"]["hierarchy"]],
        "brackets": [ATTRIBUTE_LABELS.get(b, b) for b in s["bracket_attributes"]],
        "mapped_fields": sum(1 for v in cfg.get("column_mapping", {}).values() if v),
        "aliases_count": len(cfg.get("subdivision_aliases", {})),
    }


def new_run(request: HttpRequest) -> HttpResponse:
    cfg = _config()
    errors: list[str] = []
    if request.method == "POST":
        inputs = InputsForm(request.POST, request.FILES)
        subject_form = SubjectForm(request.POST)
        subject_ok = inputs.data.get("subject_source") == "yaml" or subject_form.is_valid()
        if inputs.is_valid() and subject_ok:
            try:
                settings = load_settings(django_settings.CONFIG_FILE)
                with tempfile.TemporaryDirectory(prefix="comps_") as tmp_dir:
                    tmp = Path(tmp_dir)
                    subject_path = tmp / "subject.yaml"
                    if inputs.cleaned_data["subject_source"] == "yaml":
                        subject_path.write_bytes(inputs.cleaned_data["subject_file"].read())
                    else:
                        data = subject_form.subject_dict()
                        Subject.model_validate(data)
                        subject_path.write_text(yaml.safe_dump(data), encoding="utf-8")
                    if inputs.cleaned_data["csv_source"] == "sample":
                        csv_path = django_settings.SAMPLE_CSV
                    else:
                        upload = inputs.cleaned_data["csv_file"]
                        safe_name = Path(upload.name).name or "export.csv"
                        csv_path = tmp / safe_name
                        with csv_path.open("wb") as f:
                            for chunk in upload.chunks():
                                f.write(chunk)
                    result = _run_pipeline(csv_path, subject_path, settings)
                return redirect("results", run_id=result.run_id)
            except (ConfigError, InputError) as e:
                errors.append(str(e))
            except ValidationError as e:
                errors.append(f"The subject is not valid:\n{e}")
        else:
            for field_errs in inputs.errors.values():
                errors.extend(field_errs)
            if not subject_ok:
                for name, field_errs in subject_form.errors.items():
                    errors.extend(f"{name}: {e}" for e in field_errs)
    else:
        inputs = InputsForm()
        subject_form = SubjectForm(initial=_subject_initial())
    return render(
        request,
        "new_run.html",
        {
            "inputs": inputs,
            "subject": subject_form,
            "summary": _cfg_summary(cfg),
            "errors": errors,
        },
    )


def config_view(request: HttpRequest) -> HttpResponse:
    cfg = _config()
    errors: list[str] = []
    saved = request.GET.get("saved") == "1"
    if request.method == "POST":
        form = ConfigForm(request.POST)
        if form.is_valid():
            try:
                updated = form.apply_to(cfg)
                settings_from_dict(updated, source="configuration")
                _save_all_configs(updated)
                return redirect("/config/?saved=1")
            except ConfigError as e:
                errors.append(str(e))
    else:
        form = ConfigForm(initial=ConfigForm.initial_from(cfg))
    return render(
        request,
        "config.html",
        {
            "form": form,
            "saved": saved,
            "errors": errors,
            "summary": _cfg_summary(cfg),
        },
    )


# ---- reading a finished run -------------------------------------------------------------


def _run_dir(run_id: str) -> Path:
    path = _output_dir() / run_id
    if not RUN_ID.match(run_id) or not _readable(path):
        raise Http404("No such run")
    return path


def _readable(run_dir: Path) -> bool:
    """Runs from before the final selection existed cannot be shown."""
    return all((run_dir / n).is_file() for n in ("run_manifest.json", "final_selection.json"))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_entries(run_dir: Path) -> list[dict[str, Any]]:
    audit_path = run_dir / "audit.jsonl"
    if not audit_path.is_file():
        return []
    entries = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _v(comp: dict, field: str) -> Any:
    cell = comp.get(field)
    return cell.get("value") if isinstance(cell, dict) else cell


def _comp_attr(c: dict, attr: str) -> Any:
    return {
        "gla": lambda: _v(c, "living_area"),
        "lot": lambda: lot_acres(_v(c, "lot_size_sqft"), _v(c, "lot_size_acres")),
        "age": lambda: _v(c, "year_built"),
        "beds": lambda: _v(c, "bedrooms"),
        "baths": lambda: total_baths(_v(c, "baths_full"), _v(c, "baths_half")),
    }[attr]()


def _subject_attr(s: dict, attr: str) -> Any:
    return {
        "gla": lambda: s.get("living_area"),
        "lot": lambda: lot_acres(s.get("lot_size_sqft"), s.get("lot_size_acres")),
        "age": lambda: s.get("year_built"),
        "beds": lambda: s.get("bedrooms"),
        "baths": lambda: total_baths(s.get("baths_full"), s.get("baths_half")),
    }[attr]()


def _fmt(attr: str, value: Any) -> str:
    if value is None:
        return "—"
    if attr == "lot":
        return f"{float(value):.3f} ac"
    if attr == "baths":
        return f"{float(value):g}"
    if attr == "gla":
        return f"{value:,}"
    return str(value)


def _side(value: Any, target: Any) -> str:
    if value is None or target is None:
        return ""
    return "above" if value > target else "below" if value < target else "equal"


def _money(v: Any) -> str:
    return "—" if v is None else f"${v:,}"


def _grid(final: list[dict], subject: dict, bracket: list[str], gaps: set[str]) -> dict:
    """The final pick laid out like the sales comparison grid on the appraisal form."""
    columns = [
        {
            "title": f"Comp {i}" if c["pool"] == "sold" else "Listing",
            "mls": c["mls_number"],
            "pool": c["pool"],
            "status": _v(c, "status") or "",
        }
        for i, c in enumerate(final, start=1)
    ]
    rows = []
    for attr in ("gla", "lot", "age", "beds", "baths"):
        target = _subject_attr(subject, attr)
        if attr not in bracket:
            state = "not checked"
        elif target is None:
            state = "subject unknown"
        else:
            state = "gap" if attr in gaps else "bracketed"
        rows.append(
            {
                "label": ATTRIBUTE_LABELS[attr],
                "subject": _fmt(attr, target),
                "cells": [
                    {
                        "text": _fmt(attr, _comp_attr(c, attr)),
                        "side": _side(_comp_attr(c, attr), target),
                    }
                    for c in final
                ],
                "state": state,
            }
        )
    facts = [
        ("Price", "", [_money(_v(c, "close_price") or _v(c, "list_price")) for c in final]),
        ("Sold / listed", "", [_v(c, "close_date") or "Listed" for c in final]),
        ("Distance", "", [_miles(_v(c, "distance_miles")) for c in final]),
        ("Subdivision", subject.get("subdivision", ""), [_v(c, "subdivision_raw") for c in final]),
    ]
    return {"columns": columns, "rows": rows, "facts": facts}


def _miles(v: Any) -> str:
    return "—" if v is None else f"{v:.2f} mi"


def _comp_row(c: dict, picked: set[str], flag_counts: dict[str, int]) -> dict:
    acres = _comp_attr(c, "lot")
    baths = _comp_attr(c, "baths")
    return {
        "rank": c["rank"],
        "mls": c["mls_number"],
        "status": _v(c, "status") or "",
        "price": _money(_v(c, "close_price") or _v(c, "list_price")),
        "date": _v(c, "close_date") or "",
        "gla": _fmt("gla", _v(c, "living_area")),
        "acres": "—" if acres is None else f"{float(acres):.3f}",
        "year": _v(c, "year_built") or "—",
        "beds": _fmt("beds", _v(c, "bedrooms")),
        "baths": _fmt("baths", baths),
        "miles": _miles(_v(c, "distance_miles")),
        "subdivision": _v(c, "subdivision_raw") or "",
        "same_subdivision": _v(c, "subdivision_tier") in (0, 1),
        "flags": flag_counts.get(c["mls_number"], 0),
        "picked": c["mls_number"] in picked,
    }


STEP_LABELS = {
    "max_distance_miles": "distance {} mi",
    "gla_bracket_pct": "living area ±{}%",
    "lot_bracket_pct": "lot ±{}%",
    "sale_date_max_months": "sold within {} months",
}


def _describe_step(overrides: dict[str, Any]) -> str:
    return ", ".join(STEP_LABELS.get(k, k + " {}").format(v) for k, v in overrides.items())


def _build_pipeline_trace(
    manifest: dict[str, Any],
    audit: list[dict[str, Any]],
    shortlist: list[dict[str, Any]],
    final: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    subject: dict[str, Any],
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a visual, human-readable step-by-step walkthrough of what happened under the hood."""
    counts = manifest.get("row_counts", {})
    cfg = manifest.get("config_snapshot", {})
    input_rows = counts.get("input_rows", 0)
    after_clean = counts.get("after_clean", 0)
    after_hf = counts.get("after_hard_filters", 0)
    shortlist_sold = counts.get("shortlist_sold", 0)
    shortlist_listing = counts.get("shortlist_listing", 0)
    final_count = counts.get("final", 0)

    # 1. Ingest & Column Mapping
    mapped_cols: list[tuple[str, str]] = []
    unmapped_cols: list[str] = []
    for a in audit:
        if a.get("stage") == "ingest" and a.get("rule") == "stage_summary":
            col_map = a.get("detail", {}).get("column_mapping", {})
            for std_field, csv_header in col_map.items():
                label = FIELD_LABELS.get(std_field, (std_field, ""))[0]
                if csv_header:
                    mapped_cols.append((label, csv_header))
                else:
                    unmapped_cols.append(label)

    # 2. Data Cleaning breakdown
    clean_excl_counts = Counter(
        a.get("rule")
        for a in audit
        if a.get("stage") == "clean" and a.get("decision") == "EXCLUDED"
    )
    clean_reasons = [
        {"label": RULE_LABELS.get(rule, rule), "count": count}
        for rule, count in clean_excl_counts.most_common()
    ]
    clean_dropped = max(0, input_rows - after_clean)

    # 3. Distance & Subdivision insights
    no_coords = sum(
        1 for f in flags if f.get("reason") == "NO_COORDINATES"
    )
    fuzzy_subs = sum(
        1 for f in flags if f.get("reason") == "SUBDIVISION_UNCERTAIN"
    )
    has_subject_gps = subject.get("latitude") is not None and subject.get("longitude") is not None
    same_sub_shortlist = sum(1 for c in shortlist if _v(c, "subdivision_tier") in (0, 1))

    # 4. Hard filters breakdown
    hf_excl_counts = Counter(
        a.get("rule")
        for a in audit
        if a.get("stage") == "hard_filters" and a.get("decision") == "EXCLUDED"
    )
    hf_dropped = max(0, after_clean - after_hf)
    hf_reasons = []
    for rule, count in hf_excl_counts.most_common():
        pct = round((count / max(1, after_clean)) * 100)
        hf_reasons.append(
            {"label": RULE_LABELS.get(rule, rule), "count": count, "pct": min(100, pct)}
        )

    # 5. Ranking hierarchy & tolerance bands
    bands = cfg.get("ranking", {}).get("tolerance_bands", {})
    band_notes = {
        "subdivision": "Tier 0/1/2/3",
        "distance": f"±{bands.get('distance_miles', 0.25)} mi tie band",
        "gla": f"±{bands.get('gla_pct', 5)}% tie band",
        "age": f"±{bands.get('age_years', 5)} yr tie band",
        "lot": f"±{bands.get('lot_pct', 10)}% tie band",
        "beds": f"±{bands.get('beds_count', 1)} bed tie band",
        "baths": f"±{bands.get('baths_count', 1)} bath tie band",
    }
    hierarchy_chain = [
        {
            "order": idx,
            "name": HIERARCHY_LABELS.get(k, k),
            "band": band_notes.get(k, ""),
        }
        for idx, k in enumerate(cfg.get("ranking", {}).get("hierarchy", []), start=1)
    ]

    # 6. Final selection & bracket swaps
    swaps = [
        {
            "removed": a["detail"]["removed"],
            "added": a["detail"]["added"],
            "fixed": [
                ATTRIBUTE_LABELS.get(g, g)
                for g in a["detail"].get("gaps_before", [])
                if g not in a["detail"].get("gaps_after", [])
            ],
        }
        for a in audit
        if a.get("stage") == "final_selection" and a.get("rule") == "swap"
    ]

    f_cfg = cfg.get("filters", {})
    dist_mode = "using GPS Haversine coordinates" if has_subject_gps else "using Distance column"
    fuzzy_note = (
        f"; {fuzzy_subs} close spelling match(es) flagged for review." if fuzzy_subs else "."
    )
    min_sold = cfg.get("run", {}).get("min_shortlist_size", 20)
    esc_lvl = manifest.get("escalation_level", 0)
    relax_note = (
        f"Rules were automatically relaxed ({esc_lvl} step(s)) "
        f"to reach the minimum sold threshold ({min_sold})."
        if esc_lvl > 0
        else "Baseline rules met the minimum sold threshold without needing relaxation."
    )
    return [
        {
            "num": 1,
            "title": "CSV Ingestion & Column Mapping",
            "badge": f"{input_rows} rows read",
            "summary": (
                f"Read {input_rows} property rows from {Path(manifest.get('input_file', '')).name} "
                f"and matched {len(mapped_cols)} spreadsheet headers to standard appraisal fields."
            ),
            "mapped_cols": mapped_cols,
            "unmapped_cols": unmapped_cols,
        },
        {
            "num": 2,
            "title": "Validation, Deduplication & Status Split",
            "badge": f"{after_clean} valid · {clean_dropped} removed",
            "summary": (
                f"Checked MLS numbers, stripped duplicate listings, classified rows into Sold vs. "
                f"Active/Pending pools, and parsed numeric/date fields against effective date "
                f"{subject.get('effective_date', '')}."
            ),
            "reasons": clean_reasons,
        },
        {
            "num": 3,
            "title": "Geographic Distance & Subdivision Matching",
            "badge": ("GPS Haversine" if has_subject_gps else "MLS Reported Distance"),
            "summary": (
                f"Calculated proximity to {subject.get('address', 'the subject')} "
                f"({dist_mode}) and normalized subdivision names against "
                f'"{subject.get("subdivision", "")}".'
            ),
            "bullets": [
                f"{after_clean - no_coords} of {after_clean} comps had usable distance measurements"
                + (f" ({no_coords} missing coordinates)." if no_coords else "."),
                f"{same_sub_shortlist} shortlisted comps matched the subject subdivision directly"
                + fuzzy_note,
            ],
        },
        {
            "num": 4,
            "title": "Eligibility Filtering & Auto-Relaxation",
            "badge": f"{after_hf} passed · {hf_dropped} filtered out",
            "summary": (
                f"Applied baseline rules (GLA ±{f_cfg.get('gla_bracket_pct', 25)}%, "
                f"Lot ±{f_cfg.get('lot_bracket_pct', 25)}%, "
                f"Max {f_cfg.get('max_distance_miles', 3.0)} mi, "
                f"Sold within {f_cfg.get('sale_date_max_months', 12)} mo). " + relax_note
            ),
            "steps": steps,
            "hf_reasons": hf_reasons,
        },
        {
            "num": 5,
            "title": "Multi-Criteria Tolerance Ranking",
            "badge": f"{shortlist_sold} sold · {shortlist_listing} listing shortlisted",
            "summary": (
                "Ranked Sold candidates and Active/Pending listings separately using tolerance "
                "bands (comps within the same tolerance band tie on that attribute and are "
                "decided by the next priority)."
            ),
            "hierarchy": hierarchy_chain,
        },
        {
            "num": 6,
            "title": "Subject Bracketing & Final Selection",
            "badge": f"{final_count} final picks",
            "summary": (
                f"Selected top {cfg.get('selection', {}).get('sold_count', 5)} sold comps and "
                f"{cfg.get('selection', {}).get('listing_count', 1)} active/pending listing, "
                "verifying that at least one comp sits above and one below the subject on every "
                "checked attribute."
            ),
            "swaps": swaps,
        },
    ]


def results(request: HttpRequest, run_id: str) -> HttpResponse:
    run_dir = _run_dir(run_id)
    manifest = _json(run_dir / "run_manifest.json")
    final = _json(run_dir / "final_selection.json")
    shortlist = _json(run_dir / "shortlist.json")
    flags = _json(run_dir / "flags.json")
    subject = _json(run_dir / "subject.json") if (run_dir / "subject.json").is_file() else {}
    audit = _audit_entries(run_dir)
    with (run_dir / "excluded.csv").open(encoding="utf-8-sig", newline="") as f:
        excluded = [{**r, "reasons": r["reasons"].split(" | ")} for r in csv.DictReader(f)]

    cfg = manifest["config_snapshot"]
    gaps = {f["field"] for f in flags if f["reason"] == "NOT_BRACKETED"}
    picked = {c["mls_number"] for c in final}
    flag_counts: dict[str, int] = {}
    for f in flags:
        if f["mls_number"]:
            flag_counts[f["mls_number"]] = flag_counts.get(f["mls_number"], 0) + 1
    blocking = [f for f in flags if f["severity"] == "BLOCKING"]
    attempts = manifest.get("escalation_attempts", [])
    level = manifest.get("escalation_level", 0)
    steps = [
        {
            "level": a["level"],
            "label": "Your rules"
            if a["level"] == 0
            else "Relaxed: " + _describe_step(a["overrides"]),
            "sold": a["sold_kept"],
            "listing": a["listing_kept"],
            "used": a["level"] == level,
        }
        for a in attempts
    ]
    severity_order = {"BLOCKING": 0, "REVIEW": 1, "INFO": 2}
    pipeline_trace = _build_pipeline_trace(
        manifest, audit, shortlist, final, flags, subject, steps
    )
    context = {
        "run_id": run_id,
        "manifest": manifest,
        "subject": subject,
        "grid": _grid(final, subject, cfg["selection"]["bracket_attributes"], gaps),
        "final_count": len(final),
        "gaps": [ATTRIBUTE_LABELS[g] for g in sorted(gaps) if g in ATTRIBUTE_LABELS],
        "blocking": blocking,
        "steps": steps,
        "pipeline_trace": pipeline_trace,
        "min_sold": cfg["run"]["min_shortlist_size"],
        "sold": [_comp_row(c, picked, flag_counts) for c in shortlist if c["pool"] == "sold"],
        "listings": [
            _comp_row(c, picked, flag_counts) for c in shortlist if c["pool"] == "listing"
        ],
        "excluded": excluded,
        "flags": sorted(flags, key=lambda f: (severity_order[f["severity"]], f["id"])),
        "review_count": sum(f["severity"] == "REVIEW" for f in flags),
        "counts": manifest["row_counts"],
        "input_name": Path(manifest["input_file"]).name,
        "downloads": [n for n in DOWNLOADS if (run_dir / n).is_file()],
    }
    return render(request, "results.html", context)


def history(request: HttpRequest) -> HttpResponse:
    runs = []
    out = _output_dir()
    for d in sorted(out.iterdir(), reverse=True) if out.is_dir() else []:
        if not (RUN_ID.match(d.name) and _readable(d)):
            continue
        m = _json(d / "run_manifest.json")
        subject = _json(d / "subject.json") if (d / "subject.json").is_file() else {}
        flags = _json(d / "flags.json") if (d / "flags.json").is_file() else []
        runs.append(
            {
                "id": d.name,
                "started": m["started_at"].replace("T", " "),
                "address": subject.get("address", "Subject not recorded"),
                "subdivision": subject.get("subdivision", ""),
                "input": Path(m["input_file"]).name,
                "input_rows": m["row_counts"].get("input_rows", 0),
                "after_hf": m["row_counts"].get("after_hard_filters", 0),
                "final": m["row_counts"].get("final", 0),
                "level": m.get("escalation_level", 0),
                "blocked": any(f["severity"] == "BLOCKING" for f in flags),
            }
        )
    return render(request, "history.html", {"runs": runs})


def download(request: HttpRequest, run_id: str, name: str) -> FileResponse:
    if name not in DOWNLOADS:
        raise Http404("No such file")
    path = _run_dir(run_id) / name
    if not path.is_file():
        raise Http404("No such file")
    return FileResponse(path.open("rb"), as_attachment=True, filename=name)
