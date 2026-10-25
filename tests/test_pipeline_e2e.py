import csv
import json

from typer.testing import CliRunner

from comps_pipeline import pipeline
from comps_pipeline.cli import app
from comps_pipeline.models import FlagReason
from comps_pipeline.outputs.writers import OUTPUT_FILES
from tests.conftest import CONFIG, SAMPLES

CSV, SUBJECT = SAMPLES / "mls_sample.csv", SAMPLES / "subject.yaml"


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_e2e_llm_off_writes_all_outputs(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    for name in OUTPUT_FILES:
        assert (result.out_dir / name).is_file(), name
    assert (result.out_dir / "shortlist.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    assert len(result.shortlist) == settings.run.shortlist_size
    assert [c.rank for c in result.shortlist] == list(range(1, len(result.shortlist) + 1))
    assert any(f.reason is FlagReason.LLM_UNAVAILABLE for f in result.flags)

    # Every input row is accounted for: shortlisted or excluded with at least one reason.
    excluded = _rows(result.out_dir / "excluded.csv")
    assert all(r["reasons"].strip() for r in excluded)
    assert len(excluded) + len(result.shortlist) == 300
    assert result.manifest.row_counts["input_rows"] == 300
    assert result.exit_code == 0


def test_planted_edge_cases_handled(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    reasons = " ".join(r["reasons"] for r in _rows(result.out_dir / "excluded.csv"))
    for expected in ("DUPLICATE_LISTING", "OUT_OF_DATE_RANGE", "gla_bracket", "max_distance"):
        assert expected in reasons
    flag_reasons = {f.reason for f in result.flags}
    assert {
        FlagReason.INVALID_VALUE,
        FlagReason.MISSING_REQUIRED_FIELD,
        FlagReason.NO_COORDINATES,
        FlagReason.SUBDIVISION_UNCERTAIN,
    } <= flag_reasons


def test_determinism_identical_shortlist_json(settings):
    a = pipeline.run(CSV, SUBJECT, settings)
    b = pipeline.run(CSV, SUBJECT, settings)
    assert a.run_id != b.run_id
    for name in ("shortlist.json", "shortlist.csv", "excluded.csv", "flags.json", "audit.jsonl"):
        assert (a.out_dir / name).read_bytes() == (b.out_dir / name).read_bytes(), name


def test_below_minimum_exits_2(settings):
    s = settings.model_copy(
        update={"filters": settings.filters.model_copy(update={"max_distance_miles": 0.05})}
    )
    result = pipeline.run(CSV, SUBJECT, s)
    (flag,) = [f for f in result.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]
    assert "max_distance" in flag.message
    assert result.exit_code == 2


def test_cli_run_and_errors(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(app, ["validate-config", "--config", str(CONFIG)])
    assert ok.exit_code == 0, ok.output

    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    res = runner.invoke(
        app, ["run", "--input", str(bad_csv), "--subject", str(SUBJECT), "--llm", "off"]
    )
    assert res.exit_code == 1
    assert "Foo" in res.output and "Bar" in res.output

    res = runner.invoke(app, ["inspect-csv", "--input", str(CSV)])
    assert res.exit_code == 0 and "SqFt Living" in res.output


def test_cli_run_success(settings, tmp_path, monkeypatch):
    # Point the CLI at a config whose output_dir is inside tmp_path.
    import shutil

    import yaml

    for name in ("settings.yaml", "column_mapping.yaml", "subdivision_aliases.yaml"):
        shutil.copy(CONFIG.parent / name, tmp_path / name)
    data = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    data["run"]["output_dir"] = str(tmp_path / "out")
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(
        app,
        [
            "run",
            "--input",
            str(CSV),
            "--subject",
            str(SUBJECT),
            "--config",
            "settings.yaml",
            "--llm",
            "off",
        ],
    )
    assert res.exit_code == 0, res.output
    (run_dir,) = (tmp_path / "out").iterdir()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["llm_mode"] == "off"
