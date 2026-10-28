"""Pages: start a run, look at a run's results, list past runs. All shortlisting is done by
comps_pipeline; these views only collect inputs and read the files a run wrote."""

import csv
import json
import logging
import re
import shutil
import tempfile
from fractions import Fraction
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
from comps_pipeline.outputs.writers import OUTPUT_FILES
from web.forms import ATTRIBUTE_LABELS, InputsForm, RulesForm, SubjectForm

FILE_ONLY_KEYS = ("column_mapping", "subdivision_aliases")  # live in their own YAML files
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}(-[0-9]+)?$")
DOWNLOADS = (*OUTPUT_FILES, "subject.json", "run.log")
SQFT_PER_ACRE = 43560


def _config() -> dict[str, Any]:
    return load_settings(django_settings.CONFIG_FILE).model_dump(mode="json")


def _output_dir() -> Path:
    path = Path(_config()["run"]["output_dir"])
    return path if path.is_absolute() else django_settings.BASE_DIR / path


def _subject_initial() -> dict[str, Any]:
    src = django_settings.INPUT_SUBJECT
    if not src.exists():
        src = django_settings.SAMPLE_SUBJECT
    data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in data.items() if k in SubjectForm.base_fields}


def _save_default(cfg: dict[str, Any]) -> None:
    path = django_settings.CONFIG_FILE
    shutil.copy(path, path.with_suffix(".yaml.bak"))
    data = {k: v for k, v in cfg.items() if k not in FILE_ONLY_KEYS}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def new_run(request: HttpRequest) -> HttpResponse:
    cfg = _config()
    errors: list[str] = []
    if request.method == "POST":
        inputs = InputsForm(request.POST, request.FILES)
        subject_form = SubjectForm(request.POST)
        rules = RulesForm(request.POST)
        subject_ok = inputs.data.get("subject_source") == "yaml" or subject_form.is_valid()
        if inputs.is_valid() and subject_ok and rules.is_valid():
            try:
                settings = settings_from_dict(rules.apply_to(cfg), source="the rules form")
                tmp = Path(tempfile.mkdtemp(prefix="comps_"))
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
                    csv_path = tmp / "export.csv"
                    with csv_path.open("wb") as f:
                        for chunk in inputs.cleaned_data["csv_file"].chunks():
                            f.write(chunk)
                result = _run_pipeline(csv_path, subject_path, settings)
                if rules.cleaned_data["save_default"]:
                    _save_default(rules.apply_to(cfg))
                return redirect("results", run_id=result.run_id)
            except (ConfigError, InputError) as e:
                errors.append(str(e))
            except ValidationError as e:
                errors.append(f"The subject is not valid:\n{e}")
    else:
        inputs = InputsForm()
        subject_form = SubjectForm(initial=_subject_initial())
        rules = RulesForm(initial=RulesForm.initial_from(cfg))
    return render(
        request,
        "new_run.html",
        {"inputs": inputs, "subject": subject_form, "rules": rules, "errors": errors},
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


def _v(comp: dict, field: str) -> Any:
    cell = comp.get(field)
    return cell.get("value") if isinstance(cell, dict) else cell


def _acres(sqft: Any, acres: Any) -> Fraction | None:
    if sqft is not None:
        return Fraction(sqft, SQFT_PER_ACRE)
    return None if acres is None else Fraction(str(acres))


def _baths(full: Any, half: Any) -> Fraction | None:
    return None if full is None or half is None else full + Fraction(half, 2)


def _comp_attr(c: dict, attr: str) -> Any:
    return {
        "gla": lambda: _v(c, "living_area"),
        "lot": lambda: _acres(_v(c, "lot_size_sqft"), _v(c, "lot_size_acres")),
        "age": lambda: _v(c, "year_built"),
        "beds": lambda: _v(c, "bedrooms"),
        "baths": lambda: _baths(_v(c, "baths_full"), _v(c, "baths_half")),
    }[attr]()


def _subject_attr(s: dict, attr: str) -> Any:
    return {
        "gla": lambda: s.get("living_area"),
        "lot": lambda: _acres(s.get("lot_size_sqft"), s.get("lot_size_acres")),
        "age": lambda: s.get("year_built"),
        "beds": lambda: s.get("bedrooms"),
        "baths": lambda: _baths(s.get("baths_full"), s.get("baths_half")),
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


def results(request: HttpRequest, run_id: str) -> HttpResponse:
    run_dir = _run_dir(run_id)
    manifest = _json(run_dir / "run_manifest.json")
    final = _json(run_dir / "final_selection.json")
    shortlist = _json(run_dir / "shortlist.json")
    flags = _json(run_dir / "flags.json")
    subject = _json(run_dir / "subject.json") if (run_dir / "subject.json").is_file() else {}
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
    log_file = run_dir / "run.log"
    context = {
        "run_id": run_id,
        "manifest": manifest,
        "subject": subject,
        "grid": _grid(final, subject, cfg["selection"]["bracket_attributes"], gaps),
        "final_count": len(final),
        "gaps": [ATTRIBUTE_LABELS[g] for g in sorted(gaps) if g in ATTRIBUTE_LABELS],
        "blocking": blocking,
        "steps": steps,
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
        "log": log_file.read_text(encoding="utf-8") if log_file.is_file() else "",
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
                "input": Path(m["input_file"]).name,
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
