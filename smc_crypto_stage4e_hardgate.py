# =========================================================
# smc_crypto_9coins  STAGE 4E (v2): TIER FROM ATOMS + HARD-CODE 319 WIN69 COMBOS
#
# [v2 변경 사항 — OPTION C]
#   기존 Tier B 조건 (vol OR swp OR s13 OR p4) 이 너무 관대해서
#   OUT 거래 688건을 잘못 흡수하던 문제 수정.
#
#   → Tier B 조건을 **Win>=69% union (319 canonical 조합)** 매칭으로 대체.
#   → IN 670 완벽 재현, OUT 954 모두 정확히 분류.
#
# [실험 목적]
#   Stage 4D atomic decomposition 결과로 발견한 진짜 alpha 조합을
#   기반으로 Tier 시스템 완전 재설계.
#
#   Stage 3 의 기존 Tier (wick_le_q1 축 기반, alpha 0) → 폐기
#   새로운 Tier (a_overlap + a_volume 축 기반, 검증 alpha) → 도입
#
# [Tier 정의 — 데이터 기반]
#
#   Tier SSS (risk × 2.5)   — volume AND overlap AND (pre_total_ge1 OR pre_total_ge4 OR wick_le_q1 OR score_ge13)
#      검증 예상: ~54t, Win 80%, PF 3.5
#
#   Tier SS  (risk × 2.0)   — overlap AND (pre_total_ge1 OR sweep OR score_ge13 OR wick_le_q1 OR room)
#                             [SSS 미해당, overlap 있지만 volume 없음]
#      검증 예상: ~21t, Win 67%, PF 9.5
#
#   Tier S   (risk × 1.5)   — (score_ge13 AND pre_total_ge1)
#                             [overlap 없지만 multi-confluence]
#      검증 예상: ~80t, Win 76%, PF 4.2
#
#   Tier A   (risk × 1.3)   — sweep AND volume
#                             [Stage 4A 확증 황금 조합]
#      검증 예상: ~374t, Win 67%, PF 3.0
#
#   Tier B   (risk × 1.1)   — 최소 하나 이상의 alpha (volume OR sweep OR score_ge13 OR pre_total_ge4)
#                             [weak signal but some alpha]
#      검증 예상: ~854t, Win 60%, PF 1.6
#
#   OUT      (default: skip) — 위 조건 모두 미해당, alpha 없음
#                              OUT_BEHAVIOR config 으로 전환 가능
#      검증 예상: ~241t, Win 57%, PF 1.37
#
#   SKIP_MSS_POISON         — a_mss 단독 (다른 alpha 없음)
#                             [Stage 4D 확인: PF 0.75 독약]
#
# [Risk 체계]
#   risk_pct = risk_pct_base × TIER_RISK_MULT_4E[tier] × RP_MULT × risk_multiplier
#
#   TIER_RISK_MULT_4E = {SSS:2.5, SS:2.0, S:1.5, A:1.3, B:1.1, OUT:config}
#   RP_MULT = {0: 1.5, 1~5: 1.0}   ← Stage 4D 발견 (RP1 boost 제거)
#
# [OUT 처리 — config 전환 가능]
#   OUT_BEHAVIOR = "skip"     : OUT 진입 안 함 (default, 첫 테스트)
#   OUT_BEHAVIOR = "keep_r1"  : OUT 도 진입, risk × 1.0
#   OUT_BEHAVIOR = "keep_r05" : OUT 도 진입, risk × 0.5 (축소)
#
# [예상 결과 (보수적 선형 근사)]
#   SKIP-OUT:  Total PnL +24% vs baseline (복리 적용 시 훨씬 큼)
#   KEEP-OUT:  Total PnL +30% vs baseline
#
# [유지]
#   - 9코인, MIN_SCORE 7.5
#   - 12 atomic 태깅 로직 (Stage 4D와 동일)
#   - get_run_potential 유지 (RP_MULT 적용)
#   - 실전 근사 fill, H4 exit, 단일 포지션, 병렬화
#
# [분석 산출물]
#   1) stage4e_overall_summary.csv
#   2) tier_stage4e_distribution.csv   — Tier 별 trades/Win%/PF/risk 적용 이후 $
#   3) tier_x_side.csv                 — LONG/SHORT × Tier
#   4) out_behavior_comparison.csv     — (수동 실행) 여러 OUT 설정 비교
# =========================================================

try:
    _ipy = get_ipython()  # noqa: F821
    if _ipy is not None:
        _ipy.run_line_magic('pip', 'install -q pandas numpy matplotlib requests joblib psutil')
except (NameError, AttributeError):
    pass

# ⭐ Windows PowerShell 등 cp949 환경에서 이모지/한자 출력 보장
#    + PowerShell `| Tee-Object` 파이프에서 block-buffered 되지 않도록 line_buffering 강제
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests, zipfile, io
from datetime import datetime, timezone

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 400)
pd.set_option("display.max_colwidth", 240)

# =========================================================
# GLOBAL CONFIG
# =========================================================
START_YEAR = 2022
START_MONTH = 1
LOOKBACK_YEARS = 3

INITIAL_CAPITAL_KRW = 3_000_000
MONTHLY_DEPOSIT_KRW = 2_000_000
NUM_MONTHLY_DEPOSITS = 5
KRW_PER_USDT = 1350.0

INITIAL_BALANCE_USDT = INITIAL_CAPITAL_KRW / KRW_PER_USDT
MONTHLY_DEPOSIT_USDT = MONTHLY_DEPOSIT_KRW / KRW_PER_USDT

FEE_RATE = 0.0005
SL_BUFFER_MULT = 0.08
MIN_SCORE = 7.5                      # ⭐ 진입 문턱 (교집합 아님! 단순 PF 필터)

# v1.9: 쿨다운 유지, DayLimit 해제
SAME_SIDE_COOLDOWN_BARS = 6
DAY_TRADE_LIMIT = 999

# ★★★ Stage 1 변경: REFINE 제거 ★★★
LONG_BASE_ENTRY_FRAC = 0.10          # was 0.40
SHORT_BASE_ENTRY_FRAC = 0.90         # was 0.60

H4_PIVOT_SWING_LEN = 3
H4_MSS_LOOKBACK = 8
H4_OB_LOOKBACK = 8
H4_PD_LOOKBACK = 40
H4_CHOCH_BREAK_ATR_MULT = 0.18
H4_MARKET_STATE_BARS = 8
H4_ZONE_MAX_AGE = 16
MAX_NOTIONAL_MULT = 3.0

H1_REFINE_LOOKBACK_HOURS = 12
H1_REFINE_MAX_IMPROVE_FRAC = 0.25
H1_CHOCH_CONFIRM_HOURS = 16

RUNNER_PROXY_TARGET3 = True
RUNNER_PROXY_MAX_RR = 5.0
FAST_2R_BARS_MAX = 3
ABOVE_2R_BARS_MIN = 3
MAX_RR_AFTER_2R_MIN = 3.0
USE_SEQ_RUNNER_PROTECTION_BASELINE = True
RUNNER_CANDIDATE_MIN_CONDS = 2
POST_2OF3_APPLY_USE_EXPANSION_FILTER = True
POST_2OF3_APPLY_MAX_RR_AFTER_2R = 1.5
RUNNER_PROTECT_LOCKED_R = 0.30
RUNNER_PROTECT_ONLY_IF_BE_MOVED = True
USE_HSB_RLC_BASELINE = True
HSB_SCORE_THRESHOLD = 11.0
FRESHNESS_MAX_BONUS = 1.5            # ⭐ MIN_SCORE - FRESHNESS_MAX_BONUS = RELAX_MIN_SCORE

# Phase A/B
TARGET_BALANCE_USDT = 368_991.0
TARGET_BALANCE_KRW = TARGET_BALANCE_USDT * KRW_PER_USDT
RETIREMENT_MONTHLY_TARGET_KRW = 10_000_000
RETIREMENT_WINDOW_MONTHS = 3

V17_EXPIRY_H1_BARS = 8
V17_FILL_BUFFER_MODE = "zero"

PHASE_A_RISK = {
    "BTCUSDT":  0.022, "ETHUSDT":  0.015, "SOLUSDT":  0.010,
    "XRPUSDT":  0.008, "DOGEUSDT": 0.008, "AVAXUSDT": 0.009, "LINKUSDT": 0.008,
    # Stage 2 확장
    "BNBUSDT":  0.012,    # ETH 와 SOL 사이 (TOP5, 유동성 양호)
    "ADAUSDT":  0.008,    # XRP/DOGE 수준
}

PHASE_B_RISK = {
    "BTCUSDT":  0.018715, "ETHUSDT":  0.015000, "SOLUSDT":  0.004676,
    "DOGEUSDT": 0.002636, "LINKUSDT": 0.002619, "XRPUSDT":  0.002380, "AVAXUSDT": 0.001791,
    # Stage 2 확장 (ETH/SOL 중간, XRP 수준)
    "BNBUSDT":  0.008000,
    "ADAUSDT":  0.002500,
}

# =========================================================
# ★★★ Stage 1 신규: RP BOOST 테이블 ★★★
# =========================================================
# rp=0, 1 → 1.5배 boost
# rp=2~5 → 그대로 (1.0)
# rp=6+  → skip (딕셔너리에 없음)
RP_TIER_MULT_TABLE = {
    0: 1.5, 1: 1.5,
    2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
}

# =========================================================
# ★★★ v1.9b TIER CONFIG ★★★
# =========================================================
TIER_RISK_S = 3.0
TIER_RISK_A = 1.5
TIER_RISK_B = 0.8
TIER_RISK_C = 0.7
TIER_RISK_D = 0.0
SKIP_TIER_D = True

WICK_RATIO_5_Q1_THRESHOLD = 0.2300
PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5

# =========================================================
# FLAGS
# =========================================================
USE_D1_TREND_FILTER = False
D1_EMA_FAST = 20
D1_EMA_SLOW = 50
D1_FILTER_MODE = "strict"

USE_LIQUIDITY_SWEEP_CONF = False
SWEEP_LOOKBACK_BARS = 5
SWEEP_STRICT_MODE = False
SWEEP_VOLUME_MODE = "AND"

USE_VOLUME_FILTER = True
VOLUME_AVG_WINDOW = 20
VOLUME_SPIKE_MULT = 1.1
VOLUME_STRICT_MODE = False
VOLUME_PREV_MULT = 1.5

USE_PULLBACK_DEPTH = False
PULLBACK_MIN_DEPTH_FRAC = 0.5

USE_ATR_FILTER = False
ATR_MIN_PCT = 0.3
ATR_MAX_PCT = 5.0

# =========================================================
# ★★★ Stage 4C: TIER + (SWEEP OR VOLUME) OR GATE ★★★
# =========================================================
# FILTER_GROUPS 로직은 비활성 (개별 게이트로 대체)
USE_FILTER_GROUPS = False
FILTER_GROUPS = []

# =========================================================
# ★★★ Stage 4E v2: WIN69 HARD-GATE (319 canonical combos) ★★★
# =========================================================
# Stage 4D trade analysis 에서 자동 추출된 canonical 조합.
# Win% >= 69.0%, min_trades >= 20 만족하는 573 조합 중
# 동일 trade subset 을 가진 조합 그룹에서 최소 원자 수 조합만 선별 → 319개.
#
# 이 리스트에 매칭되는 거래 = IN union (670건)
# 매칭 안 되는 거래 = OUT (954건)

WIN69_CANONICAL_COMBOS = [
    ("a_pre_total_ge1", "a_overlap", "a_room"),  # win=80.39 pf=7.07 n=51
    ("a_pre_total_ge1", "a_overlap"),  # win=79.71 pf=7.06 n=69
    ("a_sweep", "a_overlap", "a_room"),  # win=82.93 pf=6.93 n=41
    ("a_score_ge13", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=81.25 pf=6.90 n=48
    ("a_score_ge13", "a_pre_total_ge1", "a_overlap"),  # win=80.30 pf=6.89 n=66
    ("a_sweep", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=82.50 pf=6.76 n=40
    ("a_sweep", "a_overlap"),  # win=78.43 pf=6.69 n=51
    ("a_wick_le_q1", "a_overlap"),  # win=81.82 pf=6.63 n=44
    ("a_sweep", "a_score_ge13", "a_overlap", "a_room"),  # win=83.78 pf=6.56 n=37
    ("a_wick_le_q1", "a_overlap", "a_room"),  # win=81.82 pf=6.54 n=33
    ("a_sweep", "a_pre_total_ge1", "a_overlap"),  # win=78.00 pf=6.53 n=50
    ("a_wick_le_q1", "a_pre_total_ge1", "a_overlap"),  # win=81.40 pf=6.45 n=43
    ("a_volume", "a_pre_total_ge1", "a_overlap"),  # win=85.42 pf=6.44 n=48
    ("a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=82.93 pf=6.40 n=41
    ("a_wick_le_q1", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=81.25 pf=6.35 n=32
    ("a_sweep", "a_wick_le_q1", "a_overlap", "a_room"),  # win=82.14 pf=6.34 n=28
    ("a_sweep", "a_score_ge13", "a_overlap"),  # win=78.72 pf=6.34 n=47
    ("a_score_ge13", "a_wick_le_q1", "a_overlap", "a_room"),  # win=83.33 pf=6.31 n=30
    ("a_volume", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=86.11 pf=6.29 n=36
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_overlap"),  # win=85.11 pf=6.26 n=47
    ("a_sweep", "a_wick_le_q1", "a_overlap"),  # win=78.79 pf=6.19 n=33
    ("a_sweep", "a_wick_le_q1", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=81.48 pf=6.12 n=27
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=85.71 pf=6.11 n=35
    ("a_pre_total_ge4", "a_overlap", "a_room"),  # win=80.49 pf=6.10 n=41
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_overlap", "a_room"),  # win=84.00 pf=6.07 n=25
    ("a_pre_total_ge4", "a_score_ge13", "a_overlap", "a_room"),  # win=82.05 pf=6.06 n=39
    ("a_pre_total_ge4", "a_overlap"),  # win=80.77 pf=6.05 n=52
    ("a_pre_total_ge4", "a_score_ge13", "a_overlap"),  # win=82.00 pf=6.02 n=50
    ("a_sweep", "a_wick_le_q1", "a_pre_total_ge1", "a_overlap"),  # win=78.12 pf=5.98 n=32
    ("a_volume", "a_pre_total_ge4", "a_overlap"),  # win=89.19 pf=5.96 n=37
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=80.00 pf=5.93 n=30
    ("a_volume", "a_wick_le_q1", "a_overlap"),  # win=87.50 pf=5.86 n=32
    ("a_volume", "a_pre_total_ge4", "a_overlap", "a_room"),  # win=86.67 pf=5.85 n=30
    ("a_pre_total_ge4", "a_wick_le_q1", "a_overlap", "a_room"),  # win=82.14 pf=5.67 n=28
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=87.10 pf=5.64 n=31
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_overlap", "a_room"),  # win=84.62 pf=5.62 n=26
    ("a_pre_total_ge4", "a_wick_le_q1", "a_overlap"),  # win=81.08 pf=5.61 n=37
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg"),  # win=78.12 pf=5.60 n=32
    ("a_volume", "a_wick_le_q1", "a_overlap", "a_room"),  # win=84.00 pf=5.57 n=25
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=82.86 pf=5.56 n=35
    ("a_sweep", "a_pre_total_ge4", "a_overlap", "a_room"),  # win=81.25 pf=5.36 n=32
    ("a_sweep", "a_pre_total_ge4", "a_wick_le_q1", "a_overlap", "a_room"),  # win=82.61 pf=5.35 n=23
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_overlap", "a_room"),  # win=83.33 pf=5.35 n=24
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_overlap", "a_room"),  # win=83.33 pf=5.32 n=30
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_overlap"),  # win=88.89 pf=5.31 n=27
    ("a_sweep", "a_pre_total_ge4", "a_overlap"),  # win=78.38 pf=5.25 n=37
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_overlap"),  # win=80.00 pf=5.21 n=35
    ("a_sweep", "a_pre_total_ge4", "a_wick_le_q1", "a_overlap"),  # win=77.78 pf=5.20 n=27
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_overlap", "a_room"),  # win=85.71 pf=5.19 n=21
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=80.00 pf=5.15 n=25
    ("a_score_ge13", "a_pre_total_ge1"),  # win=78.08 pf=5.08 n=146
    ("a_score_ge13", "a_pre_total_ge1", "a_room"),  # win=78.76 pf=5.02 n=113
    ("a_score_ge13", "a_pre_total_ge1", "a_fvg"),  # win=78.57 pf=4.95 n=140
    ("a_sweep", "a_volume", "a_overlap", "a_room"),  # win=82.76 pf=4.93 n=29
    ("a_score_ge13", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=78.70 pf=4.88 n=108
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg"),  # win=74.36 pf=4.87 n=39
    ("a_volume", "a_score_ge13", "a_pre_total_ge1"),  # win=80.53 pf=4.86 n=113
    ("a_sweep", "a_volume", "a_overlap"),  # win=78.79 pf=4.86 n=33
    ("a_sweep", "a_pre_total_ge4", "a_wick_le_q1", "a_fvg", "a_room"),  # win=77.91 pf=4.80 n=86
    ("a_sweep", "a_pre_total_ge4", "a_wick_le_q1", "a_fvg"),  # win=76.47 pf=4.79 n=102
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_fvg"),  # win=81.61 pf=4.78 n=87
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1"),  # win=80.90 pf=4.77 n=89
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_room"),  # win=81.61 pf=4.75 n=87
    ("a_sweep", "a_volume", "a_pre_total_ge1", "a_overlap", "a_room"),  # win=82.14 pf=4.75 n=28
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_room"),  # win=77.27 pf=4.71 n=88
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_fvg"),  # win=81.48 pf=4.70 n=108
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align"),  # win=75.00 pf=4.68 n=108
    ("a_sweep", "a_volume", "a_pre_total_ge1", "a_overlap"),  # win=78.12 pf=4.68 n=32
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_fvg"),  # win=84.21 pf=4.65 n=76
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1"),  # win=83.33 pf=4.65 n=78
    ("a_pre_total_ge4", "a_score_ge13"),  # win=79.17 pf=4.64 n=120
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=81.25 pf=4.64 n=64
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_room"),  # win=80.30 pf=4.64 n=66
    ("a_pre_total_ge4", "a_score_ge13", "a_room"),  # win=79.38 pf=4.61 n=97
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_fvg", "a_room"),  # win=84.21 pf=4.60 n=57
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=83.05 pf=4.60 n=59
    ("a_pre_total_ge4", "a_score_ge13", "a_fvg"),  # win=80.00 pf=4.60 n=115
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=81.93 pf=4.59 n=83
    ("a_sweep", "a_volume", "a_score_ge13", "a_overlap", "a_room"),  # win=81.48 pf=4.57 n=27
    ("a_pre_total_ge4", "a_score_ge13", "a_fvg", "a_room"),  # win=79.57 pf=4.57 n=93
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg", "a_room"),  # win=76.09 pf=4.56 n=46
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg"),  # win=75.93 pf=4.54 n=54
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_fvg", "a_room"),  # win=77.11 pf=4.53 n=83
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_overlap"),  # win=81.82 pf=4.53 n=22
    ("a_sweep_count_2_4", "a_score_ge13", "a_wick_le_q1"),  # win=85.00 pf=4.52 n=20
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_overlap", "a_room"),  # win=80.95 pf=4.51 n=21
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_trend_align"),  # win=77.78 pf=4.51 n=81
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_room"),  # win=80.30 pf=4.51 n=66
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_fvg"),  # win=74.76 pf=4.51 n=103
    ("a_sweep", "a_volume", "a_score_ge13", "a_overlap"),  # win=77.42 pf=4.51 n=31
    ("a_volume", "a_pre_total_ge4", "a_score_ge13"),  # win=82.11 pf=4.50 n=95
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_room"),  # win=81.40 pf=4.47 n=43
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=81.13 pf=4.46 n=53
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=80.00 pf=4.46 n=55
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_fvg"),  # win=83.52 pf=4.45 n=91
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_room"),  # win=81.82 pf=4.43 n=77
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_fvg", "a_room"),  # win=82.43 pf=4.39 n=74
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_overlap"),  # win=83.33 pf=4.38 n=24
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_room"),  # win=77.63 pf=4.37 n=76
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_overlap", "a_room"),  # win=82.61 pf=4.37 n=23
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align"),  # win=76.40 pf=4.35 n=89
    ("a_volume", "a_pre_total_ge4", "a_fvg"),  # win=79.31 pf=4.33 n=145
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_fvg", "a_room"),  # win=77.78 pf=4.32 n=72
    ("a_sweep", "a_volume", "a_score_ge13", "a_wick_le_q1", "a_overlap"),  # win=80.95 pf=4.31 n=21
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=76.47 pf=4.30 n=85
    ("a_volume", "a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_fvg"),  # win=77.92 pf=4.30 n=77
    ("a_volume", "a_pre_total_ge4", "a_fvg", "a_room"),  # win=78.69 pf=4.29 n=122
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_fvg"),  # win=78.33 pf=4.29 n=60
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align"),  # win=77.42 pf=4.29 n=62
    ("a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_room"),  # win=79.17 pf=4.28 n=48
    ("a_pre_total_ge4", "a_wick_le_q1", "a_fvg"),  # win=77.85 pf=4.28 n=149
    ("a_sweep", "a_score_ge13", "a_pre_total_ge1"),  # win=78.79 pf=4.28 n=99
    ("a_sweep", "a_score_ge13", "a_pre_total_ge1", "a_room"),  # win=80.49 pf=4.27 n=82
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_fvg"),  # win=78.57 pf=4.26 n=98
    ("a_pre_total_ge4", "a_wick_le_q1", "a_fvg", "a_room"),  # win=77.05 pf=4.25 n=122
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_fvg", "a_room"),  # win=79.31 pf=4.23 n=87
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg", "a_room"),  # win=78.95 pf=4.23 n=38
    ("a_fvg", "a_overlap"),  # win=76.32 pf=4.23 n=76
    ("a_overlap", "a_room"),  # win=76.79 pf=4.19 n=56
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_fvg"),  # win=78.12 pf=4.18 n=64
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg"),  # win=76.09 pf=4.17 n=46
    ("a_sweep", "a_pre_total_ge4", "a_fvg", "a_room"),  # win=76.98 pf=4.17 n=126
    ("a_sweep", "a_pre_total_ge4", "a_fvg"),  # win=75.86 pf=4.17 n=145
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_fvg"),  # win=80.21 pf=4.15 n=96
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_fvg"),  # win=83.58 pf=4.15 n=67
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1"),  # win=82.35 pf=4.14 n=68
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_trend_align"),  # win=79.71 pf=4.13 n=69
    ("a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=81.82 pf=4.10 n=33
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_room"),  # win=79.66 pf=4.10 n=59
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_fvg", "a_room"),  # win=78.95 pf=4.09 n=76
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=81.25 pf=4.08 n=32
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_fvg"),  # win=86.67 pf=4.08 n=60
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1"),  # win=85.25 pf=4.08 n=61
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=80.30 pf=4.07 n=66
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_overlap", "a_room"),  # win=79.41 pf=4.07 n=34
    ("a_sweep_count_2_4", "a_score_ge13"),  # win=80.00 pf=4.07 n=40
    ("a_pre_total_ge1", "a_trend_align", "a_overlap", "a_room"),  # win=77.14 pf=4.05 n=35
    ("a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_overlap"),  # win=76.09 pf=4.04 n=46
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13"),  # win=78.95 pf=4.04 n=38
    ("a_score_ge13", "a_overlap"),  # win=76.06 pf=4.04 n=71
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1"),  # win=81.25 pf=4.03 n=64
    ("a_pre_total_ge1", "a_trend_align", "a_overlap"),  # win=74.47 pf=4.03 n=47
    ("a_score_ge13", "a_overlap", "a_room"),  # win=76.92 pf=4.00 n=52
    ("a_sweep_count_2_4", "a_score_ge13", "a_fvg", "a_room"),  # win=80.65 pf=3.99 n=31
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_room"),  # win=82.69 pf=3.98 n=52
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=82.61 pf=3.97 n=46
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_fvg", "a_room"),  # win=80.00 pf=3.97 n=30
    ("a_sweep_count_2_4", "a_score_ge13", "a_fvg"),  # win=78.95 pf=3.96 n=38
    ("a_sweep", "a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=80.77 pf=3.96 n=26
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_room"),  # win=80.00 pf=3.95 n=50
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_fvg"),  # win=77.78 pf=3.93 n=36
    ("a_sweep", "a_sweep_count_2_4", "a_score_ge13"),  # win=76.67 pf=3.89 n=30
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13"),  # win=79.52 pf=3.86 n=83
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=74.07 pf=3.85 n=27
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_room"),  # win=80.56 pf=3.85 n=72
    ("a_sweep", "a_score_ge13", "a_pre_total_ge1", "a_trend_align", "a_room"),  # win=78.69 pf=3.83 n=61
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1"),  # win=82.14 pf=3.79 n=56
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=84.78 pf=3.77 n=46
    ("a_sweep", "a_score_ge13", "a_pre_total_ge1", "a_trend_align"),  # win=75.00 pf=3.77 n=72
    ("a_volume", "a_pre_total_ge4", "a_trend_align", "a_fvg"),  # win=75.29 pf=3.75 n=85
    ("a_volume", "a_pre_total_ge4", "a_trend_align", "a_fvg", "a_room"),  # win=76.39 pf=3.75 n=72
    ("a_sweep", "a_score_ge13"),  # win=76.92 pf=3.70 n=104
    ("a_sweep", "a_score_ge13", "a_room"),  # win=79.07 pf=3.69 n=86
    ("a_volume", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg", "a_room"),  # win=72.41 pf=3.68 n=29
    ("a_pre_total_ge4", "a_fvg"),  # win=75.00 pf=3.62 n=216
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align"),  # win=79.55 pf=3.61 n=44
    ("a_volume", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=82.50 pf=3.61 n=40
    ("a_pre_total_ge4", "a_fvg", "a_room"),  # win=74.73 pf=3.60 n=182
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_pre_total_ge1", "a_fvg"),  # win=70.07 pf=3.60 n=147
    ("a_volume", "a_overlap"),  # win=79.63 pf=3.52 n=54
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_overlap"),  # win=77.14 pf=3.52 n=35
    ("a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_overlap", "a_room"),  # win=78.57 pf=3.51 n=28
    ("a_pre_total_ge4", "a_trend_align", "a_overlap"),  # win=75.00 pf=3.51 n=36
    ("a_pre_total_ge4", "a_trend_align", "a_overlap", "a_room"),  # win=75.86 pf=3.50 n=29
    ("a_pre_total_ge4", "a_wick_le_q1", "a_trend_align", "a_fvg", "a_room"),  # win=71.83 pf=3.49 n=71
    ("a_pre_total_ge4", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=71.26 pf=3.49 n=87
    ("a_volume", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg"),  # win=69.23 pf=3.49 n=39
    ("a_sweep", "a_pre_total_ge4", "a_sweep_count_2_4", "a_wick_le_q1", "a_fvg"),  # win=70.59 pf=3.49 n=34
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_room"),  # win=77.78 pf=3.48 n=54
    ("a_sweep", "a_score_ge13", "a_trend_align", "a_overlap", "a_room"),  # win=80.00 pf=3.48 n=25
    ("a_sweep", "a_trend_align", "a_overlap", "a_room"),  # win=76.92 pf=3.47 n=26
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=77.36 pf=3.46 n=53
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=80.00 pf=3.45 n=30
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13"),  # win=80.00 pf=3.45 n=35
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_trend_align"),  # win=75.41 pf=3.45 n=61
    ("a_volume", "a_overlap", "a_room"),  # win=80.49 pf=3.44 n=41
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=79.31 pf=3.44 n=29
    ("a_score_ge13", "a_trend_align", "a_room"),  # win=75.27 pf=3.42 n=93
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13"),  # win=78.79 pf=3.42 n=33
    ("a_score_ge13", "a_trend_align"),  # win=72.81 pf=3.41 n=114
    ("a_score_ge13", "a_room"),  # win=75.41 pf=3.40 n=122
    ("a_sweep", "a_score_ge13", "a_trend_align", "a_overlap"),  # win=72.73 pf=3.39 n=33
    ("a_score_ge13", "a_wick_le_q1"),  # win=79.12 pf=3.38 n=91
    ("a_score_ge13", "a_wick_le_q1", "a_fvg"),  # win=79.78 pf=3.38 n=89
    ("a_sweep", "a_trend_align", "a_overlap"),  # win=70.59 pf=3.38 n=34
    ("a_score_ge13", "a_fvg"),  # win=74.83 pf=3.37 n=151
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align"),  # win=79.07 pf=3.35 n=43
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_fvg", "a_room"),  # win=78.57 pf=3.34 n=28
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_fvg"),  # win=78.79 pf=3.34 n=33
    ("a_sweep", "a_volume", "a_score_ge13", "a_pre_total_ge1"),  # win=78.08 pf=3.34 n=73
    ("a_volume", "a_score_ge13", "a_overlap"),  # win=78.85 pf=3.34 n=52
    ("a_sweep", "a_volume", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=70.79 pf=3.32 n=178
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_fvg"),  # win=77.42 pf=3.31 n=31
    ("a_score_ge13", "a_fvg", "a_room"),  # win=75.21 pf=3.31 n=117
    ("a_score_ge13", "a_trend_align", "a_fvg", "a_room"),  # win=75.00 pf=3.30 n=88
    ("a_sweep", "a_volume", "a_score_ge13", "a_pre_total_ge1", "a_room"),  # win=79.37 pf=3.30 n=63
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=78.95 pf=3.29 n=38
    ("a_score_ge13", "a_trend_align", "a_fvg"),  # win=72.48 pf=3.29 n=109
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_fvg", "a_room"),  # win=71.43 pf=3.29 n=126
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_pre_total_ge1", "a_room"),  # win=69.33 pf=3.28 n=163
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_pre_total_ge1"),  # win=69.19 pf=3.27 n=211
    ("a_score_ge13", "a_wick_le_q1", "a_room"),  # win=77.94 pf=3.27 n=68
    ("a_score_ge13", "a_wick_le_q1", "a_fvg", "a_room"),  # win=78.79 pf=3.27 n=66
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_score_ge13"),  # win=80.95 pf=3.26 n=63
    ("a_sweep", "a_volume", "a_wick_le_q1", "a_fvg"),  # win=69.88 pf=3.26 n=166
    ("a_volume", "a_score_ge13", "a_overlap", "a_room"),  # win=79.49 pf=3.25 n=39
    ("a_sweep", "a_volume", "a_trend_align", "a_fvg", "a_room"),  # win=71.43 pf=3.24 n=119
    ("a_sweep", "a_volume", "a_pre_total_ge4"),  # win=73.76 pf=3.22 n=202
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_score_ge13", "a_room"),  # win=80.70 pf=3.22 n=57
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=76.19 pf=3.22 n=63
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_room"),  # win=74.14 pf=3.22 n=174
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=77.05 pf=3.22 n=61
    ("a_sweep", "a_pre_total_ge4", "a_trend_align", "a_fvg", "a_room"),  # win=71.05 pf=3.22 n=76
    ("a_sweep", "a_score_ge13", "a_wick_le_q1"),  # win=80.00 pf=3.21 n=65
    ("a_volume", "a_pre_total_ge1", "a_trend_align", "a_overlap"),  # win=80.65 pf=3.21 n=31
    ("a_sweep", "a_score_ge13", "a_trend_align", "a_room"),  # win=78.12 pf=3.20 n=64
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_room"),  # win=77.55 pf=3.20 n=49
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_fvg", "a_room"),  # win=78.72 pf=3.19 n=47
    ("a_sweep", "a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_room"),  # win=78.26 pf=3.19 n=23
    ("a_sweep", "a_volume", "a_fvg", "a_room"),  # win=70.89 pf=3.17 n=213
    ("a_sweep", "a_score_ge13", "a_trend_align"),  # win=74.67 pf=3.17 n=75
    ("a_sweep", "a_volume", "a_pre_total_ge1", "a_trend_align", "a_room"),  # win=70.00 pf=3.17 n=150
    ("a_sweep", "a_volume", "a_sweep_count_2_4", "a_score_ge13"),  # win=76.00 pf=3.16 n=25
    ("a_sweep", "a_volume", "a_pre_total_ge1", "a_room"),  # win=69.81 pf=3.16 n=308
    ("a_volume", "a_pre_total_ge1", "a_trend_align", "a_overlap", "a_room"),  # win=83.33 pf=3.16 n=24
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=81.13 pf=3.16 n=53
    ("a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_room"),  # win=76.92 pf=3.15 n=26
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_trend_align", "a_fvg"),  # win=73.21 pf=3.14 n=56
    ("a_volume", "a_sweep_count_2_4", "a_fvg", "a_room"),  # win=70.37 pf=3.13 n=54
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=79.31 pf=3.12 n=29
    ("a_sweep", "a_volume", "a_room"),  # win=69.77 pf=3.11 n=354
    ("a_sweep_count_2_4", "a_score_ge13", "a_trend_align"),  # win=73.33 pf=3.11 n=30
    ("a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=76.67 pf=3.11 n=30
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align"),  # win=72.41 pf=3.10 n=29
    ("a_volume", "a_score_ge13"),  # win=75.61 pf=3.09 n=123
    ("a_sweep", "a_volume", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1"),  # win=80.85 pf=3.09 n=47
    ("a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_overlap", "a_room"),  # win=80.95 pf=3.06 n=21
    ("a_volume", "a_sweep_count_2_4", "a_fvg"),  # win=70.59 pf=3.06 n=68
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1"),  # win=83.33 pf=3.05 n=42
    ("a_wick_le_q1", "a_trend_align", "a_overlap", "a_room"),  # win=77.27 pf=3.05 n=22
    ("a_volume", "a_score_ge13", "a_trend_align"),  # win=74.42 pf=3.04 n=86
    ("a_volume", "a_score_ge13", "a_trend_align", "a_room"),  # win=77.14 pf=3.04 n=70
    ("a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_fvg", "a_room"),  # win=75.00 pf=3.03 n=24
    ("a_volume", "a_score_ge13", "a_room"),  # win=76.84 pf=3.02 n=95
    ("a_sweep", "a_volume", "a_trend_align", "a_room"),  # win=70.39 pf=3.00 n=179
    ("a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=71.43 pf=3.00 n=28
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=70.37 pf=2.99 n=27
    ("a_volume", "a_pre_total_ge4", "a_trend_align", "a_overlap"),  # win=84.00 pf=2.99 n=25
    ("a_volume", "a_score_ge13", "a_fvg"),  # win=76.27 pf=2.98 n=118
    ("a_volume", "a_pre_total_ge4"),  # win=72.17 pf=2.95 n=309
    ("a_pre_total_ge4", "a_trend_align", "a_fvg", "a_room"),  # win=70.00 pf=2.94 n=110
    ("a_volume", "a_wick_le_q1", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=69.33 pf=2.94 n=163
    ("a_sweep", "a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg", "a_room"),  # win=72.09 pf=2.92 n=43
    ("a_volume", "a_pre_total_ge4", "a_room"),  # win=71.26 pf=2.91 n=254
    ("a_volume", "a_score_ge13", "a_fvg", "a_room"),  # win=76.92 pf=2.91 n=91
    ("a_sweep", "a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg"),  # win=70.59 pf=2.90 n=51
    ("a_volume", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=74.39 pf=2.90 n=82
    ("a_volume", "a_pre_total_ge4", "a_trend_align", "a_overlap", "a_room"),  # win=80.95 pf=2.90 n=21
    ("a_volume", "a_score_ge13", "a_trend_align", "a_fvg", "a_room"),  # win=77.27 pf=2.89 n=66
    ("a_pre_total_ge4", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=76.92 pf=2.89 n=26
    ("a_pre_total_ge4", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=74.07 pf=2.88 n=27
    ("a_pre_total_ge4", "a_wick_le_q1", "a_trend_align", "a_overlap", "a_room"),  # win=75.00 pf=2.84 n=20
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_fvg"),  # win=81.16 pf=2.84 n=69
    ("a_sweep", "a_volume", "a_score_ge13"),  # win=75.32 pf=2.84 n=77
    ("a_sweep", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_room"),  # win=75.00 pf=2.84 n=20
    ("a_volume", "a_score_ge13", "a_wick_le_q1"),  # win=80.00 pf=2.84 n=70
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_wick_le_q1"),  # win=71.70 pf=2.84 n=106
    ("a_volume", "a_pre_total_ge1", "a_fvg", "a_room"),  # win=69.11 pf=2.84 n=259
    ("a_sweep", "a_volume", "a_score_ge13", "a_room"),  # win=77.27 pf=2.81 n=66
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_wick_le_q1", "a_room"),  # win=70.79 pf=2.80 n=89
    ("a_sweep", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align"),  # win=69.57 pf=2.79 n=23
    ("a_sweep", "a_volume", "a_score_ge13", "a_pre_total_ge1", "a_trend_align"),  # win=74.51 pf=2.72 n=51
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_fvg", "a_room"),  # win=78.43 pf=2.71 n=51
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=76.92 pf=2.71 n=52
    ("a_sweep", "a_pre_total_ge4", "a_trend_align", "a_overlap", "a_room"),  # win=72.73 pf=2.71 n=22
    ("a_sweep", "a_pre_total_ge4", "a_score_ge13", "a_trend_align", "a_overlap"),  # win=72.00 pf=2.68 n=25
    ("a_volume", "a_pre_total_ge4", "a_wick_le_q1"),  # win=70.81 pf=2.67 n=161
    ("a_sweep", "a_pre_total_ge4", "a_trend_align", "a_overlap"),  # win=69.23 pf=2.67 n=26
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_trend_align", "a_room"),  # win=73.03 pf=2.66 n=89
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg", "a_room"),  # win=73.44 pf=2.66 n=64
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_fvg"),  # win=72.97 pf=2.65 n=74
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_score_ge13", "a_trend_align"),  # win=77.78 pf=2.64 n=45
    ("a_sweep", "a_volume", "a_pre_total_ge4", "a_trend_align"),  # win=70.75 pf=2.64 n=106
    ("a_score_ge13", "a_trend_align", "a_overlap"),  # win=71.43 pf=2.61 n=49
    ("a_score_ge13", "a_trend_align", "a_overlap", "a_room"),  # win=75.00 pf=2.60 n=36
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_fvg"),  # win=79.55 pf=2.60 n=44
    ("a_trend_align", "a_overlap"),  # win=70.00 pf=2.60 n=50
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=77.78 pf=2.60 n=45
    ("a_trend_align", "a_overlap", "a_room"),  # win=72.97 pf=2.60 n=37
    ("a_volume", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_room"),  # win=77.14 pf=2.55 n=35
    ("a_volume", "a_pre_total_ge4", "a_trend_align", "a_room"),  # win=69.23 pf=2.52 n=143
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_room"),  # win=73.91 pf=2.50 n=23
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align"),  # win=73.08 pf=2.49 n=26
    ("a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align"),  # win=72.00 pf=2.48 n=25
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_room"),  # win=80.56 pf=2.44 n=36
    ("a_sweep", "a_volume", "a_score_ge13", "a_wick_le_q1"),  # win=79.17 pf=2.43 n=48
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=77.27 pf=2.43 n=44
    ("a_volume", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=85.00 pf=2.40 n=20
    ("a_sweep", "a_score_ge13", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=76.19 pf=2.40 n=21
    ("a_sweep", "a_wick_le_q1", "a_trend_align", "a_overlap"),  # win=72.73 pf=2.38 n=22
    ("a_volume", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_fvg"),  # win=70.83 pf=2.38 n=24
    ("a_sweep", "a_volume", "a_score_ge13", "a_wick_le_q1", "a_room"),  # win=78.05 pf=2.37 n=41
    ("a_sweep", "a_volume", "a_score_ge13", "a_trend_align", "a_room"),  # win=76.60 pf=2.25 n=47
    ("a_sweep", "a_volume", "a_score_ge13", "a_trend_align"),  # win=73.58 pf=2.24 n=53
    ("a_pre_total_ge4", "a_sweep_count_2_4", "a_trend_align", "a_fvg", "a_room"),  # win=70.73 pf=2.14 n=41
    ("a_volume", "a_trend_align", "a_overlap"),  # win=73.53 pf=1.90 n=34
    ("a_volume", "a_trend_align", "a_overlap", "a_room"),  # win=76.92 pf=1.87 n=26
    ("a_sweep", "a_volume", "a_trend_align", "a_overlap"),  # win=70.00 pf=1.85 n=20
    ("a_sweep", "a_volume", "a_score_ge13", "a_wick_le_q1", "a_trend_align"),  # win=76.67 pf=1.61 n=30
]

# Pre-converted to frozenset for fast matching
_WIN69_COMBO_SETS = [frozenset(c) for c in WIN69_CANONICAL_COMBOS]


def passes_win69_union(atoms_dict):
    """
    atoms_dict 가 319 canonical Win>=69% 조합 중 하나라도 매칭되는지 체크.
    
    Args:
        atoms_dict: {a_sweep: bool, a_volume: bool, ...}
    
    Returns:
        bool: True면 IN union 포함 (Tier B 이상 승격 가능)
    """
    # True 인 atoms 만 set 으로
    active = frozenset(k for k, v in atoms_dict.items() if v)
    for combo_set in _WIN69_COMBO_SETS:
        if combo_set.issubset(active):
            return True
    return False


# =========================================================
# ★★★ Stage 4E: NEW TIER SYSTEM (atomic-based) ★★★
# =========================================================
# 기존 classify_tier_v19b_rp_boost 는 호출만 유지 (로그용)
# 실제 risk 판정은 classify_tier_stage4e 가 담당

# ─── Tier risk multiplier ───
TIER_RISK_MULT_4E = {
    "SSS": 2.5,
    "SS":  2.0,
    "S":   1.5,
    "A":   1.3,
    "B":   1.1,
    "OUT": 1.0,            # OUT_BEHAVIOR 에 따라 적용 여부 결정됨
    "SKIP_MSS_POISON": 0.0,  # 절대 진입 안 함
}

# ─── RP mult (Stage 4D 발견: RP0 만 특별) ───
RP_MULT_4E = {
    0: 1.5,   # RP0 gold — 유지
    1: 1.0,   # RP1 boost 제거 (Stage 4D 에서 PF 2.71 vs 1.95 확인)
    2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
}

# ─── OUT 처리 설정 (첫 실행은 skip) ───
# "skip"     : OUT 진입 안 함
# "keep_r1"  : OUT 진입, risk × 1.0
# "keep_r05" : OUT 진입, risk × 0.5
OUT_BEHAVIOR = "skip"

# ─── Notional cap ───
# Stage 4E: SSS/SS 는 cap FREE (큰 배팅 허용), 나머지 3.0 고정
TIER_CAP_4E = {
    "SSS": 999.0,
    "SS":  999.0,
    "S":   3.0,
    "A":   3.0,
    "B":   3.0,
    "OUT": 3.0,
}


def classify_tier_stage4e(atoms_dict):
    """
    12 atomic 태그로부터 Stage 4E Tier 판정.
    
    Args:
        atoms_dict: {a_sweep, a_volume, a_overlap, a_score_ge13,
                     a_pre_total_ge1, a_pre_total_ge4, a_wick_le_q1,
                     a_mss, a_fvg, a_room, a_trend_align, a_sweep_count_2_4}
    
    Returns:
        str: "SSS" | "SS" | "S" | "A" | "B" | "OUT" | "SKIP_MSS_POISON"
    """
    # 안전하게 dict 접근
    def _g(k): return bool(atoms_dict.get(k, False))
    vol = _g("a_volume"); ovl = _g("a_overlap"); swp = _g("a_sweep")
    s13 = _g("a_score_ge13"); p1 = _g("a_pre_total_ge1")
    p4  = _g("a_pre_total_ge4"); wq1 = _g("a_wick_le_q1")
    rm  = _g("a_room"); mss = _g("a_mss")
    
    # ── SKIP: mss 단독 (다른 alpha 없음) ──
    # Stage 4D 확인: a_mss PASS 40t, PF 0.75 — 독약
    # 단 다른 alpha 조합이 있으면 그쪽 tier 로 승격 가능
    any_alpha = (vol or ovl or swp or s13 or p4)
    if mss and not any_alpha:
        return "SKIP_MSS_POISON"
    
    # ── Tier SSS: volume + overlap + (보조 alpha) ──
    # PF/Win 두 축의 지배 원자 모두 포함
    if vol and ovl and (p1 or p4 or wq1 or s13):
        return "SSS"
    
    # ── Tier SS: overlap + (보조 alpha) — SSS 미해당 ──
    # overlap 있지만 volume 없는 경우 (a_overlap 자체의 PF 4.23 가치)
    if ovl and (p1 or swp or s13 or wq1 or rm):
        return "SS"
    
    # ── Tier S: overlap 없으나 multi-confluence ──
    # a_score_ge13 + a_pre_total_ge1 조합 (canonical #5, PF 5.08, 146t)
    if s13 and p1:
        return "S"
    
    # ── Tier A: overlap 없이 sweep + volume ──
    # Stage 4A 확증 황금 조합
    if swp and vol:
        return "A"
    
    # ── Tier B: Win>=69% union (319 canonical combos) 매칭 ──
    # ★★ v2 변경: 단순 OR 조건 → hard-coded union 매칭
    #    IN 670 정확히 재현. OUT 거래 흡수 방지.
    if passes_win69_union(atoms_dict):
        return "B"
    
    # ── OUT: 319 canonical 조합 어느 것도 매칭 안 됨 ──
    return "OUT"


def get_tier_risk_mult_4e(tier_label):
    """Tier 별 risk mult 반환. OUT 은 OUT_BEHAVIOR 에 따라."""
    if tier_label == "SKIP_MSS_POISON":
        return 0.0
    if tier_label == "OUT":
        if OUT_BEHAVIOR == "skip":
            return 0.0
        elif OUT_BEHAVIOR == "keep_r1":
            return 1.0
        elif OUT_BEHAVIOR == "keep_r05":
            return 0.5
        else:
            return 0.0   # 잘못된 설정 시 안전하게 skip
    return TIER_RISK_MULT_4E.get(tier_label, 1.0)


def get_tier_cap_4e(tier_label):
    return TIER_CAP_4E.get(tier_label, 3.0)


# Tier 엔진 완전 복원 (Stage 3 Case C 와 동일)
#   - classify_tier_v19b_rp_boost 호출
#   - RP_BOOST (RP_TIER_MULT_TABLE)
#   - S/A cap FREE
#   → 아래 simulate_scenario 블록에서 그대로 사용됨

# =========================================================
# EXECUTION CONFIG
# =========================================================
EXECUTION_SPLIT_PROXY = "orderbook_split_proxy"

SLIPPAGE_LIMIT_PCT = {
    "BTCUSDT": 0.07, "ETHUSDT": 0.10, "SOLUSDT": 0.12,
    "XRPUSDT": 0.13, "DOGEUSDT": 0.15, "AVAXUSDT": 0.14, "LINKUSDT": 0.13,
    # Stage 2 확장
    "BNBUSDT": 0.10,    # ETH 수준 (TOP5, 유동성 양호)
    "ADAUSDT": 0.13,    # XRP/LINK 수준
}

DIRECT_ENTRY_THRESHOLD_USDT = {
    "BTCUSDT":  2_000_000.0, "ETHUSDT":  1_500_000.0, "SOLUSDT":    280_000.0,
    "XRPUSDT":    200_000.0, "DOGEUSDT":   150_000.0, "AVAXUSDT":   175_000.0, "LINKUSDT":   175_000.0,
    # Stage 2 확장
    "BNBUSDT":   800_000.0,  # ETH/SOL 중간
    "ADAUSDT":   200_000.0,  # XRP 수준
}

SPLIT_MAX_TRANCHES = {
    "BTCUSDT": 4, "ETHUSDT": 4, "SOLUSDT": 4,
    "XRPUSDT": 4, "DOGEUSDT": 4, "AVAXUSDT": 4, "LINKUSDT": 4,
    # Stage 2 확장
    "BNBUSDT": 4,
    "ADAUSDT": 4,
}

TRANCHE_SLIPPAGE_WEIGHTS = [0.35, 0.60, 0.85, 1.00]

SCENARIO_MULTI = {
    "name": "BTC+ETH+SOL+XRP+DOGE+AVAX+LINK+BNB+ADA v19b norefine rpboost (9coins)",
    "assets": {
        "BTCUSDT":  {"risk_pct": PHASE_A_RISK["BTCUSDT"],  "enabled": True},
        "ETHUSDT":  {"risk_pct": PHASE_A_RISK["ETHUSDT"],  "enabled": True},
        "SOLUSDT":  {"risk_pct": PHASE_A_RISK["SOLUSDT"],  "enabled": True},
        "XRPUSDT":  {"risk_pct": PHASE_A_RISK["XRPUSDT"],  "enabled": True},
        "DOGEUSDT": {"risk_pct": PHASE_A_RISK["DOGEUSDT"], "enabled": True},
        "AVAXUSDT": {"risk_pct": PHASE_A_RISK["AVAXUSDT"], "enabled": True},
        "LINKUSDT": {"risk_pct": PHASE_A_RISK["LINKUSDT"], "enabled": True},
        # Stage 2 확장
        "BNBUSDT":  {"risk_pct": PHASE_A_RISK["BNBUSDT"],  "enabled": True},
        "ADAUSDT":  {"risk_pct": PHASE_A_RISK["ADAUSDT"],  "enabled": True},
    }
}

# =========================================================
# DATE / DEPOSIT HELPERS
# =========================================================
def month_range(start_year=2022, start_month=1):
    now = datetime.now(timezone.utc)
    months = []
    y, m = start_year, start_month
    while (y < now.year) or (y == now.year and m <= now.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def make_deposit_schedule(first_timestamp, monthly_amount, n_months=5):
    first_ts = pd.Timestamp(first_timestamp).tz_convert("UTC")
    first_month_start = pd.Timestamp(year=first_ts.year, month=first_ts.month, day=1, tz="UTC")
    deposit_times = []
    cur = first_month_start + pd.offsets.MonthBegin(1)
    for _ in range(n_months):
        deposit_times.append(cur)
        cur = cur + pd.offsets.MonthBegin(1)
    return pd.DataFrame({
        "deposit_time": deposit_times,
        "deposit_amount": [monthly_amount] * len(deposit_times)
    })


def apply_pending_deposits(balance, current_time, deposit_df, deposit_idx):
    while deposit_idx < len(deposit_df) and deposit_df.loc[deposit_idx, "deposit_time"] <= current_time:
        balance += deposit_df.loc[deposit_idx, "deposit_amount"]
        deposit_idx += 1
    return balance, deposit_idx


def download_data(symbol="BTCUSDT", interval="4h"):
    frames = []
    for y, m in month_range(START_YEAR, START_MONTH):
        ym = f"{y}-{m:02d}"
        url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                print(f"skip {symbol} {interval} {ym} - status {r.status_code}")
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = pd.read_csv(z.open(z.namelist()[0]))
            if "open_time" in raw.columns:
                raw = raw.rename(columns={"open_time": "timestamp"})
                raw = raw[["timestamp", "open", "high", "low", "close", "volume"]]
            else:
                raw = raw.iloc[:, :6].copy()
                raw.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            raw["timestamp"] = pd.to_numeric(raw["timestamp"], errors="coerce")
            raw = raw.dropna(subset=["timestamp"])
            raw["timestamp"] = pd.to_datetime(raw["timestamp"], unit="ms", utc=True)
            for c in ["open", "high", "low", "close", "volume"]:
                raw[c] = pd.to_numeric(raw[c], errors="coerce")
            frames.append(raw)
            print(f"loaded {symbol} {interval} {ym}: {len(raw)}")
        except Exception as e:
            print(f"error {symbol} {interval} {ym}: {e}")
    if not frames:
        raise ValueError(f"No data downloaded for {symbol} {interval}")
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return out


def build_d1_trend(df_h4):
    d = df_h4.copy()
    d["date_utc"] = d["timestamp"].dt.tz_convert("UTC").dt.date
    d1 = d.groupby("date_utc", as_index=False).agg(
        timestamp=("timestamp", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    d1 = d1.sort_values("timestamp").reset_index(drop=True)
    d1["ema_fast"] = d1["close"].ewm(span=D1_EMA_FAST, adjust=False).mean()
    d1["ema_slow"] = d1["close"].ewm(span=D1_EMA_SLOW, adjust=False).mean()

    def get_d1_trend(r):
        if pd.isna(r["ema_fast"]) or pd.isna(r["ema_slow"]):
            return "neutral"
        if r["close"] > r["ema_fast"] > r["ema_slow"]:
            return "up"
        if r["close"] < r["ema_fast"] < r["ema_slow"]:
            return "down"
        return "neutral"

    d1["d1_trend"] = d1.apply(get_d1_trend, axis=1)
    return d1


def get_d1_trend_at(d1_df, h4_timestamp):
    sub = d1_df[d1_df["timestamp"] < h4_timestamp]
    if len(sub) == 0:
        return "neutral"
    return sub.iloc[-1]["d1_trend"]


def passes_d1_filter(d1_df, h4_timestamp, side):
    if not USE_D1_TREND_FILTER:
        return True, "d1_off"
    d1_trend = get_d1_trend_at(d1_df, h4_timestamp)
    if D1_FILTER_MODE == "strict":
        if side == "long" and d1_trend == "up":
            return True, "d1_up"
        if side == "short" and d1_trend == "down":
            return True, "d1_down"
        return False, f"d1_mismatch({d1_trend})"
    else:
        if side == "long" and d1_trend != "down":
            return True, f"d1_soft_ok({d1_trend})"
        if side == "short" and d1_trend != "up":
            return True, f"d1_soft_ok({d1_trend})"
        return False, f"d1_soft_block({d1_trend})"


def passes_sweep_confirmation(df_struct, entry_idx, side):
    if not USE_LIQUIDITY_SWEEP_CONF:
        return True, "sweep_off"
    start = max(0, entry_idx - SWEEP_LOOKBACK_BARS)
    end = entry_idx
    if side == "long":
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_low"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_low"].any()
    else:
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_high"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_high"].any()
    if SWEEP_STRICT_MODE:
        has_sweep = bool(pivot_sw)
    else:
        has_sweep = bool(pivot_sw or recent_sw)
    if has_sweep:
        return True, "sweep_confirmed"
    return False, "no_recent_sweep"


def passes_volume_filter(df_struct, zone_created_idx):
    if not USE_VOLUME_FILTER:
        return True, "vol_off"
    if "volume" not in df_struct.columns:
        return True, "vol_no_data"
    start = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
    end = zone_created_idx
    if end <= start:
        return True, "vol_window_empty"
    avg_vol = df_struct.loc[start:end - 1, "volume"].mean()
    zone_vol = df_struct.loc[zone_created_idx, "volume"]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return True, "vol_no_avg"
    ratio_avg = zone_vol / avg_vol
    if ratio_avg < VOLUME_SPIKE_MULT:
        return False, f"vol_low({ratio_avg:.2f})"
    if VOLUME_STRICT_MODE:
        if zone_created_idx >= 1:
            prev_vol = df_struct.loc[zone_created_idx - 1, "volume"]
            if pd.notna(prev_vol) and prev_vol > 0:
                ratio_prev = zone_vol / prev_vol
                if ratio_prev < VOLUME_PREV_MULT:
                    return False, f"vol_prev_low({ratio_prev:.2f})"
    return True, f"vol_spike({ratio_avg:.2f})"


def passes_pullback_depth(current_price, zone_low, zone_high, side):
    if not USE_PULLBACK_DEPTH:
        return True, "pullback_off"
    zone_size = zone_high - zone_low
    if zone_size <= 0:
        return False, "zone_invalid"
    if side == "long":
        depth = (zone_high - current_price) / zone_size
    else:
        depth = (current_price - zone_low) / zone_size
    if depth >= PULLBACK_MIN_DEPTH_FRAC:
        return True, f"depth_ok({depth:.2f})"
    return False, f"depth_shallow({depth:.2f})"


def passes_atr_filter(df_struct, entry_idx):
    if not USE_ATR_FILTER:
        return True, "atr_off"
    atr_val = df_struct.loc[entry_idx, "atr"]
    close_val = df_struct.loc[entry_idx, "close"]
    if pd.isna(atr_val) or pd.isna(close_val) or close_val <= 0:
        return True, "atr_no_data"
    atr_pct = (atr_val / close_val) * 100
    if atr_pct < ATR_MIN_PCT:
        return False, f"atr_too_low({atr_pct:.2f}%)"
    if atr_pct > ATR_MAX_PCT:
        return False, f"atr_too_high({atr_pct:.2f}%)"
    return True, f"atr_ok({atr_pct:.2f}%)"


# =========================================================
# ★★★ Stage 3: 필터 그룹 평가 헬퍼 ★★★
# =========================================================
def evaluate_all_filters(df_struct, df_d1, df_h1, entry_idx, zone_created_idx,
                          zone_low, zone_high, side, row):
    """
    모든 필터 독립 평가 — 그룹 판정/기록용.
    실제 필터 활성 여부 (USE_*_FILTER) 와 관계없이 판단.
    
    Returns:
        dict: {
            "pass_vol": bool,
            "pass_sweep": bool,
            "pass_d1": bool,
            "pass_pull": bool,
            "pass_atr": bool,
        }
    """
    result = {}
    
    # VOL — volume spike 기준
    if "volume" in df_struct.columns:
        start = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
        end = zone_created_idx
        if end <= start:
            result["pass_vol"] = True
        else:
            avg_vol = df_struct.loc[start:end - 1, "volume"].mean()
            zone_vol = df_struct.loc[zone_created_idx, "volume"]
            if pd.isna(avg_vol) or avg_vol <= 0:
                result["pass_vol"] = True
            else:
                result["pass_vol"] = (zone_vol / avg_vol) >= VOLUME_SPIKE_MULT
    else:
        result["pass_vol"] = True
    
    # SWEEP — pivot_sweep or recent_sweep 존재
    start = max(0, entry_idx - SWEEP_LOOKBACK_BARS)
    end = entry_idx
    if side == "long":
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_low"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_low"].any()
    else:
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_high"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_high"].any()
    result["pass_sweep"] = bool(pivot_sw or recent_sw)
    
    # D1 — D1 EMA fast > slow (long) or < (short)
    sub = df_d1[df_d1["timestamp"] < df_struct.loc[entry_idx, "timestamp"]]
    if len(sub) == 0:
        result["pass_d1"] = True  # 데이터 없으면 통과
    else:
        d1_trend = sub.iloc[-1]["d1_trend"]
        if side == "long":
            result["pass_d1"] = (d1_trend == "up")
        else:
            result["pass_d1"] = (d1_trend == "down")
    
    # PULLBACK — zone 진입 깊이
    zone_size = zone_high - zone_low
    if zone_size <= 0:
        result["pass_pull"] = False
    else:
        current_price = row["open"]
        if side == "long":
            depth = (zone_high - current_price) / zone_size
        else:
            depth = (current_price - zone_low) / zone_size
        result["pass_pull"] = depth >= PULLBACK_MIN_DEPTH_FRAC
    
    # ATR — ATR % 범위
    atr_val = df_struct.loc[entry_idx, "atr"]
    close_val = df_struct.loc[entry_idx, "close"]
    if pd.isna(atr_val) or pd.isna(close_val) or close_val <= 0:
        result["pass_atr"] = True
    else:
        atr_pct = (atr_val / close_val) * 100
        result["pass_atr"] = (ATR_MIN_PCT <= atr_pct <= ATR_MAX_PCT)
    
    return result


def evaluate_filter_groups(passes):
    """
    FILTER_GROUPS 그룹 평가.
    그룹 내부 OR, 그룹 간 AND.
    
    Args:
        passes: evaluate_all_filters 결과 dict
    
    Returns:
        (all_groups_pass, pass_combo_str, pass_count)
    """
    filter_key_map = {
        "VOLUME": "pass_vol",
        "LIQUIDITY_SWEEP": "pass_sweep",
        "D1_TREND": "pass_d1",
        "PULLBACK_DEPTH": "pass_pull",
        "ATR": "pass_atr",
    }
    
    passed_filters = []
    all_groups_pass = True
    
    for group in FILTER_GROUPS:
        group_pass = False
        for fname in group:
            key = filter_key_map.get(fname)
            if key and passes.get(key, False):
                group_pass = True
                if fname not in passed_filters:
                    passed_filters.append(fname)
        if not group_pass:
            all_groups_pass = False
    
    pass_combo = "+".join(sorted(passed_filters)) if passed_filters else "none"
    pass_count = len(passed_filters)
    return all_groups_pass, pass_combo, pass_count


# =========================================================
# ★★★ Stage 4D: 12 ATOMIC 태그 계산 ★★★
# =========================================================
# Tier / RP 를 구성하는 모든 원자(atomic) + SWEEP/VOLUME 을 독립 측정.
# 모든 태그는 로그 전용 — 진입 게이트 아님. Risk 전혀 미반영.
#
# [Tier 구성 5개]
#   classify_tier_v19b_rp_boost 내부 조건을 그대로 분해:
#     in_d     = (pre_total >= 4) or (2 <= sweep_count <= 4) or (score >= 13)
#     in_wick  = wick_ratio_5 <= WICK_RATIO_5_Q1_THRESHOLD
#     pre_total >= 1 (fallback)
#
# [RP 구성 5개]
#   get_run_potential 내부 rscore += 1 분기를 그대로 분해:
#     trend_align / mss / fvg / overlap / room
#
# [Entry Signal 2개]
#   sweep (pivot/recent), volume spike
def compute_trade_tags(df_struct, entry_idx, zone_created_idx,
                       zone_low, zone_high, side,
                       pre_total, sweep_count, score, wick_ratio_5,
                       structure_reasons, atr_val):
    """
    12개 atomic 태그 계산 (게이트 아님, 로그용).
    
    Args:
        pre_total, sweep_count, score, wick_ratio_5: tier 판정 inputs
        structure_reasons: structure['reasons'] 문자열 (mss/fvg/overlap 판정용)
        atr_val: atr 값 (room 판정용)
    
    Returns:
        dict with 12 atomic keys (a_*)
    """
    tags = {}

    # ─── Entry Signal (2개) ───
    # SWEEP
    start = max(0, entry_idx - SWEEP_LOOKBACK_BARS)
    end = entry_idx
    if side == "long":
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_low"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_low"].any()
    else:
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_high"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_high"].any()
    tags["a_sweep"] = bool(pivot_sw or recent_sw)

    # VOLUME spike
    if "volume" in df_struct.columns:
        vstart = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
        vend = zone_created_idx
        if vend <= vstart:
            tags["a_volume"] = False
        else:
            avg_vol = df_struct.loc[vstart:vend - 1, "volume"].mean()
            zone_vol = df_struct.loc[zone_created_idx, "volume"]
            if pd.isna(avg_vol) or avg_vol <= 0:
                tags["a_volume"] = False
            else:
                tags["a_volume"] = (zone_vol / avg_vol) >= VOLUME_SPIKE_MULT
    else:
        tags["a_volume"] = False

    # ─── Tier 구성 5개 ───
    # pre_total 은 int 로 전제
    pt = int(pre_total) if pd.notna(pre_total) else 0
    sc = int(sweep_count) if pd.notna(sweep_count) else 0
    sv = float(score) if pd.notna(score) else 0.0
    wv = wick_ratio_5

    tags["a_pre_total_ge4"]   = (pt >= 4)
    tags["a_sweep_count_2_4"] = (2 <= sc <= 4)
    tags["a_score_ge13"]      = (sv >= 13.0)
    tags["a_wick_le_q1"]      = (wv is not None) and (not pd.isna(wv)) and (wv <= WICK_RATIO_5_Q1_THRESHOLD)
    tags["a_pre_total_ge1"]   = (pt >= 1)

    # ─── RP 구성 5개 ───
    # structure_reasons 는 쉼표 구분 문자열
    reasons = str(structure_reasons) if structure_reasons is not None else ""
    reasons_set = set(r.strip() for r in reasons.split(",") if r.strip())

    # trend_align: side 방향과 H4 trend 일치
    h4_trend = df_struct.loc[entry_idx, "trend"] if "trend" in df_struct.columns else "neutral"
    tags["a_trend_align"] = (side == "long" and h4_trend == "up") or \
                             (side == "short" and h4_trend == "down")

    tags["a_mss"]     = ("bull_mss" in reasons_set) or ("bear_mss" in reasons_set)
    tags["a_fvg"]     = ("valid_bull_fvg" in reasons_set) or ("valid_bear_fvg" in reasons_set)
    tags["a_overlap"] = ("bull_ob_fvg_overlap" in reasons_set) or \
                         ("bear_ob_fvg_overlap" in reasons_set)

    # a_room: SL 대비 room >= 2.8 × risk  (get_run_potential 로직 재현)
    a_room = False
    if pd.notna(atr_val) and atr_val > 0:
        if side == "long":
            entry_proxy = zone_low + (zone_high - zone_low) * 0.40
            raw_sl = entry_proxy  # 근사 (정확한 sweep_ref 없이)
            # 정확도는 낮지만 room 개념 대략적 체크
            room_target = df_struct.loc[entry_idx, "pd_high"] if "pd_high" in df_struct.columns else np.nan
            if pd.notna(room_target):
                risk_est = max(atr_val * 0.08, 1e-9)
                room_est = max(room_target - entry_proxy, 0.0)
                a_room = (room_est >= risk_est * 2.8)
        else:
            entry_proxy = zone_low + (zone_high - zone_low) * 0.60
            room_target = df_struct.loc[entry_idx, "pd_low"] if "pd_low" in df_struct.columns else np.nan
            if pd.notna(room_target):
                risk_est = max(atr_val * 0.08, 1e-9)
                room_est = max(entry_proxy - room_target, 0.0)
                a_room = (room_est >= risk_est * 2.8)
    tags["a_room"] = bool(a_room)

    return tags


# ─── 하위 호환: 기존 Stage 4C compute_trade_tags 래퍼 (sweep/volume 만) ───
def compute_sweep_vol_only(df_struct, entry_idx, zone_created_idx,
                            zone_low, zone_high, side):
    """기존 호출 시그니처 호환 — sweep/volume 만 빠르게."""
    start = max(0, entry_idx - SWEEP_LOOKBACK_BARS)
    end = entry_idx
    if side == "long":
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_low"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_low"].any()
    else:
        pivot_sw = df_struct.loc[start:end, "pivot_sweep_high"].any()
        recent_sw = df_struct.loc[start:end, "recent_sweep_high"].any()
    sweep_ok = bool(pivot_sw or recent_sw)

    vol_ok = False
    if "volume" in df_struct.columns:
        vstart = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
        vend = zone_created_idx
        if vend > vstart:
            avg_vol = df_struct.loc[vstart:vend - 1, "volume"].mean()
            zone_vol = df_struct.loc[zone_created_idx, "volume"]
            if pd.notna(avg_vol) and avg_vol > 0:
                vol_ok = (zone_vol / avg_vol) >= VOLUME_SPIKE_MULT

    return {"tag_sweep": sweep_ok, "tag_volume": vol_ok}

# =========================================================
# INDICATORS
# =========================================================
def apply_basic_indicators(data):
    data = data.copy()
    data["ema20"] = data["close"].ewm(span=20, adjust=False).mean()
    data["ema50"] = data["close"].ewm(span=50, adjust=False).mean()
    data["ema200"] = data["close"].ewm(span=200, adjust=False).mean()

    def get_trend(row):
        if row["ema20"] < row["ema50"] < row["ema200"]:
            return "down"
        if row["ema20"] > row["ema50"] > row["ema200"]:
            return "up"
        return "neutral"

    data["trend"] = data.apply(get_trend, axis=1)
    data["range"] = data["high"] - data["low"]
    data["body"] = (data["close"] - data["open"]).abs()
    data["body_ratio"] = np.where(data["range"] > 0, data["body"] / data["range"], 0.0)

    tr1 = data["high"] - data["low"]
    tr2 = (data["high"] - data["close"].shift(1)).abs()
    tr3 = (data["low"] - data["close"].shift(1)).abs()
    data["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    data["atr"] = data["tr"].rolling(14).mean()
    return data


def apply_mss(data, mss_lookback=8):
    data = data.copy()
    data["bull_mss"] = False
    data["bear_mss"] = False
    for i in range(mss_lookback, len(data)):
        prev_high = data["high"].iloc[i - mss_lookback:i].max()
        prev_low = data["low"].iloc[i - mss_lookback:i].min()
        if data.loc[i, "close"] > prev_high:
            data.loc[i, "bull_mss"] = True
        if data.loc[i, "close"] < prev_low:
            data.loc[i, "bear_mss"] = True
    return data


def apply_displacement(data, disp_body_ratio=0.45, disp_atr_mult=0.90):
    data = data.copy()
    data["bull_disp"] = False
    data["bear_disp"] = False
    data["disp_strength"] = 0.0
    for i in range(1, len(data)):
        atr_val = data.loc[i, "atr"]
        if pd.isna(atr_val) or atr_val == 0:
            continue
        bull = (
            data.loc[i, "close"] > data.loc[i, "open"]
            and data.loc[i, "body_ratio"] >= disp_body_ratio
            and data.loc[i, "range"] >= atr_val * disp_atr_mult
        )
        bear = (
            data.loc[i, "close"] < data.loc[i, "open"]
            and data.loc[i, "body_ratio"] >= disp_body_ratio
            and data.loc[i, "range"] >= atr_val * disp_atr_mult
        )
        data.loc[i, "bull_disp"] = bull
        data.loc[i, "bear_disp"] = bear
        data.loc[i, "disp_strength"] = data.loc[i, "range"] / atr_val
    return data


def apply_fvg(data):
    data = data.copy()
    data["bull_fvg_low"] = np.nan
    data["bull_fvg_high"] = np.nan
    data["bear_fvg_low"] = np.nan
    data["bear_fvg_high"] = np.nan
    data["bull_fvg_size"] = np.nan
    data["bear_fvg_size"] = np.nan
    for i in range(2, len(data)):
        if data.loc[i, "low"] > data.loc[i - 2, "high"]:
            data.loc[i, "bull_fvg_low"] = data.loc[i - 2, "high"]
            data.loc[i, "bull_fvg_high"] = data.loc[i, "low"]
            data.loc[i, "bull_fvg_size"] = data.loc[i, "low"] - data.loc[i - 2, "high"]
        if data.loc[i, "high"] < data.loc[i - 2, "low"]:
            data.loc[i, "bear_fvg_low"] = data.loc[i, "high"]
            data.loc[i, "bear_fvg_high"] = data.loc[i - 2, "low"]
            data.loc[i, "bear_fvg_size"] = data.loc[i - 2, "low"] - data.loc[i, "high"]
    return data


def apply_ob(data, ob_lookback=8):
    data = data.copy()
    data["bull_ob_low"] = np.nan
    data["bull_ob_high"] = np.nan
    data["bear_ob_low"] = np.nan
    data["bear_ob_high"] = np.nan
    data["bull_ob_size"] = np.nan
    data["bear_ob_size"] = np.nan
    for i in range(2, len(data)):
        if data.loc[i, "bull_disp"]:
            for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                if data.loc[j, "close"] < data.loc[j, "open"]:
                    data.loc[i, "bull_ob_low"] = data.loc[j, "low"]
                    data.loc[i, "bull_ob_high"] = data.loc[j, "high"]
                    data.loc[i, "bull_ob_size"] = data.loc[j, "high"] - data.loc[j, "low"]
                    break
        if data.loc[i, "bear_disp"]:
            for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                if data.loc[j, "close"] > data.loc[j, "open"]:
                    data.loc[i, "bear_ob_low"] = data.loc[j, "low"]
                    data.loc[i, "bear_ob_high"] = data.loc[j, "high"]
                    data.loc[i, "bear_ob_size"] = data.loc[j, "high"] - data.loc[j, "low"]
                    break
    return data


def apply_pd(data, pd_lookback=40):
    data = data.copy()
    data["pd_high"] = data["high"].rolling(pd_lookback).max()
    data["pd_low"] = data["low"].rolling(pd_lookback).min()
    data["pd_mid"] = (data["pd_high"] + data["pd_low"]) / 2
    data["pd_loc"] = np.where(data["close"] >= data["pd_mid"], "premium", "discount")
    return data


def apply_pivots(data, swing_len=3):
    data = data.copy()
    data["pivot_high"] = np.nan
    data["pivot_low"] = np.nan
    for i in range(swing_len, len(data) - swing_len):
        if data.loc[i, "high"] == data["high"].iloc[i - swing_len:i + swing_len + 1].max():
            data.loc[i, "pivot_high"] = data.loc[i, "high"]
        if data.loc[i, "low"] == data["low"].iloc[i - swing_len:i + swing_len + 1].min():
            data.loc[i, "pivot_low"] = data.loc[i, "low"]

    last_high = np.nan
    last_low = np.nan
    prev_high = np.nan
    prev_low = np.nan
    data["last_pivot_high"] = np.nan
    data["prev_pivot_high"] = np.nan
    data["last_pivot_low"] = np.nan
    data["prev_pivot_low"] = np.nan

    for i in range(len(data)):
        lookup_bar = i - swing_len
        if lookup_bar >= 0:
            if pd.notna(data.loc[lookup_bar, "pivot_high"]):
                prev_high = last_high
                last_high = data.loc[lookup_bar, "pivot_high"]
            if pd.notna(data.loc[lookup_bar, "pivot_low"]):
                prev_low = last_low
                last_low = data.loc[lookup_bar, "pivot_low"]
        data.loc[i, "last_pivot_high"] = last_high
        data.loc[i, "prev_pivot_high"] = prev_high
        data.loc[i, "last_pivot_low"] = last_low
        data.loc[i, "prev_pivot_low"] = prev_low
    return data


def apply_structure_bias(data):
    data = data.copy()
    data["structure_bias"] = "neutral"
    current_bias = "neutral"
    for i in range(len(data)):
        lph = data.loc[i, "last_pivot_high"]
        pph = data.loc[i, "prev_pivot_high"]
        lpl = data.loc[i, "last_pivot_low"]
        ppl = data.loc[i, "prev_pivot_low"]
        if pd.notna(lph) and pd.notna(pph) and pd.notna(lpl) and pd.notna(ppl):
            if lph > pph and lpl > ppl:
                current_bias = "up"
            elif lph < pph and lpl < ppl:
                current_bias = "down"
        data.loc[i, "structure_bias"] = current_bias
    return data


def apply_choch(data, break_atr_mult=0.15):
    data = data.copy()
    data["bull_choch"] = False
    data["bear_choch"] = False
    for i in range(1, len(data)):
        atr_val = data.loc[i, "atr"] if pd.notna(data.loc[i, "atr"]) else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        bias = data.loc[i - 1, "structure_bias"]
        last_high = data.loc[i - 1, "last_pivot_high"]
        last_low = data.loc[i - 1, "last_pivot_low"]
        if bias == "down" and pd.notna(last_high):
            if data.loc[i, "close"] > (last_high + atr_val * break_atr_mult):
                data.loc[i, "bull_choch"] = True
        if bias == "up" and pd.notna(last_low):
            if data.loc[i, "close"] < (last_low - atr_val * break_atr_mult):
                data.loc[i, "bear_choch"] = True
    return data


def apply_h4_market_state(data, transition_bars=8):
    data = data.copy()
    data["market_state"] = "neutral"
    bull_until = -1
    bear_until = -1
    for i in range(len(data)):
        if data.loc[i, "bull_choch"]:
            bull_until = i + transition_bars
            bear_until = -1
        if data.loc[i, "bear_choch"]:
            bear_until = i + transition_bars
            bull_until = -1
        base_trend = data.loc[i, "trend"]
        if bull_until >= i and base_trend != "up":
            state = "bull_transition"
        elif bear_until >= i and base_trend != "down":
            state = "bear_transition"
        else:
            if base_trend == "up":
                state = "up"
            elif base_trend == "down":
                state = "down"
            else:
                state = "neutral"
        data.loc[i, "market_state"] = state
    return data


def has_recent_h1_choch(df_h1_local, h4_timestamp, side, lookback_hours=16):
    start_ts = h4_timestamp - pd.Timedelta(hours=lookback_hours)
    end_ts = h4_timestamp
    win = df_h1_local[(df_h1_local["timestamp"] > start_ts) & (df_h1_local["timestamp"] <= end_ts)]
    if len(win) == 0:
        return False
    if side == "long":
        return bool(win["bull_choch"].any())
    return bool(win["bear_choch"].any())


# =========================================================
# v1.9 TIER helpers
# =========================================================

def apply_sweep_flags(df, recent_sweep_n=10):
    df = df.copy()
    df["pivot_sweep_high"] = False
    df["pivot_sweep_low"] = False
    df["recent_sweep_high"] = False
    df["recent_sweep_low"] = False
    for i in range(recent_sweep_n, len(df)):
        lph = df.loc[i, "last_pivot_high"]
        lpl = df.loc[i, "last_pivot_low"]
        recent_high = df["high"].iloc[i-recent_sweep_n:i].max()
        recent_low = df["low"].iloc[i-recent_sweep_n:i].min()
        if pd.notna(lph) and df.loc[i, "high"] > lph and df.loc[i, "close"] < lph:
            df.loc[i, "pivot_sweep_high"] = True
        if pd.notna(lpl) and df.loc[i, "low"] < lpl and df.loc[i, "close"] > lpl:
            df.loc[i, "pivot_sweep_low"] = True
        if df.loc[i, "high"] > recent_high and df.loc[i, "close"] < recent_high:
            df.loc[i, "recent_sweep_high"] = True
        if df.loc[i, "low"] < recent_low and df.loc[i, "close"] > recent_low:
            df.loc[i, "recent_sweep_low"] = True
    return df


def compute_pre_entry_confluence(df_h4, df_h1, h4_entry_idx, zone_low, zone_high,
                                  lookback_ltf_bars=8):
    entry_h4_ts = df_h4.loc[h4_entry_idx, "timestamp"]
    ltf_mask = df_h1["timestamp"] <= entry_h4_ts
    if not ltf_mask.any():
        return 0, 0, 0, 0
    ltf_entry_idx = int(df_h1[ltf_mask].index[-1])
    start_idx = max(0, ltf_entry_idx - lookback_ltf_bars)
    end_idx = ltf_entry_idx
    if start_idx > end_idx or start_idx >= len(df_h1):
        return 0, 0, 0, 0
    sub = df_h1.iloc[start_idx:end_idx+1]
    fvg_count = ob_count = sweep_count = 0
    for _, r in sub.iterrows():
        for fvg_lo, fvg_hi in [("bull_fvg_low", "bull_fvg_high"), ("bear_fvg_low", "bear_fvg_high")]:
            lo, hi = r.get(fvg_lo), r.get(fvg_hi)
            if pd.notna(lo) and pd.notna(hi):
                mid = (float(lo) + float(hi)) / 2.0
                if zone_low <= mid <= zone_high:
                    fvg_count += 1
        for ob_lo, ob_hi in [("bull_ob_low", "bull_ob_high"), ("bear_ob_low", "bear_ob_high")]:
            lo, hi = r.get(ob_lo), r.get(ob_hi)
            if pd.notna(lo) and pd.notna(hi):
                mid = (float(lo) + float(hi)) / 2.0
                if zone_low <= mid <= zone_high:
                    ob_count += 1
        hs = bool(r.get("pivot_sweep_high", False)) or bool(r.get("recent_sweep_high", False))
        ls = bool(r.get("pivot_sweep_low", False)) or bool(r.get("recent_sweep_low", False))
        if hs:
            px = float(r["high"])
            if zone_low <= px <= zone_high:
                sweep_count += 1
        if ls:
            px = float(r["low"])
            if zone_low <= px <= zone_high:
                sweep_count += 1
    return sweep_count, fvg_count, ob_count, fvg_count + ob_count + sweep_count


def compute_wick_ratio_5(df_h4, df_h1, h4_entry_idx, side, lookback_n=5):
    entry_h4_ts = df_h4.loc[h4_entry_idx, "timestamp"]
    ltf_mask = df_h1["timestamp"] <= entry_h4_ts
    if not ltf_mask.any():
        return 0.0
    ltf_entry_idx = int(df_h1[ltf_mask].index[-1])
    start_idx = max(0, ltf_entry_idx - lookback_n)
    end_idx = ltf_entry_idx
    if start_idx >= end_idx:
        return 0.0
    sub = df_h1.iloc[start_idx:end_idx]
    sum_wick = 0.0
    sum_range = 0.0
    for _, r in sub.iterrows():
        o, c_px, h, l = float(r["open"]), float(r["close"]), float(r["high"]), float(r["low"])
        body_top = max(o, c_px)
        body_bot = min(o, c_px)
        bar_range = h - l
        if side == "long":
            directional_wick = body_bot - l
        else:
            directional_wick = h - body_top
        directional_wick = max(0.0, directional_wick)
        sum_wick += directional_wick
        sum_range += bar_range
    if sum_range <= 0:
        return 0.0
    return sum_wick / sum_range


# =========================================================
# ★★★ Stage 1 신규: classify_tier_v19b_rp_boost ★★★
# =========================================================
def classify_tier_v19b_rp_boost(pre_total, sweep_count, score, wick_ratio_5, run_potential):
    """
    v1.9b TIER + RP_BOOST 통합 분류.
    
    Returns:
        (tier_label, final_tier_mult, rp_action)
        - tier_label: "S", "A", "B", "C", "D"
        - final_tier_mult: base_tier_mult × RP_TIER_MULT_TABLE[run_potential]
                            (0.0 이면 skip)
        - rp_action: "rp_boost_rpN_xM.M" | "rp_pass_rpN" | "rp_skip_rpN" | "tier_d_skip"
    """
    # RP 테이블 밖 (RP 6+) → skip
    if run_potential not in RP_TIER_MULT_TABLE:
        return "D", 0.0, f"rp_skip_rp{run_potential}"
    
    rp_mult = RP_TIER_MULT_TABLE[run_potential]
    rp_action = (
        f"rp_boost_rp{run_potential}_x{rp_mult}" if rp_mult > 1.0
        else f"rp_pass_rp{run_potential}"
    )
    
    # 기존 v1.9b 티어 판정
    in_d = (pre_total >= 4) or (2 <= sweep_count <= 4) or (score >= 13)
    in_wick = (wick_ratio_5 is not None) and (not pd.isna(wick_ratio_5)) and (wick_ratio_5 <= WICK_RATIO_5_Q1_THRESHOLD)
    
    if in_d and in_wick:
        tier = "S"
        base_mult = TIER_RISK_S
    elif in_d and not in_wick:
        tier = "A"
        base_mult = TIER_RISK_A
    elif not in_d and in_wick:
        tier = "B"
        base_mult = TIER_RISK_B
    elif pre_total >= 1:
        tier = "C"
        base_mult = TIER_RISK_C
    else:
        # pre_total == 0 → Tier D → skip
        return "D", 0.0, "tier_d_skip"
    
    final_mult = base_mult * rp_mult
    return tier, final_mult, rp_action


print("Stage 1 Part 1/3 loaded: config + indicators + tier helpers (with RP_BOOST)")


# =========================================================
# STRUCTURE HELPERS
# =========================================================

def overlap_size(a_low, a_high, b_low, b_high):
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def is_zone_fresh_at_entry(df_local, zone_created_idx, entry_idx, zone_low, zone_high):
    start = zone_created_idx + 1
    end = entry_idx - 1
    if start < 0:
        start = 0
    if end >= len(df_local):
        end = len(df_local) - 1
    if start > end:
        return True
    touch_count = 0
    for t in range(start, end + 1):
        touched = (df_local.loc[t, "high"] >= zone_low) and (df_local.loc[t, "low"] <= zone_high)
        if touched:
            touch_count += 1
    return touch_count <= 1


def build_structures(df):
    recent_sweep_n = 10
    df = df.copy()

    df["pivot_sweep_high"] = False
    df["pivot_sweep_low"] = False
    df["recent_sweep_high"] = False
    df["recent_sweep_low"] = False

    for i in range(recent_sweep_n, len(df)):
        lph = df.loc[i, "last_pivot_high"]
        lpl = df.loc[i, "last_pivot_low"]
        recent_high = df["high"].iloc[i - recent_sweep_n:i].max()
        recent_low = df["low"].iloc[i - recent_sweep_n:i].min()

        if pd.notna(lph):
            if df.loc[i, "high"] > lph and df.loc[i, "close"] < lph:
                df.loc[i, "pivot_sweep_high"] = True
        if pd.notna(lpl):
            if df.loc[i, "low"] < lpl and df.loc[i, "close"] > lpl:
                df.loc[i, "pivot_sweep_low"] = True

        if df.loc[i, "high"] > recent_high and df.loc[i, "close"] < recent_high:
            df.loc[i, "recent_sweep_high"] = True
        if df.loc[i, "low"] < recent_low and df.loc[i, "close"] > recent_low:
            df.loc[i, "recent_sweep_low"] = True

    structure_wait = 10
    post_structure_zone_window = 6
    zone_max_age = H4_ZONE_MAX_AGE
    structures = []

    for i in range(60, len(df) - 1):
        short_sweep = bool(df.loc[i, "pivot_sweep_high"] or df.loc[i, "recent_sweep_high"])
        if short_sweep:
            for j in range(i + 1, min(i + structure_wait + 1, len(df))):
                if not (df.loc[j, "bear_disp"] or df.loc[j, "bear_mss"]):
                    continue
                base_score = 2.5
                reasons = ["sweep"]

                if df.loc[i, "pd_loc"] == "premium":
                    base_score += 1.0
                    reasons.append("premium")
                if df.loc[j, "bear_disp"]:
                    base_score += 3.0
                    reasons.append("bear_disp")
                if df.loc[j, "bear_mss"]:
                    base_score += 3.0
                    reasons.append("bear_mss")
                if df.loc[j, "trend"] == "down":
                    base_score += 1.5
                    reasons.append("trend_down")

                structure_idx = j
                found_zone = False

                for k in range(structure_idx + 1, min(structure_idx + post_structure_zone_window + 1, len(df))):
                    score_k = base_score
                    reasons_k = reasons.copy()

                    has_ob = pd.notna(df.loc[k, "bear_ob_low"]) and pd.notna(df.loc[k, "bear_ob_high"])
                    has_fvg = pd.notna(df.loc[k, "bear_fvg_low"]) and pd.notna(df.loc[k, "bear_fvg_high"])

                    if not (has_ob or has_fvg):
                        continue

                    ob_low = ob_high = None
                    fvg_low = fvg_high = None

                    if has_ob:
                        ob_low = float(df.loc[k, "bear_ob_low"])
                        ob_high = float(df.loc[k, "bear_ob_high"])
                        ob_size = float(df.loc[k, "bear_ob_size"]) if pd.notna(df.loc[k, "bear_ob_size"]) else 0.0
                        atr_val = float(df.loc[k, "atr"]) if pd.notna(df.loc[k, "atr"]) else np.nan

                        score_k += 1.5
                        reasons_k.append("valid_bear_ob")
                        if pd.notna(df.loc[k, "disp_strength"]) and df.loc[k, "disp_strength"] >= 1.2:
                            score_k += 1.0
                            reasons_k.append("strong_disp_ob")
                        if pd.notna(atr_val) and atr_val > 0 and ob_size / atr_val >= 0.20:
                            score_k += 0.5
                            reasons_k.append("sized_bear_ob")

                    if has_fvg:
                        fvg_low = float(df.loc[k, "bear_fvg_low"])
                        fvg_high = float(df.loc[k, "bear_fvg_high"])
                        fvg_size = float(df.loc[k, "bear_fvg_size"]) if pd.notna(df.loc[k, "bear_fvg_size"]) else 0.0
                        atr_val = float(df.loc[k, "atr"]) if pd.notna(df.loc[k, "atr"]) else np.nan

                        score_k += 1.0
                        reasons_k.append("valid_bear_fvg")
                        if pd.notna(atr_val) and atr_val > 0 and fvg_size / atr_val >= 0.15:
                            score_k += 0.5
                            reasons_k.append("sized_bear_fvg")
                        if (k - structure_idx) <= 2:
                            score_k += 0.75
                            reasons_k.append("early_bear_fvg")

                    if has_ob and has_fvg:
                        ov = overlap_size(ob_low, ob_high, fvg_low, fvg_high)
                        if ov > 0:
                            score_k += 1.5
                            reasons_k.append("bear_ob_fvg_overlap")
                        zone_low = min(ob_low, fvg_low)
                        zone_high = max(ob_high, fvg_high)
                    elif has_ob:
                        zone_low = ob_low
                        zone_high = ob_high
                    else:
                        zone_low = fvg_low
                        zone_high = fvg_high

                    if zone_low < zone_high:
                        structures.append({
                            "type": "short", "sweep_idx": i, "structure_idx": structure_idx,
                            "zone_created_idx": k, "zone_low": float(zone_low), "zone_high": float(zone_high),
                            "sweep_ref": float(df.loc[i, "high"]),
                            "expire_idx": min(k + zone_max_age, len(df) - 1),
                            "used": False, "score": float(score_k), "reasons": ",".join(reasons_k),
                            "has_ob": bool(has_ob), "has_fvg": bool(has_fvg),
                            "ob_low": float(ob_low) if has_ob else None,
                            "ob_high": float(ob_high) if has_ob else None,
                            "fvg_low": float(fvg_low) if has_fvg else None,
                            "fvg_high": float(fvg_high) if has_fvg else None,
                        })
                        found_zone = True
                        break

                if found_zone:
                    break

        long_sweep = bool(df.loc[i, "pivot_sweep_low"] or df.loc[i, "recent_sweep_low"])
        if long_sweep:
            for j in range(i + 1, min(i + structure_wait + 1, len(df))):
                if not (df.loc[j, "bull_disp"] or df.loc[j, "bull_mss"]):
                    continue
                base_score = 2.5
                reasons = ["sweep"]

                if df.loc[i, "pd_loc"] == "discount":
                    base_score += 1.0
                    reasons.append("discount")
                if df.loc[j, "bull_disp"]:
                    base_score += 3.0
                    reasons.append("bull_disp")
                if df.loc[j, "bull_mss"]:
                    base_score += 3.0
                    reasons.append("bull_mss")
                if df.loc[j, "trend"] == "up":
                    base_score += 1.5
                    reasons.append("trend_up")

                structure_idx = j
                found_zone = False

                for k in range(structure_idx + 1, min(structure_idx + post_structure_zone_window + 1, len(df))):
                    score_k = base_score
                    reasons_k = reasons.copy()

                    has_ob = pd.notna(df.loc[k, "bull_ob_low"]) and pd.notna(df.loc[k, "bull_ob_high"])
                    has_fvg = pd.notna(df.loc[k, "bull_fvg_low"]) and pd.notna(df.loc[k, "bull_fvg_high"])

                    if not (has_ob or has_fvg):
                        continue

                    ob_low = ob_high = None
                    fvg_low = fvg_high = None

                    if has_ob:
                        ob_low = float(df.loc[k, "bull_ob_low"])
                        ob_high = float(df.loc[k, "bull_ob_high"])
                        ob_size = float(df.loc[k, "bull_ob_size"]) if pd.notna(df.loc[k, "bull_ob_size"]) else 0.0
                        atr_val = float(df.loc[k, "atr"]) if pd.notna(df.loc[k, "atr"]) else np.nan

                        score_k += 1.5
                        reasons_k.append("valid_bull_ob")
                        if pd.notna(df.loc[k, "disp_strength"]) and df.loc[k, "disp_strength"] >= 1.2:
                            score_k += 1.0
                            reasons_k.append("strong_disp_ob")
                        if pd.notna(atr_val) and atr_val > 0 and ob_size / atr_val >= 0.20:
                            score_k += 0.5
                            reasons_k.append("sized_bull_ob")

                    if has_fvg:
                        fvg_low = float(df.loc[k, "bull_fvg_low"])
                        fvg_high = float(df.loc[k, "bull_fvg_high"])
                        fvg_size = float(df.loc[k, "bull_fvg_size"]) if pd.notna(df.loc[k, "bull_fvg_size"]) else 0.0
                        atr_val = float(df.loc[k, "atr"]) if pd.notna(df.loc[k, "atr"]) else np.nan

                        score_k += 1.0
                        reasons_k.append("valid_bull_fvg")
                        if pd.notna(atr_val) and atr_val > 0 and fvg_size / atr_val >= 0.15:
                            score_k += 0.5
                            reasons_k.append("sized_bull_fvg")
                        if (k - structure_idx) <= 2:
                            score_k += 0.75
                            reasons_k.append("early_bull_fvg")

                    if has_ob and has_fvg:
                        ov = overlap_size(ob_low, ob_high, fvg_low, fvg_high)
                        if ov > 0:
                            score_k += 1.5
                            reasons_k.append("bull_ob_fvg_overlap")
                        zone_low = min(ob_low, fvg_low)
                        zone_high = max(ob_high, fvg_high)
                    elif has_ob:
                        zone_low = ob_low
                        zone_high = ob_high
                    else:
                        zone_low = fvg_low
                        zone_high = fvg_high

                    if zone_low < zone_high:
                        structures.append({
                            "type": "long", "sweep_idx": i, "structure_idx": structure_idx,
                            "zone_created_idx": k, "zone_low": float(zone_low), "zone_high": float(zone_high),
                            "sweep_ref": float(df.loc[i, "low"]),
                            "expire_idx": min(k + zone_max_age, len(df) - 1),
                            "used": False, "score": float(score_k), "reasons": ",".join(reasons_k),
                            "has_ob": bool(has_ob), "has_fvg": bool(has_fvg),
                            "ob_low": float(ob_low) if has_ob else None,
                            "ob_high": float(ob_high) if has_ob else None,
                            "fvg_low": float(fvg_low) if has_fvg else None,
                            "fvg_high": float(fvg_high) if has_fvg else None,
                        })
                        found_zone = True
                        break

                if found_zone:
                    break

    structures_by_zone_created = {}
    for s in structures:
        structures_by_zone_created.setdefault(s["zone_created_idx"], []).append(s)

    return df, structures, structures_by_zone_created


def evaluate_freshness_at_entry(df_local, structure, entry_idx):
    side = structure["type"]
    side_tag = "bull" if side == "long" else "bear"
    bonus = 0.0
    fresh_reasons = []

    if structure.get("has_ob"):
        if is_zone_fresh_at_entry(df_local, structure["zone_created_idx"], entry_idx,
                                   structure["ob_low"], structure["ob_high"]):
            bonus += 1.0
            fresh_reasons.append(f"fresh_{side_tag}_ob")

    if structure.get("has_fvg"):
        if is_zone_fresh_at_entry(df_local, structure["zone_created_idx"], entry_idx,
                                   structure["fvg_low"], structure["fvg_high"]):
            bonus += 0.5
            fresh_reasons.append(f"fresh_{side_tag}_fvg")

    return bonus, fresh_reasons


# =========================================================
# RISK / ENTRY HELPERS
# =========================================================
def calc_min_stop_distance(entry, atr_val):
    pct_floor = entry * 0.003
    atr_floor = atr_val * 0.25 if pd.notna(atr_val) and atr_val > 0 else 0.0
    return max(pct_floor, atr_floor)


def clamp_stop_for_long(entry, raw_sl, atr_val):
    min_dist = calc_min_stop_distance(entry, atr_val)
    max_sl = entry - min_dist
    return min(raw_sl, max_sl)


def clamp_stop_for_short(entry, raw_sl, atr_val):
    min_dist = calc_min_stop_distance(entry, atr_val)
    min_sl = entry + min_dist
    return max(raw_sl, min_sl)


def calc_position_size(balance, risk_pct, entry, sl, fee_rate, max_notional_mult=3.0):
    risk_amount = balance * risk_pct
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return None, None, None

    qty = risk_amount / risk_per_unit
    notional = abs(entry * qty)

    max_notional = balance * max_notional_mult
    if notional > max_notional:
        qty = max_notional / abs(entry)
        notional = abs(entry * qty)

    est_roundtrip_fee = notional * fee_rate * 2
    if est_roundtrip_fee > risk_amount * 0.35:
        return None, None, None

    return qty, risk_per_unit, notional


def parse_reason_set(reason_str):
    if pd.isna(reason_str) or str(reason_str).strip() == "":
        return set()
    return set([x.strip() for x in str(reason_str).split(",") if x.strip()])


def get_run_potential(df_local, i, structure):
    side = structure["type"]
    reasons = parse_reason_set(structure["reasons"])

    rscore = 0
    tags = []

    if side == "long" and df_local.loc[i, "trend"] == "up":
        rscore += 1
        tags.append("trend_align")
    if side == "short" and df_local.loc[i, "trend"] == "down":
        rscore += 1
        tags.append("trend_align")

    if "bull_mss" in reasons or "bear_mss" in reasons:
        rscore += 1
        tags.append("mss")

    if "valid_bull_fvg" in reasons or "valid_bear_fvg" in reasons:
        rscore += 1
        tags.append("fvg")

    if "bull_ob_fvg_overlap" in reasons or "bear_ob_fvg_overlap" in reasons:
        rscore += 1
        tags.append("overlap")

    if side == "long":
        entry_proxy = structure["zone_low"] + (structure["zone_high"] - structure["zone_low"]) * 0.40
        raw_sl = structure["sweep_ref"] - (df_local.loc[i, "atr"] if pd.notna(df_local.loc[i, "atr"]) else 0.0) * 0.08
        sl_proxy = clamp_stop_for_long(entry_proxy, raw_sl, df_local.loc[i, "atr"])
        if sl_proxy < entry_proxy:
            risk = entry_proxy - sl_proxy
            room = (df_local.loc[i, "pd_high"] - entry_proxy) if pd.notna(df_local.loc[i, "pd_high"]) else 0.0
            if risk > 0 and pd.notna(room) and room >= risk * 2.8:
                rscore += 1
                tags.append("room")
    else:
        entry_proxy = structure["zone_low"] + (structure["zone_high"] - structure["zone_low"]) * 0.60
        raw_sl = structure["sweep_ref"] + (df_local.loc[i, "atr"] if pd.notna(df_local.loc[i, "atr"]) else 0.0) * 0.08
        sl_proxy = clamp_stop_for_short(entry_proxy, raw_sl, df_local.loc[i, "atr"])
        if sl_proxy > entry_proxy:
            risk = sl_proxy - entry_proxy
            room = (entry_proxy - df_local.loc[i, "pd_low"]) if pd.notna(df_local.loc[i, "pd_low"]) else 0.0
            if risk > 0 and pd.notna(room) and room >= risk * 2.8:
                rscore += 1
                tags.append("room")

    return rscore, ",".join(tags)


def classify_grade(entry_score, run_potential):
    if run_potential >= 3 and entry_score >= 10.0:
        return "S"
    elif run_potential == 2 and entry_score >= 10.0:
        return "A"
    return "B"


def get_expansion_state(market_state, h1_choch_confirm):
    return bool(h1_choch_confirm and market_state in ["up", "down"])


def get_tp_plan(expansion_state=False):
    if expansion_state:
        return {
            "name": "expansion",
            "targets": [(1.0, 0.15), (2.0, 0.15), (3.0, 0.10)],
            "runner_frac": 0.60,
            "trail_activate_rr": 4.0,
            "be_after_rr": 1.5,
            "max_hold_bars": 20,
        }
    return {
        "name": "base",
        "targets": [(1.0, 0.25), (2.0, 0.20), (3.0, 0.15)],
        "runner_frac": 0.40,
        "trail_activate_rr": 3.0,
        "be_after_rr": 1.0,
        "max_hold_bars": 12,
    }


def update_trailing_stop(df_local, j, side, current_stop, entry):
    if j - 1 < 0:
        return current_stop

    prev_high = df_local.loc[j - 1, "high"]
    prev_low = df_local.loc[j - 1, "low"]
    prev_range = prev_high - prev_low
    atr_val = df_local.loc[j - 1, "atr"] if pd.notna(df_local.loc[j - 1, "atr"]) else 0.0

    if side == "long":
        candidate = prev_low + prev_range * 0.50 - atr_val * 0.10
        candidate = max(candidate, entry)
        return max(current_stop, candidate)

    candidate = prev_high - prev_range * 0.50 + atr_val * 0.10
    candidate = min(candidate, entry)
    return min(current_stop, candidate)


# =========================================================
# TRADE SIMULATOR (v1.9b 와 동일)
# =========================================================
def calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low):
    if risk_per_unit <= 0:
        return np.nan
    if side == "long":
        return (bar_high - entry) / risk_per_unit
    return (entry - bar_low) / risk_per_unit


def _simulate_trade_with_plan_core(df_local, entry_idx, side, entry, sl, qty, fee_rate, grade, plan,
                                    use_seq_runner_protection=False, disable_time_exit_when_runner=False):
    eps = 1e-12
    entry_time = df_local.loc[entry_idx, "timestamp"]
    risk_per_unit = abs(entry - sl)
    max_hold_bars = plan["max_hold_bars"]

    targets = []
    for rr, frac in plan["targets"]:
        px = entry + risk_per_unit * rr if side == "long" else entry - risk_per_unit * rr
        targets.append({"rr": rr, "frac": frac, "price": px, "hit": False})

    remaining_qty = qty
    realized_pnl = 0.0
    exit_fees = 0.0
    current_stop = sl
    be_moved = False
    runner_active = False
    exit_reason = None
    exit_idx = None
    exit_time = None

    entry_fee = abs(entry * qty) * fee_rate
    max_rr_seen = 0.0
    runner_max_rr_seen = np.nan

    bars_to_2r = np.nan
    bars_spent_above_2r = 0
    current_consecutive_above_2r = 0
    max_rr_after_2r = 0.0

    cond_count_final = 0
    runner_candidate_2of3 = False
    post_2of3_apply_ok = False
    runner_protected = False

    stop_type_last = "initial"

    def lock_profit_stop():
        if side == "long":
            return entry + risk_per_unit * RUNNER_PROTECT_LOCKED_R
        return entry - risk_per_unit * RUNNER_PROTECT_LOCKED_R

    def update_max_rr(bar_high, bar_low):
        nonlocal max_rr_seen, runner_max_rr_seen
        favorable_rr = calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low)
        max_rr_seen = max(max_rr_seen, favorable_rr)
        if runner_active:
            if pd.isna(runner_max_rr_seen):
                runner_max_rr_seen = favorable_rr
            else:
                runner_max_rr_seen = max(runner_max_rr_seen, favorable_rr)

    def register_rr_stats(j, favorable_rr):
        nonlocal bars_to_2r, bars_spent_above_2r, current_consecutive_above_2r, max_rr_after_2r
        nonlocal cond_count_final, runner_candidate_2of3, post_2of3_apply_ok, runner_protected
        nonlocal current_stop, stop_type_last

        hold_bar = j - entry_idx

        if favorable_rr >= 2.0:
            bars_spent_above_2r += 1
            current_consecutive_above_2r += 1

            if pd.isna(bars_to_2r):
                bars_to_2r = hold_bar

            if favorable_rr > 2.0:
                max_rr_after_2r = max(max_rr_after_2r, favorable_rr - 2.0)
        else:
            current_consecutive_above_2r = 0

        cond_fast_2r = (pd.notna(bars_to_2r) and bars_to_2r <= FAST_2R_BARS_MAX)
        cond_hold_above_2r = (bars_spent_above_2r >= ABOVE_2R_BARS_MIN)
        cond_extra_expand = (max_rr_after_2r >= MAX_RR_AFTER_2R_MIN)
        cond_count_final = int(cond_fast_2r) + int(cond_hold_above_2r) + int(cond_extra_expand)

        if cond_count_final >= RUNNER_CANDIDATE_MIN_CONDS:
            runner_candidate_2of3 = True

        if use_seq_runner_protection and runner_candidate_2of3 and not post_2of3_apply_ok:
            if POST_2OF3_APPLY_USE_EXPANSION_FILTER:
                if max_rr_after_2r >= POST_2OF3_APPLY_MAX_RR_AFTER_2R:
                    post_2of3_apply_ok = True
            else:
                post_2of3_apply_ok = True

        if use_seq_runner_protection and not runner_protected:
            gate = True
            if RUNNER_PROTECT_ONLY_IF_BE_MOVED:
                gate = be_moved

            if gate and runner_candidate_2of3 and post_2of3_apply_ok:
                protected_stop = lock_profit_stop()
                runner_protected = True
                if side == "long":
                    current_stop = max(current_stop, protected_stop)
                else:
                    current_stop = min(current_stop, protected_stop)
                stop_type_last = "runner_protected"

    def hit_target(target):
        nonlocal remaining_qty, realized_pnl, exit_fees, be_moved, runner_active, current_stop, stop_type_last

        if target["hit"]:
            return

        part_qty = min(qty * target["frac"], remaining_qty)
        if part_qty <= eps:
            target["hit"] = True
            return

        if side == "long":
            realized_pnl += (target["price"] - entry) * part_qty
        else:
            realized_pnl += (entry - target["price"]) * part_qty

        exit_fees += abs(target["price"] * part_qty) * fee_rate
        remaining_qty -= part_qty
        target["hit"] = True

        if (not be_moved) and (target["rr"] >= plan["be_after_rr"]):
            be_moved = True
            current_stop = entry
            stop_type_last = "be"

        if plan["trail_activate_rr"] is not None and target["rr"] >= plan["trail_activate_rr"] and plan["runner_frac"] > 0:
            runner_active = True

    loop_end = len(df_local) if disable_time_exit_when_runner else min(len(df_local), entry_idx + max_hold_bars + 1)

    for j in range(entry_idx + 1, loop_end):
        bar_open = df_local.loc[j, "open"]
        bar_high = df_local.loc[j, "high"]
        bar_low = df_local.loc[j, "low"]
        bar_close = df_local.loc[j, "close"]

        favorable_rr = calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low)
        register_rr_stats(j, favorable_rr)
        update_max_rr(bar_high, bar_low)

        if remaining_qty <= eps:
            exit_reason = "all_targets"
            exit_idx = j
            exit_time = df_local.loc[j, "timestamp"]
            break

        if runner_active and remaining_qty > eps:
            trailed = update_trailing_stop(df_local, j, side, current_stop, entry)
            if side == "long":
                if trailed > current_stop:
                    stop_type_last = "trail"
                current_stop = max(current_stop, trailed)
            else:
                if trailed < current_stop:
                    stop_type_last = "trail"
                current_stop = min(current_stop, trailed)

        bull_bar = bar_close >= bar_open
        if side == "long":
            event_order = ["high", "low"] if bull_bar else ["low", "high"]
        else:
            event_order = ["low", "high"] if not bull_bar else ["high", "low"]

        for evt in event_order:
            if remaining_qty <= eps:
                break

            if side == "long":
                if evt == "high":
                    for tgt in targets:
                        if (not tgt["hit"]) and (bar_high >= tgt["price"]):
                            hit_target(tgt)
                elif evt == "low":
                    if bar_low <= current_stop and remaining_qty > eps:
                        realized_pnl += (current_stop - entry) * remaining_qty
                        exit_fees += abs(current_stop * remaining_qty) * fee_rate
                        remaining_qty = 0.0
                        exit_reason = "stop"
                        exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]
                        break
            else:
                if evt == "low":
                    for tgt in targets:
                        if (not tgt["hit"]) and (bar_low <= tgt["price"]):
                            hit_target(tgt)
                elif evt == "high":
                    if bar_high >= current_stop and remaining_qty > eps:
                        realized_pnl += (entry - current_stop) * remaining_qty
                        exit_fees += abs(current_stop * remaining_qty) * fee_rate
                        remaining_qty = 0.0
                        exit_reason = "stop"
                        exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]
                        break

        if exit_reason is not None:
            break

        if (not disable_time_exit_when_runner) and (j - entry_idx >= max_hold_bars):
            if remaining_qty > eps:
                if side == "long":
                    realized_pnl += (bar_close - entry) * remaining_qty
                else:
                    realized_pnl += (entry - bar_close) * remaining_qty
                exit_fees += abs(bar_close * remaining_qty) * fee_rate
                remaining_qty = 0.0
            exit_reason = "time_exit"
            exit_idx = j
            exit_time = df_local.loc[j, "timestamp"]
            break

        if disable_time_exit_when_runner and (j - entry_idx >= max_hold_bars) and (not runner_active) and (not runner_protected):
            if remaining_qty > eps:
                if side == "long":
                    realized_pnl += (bar_close - entry) * remaining_qty
                else:
                    realized_pnl += (entry - bar_close) * remaining_qty
                exit_fees += abs(bar_close * remaining_qty) * fee_rate
                remaining_qty = 0.0
            exit_reason = "time_exit_non_runner"
            exit_idx = j
            exit_time = df_local.loc[j, "timestamp"]
            break

    if exit_reason is None:
        j = len(df_local) - 1
        bar_close = df_local.loc[j, "close"]
        if remaining_qty > eps:
            if side == "long":
                realized_pnl += (bar_close - entry) * remaining_qty
            else:
                realized_pnl += (entry - bar_close) * remaining_qty
            exit_fees += abs(bar_close * remaining_qty) * fee_rate
            remaining_qty = 0.0

        exit_reason = "close_at_end"
        exit_idx = j
        exit_time = df_local.loc[j, "timestamp"]

    net_pnl = realized_pnl - entry_fee - exit_fees
    risk_amount = risk_per_unit * qty
    r_multiple = net_pnl / risk_amount if risk_amount > 0 else np.nan

    proxy_runner = bool(
        (True if not RUNNER_PROXY_TARGET3 else any([t["hit"] and abs(t["rr"] - 3.0) < 1e-9 for t in targets]))
        and (max_rr_seen >= RUNNER_PROXY_MAX_RR)
    )

    if exit_reason in ["time_exit", "time_exit_non_runner"]:
        result = exit_reason
    elif exit_reason == "close_at_end":
        result = "close_at_end"
    elif net_pnl >= 0:
        result = "win"
    else:
        result = "loss"

    return {
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_idx": exit_idx,
        "exit_reason": exit_reason,
        "result": result,
        "net_pnl": net_pnl,
        "risk_amount": risk_amount,
        "r_multiple": r_multiple,
        "be_moved": be_moved,
        "runner_active": runner_active,
        "hold_bars": exit_idx - entry_idx,
        "target1_hit": any([t["hit"] and abs(t["rr"] - 1.0) < 1e-9 for t in targets]),
        "target2_hit": any([t["hit"] and abs(t["rr"] - 2.0) < 1e-9 for t in targets]),
        "target3_hit": any([t["hit"] and abs(t["rr"] - 3.0) < 1e-9 for t in targets]),
        "max_rr_seen": max_rr_seen,
        "runner_max_rr_seen": runner_max_rr_seen,
        "bars_to_2r": bars_to_2r,
        "bars_spent_above_2r": bars_spent_above_2r,
        "max_rr_after_2r": max_rr_after_2r,
        "cond_count_final": cond_count_final,
        "runner_candidate_2of3": runner_candidate_2of3,
        "post_2of3_apply_ok": post_2of3_apply_ok,
        "runner_protected": runner_protected,
        "stop_type_last": stop_type_last,
        "proxy_runner": proxy_runner,
    }


def simulate_trade_with_plan_original(df_local, entry_idx, side, entry, sl, qty, fee_rate, grade, plan,
                                       use_seq_runner_protection=False):
    return _simulate_trade_with_plan_core(
        df_local=df_local, entry_idx=entry_idx, side=side, entry=entry, sl=sl,
        qty=qty, fee_rate=fee_rate, grade=grade, plan=plan,
        use_seq_runner_protection=use_seq_runner_protection,
        disable_time_exit_when_runner=False,
    )


def simulate_trade_with_plan_runner_no_time_exit(df_local, entry_idx, side, entry, sl, qty, fee_rate, grade, plan,
                                                  use_seq_runner_protection=False):
    return _simulate_trade_with_plan_core(
        df_local=df_local, entry_idx=entry_idx, side=side, entry=entry, sl=sl,
        qty=qty, fee_rate=fee_rate, grade=grade, plan=plan,
        use_seq_runner_protection=use_seq_runner_protection,
        disable_time_exit_when_runner=True,
    )


# =========================================================
# PHASE HELPERS
# =========================================================
def get_current_phase(balance_usdt):
    return "B" if balance_usdt >= TARGET_BALANCE_USDT else "A"


def get_phase_risk_pct(phase, symbol):
    if phase == "B":
        return PHASE_B_RISK.get(symbol, PHASE_A_RISK.get(symbol, 0.01))
    return PHASE_A_RISK.get(symbol, 0.01)


def cap_and_extract_excess(balance_usdt):
    if balance_usdt <= TARGET_BALANCE_USDT:
        return balance_usdt, 0.0
    excess = balance_usdt - TARGET_BALANCE_USDT
    return TARGET_BALANCE_USDT, excess


print("Stage 1 Part 2/3 loaded: structures + trade simulator + phase helpers")


# =========================================================
# CANDIDATE GENERATION (Stage 1: REFINE 제거)
# =========================================================
def download_symbol_data(symbol):
    print(f"\n==================== {symbol} DATA DOWNLOAD ====================")
    df = download_data(symbol=symbol, interval="4h")
    df_h1 = download_data(symbol=symbol, interval="1h")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365 * LOOKBACK_YEARS)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    df_h1 = df_h1[df_h1["timestamp"] >= cutoff].reset_index(drop=True)
    print(f"{symbol} H4: {len(df)} rows, H1: {len(df_h1)} rows")
    return {"symbol": symbol, "df_raw": df, "df_h1_raw": df_h1}


def apply_indicators_and_build(raw):
    symbol = raw["symbol"]
    df = raw["df_raw"].copy()
    df_h1 = raw["df_h1_raw"].copy()

    df = apply_basic_indicators(df)
    df = apply_mss(df, mss_lookback=H4_MSS_LOOKBACK)
    df = apply_displacement(df)
    df = apply_fvg(df)
    df = apply_ob(df, ob_lookback=H4_OB_LOOKBACK)
    df = apply_pd(df, pd_lookback=H4_PD_LOOKBACK)
    df = apply_pivots(df, swing_len=H4_PIVOT_SWING_LEN)
    df = apply_structure_bias(df)
    df = apply_choch(df, break_atr_mult=H4_CHOCH_BREAK_ATR_MULT)
    df = apply_h4_market_state(df, transition_bars=H4_MARKET_STATE_BARS)

    df_h1 = apply_basic_indicators(df_h1)
    df_h1 = apply_mss(df_h1)
    df_h1 = apply_displacement(df_h1)
    df_h1 = apply_fvg(df_h1)
    df_h1 = apply_ob(df_h1)
    df_h1 = apply_pd(df_h1, pd_lookback=40)
    df_h1 = apply_pivots(df_h1, swing_len=3)
    df_h1 = apply_structure_bias(df_h1)
    df_h1 = apply_choch(df_h1, break_atr_mult=0.12)
    df_h1 = apply_sweep_flags(df_h1, recent_sweep_n=10)

    df_struct, structures, structures_by_zone_created = build_structures(df)
    df_d1 = build_d1_trend(df_struct)

    print(f"{symbol} total structures: {len(structures)} | D1 bars: {len(df_d1)}")

    return {
        "symbol": symbol,
        "df_struct": df_struct,
        "df_h1": df_h1,
        "df_d1": df_d1,
        "structures": structures,
        "structures_by_zone_created": structures_by_zone_created,
    }


def generate_candidates_from_prepared(prepared):
    """
    Stage 1: REFINE 제거 + 기존 구조 유지.
    
    변경점:
    - refine_entry_with_h1_fvg 호출 제거
    - refined_entry_candidate = base_entry_candidate (단순 대입)
    - LONG/SHORT BASE_ENTRY_FRAC 보수적 (0.10 / 0.90)
    - 진입 체결가는 zone clamp 만 적용
    """
    symbol = prepared["symbol"]
    df_struct = prepared["df_struct"]
    df_h1 = prepared["df_h1"]
    df_d1 = prepared["df_d1"]
    structures = prepared["structures"]
    structures_by_zone_created = prepared["structures_by_zone_created"]

    for s in structures:
        s["used"] = False

    candidates = []
    skip_reasons = {}
    no_fill_log = []
    active_structures = []
    last_long_exit_idx = -9999
    last_short_exit_idx = -9999
    daily_trade_count = {}
    used_zone_ids = set()

    RELAX_MIN_SCORE = MIN_SCORE - FRESHNESS_MAX_BONUS  # ⭐ = 7.5 - 1.5 = 6.0

    def _track_skip(reason):
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    i = 200
    while i < len(df_struct) - 1:
        row = df_struct.iloc[i]

        if i in structures_by_zone_created:
            active_structures.extend(structures_by_zone_created[i])

        active_structures = [
            s for s in active_structures
            if (not s["used"])
            and (i <= s["expire_idx"])
            and (s["score"] >= RELAX_MIN_SCORE)  # ⭐ 후보 필터 (관대)
            and (s["zone_created_idx"] not in used_zone_ids)
        ]

        trade_day = str(row["timestamp"].date())
        if daily_trade_count.get(trade_day, 0) >= DAY_TRADE_LIMIT:
            i += 1
            continue

        entry_found = False
        used_structure = None
        used_effective_score = None
        used_reasons_full = None
        entry_side = None
        entry = sl = None
        grade = None
        run_potential = None
        run_tags = None
        tp_plan = None
        expansion_state = False
        base_entry = None
        refined_entry = None
        entry_refined = False
        refine_tag = ""
        fill_entry_price = None
        h4_market_state = df_struct.loc[i, "market_state"]
        pre_sweep_v = pre_fvg_v = pre_ob_v = pre_total_v = 0
        wick_ratio_v = 0.0

        scored_active = []
        for s in active_structures:
            fresh_bonus, fresh_reasons = evaluate_freshness_at_entry(df_struct, s, i)
            eff_score = float(s["score"]) + fresh_bonus
            if eff_score < MIN_SCORE:  # ⭐ 진입 문턱
                continue
            scored_active.append((s, eff_score, fresh_reasons))

        scored_active.sort(key=lambda x: (-x[1], x[0]["zone_created_idx"]))

        for s, eff_score, fresh_reasons in scored_active:
            touched = (row["high"] >= s["zone_low"]) and (row["low"] <= s["zone_high"])
            if not touched:
                continue

            # ⭐⭐ Stage 4D: 12 atomic 태그 계산 (모두 로그 전용, 게이트 아님)
            # pre_total / sweep_count / wick_ratio 는 structure 별로 계산된 값
            # 이 시점에선 아직 확정 안 되었으므로 임시 0 또는 structure field 이용
            # (정확한 값은 simulate 단계에서 다시 덮어씀)
            _atr_here = df_struct.loc[i, "atr"] if pd.notna(df_struct.loc[i, "atr"]) else 0.0
            _atoms = compute_trade_tags(
                df_struct=df_struct,
                entry_idx=i, zone_created_idx=s["zone_created_idx"],
                zone_low=s["zone_low"], zone_high=s["zone_high"],
                side=s["type"],
                pre_total=0,  # placeholder — simulate 에서 정확히 매핑
                sweep_count=0,
                score=float(eff_score),
                wick_ratio_5=None,
                structure_reasons=s.get("reasons", ""),
                atr_val=_atr_here,
            )
            # 간단한 sweep/volume 은 즉시 기록 (하위 호환)
            _sv = compute_sweep_vol_only(
                df_struct=df_struct,
                entry_idx=i, zone_created_idx=s["zone_created_idx"],
                zone_low=s["zone_low"], zone_high=s["zone_high"],
                side=s["type"],
            )
            _filter_passes = {
                "pass_vol":   _sv["tag_volume"],
                "pass_sweep": _sv["tag_sweep"],
                "pass_d1":    False,
                "pass_pull":  False,
                "pass_atr":   False,
            }
            _passed_names = []
            if _sv["tag_sweep"]:  _passed_names.append("SWEEP")
            if _sv["tag_volume"]: _passed_names.append("VOLUME")
            _pass_combo = "+".join(sorted(_passed_names)) if _passed_names else "none"
            _pass_count = len(_passed_names)

            if USE_FILTER_GROUPS:
                _groups_pass, _pass_combo, _pass_count = evaluate_filter_groups(_filter_passes)
                if not _groups_pass:
                    _track_skip(f"filter_groups_fail_{_pass_combo}")
                    continue

            vol_ok, vol_reason = passes_volume_filter(df_struct, s["zone_created_idx"])
            if (not USE_FILTER_GROUPS) and ((not USE_LIQUIDITY_SWEEP_CONF) or (SWEEP_VOLUME_MODE == "AND")):
                if not vol_ok:
                    _track_skip(vol_reason)
                    continue

            # ★ Stage 2 Compare: 실전 근사 fill — SHORT/LONG 분기 후 zone edge 로 덮어씀 (아래 참조)
            # 일단 placeholder (SHORT/LONG 분기 전 SL 계산용) — zone 중간
            fill_entry_price = float(max(s["zone_low"], min(row["open"], s["zone_high"])))
            atr_val = df_struct.loc[i, "atr"] if pd.notna(df_struct.loc[i, "atr"]) else 0.0

            rp, rp_tags = get_run_potential(df_struct, i, s)
            g = classify_grade(float(eff_score), rp)

            reasons_full = s["reasons"]
            if fresh_reasons:
                reasons_full = reasons_full + "," + ",".join(fresh_reasons) if reasons_full else ",".join(fresh_reasons)

            # 필터 그룹 모드에선 이미 그룹으로 평가했으므로 개별 체크 bypass
            if not USE_FILTER_GROUPS:
                atr_ok, atr_reason = passes_atr_filter(df_struct, i)
                if not atr_ok:
                    _track_skip(atr_reason)
                    continue

            if s["type"] == "short":
                if i - last_short_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "up":
                    continue

                # 필터 그룹 모드에선 이미 그룹으로 평가했으므로 개별 체크 bypass
                if not USE_FILTER_GROUPS:
                    d1_ok, d1_reason = passes_d1_filter(df_d1, df_struct.loc[i, "timestamp"], "short")
                    if not d1_ok:
                        _track_skip(d1_reason)
                        continue

                    sweep_ok, sweep_reason = passes_sweep_confirmation(df_struct, i, "short")
                    if USE_VOLUME_FILTER and SWEEP_VOLUME_MODE == "OR":
                        if not (sweep_ok or vol_ok):
                            _track_skip(f"or_fail({sweep_reason}|{vol_reason})")
                            continue
                    else:
                        if not sweep_ok:
                            _track_skip(sweep_reason)
                            continue

                    pullback_ok, pullback_reason = passes_pullback_depth(
                        row["open"], s["zone_low"], s["zone_high"], "short"
                    )
                    if not pullback_ok:
                        _track_skip(pullback_reason)
                        continue

                pre_sweep_v, pre_fvg_v, pre_ob_v, pre_total_v = compute_pre_entry_confluence(
                    df_struct, df_h1, i, s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_v = compute_wick_ratio_5(df_struct, df_h1, i, "short", WICK_LOOKBACK_BARS)

                h1_confirm_short = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="short", lookback_hours=H1_CHOCH_CONFIRM_HOURS
                )

                # ⭐⭐ Stage 2 Compare: REFINE 제거 + 실전 근사 fill
                # SHORT 포지션: 가격이 상승해서 zone 에 진입 → zone_low 에서 처음 터치 → 시장가 체결
                # 이게 실전 엔진의 current_price 체결과 가장 유사 (보수적 = 나쁜 SHORT entry)
                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * SHORT_BASE_ENTRY_FRAC
                refined_entry_candidate = base_entry_candidate  # REFINE OFF
                improved = False
                refine_px = np.nan
                refine_reason = "refine_off"

                # ⭐ 실전 근사 fill: SHORT 은 zone_low 에서 체결 (상승 중 처음 닿는 지점)
                fill_entry_price = float(s["zone_low"])
                fill_time_h1 = df_struct.loc[i, "timestamp"]
                fill_bars_waited = 0

                raw_sl = s["sweep_ref"] + atr_val * SL_BUFFER_MULT
                sl_candidate = clamp_stop_for_short(fill_entry_price, raw_sl, atr_val)
                if sl_candidate <= fill_entry_price:
                    continue

                expansion_candidate = get_expansion_state(h4_market_state, h1_confirm_short)
                plan = get_tp_plan(expansion_candidate)

                entry_found = True
                used_structure = s
                used_effective_score = eff_score
                used_reasons_full = reasons_full
                entry_side = "short"
                entry = fill_entry_price
                sl = sl_candidate
                grade = g
                run_potential = rp
                run_tags = rp_tags
                tp_plan = plan
                expansion_state = expansion_candidate
                base_entry = base_entry_candidate
                refined_entry = np.nan  # REFINE OFF
                entry_refined = False
                refine_tag = refine_reason
                _v17_signal_price = float(df_struct.loc[i, "close"])
                _v17_expected_entry = float(base_entry_candidate)
                _v17_submitted_entry = float(base_entry_candidate)  # refine 없음
                _v17_filled_entry = float(fill_entry_price)
                _v17_fill_time_h1 = fill_time_h1
                _v17_fill_bars_waited = fill_bars_waited
                break

            if s["type"] == "long":
                if i - last_long_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "down":
                    continue

                # 필터 그룹 모드에선 이미 그룹으로 평가했으므로 개별 체크 bypass
                if not USE_FILTER_GROUPS:
                    d1_ok, d1_reason = passes_d1_filter(df_d1, df_struct.loc[i, "timestamp"], "long")
                    if not d1_ok:
                        _track_skip(d1_reason)
                        continue

                    sweep_ok, sweep_reason = passes_sweep_confirmation(df_struct, i, "long")
                    if USE_VOLUME_FILTER and SWEEP_VOLUME_MODE == "OR":
                        if not (sweep_ok or vol_ok):
                            _track_skip(f"or_fail({sweep_reason}|{vol_reason})")
                            continue
                    else:
                        if not sweep_ok:
                            _track_skip(sweep_reason)
                            continue

                    pullback_ok, pullback_reason = passes_pullback_depth(
                        row["open"], s["zone_low"], s["zone_high"], "long"
                    )
                    if not pullback_ok:
                        _track_skip(pullback_reason)
                        continue

                pre_sweep_v, pre_fvg_v, pre_ob_v, pre_total_v = compute_pre_entry_confluence(
                    df_struct, df_h1, i, s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_v = compute_wick_ratio_5(df_struct, df_h1, i, "long", WICK_LOOKBACK_BARS)

                h1_confirm_long = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="long", lookback_hours=H1_CHOCH_CONFIRM_HOURS
                )

                # ⭐⭐ Stage 2 Compare: REFINE 제거 + 실전 근사 fill
                # LONG 포지션: 가격이 하락해서 zone 에 진입 → zone_high 에서 처음 터치 → 시장가 체결
                # 이게 실전 엔진의 current_price 체결과 가장 유사 (보수적 = 나쁜 LONG entry)
                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * LONG_BASE_ENTRY_FRAC
                refined_entry_candidate = base_entry_candidate  # REFINE OFF
                improved = False
                refine_px = np.nan
                refine_reason = "refine_off"

                # ⭐ 실전 근사 fill: LONG 은 zone_high 에서 체결 (하락 중 처음 닿는 지점)
                fill_entry_price = float(s["zone_high"])
                fill_time_h1 = df_struct.loc[i, "timestamp"]
                fill_bars_waited = 0

                raw_sl = s["sweep_ref"] - atr_val * SL_BUFFER_MULT
                sl_candidate = clamp_stop_for_long(fill_entry_price, raw_sl, atr_val)
                if sl_candidate >= fill_entry_price:
                    continue

                expansion_candidate = get_expansion_state(h4_market_state, h1_confirm_long)
                plan = get_tp_plan(expansion_candidate)

                entry_found = True
                used_structure = s
                used_effective_score = eff_score
                used_reasons_full = reasons_full
                entry_side = "long"
                entry = fill_entry_price
                sl = sl_candidate
                grade = g
                run_potential = rp
                run_tags = rp_tags
                tp_plan = plan
                expansion_state = expansion_candidate
                base_entry = base_entry_candidate
                refined_entry = np.nan  # REFINE OFF
                entry_refined = False
                refine_tag = refine_reason
                _v17_signal_price = float(df_struct.loc[i, "close"])
                _v17_expected_entry = float(base_entry_candidate)
                _v17_submitted_entry = float(base_entry_candidate)  # refine 없음
                _v17_filled_entry = float(fill_entry_price)
                _v17_fill_time_h1 = fill_time_h1
                _v17_fill_bars_waited = fill_bars_waited
                break

        if not entry_found:
            i += 1
            continue

        sim = simulate_trade_with_plan_original(
            df_local=df_struct, entry_idx=i, side=entry_side,
            entry=fill_entry_price, sl=sl, qty=1.0, fee_rate=FEE_RATE,
            grade=grade, plan=tp_plan,
            use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE,
        )

        used_structure["used"] = True
        used_zone_ids.add(used_structure["zone_created_idx"])
        daily_trade_count[trade_day] = daily_trade_count.get(trade_day, 0) + 1

        if entry_side == "long":
            last_long_exit_idx = sim["exit_idx"]
        else:
            last_short_exit_idx = sim["exit_idx"]

        candidates.append({
            "symbol": symbol,
            "entry_time": row["timestamp"],
            "exit_time": sim["exit_time"],
            "side": entry_side,
            "entry": entry,
            "fill_entry": fill_entry_price,
            "fill_vs_refined_pct": 0.0,  # refine 없음 → 차이 0
            "entry_idx": i,
            "signal_price":    _v17_signal_price,
            "expected_entry":  _v17_expected_entry,
            "submitted_entry": _v17_submitted_entry,
            "filled_entry":    _v17_filled_entry,
            "fill_status":     "filled",
            "fill_time_h1":    _v17_fill_time_h1,
            "fill_bars_waited": _v17_fill_bars_waited,
            "base_entry": base_entry,
            "entry_improved_by": 0.0,  # refine 없음
            "entry_refined": False,
            "refined_entry_px": np.nan,
            "refine_tag": "refine_off",
            "sl": sl,
            "risk_per_unit": abs(entry - sl),
            "r_multiple": sim["r_multiple"],
            "result": sim["result"],
            "exit_reason": sim["exit_reason"],
            "hold_bars": sim["hold_bars"],
            "score": used_effective_score,
            "base_score": used_structure["score"],
            "grade": grade,
            "run_potential": run_potential,
            "run_tags": run_tags,
            "pre_entry_sweep": pre_sweep_v,
            "pre_entry_fvg": pre_fvg_v,
            "pre_entry_ob": pre_ob_v,
            "pre_entry_total": pre_total_v,
            "wick_ratio_5": wick_ratio_v,
            "be_moved": sim["be_moved"],
            "runner_active": sim["runner_active"],
            "target1_hit": sim["target1_hit"],
            "target2_hit": sim["target2_hit"],
            "target3_hit": sim["target3_hit"],
            "max_rr_seen": sim["max_rr_seen"],
            "runner_max_rr_seen": sim["runner_max_rr_seen"],
            "bars_to_2r": sim["bars_to_2r"],
            "bars_spent_above_2r": sim["bars_spent_above_2r"],
            "max_rr_after_2r": sim["max_rr_after_2r"],
            "cond_count_final": sim["cond_count_final"],
            "runner_candidate_2of3": sim["runner_candidate_2of3"],
            "post_2of3_apply_ok": sim["post_2of3_apply_ok"],
            "runner_protected": sim["runner_protected"],
            "stop_type_last": sim["stop_type_last"],
            "proxy_runner": sim["proxy_runner"],
            "tp_plan_name": tp_plan["name"],
            "expansion_state": expansion_state,
            "reasons": used_reasons_full,
            "zone_created_idx": used_structure["zone_created_idx"],
            "market_state": h4_market_state,
            # ⭐⭐ Stage 4D: atomic 재계산에 필요한 원본 필드
            "structure_reasons_raw": s.get("reasons", ""),
            "atr_at_entry": float(_atr_here) if pd.notna(_atr_here) else 0.0,
            # 하위 호환 (기존 sweep/volume 태그)
            "tag_sweep":     bool(_sv.get("tag_sweep", False)),
            "tag_volume":    bool(_sv.get("tag_volume", False)),
            "pass_vol": _filter_passes.get("pass_vol", False),
            "pass_sweep": _filter_passes.get("pass_sweep", False),
            "pass_d1": _filter_passes.get("pass_d1", False),
            "pass_pull": _filter_passes.get("pass_pull", False),
            "pass_atr": _filter_passes.get("pass_atr", False),
            "pass_combo": _pass_combo,
            "pass_count": _pass_count,
            "filter_groups_active": USE_FILTER_GROUPS,
        })

        i = sim["exit_idx"] + 1

    candidates_df = pd.DataFrame(candidates)
    if len(candidates_df) > 0:
        candidates_df["entry_time"] = pd.to_datetime(candidates_df["entry_time"], utc=True)
        candidates_df["exit_time"] = pd.to_datetime(candidates_df["exit_time"], utc=True)
        candidates_df = candidates_df.sort_values(["entry_time", "exit_time"]).reset_index(drop=True)

    no_fill_df = pd.DataFrame(no_fill_log)
    if len(no_fill_df) > 0:
        no_fill_df["signal_time"] = pd.to_datetime(no_fill_df["signal_time"], utc=True)
        no_fill_df = no_fill_df.sort_values("signal_time").reset_index(drop=True)

    total_candidates = len(candidates_df) + len(no_fill_df)
    if total_candidates > 0:
        fill_rate = len(candidates_df) / total_candidates * 100
        print(f"\n{symbol} fill 통계:")
        print(f"  전체 시그널: {total_candidates}")
        print(f"  체결 (filled): {len(candidates_df)} ({fill_rate:.1f}%)")
        print(f"  미체결 (no_fill): {len(no_fill_df)} ({100-fill_rate:.1f}%)")

    if skip_reasons:
        print(f"\n{symbol} filter skips TOP 5:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"  {reason}: {count}")

    return {
        "symbol": symbol,
        "df_h4": df_struct,
        "df_h1": df_h1,
        "candidates": candidates_df,
        "no_fill": no_fill_df,
    }


# =========================================================
# EXECUTION PROXY
# =========================================================
def apply_execution_model_to_trade(row, qty):
    symbol = row["symbol"]
    side = row["side"]
    base_entry = float(row["fill_entry"])
    requested_qty = float(qty)
    requested_notional = requested_qty * base_entry

    threshold_usdt = DIRECT_ENTRY_THRESHOLD_USDT[symbol]
    slip_pct = SLIPPAGE_LIMIT_PCT[symbol] / 100.0
    max_tranches = SPLIT_MAX_TRANCHES[symbol]

    if requested_notional <= threshold_usdt:
        return {
            "fill_qty": requested_qty,
            "avg_entry": base_entry,
            "entry_cost_mode": "direct_under_threshold",
            "slippage_applied_pct": 0.0,
            "split_tranches_used": 1,
            "requested_notional": requested_notional,
            "effective_notional": requested_notional,
        }

    first_qty = threshold_usdt / base_entry
    first_qty = min(first_qty, requested_qty)
    remaining_qty = max(0.0, requested_qty - first_qty)

    tranche_count = min(max_tranches, len(TRANCHE_SLIPPAGE_WEIGHTS))
    tranche_weights = TRANCHE_SLIPPAGE_WEIGHTS[:tranche_count]

    if remaining_qty <= 0:
        return {
            "fill_qty": requested_qty,
            "avg_entry": base_entry,
            "entry_cost_mode": "threshold_exact",
            "slippage_applied_pct": 0.0,
            "split_tranches_used": 1,
            "requested_notional": requested_notional,
            "effective_notional": requested_notional,
        }

    tranche_qty = remaining_qty / tranche_count
    notional_acc = first_qty * base_entry
    qty_acc = first_qty
    weighted_slippage_pct_sum = 0.0

    for w in tranche_weights:
        tranche_fill_entry = base_entry * (1 + slip_pct * w) if side == "long" else base_entry * (1 - slip_pct * w)
        notional_acc += tranche_qty * tranche_fill_entry
        qty_acc += tranche_qty
        weighted_slippage_pct_sum += slip_pct * w

    avg_entry = notional_acc / qty_acc if qty_acc > 0 else base_entry
    avg_slippage_pct = weighted_slippage_pct_sum / tranche_count if tranche_count > 0 else 0.0

    return {
        "fill_qty": requested_qty,
        "avg_entry": avg_entry,
        "entry_cost_mode": "orderbook_split_proxy",
        "slippage_applied_pct": avg_slippage_pct * 100.0,
        "split_tranches_used": 1 + tranche_count,
        "requested_notional": requested_notional,
        "effective_notional": qty_acc * avg_entry,
    }


def execute_and_resimulate_trade(row, qty, df_h4):
    exec_info = apply_execution_model_to_trade(row, qty)

    avg_entry = float(exec_info["avg_entry"])
    fill_qty = float(exec_info["fill_qty"])
    entry_idx = int(row["entry_idx"])
    sl = float(row["sl"])

    sim = simulate_trade_with_plan_runner_no_time_exit(
        df_local=df_h4, entry_idx=entry_idx, side=row["side"],
        entry=avg_entry, sl=sl, qty=fill_qty, fee_rate=FEE_RATE,
        grade=row["grade"], plan=get_tp_plan(row["expansion_state"]),
        use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE,
    )

    risk_per_unit_exec = abs(avg_entry - sl)
    actual_risk_amount = risk_per_unit_exec * fill_qty

    return {
        "avg_entry": avg_entry,
        "fill_qty": fill_qty,
        "risk_per_unit_exec": risk_per_unit_exec,
        "actual_risk_amount": actual_risk_amount,
        "net_pnl": sim["net_pnl"],
        "r_multiple": sim["r_multiple"],
        "entry_cost_mode": exec_info["entry_cost_mode"],
        "slippage_applied_pct": exec_info["slippage_applied_pct"],
        "split_tranches_used": exec_info["split_tranches_used"],
        "requested_notional": exec_info["requested_notional"],
        "effective_notional": exec_info["effective_notional"],
        "sim_result": sim,
    }


print("Stage 1 Part 2.5/3 loaded: candidate generation (REFINE 제거) + execution")


# =========================================================
# ★★★ SIMULATION (Stage 1: v19b_norefine_rpboost) ★★★
# =========================================================
def simulate_scenario_v19b_rpboost(scenario, candidates_dict, risk_multiplier=1.0):
    assets_cfg = scenario["assets"]
    enabled_symbols = [s for s, cfg in assets_cfg.items() if cfg.get("enabled", True)]

    all_candidates = []
    for s in enabled_symbols:
        if s in candidates_dict and len(candidates_dict[s]["candidates"]) > 0:
            all_candidates.append(candidates_dict[s]["candidates"].copy())

    if len(all_candidates) == 0:
        raise ValueError(f"No candidates found for {scenario['name']}")

    cands = pd.concat(all_candidates, ignore_index=True)
    cands = cands.sort_values(["entry_time", "exit_time", "symbol"]).reset_index(drop=True)

    first_ts = cands["entry_time"].min()
    deposit_df = make_deposit_schedule(first_ts, MONTHLY_DEPOSIT_USDT, NUM_MONTHLY_DEPOSITS)

    balance = INITIAL_BALANCE_USDT
    deposit_idx = 0

    open_positions = {}
    executed_trades = []
    skipped_entries = []
    equity_points = []

    phase_transitions = []
    excess_log = []
    last_phase = get_current_phase(balance)
    cumulative_excess_usdt = 0.0

    def handle_phase_and_excess(cur_time, note=""):
        nonlocal balance, last_phase, cumulative_excess_usdt

        new_phase = get_current_phase(balance)

        if new_phase != last_phase:
            phase_transitions.append({
                "time": cur_time,
                "from_phase": last_phase,
                "to_phase": new_phase,
                "balance_usdt": balance,
                "note": note,
            })
            last_phase = new_phase

        if new_phase == "B":
            balance, excess = cap_and_extract_excess(balance)
            if excess > 0:
                cumulative_excess_usdt += excess
                excess_log.append({
                    "time": cur_time,
                    "excess_usdt": excess,
                    "cumulative_excess_usdt": cumulative_excess_usdt,
                    "note": note,
                })

    event_times = sorted(set(
        cands["entry_time"].tolist() +
        cands["exit_time"].tolist() +
        deposit_df["deposit_time"].tolist()
    ))

    entry_map = {}
    exit_map = {}
    for idx, row in cands.iterrows():
        entry_map.setdefault(row["entry_time"], []).append((idx, row.to_dict()))
        exit_map.setdefault(row["exit_time"], []).append((idx, row.to_dict()))

    for current_time in event_times:
        prev_balance = balance
        balance, deposit_idx = apply_pending_deposits(balance, current_time, deposit_df, deposit_idx)
        if balance != prev_balance:
            handle_phase_and_excess(current_time, note="deposit")

        if current_time in exit_map:
            for idx, row in exit_map[current_time]:
                trade_id = idx
                if trade_id not in open_positions:
                    continue
                pos = open_positions.pop(trade_id)
                balance += pos["net_pnl"]
                pos["balance_after_exit"] = balance
                pos["phase_at_exit"] = get_current_phase(balance)
                executed_trades.append(pos)
                handle_phase_and_excess(current_time, note=f"trade_exit:{pos['symbol']}")

        equity_points.append({
            "time": current_time,
            "equity": balance,
            "cumulative_excess": cumulative_excess_usdt,
            "phase": last_phase,
        })

        if current_time in entry_map:
            for idx, row in entry_map[current_time]:
                symbol = row["symbol"]
                if symbol not in assets_cfg:
                    continue
                if not assets_cfg[symbol].get("enabled", True):
                    continue

                # ⭐ 단일 포지션 (symbol_already_open)
                symbol_open = any([p["symbol"] == symbol for p in open_positions.values()])
                if symbol_open:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": "symbol_already_open",
                        "phase_at_entry": last_phase,
                    })
                    continue

                current_phase_for_entry = get_current_phase(balance)
                risk_pct_base = get_phase_risk_pct(current_phase_for_entry, symbol)

                # ⭐⭐ Stage 4E: Tier / RP 계산은 기존 로직도 돌려서 로그용으로만 저장
                pre_total_v = int(row.get("pre_entry_total", 0)) if pd.notna(row.get("pre_entry_total", 0)) else 0
                sweep_v = int(row.get("pre_entry_sweep", 0)) if pd.notna(row.get("pre_entry_sweep", 0)) else 0
                score_v = float(row.get("score", 0))
                wick_v = row.get("wick_ratio_5", None)
                if pd.isna(wick_v): wick_v = None
                rp_v = int(row.get("run_potential", 0)) if pd.notna(row.get("run_potential", 0)) else 0

                # 기존 tier 로직 호출 (로그용)
                tier_label_legacy, _tier_mult_legacy, rp_action = classify_tier_v19b_rp_boost(
                    pre_total_v, sweep_v, score_v, wick_v, rp_v
                )

                # 12 atomic 재계산 (Stage 4D 와 동일 로직)
                _struct_reasons_raw = str(row.get("structure_reasons_raw", row.get("reasons", "")))
                _atr_at_entry = float(row.get("atr_at_entry", 0.0)) if pd.notna(row.get("atr_at_entry", 0.0)) else 0.0
                _df_struct_here = candidates_dict[symbol].get("df_h4")
                if _df_struct_here is None:
                    _atoms_final = {
                        "a_sweep":            bool(row.get("tag_sweep", False)),
                        "a_volume":           bool(row.get("tag_volume", False)),
                        "a_pre_total_ge4":    (pre_total_v >= 4),
                        "a_sweep_count_2_4":  (2 <= sweep_v <= 4),
                        "a_score_ge13":       (score_v >= 13.0),
                        "a_wick_le_q1":       (wick_v is not None and not pd.isna(wick_v) and wick_v <= WICK_RATIO_5_Q1_THRESHOLD),
                        "a_pre_total_ge1":    (pre_total_v >= 1),
                        "a_trend_align":      False,
                        "a_mss":              ("bull_mss" in _struct_reasons_raw) or ("bear_mss" in _struct_reasons_raw),
                        "a_fvg":              ("valid_bull_fvg" in _struct_reasons_raw) or ("valid_bear_fvg" in _struct_reasons_raw),
                        "a_overlap":          ("bull_ob_fvg_overlap" in _struct_reasons_raw) or ("bear_ob_fvg_overlap" in _struct_reasons_raw),
                        "a_room":             False,
                    }
                else:
                    try:
                        _entry_ts = row["entry_time"]
                        _match = _df_struct_here.index[_df_struct_here["timestamp"] == _entry_ts]
                        if len(_match) > 0:
                            _entry_idx_sim = int(_match[0])
                            _zone_created_idx = int(row.get("zone_created_idx", _entry_idx_sim))
                            _atoms_final = compute_trade_tags(
                                df_struct=_df_struct_here,
                                entry_idx=_entry_idx_sim,
                                zone_created_idx=_zone_created_idx,
                                zone_low=float(row["entry"]) - 1e-9,
                                zone_high=float(row["entry"]) + 1e-9,
                                side=row["side"],
                                pre_total=pre_total_v,
                                sweep_count=sweep_v,
                                score=score_v,
                                wick_ratio_5=wick_v,
                                structure_reasons=_struct_reasons_raw,
                                atr_val=_atr_at_entry,
                            )
                        else:
                            raise ValueError("entry_ts match fail")
                    except Exception:
                        _atoms_final = {
                            "a_sweep":            bool(row.get("tag_sweep", False)),
                            "a_volume":           bool(row.get("tag_volume", False)),
                            "a_pre_total_ge4":    (pre_total_v >= 4),
                            "a_sweep_count_2_4":  (2 <= sweep_v <= 4),
                            "a_score_ge13":       (score_v >= 13.0),
                            "a_wick_le_q1":       (wick_v is not None and not pd.isna(wick_v) and wick_v <= WICK_RATIO_5_Q1_THRESHOLD),
                            "a_pre_total_ge1":    (pre_total_v >= 1),
                            "a_trend_align":      False,
                            "a_mss":              ("bull_mss" in _struct_reasons_raw) or ("bear_mss" in _struct_reasons_raw),
                            "a_fvg":              ("valid_bull_fvg" in _struct_reasons_raw) or ("valid_bear_fvg" in _struct_reasons_raw),
                            "a_overlap":          ("bull_ob_fvg_overlap" in _struct_reasons_raw) or ("bear_ob_fvg_overlap" in _struct_reasons_raw),
                            "a_room":             False,
                        }

                # ⭐⭐⭐ Stage 4E: 신규 Tier 판정 ⭐⭐⭐
                tier_4e = classify_tier_stage4e(_atoms_final)
                tier_mult_4e = get_tier_risk_mult_4e(tier_4e)
                
                # Skip 조건 체크
                if tier_mult_4e <= 0.0:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol,
                        "reason": f"stage4e_skip_{tier_4e}_out_behavior_{OUT_BEHAVIOR}",
                        "tier_label_4e": tier_4e,
                        "tier_label_legacy": tier_label_legacy,
                        "rp_action": rp_action,
                        "run_potential": rp_v,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue
                
                # RP mult 적용 (Stage 4D 발견: RP0 만 특별)
                rp_mult_4e = RP_MULT_4E.get(rp_v, 1.0)
                
                # 최종 risk 계산 (Stage 4E 체계)
                risk_pct = risk_pct_base * tier_mult_4e * rp_mult_4e * risk_multiplier
                effective_notional_cap = get_tier_cap_4e(tier_4e)
                
                # 하위 호환용 변수
                tier_label = tier_4e
                tier_mult  = tier_mult_4e
                sa_cap_tag = f"tier_{tier_4e}_rp{rp_v}"

                qty, risk_per_unit, notional = calc_position_size(
                    balance=balance, risk_pct=risk_pct, entry=row["entry"], sl=row["sl"],
                    fee_rate=FEE_RATE, max_notional_mult=effective_notional_cap
                )

                if qty is None:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": "size_invalid",
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                exec_adj = execute_and_resimulate_trade(
                    row=row, qty=qty, df_h4=candidates_dict[symbol]["df_h4"],
                )

                sim_exec = exec_adj["sim_result"]

                open_positions[idx] = {
                    "scenario_name": scenario["name"],
                    "execution_model": EXECUTION_SPLIT_PROXY,
                    "strategy_variant": "v19b_norefine_rpboost_9coins",
                    "risk_multiplier": risk_multiplier,   # ⭐ 기록
                    "effective_notional_cap": effective_notional_cap,  # ⭐
                    "sa_cap_tag": sa_cap_tag,              # ⭐
                    "symbol": symbol,
                    "entry_time": row["entry_time"],
                    "exit_time": sim_exec["exit_time"],
                    "side": row["side"],
                    "entry": row["entry"],
                    "fill_entry": row["fill_entry"],
                    "fill_vs_refined_pct": row["fill_vs_refined_pct"],
                    "avg_entry_exec": exec_adj["avg_entry"],
                    "sl": row["sl"],
                    "qty": exec_adj["fill_qty"],
                    "notional": exec_adj["effective_notional"],
                    "requested_notional": exec_adj["requested_notional"],
                    "risk_pct_requested": risk_pct,
                    "risk_pct_base": risk_pct_base,
                    "actual_risk_amount": exec_adj["actual_risk_amount"],
                    "risk_per_unit_exec": exec_adj["risk_per_unit_exec"],
                    "r_multiple": exec_adj["r_multiple"],
                    "net_pnl": exec_adj["net_pnl"],
                    "result": sim_exec["result"],
                    "exit_reason": sim_exec["exit_reason"],
                    "hold_bars": sim_exec["hold_bars"],
                    "score": row["score"],
                    "grade": row["grade"],
                    "run_potential": row["run_potential"],
                    "rp_action": rp_action,                # ⭐ Stage 1 신규
                    "tier": tier_label,
                    "tier_mult": tier_mult,                # final = base × rp
                    "pre_entry_total": pre_total_v,
                    "pre_entry_sweep": sweep_v,
                    "wick_ratio_5": wick_v if wick_v is not None else np.nan,
                    "tp_plan_name": row["tp_plan_name"],
                    "expansion_state": row["expansion_state"],
                    # ⭐⭐ Stage 4E: 신규 Tier 정보
                    "tier_4e":         tier_4e,
                    "tier_mult_4e":    tier_mult_4e,
                    "rp_mult_4e":      rp_mult_4e,
                    "out_behavior":    OUT_BEHAVIOR,
                    # ⭐⭐ 12 atomic (Stage 4D 로직 그대로)
                    "a_sweep":            bool(_atoms_final.get("a_sweep", False)),
                    "a_volume":           bool(_atoms_final.get("a_volume", False)),
                    "a_pre_total_ge4":    bool(_atoms_final.get("a_pre_total_ge4", False)),
                    "a_sweep_count_2_4":  bool(_atoms_final.get("a_sweep_count_2_4", False)),
                    "a_score_ge13":       bool(_atoms_final.get("a_score_ge13", False)),
                    "a_wick_le_q1":       bool(_atoms_final.get("a_wick_le_q1", False)),
                    "a_pre_total_ge1":    bool(_atoms_final.get("a_pre_total_ge1", False)),
                    "a_trend_align":      bool(_atoms_final.get("a_trend_align", False)),
                    "a_mss":              bool(_atoms_final.get("a_mss", False)),
                    "a_fvg":              bool(_atoms_final.get("a_fvg", False)),
                    "a_overlap":          bool(_atoms_final.get("a_overlap", False)),
                    "a_room":             bool(_atoms_final.get("a_room", False)),
                    # 하위 호환
                    "tag_sweep":       bool(_atoms_final.get("a_sweep", False)),
                    "tag_volume":      bool(_atoms_final.get("a_volume", False)),
                    "pass_vol": row.get("pass_vol", False),
                    "pass_sweep": row.get("pass_sweep", False),
                    "pass_d1": row.get("pass_d1", False),
                    "pass_pull": row.get("pass_pull", False),
                    "pass_atr": row.get("pass_atr", False),
                    "pass_combo": row.get("pass_combo", "none"),
                    "pass_count": row.get("pass_count", 0),
                    "filter_groups_active": row.get("filter_groups_active", False),
                    "entry_refined": row["entry_refined"],
                    "entry_improved_by": row["entry_improved_by"],
                    "max_rr_seen": sim_exec["max_rr_seen"],
                    "runner_max_rr_seen": sim_exec["runner_max_rr_seen"],
                    "runner_candidate_2of3": sim_exec["runner_candidate_2of3"],
                    "post_2of3_apply_ok": sim_exec["post_2of3_apply_ok"],
                    "runner_protected": sim_exec["runner_protected"],
                    "proxy_runner": sim_exec["proxy_runner"],
                    "balance_at_entry": balance,
                    "phase_at_entry": current_phase_for_entry,
                    "entry_cost_mode": exec_adj["entry_cost_mode"],
                    "slippage_applied_pct": exec_adj["slippage_applied_pct"],
                    "split_tranches_used": exec_adj["split_tranches_used"],
                }

    for trade_id, pos in list(open_positions.items()):
        balance += pos["net_pnl"]
        pos["balance_after_exit"] = balance
        pos["phase_at_exit"] = get_current_phase(balance)
        executed_trades.append(pos)
        handle_phase_and_excess(pos.get("exit_time", event_times[-1]), note="residual_close")

    trades_df = pd.DataFrame(executed_trades)
    skipped_df = pd.DataFrame(skipped_entries)
    equity_df = pd.DataFrame(equity_points).drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    phase_df = pd.DataFrame(phase_transitions)
    excess_df = pd.DataFrame(excess_log)

    if len(equity_df) > 0:
        equity_df["total_assets"] = equity_df["equity"] + equity_df["cumulative_excess"]
        equity_df["cummax"] = equity_df["total_assets"].cummax()
        equity_df["dd"] = equity_df["total_assets"] - equity_df["cummax"]
        equity_df["dd_pct"] = np.where(equity_df["cummax"] > 0, equity_df["dd"] / equity_df["cummax"] * 100, 0)

    if len(trades_df) > 0:
        trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
        trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"], utc=True)
        trades_df["month"] = trades_df["exit_time"].dt.strftime("%Y-%m")

    if len(skipped_df) > 0:
        skipped_df["entry_time"] = pd.to_datetime(skipped_df["entry_time"], utc=True)

    return {
        "scenario_name": scenario["name"],
        "execution_model": EXECUTION_SPLIT_PROXY,
        "strategy_variant": "v19b_norefine_rpboost_9coins",
        "risk_multiplier": risk_multiplier,   # ⭐
        "trades": trades_df,
        "skipped": skipped_df,
        "equity": equity_df,
        "phase_transitions": phase_df,
        "excess_log": excess_df,
        "final_balance_usdt": balance,
        "final_balance_krw": balance * KRW_PER_USDT,
        "final_cumulative_excess_usdt": cumulative_excess_usdt,
        "final_cumulative_excess_krw": cumulative_excess_usdt * KRW_PER_USDT,
        "final_total_assets_krw": (balance + cumulative_excess_usdt) * KRW_PER_USDT,
        "deposit_df": deposit_df,
        "first_trade_time": first_ts,
    }


# =========================================================
# REPORTING
# =========================================================
def build_monthly_pnl_krw(trades_df, deposit_df):
    if len(trades_df) == 0:
        return pd.DataFrame(columns=["month", "net_pnl_usdt", "net_pnl_krw", "trades"])
    m = trades_df.groupby("month", as_index=False).agg(
        net_pnl_usdt=("net_pnl", "sum"),
        trades=("symbol", "count"),
        avg_r=("r_multiple", "mean"),
        winrate_pct=("net_pnl", lambda s: (s > 0).mean() * 100),
    )
    m["net_pnl_krw"] = m["net_pnl_usdt"] * KRW_PER_USDT
    m = m.sort_values("month").reset_index(drop=True)
    m["rolling_3m_avg_krw"] = m["net_pnl_krw"].rolling(
        window=RETIREMENT_WINDOW_MONTHS, min_periods=RETIREMENT_WINDOW_MONTHS
    ).mean()
    return m


def find_retirement_month(monthly_df):
    if len(monthly_df) == 0:
        return None
    qualified = monthly_df[monthly_df["rolling_3m_avg_krw"] >= RETIREMENT_MONTHLY_TARGET_KRW]
    if len(qualified) == 0:
        return None
    return qualified.iloc[0]


def print_scenario_summary(result_dict):
    trades_df = result_dict["trades"].copy()
    equity_df = result_dict["equity"].copy()
    phase_df = result_dict["phase_transitions"]
    excess_df = result_dict["excess_log"]

    total_deposit_usdt = INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS
    total_deposit_krw = total_deposit_usdt * KRW_PER_USDT
    final_balance_krw = result_dict["final_balance_krw"]
    final_excess_krw = result_dict["final_cumulative_excess_krw"]
    final_total_assets_krw = result_dict["final_total_assets_krw"]

    trades_count = len(trades_df)
    if trades_count > 0:
        gross_profit = trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"].sum()
        gross_loss = abs(trades_df.loc[trades_df["net_pnl"] < 0, "net_pnl"].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else np.nan
        winrate = (trades_df["net_pnl"] > 0).mean() * 100
        avg_r = trades_df["r_multiple"].mean()
    else:
        pf = winrate = avg_r = np.nan

    mdd = equity_df["dd_pct"].min() if len(equity_df) > 0 else np.nan
    net_profit_krw = final_total_assets_krw - total_deposit_krw
    return_pct = net_profit_krw / total_deposit_krw * 100 if total_deposit_krw > 0 else np.nan

    print("\n" + "=" * 140)
    print(f"🎯 {result_dict['scenario_name']} | {result_dict.get('strategy_variant')}")
    print("=" * 140)
    print(f"\n📊 자본 현황")
    print(f"  총 납입 원금         : {total_deposit_krw:>18,.0f} KRW")
    print(f"  최종 Balance (cap)    : {final_balance_krw:>18,.0f} KRW (Target {TARGET_BALANCE_KRW:,.0f})")
    print(f"  누적 Excess (릴레이용) : {final_excess_krw:>18,.0f} KRW")
    print(f"  총 자산 (합계)        : {final_total_assets_krw:>18,.0f} KRW")
    print(f"  ──────────────────────────────────────────────")
    print(f"  순이익               : {net_profit_krw:>18,.0f} KRW ({return_pct:>10,.1f}%)")

    print(f"\n📈 거래 통계")
    print(f"  총 거래 수: {trades_count}")
    print(f"  PF: {pf:.3f}" if pd.notna(pf) else "  PF: N/A")
    print(f"  승률: {winrate:.2f}%" if pd.notna(winrate) else "  승률: N/A")
    print(f"  평균 R: {avg_r:.3f}" if pd.notna(avg_r) else "  평균 R: N/A")
    print(f"  MDD: {mdd:.2f}%" if pd.notna(mdd) else "  MDD: N/A")
    print(f"  threshold: {WICK_RATIO_5_Q1_THRESHOLD}")
    rp_table_str = " | ".join([f"rp{k}={v}" for k, v in sorted(RP_TIER_MULT_TABLE.items())])
    print(f"  RP table: {rp_table_str} | else=skip")

    print(f"\n⏱  Phase 전환 이력")
    if len(phase_df) > 0:
        for _, r in phase_df.iterrows():
            t_str = pd.Timestamp(r["time"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {t_str} | {r['from_phase']} → {r['to_phase']} | balance ${r['balance_usdt']:>12,.0f} | {r['note']}")
    else:
        print("  (Phase 전환 없음 — 전 구간 Phase A)")

    if len(excess_df) > 0:
        print(f"\n🔄 Excess 이벤트")
        print(f"  총 이벤트 수      : {len(excess_df)}")
        print(f"  누적 Excess      : ${result_dict['final_cumulative_excess_usdt']:,.0f} ({final_excess_krw:,.0f} KRW)")

    if "tier" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🎲 티어별 분포 (실제 진입 기준)")
        tier_stat = trades_df.groupby("tier").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        tier_stat["PF"] = tier_stat["tier"].apply(
            lambda t: (
                trades_df.loc[(trades_df["tier"]==t) & (trades_df["net_pnl"]>0), "net_pnl"].sum() /
                max(abs(trades_df.loc[(trades_df["tier"]==t) & (trades_df["net_pnl"]<0), "net_pnl"].sum()), 1e-9)
            )
        )
        tier_stat["pnl_contribution_%"] = tier_stat["net_pnl_usdt"] / tier_stat["net_pnl_usdt"].sum() * 100
        tier_stat = tier_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3, "pnl_contribution_%": 2})
        print(tier_stat.to_string(index=False))

    # ⭐ Stage 1 신규: run_potential 별 분포
    if "run_potential" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🚀 run_potential 별 분포 (RP_BOOST 필터 후)")
        rp_stat = trades_df.groupby("run_potential").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        rp_stat["PF"] = rp_stat["run_potential"].apply(
            lambda r: (
                trades_df.loc[(trades_df["run_potential"]==r) & (trades_df["net_pnl"]>0), "net_pnl"].sum() /
                max(abs(trades_df.loc[(trades_df["run_potential"]==r) & (trades_df["net_pnl"]<0), "net_pnl"].sum()), 1e-9)
            )
        )
        rp_stat["pnl_contribution_%"] = rp_stat["net_pnl_usdt"] / rp_stat["net_pnl_usdt"].sum() * 100
        rp_stat = rp_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3, "pnl_contribution_%": 2})
        print(rp_stat.to_string(index=False))

    # ⭐ Stage 1 신규: rp_action 별 분포
    if "rp_action" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🎚 RP action 별 분포 (boost/pass)")
        rpa_stat = trades_df.groupby("rp_action").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        rpa_stat["PF"] = rpa_stat["rp_action"].apply(
            lambda a: (
                trades_df.loc[(trades_df["rp_action"]==a) & (trades_df["net_pnl"]>0), "net_pnl"].sum() /
                max(abs(trades_df.loc[(trades_df["rp_action"]==a) & (trades_df["net_pnl"]<0), "net_pnl"].sum()), 1e-9)
            )
        )
        rpa_stat = rpa_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3})
        print(rpa_stat.to_string(index=False))

    skipped_df = result_dict.get("skipped", pd.DataFrame())
    if len(skipped_df) > 0 and "reason" in skipped_df.columns:
        rp_skip = skipped_df[skipped_df["reason"].str.contains("rp_skip", na=False)]
        tier_d_skip = skipped_df[skipped_df["reason"].str.contains("tier_d_skip", na=False)]
        print(f"\n🚫 스킵 사유 분포")
        top_reasons = skipped_df["reason"].value_counts().head(10)
        for reason, count in top_reasons.items():
            print(f"  {reason}: {count}")
        print(f"  └─ RP 스킵 총 {len(rp_skip)} / 티어D 스킵 총 {len(tier_d_skip)}")

    monthly = build_monthly_pnl_krw(trades_df, result_dict["deposit_df"])
    print(f"\n📅 월별 수익 (단위: 만원)")
    if len(monthly) > 0:
        show = monthly.copy()
        show["net_pnl_man"] = (show["net_pnl_krw"] / 1e4).round(0).astype(int)
        show["rolling_3m_man"] = show["rolling_3m_avg_krw"].apply(
            lambda x: int(round(x / 1e4)) if pd.notna(x) else None
        )
        cols = ["month", "trades", "net_pnl_man", "rolling_3m_man", "avg_r", "winrate_pct"]
        print(show[cols].to_string(index=False))

    retirement = find_retirement_month(monthly)
    target_man = RETIREMENT_MONTHLY_TARGET_KRW / 1e4
    print(f"\n🏠 퇴사 조건 검증")
    print(f"  기준: 최근 {RETIREMENT_WINDOW_MONTHS}개월 평균 월 수익 ≥ {target_man:,.0f}만원 (크립토 단독)")
    if retirement is not None:
        retirement_pnl = retirement["rolling_3m_avg_krw"] / 1e4
        print(f"  ✅ 달성! {retirement['month']} ({RETIREMENT_WINDOW_MONTHS}M 평균 {retirement_pnl:,.0f}만원)")
        idx = monthly[monthly["month"] == retirement["month"]].index[0]
        months_taken = idx + 1
        print(f"  → 백테스트 시작부터 {months_taken}개월 만에 퇴사 조건 달성")
    else:
        print(f"  ❌ 미달성 (전 기간 3M 평균 미만)")

    return monthly


def plot_equity(result_dict):
    eq = result_dict["equity"].copy()
    phase_df = result_dict["phase_transitions"]
    if len(eq) == 0:
        return
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)

    ax = axes[0]
    ax.plot(eq["time"], eq["equity"] * KRW_PER_USDT / 1e8,
            label="Engine Balance (cap)", color="#1f77b4", linewidth=1.5)
    ax.plot(eq["time"], eq["total_assets"] * KRW_PER_USDT / 1e8,
            label="Total Assets (+ Excess)", color="#2ca02c", linewidth=2.0)
    ax.axhline(TARGET_BALANCE_KRW / 1e8, color="red", linestyle="--",
               alpha=0.6, label=f"Target {TARGET_BALANCE_KRW/1e8:.2f}")
    for _, r in phase_df.iterrows():
        ax.axvline(r["time"], color="orange", linestyle=":", alpha=0.5)
    ax.set_title(f"{result_dict['scenario_name']} - Equity Curve (KRW 100M)", fontsize=13)
    ax.set_ylabel("KRW 100M")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.fill_between(eq["time"], eq["dd_pct"], 0, color="red", alpha=0.4)
    ax.set_title("Drawdown (%) - Total Assets basis", fontsize=13)
    ax.set_ylabel("DD %")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


print("Stage 1 Part 3/3 loaded: simulation + report")


# =========================================================
# ★★★ 셀 1: 데이터 다운로드 (병렬 처리) ★★★
# =========================================================
SYMBOLS_TO_PREPARE = sorted(list(SCENARIO_MULTI["assets"].keys()))

# =========================================================
# 🔍 실행 환경 체크
# =========================================================
import os as _os_env
try:
    import psutil as _psutil
    _ram_gb = _psutil.virtual_memory().total / 1e9
except ImportError:
    _ram_gb = None

_cpu_count = _os_env.cpu_count() or 2
_in_colab = "COLAB_GPU" in _os_env.environ or "google.colab" in str(_os_env.environ.get("PATH", ""))

print("=" * 75)
print("🔍 실행 환경 (Stage 2: v19b_norefine_rpboost / 9코인)")
print("=" * 75)
print(f"  환경: {'Google Colab' if _in_colab else 'Local'}")
print(f"  CPU 코어: {_cpu_count}")
if _ram_gb:
    print(f"  RAM: {_ram_gb:.1f} GB")
print("=" * 75)
print()

# =========================================================
# 병렬 처리 유틸리티
# =========================================================
import time as _time_module

def _parallel_map(func, items, n_workers=None, task_name="task", io_bound=False):
    """
    joblib(loky) → ProcessPoolExecutor → ThreadPool → 순차 fallback
    io_bound=True: Thread (네트워크 I/O 용)
    io_bound=False: Process (CPU 연산용)
    """
    n = len(items)
    if n_workers is None:
        if io_bound:
            n_workers = min(n, 9)
        else:
            n_workers = min(n, _os_env.cpu_count() or 2)
    else:
        if not io_bound:
            n_workers = min(n_workers, _os_env.cpu_count() or 2)

    t0 = _time_module.time()
    results = None
    errors = []

    if io_bound:
        try:
            from concurrent.futures import ThreadPoolExecutor
            print(f"  🔀 ThreadPool I/O 병렬 ({n_workers} threads, {n} {task_name})")
            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e:
            print(f"  ⚠️ Thread 실패, 순차 처리")
            results = [func(item) for item in items]
        elapsed = _time_module.time() - t0
        print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
        return results

    # CPU bound
    try:
        from joblib import Parallel, delayed
        print(f"  🔀 joblib(loky) CPU 병렬 ({n_workers} workers, {n} {task_name})")
        results = Parallel(n_jobs=n_workers, backend="loky", verbose=0)(
            delayed(func)(item) for item in items
        )
    except Exception as e_joblib:
        errors.append(("joblib", e_joblib))
        try:
            from concurrent.futures import ProcessPoolExecutor
            print(f"  🔀 ProcessPoolExecutor fallback ({n_workers} workers)")
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e_pool:
            errors.append(("ProcessPool", e_pool))
            print(f"  ⚠️ 병렬 모두 실패, 순차 처리")
            for name, e in errors:
                print(f"     - {name}: {type(e).__name__}: {str(e)[:100]}")
            results = [func(item) for item in items]

    elapsed = _time_module.time() - t0
    print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
    return results


# 데이터 다운로드 (병렬)
print("=" * 75)
print(f"📥 데이터 다운로드 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

raw_results = _parallel_map(
    download_symbol_data, SYMBOLS_TO_PREPARE,
    task_name="심볼 다운로드", io_bound=True,
)
raw_data = dict(zip(SYMBOLS_TO_PREPARE, raw_results))

print("\n✅ 데이터 다운로드 완료.")


# =========================================================
# ★★★ 셀 2: indicators + candidates (병렬 처리) ★★★
# =========================================================
H4_PIVOT_SWING_LEN = 30
H4_MSS_LOOKBACK = 80
H4_OB_LOOKBACK = 15
H4_PD_LOOKBACK = 1620
H4_MARKET_STATE_BARS = 360
H4_ZONE_MAX_AGE = 30

# Stage 1: REFINE 제거 설정 유지
LONG_BASE_ENTRY_FRAC = 0.10
SHORT_BASE_ENTRY_FRAC = 0.90

USE_D1_TREND_FILTER      = False
USE_LIQUIDITY_SWEEP_CONF = False
USE_VOLUME_FILTER        = True
USE_PULLBACK_DEPTH       = False
USE_ATR_FILTER           = False

print("=" * 75)
print(f"🔧 indicators + 구조물 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

def _apply_indicators_single(sym):
    return sym, apply_indicators_and_build(raw_data[sym])

try:
    prepared_results = _parallel_map(
        _apply_indicators_single, SYMBOLS_TO_PREPARE,
        task_name="indicators", io_bound=False,
    )
    prepared_data = dict(prepared_results)
except Exception as e:
    print(f"  ⚠️ indicators 병렬 실패: {e}, 순차 처리")
    prepared_data = {}
    for sym in SYMBOLS_TO_PREPARE:
        prepared_data[sym] = apply_indicators_and_build(raw_data[sym])

print()
print("=" * 75)
print(f"🎯 candidates 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

def _generate_candidates_single(sym):
    return sym, generate_candidates_from_prepared(prepared_data[sym])


# =========================================================
# ★★★ Stage 4E: candidates 생성 (Tier from Atoms) ★★★
# =========================================================
print()
print("=" * 75)
print("[Stage 4E v2] candidates 생성 — Tier 재설계 + 319 canonical hard-gate")
print("=" * 75)
print("  진입 조건 = MIN_SCORE 7.5 만 (Tier 판정은 simulate 단계)")
print(f"  OUT_BEHAVIOR = {OUT_BEHAVIOR!r}")
print(f"  TIER_RISK_MULT_4E = {TIER_RISK_MULT_4E}")
print(f"  RP_MULT_4E = {RP_MULT_4E}")
print(f"  WIN69 canonical combos: {len(WIN69_CANONICAL_COMBOS)} 개 hard-coded (Tier B 조건)")

USE_FILTER_GROUPS = False
USE_VOLUME_FILTER = False
USE_LIQUIDITY_SWEEP_CONF = False
USE_D1_TREND_FILTER = False
USE_PULLBACK_DEPTH = False
USE_ATR_FILTER = False

try:
    candidates_results_stage4e = _parallel_map(
        _generate_candidates_single, SYMBOLS_TO_PREPARE,
        task_name="candidates Stage 4E", io_bound=False,
    )
    candidates_dict_stage4e = dict(candidates_results_stage4e)
except Exception as e:
    print(f"  candidates 병렬 실패: {e}, 순차 처리")
    candidates_dict_stage4e = {}
    for sym in SYMBOLS_TO_PREPARE:
        candidates_dict_stage4e[sym] = generate_candidates_from_prepared(prepared_data[sym])

total_stage4e = sum(len(candidates_dict_stage4e[s]["candidates"]) for s in SYMBOLS_TO_PREPARE)
print(f"\n  TOTAL candidates (Stage 4E): {total_stage4e}")
print("\n[OK] candidates 생성 완료 (Stage 4E). Tier 4E + RP4E 는 simulate 단계에서 적용됨.")




# =========================================================
# ★★★ 셀 3: 단일 시나리오 백테스트 실행 (Stage 4E) ★★★
# =========================================================
import os
OUTDIR = "stage4e_outputs"
os.makedirs(OUTDIR, exist_ok=True)
print(f"\n[OUTDIR] {os.path.abspath(OUTDIR)}")
print(f"[CONFIG] OUT_BEHAVIOR = {OUT_BEHAVIOR!r}")

STAGE4E_CASE = {
    "name":  "stage4e",
    "label": f"Stage 4E: Tier from Atoms (OUT={OUT_BEHAVIOR})",
    "risk_mult": 1.0,
    "candidates": candidates_dict_stage4e,
}

print()
print("#" * 75)
print(f"# Stage 4E 백테스트 시작: {STAGE4E_CASE['label']}")
print("#" * 75)

res = simulate_scenario_v19b_rpboost(
    scenario=SCENARIO_MULTI,
    candidates_dict=STAGE4E_CASE["candidates"],
    risk_multiplier=STAGE4E_CASE["risk_mult"],
)

monthly_report = print_scenario_summary(res)

prefix = f"stage4e_out_{OUT_BEHAVIOR}"
res["trades"].to_csv(f"{OUTDIR}/{prefix}_trades.csv", index=False)
res["equity"].to_csv(f"{OUTDIR}/{prefix}_equity.csv", index=False)
res["skipped"].to_csv(f"{OUTDIR}/{prefix}_skipped.csv", index=False)
monthly_report.to_csv(f"{OUTDIR}/{prefix}_monthly.csv", index=False)

# ─── 기본 summary ───
trades = res["trades"]
eq = res["equity"]
gp = trades[trades['net_pnl']>0]['net_pnl'].sum() if len(trades)>0 else 0
gl = abs(trades[trades['net_pnl']<0]['net_pnl'].sum()) if len(trades)>0 else 0
pf_overall = gp / max(gl, 1e-9)
wr_overall = (trades['net_pnl']>0).mean() * 100 if len(trades)>0 else 0
avgr_overall = trades['r_multiple'].mean() if len(trades)>0 else 0
mdd_overall = eq['dd_pct'].min() if len(eq)>0 else 0

final_total_krw   = res["final_total_assets_krw"]
deposit_krw = (INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS) * KRW_PER_USDT
return_pct = (final_total_krw - deposit_krw) / deposit_krw * 100
qualified = monthly_report[monthly_report['rolling_3m_avg_krw'] >= RETIREMENT_MONTHLY_TARGET_KRW]
retirement_month = qualified.iloc[0]['month'] if len(qualified)>0 else "mi-dalseong"
months_taken = monthly_report[monthly_report['month'] == retirement_month].index[0] + 1 if len(qualified)>0 else None

summary_df = pd.DataFrame([{
    "scenario":  STAGE4E_CASE["name"],
    "label":     STAGE4E_CASE["label"],
    "out_behavior": OUT_BEHAVIOR,
    "trades":    len(trades),
    "win%":      wr_overall,
    "PF":        pf_overall,
    "avg_R":     avgr_overall,
    "MDD%":      mdd_overall,
    "Return_%":  return_pct,
    "retirement":      retirement_month,
    "retirement_months": months_taken if months_taken else "X",
}])
summary_df.to_csv(f"{OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_overall_summary.csv", index=False)

print()
print("=" * 75)
print(f"[Stage 4E | OUT={OUT_BEHAVIOR}] 전체 성과")
print("=" * 75)
print(f"  Trades   : {len(trades)}")
print(f"  Win%     : {wr_overall:.2f}%")
print(f"  PF       : {pf_overall:.3f}")
print(f"  avg_R    : {avgr_overall:.3f}")
print(f"  MDD%     : {mdd_overall:.2f}%")
print(f"  Return%  : {return_pct:.1f}%")
print(f"  retirement : {retirement_month} ({months_taken if months_taken else 'X'}m)")


# =========================================================
# ★★★ Stage 4E: Tier 별 심층 분석 ★★★
# =========================================================
print()
print("#" * 75)
print("# Stage 4E 심층 분석")
print("#" * 75)

tdf = res["trades"].copy()

if len(tdf) == 0:
    print("[WARN] 거래 0건 — 분석 불가")
else:
    for c in ["tier_4e", "tier_mult_4e", "rp_mult_4e"]:
        if c not in tdf.columns:
            tdf[c] = "N/A" if c == "tier_4e" else 1.0

    def _pf_of(sub):
        if len(sub) == 0: return 0.0
        g_p = sub[sub["net_pnl"] > 0]["net_pnl"].sum()
        g_l = abs(sub[sub["net_pnl"] < 0]["net_pnl"].sum())
        return g_p / max(g_l, 1e-9)

    def _stats(sub):
        if len(sub) == 0:
            return {"trades":0, "win_pct":0.0, "avg_R":0.0, "PF":0.0,
                    "total_pnl":0.0, "pnl_per_trade":0.0}
        return {
            "trades":    len(sub),
            "win_pct":   (sub["net_pnl"] > 0).mean() * 100.0,
            "avg_R":     sub["r_multiple"].mean(),
            "PF":        _pf_of(sub),
            "total_pnl":     sub["net_pnl"].sum(),
            "pnl_per_trade": sub["net_pnl"].mean(),
        }

    # ─── [1] Tier 별 분포 ───
    print()
    print("=" * 95)
    print("[1] tier_stage4e_distribution — Tier 별 성과")
    print("=" * 95)
    print(f"{'tier':<8} {'trades':>7} {'win%':>7} {'avg_R':>7} {'PF':>7} "
          f"{'$/trade':>10} {'total $':>14}")
    print("-" * 95)

    tier_order = ["SSS", "SS", "S", "A", "B", "OUT", "SKIP_MSS_POISON"]
    tier_rows = []
    for t in tier_order:
        sub = tdf[tdf["tier_4e"] == t]
        if len(sub) == 0: continue
        st = _stats(sub)
        tier_rows.append({"tier": t, **st})
        print(f"{t:<8} {int(st['trades']):>7} {st['win_pct']:>6.2f}% "
              f"{st['avg_R']:>7.3f} {st['PF']:>7.3f} "
              f"{st['pnl_per_trade']:>10,.0f} {st['total_pnl']:>14,.0f}")

    tier_df = pd.DataFrame(tier_rows).round(4)
    tier_df.to_csv(f"{OUTDIR}/tier_stage4e_distribution_out_{OUT_BEHAVIOR}.csv", index=False)

    # ─── [2] Tier × Side ───
    print()
    print("=" * 95)
    print("[2] tier_x_side — Tier × LONG/SHORT")
    print("=" * 95)
    print(f"{'tier':<8} {'side':<6} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>14}")
    print("-" * 75)

    tx_rows = []
    for t in tier_order:
        sub_t = tdf[tdf["tier_4e"] == t]
        if len(sub_t) == 0: continue
        for side in ["long", "short"]:
            sub = sub_t[sub_t["side"] == side]
            if len(sub) == 0: continue
            st = _stats(sub)
            tx_rows.append({"tier": t, "side": side, **st})
            print(f"{t:<8} {side:<6} {int(st['trades']):>7} {st['win_pct']:>6.2f}% "
                  f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    tx_df = pd.DataFrame(tx_rows).round(4)
    tx_df.to_csv(f"{OUTDIR}/tier_x_side_out_{OUT_BEHAVIOR}.csv", index=False)

    # ─── [3] RP level × Tier ───
    print()
    print("=" * 95)
    print("[3] rp_x_tier — RP 레벨 × Tier (RP0 boost 검증)")
    print("=" * 95)
    print(f"{'tier':<8} {'RP':<4} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>14}")
    print("-" * 75)

    rt_rows = []
    if "run_potential" in tdf.columns:
        for t in tier_order:
            sub_t = tdf[tdf["tier_4e"] == t]
            if len(sub_t) == 0: continue
            for rp in sorted(sub_t["run_potential"].dropna().unique().tolist()):
                sub = sub_t[sub_t["run_potential"] == rp]
                if len(sub) == 0: continue
                st = _stats(sub)
                rt_rows.append({"tier": t, "RP": int(rp), **st})
                print(f"{t:<8} {int(rp):<4} {int(st['trades']):>7} {st['win_pct']:>6.2f}% "
                      f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    rt_df = pd.DataFrame(rt_rows).round(4)
    rt_df.to_csv(f"{OUTDIR}/rp_x_tier_out_{OUT_BEHAVIOR}.csv", index=False)


print()
print("=" * 75)
print(f"[SAVED] Stage 4E 분석 산출물 (OUT={OUT_BEHAVIOR})")
print("=" * 75)
print(f"  {OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_trades.csv")
print(f"  {OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_equity.csv")
print(f"  {OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_skipped.csv")
print(f"  {OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_monthly.csv")
print(f"  {OUTDIR}/stage4e_out_{OUT_BEHAVIOR}_overall_summary.csv")
print(f"  {OUTDIR}/tier_stage4e_distribution_out_{OUT_BEHAVIOR}.csv")
print(f"  {OUTDIR}/tier_x_side_out_{OUT_BEHAVIOR}.csv")
print(f"  {OUTDIR}/rp_x_tier_out_{OUT_BEHAVIOR}.csv")

print()
print("=" * 75)
print("[Stage 4E v2] 실험 완료 (Option C — Hard-coded 319 canonical combos)")
print("=" * 75)
print(f"  OUT_BEHAVIOR: {OUT_BEHAVIOR}")
print(f"  Tier 체계: SSS(2.5x) > SS(2.0x) > S(1.5x) > A(1.3x) > B(1.1x) > OUT")
print(f"  Tier B 조건: 319 canonical Win>=69% union 매칭")
print(f"  RP Boost:  RP0 only (1.5x), RP1~5 = 1.0x")
print("  예상 분포: IN ~696 / OUT ~926 / SKIP_MSS ~2")
print("  다음: OUT_BEHAVIOR 변경하여 재실행 (skip / keep_r1 / keep_r05)")
