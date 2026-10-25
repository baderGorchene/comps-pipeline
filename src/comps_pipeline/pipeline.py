"""Orchestrates every stage in order. Python decides everything; the LLM only adds flags."""

import datetime as dt
import hashlib
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from comps_pipeline import __version__
from comps_pipeline.config.schema import Settings
from comps_pipeline.filters.geo import compute_distances
from comps_pipeline.filters.hard_filters import apply_hard_filters
from comps_pipeline.ingest.cleaner import clean
from comps_pipeline.ingest.mapper import InputError, map_rows, read_csv, suggest_mapping
from comps_pipeline.llm import LLMClient, build_client
from comps_pipeline.llm.review import review
from comps_pipeline.matching.subdivision import match_all
from comps_pipeline.models import (
    AuditEntry,
    Comp,
    Decision,
    Excluded,
    Flag,
    FlagReason,
    RunManifest,
    Severity,
    StageOutput,
    Subject,
)
from comps_pipeline.outputs.writers import write_manifest, write_outputs
from comps_pipeline.ranking.ranker import rank
from comps_pipeline.validation.gate import validate_review

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: str
    out_dir: Path
    shortlist: list[Comp]
    ranked: list[Comp]
    excluded: list[Excluded]
    flags: list[Flag]
    audit: list[AuditEntry]
    manifest: RunManifest
    paths: dict[str, Path] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """0 ok, 2 completed with BLOCKING flags."""
        return 2 if any(f.severity == Severity.BLOCKING for f in self.flags) else 0


def load_subject(path: Path) -> Subject:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise InputError(f"Subject file not found: {path}") from e
    except yaml.YAMLError as e:
        raise InputError(f"Invalid YAML in subject file {path}: {e}") from e
    try:
        return Subject.model_validate(data)
    except ValidationError as e:
        raise InputError(f"Invalid subject file {path}:\n{e}") from e


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _new_run_dir(output_dir: Path) -> tuple[str, Path]:
    base = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_id, n = base, 1
    while True:
        try:
            (output_dir / run_id).mkdir(parents=True, exist_ok=False)
            return run_id, output_dir / run_id
        except FileExistsError:
            n += 1
            run_id = f"{base}-{n}"


class _Timer:
    def __init__(self) -> None:
        self.durations: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        log.info("stage %s", name)
        try:
            yield
        finally:
            self.durations[name] = round(time.perf_counter() - start, 4)


def _summary(stage: str, **detail: object) -> AuditEntry:
    return AuditEntry(
        mls_number=None, stage=stage, decision=Decision.KEPT, rule="stage_summary", detail=detail
    )


def run(
    input_csv: Path,
    subject_file: Path,
    settings: Settings,
    llm_client: LLMClient | None = None,
) -> RunResult:
    """llm_client overrides the client built from settings (tests inject mocks this way)."""
    input_csv, subject_file = Path(input_csv), Path(subject_file)
    started_at = dt.datetime.now().isoformat(timespec="seconds")
    timer = _Timer()
    flags: list[Flag] = []
    audit: list[AuditEntry] = []
    excluded: list[Excluded] = []

    def absorb(stage_out: StageOutput) -> list[Comp]:
        flags.extend(stage_out.flags)
        audit.extend(stage_out.audit)
        excluded.extend(stage_out.excluded)
        return stage_out.comps

    with timer.stage("load_inputs"):
        subject = load_subject(subject_file)
        if llm_client is not None and settings.llm.enabled:
            client, llm_mode, llm_unavailable = llm_client, llm_client.model, None
        else:
            client, llm_mode, llm_unavailable = build_client(settings)
    with timer.stage("ingest"):
        df = read_csv(input_csv)
        rows = map_rows(df, settings.column_mapping)
        mapping = suggest_mapping(list(df.columns), settings.column_mapping)
        audit.append(_summary("ingest", rows=len(rows), column_mapping=mapping))
    raw_rows = dict(enumerate(rows, start=1))

    with timer.stage("clean"):
        comps = absorb(clean(rows, subject, settings))
        kept_after_clean = len(comps)
    with timer.stage("geo"):
        comps = absorb(compute_distances(comps, subject, settings))
    with timer.stage("subdivision"):
        comps = absorb(match_all(comps, subject, settings))
    with timer.stage("hard_filters"):
        comps = absorb(apply_hard_filters(comps, subject, settings))
    with timer.stage("rank"):
        ranked = rank(comps, subject, settings, prior_audit=audit)
        flags.extend(ranked.flags)
        audit.extend(ranked.audit)
        excluded.extend(ranked.excluded)
    batches = []
    with timer.stage("llm_review"):
        if client is None:
            flags.append(settings.flag(FlagReason.LLM_UNAVAILABLE, None, str(llm_unavailable)))
            audit.append(_summary("llm_review", message=llm_unavailable))
        else:
            batches = review(ranked.shortlist, client, settings)
            audit.append(_summary("llm_review", batches=len(batches), model=llm_mode))
    with timer.stage("validation_gate"):
        for b in batches:
            gate = validate_review(b.result, b.batch, settings, b.index, b.attempts)
            flags.extend(gate.accepted_flags + gate.gate_flags)
            audit.extend(gate.audit)

    for i, f in enumerate(flags, start=1):
        f.id = f"F{i:04d}"

    run_id, out_dir = _new_run_dir(settings.run.output_dir)
    with timer.stage("write_outputs"):
        paths = write_outputs(out_dir, ranked.shortlist, excluded, flags, audit, raw_rows)
    manifest = RunManifest(
        run_id=run_id,
        started_at=started_at,
        input_file=str(input_csv),
        input_sha256=sha256_file(input_csv),
        subject_file=str(subject_file),
        subject_sha256=sha256_file(subject_file),
        config_snapshot=settings.model_dump(mode="json"),
        package_version=__version__,
        llm_mode=llm_mode,
        row_counts={
            "input_rows": len(rows),
            "after_clean": kept_after_clean,
            "after_hard_filters": len(comps),
            "ranked": len(ranked.ranked),
            "shortlist": len(ranked.shortlist),
            "excluded": len(excluded),
            "flags": len(flags),
        },
        stage_durations_s=timer.durations,
    )
    paths["run_manifest.json"] = write_manifest(out_dir, manifest)
    log.info("run %s written to %s", run_id, out_dir)
    return RunResult(
        run_id=run_id,
        out_dir=out_dir,
        shortlist=ranked.shortlist,
        ranked=ranked.ranked,
        excluded=excluded,
        flags=flags,
        audit=audit,
        manifest=manifest,
        paths=paths,
    )
