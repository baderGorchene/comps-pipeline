@echo off
REM Start the comps shortlist app and open it in the browser: http://127.0.0.1:8000/
REM Close this window (or press Ctrl+C) to stop it.
cd /d "%~dp0"
uv sync --quiet || exit /b 1
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
uv run python manage.py runserver 127.0.0.1:8000 --noreload
exit /b %ERRORLEVEL%
