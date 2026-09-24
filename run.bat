@echo off
echo Starting backend and frontend dev servers in parallel...
start "Backend Server" /D "backend" cmd /k call run-backend.bat
start "Frontend Dev Server" /D "frontend" cmd /k call run-frontend.bat
echo Both servers launched in separate command windows.
echo Press any key to exit this launcher window...
pause >nul
exit /b 0