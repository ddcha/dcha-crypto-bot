@echo off
REM ★무장존 파리티 라이브 (Windows 로컬 테스트용). Vultr(Linux)는 run_live.sh 사용.
cd /d "%~dp0"
set PYTHONUTF8=1
set STAGE4D_DLCACHE=./data_cache
set ARMED_CACHE=./armed_cache.json

if "%BYBIT_DEMO_API_KEY%"=="" (
  echo [run] BYBIT_DEMO_API_KEY 필요. set BYBIT_DEMO_API_KEY=... 후 재실행.
  exit /b 1
)

echo [run] 배경 워커 기동 (별 창) — H4마다 무장존 재계산
start "arm_worker" cmd /c "python -u arm_worker.py --loop --live > arm_worker.log 2>&1"

echo [run] 첫 armed_cache 생성 대기 (최초 full-gen ~15분, arm_worker.log 확인)
:waitcache
if exist armed_cache.json goto runmain
timeout /t 30 >nul
goto waitcache

:runmain
echo [run] 메인 루프 기동
python -u main.py
