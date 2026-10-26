# dashboard

A Streamlit front end for the same pipeline the CLI runs. It contains no business logic: it edits an in-memory copy of the settings and calls `pipeline.run()`.

## Launch

```powershell
run_dashboard.bat
# or
uv run streamlit run dashboard\app.py
```

Your browser opens at http://localhost:8501.

## Use

1. In the sidebar, adjust the GLA bracket, radius, subdivision rules, ranking order, tolerance bands and LLM mode. These changes apply to this session only.
2. Upload an MLS CSV (or tick "Use the synthetic sample CSV"). For the subject, either fill in the form (prefilled with the sample subject; click **Apply subject** after editing) or switch to **Upload YAML**. "Download as subject.yaml" saves the form so you can reuse it from the command line.
3. Click **Run**. Results appear in tabs: Shortlist, Red flags (filter by severity), Excluded, Audit, Run info. Every output file has a download button.
4. **Save as default** writes the current sidebar values to `config/settings.yaml`. Nothing is written unless you click it. The old file is kept as `settings.yaml.bak`.

## Planned
A map view of the subject and comps (see `src/comps_pipeline/extensions/README.md`).
