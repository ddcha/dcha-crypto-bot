# =========================================================
# smc_4k_layer.py — 공통 4K BOOST15 layer (지수/원자재 재사용 모듈)
# =========================================================
# 둠챠의 크립토 stage 4K BOOST15 system 의 핵심 alpha layer 를
# 자산군 무관하게 import 해서 사용할 수 있도록 분리한 모듈.
#
# 원본: smc_crypto_stage4k_sentiment.py (4413 lines)
# 추출: 4K BOOST15 only (BOOST25/35 제거)
#
# [구성]
#   1. atomic 12 정의 (compute_trade_tags) - 모든 거래에 부착
#   2. WIN69 319 canonical combos + passes_win69_union
#   3. classify_tier_stage4h (atoms_dict, side) - WIN69 IN/OUT 분류
#   4. classify_tier_v19b_rp_boost (pre, sweep, score, wick, rp) - S/A/B/C/D
#   5. is_stage4j_blocked + get_stage4j_extra_mult - GEM/ROOM blocking + booster
#   6. compute_pre_entry_confluence - LTF sweep/fvg/ob 카운트
#   7. compute_wick_ratio_5 - 방향성 꼬리 비율
#   8. apply_sweep_flags - LTF sweep flag 추가
#   9. get_stage4k_sentiment_mult (BOOST15) - 직전 7일 sentiment booster
#  10. compute_sentiment_lookback - 7일 lookback 계산
#  11. ROOM_ONLY_SYMBOL_BLACKLIST + GEM_LONG_ONLY 차단
#
# [Risk 최종 식]
#   risk_pct = base × tier_mult × rp_mult × stage4j_mult × sentiment_mult
#
# [자산군 사용 시 주의]
#   ROOM_ONLY_SYMBOL_BLACKLIST: 크립토용 4 심볼 → 자산군에서는 빈 set
#   GEM_LONG_ONLY: True (크립토 default) → 자산군별 재검토 가능
#   WICK_RATIO_5_Q1_THRESHOLD: 0.2300 (크립토) → 자산군별 재검토 가능
#   atomic 12 효용: 자산군별 다를 수 있음 → atom OR search 로 검증 필요
# =========================================================
from __future__ import annotations
import numpy as np
import pandas as pd

# =========================================================
# CONFIG (4K master 그대로)
# =========================================================
SCENARIO = "BOOST15"                     # BOOST15 only (단순화)

TIER_RISK_S = 3.0
TIER_RISK_A = 1.5
TIER_RISK_B = 0.8
TIER_RISK_C = 0.7
TIER_RISK_D = 0.0
SKIP_TIER_D = True

WICK_RATIO_5_Q1_THRESHOLD = 0.2300       # 자산군 재검토 가능
PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5

# RP boost
RP_TIER_MULT_TABLE = {
    0: 1.5, 1: 1.5,
    2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
    # rp 6+ → not in dict → skip
}

# 4G/4H Tier risk mult (공통)
TIER_RISK_MULT_COMMON = {
    "ALPHA_MAX":    2.0,
    "ALPHA_HIGH":   1.5,
    "ALPHA_MED":    1.2,                 # side-aware override
    "COMPLETE_OUT": 1.0,                 # OUT_BEHAVIOR 따라
    "SKIP_MSS":     0.0,
}

# Side-aware ALPHA_MED
ALPHA_MED_RISK_LONG  = 0.8
ALPHA_MED_RISK_SHORT = 1.2

# RP mult (4H)
RP_MULT_4H = {0: 2.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0}

# OUT 처리
OUT_BEHAVIOR = "skip"

# Tier notional cap
TIER_CAP_4H = {
    "ALPHA_MAX":       999.0,
    "ALPHA_HIGH":      999.0,
    "ALPHA_MED":       3.0,
    "SWEEP_GEM":       3.0,
    "SWEEP_ROOM_FVG":  3.0,
    "SWEEP_ROOM_ONLY": 3.0,
    "COMPLETE_OUT":    3.0,
    "SKIP_MSS":        3.0,
}

# Stage 4I 차단 규칙
GEM_LONG_ONLY = True
ROOM_ONLY_SYMBOL_BLACKLIST: set = set()  # 자산군용 → 빈 set (크립토만 채워짐)

# 4K BOOST15 only
SWEEP_RISK_BY_SCENARIO = {
    "BOOST15": {"SWEEP_GEM": 1.0, "SWEEP_ROOM_FVG": 1.0, "SWEEP_ROOM_ONLY": 1.0},
}

# Sentiment booster
SENTIMENT_LOOKBACK_DAYS = 7
SENTIMENT_MIN_SAMPLES = 2
SENTIMENT_PREV_OFFSET = 7
SENTIMENT_BOOSTER_BY_SCENARIO = {
    "BOOST15": {"BOOST": 1.5, "CUT": 0.5},
}

# Volume / Sweep filter (4K 그대로)
USE_VOLUME_FILTER = True
VOLUME_AVG_WINDOW = 20
VOLUME_SPIKE_MULT = 1.1
SWEEP_LOOKBACK_BARS = 5


# =========================================================
# WIN69 CANONICAL COMBOS (319개, 4K master 그대로)
# =========================================================
# Stage 4D trade analysis 에서 자동 추출 (Win% >= 69.0%, n >= 20)
# 동일 trade subset 의 최소 원자 조합 → 319개

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
    """atoms_dict 가 319 canonical Win>=69% 조합 중 하나라도 매칭되는지."""
    active = frozenset(k for k, v in atoms_dict.items() if v)
    for combo_set in _WIN69_COMBO_SETS:
        if combo_set.issubset(active):
            return True
    return False


# =========================================================
# Stage 4J BLOCK + BOOSTER (크립토 그대로, 자산군 검증 필요)
# =========================================================

def is_stage4j_blocked(tier, side, symbol, run_potential):
    """4J outlier 차단 — 크립토 백테에서 발견한 패턴.
    자산군에선 다를 수 있음 (atom OR search 로 재검증)."""
    rp = int(run_potential) if run_potential is not None else -1
    if tier == "SWEEP_GEM" and side == "long" and rp == 1:
        return "GEM_LONG_RP1_outlier_dep"
    if tier == "SWEEP_ROOM_ONLY" and symbol == "AVAXUSDT":
        return "ROOM_ONLY_AVAX_outlier_dep"
    return None


def get_stage4j_extra_mult(tier, side, symbol, run_potential):
    """4J extra booster (BOOST15 매트릭스) — 크립토 그대로."""
    rp = int(run_potential) if run_potential is not None else -1
    # crypto-specific (자산군에선 무용)
    if tier == "SWEEP_ROOM_FVG" and symbol == "DOGEUSDT":
        return (1.5, "BOOST15_FVG_DOGE")
    if tier == "SWEEP_GEM" and side == "long" and rp == 2:
        return (1.5, "BOOST15_GEM_LONG_RP2")
    if tier == "SWEEP_GEM" and side == "long" and rp == 0:
        return (1.2, "BOOST12_GEM_LONG_RP0")
    if tier == "SWEEP_ROOM_ONLY" and symbol == "ADAUSDT":
        return (1.2, "BOOST12_ROOM_ONLY_ADA")
    if tier == "SWEEP_ROOM_ONLY" and side == "long" and rp == 1 and symbol != "ADAUSDT":
        return (1.2, "BOOST12_ROOM_ONLY_LONG_RP1")
    if tier == "SWEEP_ROOM_FVG" and side == "long" and rp == 2 and symbol != "DOGEUSDT":
        return (1.2, "BOOST12_FVG_LONG_RP2")
    return (1.0, "DEFAULT")


# =========================================================
# Sentiment Booster (BOOST15 only)
# =========================================================

def compute_sentiment_lookback(target_time, executed_trades_so_far, days=7):
    """target_time 직전 days일 거래 → LONG/SHORT RP 평균 격차.
    Returns: (sentiment, n_window) — None if 데이터 부족."""
    if not executed_trades_so_far:
        return None, 0
    cutoff = target_time - pd.Timedelta(days=days)
    long_rps, short_rps = [], []
    for tr in executed_trades_so_far:
        et = tr.get("entry_time")
        if et is None or et >= target_time or et < cutoff:
            continue
        rp = tr.get("run_potential")
        side = tr.get("side")
        if rp is None or side not in ("long", "short"):
            continue
        if side == "long":
            long_rps.append(int(rp))
        else:
            short_rps.append(int(rp))
    n_total = len(long_rps) + len(short_rps)
    if len(long_rps) < SENTIMENT_MIN_SAMPLES or len(short_rps) < SENTIMENT_MIN_SAMPLES:
        return None, n_total
    return (np.mean(long_rps) - np.mean(short_rps)), n_total


def get_stage4k_sentiment_mult(target_time, side, executed_trades_so_far, scenario="BOOST15"):
    """4K Sentiment + Momentum booster/cut.
    Returns: (mult, label).
    측정 불가 시 (1.0, "no_data")."""
    cfg = SENTIMENT_BOOSTER_BY_SCENARIO.get(scenario)
    if cfg is None:
        return (1.0, "no_scenario")
    s_now,  _ = compute_sentiment_lookback(target_time, executed_trades_so_far, days=SENTIMENT_LOOKBACK_DAYS)
    s_prev, _ = compute_sentiment_lookback(
        target_time - pd.Timedelta(days=SENTIMENT_PREV_OFFSET),
        executed_trades_so_far, days=SENTIMENT_LOOKBACK_DAYS,
    )
    if s_now is None or s_prev is None:
        return (1.0, "no_data")
    chg = s_now - s_prev
    BOOST = cfg["BOOST"]
    CUT = cfg["CUT"]
    # 4 BOOSTER
    if s_now > 0.3 and chg > 0.2 and side == "short":
        return (BOOST, "BOOST_TopReversal")
    if s_now < -0.3 and chg < -0.2 and side == "long":
        return (BOOST, "BOOST_BottomReversal")
    if abs(s_now) <= 0.3 and chg > 0.2 and side == "long":
        return (BOOST, "BOOST_TrendStart_L")
    if abs(s_now) <= 0.3 and chg > 0.2 and side == "short":
        return (BOOST, "BOOST_TrendStart_S")
    # 3 CUT
    if abs(s_now) <= 0.3 and abs(chg) <= 0.2 and side == "short":
        return (CUT, "CUT_NeutStable_S")
    if abs(s_now) <= 0.3 and chg < -0.2 and side == "short":
        return (CUT, "CUT_NeutFalling_S")
    if s_now < -0.3 and abs(chg) <= 0.2 and side == "long":
        return (CUT, "CUT_ShortStable_L")
    return (1.0, "default")


# =========================================================
# LTF helpers (sweep flag, pre-entry confluence, wick ratio)
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


def compute_pre_entry_confluence(df_htf, df_ltf, htf_entry_idx,
                                 zone_low, zone_high,
                                 lookback_ltf_bars=8):
    """진입 직전 LTF 봉 안에 zone 내부의 sweep/fvg/ob 카운트."""
    entry_htf_ts = df_htf.loc[htf_entry_idx, "timestamp"]
    ltf_mask = df_ltf["timestamp"] <= entry_htf_ts
    if not ltf_mask.any():
        return 0, 0, 0, 0
    ltf_entry_idx = int(df_ltf[ltf_mask].index[-1])
    start_idx = max(0, ltf_entry_idx - lookback_ltf_bars)
    end_idx = ltf_entry_idx
    if start_idx > end_idx or start_idx >= len(df_ltf):
        return 0, 0, 0, 0
    sub = df_ltf.iloc[start_idx:end_idx+1]
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


def compute_wick_ratio_5(df_htf, df_ltf, htf_entry_idx, side, lookback_n=5):
    """진입 직전 LTF 5봉의 방향성 꼬리 비율."""
    entry_htf_ts = df_htf.loc[htf_entry_idx, "timestamp"]
    ltf_mask = df_ltf["timestamp"] <= entry_htf_ts
    if not ltf_mask.any():
        return 0.0
    ltf_entry_idx = int(df_ltf[ltf_mask].index[-1])
    start_idx = max(0, ltf_entry_idx - lookback_n)
    end_idx = ltf_entry_idx
    if start_idx >= end_idx:
        return 0.0
    sub = df_ltf.iloc[start_idx:end_idx]
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
# Tier 분류 (atomic 12 → tier)
# =========================================================

def classify_tier_stage4h(atoms_dict, side="long"):
    """Stage 4H Tier 판정 — SWEEP_BASE 를 GEM/ROOM_FVG/ROOM_ONLY 로 세분화."""
    def _g(k):
        return bool(atoms_dict.get(k, False))
    vol = _g("a_volume"); ovl = _g("a_overlap"); swp = _g("a_sweep")
    s13 = _g("a_score_ge13"); p1 = _g("a_pre_total_ge1")
    p4 = _g("a_pre_total_ge4"); wq1 = _g("a_wick_le_q1")
    mss = _g("a_mss"); fvg = _g("a_fvg"); rm = _g("a_room")
    any_alpha = (vol or ovl or swp or s13 or p4)
    # SKIP_MSS
    if mss and not any_alpha:
        return "SKIP_MSS"
    # ALPHA_MAX
    if ovl and not vol:
        return "ALPHA_MAX"
    if s13 and p1 and not ovl:
        return "ALPHA_MAX"
    # ALPHA_HIGH
    if vol and ovl and (p1 or p4 or wq1 or s13):
        return "ALPHA_HIGH"
    if swp and vol and not ovl:
        return "ALPHA_HIGH"
    # ALPHA_MED (WIN69)
    if passes_win69_union(atoms_dict):
        return "ALPHA_MED"
    # SWEEP_BASE 세분화
    if swp:
        if not rm:
            return "SWEEP_GEM"
        elif fvg:
            return "SWEEP_ROOM_FVG"
        else:
            return "SWEEP_ROOM_ONLY"
    # COMPLETE_OUT
    return "COMPLETE_OUT"


def get_tier_risk_mult_4h(tier_label, side="long", symbol=None):
    """Tier 별 risk mult — BOOST15 + Stage 4I 차단 규칙."""
    if tier_label == "SKIP_MSS":
        return 0.0
    if tier_label == "ALPHA_MED":
        return ALPHA_MED_RISK_LONG if side == "long" else ALPHA_MED_RISK_SHORT
    if tier_label == "COMPLETE_OUT":
        if OUT_BEHAVIOR == "skip":
            return 0.0
        elif OUT_BEHAVIOR == "keep_r1":
            return 1.0
        elif OUT_BEHAVIOR == "keep_r05":
            return 0.5
        return 0.0
    # Stage 4I 차단
    if tier_label == "SWEEP_GEM" and GEM_LONG_ONLY and side == "short":
        return 0.0
    if tier_label == "SWEEP_ROOM_ONLY" and symbol is not None and symbol in ROOM_ONLY_SYMBOL_BLACKLIST:
        return 0.0
    # SWEEP scenario
    if tier_label in ("SWEEP_GEM", "SWEEP_ROOM_FVG", "SWEEP_ROOM_ONLY"):
        return SWEEP_RISK_BY_SCENARIO[SCENARIO][tier_label]
    return TIER_RISK_MULT_COMMON.get(tier_label, 1.0)


def get_tier_cap_4h(tier_label):
    return TIER_CAP_4H.get(tier_label, 3.0)


def classify_tier_v19b_rp_boost(pre_total, sweep_count, score, wick_ratio_5, run_potential):
    """v1.9b TIER + RP_BOOST 통합 분류.
    Returns: (tier_label, final_tier_mult, rp_action)."""
    if run_potential not in RP_TIER_MULT_TABLE:
        return "D", 0.0, f"rp_skip_rp{run_potential}"
    rp_mult = RP_TIER_MULT_TABLE[run_potential]
    rp_action = (
        f"rp_boost_rp{run_potential}_x{rp_mult}" if rp_mult > 1.0
        else f"rp_pass_rp{run_potential}"
    )
    in_d = (pre_total >= 4) or (2 <= sweep_count <= 4) or (score >= 13)
    in_wick = (wick_ratio_5 is not None) and (not pd.isna(wick_ratio_5)) and (wick_ratio_5 <= WICK_RATIO_5_Q1_THRESHOLD)
    if in_d and in_wick:
        tier = "S"; base_mult = TIER_RISK_S
    elif in_d and not in_wick:
        tier = "A"; base_mult = TIER_RISK_A
    elif not in_d and in_wick:
        tier = "B"; base_mult = TIER_RISK_B
    elif pre_total >= 1:
        tier = "C"; base_mult = TIER_RISK_C
    else:
        return "D", 0.0, "tier_d_skip"
    final_mult = base_mult * rp_mult
    return tier, final_mult, rp_action


# =========================================================
# atomic 12 태그 계산 (compute_trade_tags)
# =========================================================

def compute_trade_tags(df_struct, entry_idx, zone_created_idx,
                       zone_low, zone_high, side,
                       pre_total, sweep_count, score, wick_ratio_5,
                       structure_reasons, atr_val):
    """12 atomic 태그 계산 (게이트 아님, 로그용/tier 분류용)."""
    tags = {}
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
    # Tier 구성 5개
    pt = int(pre_total) if pd.notna(pre_total) else 0
    sc = int(sweep_count) if pd.notna(sweep_count) else 0
    sv = float(score) if pd.notna(score) else 0.0
    wv = wick_ratio_5
    tags["a_pre_total_ge4"]   = (pt >= 4)
    tags["a_sweep_count_2_4"] = (2 <= sc <= 4)
    tags["a_score_ge13"]      = (sv >= 13.0)
    tags["a_wick_le_q1"]      = (wv is not None) and (not pd.isna(wv)) and (wv <= WICK_RATIO_5_Q1_THRESHOLD)
    tags["a_pre_total_ge1"]   = (pt >= 1)
    # RP 구성 5개
    reasons = str(structure_reasons) if structure_reasons is not None else ""
    reasons_set = set(r.strip() for r in reasons.split(",") if r.strip())
    h4_trend = df_struct.loc[entry_idx, "trend"] if "trend" in df_struct.columns else "neutral"
    tags["a_trend_align"] = (side == "long" and h4_trend == "up") or \
                             (side == "short" and h4_trend == "down")
    tags["a_mss"]     = ("bull_mss" in reasons_set) or ("bear_mss" in reasons_set)
    tags["a_fvg"]     = ("valid_bull_fvg" in reasons_set) or ("valid_bear_fvg" in reasons_set)
    tags["a_overlap"] = ("bull_ob_fvg_overlap" in reasons_set) or \
                         ("bear_ob_fvg_overlap" in reasons_set)
    # a_room: SL 대비 room >= 2.8 × risk
    a_room = False
    if pd.notna(atr_val) and atr_val > 0:
        if side == "long":
            entry_proxy = zone_low + (zone_high - zone_low) * 0.40
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


# =========================================================
# 4K 통합 risk multiplier (final 진입 시 호출)
# =========================================================

def compute_4k_risk_pct(base_risk_pct, atoms_dict, side, symbol, run_potential,
                       pre_total, sweep_count, score, wick_ratio_5,
                       target_time, executed_trades_so_far, scenario="BOOST15"):
    """
    base_risk × tier_mult × rp_mult × stage4j_mult × sentiment_mult.
    Returns: (effective_risk_pct, info_dict).
    info_dict: {tier, tier_mult, rp_action, j_mult, j_label, sent_mult, sent_label, blocked}
    """
    info = {
        "tier_4h": None, "tier_v19b": None,
        "tier_mult": 0.0, "rp_action": None,
        "j_mult": 1.0, "j_label": "DEFAULT",
        "sent_mult": 1.0, "sent_label": "no_data",
        "blocked": None,
    }
    # 1. 4H tier (atoms 기반 분류, 단순 lookup)
    tier_4h = classify_tier_stage4h(atoms_dict, side=side)
    info["tier_4h"] = tier_4h
    # 2. v19b tier (pre/sweep/score/wick + RP boost)
    tier_v19b, tier_mult, rp_action = classify_tier_v19b_rp_boost(
        pre_total, sweep_count, score, wick_ratio_5, run_potential
    )
    info["tier_v19b"] = tier_v19b
    info["tier_mult"] = tier_mult
    info["rp_action"] = rp_action
    if tier_mult <= 0.0:
        return 0.0, info  # skip
    # 3. 4J block
    blocked = is_stage4j_blocked(tier_4h, side, symbol, run_potential)
    if blocked:
        info["blocked"] = blocked
        return 0.0, info
    # 4. 4H tier mult (별도 layer — 4G/4H 의 ALPHA_MAX 등)
    h4_mult = get_tier_risk_mult_4h(tier_4h, side=side, symbol=symbol)
    if h4_mult <= 0.0:
        info["blocked"] = f"tier4h_zero_{tier_4h}"
        return 0.0, info
    # 5. 4J extra mult
    j_mult, j_label = get_stage4j_extra_mult(tier_4h, side, symbol, run_potential)
    info["j_mult"] = j_mult
    info["j_label"] = j_label
    # 6. Sentiment booster
    sent_mult, sent_label = get_stage4k_sentiment_mult(target_time, side, executed_trades_so_far, scenario)
    info["sent_mult"] = sent_mult
    info["sent_label"] = sent_label
    # 최종
    effective_risk_pct = base_risk_pct * tier_mult * h4_mult * j_mult * sent_mult
    info["effective_risk_pct"] = effective_risk_pct
    info["base_risk_pct"] = base_risk_pct
    info["h4_mult"] = h4_mult
    return effective_risk_pct, info


print("smc_4k_layer loaded — BOOST15 only, GEM_LONG_ONLY={}, ROOM_BLACKLIST={}, WICK_Q1={}".format(
    GEM_LONG_ONLY, len(ROOM_ONLY_SYMBOL_BLACKLIST), WICK_RATIO_5_Q1_THRESHOLD
))
