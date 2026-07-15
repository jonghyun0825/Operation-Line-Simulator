@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

rem Check if port 8000 is already in use (server already running)
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if %errorlevel% neq 0 (
    echo Starting Line Simulator server...
    start "Line Simulator Server" /min cmd /c ""%PROJECT_DIR%venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000"
    timeout /t 3 /nobreak >nul
) else (
    echo Line Simulator server is already running.
)

start "" "http://127.0.0.1:8000"
endlocal
