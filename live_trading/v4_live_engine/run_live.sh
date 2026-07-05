#!/usr/bin/env bash
# ★무장존 파리티 라이브 실행 (이 폴더 하나로 자립).
#   워커(H4마다 무장존 재계산) + 메인(터치 진입·포지션관리)을 함께 띄운다.
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1
export STAGE4D_DLCACHE="./data_cache"          # 워커 full-히스토리 시드 (폴더 내 parquet)
export ARMED_CACHE="./armed_cache.json"

# API 키: 기존과 동일하게 **컨트롤패널**(control_panel.py → live_settings.json)에서 입력한 키 사용.
#   워커·메인 둘 다 live_settings.json 우선 → env 폴백, 모드(live/demo)도 패널 설정 따름.
#   (env 로 줘도 됨: BYBIT_DEMO_API_KEY/SECRET 또는 BYBIT_LIVE_API_KEY/SECRET)
if [ ! -f live_settings.json ] && [ -z "$BYBIT_DEMO_API_KEY$BYBIT_LIVE_API_KEY$BYBIT_API_KEY" ]; then
  echo "[run] 경고: live_settings.json(컨트롤패널) 도 env 키도 없음. control_panel.py 로 키 입력하거나 env 설정 필요."
fi

echo "[run] 배경 워커 기동 (H4마다 무장존 → armed_cache.json)"
python -u arm_worker.py --loop --live > arm_worker.log 2>&1 &
WORKER_PID=$!
echo "[run] worker PID=$WORKER_PID (로그: arm_worker.log)"

# 첫 무장캐시 생성까지 대기(최초 full-gen ~15분). 캐시 없으면 메인은 진입 안 함(안전).
echo "[run] 첫 armed_cache 생성 대기중... (arm_worker.log 확인)"
for i in $(seq 1 60); do [ -f armed_cache.json ] && break; sleep 30; done

echo "[run] 메인 루프 기동"
trap "echo '[run] 종료: worker kill'; kill $WORKER_PID 2>/dev/null" EXIT
python -u main.py
