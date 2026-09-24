@echo off
cd frontend
if errorlevel 1 (
    echo Error: Cannot change to frontend directory.
    exit /b 1
)
echo Installing/updating dependencies...
npm install
if errorlevel 1 (
    echo Retrying with legacy peer dependency resolution...
    npm install --legacy-peer-deps
    if errorlevel 1 (
        echo Error: npm install failed.
        pause
        exit /b 1
    )
)
npm run dev
pause