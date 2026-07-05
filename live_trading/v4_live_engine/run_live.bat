@echo off
REM ★무장존 파리티 라이브 (Windows 로컬 테스트용). Vultr(Linux)는 run_live.sh 사용.
cd /d "%~dp0"
set PYTHONUTF8=1
set STAGE4D_DLCACHE=./data_cache
set ARMED_CACHE=./armed_cache.json

REM API 키: 기존과 동일 컨트롤패널(control_panel.py -> live_settings.json) 사용. env 폴백도 지원.
if not exist live_settings.json if "%BYBIT_DEMO_API_KEY%%BYBIT_LIVE_API_KEY%%BYBIT_API_KEY%"=="" (
  echo [run] 경고: live_settings.json(컨트롤패널) 도 env 키도 없음. control_panel.py 로 키 입력 필요.
)

REM ★싱글턴 가드: 반복 실행해도 워커/메인이 누적되지 않게 이미 떠있으면 중단.
tasklist /v /fi "imagename eq cmd.exe" 2>nul | findstr /i "arm_worker" >nul
if %errorlevel%==0 (
  echo [run] 중단: arm_worker 가 이미 실행 중 (중복 기동 방지^). 먼저 종료 후 재실행하세요.
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
