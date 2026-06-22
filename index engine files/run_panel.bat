@echo off
REM =========================================================
REM KIS Index Bot - Control Panel Launcher (Windows)
REM =========================================================
REM Usage:
REM   1) Place this file in kis_index_bot folder
REM   2) Double-click or run from cmd: run_panel.bat
REM
REM Uses port 8502 (avoid conflict with crypto bot on 8501)
REM =========================================================

REM Set UTF-8 codepage for proper output
chcp 65001 >nul

cd /d "%~dp0"

echo =============================================
echo  KIS Index Bot - Control Panel
echo =============================================
echo.
echo Working dir: %CD%
echo.

REM Activate venv if exists
if exist "venv\Scripts\activate.bat" (
    echo [venv] Activating venv\Scripts\activate.bat
    call venv\Scripts\activate.bat
) else (
    echo [venv] Not found - using system python
)

echo.
echo [Dependency check]
python -c "import streamlit, pandas, requests" 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] Missing dependencies. Run:
    echo    pip install streamlit pandas requests pybit python-dotenv numpy
    echo.
    pause
    exit /b 1
)

echo [Dependencies OK]
echo.
echo =============================================
echo  Starting Control Panel
echo =============================================
echo.
echo  Access URL: http://localhost:8502
echo.
echo  Stop: Ctrl+C
echo =============================================
echo.

streamlit run control_panel_idx.py --server.port 8502 --server.address 0.0.0.0

echo.
echo Control Panel stopped.
pause
