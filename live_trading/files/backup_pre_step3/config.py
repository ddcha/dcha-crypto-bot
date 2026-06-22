from __future__ import annotations

# =========================================================
# Stage 4K BOOST15 시스템 (백테스트 검증 baseline)
#
# 백테스트 결과 (9코인, 3년):
#   trades 1077, win 65.09%, PF 2.644, MDD -10.36%, Return 15,797%, 퇴사 10m
#
# 진입 결정 흐름:
#   1) Tier 분류 (classify_tier_stage4h):
#        ALPHA_MAX, ALPHA_HIGH, ALPHA_MED, SWEEP_GEM, SWEEP_ROOM_FVG,
#        SWEEP_ROOM_ONLY, COMPLETE_OUT, SKIP_MSS
#   2) 4I 차단: GEM SHORT 차단, ROOM_ONLY 4심볼 차단
#   3) 4J 차단: GEM_LONG_RP1 outlier, ROOM_ONLY_AVAX outlier
#   4) 4J Booster matrix: 1.5× / 1.2× (DOGE_FVG, GEM_LONG_RP2 등)
#   5) 4K Sentiment Booster: 직전 7일 LONG/SHORT RP 격차 + 변화량 매트릭스
#   6) RP boost: RP0 → 1.5×
#   7) 최종 risk_pct = base × tier_mult × rp_mult × stage4j_mult
#                       × sentiment_mult × risk_multiplier
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
    "ALPHA_MAX":    2.0,
    "ALPHA_HIGH":   1.5,
    "ALPHA_MED":    1.2,   # side-aware override (아래 별도)
    "COMPLETE_OUT": 1.0,   # OUT_BEHAVIOR 에 따라 변경
    "SKIP_MSS":     0.0,   # 차단
}

# ALPHA_MED side-aware
ALPHA_MED_RISK_LONG  = 0.8
ALPHA_MED_RISK_SHORT = 1.2

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

# SWEEP 계열 base risk mult (4J/4K: 모두 1.0 평평)
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

# ─────────────────────────────────────────────
# Stage 4K RP boost 테이블 (백테스트 RP_MULT_4E)
# RP0 만 1.5× boost (Win 92%+ 의 가장 강한 신호)
# RP6+ 는 dict 에 없음 → SKIP
# ─────────────────────────────────────────────
RP_MULT_4H = {
    0: 1.5,
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
