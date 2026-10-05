@echo off
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Virtual environment not found. Run setup first.
    exit /b 1
)
echo Installing/updating dependencies...
pip install -e ".[dev]"
if errorlevel 1 (
    echo Error: pip install failed.
    pause
    exit /b 1
)
python -m uvicorn ogr.api.main:app --app-dir src --host 127.0.0.1 --port 8000
pause