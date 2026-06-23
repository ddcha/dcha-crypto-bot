# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지 (config: 모든 상수·테이블 단일 소스).
#     14개 중간 재정의 상수는 원본 라인순서 그대로 모아 최종 실효값이 승리한다.
#     재생성: python tools/extract_modules.py --write
# =========================================================================
# =========================================================
# smc_crypto_9coins  STAGE 4D: ATOMIC DECOMPOSITION EXPERIMENT
#
# [실험 목적]
#   Stage 4C 결과에서 발견한 핵심 패턴:
#     - Tier 엔진은 품질 필터가 아니라 risk scaler 였다
#     - "tier 단독" 거래가 가장 약했다 (PF 1.29)
#     - RP0 이 숨은 최강 (PF 6.22) — RP0 과 RP1 이 동일 boost 받는 게 옳은지 의문
#     - SWEEP + VOLUME 이 진짜 alpha
#
#   Stage 4D 는 이 모든 복합 변수(Tier / RP) 를 원자(atomic) 단위로 분해하여
#   각 원자의 순수 기여도를 측정한다.
#
# [핵심 원칙]
#   (1) 모든 risk multiplier 를 1.0 고정 — 순수 signal 품질만 비교
#       - tier_mult = 1.0 강제
#       - rp_mult 곱 제거 (RP_TIER_MULT_TABLE 미사용)
#       - risk_multiplier = 1.0
#       - cap = 3.0 고정 (S/A cap FREE 제거)
#
#   (2) 모든 게이트 해제 — MIN_SCORE 7.5 만 유일 게이트
#       - Tier D skip 제거 (모든 거래 수용)
#       - SWEEP / VOLUME 게이트 아님 (태깅만)
#
#   (3) 12개 atomic 태그 전부 계산 + 로그
#       Tier 구성 (5): a_pre_total_ge4, a_sweep_count_2_4, a_score_ge13,
#                      a_wick_le_q1, a_pre_total_ge1
#       RP 구성 (5):   a_trend_align, a_mss, a_fvg, a_overlap, a_room
#       Entry signal (2): a_sweep, a_volume
#
# [분석 산출물 8개]
#   1) atom_solo_effect.csv          — 각 원자 PASS vs FAIL 효과
#   2) sweep_vol_pivot.csv           — SWEEP+VOL 기준 원자 추가 시 PF 변화 (핵심)
#   3) tier_decomposition.csv        — Tier 구성 원자별 기여도
#   4) rp_decomposition.csv          — RP 구성 원자별 기여도 + side
#   5) rp_level_analysis.csv         — RP0 vs RP1 vs RP2+ 세분 분석
#   6) side_x_atom.csv               — LONG/SHORT × 12 원자
#   7) top_combo_analysis.csv        — 2-3개 원자 조합 brute-force PF 상위 30개 (핵심)
#   8) tier_original_vs_atoms.csv    — 원본 Tier 판정이 원자로 어떻게 구성되는지
#
# [유지]
#   - 9코인 / MIN_SCORE 7.5 / REFINE 제거 / H4 exit
#   - 단일 포지션 / 병렬화 / 실전 근사 fill
#
# [예상 거동 (Stage 4A 와 유사)]
#   - Trades: Stage 4A 1,624 와 유사 (~1,600)
#   - Win%: ~62%, PF: ~2.0, MDD: ~-11%
#   - Return: Stage 4A 12,455% 수준 (risk 증폭 없음)
#   - 실험 목적은 Return 최적화가 아니라 atomic 기여도 매핑
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

# =========================================================
# ⭐⭐⭐ [ATOM 진입게이트 — OR / AND] — VS Code 직접 실행용
# =========================================================
#   목적: 지정한 원자 리터럴을 "실제 진입게이트"로 박아 백테스트하고,
#         진입한 모든 트레이드에 12원자 true/false 를 전부 기록.
#         → 같은 방식으로 "다음에 더할 원자"를 co-occurrence 로 계속 스크리닝(퍼널 반복).
#
#   ⭐ AND 모드 (이번 핵심): 지정 리터럴이 "전부 True" 여야만 진입 (AND).
#       예) 2-AND 게이트:  ~a_fvg AND ~a_pre_total_ge4
#           3-AND 게이트:  ~a_volume AND ~a_sweep AND ~a_fvg
#       → trades.csv 에 12원자 플래그가 다 찍히므로, 그 로그를 다시 쪼개
#         "이 AND 게이트 + 4번째 원자" 의 OOS PF 를 screen_next_atom.py 로 확인.
#
#   모드 (이 파일에서 ATOM_GATE_MODE 바꿔 실행):
#     "AND"   → ATOM_AND_LIST 의 리터럴이 전부 True 여야 진입. (★ 2-AND / 3-AND 용)
#     "OR12"  → 12원자 중 하나라도 True 면 진입 (OR-of-12).
#     "CUSTOM"→ ATOM_GATE_CUSTOM_LIST 의 리터럴들을 OR.
#     "OFF"   → 게이트 없음(MIN_SCORE 7.5 만). 12플래그는 그대로 기록(전수 로그).
#
#   리터럴 표기: "a_fvg"=양극(True 진입), "~a_fvg"=음극(False 진입). (스크린의 fvg~ = ~a_fvg)
#   룩어헤드 차단: HONEST_STAGE=5 강제 (게이트·기록 원자 모두 i-1 신호봉).
#   ※ 쉘 환경변수(HONEST_STAGE / ATOM_OR_LIST / ATOM_AND_LIST)를 직접 주면 그 값 우선(setdefault).
# =========================================================
import os as _os_cfg

ATOM_GATE_MODE = "OFF"                        # ⭐ 존 재구성 단독 측정: 원자 제외(로그만, 게이트 X)

# ★ AND 모드 게이트 리터럴 — 여기만 바꿔가며 퍼널 반복 (2-AND → 3-AND → 4-AND ...)
#   현재 스크리닝에서 유효 후보로 나온 값들:
#     2-AND:  "~a_fvg,~a_pre_total_ge4"             (fvg~ + pre_total_ge4~, OOS PF 1.037)
#     3-AND:  "~a_volume,~a_sweep,~a_fvg"           (volume~ + sweep~ + fvg~, OOS PF 1.868)
ATOM_AND_LIST = "~a_fvg,~a_pre_total_ge4"

ATOM_GATE_CUSTOM_LIST = "a_sweep,a_volume"    # ATOM_GATE_MODE="CUSTOM" 일 때만 사용

_ALL_12_ATOMS = [
    "a_sweep", "a_volume",                                                          # Entry signal (2)
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1",  # Tier (5)
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",                        # RP (5)
]

# 진입게이트는 정직봉(i-1) 필수 — 안 그러면 게이트·로그가 룩어헤드로 오염됨
_os_cfg.environ.setdefault("HONEST_STAGE", "5")

if ATOM_GATE_MODE == "AND":
    _os_cfg.environ.setdefault("ATOM_AND_LIST", ATOM_AND_LIST)
elif ATOM_GATE_MODE == "OR12":
    _os_cfg.environ.setdefault("ATOM_OR_LIST", ",".join(_ALL_12_ATOMS))
elif ATOM_GATE_MODE == "CUSTOM":
    _os_cfg.environ.setdefault("ATOM_OR_LIST", ATOM_GATE_CUSTOM_LIST)
elif ATOM_GATE_MODE == "OFF":
    pass  # 게이트 없음(전수). 12플래그는 그대로 기록.
else:
    raise ValueError(f"ATOM_GATE_MODE 잘못됨: {ATOM_GATE_MODE!r} (AND|OR12|CUSTOM|OFF 중 하나)")

print("=" * 78)
print(f"[ATOM GATE] mode={ATOM_GATE_MODE}  HONEST_STAGE={_os_cfg.environ.get('HONEST_STAGE')}")
print(f"            ATOM_AND_LIST={_os_cfg.environ.get('ATOM_AND_LIST', '(none)')}")
print(f"            ATOM_OR_LIST ={_os_cfg.environ.get('ATOM_OR_LIST',  '(none)')}")
print("=" * 78)

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
MIN_SCORE = float(_os_cfg.environ.get("MIN_SCORE", "7.5"))   # ⭐ 진입 문턱. env로 6.0~9.0 스윕 (예: MIN_SCORE=6.0)
# ⭐ OB 정의 토글: "strict"=정통(기원 base캔들+바디) / "legacy"=직전 반대캔들 풀레인지 /
#                  "engulf"=직전 반대캔들보다 큰(바디) 임펄스 출현 시, 그 *직전 반대캔들의 바디*를 OB로
OB_MODE = _os_cfg.environ.get("OB_MODE", "strict")

# ── 존 게이트 엄밀화 스윕 (H4 전용) — feature/gate-tighten ──
#   기본값=현행 → env 없이 돌리면 baseline 과 동일(회귀 0).
SWEEP_RECENT_N   = int(_os_cfg.environ.get("SWEEP_RECENT_N", "10"))      # H4 recent-sweep 봉수
DISP_ATR_MULT    = float(_os_cfg.environ.get("DISP_ATR_MULT", "0.90"))   # displacement 최소 레인지/ATR
DISP_BODY_RATIO  = float(_os_cfg.environ.get("DISP_BODY_RATIO", "0.45")) # displacement 최소 바디비율
MSS_MODE         = _os_cfg.environ.get("MSS_MODE", "legacy")             # "legacy"(롤링맥스) | "choch"(스윙기반)

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
# ⭐ 트레이딩에 활용하는 캔들 윈도우: i-1봉 기준 과거 N개월(룩어헤드 0). 이 기간 내 생성된 OB/FVG만 후보.
#    (H4 24/7 기준 3개월 ≈ 540봉. expire_idx(생성+ZONE_MAX_AGE) 게이트를 이 시간윈도우로 대체.)
H4_TRADE_WINDOW_MONTHS = 3
MAX_NOTIONAL_MULT = 3.0

H1_REFINE_LOOKBACK_HOURS = 12
H1_REFINE_MAX_IMPROVE_FRAC = 0.25
H1_CHOCH_CONFIRM_HOURS = 16

# ── H1×H4 존 정밀화(refine) 토글 — feature/h1-refine-zone ──
#   1 이면 H4 FVG/OB 존을 H1 FVG/OB 와의 가격겹침 교집합으로 좁혀 진입가·손절을 타이트화.
#   기본 off → baseline(=원본) 동작 그대로 보존. (의도된 동작 변경, 효과는 CI 로 측정)
USE_H1_REFINE = _os_cfg.environ.get("USE_H1_REFINE", "0") == "1"

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
# =========================================================
# ⭐ BROAD 원자 튜닝 상수 (AND 교집합 전제 — 각 원자는 high-recall, 컷은 느슨)
#   설계: 축1(현상 정확성) 유지 / 축2(임계값) 느슨. tight화는 AND가 담당.
#   더 broad로: MIN↓ / FLOOR↓ / RR↓.  더 tight로: 반대.
# =========================================================
BROAD_VOL_RELVOL_MIN  = 1.5    # a_volume: 존형성창 max거래량 / median(20) ≥ 1.5 (기존 1.1 스파이크아님→1.5)
BROAD_FVG_SIZE_ATR    = 0.10   # a_fvg: 존(임밸런스) 크기 ≥ 0.10·ATR (미세 갭만 배제)
BROAD_SCORE_STRONG    = 10.0   # a_score_ge13: 절대 13(tight) → 10(진입floor 7.5 대비 '강', broad)
BROAD_SWEEP_CNT_MIN   = 2      # a_sweep_count_2_4: 밴드(2~4) → 단조 ≥2 (broad)
BROAD_WICK_MAX        = 0.35   # a_wick_le_q1: 0.23(Q1,tight) → 0.35 (broad, '접근 깨끗함' 개념 유지)
BROAD_TREND_INCL_NEUTRAL = False  # a_trend_align: strict(정합만). True 였을 때 100% 항상참→분산0 이라 복원.
BROAD_ROOM_RR_MIN     = 1.5    # a_room: 실RR(타겟/존리스크) ≥ 1.5 (proxy risk=atr*0.08 → 존두께)

# ── 신규축: 변동성/레짐 원자 knob (전부 트레일링, 룩어헤드 0) ──
REG_EFF_N          = 10     # a_efficiency: Kaufman ER 윈도우(봉)
REG_EFF_MIN        = 0.30   #   ER ≥ 0.30 = 추세 레짐 (broad)
REG_BB_N           = 20     # a_bb_squeeze: BB 표준편차 윈도우
REG_BB_K           = 2.0    #   BB 배수
REG_BB_PCTL_WIN    = 100    #   BB폭 백분위 비교 트레일링 윈도우
REG_BB_SQUEEZE_PCTL= 0.30   #   BB폭이 하위 30% = 압축 (broad)
REG_VOL_WIN        = 100    # a_vol_expansion: ATR 백분위 트레일링 윈도우
REG_VOL_PCTL       = 0.50   #   ATR 백분위 ≥ 0.5 = 확장 (broad)


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

USE_FILTER_GROUPS = False
USE_VOLUME_FILTER = False
USE_LIQUIDITY_SWEEP_CONF = False
USE_D1_TREND_FILTER = False
USE_PULLBACK_DEPTH = False
USE_ATR_FILTER = False
