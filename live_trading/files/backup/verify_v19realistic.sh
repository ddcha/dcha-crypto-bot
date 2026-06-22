#!/bin/bash
# =========================================================
# v1.9_REALISTIC 배포 후 검증 스크립트
# =========================================================
# 사용법:
#   1) 서버에 업로드한 후 bybit_bot 디렉토리에서 실행:
#      cd /home/linuxuser/bybit_bot && bash verify_v19realistic.sh
#   2) 모든 체크가 [OK] 면 systemctl 로 서비스 재시작
# =========================================================

set -e
echo "============================================="
echo " v1.9_REALISTIC 배포 검증 시작"
echo "============================================="

VENV_PY="/home/linuxuser/bybit_bot/venv/bin/python3"

# 1. 문법 검증
echo ""
echo "[1/5] 문법 검증..."
$VENV_PY -c "
import ast, py_compile
for f in ['config.py', 'strategy_engine.py', 'control_panel.py']:
    with open(f) as fh:
        src = fh.read()
    ast.parse(src)
    py_compile.compile(f, doraise=True)
    print(f'  [OK] {f}: {len(src.splitlines())} lines')
"

# 2. Config 값 확인
echo ""
echo "[2/5] Config 값 확인..."
$VENV_PY -c "
from config import (
    USE_TIER_PRIORITY_SORT, EXCLUDE_RECENT_H1_FOR_TIER,
    RP_TIER_MULT_TABLE, MAX_NOTIONAL_MULT_SA_FREE,
    RISK_MULTIPLIER_DEFAULT, LOOP_SLEEP_SECONDS,
)
assert USE_TIER_PRIORITY_SORT == True, 'USE_TIER_PRIORITY_SORT 가 True 가 아님'
assert EXCLUDE_RECENT_H1_FOR_TIER == 0, 'EXCLUDE_RECENT_H1_FOR_TIER 가 0 이 아님 (실전 권장)'
assert RP_TIER_MULT_TABLE == {0:1.5, 1:1.5, 2:1.0, 3:1.0, 4:1.0, 5:1.0}, 'RP_TIER_MULT_TABLE 불일치'
assert MAX_NOTIONAL_MULT_SA_FREE == 999.0, 'MAX_NOTIONAL_MULT_SA_FREE 불일치'
assert RISK_MULTIPLIER_DEFAULT == 1.0, 'RISK_MULTIPLIER_DEFAULT 불일치'
assert LOOP_SLEEP_SECONDS == 15, f'LOOP_SLEEP_SECONDS 가 15 가 아님 (실제: {LOOP_SLEEP_SECONDS})'
print('  [OK] USE_TIER_PRIORITY_SORT = True')
print('  [OK] EXCLUDE_RECENT_H1_FOR_TIER = 0')
print('  [OK] LOOP_SLEEP_SECONDS = 15')
print('  [OK] RP_TIER_MULT_TABLE, MAX_NOTIONAL_MULT_SA_FREE, RISK_MULTIPLIER_DEFAULT 정상')
"

# 3. 주요 함수 import 체크
echo ""
echo "[3/5] 주요 함수 import 체크..."
$VENV_PY -c "
from strategy_engine import (
    evaluate_zones_at_current_time,
    compute_pre_entry_confluence,
    compute_wick_ratio_5,
    classify_tier_v19b,
    apply_rp_filter,
    resolve_notional_cap,
    generate_entry_signal,
)
import inspect

# exclude_recent_h1 파라미터 존재 확인
sig1 = inspect.signature(compute_pre_entry_confluence)
assert 'exclude_recent_h1' in sig1.parameters, 'compute_pre_entry_confluence 에 exclude_recent_h1 없음'
sig2 = inspect.signature(compute_wick_ratio_5)
assert 'exclude_recent_h1' in sig2.parameters, 'compute_wick_ratio_5 에 exclude_recent_h1 없음'
sig3 = inspect.signature(evaluate_zones_at_current_time)
assert 'exclude_recent_h1' in sig3.parameters, 'evaluate_zones_at_current_time 에 exclude_recent_h1 없음'
print('  [OK] evaluate_zones_at_current_time 함수 존재')
print('  [OK] exclude_recent_h1 파라미터 모두 존재')
"

# 4. Notional cap 동작 확인
echo ""
echo "[4/5] Notional cap 동작 확인..."
$VENV_PY -c "
from strategy_engine import resolve_notional_cap
assert resolve_notional_cap('S') == 999.0, 'S tier notional cap 오류'
assert resolve_notional_cap('A') == 999.0, 'A tier notional cap 오류'
assert resolve_notional_cap('B') == 3.0, 'B tier notional cap 오류'
assert resolve_notional_cap('C') == 3.0, 'C tier notional cap 오류'
print('  [OK] S/A tier = 999.0 (cap free)')
print('  [OK] B/C tier = 3.0')
"

# 5. Settings store 읽기 테스트
echo ""
echo "[5/5] Settings store 읽기 테스트..."
$VENV_PY -c "
try:
    from settings_store import load_settings
    s = load_settings()
    portfolio = s.get('portfolio', {})
    rm = portfolio.get('risk_multiplier', 1.0)
    print(f'  [OK] risk_multiplier = {rm}')
except Exception as e:
    print(f'  [WARN] settings 읽기 실패 (첫 실행이라면 정상): {e}')
"

echo ""
echo "============================================="
echo "✅ ALL CHECKS PASSED"
echo "============================================="
echo ""
echo "다음 단계: systemctl 로 서비스 재시작"
echo "  sudo systemctl restart bybit-bot.service"
echo "  sudo systemctl restart control-panel.service"
echo ""
echo "로그 확인:"
echo "  sudo journalctl -u bybit-bot -f"
echo ""
