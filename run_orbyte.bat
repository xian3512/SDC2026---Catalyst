@echo off
setlocal
cd /d "%~dp0"
echo Starting Orbyte backend from: %CD%
echo Keep this window open while using the dashboard.
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo.
  echo Orbyte did not start. Read the error above.
  echo If uvicorn is missing, activate your project .venv and install requirements.txt.
  echo If port 8000 is already in use, stop the old server and run this file again.
  pause
)
endlocal
