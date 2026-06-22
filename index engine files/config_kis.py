"""
================================================================
한투 KIS 인덱스 자동매매 - 메인 Config
================================================================
v29.5 baseline 9자산 + 코인 봇 v2.2 운용 인프라 결합

[운용 흐름 - 진입 결정]
  1) Zone-Proximity Trigger (코인 v2.2 그대로)
     - Light loop: 5초 가격 polling
     - Hot symbols: zone ±0.5% 이내인 자산만 풀 분석
  2) v29.5 baseline 진입 판단 (코인 tier 시스템 X)
     - compute_trade_tags (12 atoms)
     - classify_v25idx_subtier → S++/S/A+/A/XB
     - XB 차단 (시나리오 B 12종 + v29.4 추가 3종)
  3) Mult 계산
     - rule_mult (V29_1_RULE_MULT): 5.0 ~ 1.0
     - asset_mult (V29_2_ASSET_MULT): ES 1.5x, NQ 1.2x
     - combined_mult = rule × asset
  4) Position sizing
     - 정수 계약 (floor)
     - min_qty=1 강제 (백테 거래 빈도 유지)
     - max_open_positions=8 (둠챠 결정)

[v29.5 백테 baseline]
  216 trades, Win 63.0%, PF 4.03, MDD -17.28%, Return +4,929%
================================================================
"""
from __future__ import annotations

# ============================================================
# Exchange / API
# ============================================================
USE_TESTNET = False        # KIS 는 testnet 개념 X (모의/실전 분리)
USE_DEMO = True            # 모의투자 모드 (둠챠 모의계좌 00225351-08)

# KIS API 도메인 (settings_store 에서 읽음)
KIS_DEMO_BASE_URL = "https://openapivts.koreainvestment.com:29443"   # 모의투자
KIS_LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"      # 실전

# ============================================================
# Timeframe (v29.5 baseline 동일: 2h / 1h)
# ============================================================
HTF_INTERVAL = "120"       # 2시간 (코인 봇 H4_INTERVAL 대체)
LTF_INTERVAL = "60"        # 1시간

HTF_LIMIT = 2000           # 2h × 2000 = 약 167일 (백테 baseline 동일)
LTF_LIMIT = 1200           # 1h × 1200 = 약 50일

# 코인 봇 변수명 호환 alias (main_idx.py 가 H4_INTERVAL 변수 그대로 사용)
H4_INTERVAL = HTF_INTERVAL
H1_INTERVAL = LTF_INTERVAL
H4_LIMIT = HTF_LIMIT
H1_LIMIT = LTF_LIMIT

# 코인 호환: CATEGORY (인덱스에선 의미 없으나 import 호환용)
CATEGORY = "futures_idx"
# 코인 호환: MAX_NOTIONAL_MULT (인덱스는 MAX_NOTIONAL_PCT_OF_BALANCE 사용)
MAX_NOTIONAL_MULT = 999.0  # 사실상 무제한, 인덱스는 별도 cap

# ============================================================
# Risk - v29.5 baseline + 둠챠 결정
# ============================================================
FEE_RATE = 0.00025          # 인덱스 선물 수수료 (KIS 평균)
RISK_MULTIPLIER_DEFAULT = 1.0
RISK_MULTIPLIER_MIN = 0.1
RISK_MULTIPLIER_MAX = 3.0

# 둠챠 결정: 안전장치는 max_open_positions=8 만
MAX_OPEN_POSITIONS_DEFAULT = 8

# Notional cap (잔고 대비 max %, 1000% = 10x leverage)
# 인덱스는 leverage 가 본질적 → 코인보다 높음
MAX_NOTIONAL_PCT_OF_BALANCE = 1000.0

# ============================================================
# v29.5 RULE Mult Table (yahoo_index_v29_5.py 와 동일)
# ============================================================
V29_1_RULE_MULT = {
    # S++ 핵심
    "S++_MSS_OVL":          5.0,
    "S++_SC24_FVG_WICK":    4.5,
    "S++_SC24_WICK_RFVG":   4.5,
    "S++_SC24_SCORE_WICK":  2.5,
    # S 핵심
    "S_PRE4_WICK_MAX":      4.0,   # ⭐ 메인 알파
    "S_FVG_MAX_S":          2.5,
    # A+ 중 승격
    "A+_FVG_D_RP3":         3.5,
    # 나머지 S 계열
    "S_PRE4_SCORE":         2.0,
    "S_SCORE_S":            2.5,
    "S_SCORE_MAX_WICK":     2.5,
    # A+ / A 1.0x 통일
    "A+_MAX":               1.0,
    "A+_SCORE_FVG":         1.0,
    "A_HIGH":               1.0,
    "A_RP3":                1.0,
    "A_RP2":                1.0,
    # S+ 5종 (도달 불가, 안전망)
    "S+_MAX_RFVG_S":        3.0,
    "S+_MAX_RFVG_WICK":     3.0,
    "S+_SCORE_RFVG_S":      3.0,
    "S+_MAX_HSV_S":         3.0,
    "S+_FVG_HSV_S":         3.0,
    # A- / OTHER (안전망)
    "A-_ROOM_ONLY":         1.0,
    "A-_OUT":               1.0,
    "OTHER":                1.0,
}

# v29.5 자산별 mult (yahoo_index_v29_5.py 와 동일)
V29_2_ASSET_MULT = {
    "ES":   1.5,
    "NQ":   1.2,
    "YM":   1.0,
    "RTY":  1.0,
    "NKD":  1.0,
    "TPX":  1.0,
    "FTSE": 1.0,
    "HSI":  1.0,
    "TWII": 1.0,
}

# 자산별 base risk_pct (둠챠 결정: 1.0% 일괄)
PHASE_A_RISK = {
    "NQ":   0.010, "ES":   0.010, "YM":   0.010, "RTY":  0.010,
    "NKD":  0.010,
    "TPX":  0.010,
    "FTSE": 0.010,
    "HSI":  0.010, "TWII": 0.010,
}

# Phase B (둠챠 수동 전환 - 자동전환 X)
# 사용 시 control_panel 에서 토글
PHASE_B_RISK = {
    "NQ":   0.005, "ES":   0.005, "YM":   0.005, "RTY":  0.005,
    "NKD":  0.005,
    "TPX":  0.005,
    "FTSE": 0.005,
    "HSI":  0.005, "TWII": 0.005,
}

# ============================================================
# v29 시나리오 B 차단 (yahoo_index_v29_5.py 동일)
# ============================================================
USE_V29_1_PATCH = True       # 시나리오 B 12종 차단
USE_V29_2_PATCH = True       # 자산별 mult
USE_V29_3_PATCH = True       # 신규 자산
USE_V29_4_PATCH = True       # 음수 RULE 3종 차단 (A+_MAX, S_SCORE_MAX_WICK, A_RP3)
USE_V29_5_PATCH = True       # FESX→TPX

# ============================================================
# Loop / Zone-Proximity (코인 v2.2 그대로)
# ============================================================
LOOP_SLEEP_SECONDS = 15
USE_ZONE_PROXIMITY_TRIGGER = True
LIGHT_LOOP_SLEEP_SECONDS = 5
ZONE_PROXIMITY_PCT = 0.5
ZONE_CACHE_REFRESH_SECONDS = 3600    # 1시간

# 청산 후 재진입 쿨다운 (시간)
EXIT_COOLDOWN_HOURS = 4              # 인덱스: 2h 봉 2개 = 4시간

# ============================================================
# v1.9b atomic 계산용 (백테 호환)
# ============================================================
WICK_RATIO_5_Q1_THRESHOLD = 0.2300
PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5
SWEEP_LOOKBACK_BARS = 5

# Tier 우선 정렬 + exclude 최근 LTF (코인 v1.9_REALISTIC 동일)
USE_TIER_PRIORITY_SORT = True
EXCLUDE_RECENT_H1_FOR_TIER = 0       # 실전: 0 (최신 정보 활용)

# ============================================================
# Runtime State / Watchdog (코인 그대로)
# ============================================================
TRADING_ENABLED_DEFAULT = True
KILL_SWITCH_DEFAULT = False
PANEL_AUTO_REFRESH_SECONDS = 5
MAIN_LOCK_FILE = "main_idx.lock"

# Exchange API retry
READ_API_MAX_RETRIES = 3
READ_API_RETRY_SLEEP_SECONDS = 0.8

# 1m wick touch (인덱스는 fractional 캔들 X — 코인 specific 이라 OFF)
USE_1M_WICK_TOUCH = False
WICK_TOUCH_LOOKBACK_BARS = 5
WICK_TOUCH_MAX_EXIT_FRAC = 0.30

# ============================================================
# Position Management Defaults (settings_store 에서 override 가능)
# ============================================================
DEFAULT_POSITION_MANAGEMENT = {
    "position_management_enabled": True,
    "move_be_at_1r": True,
    "runner_trailing_enabled": True,
    "runner_trail_start_lock_rr": 1.0,
    "runner_trail_step_rr": 1.0,
    "runner_trail_lock_increment_rr": 0.5,
    "runner_lifecycle_enabled": True,
    "runner_fast_2r_bars_max": 3,
    "runner_above_2r_bars_min": 3,
    "runner_max_rr_after_2r_min": 3.0,
    "runner_candidate_min_conds": 2,
    "runner_post_filter_enabled": True,
    "runner_post_filter_max_rr_after_2r": 1.5,
    "runner_protect_locked_r": 0.30,
    "runner_protect_only_if_be_moved": True,
    "disable_time_exit_for_runner": True,
}

# ============================================================
# Logging
# ============================================================
LOG_LEVEL = "INFO"


# ============================================================
# 자기 검증
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("KIS 인덱스 봇 Config 검증")
    print("=" * 80)
    print(f"USE_DEMO:              {USE_DEMO}")
    print(f"HTF_INTERVAL:          {HTF_INTERVAL} (2h)")
    print(f"LTF_INTERVAL:          {LTF_INTERVAL} (1h)")
    print(f"MAX_OPEN_POSITIONS:    {MAX_OPEN_POSITIONS_DEFAULT}")
    print(f"USE_ZONE_PROXIMITY:    {USE_ZONE_PROXIMITY_TRIGGER}")
    print(f"LIGHT_LOOP_SLEEP:      {LIGHT_LOOP_SLEEP_SECONDS}s")
    print(f"ZONE_PROXIMITY_PCT:    ±{ZONE_PROXIMITY_PCT}%")
    print(f"v29.5 RULE_MULT 개수:  {len(V29_1_RULE_MULT)}")
    print(f"v29.5 ASSET_MULT 개수: {len(V29_2_ASSET_MULT)}")
    print(f"PHASE_A_RISK 개수:     {len(PHASE_A_RISK)}")
    print()
    print(f"강력 RULE (mult > 3):")
    for r, m in sorted(V29_1_RULE_MULT.items(), key=lambda x: -x[1])[:6]:
        print(f"  {r:<25} {m}x")
    print()
    print(f"자산별 mult:")
    for a, m in V29_2_ASSET_MULT.items():
        risk = PHASE_A_RISK.get(a, 0)
        print(f"  {a:<6} mult={m}x  base_risk={risk*100}%")
