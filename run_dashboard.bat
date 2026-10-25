@echo off
REM Launch the dashboard in your browser.
cd /d "%~dp0"
uv run streamlit run dashboard\app.py
