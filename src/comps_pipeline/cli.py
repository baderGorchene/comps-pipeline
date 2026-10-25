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


def print_summary(result: pipeline.RunResult) -> None:
    table = Table(title=f"Shortlist (top 10 of {len(result.shortlist)})")
    for col in ("rank", "mls", "subdivision", "tier", "miles", "GLA", "flags"):
        table.add_column(col)
    flagged = Counter(f.mls_number for f in result.flags if f.origin != "GATE")
    for c in result.shortlist[:10]:
        d = c.distance_miles.value
        table.add_row(
            str(c.rank),
            c.mls_number,
            str(c.subdivision_raw.value or ""),
            str(c.subdivision_tier.value),
            "" if d is None else f"{d:.2f}",
            str(c.living_area.value or ""),
            str(flagged.get(c.mls_number, "")),
        )
    console.print(table)
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
