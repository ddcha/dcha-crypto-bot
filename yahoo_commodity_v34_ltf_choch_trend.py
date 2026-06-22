# =========================================================
# YAHOO COMMODITY FUTURES BACKTEST — v3.3 V6.2 (B2 X-block)
import os as _os  # ← 파일 맨 위로 이동 (line 195+ 에서 사용 가능하도록)
#
# [v33 변경점 (vs v32)]
#   ★★★ V6.2: B2 (wick_q1 & rp_eq_3) → X-block ★★★
#       v32 BOOSTED 결과 분석:
#         B2 단독 매치 29거래 PnL -$19,609
#         B2 전체 매치 42거래 PnL -$48,894
#       → A- 70거래 중 B2 매치가 손실 대부분 (PF 0.51)
#       → B2 차단 시 A- 양수 전환 + ALI/HG A- 자동 정리
#
#   변경: V6_RULE_TO_SUBTIER["B2"] = "A-" → "X-block"
#   다른 모든 설정은 v32 와 동일 (BOOSTED + asset_mult + TRUEFLAT)
# =========================================================
#
# [v32 변경점 (vs v31)]
#   ★★★ 데이터 기반 자산 mult 도입 (TRUEFLAT 결과 기반) ★★★
#       GC, SI         : ×1.5 (AvgR 0.81 압도적)
#       NG, SB         : ×1.2 (PF 4.7+, Win 78%+)
#       나머지         : ×1.0
#
#   ★★★ V6_SCENARIO=BOOSTED (S 5배 / S+ 4배 / A+ 3배 / A 1.2 / A- 0.9) ★★★
#       강한 sub-tier 에 대폭 risk 차등
#
#   [최종 risk_pct = base 1.0% × asset_mult × v6_mult]
#   예: GC × S 거래 = 1.0% × 1.5 × 5.0 = 7.5%   ⚠ 매우 큼
#       SI × S+ 거래 = 1.0% × 1.5 × 4.0 = 6.0%
#       NG × A+ 거래 = 1.0% × 1.2 × 3.0 = 3.6%
#       ALI × A 거래 = 1.0% × 1.0 × 1.2 = 1.2%
# =========================================================
#
# [v31 변경점 (vs v30)]
#   ★★★ V6.1 RULE 매핑 보정 (v30 백테 결과 기반 fine-tune) ★★★
#       격상:
#         B1 (volume 단독)            : A- → A   (단독 매치 PnL +$11,300)
#         B4 (trend+fvg+rp2+matchC)  : A- → A   (단독 매치 PnL +$1,767)
#       격하:
#         B2 (wick_q1+rp_eq_3)        : A  → A-  (단독 매치 PnL -$1,284)
#       SKIP (X-block):
#         B3 (v19b_match_S 단독)      : A- → X   (단독 매치 PnL -$2,863)
#         B5 (pre_ge1+fvg+rp_eq_3)    : A- → X   (단독 매치 PnL -$1,617)
#         B8 (sweep+d_cond+rp_eq_2)   : A  → X   (단독 매치 PnL -$2,007)
#         B10 (pre_ge1+trend+mss)     : A- → X   (전체 PnL -$1,079)
#
#   ★★★ DANGEROUS 4H × v19b COMBO 직접 차단 ★★★
#       A- 분류된 거래 중 약한 4H × v19b 조합이면 SKIP
#         (SWEEP_ROOM_ONLY, S)  : PnL -$1,241
#         (SWEEP_ROOM_ONLY, A)  : PnL  -$847
#         (COMPLETE_OUT, S)     : PnL -$1,539
#
# [V6.1 RULE → SUB-TIER 매핑 (확정)]
#   S    : V5 S rule 매치
#   S+   : A7 (Win 87.8%, AvgR 1.06)
#   A+   : A1, A2, A3, A4, A5, A8, A9, A10, A11, A12
#   A    : A6, B1, B4
#   A-   : B2, B6, B7, B9
#   X    : B3, B5, B8, B10 (X-block, SKIP)
#
# [예상 효과 (FLAT 기준)]
#   v30 FLAT: $54,980 → v31 FLAT 약 $65,500 예상 (+$10,540)
#   거래 수: 536 → 약 460 (76 거래 차단)
#   PF: 2.45 → 약 3.0 예상
# =========================================================
#
# =========================================================

# Cell 1: 패키지 설치 + 임포트 -------------------------------
try:
    _ipy = get_ipython()  # noqa: F821
    if _ipy is not None:
        _ipy.run_line_magic('pip', 'install -q yfinance pandas numpy matplotlib pytz')
except (NameError, AttributeError):
    pass

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib
try:
    matplotlib.use("Agg")
except Exception:
    pass
import matplotlib.pyplot as plt
import yfinance as yf
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import multiprocessing as mp
from typing import Any, Dict, List, Optional, Set, Tuple

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 240)
pd.set_option("display.max_colwidth", 180)


# %%
# =========================================================
# Cell 2: ★ 실험/수정 섹션 — 여기만 바꾸면 됨 ★
# =========================================================

MODE = "portfolio"

# ----- 심볼 세트: 14 commodities (Slow 9 + Fast 5) -----
INDEX_SYMBOLS = {
    # 🐢 Slow Group (12h/4h) - 9 자산 (귀금속 4 + 에너지 3 + 소프트 2)
    "GC":  "GC=F",   # 금
    "SI":  "SI=F",   # 은
    "PL":  "PL=F",   # 백금
    "PA":  "PA=F",   # 팔라듐
    "CL":  "CL=F",   # WTI 원유
    "NG":  "NG=F",   # 천연가스
    "HO":  "HO=F",   # 난방유
    "SB":  "SB=F",   # 설탕
    "CC":  "CC=F",   # 코코아
    # 🐇 Fast Group (4h/1h) - 5 자산 (산업금속 2 + 곡물 2 + 소프트 1)
    "HG":  "HG=F",   # 구리
    "ALI": "ALI=F",  # 알루미늄
    "ZS":  "ZS=F",   # 대두
    "ZW":  "ZW=F",   # 밀
    "KC":  "KC=F",   # 커피
}
SINGLE_TARGETS = list(INDEX_SYMBOLS.keys())

SYMBOL_TF_MAP = {
    # Slow: 12h HTF / 4h LTF (9자산)
    "GC":  ("12h", "4h"), "SI":  ("12h", "4h"),
    "PL":  ("12h", "4h"), "PA":  ("12h", "4h"),
    "CL":  ("12h", "4h"), "NG":  ("12h", "4h"),
    "HO":  ("12h", "4h"), "SB":  ("12h", "4h"),
    "CC":  ("12h", "4h"),
    # Fast: 4h HTF / 1h LTF (5자산)
    "HG":  ("4h", "1h"), "ALI": ("4h", "1h"),
    "ZS":  ("4h", "1h"), "ZW":  ("4h", "1h"),
    "KC":  ("4h", "1h"),
}

# ----- 데이터 파라미터 -----
TIMEZONE = "America/New_York"
PERIOD_1H = "729d"
INTERVAL_1H = "60m"
HTF_RESAMPLE = "12h"
LTF_RESAMPLE = "4h"

# ★★★ [PATCHED v34 — LTF CHoCH Trend 스위치, 2026-05-22] ★★★
# True  : df_htf.trend 을 df_ltf CHoCH state 로 교체 (크립토 v3 방식)
# False : 기존 EMA(ema20<ema50<ema200) trend 유지 (v33 원래 방식)
# 환경변수로도 전환 가능: USE_LTF_CHOCH_TREND=1 python ...
USE_LTF_CHOCH_TREND = _os.environ.get("USE_LTF_CHOCH_TREND", "0") == "1"

USE_RTH_ONLY = False

# ----- 자본 / 입금 -----
INITIAL_CAPITAL_KRW = 3_000_000
MONTHLY_DEPOSIT_KRW = 2_000_000
NUM_MONTHLY_DEPOSITS = 5
KRW_PER_USD = 1350.0

# ----- 수수료 / 슬리피지 -----
FEE_RATE = 0.0005
ENTRY_SLIPPAGE_BPS = 1.0
EXIT_SLIPPAGE_BPS = 1.0

# =========================================================
# Phase A/B Capacity Cap
# =========================================================
TARGET_BALANCE_USD = 3_099_690.0
TARGET_BALANCE_KRW = TARGET_BALANCE_USD * KRW_PER_USD

TAX_RATE = 0.22
TAX_DEDUCTION_KRW = 2_500_000

THRESHOLD_USD = {
    # 🐢 Slow Group (12h/4h) - 9자산
    "GC":  3_000_000.0,  # 금 (메인)
    "SI":  1_000_000.0,
    "PL":    300_000.0,
    "PA":    200_000.0,
    "CL":  3_000_000.0,  # 원유 메인
    "NG":    500_000.0,
    "HO":    500_000.0,
    "SB":    300_000.0,
    "CC":    200_000.0,
    # 🐇 Fast Group (4h/1h) - 5자산
    "HG":    500_000.0,
    "ALI":   300_000.0,
    "ZS":    300_000.0,
    "ZW":    200_000.0,
    "KC":    300_000.0,
}

PHASE_A_RISK = {
    # 🐢 Slow Group (9자산) - v2.0 Avg R 차등 배분
    "GC":   0.020,   # 메인 (PF 14.72, Avg R 1.52)
    "SI":   0.010,
    "PL":   0.010,
    "PA":   0.005,   # 변동성 극심
    "CL":   0.015,   # Avg R 2.28 🏆
    "NG":   0.005,   # 변동성 극심
    "HO":   0.010,
    "SB":   0.010,
    "CC":   0.0075,  # Avg R 0.96
    # 🐇 Fast Group (5자산)
    "HG":   0.0075,  # MDD -2.62%
    "ALI":  0.0075,
    "ZS":   0.0075,  # MDD -2.33%
    "ZW":   0.010,   # 안정 (PF 8.60, MDD -1.10%)
    "KC":   0.010,
}
# 합: 13.25%

PHASE_B_RISK = {
    # Phase B: Phase A 의 50%
    "GC":   0.010, "SI":   0.005, "PL":   0.005, "PA":   0.0025,
    "CL":   0.0075, "NG":   0.0025, "HO":   0.005,
    "SB":   0.005, "CC":   0.00375,
    "HG":   0.00375, "ALI":  0.00375, "ZS":   0.00375,
    "ZW":   0.005, "KC":   0.005,
}

SINGLE_RISK_PCT = 0.01
PORTFOLIO_RISK_CONFIG = PHASE_A_RISK
MAX_TOTAL_RISK = 0.1325
MAX_NOTIONAL_MULT = 3.0

# ★★★ v31 신규: USE_TRUE_FLAT_RISK ★★★
# True 면 자산별 차등 무시, 모든 자산 1.0% 통일 (Phase A/B 모두)
# v6_mult 와 곱해서 진짜 sub-tier 효과만 검증 가능
# v31.1: 환경변수 의존 제거 - 코드에서 직접 변경 (default True)
USE_TRUE_FLAT_RISK = True  # ← 자산별 차등 OFF 강제 활성. False 로 바꾸면 v25 원래 차등 사용
if USE_TRUE_FLAT_RISK:
    print("=" * 70)
    print("⚠ USE_TRUE_FLAT_RISK=True - 자산별 차등 비활성, 모든 자산 1.0%")
    print("=" * 70)
    for k in PHASE_A_RISK:
        PHASE_A_RISK[k] = 0.01
    for k in PHASE_B_RISK:
        PHASE_B_RISK[k] = 0.01
    MAX_TOTAL_RISK = 0.50  # v32: BOOSTED 대응 (S 5x × asset 1.5 = 7.5% / 거래)

# ★★★ v32 신규: 데이터 기반 ASSET MULTIPLIER ★★★
# v31 TRUEFLAT 결과 분석 기반 자산별 risk 차등
# (자산별 차등은 USE_TRUE_FLAT_RISK 와 별개. 1% × asset_mult × v6_mult 로 곱해짐)
USE_ASSET_MULT = True   # True 면 자산별 mult 적용
ASSET_MULT = {
    # 강함 (AvgR 0.81 압도적)
    "GC":  1.5,
    "SI":  1.5,
    # 중상 (PF 4.7+, Win 78%+)
    "NG":  1.2,
    "SB":  1.2,
    # 평범 (default 1.0)
    "CL":  1.0,  "HO":  1.0,  "CC":  1.0,
    "PA":  1.0,  "PL":  1.0,  "ZW":  1.0,
    "KC":  1.0,  "HG":  1.0,  "ZS":  1.0,
    "ALI": 1.0,
}
def get_asset_mult(symbol):
    if not USE_ASSET_MULT:
        return 1.0
    return ASSET_MULT.get(symbol, 1.0)

# ★★★ v31 신규: ALLOW_RUNNER_DOUBLE_POSITION ★★★
# True 면 같은 종목에 runner 활성화된 포지션이 있으면 추가 진입 1개 허용
# (총 같은 종목에 최대 2 포지션)
ALLOW_RUNNER_DOUBLE_POSITION = _os.environ.get("ALLOW_RUNNER_DOUBLE_POSITION", "true").lower() in ("true", "1", "yes")

# ★★★ v31 신규: MAX_CONCURRENT_POSITIONS ★★★
# 전체 동시 포지션 한도 (default 14, 14자산 × 1포지션 + runner double 케이스 고려)
MAX_CONCURRENT_POSITIONS = int(_os.environ.get("MAX_CONCURRENT_POSITIONS", "14"))

# =========================================================
# ★★★ Stage 4K BOOST15 — 4K MATRIX CONFIG ★★★
# =========================================================

MIN_SCORE = 7.5

# Stage 4K Tier 시스템 (크립토 4K BOOST15 와 동일)
SCENARIO = "BOOST15"

TIER_RISK_MULT_COMMON = {
    "ALPHA_MAX":    2.0,
    "ALPHA_HIGH":   1.5,
    "ALPHA_MED":    1.2,   # side-aware override
    "COMPLETE_OUT": 1.0,
    "SKIP_MSS":     0.0,
}
ALPHA_MED_RISK_LONG  = 0.8
ALPHA_MED_RISK_SHORT = 1.2

TIER_CAP_4H = {
    "ALPHA_MAX":       999.0,
    "ALPHA_HIGH":      999.0,
    "ALPHA_MED":       999.0,
    "SWEEP_GEM":       3.0,
    "SWEEP_ROOM_FVG":  3.0,
    "SWEEP_ROOM_ONLY": 3.0,
    "COMPLETE_OUT":    3.0,
    "SKIP_MSS":        3.0,
}

OUT_BEHAVIOR = "skip"

SWEEP_RISK_BY_SCENARIO = {
    "BOOST15": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST25": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST35": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
}

# Stage 4I 차단 규칙
# 지수는 sweep 행동 패턴이 크립토와 다를 수 있어 일단 GEM_LONG_ONLY 만 적용
# ROOM_ONLY blacklist 는 지수 백테 결과 보고 추가 (현재는 비움)
GEM_LONG_ONLY = True
ROOM_ONLY_SYMBOL_BLACKLIST = set()  # 원자재 데이터로 검증 후 추가

# Stage 4K Sentiment
SENTIMENT_LOOKBACK_DAYS = 7
SENTIMENT_PREV_OFFSET   = 7
SENTIMENT_MIN_SAMPLES   = 2

SENTIMENT_BOOSTER_BY_SCENARIO = {
    "BOOST15": {"BOOST": 1.5, "CUT": 0.5},
    "BOOST25": {"BOOST": 2.5, "CUT": 0.5},
    "BOOST35": {"BOOST": 3.5, "CUT": 0.5},
}

# RP_MULT_4H (RP0 만 1.5×, RP6+ SKIP)
RP_MULT_4H = {
    0: 1.5, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
}
RP_FILTER_ENABLE = True

# 호환 alias
TIER_RISK_S = 2.0   # ALPHA_MAX 매핑
TIER_RISK_A = 1.5   # ALPHA_HIGH 매핑
TIER_RISK_B = 1.2   # ALPHA_MED 매핑
TIER_RISK_C = 1.0   # COMPLETE_OUT 매핑
TIER_RISK_D = 0.0   # SKIP_MSS

# =========================================================
# ★★★ v26 신규: v19b RP_BOOST tier 시스템 ★★★
# =========================================================
# 4H tier (ALPHA/SWEEP/...) 와 별도 layer
# pre_total/sweep_count/score/wick → S/A/B/C/D 분류
# + RP_TIER_MULT_TABLE 로 rp 별 boost
TIER_RISK_V19B_S = 3.0   # D 조건 AND wick_Q1
TIER_RISK_V19B_A = 1.5   # D 조건 단독
TIER_RISK_V19B_B = 0.8   # wick_Q1 단독
TIER_RISK_V19B_C = 0.7   # pre>=1 fallback
TIER_RISK_V19B_D = 0.0   # pre=0 → SKIP

# RP_TIER_MULT_TABLE (v19b layer 의 RP boost)
# rp 0,1 → 1.5× / rp 2-5 → 1.0× / rp 6+ → not in dict → SKIP
RP_TIER_MULT_TABLE = {
    0: 1.5, 1: 1.5,
    2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
}

# =========================================================
# ★★★ v28 신규: ATOM SEARCH 모드 ★★★
# =========================================================
# score gate 만 통과하면 모든 거래 받음.
# 어떤 tier/v19b/RP/stage4j/GEM 차단도 적용 안함.
# 34 atom 으로만 trade record 구성.

SCORE_ONLY_GATE  = True   # ← 핵심: True 면 score 만 통과하면 모든 거래
USE_FLAT_RISK_MULT = True  # v29: True 면 V5_TIER_MULT 사용, False 면 v26 stack mult

# =========================================================
# ★★★ v29 신규: V5 TIER 분류 + RISK MULTIPLIER ★★★
# =========================================================
# V5 cutoff (atom OR analysis 결과 도출):
#   S Tier: Win >= 90% AND AvgR >= 1.3
#   A Tier: Win >= 80% AND AvgR >= 0.65 (S 미충족)
#   B Tier: Win >= 68% AND AvgR >= 0.35 (S/A 미충족)
#   X Tier: 어느 rule 도 안 맞음 → SKIP

USE_V5_TIER_GATE = True   # True 면 V5 tier 분류 + risk mult 적용 (v29 핵심)
SKIP_V5_X_TIER   = True   # X tier 모두 SKIP

# 3가지 risk multiplier scenario - 환경변수 RISK_SCENARIO 또는 직접 변경
RISK_SCENARIO = _os.environ.get("RISK_SCENARIO", "AGGRESSIVE")
# 옵션:
#   AGGRESSIVE : S=2.5  A=1.2  B=0.6   (보수적 정수배, 권장 - MDD 5% 수준)
#   SQRT_PF    : S=4.42 A=1.30 B=0.81  (sqrt(PF/baseline) - MDD 7% 수준)
#   AVGR_PROP  : S=11.15 A=4.41 B=1.0  (AvgR 비례 - 매우 공격적, MDD 19%)

V5_TIER_MULT_TABLE = {
    "AGGRESSIVE": {"S": 2.5,   "A": 1.2,   "B": 0.6,  "X": 0.0},
    "SQRT_PF":    {"S": 4.42,  "A": 1.30,  "B": 0.81, "X": 0.0},
    "AVGR_PROP":  {"S": 11.15, "A": 4.41,  "B": 1.0,  "X": 0.0},
}

if RISK_SCENARIO not in V5_TIER_MULT_TABLE:
    print(f"⚠ Unknown RISK_SCENARIO={RISK_SCENARIO}, fallback to AGGRESSIVE")
    RISK_SCENARIO = "AGGRESSIVE"
V5_TIER_MULT = V5_TIER_MULT_TABLE[RISK_SCENARIO]

# 자산 차단 (UNCL 깊은 음수 자산)
# 환경변수 SKIP_ASSETS=ZW,CL 처럼 지정 가능
SKIP_ASSETS = set()
_skip_env = _os.environ.get("SKIP_ASSETS", "").strip()
if _skip_env:
    SKIP_ASSETS = set(s.strip() for s in _skip_env.split(",") if s.strip())

# v29 V5 TIER RULE 정의 (atom 조합)
V5_S_RULES = [
    ("atoms_a_score_ge13", "t4h_high_sweep_vol"),
    ("atoms_a_pre_total_ge4", "t4h_max_score_pre", "t4h_sweep_room_fvg"),
]

V5_A_RULES = [
    ("t4h_max_score_pre",),
    ("atoms_a_score_ge13", "atoms_a_fvg"),
    ("t4h_high_sweep_vol", "v19b_match_C"),
    ("t4h_high_sweep_vol", "v19b_match_S"),
    ("atoms_a_fvg", "v19b_match_S"),
    ("atoms_a_volume", "atoms_a_trend_align", "v19b_match_A"),
    ("atoms_a_trend_align", "v19b_d_cond", "t4h_high_sweep_vol"),
    ("atoms_a_volume", "atoms_a_trend_align", "t4h_sweep_room_only"),
    ("v19b_d_cond", "t4h_sweep_room_fvg"),
    ("atoms_a_volume", "atoms_a_mss", "rp_eq_3"),
    ("atoms_a_fvg", "v19b_d_cond", "rp_eq_3"),
    ("atoms_a_sweep", "atoms_a_volume", "atoms_a_mss"),
]

V5_B_RULES = [
    ("atoms_a_volume",),
    ("atoms_a_wick_le_q1", "rp_eq_3"),
    ("v19b_match_S",),
    ("atoms_a_trend_align", "atoms_a_fvg", "rp_eq_2", "v19b_match_C"),
    ("atoms_a_pre_total_ge1", "atoms_a_fvg", "rp_eq_3"),
    ("atoms_a_sweep", "atoms_a_pre_total_ge1", "atoms_a_mss"),
    ("atoms_a_mss", "rp_eq_3"),
    ("atoms_a_sweep", "v19b_d_cond", "rp_eq_2"),
    ("atoms_a_wick_le_q1", "atoms_a_pre_total_ge1", "atoms_a_mss", "atoms_a_fvg"),
    ("atoms_a_pre_total_ge1", "atoms_a_trend_align", "atoms_a_mss"),
]

def classify_tier_v5(atoms_dict):
    """주어진 atom 들로 V5 tier 분류 (S/A/B/X). hierarchical match.
    atoms_dict: {atom_name: bool} - 거래 시점의 모든 atom 값
    """
    # S 먼저 검사
    for rule in V5_S_RULES:
        if all(atoms_dict.get(a, False) for a in rule):
            return "S"
    # A
    for rule in V5_A_RULES:
        if all(atoms_dict.get(a, False) for a in rule):
            return "A"
    # B
    for rule in V5_B_RULES:
        if all(atoms_dict.get(a, False) for a in rule):
            return "B"
    return "X"

def get_v5_tier_mult(tier_v5):
    return V5_TIER_MULT.get(tier_v5, 0.0)

# =========================================================
# ★★★ v30 신규: V6 SUB-TIER 분류 + 매핑 ★★★
# =========================================================
# rule 의 raw stat (전체 거래 대상) 기반 자동 sub-tier 부여
# 거래의 매치 rule 들 중 가장 강한 sub-tier 선택 (best-match)

# Sub-tier 우선순위 (낮은 rank = 강한 tier)
V6_SUB_RANK = {
    "S": 0, "S+": 1, "A+": 2, "A": 3, "A-": 4,
    "B+": 5, "B": 6, "B-": 7, "X-block": 8, "X": 9
}

# Rule → Sub-tier 매핑 (V6.1: v30 백테 결과 기반 fine-tune)
# 변경: B1/B4 격상 (A), B2 격하 (A-), B3/B5/B8/B10 SKIP (X-block)
V6_RULE_TO_SUBTIER = {
    # S rules (V5 S 그대로)
    "S1": "S", "S2": "S",
    # A rules
    "A1":  "A+",   # t4h_max_score_pre              Win 80.5%, AvgR +0.89, PF 8.32
    "A2":  "A+",   # score_ge13 & fvg               Win 81.5%, AvgR +0.91, PF 9.57
    "A3":  "A+",   # high_sweep_vol & match_C       Win 80.0%, AvgR +0.70, PF 6.22
    "A4":  "A+",   # high_sweep_vol & match_S       Win 82.6%, AvgR +0.90, PF 20.21
    "A5":  "A+",   # fvg & match_S                  Win 81.1%, AvgR +0.82, PF 19.06
    "A6":  "A-",   # volume & trend & match_A       Win 80.0%, AvgR +0.83, PF 2.76 (PF 낮음)
    "A7":  "S+",   # trend & d_cond & high_sweep_vol Win 87.8%, AvgR +1.06, PF 21.75 ⭐
    "A8":  "A+",   # volume & trend & sweep_room_only Win 80%, AvgR +0.66, PF 6.09
    "A9":  "A+",   # d_cond & sweep_room_fvg        Win 80.6%, AvgR +0.88, PF 11.05
    "A10": "A+",   # volume & mss & rp_eq_3         Win 81.5%, AvgR +0.79, PF 9.68
    "A11": "A+",   # fvg & d_cond & rp_eq_3         Win 80.7%, AvgR +0.92, PF 11.73
    "A12": "A+",   # sweep & volume & mss           Win 85.0%, AvgR +0.71, PF 9.15
    # B rules (V6.1 보정)
    "B1":  "A",         # ⬆ 격상 (A-→A): 단독 매치 89거래, AvgR +0.39, PnL +$11,300 ⭐
    "B2":  "X-block",   # ❌ v33: 격하 (A-→X-block) - 단독 -$19,609, 전체 -$48,894
    "B3":  "X-block",   # ❌ SKIP (A-→X): match_S 단독 21거래, AvgR -0.53, PnL -$2,863
    "B4":  "A",         # ⬆ 격상 (A-→A): 단독 매치 24거래, AvgR +0.48, PnL +$1,767
    "B5":  "X-block",   # ❌ SKIP (A-→X): pre_ge1+fvg+rp3 17거래, AvgR -0.21, PnL -$1,617
    "B6":  "A-",        # 그대로 - sweep & pre_ge1 & mss
    "B7":  "A-",        # 그대로 - mss & rp_eq_3
    "B8":  "X-block",   # ❌ SKIP (A→X): sweep+d_cond+rp2 17거래, AvgR -0.65, PnL -$2,007
    "B9":  "A-",        # 그대로 - wick_q1+pre_ge1+mss+fvg
    "B10": "X-block",   # ❌ SKIP (A-→X): pre_ge1+trend+mss 14거래, PnL -$1,079
}

# ★★★ v31 신규: DANGEROUS 4H × v19b COMBO 차단 ★★★
# A- 또는 A 로 분류된 거래 중, 아래 조합에 해당하면 X-block 처리
# (rule 매핑만으로는 안 잡히는 약한 거래 패턴)
V6_DANGEROUS_4H_V19B_COMBOS = {
    ("SWEEP_ROOM_ONLY", "S"),   # n=13, AvgR -0.45, PnL -$1,241
    ("SWEEP_ROOM_ONLY", "A"),   # n= 7, AvgR -0.94, PnL  -$847
    ("COMPLETE_OUT",    "S"),   # n= 9, AvgR -0.56, PnL -$1,539
}

def classify_tier_v6(atoms_dict):
    """V6 sub-tier 분류 - best-match 방식
    각 거래의 매치 rule 들 중 가장 강한 sub-tier 반환.
    
    Returns: 'S' / 'S+' / 'A+' / 'A' / 'A-' / 'X' (어느 rule 도 매치 안됨)
    """
    matched_subs = []
    # S rules
    for i, rule in enumerate(V5_S_RULES, 1):
        if all(atoms_dict.get(a, False) for a in rule):
            matched_subs.append(V6_RULE_TO_SUBTIER[f"S{i}"])
    # A rules
    for i, rule in enumerate(V5_A_RULES, 1):
        if all(atoms_dict.get(a, False) for a in rule):
            matched_subs.append(V6_RULE_TO_SUBTIER[f"A{i}"])
    # B rules
    for i, rule in enumerate(V5_B_RULES, 1):
        if all(atoms_dict.get(a, False) for a in rule):
            matched_subs.append(V6_RULE_TO_SUBTIER[f"B{i}"])
    
    if not matched_subs:
        return "X"
    # 가장 강한 sub-tier (rank 낮은 것)
    return min(matched_subs, key=lambda s: V6_SUB_RANK.get(s, 99))


# V6 sub-tier 별 risk multiplier (3가지 시나리오)
# 환경변수 V6_SCENARIO 로 선택 (default: FLAT)
V6_SCENARIO = _os.environ.get("V6_SCENARIO", "BOOSTED")  # v32: default BOOSTED

V6_SUB_TIER_MULT_TABLE = {
    # FLAT: 모두 1.0 통일 (분류 검증용 - v30 default)
    "FLAT": {
        "S": 1.0, "S+": 1.0, "A+": 1.0, "A": 1.0, "A-": 1.0,
        "B+": 1.0, "B": 1.0, "B-": 1.0,
        "X-block": 0.0, "X": 0.0,
    },
    # BALANCED: 권장 운용
    "BALANCED": {
        "S": 2.5, "S+": 2.5, "A+": 1.8, "A": 1.2, "A-": 0.9,
        "B+": 0.7, "B": 0.5, "B-": 0.3,
        "X-block": 0.0, "X": 0.0,
    },
    # CONSERVATIVE
    "CONSERVATIVE": {
        "S": 2.0, "S+": 2.0, "A+": 1.5, "A": 1.0, "A-": 0.7,
        "B+": 0.5, "B": 0.4, "B-": 0.2,
        "X-block": 0.0, "X": 0.0,
    },
    # AGGRESSIVE
    "AGGRESSIVE": {
        "S": 3.0, "S+": 3.0, "A+": 2.2, "A": 1.4, "A-": 1.0,
        "B+": 0.8, "B": 0.5, "B-": 0.3,
        "X-block": 0.0, "X": 0.0,
    },
    # ★★★ v32 신규: BOOSTED ★★★ - 강한 sub-tier 대폭 강화
    # S=5x, S+=4x, A+=3x, A=1.2, A-=0.9
    "BOOSTED": {
        "S": 5.0, "S+": 4.0, "A+": 3.0, "A": 1.2, "A-": 0.9,
        "B+": 0.7, "B": 0.5, "B-": 0.3,
        "X-block": 0.0, "X": 0.0,
    },
}

if V6_SCENARIO not in V6_SUB_TIER_MULT_TABLE:
    print(f"⚠ Unknown V6_SCENARIO={V6_SCENARIO}, fallback to FLAT")
    V6_SCENARIO = "FLAT"
V6_SUB_TIER_MULT = V6_SUB_TIER_MULT_TABLE[V6_SCENARIO]

USE_V6_SUB_TIER = True   # True 면 V6 sub-tier 분류 사용 (V5 대신)

def get_v6_sub_tier_mult(sub_tier):
    return V6_SUB_TIER_MULT.get(sub_tier, 0.0)


# v28 잔재 호환 (USE_COMBO_WHITELIST 등 다른 함수에서 참조하므로 stub 유지)
ALLOWED_TIER_COMBOS = set()  # 사용 안함 (USE_COMBO_WHITELIST=False)
USE_COMBO_WHITELIST = False
ATOMIZED_MODE = USE_COMBO_WHITELIST

# =========================================================

# Stage 4K atomic 계산용
WICK_RATIO_5_Q1_THRESHOLD = 0.2300   # 4K 매트릭스 일치
PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5
SWEEP_LOOKBACK_BARS = 5
VOLUME_AVG_WINDOW = 20
VOLUME_SPIKE_MULT = 1.1
VOLUME_STRICT_MODE = False
VOLUME_PREV_MULT = 1.5
USE_VOLUME_FILTER = False  # v28: atom 분석용으로 OFF

# Skip flags (호환)
SKIP_TIER_B = False
SKIP_TIER_C = False
SKIP_TIER_D = True

SL_BUFFER_MULT = 0.08

# ★ 보수 entry (실전 시장가 fill 일치) ★
LONG_BASE_ENTRY_FRAC = 1.0    # zone_high
SHORT_BASE_ENTRY_FRAC = 0.0   # zone_low
H1_REFINE_MAX_IMPROVE_FRAC = 0.0  # refine OFF
H1_REFINE_LOOKBACK_HOURS = 12
H1_CHOCH_CONFIRM_HOURS = 16

SAME_SIDE_COOLDOWN_BARS = 0
DAY_TRADE_LIMIT = 999

FRESHNESS_MAX_BONUS = 1.5
RELAX_MIN_SCORE = MIN_SCORE - FRESHNESS_MAX_BONUS

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

_TF_SUFFIX = "_TRUEFLAT" if USE_TRUE_FLAT_RISK else ""
OUTDIR = Path(f"yahoo_commodity_v33_v6_2_b2block_{V6_SCENARIO}{_TF_SUFFIX}_outputs")
OUTDIR.mkdir(exist_ok=True)

INITIAL_BALANCE_USD = INITIAL_CAPITAL_KRW / KRW_PER_USD
MONTHLY_DEPOSIT_USD = MONTHLY_DEPOSIT_KRW / KRW_PER_USD

print("=" * 80)
print(f"YAHOO COMMODITY v33 — V6.2 (B2 X-block) {V6_SCENARIO} (S/S+/A+/A/A- best-match, 14 commodities)")
print("=" * 80)
print(f"Total assets: {len(INDEX_SYMBOLS)}")
print()
print("🐢 Slow Group (12h/4h) - 9 commodities:")
slow = [k for k, (h, l) in SYMBOL_TF_MAP.items() if h == "12h"]
for k in slow:
    print(f"   {k:4s}: A_risk={PHASE_A_RISK[k]*100:.2f}%  B_risk={PHASE_B_RISK[k]*100:.2f}%  thr=${THRESHOLD_USD[k]/1e6:.1f}M")
print()
print("🐇 Fast Group (4h/1h) - 5 commodities:")
fast = [k for k, (h, l) in SYMBOL_TF_MAP.items() if h == "4h"]
for k in fast:
    print(f"   {k:4s}: A_risk={PHASE_A_RISK[k]*100:.2f}%  B_risk={PHASE_B_RISK[k]*100:.2f}%  thr=${THRESHOLD_USD[k]/1e6:.1f}M")
print()
print(f"MIN_SCORE: {MIN_SCORE} | Volume Filter: {"ON" if USE_VOLUME_FILTER else "OFF"} ({VOLUME_SPIKE_MULT})")
print(f"SCENARIO: {SCENARIO}")
print(f"Wick Q1 threshold: {WICK_RATIO_5_Q1_THRESHOLD}")
print(f"GEM_LONG_ONLY: {GEM_LONG_ONLY}")
print(f"ROOM_ONLY blacklist: {ROOM_ONLY_SYMBOL_BLACKLIST or 'NONE'}")
print(f"ENTRY MODE: LONG=zone_high (frac={LONG_BASE_ENTRY_FRAC}), SHORT=zone_low (frac={SHORT_BASE_ENTRY_FRAC}), refine={H1_REFINE_MAX_IMPROVE_FRAC}")
print()
print(f"★ v30 USE_V6_SUB_TIER:    {USE_V6_SUB_TIER}  (True → V6 sub-tier best-match 분류)")
print(f"★ v30 V6_SCENARIO:        {V6_SCENARIO}")
print(f"★ v31 USE_TRUE_FLAT_RISK: {USE_TRUE_FLAT_RISK}  (True → 자산별 차등 OFF, 모든 자산 1.0%)")
print(f"★ v32 USE_ASSET_MULT:     {USE_ASSET_MULT}  (True → 자산별 mult)")
if USE_ASSET_MULT:
    am_groups = {}
    for sym, m in ASSET_MULT.items():
        am_groups.setdefault(m, []).append(sym)
    for m in sorted(am_groups.keys(), reverse=True):
        print(f"   → ×{m:.1f}: {', '.join(sorted(am_groups[m]))}")
print(f"★ v31 ALLOW_RUNNER_DOUBLE_POSITION: {ALLOW_RUNNER_DOUBLE_POSITION}  (True → runner 활성화 시 같은 종목 2포지션 허용)")
print(f"★ v31 MAX_CONCURRENT_POSITIONS: {MAX_CONCURRENT_POSITIONS}")
v6m = V6_SUB_TIER_MULT
print(f"   → S={v6m.get('S',0):.2f} S+={v6m.get('S+',0):.2f} A+={v6m.get('A+',0):.2f} "
      f"A={v6m.get('A',0):.2f} A-={v6m.get('A-',0):.2f}")
print(f"   → B+={v6m.get('B+',0):.2f} B={v6m.get('B',0):.2f} B-={v6m.get('B-',0):.2f} "
      f"X-block=SKIP X=SKIP")
print(f"★ v30 USE_V5_TIER_GATE:   False (V6 가 우선 적용)")
print(f"★ v29 RISK_SCENARIO (사용 안함): {RISK_SCENARIO}")
if SKIP_ASSETS:
    print(f"★ v30 SKIP_ASSETS:        {sorted(SKIP_ASSETS)}")
else:
    print(f"★ v30 SKIP_ASSETS:        (없음, 환경변수 SKIP_ASSETS 로 지정)")
print(f"★ ATOM 34개 + V6 sub-tier 저장")
total_a_risk = sum(PHASE_A_RISK.values())
total_b_risk = sum(PHASE_B_RISK.values())
print(f"Phase A Total Risk: {total_a_risk*100:.2f}%   |   Phase B Total Risk: {total_b_risk*100:.2f}%")
print(f"Target Balance   : {TARGET_BALANCE_USD:,.0f} USD = {TARGET_BALANCE_KRW/1e8:.2f}억 KRW")
print(f"Tax              : 연 {TAX_RATE*100:.0f}% (공제 {TAX_DEDUCTION_KRW/1e4:.0f}만원)")
print(f"Initial          : {INITIAL_CAPITAL_KRW:,} KRW + {MONTHLY_DEPOSIT_KRW:,} x {NUM_MONTHLY_DEPOSITS}회")
print("=" * 80)
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
# ★★★ Stage 4J: BOOSTER + ADD'L BLOCK ★★★
# =========================================================
# Stage 4J 그대로 + 4K Sentiment Momentum lookback layer 추가
# Runner time exit: 그대로 풀어둠 (수동 청산 의도)

# ─── Stage 4K 시나리오 (booster mult variation) ───
SCENARIO = "BOOST15"   # default — 셀 3 에서 변경

# ─── 공통 Tier risk mult (4G 유지) ───
TIER_RISK_MULT_COMMON = {
    "ALPHA_MAX":    2.0,
    "ALPHA_HIGH":   1.5,
    "ALPHA_MED":    1.2,   # side-aware override
    "COMPLETE_OUT": 1.0,   # OUT_BEHAVIOR 따라
    "SKIP_MSS":     0.0,
}

# ─── 시나리오별 SWEEP 계열 risk mult ───
# 4K 모든 시나리오에서 base SWEEP risk = 1.0× (4J 와 동일)
# Sentiment booster 는 별도 layer 로 곱셈 (get_stage4k_sentiment_mult)
SWEEP_RISK_BY_SCENARIO = {
    "BOOST15": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST25": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST35": {
        "SWEEP_GEM":       1.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
}

# ─── Stage 4I 신규 차단 규칙 (그대로 유지) ───
GEM_LONG_ONLY = True
ROOM_ONLY_SYMBOL_BLACKLIST = {
    "BTCUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT",
}

# ─── Stage 4J BLOCK + BOOSTER 매트릭스 (그대로 유지) ───
def is_stage4j_blocked(tier, side, symbol, run_potential):
    rp = int(run_potential) if run_potential is not None else -1
    if tier == "SWEEP_GEM" and side == "long" and rp == 1:
        return "GEM_LONG_RP1_outlier_dep"
    if tier == "SWEEP_ROOM_ONLY" and symbol == "AVAXUSDT":
        return "ROOM_ONLY_AVAX_outlier_dep"
    return None

def get_stage4j_extra_mult(tier, side, symbol, run_potential):
    rp = int(run_potential) if run_potential is not None else -1
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

# ─── Stage 4K Sentiment Momentum 매트릭스 ───
SENTIMENT_LOOKBACK_DAYS = 7      # 직전 7일 lookback
SENTIMENT_MIN_SAMPLES   = 2      # 양 side 최소 시그널 개수
SENTIMENT_PREV_OFFSET   = 7      # 직전 sentiment = -14 ~ -7일

# 시나리오별 booster/cut mult
SENTIMENT_BOOSTER_BY_SCENARIO = {
    "BOOST15": {"BOOST": 1.5, "CUT": 0.5},
    "BOOST25": {"BOOST": 2.5, "CUT": 0.5},
    "BOOST35": {"BOOST": 3.5, "CUT": 0.5},
}

def compute_sentiment_lookback(target_time, executed_trades_so_far, days=7):
    """
    target_time 직전 days 일의 모든 체결 거래 → LONG/SHORT RP 평균 격차
    Returns: (sentiment, n_window) — sentiment 측정 불가 시 (None, n)
    """
    if not executed_trades_so_far:
        return None, 0
    cutoff = target_time - pd.Timedelta(days=days)
    long_rps  = []
    short_rps = []
    for tr in executed_trades_so_far:
        et = tr.get("entry_time")
        if et is None:
            continue
        if et >= target_time:
            continue
        if et < cutoff:
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

def get_stage4k_sentiment_mult(target_time, side, executed_trades_so_far, scenario):
    """
    Stage 4K 신규 layer. Sentiment + Momentum 기반 booster/cut.
    
    Returns: (mult, label)
    - 측정 불가 (lookback 데이터 부족) 시 (1.0, "no_data")
    - cell 매트릭스 외 시 (1.0, "default")
    """
    cfg = SENTIMENT_BOOSTER_BY_SCENARIO.get(scenario)
    if cfg is None:
        return (1.0, "no_scenario")
    
    # 직전 7일 sentiment
    s_now,  n_now  = compute_sentiment_lookback(target_time, executed_trades_so_far, days=SENTIMENT_LOOKBACK_DAYS)
    # 7-14일 전 sentiment
    s_prev, n_prev = compute_sentiment_lookback(
        target_time - pd.Timedelta(days=SENTIMENT_PREV_OFFSET),
        executed_trades_so_far, days=SENTIMENT_LOOKBACK_DAYS
    )
    if s_now is None or s_prev is None:
        return (1.0, "no_data")
    
    chg = s_now - s_prev
    BOOST = cfg["BOOST"]
    CUT   = cfg["CUT"]
    
    # ── 강력 4 BOOSTER ──
    if s_now > 0.3 and chg > 0.2 and side == "short":
        return (BOOST, "BOOST_TopReversal")        # PF 15.51
    if s_now < -0.3 and chg < -0.2 and side == "long":
        return (BOOST, "BOOST_BottomReversal")     # PF 7.31
    if abs(s_now) <= 0.3 and chg > 0.2 and side == "long":
        return (BOOST, "BOOST_TrendStart_L")       # PF 8.77
    if abs(s_now) <= 0.3 and chg > 0.2 and side == "short":
        return (BOOST, "BOOST_TrendStart_S")       # PF 5.22
    
    # ── 약점 3 CUT ──
    if abs(s_now) <= 0.3 and abs(chg) <= 0.2 and side == "short":
        return (CUT, "CUT_NeutStable_S")           # PF 0.35
    if abs(s_now) <= 0.3 and chg < -0.2 and side == "short":
        return (CUT, "CUT_NeutFalling_S")          # PF 0.74
    if s_now < -0.3 and abs(chg) <= 0.2 and side == "long":
        return (CUT, "CUT_ShortStable_L")          # PF 0.47
    
    return (1.0, "default")

# ─── Side-aware ALPHA_MED ───
ALPHA_MED_RISK_LONG  = 0.8
ALPHA_MED_RISK_SHORT = 1.2

# ─── RP mult ───
RP_MULT_4H = {
    0: 2.0,
    1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0,
}

# ─── OUT 처리 ───
OUT_BEHAVIOR = "skip"

# ─── Notional cap ───
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


def classify_tier_stage4h(atoms_dict, side="long"):
    """
    Stage 4H Tier 판정 — SWEEP_BASE 를 GEM/ROOM_FVG/ROOM_ONLY 로 세분화.
    """
    def _g(k): return bool(atoms_dict.get(k, False))
    vol = _g("a_volume"); ovl = _g("a_overlap"); swp = _g("a_sweep")
    s13 = _g("a_score_ge13"); p1 = _g("a_pre_total_ge1")
    p4  = _g("a_pre_total_ge4"); wq1 = _g("a_wick_le_q1")
    mss = _g("a_mss"); fvg = _g("a_fvg"); rm  = _g("a_room")
    
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
    
    # ALPHA_MED
    if passes_win69_union(atoms_dict):
        return "ALPHA_MED"
    
    # SWEEP_BASE 세분화 (이전 Stage 4G 의 SWEEP_BASE 자리)
    if swp:
        if not rm:
            return "SWEEP_GEM"         # sweep + NOT room
        elif fvg:
            return "SWEEP_ROOM_FVG"    # sweep + room + fvg
        else:
            return "SWEEP_ROOM_ONLY"   # sweep + room + NOT fvg
    
    # COMPLETE_OUT
    return "COMPLETE_OUT"


def get_tier_risk_mult_4h(tier_label, side="long", symbol=None):
    """Tier 별 risk mult — scenario 설정 반영 + Stage 4I 차단 규칙."""
    if tier_label == "SKIP_MSS":
        return 0.0
    
    # ALPHA_MED side-aware
    if tier_label == "ALPHA_MED":
        return ALPHA_MED_RISK_LONG if side == "long" else ALPHA_MED_RISK_SHORT
    
    # COMPLETE_OUT
    if tier_label == "COMPLETE_OUT":
        if OUT_BEHAVIOR == "skip":
            return 0.0
        elif OUT_BEHAVIOR == "keep_r1":
            return 1.0
        elif OUT_BEHAVIOR == "keep_r05":
            return 0.5
        return 0.0
    
    # ─── Stage 4I 차단 규칙 ───
    # SWEEP_GEM SHORT 차단 (LONG only)
    if tier_label == "SWEEP_GEM" and GEM_LONG_ONLY and side == "short":
        return 0.0
    # SWEEP_ROOM_ONLY 심볼 블랙리스트
    if tier_label == "SWEEP_ROOM_ONLY" and symbol is not None and symbol in ROOM_ONLY_SYMBOL_BLACKLIST:
        return 0.0
    
    # SWEEP 계열 — scenario 에 따라
    if tier_label in ("SWEEP_GEM", "SWEEP_ROOM_FVG", "SWEEP_ROOM_ONLY"):
        return SWEEP_RISK_BY_SCENARIO[SCENARIO][tier_label]
    
    # 공통 Tier
    return TIER_RISK_MULT_COMMON.get(tier_label, 1.0)


def get_tier_cap_4h(tier_label):
    return TIER_CAP_4H.get(tier_label, 3.0)


# ─── 하위 호환 alias (simulate 내부 호출 유지) ───
TIER_RISK_MULT_4G = TIER_RISK_MULT_COMMON
TIER_RISK_MULT_4F = TIER_RISK_MULT_COMMON
TIER_RISK_MULT_4E = TIER_RISK_MULT_COMMON
RP_MULT_4G = RP_MULT_4H
RP_MULT_4F = RP_MULT_4H
RP_MULT_4E = RP_MULT_4H

classify_tier_stage4g = classify_tier_stage4h
get_tier_risk_mult_4g = get_tier_risk_mult_4h
get_tier_cap_4g       = get_tier_cap_4h

def classify_tier_stage4f(atoms_dict):
    return classify_tier_stage4h(atoms_dict, side="long")
def classify_tier_stage4e(atoms_dict):
    return classify_tier_stage4h(atoms_dict, side="long")
def get_tier_risk_mult_4f(tier_label, symbol=None):
    return get_tier_risk_mult_4h(tier_label, side="long", symbol=symbol)
def get_tier_risk_mult_4e(tier_label, symbol=None):
    return get_tier_risk_mult_4h(tier_label, side="long", symbol=symbol)

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



# %%
# =========================================================
# Cell 3: 데이터 로드 + 지표 계산 (v24_final 와 동일)
# =========================================================

def make_deposit_schedule(first_timestamp, monthly_amount, n_months=5):
    first_ts = pd.Timestamp(first_timestamp)
    if first_ts.tz is None:
        first_ts = first_ts.tz_localize("UTC")
    else:
        first_ts = first_ts.tz_convert("UTC")
    first_month_start = pd.Timestamp(year=first_ts.year, month=first_ts.month, day=1, tz="UTC")
    deposit_times = []
    cur = first_month_start + pd.offsets.MonthBegin(1)
    for _ in range(n_months):
        deposit_times.append(cur)
        cur = cur + pd.offsets.MonthBegin(1)
    return pd.DataFrame({"deposit_time": deposit_times, "deposit_amount": [monthly_amount] * len(deposit_times)})


def apply_pending_deposits(balance, current_time, deposit_df, deposit_idx):
    while deposit_idx < len(deposit_df) and deposit_df.loc[deposit_idx, "deposit_time"] <= current_time:
        balance += deposit_df.loc[deposit_idx, "deposit_amount"]
        deposit_idx += 1
    return balance, deposit_idx


def parse_reason_set(reason_str):
    if pd.isna(reason_str) or str(reason_str).strip() == "":
        return set()
    return set([x.strip() for x in str(reason_str).split(",") if x.strip()])


def overlap_size(a_low, a_high, b_low, b_high):
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def load_yahoo_1h(symbol, period=PERIOD_1H, interval=INTERVAL_1H, tz=TIMEZONE):
    df = yf.download(
        tickers=symbol, period=period, interval=interval,
        auto_adjust=False, actions=False, prepost=False, progress=False, threads=False,
    )
    if df is None or len(df) == 0:
        raise ValueError(f"No data returned from Yahoo for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Adj Close":"adj_close","Volume":"volume"}).copy()
    needed = ["open","high","low","close","volume"]
    for c in needed:
        if c not in df.columns:
            raise ValueError(f"Missing column {c} in Yahoo response for {symbol}")
    df = df[needed].copy().reset_index()
    ts_col = None
    for c in df.columns:
        if str(c).lower() in ["datetime","date"]:
            ts_col = c
            break
    if ts_col is None:
        raise ValueError(f"Could not find timestamp column for {symbol}")
    df = df.rename(columns={ts_col:"timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp_ny"] = df["timestamp"].dt.tz_convert(tz)
    return df.sort_values("timestamp").reset_index(drop=True)


def resample_ohlcv(df_h1, rule):
    """
    원자재 24/7 데이터용 - floor 방식 (timezone-aware bin 경계).
    rule:
      - '4h'  → 4시간 블록
      - '12h' → 12시간 블록
      - '1D'  → 일단위
    """
    df = df_h1.copy().sort_values("timestamp").reset_index(drop=True)
    if rule.endswith("h"):
        hours = int(rule[:-1])
        df["block_ts"] = df["timestamp"].dt.floor(f"{hours}h")
    elif rule.endswith("D") or rule.endswith("d"):
        df["block_ts"] = df["timestamp"].dt.floor("1D")
    else:
        raise ValueError(f"Unsupported resample rule: {rule}")
    agg = (
        df.groupby("block_ts", as_index=False)
        .agg(
            timestamp=("timestamp", "last"),
            timestamp_ny=("timestamp_ny", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    )
    return agg.sort_values("timestamp").reset_index(drop=True)


def build_h4_from_h1(df_htf):
    return resample_ohlcv(df_htf, LTF_RESAMPLE)


def build_htf_from_h1(df_htf):
    return resample_ohlcv(df_htf, HTF_RESAMPLE)


# =========================================================
# [PATCHED v34 — H1/LTF CHoCH Trend 이식, 2026-05-22]
# 크립토 v3 의 apply_h1_choch_trend 를 원자재(HTF/LTF)에 이식.
#   df_htf (구조 TF) 의 trend 컬럼을 df_ltf (하위 TF) CHoCH 기반으로 교체.
#   USE_LTF_CHOCH_TREND=True 일 때만 prepare_symbol 에서 호출됨.
#   df_ltf 에 apply_choch 가 이미 적용돼 있어야 함 (bull_choch/bear_choch).
# =========================================================
def apply_ltf_choch_trend(df_htf, df_ltf):
    """
    H4 dataframe 의 trend 컬럼을 H1 CHoCH state 기반으로 갈아끼움.

    각 H4 시점 t 에 대해:
      - df_ltf 에서 timestamp <= t 인 마지막 bull_choch 시점과
        마지막 bear_choch 시점을 비교해 더 최근인 쪽이 trend
      - 둘 다 없음 → "neutral"
      - 하나만 있음 → 그 방향
      - 동시 발생 (희박) → "neutral"

    SMC 정통: CHoCH state 는 반대 방향 CHoCH 가 나올 때까지 유효.
    stale 컷오프 없음.

    [선결 조건] df_ltf 에 apply_choch() 가 이미 적용되어 있어야 함
    (df_ltf["bull_choch"], df_ltf["bear_choch"] 컬럼 존재).
    """
    df_htf = df_htf.copy()

    if "bull_choch" not in df_ltf.columns or "bear_choch" not in df_ltf.columns:
        raise ValueError(
            "apply_h1_choch_trend: df_ltf 에 bull_choch/bear_choch 컬럼이 없음. "
            "apply_choch(df_ltf) 호출 후 사용할 것."
        )

    # H1 에서 CHoCH 발생한 timestamp 만 추출 (이미 시간순 정렬됨)
    bull_ts_arr = df_ltf.loc[df_ltf["bull_choch"], "timestamp"].sort_values().values
    bear_ts_arr = df_ltf.loc[df_ltf["bear_choch"], "timestamp"].sort_values().values

    n_bull = len(bull_ts_arr)
    n_bear = len(bear_ts_arr)
    h4_ts = df_htf["timestamp"].values
    n_h4 = len(h4_ts)

    # searchsorted: t 이하의 마지막 인덱스 찾기 (없으면 -1)
    if n_bull > 0:
        bull_last_pos = np.searchsorted(bull_ts_arr, h4_ts, side="right") - 1
    else:
        bull_last_pos = np.full(n_h4, -1, dtype=int)

    if n_bear > 0:
        bear_last_pos = np.searchsorted(bear_ts_arr, h4_ts, side="right") - 1
    else:
        bear_last_pos = np.full(n_h4, -1, dtype=int)

    trends = np.array(["neutral"] * n_h4, dtype=object)
    # ⭐ Step 1 모니터링: 진입 시점 H4 row에서 마지막 CHoCH ts/방향 직접 lookup 가능하도록 컬럼 추가
    last_choch_ts = np.array([pd.NaT] * n_h4, dtype=object)
    last_choch_dir = np.array(["none"] * n_h4, dtype=object)

    for k in range(n_h4):
        bp = bull_last_pos[k]
        rp = bear_last_pos[k]
        has_bull = bp >= 0
        has_bear = rp >= 0

        if not has_bull and not has_bear:
            continue  # neutral, no CHoCH ever
        if has_bull and not has_bear:
            trends[k] = "up"
            last_choch_ts[k] = bull_ts_arr[bp]
            last_choch_dir[k] = "bull"
            continue
        if has_bear and not has_bull:
            trends[k] = "down"
            last_choch_ts[k] = bear_ts_arr[rp]
            last_choch_dir[k] = "bear"
            continue
        # 둘 다 있음 — 더 최근인 쪽
        tb = bull_ts_arr[bp]
        tr_ = bear_ts_arr[rp]
        if tb > tr_:
            trends[k] = "up"
            last_choch_ts[k] = tb
            last_choch_dir[k] = "bull"
        elif tr_ > tb:
            trends[k] = "down"
            last_choch_ts[k] = tr_
            last_choch_dir[k] = "bear"
        else:
            # 동시 발생 — neutral, 둘 중 아무거나 기록 (매우 희박)
            last_choch_ts[k] = tb
            last_choch_dir[k] = "tie"

    df_htf["trend"] = trends
    df_htf["last_choch_ts"] = last_choch_ts
    df_htf["last_choch_dir"] = last_choch_dir

    # 진단용 통계 출력
    n_up = int((trends == "up").sum())
    n_dn = int((trends == "down").sum())
    n_nu = int((trends == "neutral").sum())
    print(
        f"  [LTF-CHoCH-Trend] H4 bars={n_h4} | "
        f"up={n_up} ({n_up/max(n_h4,1)*100:.1f}%) | "
        f"down={n_dn} ({n_dn/max(n_h4,1)*100:.1f}%) | "
        f"neutral={n_nu} ({n_nu/max(n_h4,1)*100:.1f}%) | "
        f"H1_bull_choch_n={n_bull} H1_bear_choch_n={n_bear}"
    )
    return df_htf





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
        prev_high = data["high"].iloc[i-mss_lookback:i].max()
        prev_low = data["low"].iloc[i-mss_lookback:i].min()
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
        bull = data.loc[i, "close"] > data.loc[i, "open"] and data.loc[i, "body_ratio"] >= disp_body_ratio and data.loc[i, "range"] >= atr_val * disp_atr_mult
        bear = data.loc[i, "close"] < data.loc[i, "open"] and data.loc[i, "body_ratio"] >= disp_body_ratio and data.loc[i, "range"] >= atr_val * disp_atr_mult
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
        if data.loc[i, "low"] > data.loc[i-2, "high"]:
            data.loc[i, "bull_fvg_low"] = data.loc[i-2, "high"]
            data.loc[i, "bull_fvg_high"] = data.loc[i, "low"]
            data.loc[i, "bull_fvg_size"] = data.loc[i, "low"] - data.loc[i-2, "high"]
        if data.loc[i, "high"] < data.loc[i-2, "low"]:
            data.loc[i, "bear_fvg_low"] = data.loc[i, "high"]
            data.loc[i, "bear_fvg_high"] = data.loc[i-2, "low"]
            data.loc[i, "bear_fvg_size"] = data.loc[i-2, "low"] - data.loc[i, "high"]
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
            for j in range(i-1, max(i-ob_lookback-1, -1), -1):
                if data.loc[j, "close"] < data.loc[j, "open"]:
                    data.loc[i, "bull_ob_low"] = data.loc[j, "low"]
                    data.loc[i, "bull_ob_high"] = data.loc[j, "high"]
                    data.loc[i, "bull_ob_size"] = data.loc[j, "high"] - data.loc[j, "low"]
                    break
        if data.loc[i, "bear_disp"]:
            for j in range(i-1, max(i-ob_lookback-1, -1), -1):
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
    for i in range(swing_len, len(data)-swing_len):
        if data.loc[i, "high"] == data["high"].iloc[i-swing_len:i+swing_len+1].max():
            data.loc[i, "pivot_high"] = data.loc[i, "high"]
        if data.loc[i, "low"] == data["low"].iloc[i-swing_len:i+swing_len+1].min():
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
        if pd.notna(data.loc[i, "pivot_high"]):
            prev_high = last_high
            last_high = data.loc[i, "pivot_high"]
        if pd.notna(data.loc[i, "pivot_low"]):
            prev_low = last_low
            last_low = data.loc[i, "pivot_low"]
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
        bias = data.loc[i-1, "structure_bias"]
        last_high = data.loc[i-1, "last_pivot_high"]
        last_low = data.loc[i-1, "last_pivot_low"]
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


def is_fresh_zone(df_local, idx, zone_low, zone_high):
    touch_count = 0
    end_idx = min(idx + 3, len(df_local) - 1)
    for t in range(idx + 1, end_idx + 1):
        touched = (df_local.loc[t, "high"] >= zone_low) and (df_local.loc[t, "low"] <= zone_high)
        if touched:
            touch_count += 1
    return touch_count <= 1


# =========================================================
# Phase A/B + Tax helpers
# =========================================================

def get_current_phase(balance_usd):
    return "B" if balance_usd >= TARGET_BALANCE_USD else "A"


def get_phase_risk_pct(phase, symbol):
    if phase == "B":
        return PHASE_B_RISK.get(symbol, PHASE_A_RISK.get(symbol, 0.01))
    return PHASE_A_RISK.get(symbol, 0.01)


def cap_and_extract_excess(balance_usd):
    if balance_usd <= TARGET_BALANCE_USD:
        return balance_usd, 0.0
    excess = balance_usd - TARGET_BALANCE_USD
    return TARGET_BALANCE_USD, excess


def calculate_annual_tax_usd(annual_pnl_usd):
    annual_pnl_krw = annual_pnl_usd * KRW_PER_USD
    taxable_krw = max(0.0, annual_pnl_krw - TAX_DEDUCTION_KRW)
    tax_krw = taxable_krw * TAX_RATE
    return tax_krw / KRW_PER_USD


print("v25 Part 2 loaded: helpers + indicators + Phase/Tax")


# =========================================================
# Structure + Freshness + Volume Filter (v24 동일)
# =========================================================

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


def evaluate_freshness_at_entry(df_local, structure, entry_idx):
    side = structure["type"]
    side_tag = "bull" if side == "long" else "bear"
    bonus = 0.0
    fresh_reasons = []
    if structure.get("has_ob"):
        if is_zone_fresh_at_entry(df_local, structure["zone_created_idx"], entry_idx, structure["ob_low"], structure["ob_high"]):
            bonus += 1.0
            fresh_reasons.append(f"fresh_{side_tag}_ob")
    if structure.get("has_fvg"):
        if is_zone_fresh_at_entry(df_local, structure["zone_created_idx"], entry_idx, structure["fvg_low"], structure["fvg_high"]):
            bonus += 0.5
            fresh_reasons.append(f"fresh_{side_tag}_fvg")
    return bonus, fresh_reasons


def passes_volume_filter(df, zone_created_idx):
    if not USE_VOLUME_FILTER:
        return True, "vol_off"
    if "volume" not in df.columns:
        return True, "vol_no_data"
    start = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
    end = zone_created_idx
    if end <= start:
        return True, "vol_window_empty"
    try:
        avg_vol = df.loc[start:end - 1, "volume"].mean()
        zone_vol = df.loc[zone_created_idx, "volume"]
    except Exception:
        return True, "vol_index_err"
    if pd.isna(avg_vol) or avg_vol <= 0:
        return True, "vol_no_avg"
    if pd.isna(zone_vol) or zone_vol <= 0:
        return True, "vol_zone_invalid"
    ratio_avg = zone_vol / avg_vol
    if ratio_avg < VOLUME_SPIKE_MULT:
        return False, f"vol_low({ratio_avg:.2f})"
    if VOLUME_STRICT_MODE and zone_created_idx >= 1:
        prev_vol = df.loc[zone_created_idx - 1, "volume"]
        if pd.notna(prev_vol) and prev_vol > 0:
            ratio_prev = zone_vol / prev_vol
            if ratio_prev < VOLUME_PREV_MULT:
                return False, f"vol_prev_low({ratio_prev:.2f})"
    return True, f"vol_spike({ratio_avg:.2f})"


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


def compute_pre_entry_confluence(df_htf, df_ltf, htf_entry_idx, zone_low, zone_high,
                                  lookback_ltf_bars=8):
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
        o = float(r["open"])
        c = float(r["close"])
        h = float(r["high"])
        l = float(r["low"])
        body_top = max(o, c)
        body_bot = min(o, c)
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
# ★★★ v26 신규: classify_tier_v19b_rp_boost ★★★
# =========================================================
def classify_tier_v19b_rp_boost(pre_total, sweep_count, score, wick_ratio_5, run_potential):
    """
    v1.9b TIER + RP_BOOST 통합 분류 (4H tier 와 별도 layer).
    
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
        base_mult = TIER_RISK_V19B_S
    elif in_d and not in_wick:
        tier = "A"
        base_mult = TIER_RISK_V19B_A
    elif not in_d and in_wick:
        tier = "B"
        base_mult = TIER_RISK_V19B_B
    elif pre_total >= 1:
        tier = "C"
        base_mult = TIER_RISK_V19B_C
    else:
        # pre_total == 0 → Tier D → skip
        return "D", 0.0, "tier_d_skip"
    
    final_mult = base_mult * rp_mult
    return tier, final_mult, rp_action


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

    structure_wait = 10
    post_structure_zone_window = 6
    zone_max_age = 16
    structures = []

    for i in range(60, len(df)-1):
        short_sweep = bool(df.loc[i, "pivot_sweep_high"] or df.loc[i, "recent_sweep_high"])
        if short_sweep:
            for j in range(i+1, min(i+structure_wait+1, len(df))):
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
                for k in range(structure_idx+1, min(structure_idx+post_structure_zone_window+1, len(df))):
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
                        if is_fresh_zone(df, k, ob_low, ob_high):
                            score_k += 1.0
                            reasons_k.append("fresh_bear_ob")
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
                        if is_fresh_zone(df, k, fvg_low, fvg_high):
                            score_k += 0.5
                            reasons_k.append("fresh_bear_fvg")
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
                            "type":"short","sweep_idx":i,"structure_idx":structure_idx,"zone_created_idx":k,
                            "zone_low":float(zone_low),"zone_high":float(zone_high),"sweep_ref":float(df.loc[i, "high"]),
                            "expire_idx":min(k + zone_max_age, len(df)-1),"used":False,"score":float(score_k),"reasons":",".join(reasons_k),
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
            for j in range(i+1, min(i+structure_wait+1, len(df))):
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
                for k in range(structure_idx+1, min(structure_idx+post_structure_zone_window+1, len(df))):
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
                        if is_fresh_zone(df, k, ob_low, ob_high):
                            score_k += 1.0
                            reasons_k.append("fresh_bull_ob")
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
                        if is_fresh_zone(df, k, fvg_low, fvg_high):
                            score_k += 0.5
                            reasons_k.append("fresh_bull_fvg")
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
                            "type":"long","sweep_idx":i,"structure_idx":structure_idx,"zone_created_idx":k,
                            "zone_low":float(zone_low),"zone_high":float(zone_high),"sweep_ref":float(df.loc[i, "low"]),
                            "expire_idx":min(k + zone_max_age, len(df)-1),"used":False,"score":float(score_k),"reasons":",".join(reasons_k),
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


# =========================================================
# Trade simulator (v24 동일 — TP/SL 휴리스틱은 그대로, 4K 도 동일 사용)
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

def get_run_potential(df_local, i, structure):
    side = structure["type"]
    reasons = parse_reason_set(structure["reasons"])
    rscore = 0
    tags = []
    if side == "long" and df_local.loc[i, "trend"] == "up":
        rscore += 1; tags.append("trend_align")
    if side == "short" and df_local.loc[i, "trend"] == "down":
        rscore += 1; tags.append("trend_align")
    if "bull_mss" in reasons or "bear_mss" in reasons:
        rscore += 1; tags.append("mss")
    if "valid_bull_fvg" in reasons or "valid_bear_fvg" in reasons:
        rscore += 1; tags.append("fvg")
    if "bull_ob_fvg_overlap" in reasons or "bear_ob_fvg_overlap" in reasons:
        rscore += 1; tags.append("overlap")
    if side == "long":
        entry_proxy = structure["zone_low"] + (structure["zone_high"] - structure["zone_low"]) * 0.40
        raw_sl = structure["sweep_ref"] - (df_local.loc[i, "atr"] if pd.notna(df_local.loc[i, "atr"]) else 0.0) * 0.08
        sl_proxy = clamp_stop_for_long(entry_proxy, raw_sl, df_local.loc[i, "atr"])
        if sl_proxy < entry_proxy:
            risk = entry_proxy - sl_proxy
            room = (df_local.loc[i, "pd_high"] - entry_proxy) if pd.notna(df_local.loc[i, "pd_high"]) else 0.0
            if risk > 0 and pd.notna(room) and room >= risk * 2.8:
                rscore += 1; tags.append("room")
    else:
        entry_proxy = structure["zone_low"] + (structure["zone_high"] - structure["zone_low"]) * 0.60
        raw_sl = structure["sweep_ref"] + (df_local.loc[i, "atr"] if pd.notna(df_local.loc[i, "atr"]) else 0.0) * 0.08
        sl_proxy = clamp_stop_for_short(entry_proxy, raw_sl, df_local.loc[i, "atr"])
        if sl_proxy > entry_proxy:
            risk = sl_proxy - entry_proxy
            room = (entry_proxy - df_local.loc[i, "pd_low"]) if pd.notna(df_local.loc[i, "pd_low"]) else 0.0
            if risk > 0 and pd.notna(room) and room >= risk * 2.8:
                rscore += 1; tags.append("room")
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
        return {"name":"expansion","targets":[(1.0,0.15),(2.0,0.15),(3.0,0.10)],"runner_frac":0.60,"trail_activate_rr":4.0,"be_after_rr":1.5,"max_hold_bars":20}
    return {"name":"base","targets":[(1.0,0.25),(2.0,0.20),(3.0,0.15)],"runner_frac":0.40,"trail_activate_rr":3.0,"be_after_rr":1.0,"max_hold_bars":12}

def update_trailing_stop(df_local, j, side, current_stop, entry):
    if j - 1 < 0:
        return current_stop
    prev_high = df_local.loc[j-1, "high"]
    prev_low = df_local.loc[j-1, "low"]
    prev_range = prev_high - prev_low
    atr_val = df_local.loc[j-1, "atr"] if pd.notna(df_local.loc[j-1, "atr"]) else 0.0
    if side == "long":
        candidate = prev_low + prev_range * 0.50 - atr_val * 0.10
        candidate = max(candidate, entry)
        return max(current_stop, candidate)
    candidate = prev_high - prev_range * 0.50 + atr_val * 0.10
    candidate = min(candidate, entry)
    return min(current_stop, candidate)

def calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low):
    if risk_per_unit <= 0:
        return np.nan
    if side == "long":
        return (bar_high - entry) / risk_per_unit
    return (entry - bar_low) / risk_per_unit

def apply_entry_slippage(side, entry):
    slip = entry * (ENTRY_SLIPPAGE_BPS / 10000.0)
    return entry + slip if side == "long" else entry - slip

def apply_exit_slippage(side, exit_price, exit_type="generic"):
    slip = exit_price * (EXIT_SLIPPAGE_BPS / 10000.0)
    return exit_price - slip if side == "long" else exit_price + slip


def simulate_trade_with_plan(df_local, entry_idx, side, entry, sl, qty, fee_rate, grade, plan, use_seq_runner_protection=False):
    eps = 1e-12
    entry_time = df_local.loc[entry_idx, "timestamp"]
    entry = apply_entry_slippage(side, entry)
    risk_per_unit = abs(entry - sl)
    max_hold_bars = plan["max_hold_bars"]
    targets = []
    for rr, frac in plan["targets"]:
        px = entry + risk_per_unit * rr if side == "long" else entry - risk_per_unit * rr
        targets.append({"rr":rr, "frac":frac, "price":px, "hit":False})
    remaining_qty = qty
    realized_pnl = 0.0
    exit_fees = 0.0
    current_stop = sl
    be_moved = False
    runner_active = False
    exit_reason = None
    exit_idx = None
    exit_time = None
    final_exit_price = np.nan
    entry_fee = abs(entry * qty) * fee_rate
    max_rr_seen = 0.0
    runner_max_rr_seen = np.nan
    bars_to_2r = np.nan
    bars_spent_above_2r = 0
    max_rr_after_2r = 0.0
    cond_count_final = 0
    runner_candidate_2of3 = False
    post_2of3_apply_ok = False
    runner_protected = False
    stop_type_last = "initial"
    # ★ v31: runner 활성화 시점 기록 (추가 진입 허용 판단용)
    runner_activated_time = None
    runner_activated_idx = None
    target1_hit_time = None
    target1_hit_idx = None

    def lock_profit_stop():
        return entry + risk_per_unit * RUNNER_PROTECT_LOCKED_R if side == "long" else entry - risk_per_unit * RUNNER_PROTECT_LOCKED_R

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
        nonlocal bars_to_2r, bars_spent_above_2r, max_rr_after_2r
        nonlocal cond_count_final, runner_candidate_2of3, post_2of3_apply_ok, runner_protected
        nonlocal current_stop, stop_type_last
        hold_bar = j - entry_idx
        if favorable_rr >= 2.0:
            bars_spent_above_2r += 1
            if pd.isna(bars_to_2r):
                bars_to_2r = hold_bar
            if favorable_rr > 2.0:
                max_rr_after_2r = max(max_rr_after_2r, favorable_rr - 2.0)
        cond_fast_2r = pd.notna(bars_to_2r) and bars_to_2r <= FAST_2R_BARS_MAX
        cond_hold_above_2r = bars_spent_above_2r >= ABOVE_2R_BARS_MIN
        cond_extra_expand = max_rr_after_2r >= MAX_RR_AFTER_2R_MIN
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

    def hit_target(target, fill_price=None):
        nonlocal remaining_qty, realized_pnl, exit_fees, be_moved, runner_active, current_stop, stop_type_last
        if target["hit"]:
            return
        part_qty = min(qty * target["frac"], remaining_qty)
        if part_qty <= eps:
            target["hit"] = True
            return
        px = target["price"] if fill_price is None else fill_price
        px = apply_exit_slippage(side, px, exit_type="target")
        if side == "long":
            realized_pnl += (px - entry) * part_qty
        else:
            realized_pnl += (entry - px) * part_qty
        exit_fees += abs(px * part_qty) * fee_rate
        remaining_qty -= part_qty
        target["hit"] = True
        if (not be_moved) and (target["rr"] >= plan["be_after_rr"]):
            be_moved = True
            current_stop = entry
            stop_type_last = "be"
        if plan["trail_activate_rr"] is not None and target["rr"] >= plan["trail_activate_rr"] and plan["runner_frac"] > 0:
            runner_active = True

    for j in range(entry_idx+1, min(len(df_local), entry_idx+max_hold_bars+1)):
        bar_open = df_local.loc[j, "open"]
        bar_high = df_local.loc[j, "high"]
        bar_low = df_local.loc[j, "low"]
        bar_close = df_local.loc[j, "close"]
        favorable_rr = calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low)
        register_rr_stats(j, favorable_rr)
        update_max_rr(bar_high, bar_low)
        # ★ v31: runner 활성화 / 1R hit 시점 기록 ★
        _runner_active_before = runner_active
        _target1_hit_before = any(t["hit"] and abs(t["rr"] - 1.0) < 1e-9 for t in targets)
        if remaining_qty <= eps:
            exit_reason = "all_targets"
            exit_idx = j
            exit_time = df_local.loc[j, "timestamp"]
            final_exit_price = bar_close
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
                        fill_px = apply_exit_slippage(side, current_stop, exit_type="stop")
                        realized_pnl += (fill_px - entry) * remaining_qty
                        exit_fees += abs(fill_px * remaining_qty) * fee_rate
                        remaining_qty = 0.0
                        exit_reason = "stop"
                        exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]
                        final_exit_price = fill_px
                        break
            else:
                if evt == "low":
                    for tgt in targets:
                        if (not tgt["hit"]) and (bar_low <= tgt["price"]):
                            hit_target(tgt)
                elif evt == "high":
                    if bar_high >= current_stop and remaining_qty > eps:
                        fill_px = apply_exit_slippage(side, current_stop, exit_type="stop")
                        realized_pnl += (entry - fill_px) * remaining_qty
                        exit_fees += abs(fill_px * remaining_qty) * fee_rate
                        remaining_qty = 0.0
                        exit_reason = "stop"
                        exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]
                        final_exit_price = fill_px
                        break
        # ★ v31: runner 활성화 / target1 hit 변화 시점 기록 ★
        if (not _runner_active_before) and runner_active and runner_activated_time is None:
            runner_activated_idx = j
            runner_activated_time = df_local.loc[j, "timestamp"]
        if (not _target1_hit_before):
            _target1_hit_after = any(t["hit"] and abs(t["rr"] - 1.0) < 1e-9 for t in targets)
            if _target1_hit_after and target1_hit_time is None:
                target1_hit_idx = j
                target1_hit_time = df_local.loc[j, "timestamp"]
        if exit_reason is not None:
            break
        if j - entry_idx >= max_hold_bars:
            if remaining_qty > eps:
                fill_px = apply_exit_slippage(side, bar_close, exit_type="time_exit")
                if side == "long":
                    realized_pnl += (fill_px - entry) * remaining_qty
                else:
                    realized_pnl += (entry - fill_px) * remaining_qty
                exit_fees += abs(fill_px * remaining_qty) * fee_rate
                remaining_qty = 0.0
                final_exit_price = fill_px
            exit_reason = "time_exit"
            exit_idx = j
            exit_time = df_local.loc[j, "timestamp"]
            break

    if exit_reason is None:
        j = len(df_local)-1
        bar_close = df_local.loc[j, "close"]
        if remaining_qty > eps:
            fill_px = apply_exit_slippage(side, bar_close, exit_type="close_at_end")
            if side == "long":
                realized_pnl += (fill_px - entry) * remaining_qty
            else:
                realized_pnl += (entry - fill_px) * remaining_qty
            exit_fees += abs(fill_px * remaining_qty) * fee_rate
            remaining_qty = 0.0
            final_exit_price = fill_px
        exit_reason = "close_at_end"
        exit_idx = j
        exit_time = df_local.loc[j, "timestamp"]

    net_pnl = realized_pnl - entry_fee - exit_fees
    risk_amount = risk_per_unit * qty
    r_multiple = net_pnl / risk_amount if risk_amount > 0 else np.nan
    proxy_runner = bool((True if not RUNNER_PROXY_TARGET3 else any([t["hit"] and abs(t["rr"] - 3.0) < 1e-9 for t in targets])) and (max_rr_seen >= RUNNER_PROXY_MAX_RR))
    if exit_reason in ["time_exit", "close_at_end"]:
        result = exit_reason
    elif net_pnl >= 0:
        result = "win"
    else:
        result = "loss"

    return {
        "entry_time": entry_time, "entry_exec": entry, "exit_time": exit_time, "exit_idx": exit_idx,
        "exit_reason": exit_reason, "exit_price_exec": final_exit_price, "result": result,
        "net_pnl": net_pnl, "risk_amount": risk_amount, "r_multiple": r_multiple,
        "be_moved": be_moved, "runner_active": runner_active, "hold_bars": exit_idx - entry_idx,
        "target1_hit": any([t["hit"] and abs(t["rr"] - 1.0) < 1e-9 for t in targets]),
        "target2_hit": any([t["hit"] and abs(t["rr"] - 2.0) < 1e-9 for t in targets]),
        "target3_hit": any([t["hit"] and abs(t["rr"] - 3.0) < 1e-9 for t in targets]),
        "max_rr_seen": max_rr_seen, "runner_max_rr_seen": runner_max_rr_seen,
        "bars_to_2r": bars_to_2r, "bars_spent_above_2r": bars_spent_above_2r,
        "max_rr_after_2r": max_rr_after_2r, "cond_count_final": cond_count_final,
        "runner_candidate_2of3": runner_candidate_2of3, "post_2of3_apply_ok": post_2of3_apply_ok,
        "runner_protected": runner_protected, "stop_type_last": stop_type_last, "proxy_runner": proxy_runner,
        # ★ v31: runner 활성화 / 1R hit 시점 ★
        "runner_activated_time": runner_activated_time,
        "runner_activated_idx": runner_activated_idx,
        "target1_hit_time": target1_hit_time,
        "target1_hit_idx": target1_hit_idx,
    }


print("v25 Part 3 loaded: structures + simulator")


# =========================================================
# Cell 4: prepare symbol data
# =========================================================

def prepare_symbol(symbol_key, yahoo_symbol, htf_rule, ltf_rule):
    sep = '=' * 80
    print('')
    print(sep)
    print(f'🔧 PREPARING {symbol_key} ({yahoo_symbol}) | HTF={htf_rule} LTF={ltf_rule}')
    print(sep)
    df_h1_raw = load_yahoo_1h(yahoo_symbol, period=PERIOD_1H, interval=INTERVAL_1H, tz=TIMEZONE)
    print(f"H1 rows (raw): {len(df_h1_raw):,} | {df_h1_raw['timestamp'].min()} → {df_h1_raw['timestamp'].max()}")
    df_ltf = resample_ohlcv(df_h1_raw, ltf_rule)
    df_htf = resample_ohlcv(df_h1_raw, htf_rule)
    print(f"LTF ({ltf_rule}) rows: {len(df_ltf):,} | HTF ({htf_rule}) rows: {len(df_htf):,}")

    # HTF: 구조 분석용 지표
    print(f"Applying structure indicators on HTF ({htf_rule})...")
    df_htf = df_htf.copy()
    df_htf = apply_basic_indicators(df_htf)
    df_htf = apply_mss(df_htf, mss_lookback=8)
    df_htf = apply_displacement(df_htf)
    df_htf = apply_fvg(df_htf)
    df_htf = apply_ob(df_htf, ob_lookback=8)
    df_htf = apply_pd(df_htf, pd_lookback=40)
    df_htf = apply_pivots(df_htf, swing_len=3)
    df_htf = apply_structure_bias(df_htf)
    df_htf = apply_choch(df_htf, break_atr_mult=0.18)
    df_htf = apply_h4_market_state(df_htf, transition_bars=8)

    # LTF: confluence 계산용
    print(f"Applying refine/choch indicators on LTF ({ltf_rule})...")
    df_ltf = df_ltf.copy()
    df_ltf = apply_basic_indicators(df_ltf)
    df_ltf = apply_mss(df_ltf)
    df_ltf = apply_displacement(df_ltf)
    df_ltf = apply_fvg(df_ltf)
    df_ltf = apply_ob(df_ltf)
    df_ltf = apply_pd(df_ltf, pd_lookback=40)
    df_ltf = apply_pivots(df_ltf, swing_len=3)
    df_ltf = apply_structure_bias(df_ltf)
    df_ltf = apply_choch(df_ltf, break_atr_mult=0.12)
    df_ltf = apply_sweep_flags(df_ltf, recent_sweep_n=10)

    # ★★★ [PATCHED v34 — LTF CHoCH Trend 교체, 2026-05-22] ★★★
    # USE_LTF_CHOCH_TREND=True 면 df_htf 의 EMA trend 를
    # df_ltf 의 CHoCH state 기반으로 갈아끼움 (크립토 v3 방식).
    # build_structures 전에 적용해야 trend 가 구조 분석/진입 판정에 반영됨.
    if USE_LTF_CHOCH_TREND:
        print(f"  → LTF CHoCH trend 적용 (EMA trend 대체)")
        df_htf = apply_ltf_choch_trend(df_htf, df_ltf)
    else:
        print(f"  → 기존 EMA trend 유지 (USE_LTF_CHOCH_TREND=0)")

    print("Building structures on HTF...")
    df_htf, structures, structures_by_zone_created = build_structures(df_htf)
    print(f"Total HTF structures found: {len(structures)}")

    return {
        "symbol_key": symbol_key, "yahoo_symbol": yahoo_symbol,
        "htf_rule": htf_rule, "ltf_rule": ltf_rule,
        "df_ltf": df_ltf, "df_htf": df_htf,
        "structures": structures, "structures_by_zone_created": structures_by_zone_created,
    }


# =========================================================
# ★★★ Stage 4K Candidate Generation ★★★
#  - 보수 entry: LONG=zone_high (frac=1.0), SHORT=zone_low (frac=0.0)
#  - refine OFF
#  - atomic 12 계산 → tier_label 만 candidate 에 저장 (실 risk_mult 는 simulate_portfolio 에서)
#  - 4I/4J 차단은 simulate_portfolio 에서 적용 (sentiment 계산 위해)
# =========================================================

def _prepare_one(args):
    symbol_key, yahoo_symbol, htf_rule, ltf_rule = args
    return symbol_key, prepare_symbol(symbol_key, yahoo_symbol, htf_rule, ltf_rule)


def _generate_one(pack):
    return pack["symbol_key"], generate_trade_candidates_for_symbol(pack)


def prepare_all_symbols_parallel(index_symbols, symbol_tf_map, max_workers=None):
    """심볼별 데이터 다운로드 + 지표 + 구조 병렬 (ProcessPool, CPU bound)."""
    tasks = [
        (sk, ys, *symbol_tf_map[sk])
        for sk, ys in index_symbols.items()
    ]
    if max_workers is None:
        max_workers = min(len(tasks), max(1, mp.cpu_count() - 1))
    print(f"\n[병렬] prepare_symbol: {len(tasks)}심볼 × {max_workers} workers")
    results = {}
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_prepare_one, t): t[0] for t in tasks}
        for fut in as_completed(futures):
            sk, pack = fut.result()
            results[sk] = pack
            print(f"  ✓ {sk}: {len(pack['structures'])} structures")
    # INDEX_SYMBOLS 순서 유지
    return {sk: results[sk] for sk in index_symbols if sk in results}


def generate_candidates_all_parallel(prepared_data, max_workers=None):
    """심볼별 candidates 생성 병렬 (ProcessPool, CPU bound)."""
    import copy as _copy
    packs = []
    for sk, orig in prepared_data.items():
        packs.append({
            "symbol_key": orig["symbol_key"],
            "yahoo_symbol": orig["yahoo_symbol"],
            "htf_rule": orig["htf_rule"],
            "ltf_rule": orig["ltf_rule"],
            "df_ltf": orig["df_ltf"],
            "df_htf": orig["df_htf"],
            "structures": _copy.deepcopy(orig["structures"]),
            "structures_by_zone_created": _copy.deepcopy(orig["structures_by_zone_created"]),
        })
    if max_workers is None:
        max_workers = min(len(packs), max(1, mp.cpu_count() - 1))
    print(f"\n[병렬] candidates: {len(packs)}심볼 × {max_workers} workers")
    results = {}
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_generate_one, p): p["symbol_key"] for p in packs}
        for fut in as_completed(futures):
            sk, cand_pack = fut.result()
            results[sk] = cand_pack
            print(f"  ✓ {sk}: {len(cand_pack['candidates'])} candidates")
    return {sk: results[sk] for sk in prepared_data if sk in results}


def generate_trade_candidates_for_symbol(pack):
    df_htf = pack["df_htf"]
    df_ltf = pack["df_ltf"]
    structures = pack["structures"]
    structures_by_zone_created = pack["structures_by_zone_created"]
    symbol_key = pack["symbol_key"]
    yahoo_symbol = pack["yahoo_symbol"]

    candidates = []
    active_structures = []
    last_long_exit_idx = -9999
    last_short_exit_idx = -9999
    daily_trade_count = {}
    used_zone_ids = set()

    for s in structures:
        s["used"] = False

    skip_reasons = {}
    def _track_skip(reason):
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    i = 200
    while i < len(df_htf) - 1:
        row = df_htf.iloc[i]
        if i in structures_by_zone_created:
            active_structures.extend(structures_by_zone_created[i])
        active_structures = [
            s for s in active_structures
            if (not s["used"]) and (i <= s["expire_idx"])
            and (s["score"] >= RELAX_MIN_SCORE) and (s["zone_created_idx"] not in used_zone_ids)
        ]
        trade_day = str(row["timestamp"].date())
        if daily_trade_count.get(trade_day, 0) >= DAY_TRADE_LIMIT:
            i += 1
            continue

        entry_found = False
        used_structure = None
        used_effective_score = None
        used_reasons_full = None
        used_base_score = None
        used_fresh_reasons = None
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
        ltf_market_state = df_htf.loc[i, "market_state"]
        # 4K atoms / tier 미리 계산
        atoms_dict = None
        tier_label_4h = None
        sw_c = fvg_c = ob_c = total_c = 0
        wick_ratio_5 = 0.0

        scored_active = []
        for s in active_structures:
            fresh_bonus, fresh_reasons = evaluate_freshness_at_entry(df_htf, s, i)
            eff_score = float(s["score"]) + fresh_bonus
            if eff_score < MIN_SCORE:
                continue
            scored_active.append((s, eff_score, fresh_reasons))
        scored_active.sort(key=lambda x: (-x[1], x[0]["zone_created_idx"]))

        for s, eff_score, fresh_reasons in scored_active:
            touched = (row["high"] >= s["zone_low"]) and (row["low"] <= s["zone_high"])
            if not touched:
                continue
            vol_ok, vol_reason = passes_volume_filter(df_htf, s["zone_created_idx"])
            if not vol_ok:
                _track_skip(vol_reason)
                continue
            atr_val = df_htf.loc[i, "atr"] if pd.notna(df_htf.loc[i, "atr"]) else 0.0
            rp, rp_tags = get_run_potential(df_htf, i, s)
            g = classify_grade(float(eff_score), rp)
            reasons_full = s["reasons"]
            if fresh_reasons:
                reasons_full = reasons_full + "," + ",".join(fresh_reasons) if reasons_full else ",".join(fresh_reasons)

            if s["type"] == "short":
                if i - last_short_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_htf.loc[i, "trend"] == "up":
                    continue
                # 4K: pre-entry confluence + wick + h1 choch
                sw_c, fvg_c, ob_c, total_c = compute_pre_entry_confluence(
                    df_htf, df_ltf, i, s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_5 = compute_wick_ratio_5(df_htf, df_ltf, i, "short", WICK_LOOKBACK_BARS)
                h1_confirm = has_recent_h1_choch(df_ltf, df_htf.loc[i, "timestamp"], "short", H1_CHOCH_CONFIRM_HOURS)
                # ★★★ 보수 entry: SHORT_BASE_ENTRY_FRAC = 0.0 = zone_low ★★★
                base_entry_c = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * SHORT_BASE_ENTRY_FRAC
                # refine OFF (max_improve_frac=0.0 이라 refine 작동해도 base 와 동일)
                refined_entry_c = base_entry_c
                improved = False
                refine_px = np.nan
                refine_reason = "refine_disabled"
                # 보수 fill: zone_low (4K 백테 fill 모델 일치)
                fill_entry_price = float(s["zone_low"])
                raw_sl = s["sweep_ref"] + atr_val * SL_BUFFER_MULT
                sl_c = clamp_stop_for_short(fill_entry_price, raw_sl, atr_val)
                if sl_c <= fill_entry_price:
                    continue

                # 4K atoms 계산 (compute_trade_tags)
                atoms_dict = compute_trade_tags(
                    df_htf, i, s["zone_created_idx"],
                    s["zone_low"], s["zone_high"], "short",
                    total_c, sw_c, eff_score, wick_ratio_5,
                    reasons_full, atr_val,
                )
                tier_label_4h = classify_tier_stage4h(atoms_dict, side="short")

                expansion_c = get_expansion_state(ltf_market_state, h1_confirm)
                plan = get_tp_plan(expansion_c)
                entry_found = True
                used_structure = s
                used_effective_score = eff_score
                used_reasons_full = reasons_full
                used_base_score = float(s["score"])
                used_fresh_reasons = ",".join(fresh_reasons)
                entry_side = "short"
                entry = fill_entry_price
                sl = sl_c
                grade = g
                run_potential = rp
                run_tags = rp_tags
                tp_plan = plan
                expansion_state = expansion_c
                base_entry = base_entry_c
                refined_entry = refine_px if improved else np.nan
                entry_refined = improved
                refine_tag = refine_reason
                break

            if s["type"] == "long":
                if i - last_long_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_htf.loc[i, "trend"] == "down":
                    continue
                sw_c, fvg_c, ob_c, total_c = compute_pre_entry_confluence(
                    df_htf, df_ltf, i, s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_5 = compute_wick_ratio_5(df_htf, df_ltf, i, "long", WICK_LOOKBACK_BARS)
                h1_confirm = has_recent_h1_choch(df_ltf, df_htf.loc[i, "timestamp"], "long", H1_CHOCH_CONFIRM_HOURS)
                # ★★★ 보수 entry: LONG_BASE_ENTRY_FRAC = 1.0 = zone_high ★★★
                base_entry_c = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * LONG_BASE_ENTRY_FRAC
                refined_entry_c = base_entry_c
                improved = False
                refine_px = np.nan
                refine_reason = "refine_disabled"
                # 보수 fill: zone_high (4K 백테 fill 모델 일치)
                fill_entry_price = float(s["zone_high"])
                raw_sl = s["sweep_ref"] - atr_val * SL_BUFFER_MULT
                sl_c = clamp_stop_for_long(fill_entry_price, raw_sl, atr_val)
                if sl_c >= fill_entry_price:
                    continue

                atoms_dict = compute_trade_tags(
                    df_htf, i, s["zone_created_idx"],
                    s["zone_low"], s["zone_high"], "long",
                    total_c, sw_c, eff_score, wick_ratio_5,
                    reasons_full, atr_val,
                )
                tier_label_4h = classify_tier_stage4h(atoms_dict, side="long")

                expansion_c = get_expansion_state(ltf_market_state, h1_confirm)
                plan = get_tp_plan(expansion_c)
                entry_found = True
                used_structure = s
                used_effective_score = eff_score
                used_reasons_full = reasons_full
                used_base_score = float(s["score"])
                used_fresh_reasons = ",".join(fresh_reasons)
                entry_side = "long"
                entry = fill_entry_price
                sl = sl_c
                grade = g
                run_potential = rp
                run_tags = rp_tags
                tp_plan = plan
                expansion_state = expansion_c
                base_entry = base_entry_c
                refined_entry = refine_px if improved else np.nan
                entry_refined = improved
                refine_tag = refine_reason
                break

        if not entry_found:
            i += 1
            continue

        sim = simulate_trade_with_plan(
            df_htf, i, entry_side, entry, sl, 1.0, FEE_RATE, grade, tp_plan,
            USE_SEQ_RUNNER_PROTECTION_BASELINE,
        )
        used_structure["used"] = True
        used_zone_ids.add(used_structure["zone_created_idx"])
        daily_trade_count[trade_day] = daily_trade_count.get(trade_day, 0) + 1
        if entry_side == "long":
            last_long_exit_idx = sim["exit_idx"]
        else:
            last_short_exit_idx = sim["exit_idx"]

        candidates.append({
            "symbol_key": symbol_key, "yahoo_symbol": yahoo_symbol,
            "entry_time": row["timestamp"], "entry_time_ny": row["timestamp_ny"],
            "exit_time": sim["exit_time"], "side": entry_side,
            "entry": entry, "fill_entry": entry, "entry_idx": i,
            "pre_entry_sweep": sw_c, "pre_entry_total": total_c, "wick_ratio_5": wick_ratio_5,
            "base_entry": base_entry,
            "entry_improved_by": (base_entry - entry) if entry_side == "long" else (entry - base_entry),
            "entry_refined": entry_refined, "refined_entry_px": refined_entry,
            "refine_tag": refine_tag, "sl": sl, "risk_per_unit": abs(entry - sl),
            "r_multiple": sim["r_multiple"], "result": sim["result"],
            "exit_reason": sim["exit_reason"], "hold_bars": sim["hold_bars"],
            "score": used_effective_score, "base_score": used_base_score,
            "fresh_reasons": used_fresh_reasons, "grade": grade,
            "run_potential": run_potential, "run_tags": run_tags,
            "be_moved": sim["be_moved"], "runner_active": sim["runner_active"],
            "target1_hit": sim["target1_hit"], "target2_hit": sim["target2_hit"], "target3_hit": sim["target3_hit"],
            "max_rr_seen": sim["max_rr_seen"], "runner_max_rr_seen": sim["runner_max_rr_seen"],
            "bars_to_2r": sim["bars_to_2r"], "bars_spent_above_2r": sim["bars_spent_above_2r"],
            "max_rr_after_2r": sim["max_rr_after_2r"], "cond_count_final": sim["cond_count_final"],
            "runner_candidate_2of3": sim["runner_candidate_2of3"],
            "post_2of3_apply_ok": sim["post_2of3_apply_ok"],
            "runner_protected": sim["runner_protected"],
            "stop_type_last": sim["stop_type_last"],
            "proxy_runner": sim["proxy_runner"],
            "tp_plan_name": tp_plan["name"], "expansion_state": expansion_state,
            "reasons": used_reasons_full, "zone_created_idx": used_structure["zone_created_idx"],
            "market_state": ltf_market_state,
            # ★ 4K 추가 필드 ★
            "tier_label_4h": tier_label_4h,
            "atoms_a_sweep":          bool(atoms_dict.get("a_sweep", False))          if atoms_dict else False,
            "atoms_a_volume":         bool(atoms_dict.get("a_volume", False))         if atoms_dict else False,
            "atoms_a_pre_total_ge4":  bool(atoms_dict.get("a_pre_total_ge4", False))  if atoms_dict else False,
            "atoms_a_sweep_count_2_4": bool(atoms_dict.get("a_sweep_count_2_4", False)) if atoms_dict else False,
            "atoms_a_score_ge13":     bool(atoms_dict.get("a_score_ge13", False))     if atoms_dict else False,
            "atoms_a_wick_le_q1":     bool(atoms_dict.get("a_wick_le_q1", False))     if atoms_dict else False,
            "atoms_a_pre_total_ge1":  bool(atoms_dict.get("a_pre_total_ge1", False))  if atoms_dict else False,
            "atoms_a_trend_align":    bool(atoms_dict.get("a_trend_align", False))    if atoms_dict else False,
            "atoms_a_mss":            bool(atoms_dict.get("a_mss", False))            if atoms_dict else False,
            "atoms_a_fvg":            bool(atoms_dict.get("a_fvg", False))            if atoms_dict else False,
            "atoms_a_overlap":        bool(atoms_dict.get("a_overlap", False))        if atoms_dict else False,
            "atoms_a_room":           bool(atoms_dict.get("a_room", False))           if atoms_dict else False,
        })
        i = sim["exit_idx"] + 1

    candidates_df = pd.DataFrame(candidates)
    if len(candidates_df) > 0:
        candidates_df["entry_time"] = pd.to_datetime(candidates_df["entry_time"], utc=True)
        candidates_df["exit_time"] = pd.to_datetime(candidates_df["exit_time"], utc=True)
        candidates_df = candidates_df.sort_values(["entry_time", "exit_time"]).reset_index(drop=True)

    if skip_reasons:
        print(f"\n{symbol_key} candidate skips:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1])[:10]:
            print(f"  {reason}: {count}")

    return {
        "symbol_key": symbol_key, "yahoo_symbol": yahoo_symbol,
        "df_htf": df_htf, "df_ltf": df_ltf, "candidates": candidates_df,
    }


print("v25 Part 4 loaded: prepare + 4K candidate generation")


# =========================================================
# ★★★ simulate_portfolio_v25 — Stage 4K BOOST15 적용 ★★★
#  - candidate 의 tier_label_4h 사용
#  - get_tier_risk_mult_4h (4I 차단 포함: GEM_LONG_ONLY, ROOM_ONLY blacklist)
#  - is_stage4j_blocked (4J 차단)
#  - get_stage4j_extra_mult (4J booster 1.5×/1.2×)
#  - get_stage4k_sentiment_mult (sentiment booster/cut)
#  - RP_MULT_4H 적용
#  - get_tier_cap_4h (notional cap)
#  - Phase A/B + Tax 그대로
# =========================================================

def simulate_portfolio_v25(candidates_packs, max_total_risk=0.1325, scenario_name="BOOST15"):
    all_candidates = []
    for k, pack in candidates_packs.items():
        cdf = pack["candidates"].copy()
        if len(cdf) > 0:
            all_candidates.append(cdf)
    if len(all_candidates) == 0:
        raise ValueError("No candidates found for portfolio")
    cands = pd.concat(all_candidates, ignore_index=True).sort_values(["entry_time","exit_time","symbol_key"]).reset_index(drop=True)

    first_ts = cands["entry_time"].min()
    deposit_df = make_deposit_schedule(first_ts, MONTHLY_DEPOSIT_USD, NUM_MONTHLY_DEPOSITS)

    balance = INITIAL_BALANCE_USD
    deposit_idx = 0

    open_positions = {}
    executed_trades = []
    skipped_entries = []
    equity_points = []

    phase_transitions = []
    excess_log = []
    tax_log = []
    last_phase = get_current_phase(balance)
    cumulative_excess_usd = 0.0
    cumulative_tax_usd = 0.0
    annual_pnl_by_year = {}

    def handle_phase_and_excess(cur_time, note=""):
        nonlocal balance, last_phase, cumulative_excess_usd
        new_phase = get_current_phase(balance)
        if new_phase != last_phase:
            phase_transitions.append({
                "time": cur_time, "from_phase": last_phase, "to_phase": new_phase,
                "balance_usd": balance, "note": note,
            })
            last_phase = new_phase
        if new_phase == "B":
            balance, excess = cap_and_extract_excess(balance)
            if excess > 0:
                cumulative_excess_usd += excess
                excess_log.append({
                    "time": cur_time, "excess_usd": excess,
                    "cumulative_excess_usd": cumulative_excess_usd,
                    "note": note,
                })

    def current_open_risk():
        return sum(p["actual_risk_amount"] for p in open_positions.values())

    years = sorted(set(
        [t.year for t in cands["entry_time"].tolist()] +
        [t.year for t in cands["exit_time"].tolist()]
    ))
    year_end_events = [pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC") for y in years]

    event_times = sorted(set(
        cands["entry_time"].tolist()
        + cands["exit_time"].tolist()
        + deposit_df["deposit_time"].tolist()
        + year_end_events
    ))

    entry_map = {}
    exit_map = {}
    for idx, row in cands.iterrows():
        entry_map.setdefault(row["entry_time"], []).append((idx, row.to_dict()))
        exit_map.setdefault(row["exit_time"], []).append((idx, row.to_dict()))

    year_end_set = set(year_end_events)

    for current_time in event_times:
        prev_bal = balance
        balance, deposit_idx = apply_pending_deposits(balance, current_time, deposit_df, deposit_idx)
        if balance != prev_bal:
            handle_phase_and_excess(current_time, note="deposit")

        if current_time in exit_map:
            exit_events = sorted(exit_map[current_time], key=lambda x: x[1]["symbol_key"])
            for idx, row in exit_events:
                if idx not in open_positions:
                    continue
                pos = open_positions.pop(idx)
                balance += pos["net_pnl"]
                pos["balance_after_exit"] = balance
                pos["phase_at_exit"] = get_current_phase(balance)
                y = pd.Timestamp(pos["exit_time"]).year
                annual_pnl_by_year[y] = annual_pnl_by_year.get(y, 0.0) + pos["net_pnl"]
                executed_trades.append(pos)
                handle_phase_and_excess(current_time, note=f"trade_exit:{pos['symbol_key']}")

        equity_points.append({
            "time": current_time, "equity": balance,
            "cumulative_excess": cumulative_excess_usd,
            "cumulative_tax": cumulative_tax_usd,
            "phase": last_phase,
        })

        if current_time in year_end_set:
            y = current_time.year
            annual_pnl = annual_pnl_by_year.get(y, 0.0)
            if annual_pnl > 0:
                tax_usd = calculate_annual_tax_usd(annual_pnl)
                if tax_usd > 0:
                    balance -= tax_usd
                    cumulative_tax_usd += tax_usd
                    tax_log.append({
                        "time": current_time, "year": y,
                        "annual_pnl_usd": annual_pnl,
                        "tax_usd": tax_usd,
                        "cumulative_tax_usd": cumulative_tax_usd,
                    })
                    handle_phase_and_excess(current_time, note=f"tax_{y}")
            annual_pnl_by_year[y] = 0.0

        if current_time in entry_map:
            entry_events = sorted(entry_map[current_time], key=lambda x: (-x[1]["score"], x[1]["symbol_key"]))
            for idx, row in entry_events:
                symbol_key = row["symbol_key"]

                # ★ v31: 동시포지션 전체 한도 검사 ★
                if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": f"max_concurrent_positions_{MAX_CONCURRENT_POSITIONS}",
                        "phase_at_entry": last_phase,
                    })
                    continue

                # ★ v31: same_symbol 검사 + runner 활성화 시 추가 허용 ★
                # ALLOW_RUNNER_DOUBLE_POSITION=True 이면 SCORE_ONLY_GATE 와 무관하게 검사 활성화
                same_sym_check_active = ALLOW_RUNNER_DOUBLE_POSITION or (not SCORE_ONLY_GATE)
                same_sym_positions = [p for p in open_positions.values() if p["symbol_key"] == symbol_key]
                if same_sym_check_active and len(same_sym_positions) > 0:
                    if not ALLOW_RUNNER_DOUBLE_POSITION:
                        # 기존 정책: 같은 종목 1포지션만
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": "same_symbol_already_open",
                            "phase_at_entry": last_phase,
                        })
                        continue
                    # ALLOW_RUNNER_DOUBLE_POSITION=True 시:
                    #   같은 종목 포지션 중 runner 활성화 + 현재 시각이 runner 활성화 시점 이후인 것만 인정
                    #   동시에 같은 종목 최대 2 포지션까지만
                    if len(same_sym_positions) >= 2:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": "same_symbol_max2_already_open",
                            "phase_at_entry": last_phase,
                        })
                        continue
                    # 하나만 있을 때 - 그 포지션이 runner 활성화 됐고 현재 시각이 그 이후인지
                    runner_qualified = False
                    for p in same_sym_positions:
                        ra_time = p.get("runner_activated_time")
                        if ra_time is not None and pd.notna(ra_time):
                            if current_time >= pd.Timestamp(ra_time):
                                runner_qualified = True
                                break
                    if not runner_qualified:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": "same_symbol_no_runner_active",
                            "phase_at_entry": last_phase,
                        })
                        continue
                    # → runner 활성화 됐으니 추가 진입 허용 (이 line 아래로 진행)

                # Phase 기반 base risk
                current_phase_for_entry = get_current_phase(balance)
                risk_pct_base = get_phase_risk_pct(current_phase_for_entry, symbol_key)

                # ★★★ Stage 4K Tier 적용 ★★★
                tier_label = row.get("tier_label_4h")
                if tier_label is None or pd.isna(tier_label):
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": "no_tier_label",
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                side = row["side"]
                rp_v = int(row.get("run_potential", 0)) if pd.notna(row.get("run_potential", 0)) else 0

                # 4I 차단 포함된 tier mult
                tier_mult = get_tier_risk_mult_4h(tier_label, side=side, symbol=symbol_key)

                # ★★★ v28: 모든 차단을 SCORE_ONLY_GATE 가 OFF 일 때만 적용 ★★★
                
                # 4J 차단
                stage4j_block = is_stage4j_blocked(tier_label, side, symbol_key, rp_v)
                if (not SCORE_ONLY_GATE) and stage4j_block is not None:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": f"stage4j_skip_{stage4j_block}",
                        "tier_label": tier_label, "rp": rp_v,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                # tier_4h 차단
                if (not SCORE_ONLY_GATE) and tier_mult <= 0.0:
                    if tier_label == "SWEEP_GEM" and GEM_LONG_ONLY and side == "short":
                        sk_reason = "stage4i_skip_GEM_SHORT_blocked"
                    elif tier_label == "SWEEP_ROOM_ONLY" and symbol_key in ROOM_ONLY_SYMBOL_BLACKLIST:
                        sk_reason = f"stage4i_skip_ROOM_ONLY_blacklist_{symbol_key}"
                    elif tier_label == "SKIP_MSS":
                        sk_reason = "stage4h_skip_SKIP_MSS"
                    elif tier_label == "COMPLETE_OUT":
                        sk_reason = f"stage4h_skip_COMPLETE_OUT_{OUT_BEHAVIOR}"
                    else:
                        sk_reason = f"stage4h_skip_{tier_label}_zero_mult"
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": sk_reason, "tier_label": tier_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                # RP filter
                if (not SCORE_ONLY_GATE) and RP_FILTER_ENABLE and rp_v not in RP_MULT_4H:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": f"rp_filter_skip_RP{rp_v}",
                        "tier_label": tier_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue
                rp_mult = RP_MULT_4H.get(rp_v, 1.0)

                # 4J booster (mult 만)
                stage4j_mult, stage4j_label = get_stage4j_extra_mult(tier_label, side, symbol_key, rp_v)

                # 4K Sentiment (mult 만)
                sentiment_mult, sentiment_label = get_stage4k_sentiment_mult(
                    target_time=row["entry_time"],
                    side=side,
                    executed_trades_so_far=executed_trades,
                    scenario=scenario_name,
                )

                # v19b RP_BOOST tier
                pre_total_v = int(row.get("pre_entry_total", 0)) if pd.notna(row.get("pre_entry_total", 0)) else 0
                sweep_v = int(row.get("pre_entry_sweep", 0)) if pd.notna(row.get("pre_entry_sweep", 0)) else 0
                score_v = float(row.get("score", 0)) if pd.notna(row.get("score", 0)) else 0.0
                wick_v = row.get("wick_ratio_5", None)
                if pd.notna(wick_v):
                    wick_v = float(wick_v)
                else:
                    wick_v = None
                tier_v19b_label, tier_v19b_mult, rp_action_v19b = classify_tier_v19b_rp_boost(
                    pre_total_v, sweep_v, score_v, wick_v, rp_v
                )
                # tier_v19b D 차단
                if (not SCORE_ONLY_GATE) and tier_v19b_mult <= 0.0:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": f"v19b_skip_{tier_v19b_label}_{rp_action_v19b}",
                        "tier_label": tier_label, "tier_v19b": tier_v19b_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                # whitelist 차단
                if (not SCORE_ONLY_GATE) and USE_COMBO_WHITELIST and (tier_label, tier_v19b_label) not in ALLOWED_TIER_COMBOS:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": f"combo_skip_{tier_label}_x_{tier_v19b_label}",
                        "tier_label": tier_label, "tier_v19b": tier_v19b_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                # ★ Risk: V6 SUB-TIER (FLAT 1.0 또는 sub-tier mult) ★
                if USE_V6_SUB_TIER:
                    # ===== v30: V6 SUB-TIER 분류 + risk multiplier =====
                    # 1. 자산 차단 검사
                    if symbol_key in SKIP_ASSETS:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": f"v6_asset_skip_{symbol_key}",
                            "tier_label": tier_label,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue

                    # 2. row 에서 카테고리 1 (atomic 12) 추출
                    def _ag(k):
                        v = row.get(k, False)
                        if pd.isna(v): return False
                        return bool(v)
                    a_sweep         = _ag("atoms_a_sweep")
                    a_volume        = _ag("atoms_a_volume")
                    a_pre_ge4       = _ag("atoms_a_pre_total_ge4")
                    a_sweep_count_24 = _ag("atoms_a_sweep_count_2_4")
                    a_score_ge13    = _ag("atoms_a_score_ge13")
                    a_wick_q1       = _ag("atoms_a_wick_le_q1")
                    a_pre_ge1       = _ag("atoms_a_pre_total_ge1")
                    a_trend_align   = _ag("atoms_a_trend_align")
                    a_mss           = _ag("atoms_a_mss")
                    a_fvg           = _ag("atoms_a_fvg")
                    a_overlap       = _ag("atoms_a_overlap")
                    a_room          = _ag("atoms_a_room")

                    # 3. V6 RULES 가 참조하는 모든 atom dict 구성
                    atoms_for_v6 = {
                        "atoms_a_sweep": a_sweep, "atoms_a_volume": a_volume,
                        "atoms_a_pre_total_ge4": a_pre_ge4, "atoms_a_sweep_count_2_4": a_sweep_count_24,
                        "atoms_a_score_ge13": a_score_ge13, "atoms_a_wick_le_q1": a_wick_q1,
                        "atoms_a_pre_total_ge1": a_pre_ge1, "atoms_a_trend_align": a_trend_align,
                        "atoms_a_mss": a_mss, "atoms_a_fvg": a_fvg, "atoms_a_overlap": a_overlap,
                        "atoms_a_room": a_room,
                        "v19b_d_cond": (a_pre_ge4 or a_sweep_count_24 or a_score_ge13),
                        "v19b_wick_q1": a_wick_q1, "v19b_pre_ge1": a_pre_ge1,
                        "rp_eq_0": rp_v == 0, "rp_eq_1": rp_v == 1, "rp_eq_2": rp_v == 2,
                        "rp_eq_3": rp_v == 3, "rp_eq_4": rp_v == 4, "rp_eq_5": rp_v == 5,
                        "t4h_max_overlap": (a_overlap and not a_volume),
                        "t4h_max_score_pre": (a_score_ge13 and a_pre_ge1 and not a_overlap),
                        "t4h_high_vol_overlap": (a_volume and a_overlap and
                                                 (a_pre_ge1 or a_pre_ge4 or a_wick_q1 or a_score_ge13)),
                        "t4h_high_sweep_vol": (a_sweep and a_volume and not a_overlap),
                        "t4h_med_win69": (tier_label == "ALPHA_MED"),
                        "t4h_sweep_gem": (a_sweep and not a_room),
                        "t4h_sweep_room_fvg": (a_sweep and a_room and a_fvg),
                        "t4h_sweep_room_only": (a_sweep and a_room and not a_fvg),
                        "t4h_skip_mss": (a_mss and not (a_volume or a_overlap or a_sweep
                                                       or a_score_ge13 or a_pre_ge4)),
                        "v19b_match_S": (tier_v19b_label == "S"),
                        "v19b_match_A": (tier_v19b_label == "A"),
                        "v19b_match_B": (tier_v19b_label == "B"),
                        "v19b_match_C": (tier_v19b_label == "C"),
                    }

                    # 4. V6 sub-tier 분류 (best-match)
                    sub_tier_v6 = classify_tier_v6(atoms_for_v6)
                    v6_mult = get_v6_sub_tier_mult(sub_tier_v6)

                    # V5 호환 (X 차단 동일)
                    tier_v5 = sub_tier_v6  # log 호환
                    v5_tier_mult_applied = v6_mult

                    # 4b. ★ v31: DANGEROUS 4H × v19b COMBO 차단 ★
                    # A- / A 분류된 거래 중 약한 조합이면 X-block 처리
                    if sub_tier_v6 in ("A-", "A"):
                        if (tier_label, tier_v19b_label) in V6_DANGEROUS_4H_V19B_COMBOS:
                            skipped_entries.append({
                                "entry_time": row["entry_time"], "symbol_key": symbol_key,
                                "reason": f"v6_dangerous_combo_{tier_label}_x_{tier_v19b_label}",
                                "tier_label": tier_label,
                                "sub_tier_v6": sub_tier_v6,
                                "phase_at_entry": current_phase_for_entry,
                            })
                            continue

                    # 5. X / X-block SKIP
                    if sub_tier_v6 in ("X", "X-block"):
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": f"v6_sub_tier_{sub_tier_v6}_skip",
                            "tier_label": tier_label,
                            "sub_tier_v6": sub_tier_v6,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue
                    if v6_mult <= 0.0:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": f"v6_zero_mult_{sub_tier_v6}",
                            "tier_label": tier_label,
                            "sub_tier_v6": sub_tier_v6,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue

                    # 6. risk_pct = base × V6 sub-tier mult × asset mult (v32)
                    asset_mult = get_asset_mult(symbol_key)
                    risk_pct_effective = risk_pct_base * v6_mult * asset_mult
                    tier_v19b_mult_applied = 1.0
                    tier_mult_applied = 1.0
                    rp_mult_applied = 1.0
                    stage4j_mult_applied = 1.0
                    sentiment_mult_applied = 1.0
                elif USE_V5_TIER_GATE:
                    # ===== v29: V5 TIER 분류 + risk multiplier =====
                    # 1. 자산 차단 검사
                    if symbol_key in SKIP_ASSETS:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": f"v5_asset_skip_{symbol_key}",
                            "tier_label": tier_label,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue

                    # 2. row 에서 카테고리 1 (atomic 12) 추출
                    def _ag(k):  # atom-get from row
                        v = row.get(k, False)
                        if pd.isna(v): return False
                        return bool(v)
                    a_sweep         = _ag("atoms_a_sweep")
                    a_volume        = _ag("atoms_a_volume")
                    a_pre_ge4       = _ag("atoms_a_pre_total_ge4")
                    a_sweep_count_24 = _ag("atoms_a_sweep_count_2_4")
                    a_score_ge13    = _ag("atoms_a_score_ge13")
                    a_wick_q1       = _ag("atoms_a_wick_le_q1")
                    a_pre_ge1       = _ag("atoms_a_pre_total_ge1")
                    a_trend_align   = _ag("atoms_a_trend_align")
                    a_mss           = _ag("atoms_a_mss")
                    a_fvg           = _ag("atoms_a_fvg")
                    a_overlap       = _ag("atoms_a_overlap")
                    a_room          = _ag("atoms_a_room")

                    # 3. V5 RULES 가 참조하는 모든 atom dict 구성 (카테고리 1~5)
                    atoms_for_v5 = {
                        # 카테고리 1 - atomic 12
                        "atoms_a_sweep": a_sweep,
                        "atoms_a_volume": a_volume,
                        "atoms_a_pre_total_ge4": a_pre_ge4,
                        "atoms_a_sweep_count_2_4": a_sweep_count_24,
                        "atoms_a_score_ge13": a_score_ge13,
                        "atoms_a_wick_le_q1": a_wick_q1,
                        "atoms_a_pre_total_ge1": a_pre_ge1,
                        "atoms_a_trend_align": a_trend_align,
                        "atoms_a_mss": a_mss,
                        "atoms_a_fvg": a_fvg,
                        "atoms_a_overlap": a_overlap,
                        "atoms_a_room": a_room,
                        # 카테고리 2 - v19b raw decision (atomic 12 의 OR/단독 derivation)
                        "v19b_d_cond": (a_pre_ge4 or a_sweep_count_24 or a_score_ge13),
                        "v19b_wick_q1": a_wick_q1,
                        "v19b_pre_ge1": a_pre_ge1,
                        # 카테고리 3 - RP
                        "rp_eq_0": rp_v == 0, "rp_eq_1": rp_v == 1,
                        "rp_eq_2": rp_v == 2, "rp_eq_3": rp_v == 3,
                        "rp_eq_4": rp_v == 4, "rp_eq_5": rp_v == 5,
                        # 카테고리 4 - tier_4h decision (분해된 atom)
                        "t4h_max_overlap": (a_overlap and not a_volume),
                        "t4h_max_score_pre": (a_score_ge13 and a_pre_ge1 and not a_overlap),
                        "t4h_high_vol_overlap": (a_volume and a_overlap and
                                                 (a_pre_ge1 or a_pre_ge4 or a_wick_q1 or a_score_ge13)),
                        "t4h_high_sweep_vol": (a_sweep and a_volume and not a_overlap),
                        "t4h_med_win69": (tier_label == "ALPHA_MED"),
                        "t4h_sweep_gem": (a_sweep and not a_room),
                        "t4h_sweep_room_fvg": (a_sweep and a_room and a_fvg),
                        "t4h_sweep_room_only": (a_sweep and a_room and not a_fvg),
                        "t4h_skip_mss": (a_mss and not (a_volume or a_overlap or a_sweep
                                                       or a_score_ge13 or a_pre_ge4)),
                        # 카테고리 5 - v19b match
                        "v19b_match_S": (tier_v19b_label == "S"),
                        "v19b_match_A": (tier_v19b_label == "A"),
                        "v19b_match_B": (tier_v19b_label == "B"),
                        "v19b_match_C": (tier_v19b_label == "C"),
                    }

                    # 4. V5 tier 분류
                    tier_v5 = classify_tier_v5(atoms_for_v5)
                    v5_mult = get_v5_tier_mult(tier_v5)

                    # 5. X tier SKIP
                    if SKIP_V5_X_TIER and tier_v5 == "X":
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": "v5_tier_X_skip",
                            "tier_label": tier_label,
                            "tier_v5": tier_v5,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue
                    if v5_mult <= 0.0:
                        skipped_entries.append({
                            "entry_time": row["entry_time"], "symbol_key": symbol_key,
                            "reason": f"v5_zero_mult_{tier_v5}",
                            "tier_label": tier_label,
                            "tier_v5": tier_v5,
                            "phase_at_entry": current_phase_for_entry,
                        })
                        continue

                    # 6. risk_pct = base × V5 mult
                    risk_pct_effective = risk_pct_base * v5_mult
                    tier_v19b_mult_applied = 1.0
                    tier_mult_applied = 1.0
                    rp_mult_applied = 1.0
                    stage4j_mult_applied = 1.0
                    sentiment_mult_applied = 1.0
                    v5_tier_mult_applied = v5_mult
                    sub_tier_v6 = "OFF"
                    v6_mult = 1.0
                    asset_mult = 1.0
                elif USE_FLAT_RISK_MULT:
                    risk_pct_effective = risk_pct_base
                    tier_v19b_mult_applied = 1.0
                    tier_mult_applied = 1.0
                    rp_mult_applied = 1.0
                    stage4j_mult_applied = 1.0
                    sentiment_mult_applied = 1.0
                    tier_v5 = "FLAT"
                    v5_tier_mult_applied = 1.0
                    sub_tier_v6 = "OFF"
                    v6_mult = 1.0
                    asset_mult = 1.0
                else:
                    risk_pct_effective = risk_pct_base * tier_v19b_mult * tier_mult * rp_mult * stage4j_mult * sentiment_mult
                    tier_v19b_mult_applied = tier_v19b_mult
                    tier_mult_applied = tier_mult
                    rp_mult_applied = rp_mult
                    stage4j_mult_applied = stage4j_mult
                    sentiment_mult_applied = sentiment_mult
                    tier_v5 = "OFF"
                    v5_tier_mult_applied = 1.0
                    sub_tier_v6 = "OFF"
                    v6_mult = 1.0
                    asset_mult = 1.0

                # Notional cap
                effective_notional_cap = get_tier_cap_4h(tier_label)

                qty, risk_per_unit, notional = calc_position_size(
                    balance, risk_pct_effective, row["entry"], row["sl"], FEE_RATE, effective_notional_cap
                )
                if qty is None:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": "size_invalid",
                        "tier_label": tier_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                pack = candidates_packs[symbol_key]
                sim_exec = simulate_trade_with_plan(
                    pack["df_htf"], int(row["entry_idx"]), side, row["entry"], row["sl"],
                    qty, FEE_RATE, row["grade"], get_tp_plan(bool(row["expansion_state"])),
                    USE_SEQ_RUNNER_PROTECTION_BASELINE
                )
                projected_total_risk = current_open_risk() + sim_exec["risk_amount"]
                allowed_total_risk = balance * max_total_risk
                if (not SCORE_ONLY_GATE) and projected_total_risk > allowed_total_risk + 1e-12:
                    skipped_entries.append({
                        "entry_time": row["entry_time"], "symbol_key": symbol_key,
                        "reason": "max_total_risk_exceeded",
                        "tier_label": tier_label,
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue
                open_positions[idx] = {
                    "trade_id": idx, "symbol_key": symbol_key, "yahoo_symbol": row["yahoo_symbol"],
                    "entry_time": row["entry_time"], "entry_time_ny": row["entry_time_ny"],
                    "exit_time": sim_exec["exit_time"], "side": side,
                    "entry_signal": row["entry"], "entry_exec": sim_exec["entry_exec"],
                    "exit_exec": sim_exec["exit_price_exec"], "sl": row["sl"], "qty": qty,
                    "notional": abs(sim_exec["entry_exec"] * qty),
                    "risk_pct_base": risk_pct_base,
                    "risk_pct_effective": risk_pct_effective,
                    # ★ v31: runner 활성화 추적 ★
                    "runner_activated_time": sim_exec.get("runner_activated_time"),
                    "runner_activated_idx": sim_exec.get("runner_activated_idx"),
                    "target1_hit_time": sim_exec.get("target1_hit_time"),
                    "target1_hit_idx": sim_exec.get("target1_hit_idx"),
                    "tier_label": tier_label,
                    "tier_mult": tier_mult,
                    "tier_mult_applied": tier_mult_applied,
                    "tier_v19b": tier_v19b_label,
                    "tier_v19b_mult": tier_v19b_mult,
                    "tier_v19b_mult_applied": tier_v19b_mult_applied,
                    "tier_v5": tier_v5,
                    "v5_tier_mult": v5_tier_mult_applied,  # V5/V6 모두에서 mult 값 일치
                    "v5_tier_mult_applied": v5_tier_mult_applied,
                    "rp_action_v19b": rp_action_v19b,
                    "rp_value": rp_v,
                    "rp_mult": rp_mult,
                    "rp_mult_applied": rp_mult_applied,
                    "stage4j_mult": stage4j_mult,
                    "stage4j_mult_applied": stage4j_mult_applied,
                    "stage4j_label": stage4j_label,
                    "sentiment_mult": sentiment_mult,
                    "sentiment_mult_applied": sentiment_mult_applied,
                    "sentiment_label": sentiment_label,
                    # ★ v28: 카테고리 1 - atomic 12 ★
                    "atoms_a_sweep":           bool(row.get("atoms_a_sweep", False)),
                    "atoms_a_volume":          bool(row.get("atoms_a_volume", False)),
                    "atoms_a_pre_total_ge4":   bool(row.get("atoms_a_pre_total_ge4", False)),
                    "atoms_a_sweep_count_2_4": bool(row.get("atoms_a_sweep_count_2_4", False)),
                    "atoms_a_score_ge13":      bool(row.get("atoms_a_score_ge13", False)),
                    "atoms_a_wick_le_q1":      bool(row.get("atoms_a_wick_le_q1", False)),
                    "atoms_a_pre_total_ge1":   bool(row.get("atoms_a_pre_total_ge1", False)),
                    "atoms_a_trend_align":     bool(row.get("atoms_a_trend_align", False)),
                    "atoms_a_mss":             bool(row.get("atoms_a_mss", False)),
                    "atoms_a_fvg":             bool(row.get("atoms_a_fvg", False)),
                    "atoms_a_overlap":         bool(row.get("atoms_a_overlap", False)),
                    "atoms_a_room":            bool(row.get("atoms_a_room", False)),
                    # ★ v28: 카테고리 2 - v19b decision raw ★
                    "v19b_d_cond":  (pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13),
                    "v19b_wick_q1": (wick_v is not None) and (wick_v <= WICK_RATIO_5_Q1_THRESHOLD),
                    "v19b_pre_ge1": pre_total_v >= 1,
                    # ★ v28: 카테고리 3 - RP atom ★
                    "rp_eq_0": rp_v == 0,
                    "rp_eq_1": rp_v == 1,
                    "rp_eq_2": rp_v == 2,
                    "rp_eq_3": rp_v == 3,
                    "rp_eq_4": rp_v == 4,
                    "rp_eq_5": rp_v == 5,
                    # ★ v28: 카테고리 4 - tier_4h decision atom (9개) ★
                    "t4h_max_overlap": (
                        bool(row.get("atoms_a_overlap", False))
                        and not bool(row.get("atoms_a_volume", False))
                    ),
                    "t4h_max_score_pre": (
                        bool(row.get("atoms_a_score_ge13", False))
                        and bool(row.get("atoms_a_pre_total_ge1", False))
                        and not bool(row.get("atoms_a_overlap", False))
                    ),
                    "t4h_high_vol_overlap": (
                        bool(row.get("atoms_a_volume", False))
                        and bool(row.get("atoms_a_overlap", False))
                        and (
                            bool(row.get("atoms_a_pre_total_ge1", False))
                            or bool(row.get("atoms_a_pre_total_ge4", False))
                            or bool(row.get("atoms_a_wick_le_q1", False))
                            or bool(row.get("atoms_a_score_ge13", False))
                        )
                    ),
                    "t4h_high_sweep_vol": (
                        bool(row.get("atoms_a_sweep", False))
                        and bool(row.get("atoms_a_volume", False))
                        and not bool(row.get("atoms_a_overlap", False))
                    ),
                    "t4h_med_win69": tier_label == "ALPHA_MED",
                    "t4h_sweep_gem": (
                        bool(row.get("atoms_a_sweep", False))
                        and not bool(row.get("atoms_a_room", False))
                    ),
                    "t4h_sweep_room_fvg": (
                        bool(row.get("atoms_a_sweep", False))
                        and bool(row.get("atoms_a_room", False))
                        and bool(row.get("atoms_a_fvg", False))
                    ),
                    "t4h_sweep_room_only": (
                        bool(row.get("atoms_a_sweep", False))
                        and bool(row.get("atoms_a_room", False))
                        and not bool(row.get("atoms_a_fvg", False))
                    ),
                    "t4h_skip_mss": (
                        bool(row.get("atoms_a_mss", False))
                        and not (
                            bool(row.get("atoms_a_volume", False))
                            or bool(row.get("atoms_a_overlap", False))
                            or bool(row.get("atoms_a_sweep", False))
                            or bool(row.get("atoms_a_score_ge13", False))
                            or bool(row.get("atoms_a_pre_total_ge4", False))
                        )
                    ),
                    # ★ v28: 카테고리 5 - tier_v19b match atom (4개) ★
                    "v19b_match_S": (
                        ((pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13))
                        and (wick_v is not None) and (wick_v <= WICK_RATIO_5_Q1_THRESHOLD)
                    ),
                    "v19b_match_A": (
                        ((pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13))
                        and not ((wick_v is not None) and (wick_v <= WICK_RATIO_5_Q1_THRESHOLD))
                    ),
                    "v19b_match_B": (
                        not ((pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13))
                        and (wick_v is not None) and (wick_v <= WICK_RATIO_5_Q1_THRESHOLD)
                    ),
                    "v19b_match_C": (
                        not ((pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13))
                        and not ((wick_v is not None) and (wick_v <= WICK_RATIO_5_Q1_THRESHOLD))
                        and (pre_total_v >= 1)
                    ),
                    # 진입 조합 라벨
                    "combo_label": f"{tier_label}_x_{tier_v19b_label}",
                    # ★ v29: V5 tier ★
                    "tier_v5_final": tier_v5 if (USE_V5_TIER_GATE or USE_V6_SUB_TIER) else "OFF",
                    "v5_mult_final": v5_tier_mult_applied,
                    "risk_scenario": RISK_SCENARIO,
                    # ★ v30: V6 sub-tier ★
                    "sub_tier_v6": sub_tier_v6 if USE_V6_SUB_TIER else "OFF",
                    "v6_mult_final": v6_mult if USE_V6_SUB_TIER else 1.0,
                    "v6_scenario": V6_SCENARIO,
                    # ★ v32: asset mult ★
                    "asset_mult": asset_mult,
                    "pre_entry_total": pre_total_v,
                    "pre_entry_sweep": sweep_v,
                    "wick_ratio_5":    wick_v if wick_v is not None else float("nan"),
                    "actual_risk_amount": sim_exec["risk_amount"],
                    "risk_per_unit_exec": abs(sim_exec["entry_exec"] - row["sl"]),
                    "r_multiple": sim_exec["r_multiple"], "net_pnl": sim_exec["net_pnl"],
                    "result": sim_exec["result"], "exit_reason": sim_exec["exit_reason"],
                    "hold_bars": sim_exec["hold_bars"], "score": row["score"],
                    "base_score": row.get("base_score", row["score"]),
                    "fresh_reasons": row.get("fresh_reasons", ""),
                    "grade": row["grade"], "run_potential": row["run_potential"],
                    "tp_plan_name": row["tp_plan_name"], "expansion_state": row["expansion_state"],
                    "entry_refined": row["entry_refined"], "entry_improved_by": row["entry_improved_by"],
                    "max_rr_seen": sim_exec["max_rr_seen"], "runner_max_rr_seen": sim_exec["runner_max_rr_seen"],
                    "runner_candidate_2of3": sim_exec["runner_candidate_2of3"],
                    "post_2of3_apply_ok": sim_exec["post_2of3_apply_ok"],
                    "runner_protected": sim_exec["runner_protected"],
                    "proxy_runner": sim_exec["proxy_runner"],
                    "be_moved": sim_exec["be_moved"], "runner_active": sim_exec["runner_active"],
                    "bars_to_2r": sim_exec["bars_to_2r"], "bars_spent_above_2r": sim_exec["bars_spent_above_2r"],
                    "max_rr_after_2r": sim_exec["max_rr_after_2r"], "cond_count_final": sim_exec["cond_count_final"],
                    "stop_type_last": sim_exec["stop_type_last"],
                    "target1_hit": sim_exec["target1_hit"],
                    "target2_hit": sim_exec["target2_hit"],
                    "target3_hit": sim_exec["target3_hit"],
                    # ★ v31: runner / 1R hit 시점 ★
                    "runner_activated_time": sim_exec.get("runner_activated_time"),
                    "runner_activated_idx": sim_exec.get("runner_activated_idx"),
                    "target1_hit_time": sim_exec.get("target1_hit_time"),
                    "target1_hit_idx": sim_exec.get("target1_hit_idx"),
                    "balance_at_entry": balance,
                    "phase_at_entry": current_phase_for_entry,
                }

    for _, pos in list(open_positions.items()):
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
    tax_df = pd.DataFrame(tax_log)

    if len(equity_df) > 0:
        equity_df["total_assets_usd"] = equity_df["equity"] + equity_df["cumulative_excess"]
        equity_df["cummax"] = equity_df["total_assets_usd"].cummax()
        equity_df["dd"] = equity_df["total_assets_usd"] - equity_df["cummax"]
        equity_df["dd_pct"] = np.where(equity_df["cummax"] > 0, equity_df["dd"] / equity_df["cummax"] * 100, 0)

    if len(trades_df) > 0:
        trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
        trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"], utc=True)
        trades_df["month"] = trades_df["exit_time"].dt.strftime("%Y-%m")
        trades_df["entry_time_kst"] = trades_df["entry_time"].dt.tz_convert("Asia/Seoul")
        trades_df["exit_time_kst"] = trades_df["exit_time"].dt.tz_convert("Asia/Seoul")

    return {
        "mode": "portfolio",
        "symbol_key": "PORTFOLIO_INDEX_V25_STAGE4K",
        "yahoo_symbol": "+".join(INDEX_SYMBOLS.values()),
        "strategy_variant": f"v33_{V6_SCENARIO}{_TF_SUFFIX}_BOOST15",
        "scenario": scenario_name,
        "trades": trades_df,
        "skipped": skipped_df,
        "equity": equity_df,
        "phase_transitions": phase_df,
        "excess_log": excess_df,
        "tax_log": tax_df,
        "final_balance_usd": balance,
        "final_balance_krw": balance * KRW_PER_USD,
        "final_cumulative_excess_usd": cumulative_excess_usd,
        "final_cumulative_excess_krw": cumulative_excess_usd * KRW_PER_USD,
        "final_cumulative_tax_usd": cumulative_tax_usd,
        "final_cumulative_tax_krw": cumulative_tax_usd * KRW_PER_USD,
        "final_total_assets_usd": balance + cumulative_excess_usd,
        "final_total_assets_krw": (balance + cumulative_excess_usd) * KRW_PER_USD,
        "deposit_df": deposit_df,
    }


print("v25 Part 5 loaded: simulate_portfolio_v25 (Stage 4K BOOST15)")


# =========================================================
# Cell 5: Report
# =========================================================

def build_monthly_pnl_with_tax(trades_df, tax_df):
    if len(trades_df) == 0:
        return pd.DataFrame(columns=["month", "net_pnl_usd", "net_pnl_krw",
                                      "tax_usd_in_month", "after_tax_pnl_krw", "trades"])
    m = trades_df.groupby("month", as_index=False).agg(
        net_pnl_usd=("net_pnl", "sum"),
        trades=("symbol_key", "count"),
        avg_r=("r_multiple", "mean"),
        winrate_pct=("net_pnl", lambda s: (s > 0).mean() * 100),
    )
    m["net_pnl_krw"] = m["net_pnl_usd"] * KRW_PER_USD
    m["tax_usd_in_month"] = 0.0
    if tax_df is not None and len(tax_df) > 0:
        for _, r in tax_df.iterrows():
            month_label = pd.Timestamp(r["time"]).strftime("%Y-%m")
            mask = m["month"] == month_label
            if mask.any():
                m.loc[mask, "tax_usd_in_month"] += float(r["tax_usd"])
    m["after_tax_pnl_usd"] = m["net_pnl_usd"] - m["tax_usd_in_month"]
    m["after_tax_pnl_krw"] = m["after_tax_pnl_usd"] * KRW_PER_USD
    m = m.sort_values("month").reset_index(drop=True)
    return m


def plot_equity_v25(result_dict, save_path=None):
    eq = result_dict["equity"].copy()
    phase_df = result_dict["phase_transitions"]
    if len(eq) == 0:
        return
    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True)

    ax = axes[0]
    ax.plot(eq["time"], eq["equity"] * KRW_PER_USD / 1e8, label="엔진 잔고 (cap)", color="#1f77b4", linewidth=1.5)
    ax.plot(eq["time"], eq["total_assets_usd"] * KRW_PER_USD / 1e8,
            label="총 자산 (+ 누적 Excess)", color="#2ca02c", linewidth=2.0)
    ax.axhline(TARGET_BALANCE_KRW / 1e8, color="red", linestyle="--", alpha=0.6,
               label=f"Target {TARGET_BALANCE_KRW/1e8:.2f}억")
    if phase_df is not None and len(phase_df) > 0:
        for _, r in phase_df.iterrows():
            ax.axvline(r["time"], color="orange", linestyle=":", alpha=0.5)
    ax.set_title(f"{result_dict['symbol_key']} — Equity Curve (KRW 억)", fontsize=13)
    ax.set_ylabel("억 KRW")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(eq["time"], eq["cumulative_tax"] * KRW_PER_USD / 1e4, color="#d62728", linewidth=1.5)
    ax.set_title("누적 세금 (만원)", fontsize=13)
    ax.set_ylabel("만원")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.fill_between(eq["time"], eq["dd_pct"], 0, color="red", alpha=0.4)
    ax.set_title("Drawdown (%) — 총 자산 기준", fontsize=13)
    ax.set_ylabel("DD %")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        try:
            plt.savefig(save_path, dpi=120, bbox_inches="tight")
            print(f"📊 차트 저장: {save_path}")
        except Exception as e:
            print(f"[WARN] 차트 저장 실패: {e}")
    try:
        plt.show()
    except Exception:
        pass
    finally:
        plt.close(fig)


# =========================================================
# Cell 6: Main Execution
# =========================================================

if __name__ == "__main__":
    import copy
    import time as _time

    # Windows / macOS 호환 (ProcessPool 안전)
    try:
        mp.set_start_method("spawn", force=False)
    except RuntimeError:
        pass

    _t_total_start = _time.time()

    print("\n" + "=" * 80)
    print("  🎯 v25 STAGE 4K BOOST15 — 지수 엔진")
    print("=" * 80)
    print(f"  Stage 4K Tier 매트릭스 (크립토 4K BOOST15 동일):")
    print(f"    ALPHA_MAX:    risk × {TIER_RISK_MULT_COMMON['ALPHA_MAX']}")
    print(f"    ALPHA_HIGH:   risk × {TIER_RISK_MULT_COMMON['ALPHA_HIGH']}")
    print(f"    ALPHA_MED:    LONG×{ALPHA_MED_RISK_LONG}, SHORT×{ALPHA_MED_RISK_SHORT}")
    print(f"    SWEEP_GEM:    {SWEEP_RISK_BY_SCENARIO[SCENARIO]['SWEEP_GEM']}× (LONG only)")
    print(f"    SWEEP_ROOM:   {SWEEP_RISK_BY_SCENARIO[SCENARIO]['SWEEP_ROOM_FVG']}× (FVG/ONLY)")
    print(f"    COMPLETE_OUT: SKIP, SKIP_MSS: SKIP")
    print(f"  Stage 4I 차단:")
    print(f"    GEM_LONG_ONLY: {GEM_LONG_ONLY}")
    print(f"    ROOM_ONLY blacklist: {ROOM_ONLY_SYMBOL_BLACKLIST or 'NONE (지수 데이터 후 검토)'}")
    print(f"  Stage 4J 차단/booster:")
    print(f"    GEM_LONG_RP1, ROOM_ONLY_AVAX (지수에 영향 없음)")
    print(f"    BOOST: FVG_DOGE 1.5×, GEM_LONG_RP2 1.5×, GEM_LONG_RP0 1.2× ...")
    print(f"  Stage 4K Sentiment:")
    print(f"    booster {SENTIMENT_BOOSTER_BY_SCENARIO[SCENARIO]['BOOST']}×, cut {SENTIMENT_BOOSTER_BY_SCENARIO[SCENARIO]['CUT']}×")
    print(f"  RP_MULT_4H: RP0={RP_MULT_4H[0]}, RP1~5={RP_MULT_4H[1]}, RP6+ SKIP")
    print(f"  Wick threshold: {WICK_RATIO_5_Q1_THRESHOLD}")
    print(f"  Entry: LONG=zone_high (frac={LONG_BASE_ENTRY_FRAC}), SHORT=zone_low (frac={SHORT_BASE_ENTRY_FRAC}), refine={H1_REFINE_MAX_IMPROVE_FRAC}")
    print(f"  CPU cores: {mp.cpu_count()}")
    print("=" * 80)

    # Step 1: prepare_symbol (병렬)
    _t = _time.time()
    print("\n[STEP 1] 데이터 준비 (병렬)...")
    prepared_data = prepare_all_symbols_parallel(INDEX_SYMBOLS, SYMBOL_TF_MAP)
    print(f"\n✅ STEP 1 완료 ({_time.time()-_t:.1f}초)")

    # Step 2: Candidates (병렬)
    _t = _time.time()
    print("\n[STEP 2] Candidate 생성 (Stage 4K atomic 12 + tier 분류, 병렬)...")
    candidates_packs = generate_candidates_all_parallel(prepared_data)
    print(f"\n✅ STEP 2 완료 ({_time.time()-_t:.1f}초)")

    # 4K tier 분포
    all_cand = pd.concat([p["candidates"] for p in candidates_packs.values()], ignore_index=True) if candidates_packs else pd.DataFrame()
    if len(all_cand) > 0 and "tier_label_4h" in all_cand.columns:
        print(f"\n  [Stage 4K Tier 분포 (candidate 기준)]")
        tier_dist = all_cand["tier_label_4h"].value_counts().sort_index()
        for tier, n in tier_dist.items():
            print(f"    {tier:<20s}: {n:>4d}")

    # Step 3: Portfolio sim
    _t = _time.time()
    print("\n[STEP 3] Portfolio simulation (Stage 4K BOOST15)...")
    res = simulate_portfolio_v25(candidates_packs, max_total_risk=MAX_TOTAL_RISK, scenario_name=SCENARIO)
    print(f"\n✅ STEP 3 완료 ({_time.time()-_t:.1f}초)")

    # CSV 저장 (먼저)
    outdir = OUTDIR
    outdir.mkdir(exist_ok=True, parents=True)

    try:
        res["trades"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_trades.csv", index=False)
        res["equity"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_equity.csv", index=False)
        res["skipped"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_skipped.csv", index=False)
        res["phase_transitions"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_phase_transitions.csv", index=False)
        res["excess_log"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_excess_log.csv", index=False)
        res["tax_log"].to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_tax_log.csv", index=False)
        all_cand.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_all_candidates.csv", index=False)
        print(f"\n💾 CSV 저장 완료: {outdir}/")
        for f in sorted(outdir.iterdir()):
            sz = f.stat().st_size
            print(f"   {f.name}: {sz:,} bytes")
    except Exception as e:
        print(f"\n[ERROR] CSV 저장 실패: {e}")
        import traceback; traceback.print_exc()

    # 분석 리포트
    tdf = res["trades"]
    edf = res["equity"]

    if len(tdf) == 0:
        print("\n⚠️  거래가 0건입니다. tier 분포 / 차단 사유를 확인하세요.")
    else:
        # SUMMARY
        print("\n" + "=" * 110)
        print("  [1] SUMMARY")
        print("=" * 110)
        gp = tdf.loc[tdf["net_pnl"] > 0, "net_pnl"].sum()
        gl = abs(tdf.loc[tdf["net_pnl"] < 0, "net_pnl"].sum())
        pf = gp / gl if gl > 0 else float("inf")
        winrate = (tdf["net_pnl"] > 0).mean() * 100
        avg_r = float(tdf["r_multiple"].mean())

        final_usd = res["final_balance_usd"]
        final_krw = final_usd * KRW_PER_USD
        initial_krw = INITIAL_CAPITAL_KRW + MONTHLY_DEPOSIT_KRW * NUM_MONTHLY_DEPOSITS
        excess_krw = res["final_cumulative_excess_krw"]
        tax_krw = res["final_cumulative_tax_krw"]
        total_after_tax_krw = final_krw + excess_krw
        net_profit_krw = total_after_tax_krw - initial_krw
        return_pct = net_profit_krw / initial_krw * 100
        mdd_pct = float(edf["dd_pct"].min()) if len(edf) > 0 else 0

        summary_row = {
            "Name": "PORTFOLIO_INDEX_V25_STAGE4K",
            "Scenario": SCENARIO,
            "Trades": len(tdf),
            "Skipped": len(res["skipped"]),
            "WinRate_%": round(winrate, 3),
            "PF": round(pf, 3),
            "Avg_R": round(avg_r, 3),
            "Final_USD": round(final_usd, 2),
            "Final_KRW": round(final_krw, 0),
            "Excess_KRW": round(excess_krw, 0),
            "Tax_KRW": round(tax_krw, 0),
            "TotalAfterTax_KRW": round(total_after_tax_krw, 0),
            "NetProfit_KRW": round(net_profit_krw, 0),
            "Return_%": round(return_pct, 3),
            "MDD_%": round(mdd_pct, 3),
        }
        summary_df = pd.DataFrame([summary_row])
        print(summary_df.to_string(index=False))
        summary_df.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_summary.csv", index=False)

        # MONTHLY
        print("\n" + "=" * 110)
        print("  [2] MONTHLY SUMMARY")
        print("=" * 110)
        tdf["_dt"] = pd.to_datetime(tdf["entry_time"])
        tdf["month"] = tdf["_dt"].dt.to_period("M").astype(str)
        tdf["_is_win"] = (tdf["net_pnl"] > 0).astype(int)
        tdf["_is_loss"] = (tdf["net_pnl"] < 0).astype(int)
        monthly_summary = tdf.groupby("month").agg(
            trades=("trade_id", "count"),
            wins=("_is_win", "sum"),
            losses=("_is_loss", "sum"),
            net_pnl_usd=("net_pnl", "sum"),
            avg_r=("r_multiple", "mean"),
            winrate_pct=("_is_win", lambda s: s.mean() * 100),
        ).reset_index()
        monthly_summary["net_pnl_krw"] = monthly_summary["net_pnl_usd"] * KRW_PER_USD
        monthly_summary = monthly_summary.round({
            "net_pnl_usd": 2, "avg_r": 3, "winrate_pct": 2, "net_pnl_krw": 0
        })
        print(monthly_summary.to_string(index=False))
        monthly_summary.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_monthly_summary.csv", index=False)

        # ASSET
        print("\n" + "=" * 110)
        print("  [3] ASSET 전체 요약")
        print("=" * 110)
        asset_summary = tdf.groupby("symbol_key").agg(
            trades=("trade_id", "count"),
            wins=("_is_win", "sum"),
            losses=("_is_loss", "sum"),
            net_pnl_usd=("net_pnl", "sum"),
            avg_r=("r_multiple", "mean"),
            winrate_pct=("_is_win", lambda s: s.mean() * 100),
        ).reset_index()
        asset_summary["PF"] = asset_summary["symbol_key"].apply(
            lambda s: (
                tdf.loc[(tdf["symbol_key"] == s) & (tdf["net_pnl"] > 0), "net_pnl"].sum() /
                max(abs(tdf.loc[(tdf["symbol_key"] == s) & (tdf["net_pnl"] < 0), "net_pnl"].sum()), 1e-9)
            )
        )
        asset_summary["net_pnl_krw"] = asset_summary["net_pnl_usd"] * KRW_PER_USD
        asset_summary = asset_summary.round({
            "net_pnl_usd": 2, "avg_r": 3, "winrate_pct": 2, "PF": 3, "net_pnl_krw": 0
        }).sort_values("net_pnl_usd", ascending=False)
        print(asset_summary.to_string(index=False))
        asset_summary.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_asset_summary.csv", index=False)

        # TIER
        print("\n" + "=" * 110)
        print("  [4] Stage 4K TIER 별 성과")
        print("=" * 110)
        if "tier_label" in tdf.columns:
            tier_summary = tdf.groupby("tier_label").agg(
                trades=("trade_id", "count"),
                winrate_pct=("_is_win", lambda s: s.mean() * 100),
                avg_r=("r_multiple", "mean"),
                net_pnl_usd=("net_pnl", "sum"),
            ).reset_index()
            tier_summary["PF"] = tier_summary["tier_label"].apply(
                lambda t: (
                    tdf.loc[(tdf["tier_label"] == t) & (tdf["net_pnl"] > 0), "net_pnl"].sum() /
                    max(abs(tdf.loc[(tdf["tier_label"] == t) & (tdf["net_pnl"] < 0), "net_pnl"].sum()), 1e-9)
                )
            )
            tier_summary["net_pnl_krw"] = tier_summary["net_pnl_usd"] * KRW_PER_USD
            tier_summary["pnl_contribution_%"] = tier_summary["net_pnl_usd"] / tier_summary["net_pnl_usd"].sum() * 100
            tier_summary = tier_summary.round({
                "winrate_pct": 2, "avg_r": 3, "net_pnl_usd": 2,
                "PF": 3, "net_pnl_krw": 0, "pnl_contribution_%": 2,
            }).sort_values("net_pnl_usd", ascending=False)
            print(tier_summary.to_string(index=False))
            tier_summary.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_tier_summary.csv", index=False)

        # ★★★ v29: V5 TIER 별 성과 ★★★
        print()
        print("=" * 110)
        print(f"  [4b] V5 TIER (S/A/B) 별 성과 - RISK_SCENARIO = {RISK_SCENARIO}")
        print("=" * 110)
        if "tier_v5_final" in tdf.columns:
            v5_summary = tdf.groupby("tier_v5_final").agg(
                trades=("trade_id", "count"),
                winrate_pct=("_is_win", lambda s: s.mean() * 100),
                avg_r=("r_multiple", "mean"),
                net_pnl_usd=("net_pnl", "sum"),
                avg_v5_mult=("v5_mult_final", "mean"),
            ).reset_index()
            v5_summary["PF"] = v5_summary["tier_v5_final"].apply(
                lambda t: (
                    tdf.loc[(tdf["tier_v5_final"] == t) & (tdf["net_pnl"] > 0), "net_pnl"].sum() /
                    max(abs(tdf.loc[(tdf["tier_v5_final"] == t) & (tdf["net_pnl"] < 0), "net_pnl"].sum()), 1e-9)
                )
            )
            v5_summary["pnl_contribution_%"] = v5_summary["net_pnl_usd"] / v5_summary["net_pnl_usd"].sum() * 100
            v5_summary = v5_summary.round({
                "winrate_pct": 2, "avg_r": 3, "net_pnl_usd": 2,
                "PF": 3, "pnl_contribution_%": 2, "avg_v5_mult": 3,
            }).sort_values("net_pnl_usd", ascending=False)
            print(v5_summary.to_string(index=False))
            v5_summary.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_v5_tier_summary.csv", index=False)

        # ★★★ v30: V6 SUB-TIER 별 성과 ★★★
        print()
        print("=" * 110)
        print(f"  [4c] V6 SUB-TIER (S/S+/A+/A/A-) 별 성과 - V6_SCENARIO = {V6_SCENARIO}")
        print("=" * 110)
        if "sub_tier_v6" in tdf.columns:
            v6_summary = tdf.groupby("sub_tier_v6").agg(
                trades=("trade_id", "count"),
                winrate_pct=("_is_win", lambda s: s.mean() * 100),
                avg_r=("r_multiple", "mean"),
                net_pnl_usd=("net_pnl", "sum"),
                avg_v6_mult=("v6_mult_final", "mean"),
            ).reset_index()
            v6_summary["PF"] = v6_summary["sub_tier_v6"].apply(
                lambda t: (
                    tdf.loc[(tdf["sub_tier_v6"] == t) & (tdf["net_pnl"] > 0), "net_pnl"].sum() /
                    max(abs(tdf.loc[(tdf["sub_tier_v6"] == t) & (tdf["net_pnl"] < 0), "net_pnl"].sum()), 1e-9)
                )
            )
            v6_summary["pnl_contribution_%"] = v6_summary["net_pnl_usd"] / v6_summary["net_pnl_usd"].sum() * 100
            # Sub-tier 순서대로 정렬 (S → S+ → A+ → A → A-)
            order_map = {"S":0, "S+":1, "A+":2, "A":3, "A-":4, "B+":5, "B":6, "B-":7}
            v6_summary["_order"] = v6_summary["sub_tier_v6"].map(lambda x: order_map.get(x, 99))
            v6_summary = v6_summary.sort_values("_order").drop("_order", axis=1)
            v6_summary = v6_summary.round({
                "winrate_pct": 2, "avg_r": 3, "net_pnl_usd": 2,
                "PF": 3, "pnl_contribution_%": 2, "avg_v6_mult": 3,
            })
            print(v6_summary.to_string(index=False))
            v6_summary.to_csv(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_v6_sub_tier_summary.csv", index=False)

        # 차트
        try:
            plot_equity_v25(res, save_path=str(outdir / f"v33_{V6_SCENARIO}{_TF_SUFFIX}_equity_chart.png"))
        except Exception as e:
            print(f"[WARN] 차트 생성 실패: {e}")

        # 최종 요약
        print("\n" + "=" * 110)
        print("  🏆 v25 STAGE 4K 결과")
        print("=" * 110)
        print(f"  총 거래 수         : {len(tdf)}")
        print(f"  PF                 : {pf:.3f}")
        print(f"  Win Rate           : {winrate:.2f}%")
        print(f"  Avg R              : {avg_r:.3f}")
        print(f"  MDD                : {mdd_pct:.2f}%")
        print(f"  Return (세후)      : {return_pct:.1f}%")
        print(f"  최종 자산 (세후)    : {total_after_tax_krw:,.0f} KRW ({total_after_tax_krw/1e8:.2f}억)")
        print(f"  누적 Excess        : {excess_krw:,.0f} KRW")
        print(f"  누적 세금          : {tax_krw:,.0f} KRW")
        print("=" * 110)

    print(f"\n⏱  전체 실행 시간: {_time.time()-_t_total_start:.1f}초")
    print(f"\n💾 모든 결과: {outdir}/")
    print("\n🎯 v25 Stage 4K BOOST15 지수 엔진 백테스트 완료!")
