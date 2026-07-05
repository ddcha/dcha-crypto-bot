@echo off
REM ★컨트롤패널 싱글턴 런처 (Windows) — 이미 8501 떠있으면 중복 기동 안 함(누적 방지).
REM   streamlit 은 포트가 바쁘면 조용히 8502...로 옮겨 떠서 인스턴스가 쌓인다 → 포트 리스닝 체크로 차단.
cd /d "%~dp0"
set PYTHONUTF8=1

netstat -ano | findstr ":8501 " | findstr LISTENING >nul
if %errorlevel%==0 (
  echo [panel] 이미 실행 중 - http://localhost:8501 . 중복 기동 안 함.
  exit /b 0
)

echo [panel] 컨트롤패널 기동 - http://localhost:8501
python -m streamlit run control_panel.py --server.headless true --server.port 8501
