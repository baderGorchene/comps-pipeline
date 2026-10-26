"""Command line: python -m comps_pipeline <command>. Exit codes: 0 ok, 1 config/input error,
2 completed with BLOCKING flags."""

import logging
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from comps_pipeline import pipeline
from comps_pipeline.config.loader import (
    DEFAULT_CONFIG,
    ConfigError,
    apply_llm_override,
    load_dotenv,
    load_settings,
)
from comps_pipeline.ingest.mapper import REQUIRED_COLUMNS, InputError, read_csv, suggest_mapping
from comps_pipeline.logging_setup import setup_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Comparable sales pipeline.")
console = Console()
log = logging.getLogger(__name__)

ConfigOpt = Annotated[Path, typer.Option("--config", help="Path to settings.yaml")]
LogOpt = Annotated[str, typer.Option("--log-level", help="DEBUG, INFO, WARNING")]


def _fail(e: Exception) -> typer.Exit:
    console.print(f"[bold red]Error:[/] {e}")
    return typer.Exit(1)


def _num(value: object) -> str:
    return "?" if value is None else str(value)


def print_summary(result: pipeline.RunResult) -> None:
    pools = Counter(c.pool for c in result.shortlist)
    table = Table(
        title=f"Final selection ({pools['sold']} sold + {pools['listing']} listings shortlisted)"
    )
    for col in ("pool", "rank", "mls", "subdivision", "miles", "GLA", "acres", "bd/fb/hb", "flags"):
        table.add_column(col)
    flagged = Counter(f.mls_number for f in result.flags if f.origin != "GATE")
    for c in result.final.picks:
        d, acres = c.distance_miles.value, c.lot_acres()
        rooms = (c.bedrooms.value, c.baths_full.value, c.baths_half.value)
        table.add_row(
            c.pool or "",
            str(c.rank),
            c.mls_number,
            str(c.subdivision_raw.value or ""),
            "" if d is None else f"{d:.2f}",
            str(c.living_area.value or ""),
            "" if acres is None else f"{float(acres):.3f}",
            "/".join(_num(v) for v in rooms),
            str(flagged.get(c.mls_number, "")),
        )
    console.print(table)
    console.print(
        f"Escalation steps applied: {result.manifest.escalation_level}  |  "
        f"not bracketed: {result.final.gaps or 'none'}  |  swaps: {len(result.final.swaps)}"
    )
    severities = Counter(f.severity.value for f in result.flags)
    console.print(
        f"Flags: {dict(sorted(severities.items()))}  |  excluded rows: {len(result.excluded)}"
        f"  |  LLM: {result.manifest.llm_mode}"
    )
    console.print(f"Outputs: [bold]{result.out_dir}[/]")
    if result.exit_code == 2:
        for f in result.flags:
            if f.severity == "BLOCKING":
                console.print(f"[bold red]BLOCKING[/] {f.reason.value}: {f.message}")


@app.command("run")
def run_cmd(
    input_csv: Annotated[Path, typer.Option("--input", help="MLS export CSV")],
    subject: Annotated[Path, typer.Option("--subject", help="Subject property YAML")],
    config: ConfigOpt = DEFAULT_CONFIG,
    llm: Annotated[str | None, typer.Option("--llm", help="gemini | mock | off")] = None,
    log_level: LogOpt = "INFO",
) -> None:
    """Run the full pipeline and write outputs to data/output/<run_id>/."""
    setup_logging(log_level)
    load_dotenv()
    try:
        settings = apply_llm_override(load_settings(config), llm)
        result = pipeline.run(input_csv, subject, settings)
    except (ConfigError, InputError) as e:
        raise _fail(e) from e
    print_summary(result)
    raise typer.Exit(result.exit_code)


@app.command("validate-config")
def validate_config(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Check settings.yaml, column_mapping.yaml and subdivision_aliases.yaml."""
    try:
        settings = load_settings(config)
    except ConfigError as e:
        raise _fail(e) from e
    console.print(f"[green]OK[/] {config}")
    console.print(f"hierarchy: {settings.ranking.hierarchy}")
    console.print(f"mapped fields: {sorted(settings.column_mapping)}")


@app.command("inspect-csv")
def inspect_csv(
    input_csv: Annotated[Path, typer.Option("--input", help="MLS export CSV")],
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """List the CSV headers and the mapping column_mapping.yaml would apply."""
    try:
        settings = load_settings(config)
        headers = list(read_csv(input_csv).columns)
    except (ConfigError, InputError) as e:
        raise _fail(e) from e
    found = suggest_mapping(headers, settings.column_mapping)
    table = Table(title=f"{input_csv}")
    table.add_column("standard field")
    table.add_column("CSV header")
    for field in settings.column_mapping:
        header = found.get(field)
        required = " (required)" if field in REQUIRED_COLUMNS else ""
        table.add_row(field + required, header or "[red]-- not found --[/]")
    console.print(table)
    unmapped = [h for h in headers if h not in found.values()]
    console.print(f"Unmapped headers (kept as extras): {unmapped}")
    missing = [f for f in REQUIRED_COLUMNS if f not in found]
    if missing:
        console.print(f"[bold red]Missing required fields:[/] {missing}")
        raise typer.Exit(1)


SAMPLE_CSV = Path("data/samples/mls_sample.csv")
SAMPLE_SUBJECT = Path("data/samples/subject.yaml")


def _flag_table(title: str, flags: list) -> Table:
    table = Table(title=title)
    for col in ("reason", "mls", "evidence / message"):
        table.add_column(col)
    for f in flags:
        table.add_row(f.reason.value, f.mls_number or "-", (f.evidence or f.message)[:90])
    return table


def run_demo(config: Path = DEFAULT_CONFIG) -> int:
    """Synthetic data with mock hallucinate_id, then fake_quote. Returns an exit code."""
    settings = load_settings(config)
    if not SAMPLE_CSV.exists():
        console.print("[red]No sample data.[/] Run: uv run python scripts/generate_synthetic.py")
        return 1
    baseline = pipeline.run(SAMPLE_CSV, SAMPLE_SUBJECT, apply_llm_override(settings, "off"))
    baseline_json = (baseline.out_dir / "shortlist.json").read_bytes()
    console.print(f"Baseline run with LLM off: {len(baseline.shortlist)} comps shortlisted")
    ok = True
    for mode in ("hallucinate_id", "fake_quote"):
        llm = settings.llm.model_copy(
            update={"enabled": True, "provider": "mock", "mock_mode": mode, "cache": False}
        )
        result = pipeline.run(SAMPLE_CSV, SAMPLE_SUBJECT, settings.model_copy(update={"llm": llm}))
        accepted = [f for f in result.flags if f.origin == "LLM"]
        rejected = [f for f in result.flags if f.origin == "GATE"]
        console.rule(f"mock mode: {mode}")
        console.print(_flag_table(f"Accepted by the gate ({len(accepted)})", accepted))
        console.print(_flag_table(f"Rejected by the gate ({len(rejected)})", rejected))
        same = (result.out_dir / "shortlist.json").read_bytes() == baseline_json
        mark = "[green]identical[/]" if same else "[bold red]DIFFERENT[/]"
        console.print(f"shortlist.json vs LLM-off run: {mark}")
        ok = ok and same and bool(rejected)
    console.print("[green]Demo passed[/]" if ok else "[bold red]Demo failed[/]")
    return 0 if ok else 1


@app.command()
def demo(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Show the validation gate rejecting a hallucinated ID and a fake quote."""
    setup_logging("WARNING")
    try:
        code = run_demo(config)
    except (ConfigError, InputError) as e:
        raise _fail(e) from e
    raise typer.Exit(code)
