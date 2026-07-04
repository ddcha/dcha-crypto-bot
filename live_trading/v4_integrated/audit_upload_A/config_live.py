from __future__ import annotations

# =========================================================
# Stage 4L + Wave-aware (옵션 A+B+C) + Balance-aware BA (최종 채택)
#
# 백테스트 BOOST15 BA 최종:
#   PF 3.55, Win 63.46%, MDD -9.37%, Return 27,514%, retire 6m, total $2.66M
#
# 진입 결정 흐름:
#   1) Tier 분류 (classify_tier_stage4h): 4L tier mult 적용
#   2) 4I/4J 차단 + 4J Booster matrix (1.5× / 1.2×)
#   3) 4K Sentiment Booster (4 BOOST + 3 CUT)
#   4) Stage 3 처방 (Wave-aware):
#        - PD-aware: discount + SHORT × 0.5
#        - Weak Setup Blacklist: (d1,h4,h1,side) 21개 조합 × 0.2
#        - Wave Pattern Rules: 6+2 일반 패턴 (WEAK × 0.3-0.7, STRONG × 1.2-1.5)
#        - Balance-aware: balance < $50k 시 WEAK 비활성, STRONG만 적용
#   5) 최종 risk_pct = base × tier_mult × rp_mult × stage4j_mult
#                       × sentiment_mult × pd_aware × weak_setup × wave_pattern × rm
#
# Stage 4L Tier Redistribution (4K → 4L):
#   ALPHA_MAX  : 2.0 → 2.5
#   ALPHA_MED LONG : 0.8 → 0.6
#   ALPHA_MED SHORT: 1.2 → 1.0
#   SWEEP_GEM  : 1.0 → 4.0
#   RP_MULT[0] : 1.5 → 2.0
# =========================================================

CATEGORY = "linear"

USE_TESTNET = False
USE_DEMO = True

H4_INTERVAL = "240"
H1_INTERVAL = "60"

H4_LIMIT = 2000
H1_LIMIT = 1200

FEE_RATE = 0.0005
MAX_NOTIONAL_MULT = 3.0

# ─────────────────────────────────────────────
# v1.9_BASELINE: S/A 티어 notional cap 해제 (이전 버전)
# 4K 에서는 ALPHA tier 가 새 분류로 매핑됨 (TIER_CAP_4H 참조)
# ─────────────────────────────────────────────
MAX_NOTIONAL_MULT_SA_FREE = 999.0

# ─────────────────────────────────────────────
# Stage 4K Tier 시스템 (백테스트 4G/4H/4I/4J/4K 와 동일)
# =========================================================

# Tier 분류 결과별 risk multiplier
# ALPHA_MAX:  최강 알파 (overlap 단독 또는 score>=13 + pre>=1)
# ALPHA_HIGH: 강 알파 (volume + overlap + pre/wick 등)
# ALPHA_MED:  중 알파 (Win>=69% canonical 조합) — side aware
# SWEEP_GEM:  sweep + NOT room (LONG only, 4I)
# SWEEP_ROOM_FVG:  sweep + room + fvg
# SWEEP_ROOM_ONLY: sweep + room + NOT fvg (BTC/SOL/BNB/LINK 차단)
# COMPLETE_OUT: 그 외 (OUT_BEHAVIOR 따라)
# SKIP_MSS:    a_mss 단독 (다른 alpha 없음, 차단)
TIER_RISK_MULT_COMMON = {
    "ALPHA_MAX":    4.0,   # ★ [FINAL 정합 2026-06-04] 4L 2.5 → FINAL 4.0 (검증 완료, return↑)
    "ALPHA_HIGH":   1.5,
    "ALPHA_MED":    1.0,   # side-aware override (아래 별도)
    "COMPLETE_OUT": 1.0,
    "SKIP_MSS":     0.0,
}

# ALPHA_MED side-aware (4L 강등)
# ⭐ [v3 CONSERVATIVE 패치 — 2026-05-15] ALPHA_MED SHORT × 0.3
#   분석 근거 (h1choch BOOST25 trades):
#     IS  (~2024-12): n=45, Win 48.9%, PF 0.78, pnl -$6,178
#     OOS (2025+):    n=47, Win 36.2%, PF 0.81, pnl -$13,202
#     IS/OOS 둘 다 PF<1, 12분기 중 PF>1.5 분기 4개뿐 → 일관된 약점
#   → risk × 0.3 으로 손실 70% 흡수 (백테스트 검증 완료)
ALPHA_MED_RISK_LONG  = 0.6   # 4K 0.8 → 4L 0.6
ALPHA_MED_RISK_SHORT = 0.3   # ⭐ v3 patch: 1.0 → 0.3 (was 4K 1.2 → 4L 1.0 → v3 0.3)

# Tier 별 notional cap (자본 대비 max position size)
TIER_CAP_4H = {
    "ALPHA_MAX":       999.0,    # 사실상 무제한
    "ALPHA_HIGH":      999.0,
    "ALPHA_MED":       999.0,
    "SWEEP_GEM":       3.0,
    "SWEEP_ROOM_FVG":  3.0,
    "SWEEP_ROOM_ONLY": 3.0,
    "COMPLETE_OUT":    3.0,
    "SKIP_MSS":        3.0,
}

# COMPLETE_OUT 처리 방식
# "skip"     → 진입 안 함
# "keep_r1"  → 진입, risk × 1.0
# "keep_r05" → 진입, risk × 0.5
OUT_BEHAVIOR = "skip"

# ─────────────────────────────────────────────
# Stage 4K Scenario (booster mult variation)
# 백테스트 결과 기반 default = "BOOST15"
# ─────────────────────────────────────────────
SCENARIO = "BOOST15"

# SWEEP 계열 base risk mult (4L: SWEEP_GEM 1.0 → 4.0)
SWEEP_RISK_BY_SCENARIO = {
    "BOOST15": {
        "SWEEP_GEM":       4.0,    # 4K 1.0 → 4L 4.0 (Edge 4.76, worst loss $467 — 매우 안전)
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST25": {
        "SWEEP_GEM":       4.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
    "BOOST35": {
        "SWEEP_GEM":       4.0,
        "SWEEP_ROOM_FVG":  1.0,
        "SWEEP_ROOM_ONLY": 1.0,
    },
}

# ─────────────────────────────────────────────
# Stage 4I 차단 규칙
# ─────────────────────────────────────────────
GEM_LONG_ONLY = True                         # SWEEP_GEM SHORT 차단
ROOM_ONLY_SYMBOL_BLACKLIST = {               # SWEEP_ROOM_ONLY 적자 심볼
    "BTCUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT",
}

# ─────────────────────────────────────────────
# Stage 4K Sentiment Momentum lookback
# 직전 7일 모든 진입 시그널의 LONG/SHORT RP 평균 격차
# 직전 7-14일 sentiment 와의 차이로 momentum 측정
# ─────────────────────────────────────────────
SENTIMENT_LOOKBACK_DAYS = 7
SENTIMENT_MIN_SAMPLES   = 2          # 양 side 최소 시그널 개수
SENTIMENT_PREV_OFFSET   = 7          # 직전 sentiment = -14 ~ -7일

# 시나리오별 booster/cut mult
SENTIMENT_BOOSTER_BY_SCENARIO = {
    "BOOST15": {"BOOST": 1.5, "CUT": 0.5},
    "BOOST25": {"BOOST": 2.5, "CUT": 0.5},
    "BOOST35": {"BOOST": 3.5, "CUT": 0.5},
}

# ★ [FINAL 정합 2026-06-04] REVIVE_CUTS
#   CUT_NeutFalling_S (n=42 Win 71% PF 5.25) 와 CUT_ShortStable_L_DISABLED (n=10 Win 80% PF 16.4)
#   실데이터상 "cut" 가정과 정반대로 우수 → BOOST 로 재분류 (booster mult 적용).
#   True = FINAL 과 동일(부활) / False = 기존 v3 보수(각각 0.5×, 1.0×).
REVIVE_CUTS = True

# ─────────────────────────────────────────────
# Stage 4L RP boost 테이블 (RP0 = 2.0)
# RP0 만 2.0× boost (4K 1.5 → 4L 2.0)
# RP6+ 는 dict 에 없음 → SKIP
# ─────────────────────────────────────────────
RP_MULT_4H = {
    0: 2.0,   # 4K 1.5 → 4L 2.0
    1: 1.0,
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.0,
}
RP_FILTER_ENABLE = True

# 하위 호환 alias
RP_MULT_4E = RP_MULT_4H
RP_TIER_MULT_TABLE = RP_MULT_4H  # 기존 v1.9b import 호환

# ─────────────────────────────────────────────
# Global Risk Multiplier (패널 runtime 조절)
# ─────────────────────────────────────────────
RISK_MULTIPLIER_DEFAULT = 1.0
RISK_MULTIPLIER_MIN = 0.1
RISK_MULTIPLIER_MAX = 3.0

# ─────────────────────────────────────────────
# SL/Position 계산 상수
# ─────────────────────────────────────────────
SL_BUFFER_MULT = 0.08

# ─────────────────────────────────────────────
# Volume Filter
# ─────────────────────────────────────────────
USE_VOLUME_FILTER = True
VOLUME_AVG_WINDOW = 20
VOLUME_SPIKE_MULT = 1.1
VOLUME_STRICT_MODE = False
VOLUME_PREV_MULT = 1.5

# ─────────────────────────────────────────────
# 자동 실행 루프
# ─────────────────────────────────────────────
LOOP_SLEEP_SECONDS = 15

# ★★★ v2.2: Zone-Proximity Trigger ★★★
# Light loop = 가격만 polling (가벼움)
# 가격이 zone 의 high/low 에서 ZONE_PROXIMITY_PCT% 이내일 때만 풀 SMC 분석 (Heavy)
# 평소엔 거의 0% CPU. zone 근처일 때만 일시 부하.
USE_ZONE_PROXIMITY_TRIGGER = True  # False 면 기존 방식 (매 LOOP 풀 분석)
LIGHT_LOOP_SLEEP_SECONDS = 5       # Light loop 주기 (가격 polling) - 진입 응답성
ZONE_PROXIMITY_PCT = 0.5           # Zone high/low 의 ±0.5% 이내 = HOT
ZONE_CACHE_REFRESH_SECONDS = 3600  # Zone cache 갱신 주기 (1시간 = H4 봉 4번 안에 갱신)
# Zone cache 강제 갱신 트리거: 모든 symbol 의 가격이 모든 zone 에서 멀어졌을 때
# (zone 갱신 했더니 전부 거리 멀면, 새 H4 봉이 닫혔을 가능성 → 다음 cycle 에 다시 fetch)

# 청산 후 재진입 쿨다운 (시간)
EXIT_COOLDOWN_HOURS = 8    # H4 2봉 = 8시간

# ★트레일링 방식 (2026-07-04 기준조건): "backtest"=백테엔진 트레일(직전봉 range중점−0.10×H4ATR),
#   "rratchet"=구 라이브 R래칫. 백테 검증상 backtest 가 MDD −17.75% vs R래칫 −27% 로 우위 → 기본 backtest.
TRAIL_MODE = "backtest"

LOG_LEVEL = "INFO"

# ─────────────────────────────────────────────
# v1.9b atomic 계산용 (백테스트 호환)
# ─────────────────────────────────────────────
WICK_RATIO_5_Q1_THRESHOLD = 0.2300
PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5

# 백테스트의 atomic 계산용 (compute_trade_tags)
SWEEP_LOOKBACK_BARS = 5

# ─────────────────────────────────────────────
# Tier 우선 정렬 + exclude 최근 H1
# ─────────────────────────────────────────────
USE_TIER_PRIORITY_SORT = True
EXCLUDE_RECENT_H1_FOR_TIER = 0

# runtime_state 기본값
TRADING_ENABLED_DEFAULT = True
KILL_SWITCH_DEFAULT = False

# control panel / runtime
PANEL_AUTO_REFRESH_SECONDS = 5
MAIN_LOCK_FILE = "main.lock"

# exchange api retry
READ_API_MAX_RETRIES = 3
READ_API_RETRY_SLEEP_SECONDS = 0.8

# ─────────────────────────────────────────────
# 1m wick touch 감지 (15초 루프 사이 zone 빠른 wick 포착)
# ─────────────────────────────────────────────
USE_1M_WICK_TOUCH = True
WICK_TOUCH_LOOKBACK_BARS = 5         # 최근 5개 1분봉 (5분 범위)
WICK_TOUCH_MAX_EXIT_FRAC = 0.30      # Zone 폭의 30% 이상 이탈 시 skip


# =========================================================
# ⭐⭐⭐ Stage 3 Wave-aware 처방 (옵션 A+B+C + Balance-aware) ⭐⭐⭐
# 백테스트 BOOST15 BA 최종 채택 — PF 3.55, MDD -9.37%, retire 6m
# =========================================================

# 옵션 1 (Balance-aware): 자본 < 임계 시기에 WEAK 처방 비활성, STRONG만 적용
# 목적: 자본 작은 초기에 risk 축소로 retire 늦어지는 문제 해결
USE_BALANCE_AWARE_WEAK_SKIP = True
WEAK_SKIP_BALANCE_THRESHOLD_USDT = 50_000.0  # 이 이하에선 WEAK 비활성

# 처방 A: PD-aware filter (discount + SHORT × 0.5)
USE_PD_AWARE_FILTER = True
PD_AWARE_DISCOUNT_SHORT_MULT = 0.5

# 처방 B: 폐기 (Reverse exit / Fresh CHoCH — 시스템 알파 손상)
USE_REVERSE_EXIT     = False
USE_FRESH_CHOCH_RISK = False
FRESH_CHOCH_AGE_THRESHOLD_H = 24.0
FRESH_CHOCH_RISK_MULT       = 0.5
REVERSE_EXIT_CUTOFF_H       = 8.0

# 옵션 A: Weak Setup Blacklist (21개 명시 조합, risk × WEAK_SETUP_RISK_MULT)
USE_WEAK_SETUP_FILTER = True
WEAK_SETUP_RISK_MULT = 0.2   # fine-tuning sweep 결과 최적 (0.3 → 0.2)
WEAK_SETUPS_SET = {
    # (d1_wave, h4_wave, h1_wave, side) — 백테스트 분석 PF < 0.7 × baseline (≈ 1.87) 조합
    ("impulse_up",   "impulse_down",  "impulse_up",   "short"),  # PF 0.29
    ("compression",  "compression",   "compression",  "short"),  # PF 0.31
    ("impulse_down", "impulse_down",  "expansion",    "short"),  # PF 0.35
    ("impulse_down", "impulse_down",  "impulse_down", "short"),  # PF 0.38
    ("expansion",    "impulse_up",    "impulse_down", "long"),   # PF 0.44
    ("impulse_up",   "compression",   "impulse_down", "long"),   # PF 0.45
    ("impulse_up",   "impulse_up",    "expansion",    "short"),  # PF 0.50
    ("expansion",    "impulse_up",    "compression",  "long"),   # PF 0.53
    ("impulse_up",   "expansion",     "compression",  "short"),  # PF 0.59
    ("compression",  "impulse_up",    "impulse_down", "long"),   # PF 0.63
    ("expansion",    "impulse_up",    "impulse_up",   "long"),   # PF 0.63
    ("compression",  "impulse_down",  "expansion",    "short"),  # PF 0.64
    ("impulse_down", "impulse_down",  "expansion",    "long"),   # PF 0.67
    ("impulse_up",   "compression",   "expansion",    "long"),   # PF 0.73
    ("impulse_down", "expansion",     "impulse_up",   "short"),  # PF 0.95
    ("impulse_down", "compression",   "impulse_up",   "short"),  # PF 1.16
    ("impulse_down", "impulse_down",  "impulse_up",   "long"),   # PF 1.18
    ("compression",  "compression",   "impulse_up",   "long"),   # PF 1.23
    ("impulse_up",   "expansion",     "impulse_down", "long"),   # PF 1.24
    ("impulse_up",   "impulse_up",    "impulse_up",   "long"),   # PF 1.63
    ("impulse_down", "impulse_up",    "compression",  "long"),   # PF 1.73
}

# 옵션 B: Wave Pattern Rules (rule-based 일반 패턴 + 옵션 C 정밀 sub-pattern)
USE_WAVE_PATTERN_RULES = True
PATTERN_MULT_FLOOR     = 0.2
PATTERN_MULT_CEILING   = 2.0
PATTERN_MULTS = {
    # WEAK (검증된 약점 일반 패턴)
    "weak_d1_h4_opposite":           0.5,   # PF 1.50, 56% baseline (D1 ≠ H4)
    "weak_h1_expansion_short":       0.5,   # PF 1.36, 51% baseline (H1=exp + SHORT)
    "weak_d1up_h4corr_long":         0.7,   # PF 1.20 (D1up + H4 correction + LONG)
    # STRONG (검증된 강점 일반 패턴)
    "strong_expansion_x_expansion":  1.5,   # PF 5.24 (D1+H4 모두 expansion)
    "strong_h1_compression_short":   1.3,   # PF 4.92 (H1=comp + SHORT)
    "strong_h1_compression_long":    1.2,   # PF 3.08 (H1=comp + LONG)
    # 옵션 C 정밀 sub-pattern (T2 분석 기반)
    "weak_T2_h1expansion":           0.3,   # n=45 PF 0.59 (D1=H4 same + H1=exp)
    "strong_T2aligned_h1comp_short": 1.5,   # n=16 PF 20.01 (D1=H4=down + H1=comp + SHORT)
}

# Same-side cooldown (생성 후 같은 방향 재진입 차단)
SAME_SIDE_COOLDOWN_HOURS = 24.0    # H4 6봉 = 24시간 (백테스트 SAME_SIDE_COOLDOWN_BARS=6 환산)
