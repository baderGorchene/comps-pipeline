@echo off
REM Run the pipeline on the synthetic sample. Outputs go to data\output\RUN_ID
cd /d "%~dp0"
uv run python -m comps_pipeline run --input data\samples\mls_sample.csv --subject data\samples\subject.yaml %*
exit /b %ERRORLEVEL%
