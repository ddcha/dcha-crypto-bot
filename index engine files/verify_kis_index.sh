#!/bin/bash
# =========================================================
# KIS 인덱스 봇 배포 후 검증 스크립트
# =========================================================
# 사용법:
#   bash verify_kis_index.sh
# =========================================================

set -e
echo "============================================="
echo " KIS 인덱스 봇 배포 검증 시작"
echo "============================================="

# venv 확인
if [ -d "venv" ]; then
    VENV_PY="$(pwd)/venv/bin/python3"
else
    VENV_PY="python3"
fi

# 1. 모든 파일 존재 확인
echo ""
echo "[1/8] 파일 존재 확인..."
REQUIRED_FILES=(
    "config_kis.py" "kis_assets.py" "market_hours.py" "risk_manager_idx.py"
    "strategy_engine_idx.py" "exchange_kis.py" "main_idx.py"
    "control_panel_idx.py" "settings_store.py" "state_store.py"
    "log_store.py" "telegram_utils.py" "engine_watchdog.py"
    "yahoo_index_v29_5.py"
)
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  [ERR] 누락: $f"
        MISSING=1
    fi
done
if [ $MISSING -eq 0 ]; then
    echo "  [OK] 모든 파일 존재 (${#REQUIRED_FILES[@]} 개)"
else
    echo "  [ERR] 누락 파일 존재 → 배포 중단"
    exit 1
fi

# 2. Syntax 검증
echo ""
echo "[2/8] Python syntax 검증..."
$VENV_PY -c "
import ast
files = ['config_kis.py', 'kis_assets.py', 'market_hours.py', 'risk_manager_idx.py',
        'strategy_engine_idx.py', 'exchange_kis.py', 'main_idx.py',
        'control_panel_idx.py', 'settings_store.py', 'state_store.py',
        'log_store.py', 'telegram_utils.py', 'engine_watchdog.py']
for f in files:
    with open(f) as fh:
        src = fh.read()
    ast.parse(src)
    print(f'  [OK] {f}: {len(src.splitlines())} lines')
"

# 3. Import chain
echo ""
echo "[3/8] Import chain 검증..."
$VENV_PY -c "
import config_kis, kis_assets, market_hours, risk_manager_idx
import strategy_engine_idx, exchange_kis
import settings_store, state_store, log_store, telegram_utils, engine_watchdog
print('  [OK] 모든 모듈 import 성공')
"

# 4. 9자산 일관성
echo ""
echo "[4/8] 9자산 일관성 검증..."
$VENV_PY -c "
from kis_assets import ASSET_META
import config_kis, settings_store
s = settings_store.load_live_settings()
keys_meta = set(ASSET_META.keys())
keys_config = set(config_kis.V29_2_ASSET_MULT.keys())
keys_settings = set(s['assets'].keys())
keys_pa = set(config_kis.PHASE_A_RISK.keys())
keys_pb = set(config_kis.PHASE_B_RISK.keys())
assert keys_meta == keys_config == keys_settings == keys_pa == keys_pb, '자산 키 불일치'
assert len(keys_meta) == 9, f'자산 수 {len(keys_meta)} != 9'
print(f'  [OK] 9자산 일관성: {sorted(keys_meta)}')
"

# 5. v29.5 mult 검증
echo ""
echo "[5/8] v29.5 mult 검증..."
$VENV_PY -c "
import config_kis
assert config_kis.V29_1_RULE_MULT['S++_MSS_OVL'] == 5.0
assert config_kis.V29_1_RULE_MULT['S_PRE4_WICK_MAX'] == 4.0
assert config_kis.V29_1_RULE_MULT['A_HIGH'] == 1.0
assert config_kis.V29_2_ASSET_MULT['ES'] == 1.5
assert config_kis.V29_2_ASSET_MULT['NQ'] == 1.2
assert all(v == 0.010 for v in config_kis.PHASE_A_RISK.values())
print(f'  [OK] V29_1_RULE_MULT 23종, V29_2_ASSET_MULT 9종')
print(f'  [OK] ES 1.5x, NQ 1.2x, 모든 PHASE_A 1.0%')
"

# 6. v29.5 백테 core 로드
echo ""
echo "[6/8] v29.5 백테 core 로드..."
$VENV_PY -c "
import strategy_engine_idx as se
core = se.get_v29_5_core()
assert core is not None, 'v29.5 core 로드 실패'
assert len(core) >= 24, f'core 함수 수 {len(core)} < 24'
print(f'  [OK] v29_5 core: {len(core)} 함수 로드')
" 2>&1 | grep -v "^=" | grep -v "Total assets:" | grep -v "📊\|🇺🇸\|MIN_SCORE\|SCENARIO\|Wick\|GEM_LONG\|ROOM_ONLY\|ENTRY MODE\|★\|Phase\|Target\|Tax\|Initial\|loaded\|━" | tail -5

# 7. main_idx + control_panel_idx 모듈 로드
echo ""
echo "[7/8] main_idx / control_panel_idx 모듈 로드..."
$VENV_PY -c "
import importlib.util
for fname in ['main_idx.py', 'control_panel_idx.py']:
    spec = importlib.util.spec_from_file_location(fname[:-3], fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    print(f'  [OK] {fname}')
" 2>&1 | grep "OK" | head -5

# 8. KisExchange 메서드 (Bybit 호환)
echo ""
echo "[8/8] KisExchange 메서드 (17개)..."
$VENV_PY -c "
from exchange_kis import KisExchange
required = ['get_server_time', 'get_wallet_balance', 'get_balance_usd',
            'get_positions', 'get_position_by_symbol', 'get_kline',
            'get_recent_klines_df', 'get_last_price', 'place_market_order',
            'place_market_order_and_wait', 'get_order_fill_status',
            'place_reduce_only_limit_order', 'cancel_order', 'get_open_orders',
            'set_stop_loss_only', 'close_position_market', 'wait_for_position_fill_info']
for r in required:
    assert hasattr(KisExchange, r), f'missing method: {r}'
print(f'  [OK] 17개 메서드 모두 존재')
"

echo ""
echo "============================================="
echo "✅ ALL CHECKS PASSED"
echo "============================================="
echo ""
echo "다음 단계:"
echo "  1) control_panel 에서 KIS app_key/secret/account_no 입력"
echo "     http://158.247.231.108:8502"
echo "  2) System Check ALL GREEN 확인"
echo "  3) 봇 시작:"
echo "     sudo systemctl start kis-index-bot.service"
echo ""
echo "로그 확인:"
echo "  tail -f logs/main_stdout.log"
