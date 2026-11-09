@echo off
REM One-click local runner for the Item Request Portal.
REM Assumes a .venv already exists in this folder (Python 3.12 or 3.13).
cd /d "%~dp0"

REM Local machine: without this the app assumes production and refuses the
REM placeholder SECRET_KEY (app/config.py fails closed).
set APP_ENV=dev

if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Create it first with:
    echo    python -m venv .venv
    echo    ^(python must be 3.12 or 3.13 from python.org; check with: where.exe python^)
    pause
    exit /b 1
)

echo === [1/4] Installing packages ^(first run takes 1-2 min^) ===
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err

echo === [2/4] Applying database migrations ===
".venv\Scripts\python.exe" -m alembic upgrade head || goto :err

echo === [3/4] Seeding reference data ===
".venv\Scripts\python.exe" -m app.seed || goto :err

echo === [4/4] Starting server ===
echo.
echo    Open your browser at:  http://localhost:8000
echo    Press Ctrl+C here to stop the server.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
goto :eof

:err
echo.
echo *** เกิด error - ถ่าย screenshot บรรทัดสีแดงส่งให้ Claude ***
pause
