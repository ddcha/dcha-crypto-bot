#!/bin/bash
# =========================================================
# v2.0_WICK 배포 후 검증 스크립트
# =========================================================

set -e
echo "============================================="
echo " v2.0_WICK 배포 검증 시작"
echo "============================================="

VENV_PY="/home/linuxuser/bybit_bot/venv/bin/python3"

# 1. 문법 검증
echo ""
echo "[1/6] 문법 검증..."
$VENV_PY -c "
import ast, py_compile
for f in ['config.py', 'strategy_engine.py', 'control_panel.py', 'main.py']:
    with open(f) as fh:
        src = fh.read()
    ast.parse(src)
    py_compile.compile(f, doraise=True)
    print(f'  [OK] {f}: {len(src.splitlines())} lines')
"

# 2. Config 값 확인
echo ""
echo "[2/6] Config 값 확인..."
$VENV_PY -c "
from config import (
    USE_TIER_PRIORITY_SORT, EXCLUDE_RECENT_H1_FOR_TIER,
    RP_TIER_MULT_TABLE, MAX_NOTIONAL_MULT_SA_FREE,
    RISK_MULTIPLIER_DEFAULT, LOOP_SLEEP_SECONDS,
    USE_1M_WICK_TOUCH, WICK_TOUCH_LOOKBACK_BARS, WICK_TOUCH_MAX_EXIT_FRAC,
)
# v1.9_REALISTIC 유지
assert USE_TIER_PRIORITY_SORT == True
assert EXCLUDE_RECENT_H1_FOR_TIER == 0
assert RP_TIER_MULT_TABLE == {0:1.5, 1:1.5, 2:1.0, 3:1.0, 4:1.0, 5:1.0}
assert MAX_NOTIONAL_MULT_SA_FREE == 999.0
assert RISK_MULTIPLIER_DEFAULT == 1.0
assert LOOP_SLEEP_SECONDS == 15
# v2.0_WICK 신규
assert USE_1M_WICK_TOUCH == True, 'USE_1M_WICK_TOUCH 가 True 가 아님'
assert WICK_TOUCH_LOOKBACK_BARS == 5, 'WICK_TOUCH_LOOKBACK_BARS != 5'
assert WICK_TOUCH_MAX_EXIT_FRAC == 0.30, 'WICK_TOUCH_MAX_EXIT_FRAC != 0.30'
print('  [OK] v1.9_REALISTIC config 유지')
print('  [OK] USE_1M_WICK_TOUCH = True')
print('  [OK] WICK_TOUCH_LOOKBACK_BARS = 5 (5분봉)')
print('  [OK] WICK_TOUCH_MAX_EXIT_FRAC = 0.30 (30%)')
"

# 3. generate_entry_signal 시그니처 확인
echo ""
echo "[3/6] generate_entry_signal 시그니처 확인..."
$VENV_PY -c "
from strategy_engine import generate_entry_signal
import inspect
sig = inspect.signature(generate_entry_signal)
params = list(sig.parameters.keys())
assert 'df_1m_raw' in params, 'df_1m_raw 파라미터 없음'
print('  [OK] df_1m_raw 파라미터 존재')
print(f'  전체 params: {params}')
"

# 4. main.py 의 1분봉 fetch 확인
echo ""
echo "[4/6] main.py 의 1분봉 fetch 로직 확인..."
if grep -q 'interval="1"' main.py && grep -q 'df_1m_raw=df_1m' main.py; then
    echo "  [OK] 1분봉 fetch 및 전달 확인"
else
    echo "  [ERR] main.py 에 1분봉 로직 없음"
    exit 1
fi

# 5. control_panel.py 의 모드 토글 확인
echo ""
echo "[5/6] control_panel.py 의 모드 토글 확인..."
if grep -q 'zones_view_mode' control_panel.py && grep -q '진입 후보만' control_panel.py; then
    echo "  [OK] 모드 토글 존재"
else
    echo "  [ERR] control_panel.py 에 모드 토글 없음"
    exit 1
fi

# 6. Settings store 읽기 테스트
echo ""
echo "[6/6] Settings store 읽기 테스트..."
$VENV_PY -c "
try:
    from settings_store import load_settings
    s = load_settings()
    portfolio = s.get('portfolio', {})
    rm = portfolio.get('risk_multiplier', 1.0)
    print(f'  [OK] risk_multiplier = {rm}')
except Exception as e:
    print(f'  [WARN] settings 읽기 실패: {e}')
"

echo ""
echo "============================================="
echo "✅ ALL CHECKS PASSED"
echo "============================================="
echo ""
echo "다음 단계:"
echo "  sudo systemctl restart bybit-bot.service"
echo "  sudo systemctl restart control-panel.service"
echo ""
echo "로그 확인:"
echo "  sudo journalctl -u bybit-bot -f"
echo ""
echo "패널 확인:"
echo "  http://158.247.231.108:8501"
echo "  → Active Zones 모니터에서 '진입 후보만' 모드 확인"
