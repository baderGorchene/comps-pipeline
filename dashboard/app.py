"""Streamlit dashboard. No business logic: it edits settings in memory and calls pipeline.run().

Launch: uv run streamlit run dashboard\\app.py
"""

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from comps_pipeline import pipeline
from comps_pipeline.config.loader import (
    DEFAULT_CONFIG,
    ConfigError,
    load_dotenv,
    load_settings,
    settings_from_dict,
)
from comps_pipeline.config.schema import RANKING_KEYS
from comps_pipeline.ingest.mapper import InputError

SAMPLE_CSV = Path("data/samples/mls_sample.csv")
SAMPLE_SUBJECT = Path("data/samples/subject.yaml")
FILE_ONLY_KEYS = ("column_mapping", "subdivision_aliases")  # live in their own YAML files

st.set_page_config(page_title="Comps pipeline", layout="wide")
load_dotenv()


@st.cache_data
def _defaults() -> dict:
    return load_settings(DEFAULT_CONFIG).model_dump(mode="json")


def sidebar(base: dict) -> dict:
    """Returns an edited copy of the settings dict. Nothing is written to disk here."""
    cfg = json.loads(json.dumps(base))
    f, r, b, llm = cfg["filters"], cfg["run"], cfg["ranking"]["tolerance_bands"], cfg["llm"]
    sb = st.sidebar
    sb.header("Filters")
    f["gla_bracket_pct"] = sb.number_input("GLA bracket (+/- %)", 0, 100, f["gla_bracket_pct"])
    f["gla_bracket_inclusive"] = sb.toggle("Boundary is inclusive", f["gla_bracket_inclusive"])
    f["lot_bracket_pct"] = sb.number_input(
        "Lot bracket, acres (+/- %)", 0, 100, f["lot_bracket_pct"]
    )
    f["max_distance_miles"] = sb.number_input(
        "Max distance (miles)", 0.05, 50.0, float(f["max_distance_miles"]), step=0.05
    )
    f["sale_date_max_months"] = sb.number_input(
        "Max sale age (months)", 1, 60, f["sale_date_max_months"]
    )
    f["require_subdivision_match"] = sb.toggle(
        "Require subdivision match", f["require_subdivision_match"]
    )
    f["subdivision_min_score"] = sb.slider(
        "Subdivision min fuzzy score", 0, 100, int(f["subdivision_min_score"])
    )
    f["missing_distance"] = sb.selectbox(
        "No coordinates",
        ["exclude", "keep_and_flag"],
        ["exclude", "keep_and_flag"].index(f["missing_distance"]),
    )

    sb.header("Ranking")
    order = sb.multiselect(
        "Hierarchy (in priority order, pick all seven)", RANKING_KEYS, cfg["ranking"]["hierarchy"]
    )
    cfg["ranking"]["hierarchy"] = order
    b["distance_miles"] = sb.number_input(
        "Distance band (mi)", 0.01, 5.0, float(b["distance_miles"])
    )
    b["gla_pct"] = sb.number_input("GLA band (%)", 0.5, 50.0, float(b["gla_pct"]))
    b["age_years"] = sb.number_input("Age band (years)", 0.5, 50.0, float(b["age_years"]))
    b["lot_pct"] = sb.number_input("Lot band (%)", 0.5, 100.0, float(b["lot_pct"]))
    r["shortlist_size"] = sb.number_input("Shortlist size", 1, 200, r["shortlist_size"])
    r["min_shortlist_size"] = sb.number_input(
        "Minimum sold candidates (else relax criteria)", 0, 200, r["min_shortlist_size"]
    )
    r["listing_shortlist_size"] = sb.number_input(
        "Listing shortlist size", 1, 200, r["listing_shortlist_size"]
    )
    cfg["selection"]["equal_counts_as_bracketed"] = sb.toggle(
        "Equal to subject counts as bracketed", cfg["selection"]["equal_counts_as_bracketed"]
    )

    sb.header("LLM review")
    modes = ["off", "mock", "gemini"]
    current = "off" if not llm["enabled"] else llm["provider"]
    choice = sb.selectbox("LLM mode", modes, modes.index(current))
    llm["enabled"] = choice != "off"
    if choice != "off":
        llm["provider"] = choice
    if choice == "mock":
        mock_modes = ["clean", "hallucinate_id", "fake_quote", "malformed", "error"]
        llm["mock_mode"] = sb.selectbox("Mock mode", mock_modes, mock_modes.index(llm["mock_mode"]))
    return cfg


def save_as_default(cfg: dict) -> None:
    shutil.copy(DEFAULT_CONFIG, DEFAULT_CONFIG.with_suffix(".yaml.bak"))
    data = {k: v for k, v in cfg.items() if k not in FILE_ONLY_KEYS}
    DEFAULT_CONFIG.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _defaults.clear()


def inputs() -> tuple[Path, Path] | None:
    c1, c2 = st.columns(2)
    csv_file = c1.file_uploader("MLS export (CSV)", type=["csv"])
    subject_file = c2.file_uploader("Subject (YAML)", type=["yaml", "yml"])
    if csv_file and subject_file:
        tmp = Path(tempfile.mkdtemp(prefix="comps_"))
        (tmp / "input.csv").write_bytes(csv_file.getvalue())
        (tmp / "subject.yaml").write_bytes(subject_file.getvalue())
        return tmp / "input.csv", tmp / "subject.yaml"
    if st.checkbox("Use the synthetic sample", value=not (csv_file or subject_file)):
        return SAMPLE_CSV, SAMPLE_SUBJECT
    return None


def show(result: pipeline.RunResult) -> None:
    p = result.paths
    st.success(
        f"Run {result.run_id}: {len(result.shortlist)} comps shortlisted, "
        f"{result.manifest.escalation_level} escalation step(s), exit code {result.exit_code}"
    )
    tabs = st.tabs(["Final 6", "Shortlist", "Red flags", "Excluded", "Audit", "Run info"])
    with tabs[0]:
        st.dataframe(
            pd.read_csv(p["final_selection.csv"], encoding="utf-8-sig", dtype=str),
            hide_index=True,
        )
        st.caption(f"Not bracketed: {result.final.gaps or 'none'}")
        if result.final.swaps:
            st.dataframe(pd.DataFrame(result.final.swaps).astype(str), hide_index=True)
    tabs = tabs[1:]
    with tabs[0]:
        st.dataframe(
            pd.read_csv(p["shortlist.csv"], encoding="utf-8-sig", dtype=str), hide_index=True
        )
    with tabs[1]:
        flags = pd.DataFrame([f.model_dump(mode="json") for f in result.flags])
        chosen = st.multiselect("Severity", ["BLOCKING", "REVIEW", "INFO"], ["BLOCKING", "REVIEW"])
        if not flags.empty:
            st.dataframe(flags[flags["severity"].isin(chosen)], hide_index=True)
    with tabs[2]:
        st.dataframe(
            pd.read_csv(p["excluded.csv"], encoding="utf-8-sig", dtype=str), hide_index=True
        )
    with tabs[3]:
        audit = pd.DataFrame([a.model_dump(mode="json") for a in result.audit])
        audit["detail"] = audit["detail"].map(json.dumps)  # mixed shapes; show as text
        st.dataframe(audit, hide_index=True)
    with tabs[4]:
        st.json(result.manifest.model_dump(mode="json"))
    st.subheader("Downloads")
    cols = st.columns(len(p))
    for col, (name, path) in zip(cols, p.items(), strict=True):
        col.download_button(name, path.read_bytes(), file_name=name, key=f"dl-{name}")


def main() -> None:
    st.title("Comparable sales shortlist")
    try:
        cfg = sidebar(_defaults())
    except ConfigError as e:
        st.error(str(e))
        return
    try:
        settings = settings_from_dict(cfg, source="dashboard settings")
    except ConfigError as e:
        st.sidebar.error(str(e))
        settings = None
    if st.sidebar.button("Save as default", disabled=settings is None):
        save_as_default(cfg)
        st.sidebar.success(f"Saved to {DEFAULT_CONFIG} (previous copy in settings.yaml.bak)")

    files = inputs()
    if st.button("Run", type="primary", disabled=settings is None or files is None):
        try:
            with st.spinner("Running pipeline..."):
                st.session_state["result"] = pipeline.run(files[0], files[1], settings)
        except (ConfigError, InputError) as e:
            st.error(str(e))
    if "result" in st.session_state:
        show(st.session_state["result"])


main()
