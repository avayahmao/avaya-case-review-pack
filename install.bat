@echo off
REM =============================================================================
REM Avaya Case Review Suite — 1-click installer (Windows)
REM =============================================================================
REM This wrapper launches setup_env.ps1 with -ExecutionPolicy Bypass so it works
REM under corporate Group Policy that blocks .ps1 execution by default.
REM Double-click, or run from any cmd/PowerShell window.
REM =============================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
set "PS1_PATH=%SCRIPT_DIR%setup_env.ps1"

if not exist "%PS1_PATH%" (
    echo [ERROR] setup_env.ps1 not found next to install.bat: "%PS1_PATH%"
    pause
    exit /b 1
)

echo === Avaya Case Review Suite Installer ===
echo Launching PowerShell with ExecutionPolicy Bypass...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo === Installation finished. ===
) else (
    echo === Installation exited with code %EXITCODE% ===
)

REM Keep the window open when double-clicked so users can read messages.
pause
exit /b %EXITCODE%
