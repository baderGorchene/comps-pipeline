import csv

from comps_pipeline import pipeline
from comps_pipeline.models import FlagReason
from comps_pipeline.outputs.writers import OUTPUT_FILES
from tests.conftest import SAMPLES

CSV, SUBJECT = SAMPLES / "mls_sample.csv", SAMPLES / "subject.yaml"


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_e2e_writes_all_outputs(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    for name in OUTPUT_FILES:
        assert (result.out_dir / name).is_file(), name
    assert (result.out_dir / "shortlist.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    sold = [c for c in result.shortlist if c.pool == "sold"]
    listings = [c for c in result.shortlist if c.pool == "listing"]
    assert len(sold) == settings.run.shortlist_size and listings
    assert result.shortlist == sold + listings
    for pool in (sold, listings):
        assert [c.rank for c in pool] == list(range(1, len(pool) + 1))
    picks = result.final.picks
    assert [c.pool for c in picks] == ["sold"] * 5 + ["listing"]
    assert len(_rows(result.out_dir / "final_selection.csv")) == 6

    # Every input row is accounted for: shortlisted or excluded with at least one reason.
    excluded = _rows(result.out_dir / "excluded.csv")
    assert all(r["reasons"].strip() for r in excluded)
    assert len(excluded) + len(result.shortlist) == 300
    assert result.manifest.row_counts["input_rows"] == 300
    assert result.exit_code == 0


def test_planted_edge_cases_handled(settings):
    result = pipeline.run(CSV, SUBJECT, settings)
    reasons = " ".join(r["reasons"] for r in _rows(result.out_dir / "excluded.csv"))
    for expected in ("DUPLICATE_LISTING", "STATUS_NOT_USED", "sale_date_window", "gla_bracket"):
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
    names = ("shortlist.json", "final_selection.json", "excluded.csv", "flags.json", "audit.jsonl")
    for name in names:
        assert (a.out_dir / name).read_bytes() == (b.out_dir / name).read_bytes(), name


def _escalating(settings, start_miles, steps):
    return settings.model_copy(
        update={
            "filters": settings.filters.model_copy(update={"max_distance_miles": start_miles}),
            "escalation": settings.escalation.model_copy(update={"steps": steps}),
        }
    )


def test_escalation_relaxes_until_enough_sold(settings):
    s = _escalating(settings, 0.05, [{"max_distance_miles": 0.1}, {"max_distance_miles": 3.0}])
    result = pipeline.run(CSV, SUBJECT, s)
    assert result.manifest.escalation_level == 2
    attempts = result.manifest.escalation_attempts
    assert [a["sold_kept"] < settings.run.min_shortlist_size for a in attempts] == [
        True,
        True,
        False,
    ]
    relaxed = [f for f in result.flags if f.reason is FlagReason.CRITERIA_RELAXED]
    assert len(relaxed) == 2
    assert not [f for f in result.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]


def test_below_minimum_after_escalation_exits_2(settings):
    s = _escalating(settings, 0.05, [{"max_distance_miles": 0.1}])
    result = pipeline.run(CSV, SUBJECT, s)
    assert result.manifest.escalation_level == 1
    (flag,) = [f for f in result.flags if f.reason is FlagReason.SHORTLIST_BELOW_MINIMUM]
    assert "max_distance" in flag.message
    assert result.exit_code == 2


def test_second_round_keeps_good_drops_flagged_and_refills(settings):
    first = pipeline.run(CSV, SUBJECT, settings)
    assert first.manifest.second_round is None
    picked = {c.mls_number for c in first.final.picks}
    bad = next(
        f for f in first.flags if f.mls_number in picked
    )  # pretend this flag = not comparable
    cfg = settings.second_round.model_copy(update={"remove_if_flagged": [bad.reason]})
    s = settings.model_copy(update={"second_round": cfg})

    r = pipeline.run(CSV, SUBJECT, s, find_more=True)
    info = r.manifest.second_round
    removed, first_sl = set(info["removed"]), {c.mls_number for c in first.shortlist}
    shortlisted = {c.mls_number for c in r.shortlist}
    assert bad.mls_number in removed and not removed & shortlisted
    assert set(info["kept"]) == first_sl - removed <= shortlisted  # good comps never re-judged
    added = {c.mls_number for c in r.shortlist if c.found_in_round == 2}
    assert added == set(info["added"]) and added and not added & first_sl
    assert not removed & {c.mls_number for c in r.final.picks}
    assert len(r.final.picks) == 6
    excluded = _rows(r.out_dir / "excluded.csv")
    assert len(excluded) + len(r.shortlist) == 300  # still every row accounted for
    assert any("SECOND_ROUND_REMOVED" in e["reasons"] for e in excluded)


def test_second_round_explains_itself(settings):
    r = pipeline.run(CSV, SUBJECT, settings, find_more=True)
    info = r.manifest.second_round
    if info is None:  # sample run needed nothing; force a shortfall via an impossible count
        s = settings.model_copy(
            update={"selection": settings.selection.model_copy(update={"sold_count": 99})}
        )
        info = pipeline.run(CSV, SUBJECT, s, find_more=True).manifest.second_round
    assert {
        "level_round_1",
        "steps_available",
        "no_looser_rules",
        "blocked_by",
        "only_miss",
    } <= set(info)
    assert info["passed_rules"] >= info["candidates_checked"]


def test_fill_keeps_never_relax_rules(settings):
    # 200 sold wanted: the sample can't satisfy it, so fillers appear; none may break never_relax.
    s = settings.model_copy(
        update={"selection": settings.selection.model_copy(update={"sold_count": 200})}
    )
    r = pipeline.run(CSV, SUBJECT, s)
    filled = [f for f in r.flags if f.reason == FlagReason.OUTSIDE_RULES_PICK]
    assert filled and all("sub_type_and_stories" not in f.message for f in filled)
    sold = [c for c in r.final.picks if c.pool == "sold"]
    filled_mls = {f.mls_number for f in filled}
    first_filler = next(i for i, c in enumerate(sold) if c.mls_number in filled_mls)
    assert all(c.mls_number in filled_mls for c in sold[first_filler:])  # fillers rank last
