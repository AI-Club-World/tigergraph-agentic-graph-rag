@echo off
echo Installing/updating dependencies...
call npm install
if %errorlevel% equ 0 (
    echo Dependencies installed successfully.
    echo Starting frontend dev server...
    call npm run dev
) else (
    echo Retrying with legacy peer dependency resolution...
    call npm install --legacy-peer-deps
    if %errorlevel% equ 0 (
        echo Dependencies installed successfully.
        echo Starting frontend dev server...
        call npm run dev
    ) else (
        echo Error: npm install failed.
        pause
        exit /b 1
    )
)
pause