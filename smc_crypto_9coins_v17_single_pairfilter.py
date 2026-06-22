# =========================================================
# smc_crypto_9coins  v1.7 LTF (7coins base + BNB + ADA)
#
# [REALISTIC 확정 (2026-04-23)]
#
#   ★ 이 파일의 역할 ★
#     - v1.9_BASELINE 의 "실전 재현" 버전
#     - 백테스트 낙관 편향 제거, 실전과 괴리 최소화
#     - 실전 엔진과 비교 가능한 "정직한 숫자" 산출
#
#   ★ 3가지 주요 변경 ★
#
#   1) REFINE 제거
#      - refine_entry_with_h1_fvg 호출 완전 제거
#      - fill_entry = max(zone_low, min(open, zone_high)) 만 사용
#      - 이유: 실전 엔진에서 refine 안 쓰고 있음
#             (실전은 current_price 로 시장가 즉시 체결)
#
#   2) TIER 우선 계산 (evaluate_zones_at_current_time)
#      - 모든 active zone 에 대해 tier 미리 계산
#      - Tier 우선 정렬: tier_mult_final > eff_score
#      - Tier S/A 가 낮은 score 라도 낮은 tier 보다 먼저 진입 시도
#      - 이유: 신호 품질 기반 우선순위 (경제적 합리성)
#
#   3) 최근 1 H1 제외 (실전 지연 시뮬레이션)
#      - compute_pre_entry_confluence 에서 최근 1 H1 봉 제외
#      - compute_wick_ratio_5 도 동일
#      - 이유: 실전 60초 루프 환경에서 최근 H1 정보 즉시 활용 불가
#             (진행중인 H1 봉은 아직 닫히지 않음)
#
#   ★ 그대로 유지 ★
#     - v1.9b 티어 시스템 (S/A/B/C/D × 3.0/1.5/0.8/0.7/skip)
#     - v1.9g RP Boost 테이블 {rp0=1.5, rp1=1.5, rp2~5=1.0, rp>=6 skip}
#     - S/A 티어 notional cap 해제 (MAX_NOTIONAL_MULT_SA_FREE = 999.0)
#     - Phase A/B 자동 전환 (Target $368,991)
#     - 리스크 배수 = 1.0 (패널 multiplier 는 실전 기능)
#
#   ★ 예상 결과 (v1.9_BASELINE 대비) ★
#     - Return: 28,000 ~ 33,000% (-20~30% 감소)
#     - MDD: -5.5 ~ -7% (약간 증가)
#     - PF: 8.0 ~ 8.5
#     - Win rate: 76 ~ 78%
#
#   ★ 왜 낙관적 편향 제거인가 ★
#     - Refine 효과: 백테스트에서 "이상적 진입가" 체결 가정
#       → 실전에선 재현 불가 (limit order 방식 필요)
#     - 최근 1 H1: 백테스트는 "H4 종가 시점 직전 H1" 까지 접근 가능
#       → 실전은 "진행중 H1 제외하고 그 전까지" 만 접근
#
# [비교 baseline]
#   v1.9_BASELINE (refine + no exclude):
#     Return 40,776% | PF 9.591 | MDD -5.15% | Win 78.43%
#
#   ★ v1.9_BASELINE_REALISTIC (이 파일):
#     예상 Return 28,000~33,000% | PF 8.0~8.5 | MDD -5.5~-7% | Win 76~78%
#     "현실 기반 기대치"
# =========================================================

try:
    _ipy = get_ipython()  # noqa: F821
    if _ipy is not None:
        _ipy.run_line_magic('pip', 'install -q pandas numpy matplotlib requests')
except (NameError, AttributeError):
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
MIN_SCORE = 7.5

# v1.9: 쿨다운 유지, DayLimit 해제
SAME_SIDE_COOLDOWN_BARS = 6
DAY_TRADE_LIMIT = 999

LONG_BASE_ENTRY_FRAC = 0.40
SHORT_BASE_ENTRY_FRAC = 0.60

H4_PIVOT_SWING_LEN = 3
H4_MSS_LOOKBACK = 8
H4_OB_LOOKBACK = 8
H4_PD_LOOKBACK = 40
H4_CHOCH_BREAK_ATR_MULT = 0.18
H4_MARKET_STATE_BARS = 8
H4_ZONE_MAX_AGE = 16
MAX_NOTIONAL_MULT = 3.0

# ★★★ v1.9g 확장: S/A 티어 notional cap 해제 ★★★
#
# simulate_scenario_v19g 인자 sa_cap_free=True 일 때,
# S 와 A 티어의 포지션 계산에서 MAX_NOTIONAL_MULT 를 이 값으로 덮어쓴다.
# 999.0 → 사실상 무제한 (risk 자체 제약만 남음).
#
# 예) S × rp_boost = 3.0 × 1.5 = 4.5 → BTC 9.9% risk 전부 반영
# 주의: risk×2 모드에선 S × rp=0/1 이 19.8% risk 가 될 수 있음.
MAX_NOTIONAL_MULT_SA_FREE = 999.0

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
FRESHNESS_MAX_BONUS = 1.5

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
    # v1.7 LTF 9coins 확장
    "BNBUSDT":  0.010,  # ETH/SOL 와 유사 (시총 TOP5, 중상 변동성)
    "ADAUSDT":  0.008,  # XRP/DOGE/LINK 와 유사 (중 변동성)
}

PHASE_B_RISK = {
    "BTCUSDT":  0.018715, "ETHUSDT":  0.015000, "SOLUSDT":  0.004676,
    "DOGEUSDT": 0.002636, "LINKUSDT": 0.002619, "XRPUSDT":  0.002380, "AVAXUSDT": 0.001791,
    # v1.7 LTF 9coins 확장 — BNB/ADA 는 SOL/LINK 수준
    "BNBUSDT":  0.004500,
    "ADAUSDT":  0.002500,
}

# =========================================================
# ★★★ v1.9b/v1.9e/v1.9g TIER CONFIG (동일) ★★★
# =========================================================
#
# D 조건 = (pre_total >= 4) OR (2 <= sweep <= 4) OR (score >= 13)
# 꼬리 조건 = wick_ratio_5 <= WICK_RATIO_5_THRESHOLD
#
# 티어:
#   S = D AND 꼬리조건     → risk × 3.0
#   A = D 단독               → risk × 1.5
#   B = 꼬리조건 단독         → risk × 0.8
#   C = pre>=1 일반          → risk × 0.7
#   D = pre=0                → SKIP
#
TIER_RISK_S = 3.0
TIER_RISK_A = 1.5
TIER_RISK_B = 0.8
TIER_RISK_C = 0.7
TIER_RISK_D = 0.0
SKIP_TIER_D = True

# threshold (median 근처)
WICK_RATIO_5_Q1_THRESHOLD = 0.2300

PRE_ENTRY_LOOKBACK_LTF_BARS = 8
WICK_LOOKBACK_BARS = 5

# =========================================================
# ★★★ v1.9g RP BOOST (강점 증폭 방식) ★★★
# =========================================================
#
# 동작 순서: tier 분류(기존 v1.9b) → RP 테이블 lookup (v1.9g)
#
#   RP_TIER_MULT_TABLE 에 있으면 → tier_mult × mult
#   RP_TIER_MULT_TABLE 에 없으면 → SKIP
#
# v1.9g 철학: 약점을 자르지 않고(rp=3/4 그대로 수용), 강점만 증폭
#   rp=0: ×1.5 (Win 92.59%, avg_R 1.599)  → 주력 증폭
#   rp=1: ×1.5 (Win 87.08%, avg_R 1.788)  → 주력 증폭
#   rp=2: ×1.0 (Win 76.37%, avg_R 1.276)  → 그대로
#   rp=3: ×1.0 (Win 68.00%, avg_R 0.532)  → 그대로 (skip 안 함)
#   rp=4: ×1.0 (Win 77.42%, avg_R 0.485)  → 그대로 (skip 안 함)
#   rp=5: ×1.0 (드물지만 수용)
#   rp>=6: skip (구조상 거의 불가능)
#
# 안전장치: MAX_NOTIONAL_MULT = 3.0 으로 과다 리스크 자동 cap
#   예) S × rp=0/1 = 3.0 × 1.5 = 4.5 → notional cap 걸려 실질 ~2.2% risk
#
RP_FILTER_ENABLE = True

RP_TIER_MULT_TABLE = {
    0: 1.5,    # +50% boost
    1: 1.5,    # +50% boost (주력)
    2: 1.0,    # 그대로 (v1.9b와 동일)
    3: 1.0,    # 그대로 (v1.9b와 동일, skip 안 함)
    4: 1.0,    # 그대로 (v1.9b와 동일, skip 안 함)
    5: 1.0,    # 그대로 (드물게 발생 가능)
}
# rp >= 6 → skip (구조상 거의 나오지 않음)

# (호환성 유지용 — 이전 v1.9d 코드와의 backward compat)
RP_SKIP_THRESHOLD = 6        # rp >= 6 SKIP
RP_DAMP_THRESHOLD = 0        # 표시용 (v1.9g는 damping 대신 boost)
RP_DAMP_MULT = 1.0           # 표시용

# =========================================================
# ★★★ v1.9_REALISTIC: 실전 재현 설정 ★★★
# =========================================================
#
# 1) EXCLUDE_RECENT_H1_FOR_TIER
#    Tier 계산 시 최근 N개 H1 봉 제외.
#    이유: 실전 60초 루프에서 진행중인 H1 봉은 아직 닫히지 않아
#          엔진이 접근 가능한 "가장 최신 확정 H1" 은 1개 전 봉.
#          백테스트도 이 조건을 반영하여 낙관 편향 제거.
#
#    0 = 기존 방식 (H4 진입 시점까지 모든 H1 사용)
#    1 = 실전 지연 시뮬레이션 (권장, 최근 1 H1 제외)
#    2 = 더 보수적 (실전 4시간 지연 가정)
EXCLUDE_RECENT_H1_FOR_TIER = 1

# 2) USE_REFINE_ENTRY
#    refine_entry_with_h1_fvg 호출 여부.
#    False = refine 제거 (실전 엔진과 동일, 권장)
#    True  = 기존 v1.9_BASELINE 동일 (refine 체결)
USE_REFINE_ENTRY = False

# 3) USE_TIER_PRIORITY_SORT
#    Tier 우선 정렬 여부.
#    True  = tier_mult_final 내림차순 우선 (권장)
#    False = 기존 eff_score 우선 정렬
USE_TIER_PRIORITY_SORT = True

# =========================================================
# ★★★ v1.9g RISK MULTIPLIER (기본 vs 2배 비교) ★★★
# =========================================================
#
# RISK_MULTIPLIER = 1.0 → 기존 Phase A/B risk 그대로 (baseline)
# RISK_MULTIPLIER = 2.0 → Phase A/B risk 전부 2배 (aggressive)
#
# 셀 3에서 두 번 호출하여 나란히 비교 리포트 출력.
#
RISK_MULT_BASE = 1.0
RISK_MULT_2X = 2.0

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
# EXECUTION CONFIG
# =========================================================
EXECUTION_SPLIT_PROXY = "orderbook_split_proxy"

SLIPPAGE_LIMIT_PCT = {
    "BTCUSDT": 0.07, "ETHUSDT": 0.10, "SOLUSDT": 0.12,
    "XRPUSDT": 0.13, "DOGEUSDT": 0.15, "AVAXUSDT": 0.14, "LINKUSDT": 0.13,
    # v1.7 LTF 9coins 확장
    "BNBUSDT": 0.10,   # ETH 수준 (TOP5, 유동성 양호)
    "ADAUSDT": 0.13,   # XRP/LINK 수준 (중 유동성)
}

DIRECT_ENTRY_THRESHOLD_USDT = {
    "BTCUSDT":  2_000_000.0, "ETHUSDT":  1_500_000.0, "SOLUSDT":    280_000.0,
    "XRPUSDT":    200_000.0, "DOGEUSDT":   150_000.0, "AVAXUSDT":   175_000.0, "LINKUSDT":   175_000.0,
    # v1.7 LTF 9coins 확장
    "BNBUSDT":   800_000.0,  # ETH 와 SOL 중간 (유동성 중상)
    "ADAUSDT":   200_000.0,  # XRP 수준 (중 유동성)
}

SPLIT_MAX_TRANCHES = {
    "BTCUSDT": 4, "ETHUSDT": 4, "SOLUSDT": 4,
    "XRPUSDT": 4, "DOGEUSDT": 4, "AVAXUSDT": 4, "LINKUSDT": 4,
    # v1.7 LTF 9coins 확장
    "BNBUSDT": 4,
    "ADAUSDT": 4,
}

TRANCHE_SLIPPAGE_WEIGHTS = [0.35, 0.60, 0.85, 1.00]

SCENARIO_MULTI = {
    "name": "BTC+ETH+SOL+XRP+DOGE+AVAX+LINK+BNB+ADA v1.7 LTF 9coins (no refine + tier priority + exclude 1 H1)",
    "assets": {
        "BTCUSDT":  {"risk_pct": PHASE_A_RISK["BTCUSDT"],  "enabled": True},
        "ETHUSDT":  {"risk_pct": PHASE_A_RISK["ETHUSDT"],  "enabled": True},
        "SOLUSDT":  {"risk_pct": PHASE_A_RISK["SOLUSDT"],  "enabled": True},
        "XRPUSDT":  {"risk_pct": PHASE_A_RISK["XRPUSDT"],  "enabled": True},
        "DOGEUSDT": {"risk_pct": PHASE_A_RISK["DOGEUSDT"], "enabled": True},
        "AVAXUSDT": {"risk_pct": PHASE_A_RISK["AVAXUSDT"], "enabled": True},
        "LINKUSDT": {"risk_pct": PHASE_A_RISK["LINKUSDT"], "enabled": True},
        # v1.7 LTF 9coins 확장
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
                                  lookback_ltf_bars=8, exclude_recent_h1=0):
    """
    [v1.9_REALISTIC] exclude_recent_h1 파라미터 추가.
    실전 60초 루프에서 진행중 H1 봉은 접근 불가 시뮬레이션.
    exclude_recent_h1=1 이면 가장 최신 H1 1개를 제외하고 그 이전 8개 사용.
    """
    entry_h4_ts = df_h4.loc[h4_entry_idx, "timestamp"]
    ltf_mask = df_h1["timestamp"] <= entry_h4_ts
    if not ltf_mask.any():
        return 0, 0, 0, 0
    ltf_entry_idx = int(df_h1[ltf_mask].index[-1])

    # ⭐ v1.9_REALISTIC: 최근 H1 봉 제외
    ltf_entry_idx_adjusted = ltf_entry_idx - int(exclude_recent_h1)
    if ltf_entry_idx_adjusted < 0:
        return 0, 0, 0, 0

    start_idx = max(0, ltf_entry_idx_adjusted - lookback_ltf_bars)
    end_idx = ltf_entry_idx_adjusted
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


def compute_wick_ratio_5(df_h4, df_h1, h4_entry_idx, side, lookback_n=5, exclude_recent_h1=0):
    """
    [v1.9_REALISTIC] exclude_recent_h1 파라미터 추가.
    실전 60초 루프에서 진행중 H1 봉은 접근 불가 시뮬레이션.
    """
    entry_h4_ts = df_h4.loc[h4_entry_idx, "timestamp"]
    ltf_mask = df_h1["timestamp"] <= entry_h4_ts
    if not ltf_mask.any():
        return 0.0
    ltf_entry_idx = int(df_h1[ltf_mask].index[-1])

    # ⭐ v1.9_REALISTIC: 최근 H1 봉 제외
    ltf_entry_idx_adjusted = ltf_entry_idx - int(exclude_recent_h1)
    if ltf_entry_idx_adjusted < 0:
        return 0.0

    start_idx = max(0, ltf_entry_idx_adjusted - lookback_n)
    end_idx = ltf_entry_idx_adjusted
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


def classify_tier_v19b(pre_total, sweep_count, score, wick_ratio_5):
    """v1.9b: threshold 0.2300 (median 근처), 꼬리 작을수록 S. (v1.9d에서도 동일 재사용)"""
    in_d = (pre_total >= 4) or (2 <= sweep_count <= 4) or (score >= 13)
    in_wick = (wick_ratio_5 is not None) and (not pd.isna(wick_ratio_5)) and (wick_ratio_5 <= WICK_RATIO_5_Q1_THRESHOLD)
    if in_d and in_wick:
        return "S", TIER_RISK_S
    elif in_d and not in_wick:
        return "A", TIER_RISK_A
    elif not in_d and in_wick:
        return "B", TIER_RISK_B
    elif pre_total >= 1:
        return "C", TIER_RISK_C
    else:
        if SKIP_TIER_D:
            return "D", 0.0
        return "D", TIER_RISK_D


def apply_rp_filter(tier_mult, run_potential):
    """
    v1.9g RP BOOST (테이블 방식)
    반환: (action, final_tier_mult)
      action 예시:
        "rp_pass"          : 테이블 값이 정확히 1.0 (중립)
        "rp_boost_rp0_x1.5": 테이블 값이 1.0 초과 (boost)
        "rp_damp_rp2_x0.5" : 테이블 값이 1.0 미만 (damp, v1.9g에서는 미사용)
        "rp_skip_rp6"      : 테이블에 없음 또는 mult<=0
        "rp_disabled"      : 필터 비활성
    """
    if not RP_FILTER_ENABLE:
        return "rp_disabled", tier_mult
    if run_potential is None or (isinstance(run_potential, float) and pd.isna(run_potential)):
        return "rp_pass", tier_mult

    rp = int(run_potential)

    # 테이블에 없으면 skip
    if rp not in RP_TIER_MULT_TABLE:
        return f"rp_skip_rp{rp}", 0.0

    mult = RP_TIER_MULT_TABLE[rp]

    if mult <= 0:
        return f"rp_skip_rp{rp}", 0.0
    if mult > 1.0:
        return f"rp_boost_rp{rp}_x{mult}", tier_mult * mult
    if mult < 1.0:
        return f"rp_damp_rp{rp}_x{mult}", tier_mult * mult
    # mult == 1.0 → 중립
    return "rp_pass", tier_mult


# =========================================================
# v1.9_REALISTIC: S/A 티어 notional cap 결정
# =========================================================
def resolve_notional_cap(tier_label):
    """
    S 또는 A 티어면 MAX_NOTIONAL_MULT_SA_FREE (사실상 무제한) 사용.
    나머지 티어는 MAX_NOTIONAL_MULT (3.0) 사용.
    """
    if tier_label in ("S", "A"):
        return float(MAX_NOTIONAL_MULT_SA_FREE)
    return float(MAX_NOTIONAL_MULT)


print("v1.9_REALISTIC Part 1/3 loaded: config + indicators + tier + RP table filter")


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


# =========================================================
# v1.9_REALISTIC: Zone 일괄 평가 (tier 먼저 계산)
# =========================================================
def evaluate_zones_at_current_time(
    df_h4,
    df_h1,
    active_structures,
    i,
    exclude_recent_h1=0,
):
    """
    현재 H4 index 기준으로 active zone 들을 일괄 평가.
    Tier, RP, notional cap 등을 미리 계산하여 각 zone 에 부착.

    반환: list of dicts (원본 zone + 동적 평가 결과)

    평가된 zone 정렬 키 (상위 호출자에서 사용):
      1순위: tier_mult_final 내림차순 (품질 우선)
      2순위: eff_score 내림차순
      3순위: zone_created_idx 오름차순 (먼저 생긴 zone)
    """
    row = df_h4.iloc[i]
    evaluated = []

    for s in active_structures:
        # Freshness 재평가
        fresh_bonus, fresh_reasons = evaluate_freshness_at_entry(df_h4, s, i)
        eff_score = float(s["score"]) + fresh_bonus
        if eff_score < MIN_SCORE:
            continue

        # ⭐ Tier 입력값 계산 (exclude_recent_h1 적용)
        pre_sweep, pre_fvg, pre_ob, pre_total = compute_pre_entry_confluence(
            df_h4=df_h4,
            df_h1=df_h1,
            h4_entry_idx=i,
            zone_low=s["zone_low"],
            zone_high=s["zone_high"],
            lookback_ltf_bars=PRE_ENTRY_LOOKBACK_LTF_BARS,
            exclude_recent_h1=exclude_recent_h1,
        )
        wick_r5 = compute_wick_ratio_5(
            df_h4=df_h4,
            df_h1=df_h1,
            h4_entry_idx=i,
            side=s["type"],
            lookback_n=WICK_LOOKBACK_BARS,
            exclude_recent_h1=exclude_recent_h1,
        )

        # Tier 분류
        tier_label, tier_mult_raw = classify_tier_v19b(
            pre_total=int(pre_total),
            sweep_count=int(pre_sweep),
            score=float(eff_score),
            wick_ratio_5=float(wick_r5),
        )

        # Run Potential 계산
        rp, rp_tags = get_run_potential(df_h4, i, s)

        # RP Boost 필터
        rp_action, tier_mult_final = apply_rp_filter(tier_mult_raw, rp)

        # Notional cap 결정
        effective_cap = resolve_notional_cap(tier_label)

        evaluated.append({
            # 원본 zone 정보
            **s,
            # 동적 평가 결과
            "eff_score": eff_score,
            "fresh_reasons": fresh_reasons,
            "tier_pre_sweep": int(pre_sweep),
            "tier_pre_fvg": int(pre_fvg),
            "tier_pre_ob": int(pre_ob),
            "tier_pre_total": int(pre_total),
            "wick_ratio_5": float(wick_r5),
            "tier": tier_label,
            "tier_mult_raw": float(tier_mult_raw),
            "run_potential": int(rp),
            "run_tags": rp_tags,
            "rp_action": str(rp_action),
            "tier_mult_final": float(tier_mult_final),
            "effective_notional_cap": float(effective_cap),
            "tier_passable": tier_mult_final > 0.0,
        })

    return evaluated


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


def get_h1_window(df_h1_local, h4_timestamp, lookback_hours=12):
    start_ts = h4_timestamp - pd.Timedelta(hours=lookback_hours)
    end_ts = h4_timestamp
    return df_h1_local[(df_h1_local["timestamp"] > start_ts) & (df_h1_local["timestamp"] <= end_ts)].copy()


def refine_entry_with_h1_fvg(df_h1_local, h4_timestamp, side, zone_low, zone_high, base_entry,
                              lookback_hours=12, max_improve_frac=0.25):
    zone_size = zone_high - zone_low
    if zone_size <= 0:
        return base_entry, False, np.nan, ""

    max_improve = zone_size * max_improve_frac
    win = get_h1_window(df_h1_local, h4_timestamp, lookback_hours=lookback_hours)

    if len(win) == 0:
        return base_entry, False, np.nan, ""

    if side == "long":
        candidates = []
        for _, r in win.iterrows():
            if pd.notna(r["bull_fvg_low"]) and pd.notna(r["bull_fvg_high"]):
                mid = (float(r["bull_fvg_low"]) + float(r["bull_fvg_high"])) / 2.0
                if zone_low <= mid <= zone_high and mid < base_entry:
                    candidates.append({"mid": mid})
        if not candidates:
            return base_entry, False, np.nan, ""
        candidates = sorted(candidates, key=lambda x: abs(base_entry - x["mid"]))
        candidate = candidates[0]["mid"]
        candidate = max(candidate, base_entry - max_improve)
        candidate = max(candidate, zone_low)
        candidate = min(candidate, base_entry)
        improved = candidate < base_entry - 1e-12
        return candidate, improved, candidate, "h1_bull_fvg_mid"

    candidates = []
    for _, r in win.iterrows():
        if pd.notna(r["bear_fvg_low"]) and pd.notna(r["bear_fvg_high"]):
            mid = (float(r["bear_fvg_low"]) + float(r["bear_fvg_high"])) / 2.0
            if zone_low <= mid <= zone_high and mid > base_entry:
                candidates.append({"mid": mid})
    if not candidates:
        return base_entry, False, np.nan, ""
    candidates = sorted(candidates, key=lambda x: abs(base_entry - x["mid"]))
    candidate = candidates[0]["mid"]
    candidate = min(candidate, base_entry + max_improve)
    candidate = min(candidate, zone_high)
    candidate = max(candidate, base_entry)
    improved = candidate > base_entry + 1e-12
    return candidate, improved, candidate, "h1_bear_fvg_mid"


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
# TRADE SIMULATOR
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
# v1.7 LTF — H1 기반 순차 체결/청산 simulator
# =========================================================
def _simulate_trade_with_plan_core_ltf(
    df_h4, df_h1, h4_to_h1_ranges,
    entry_h4_idx, entry_h1_idx,
    side, entry, sl, qty, fee_rate, grade, plan,
    use_seq_runner_protection=False, disable_time_exit_when_runner=False,
):
    """v1.7 LTF 버전 trade simulator.
    기존 _core 와 동일 로직이지만 loop 를 H1 단위로 돌림.

    차이점:
      - entry 는 H4 봉에 기록되지만 실제 체결은 entry_h1_idx 의 H1 봉에서
      - loop 시작: entry_h1_idx + 1
      - TP/SL/BE 판정: H1 high/low 로
      - update_trailing_stop: H1 df 기준 (prev H1 봉 high/low/atr 사용)
      - max_hold_bars 는 H4 단위 → H1 단위로 변환 (× 4)
      - exit_idx 는 **H4 인덱스로 환산** 해서 반환 (기존 코드 호환성)
    """
    eps = 1e-12
    entry_time = df_h4.loc[entry_h4_idx, "timestamp"]
    risk_per_unit = abs(entry - sl)
    max_hold_bars_h4 = plan["max_hold_bars"]
    max_hold_bars_h1 = max_hold_bars_h4 * 4  # H4 봉당 H1 4 개

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
    exit_h1_idx = None
    exit_time = None

    entry_fee = abs(entry * qty) * fee_rate
    max_rr_seen = 0.0
    runner_max_rr_seen = np.nan

    # v1.7 LTF: bar stat 은 H1 단위로 측정 (hold_bars 는 H4 기준으로 scale 조정)
    # 하지만 "빠른 2R" 같은 조건은 H4 기준 FAST_2R_BARS_MAX 로 비교해야 backward compat.
    # → H1 hold 를 4로 나눠서 H4 equivalent 로 비교.
    bars_to_2r = np.nan         # H4 단위
    bars_spent_above_2r = 0      # H4 단위
    current_consecutive_above_2r = 0
    max_rr_after_2r = 0.0

    cond_count_final = 0
    runner_candidate_2of3 = False
    post_2of3_apply_ok = False
    runner_protected = False

    stop_type_last = "initial"

    # H4 단위 hold 계산: 현재 H1 인덱스가 어느 H4 봉에 속하는지 확인
    # 간단화: H4 hold = (현재_h1_idx - entry_h1_idx) // 4
    def h1_to_h4_hold(h1_idx):
        return (h1_idx - entry_h1_idx) // 4

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

    def register_rr_stats(h4_hold_bar, favorable_rr):
        """기존 _core 의 register_rr_stats 와 동일하되 H4 hold 기준으로 동작."""
        nonlocal bars_to_2r, bars_spent_above_2r, current_consecutive_above_2r, max_rr_after_2r
        nonlocal cond_count_final, runner_candidate_2of3, post_2of3_apply_ok, runner_protected
        nonlocal current_stop, stop_type_last

        if favorable_rr >= 2.0:
            bars_spent_above_2r += 1
            current_consecutive_above_2r += 1

            if pd.isna(bars_to_2r):
                bars_to_2r = h4_hold_bar

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
            if gate and post_2of3_apply_ok:
                locked = lock_profit_stop()
                if side == "long" and locked > current_stop:
                    current_stop = locked
                    stop_type_last = "runner_protect"
                    runner_protected = True
                elif side == "short" and locked < current_stop:
                    current_stop = locked
                    stop_type_last = "runner_protect"
                    runner_protected = True

    def hit_target(target):
        nonlocal realized_pnl, exit_fees, remaining_qty, be_moved, current_stop, stop_type_last, runner_active
        part_qty = qty * target["frac"]
        if part_qty > remaining_qty:
            part_qty = remaining_qty
        if part_qty <= eps:
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

    # H1 기반 loop
    n_h1 = len(df_h1)
    if disable_time_exit_when_runner:
        loop_end_h1 = n_h1
    else:
        loop_end_h1 = min(n_h1, entry_h1_idx + max_hold_bars_h1 + 1)

    for j in range(entry_h1_idx + 1, loop_end_h1):
        bar_open = df_h1.iloc[j]["open"]
        bar_high = df_h1.iloc[j]["high"]
        bar_low = df_h1.iloc[j]["low"]
        bar_close = df_h1.iloc[j]["close"]

        favorable_rr = calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low)
        # H4 단위 hold bar 로 stat 기록 (FAST_2R_BARS_MAX=3 등은 H4 기준이므로)
        h4_hold = h1_to_h4_hold(j)
        register_rr_stats(h4_hold, favorable_rr)
        update_max_rr(bar_high, bar_low)

        if remaining_qty <= eps:
            exit_reason = "all_targets"
            exit_h1_idx = j
            exit_time = df_h1.iloc[j]["timestamp"]
            break

        if runner_active and remaining_qty > eps:
            trailed = update_trailing_stop(df_h1, j, side, current_stop, entry)
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
                        exit_h1_idx = j
                        exit_time = df_h1.iloc[j]["timestamp"]
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
                        exit_h1_idx = j
                        exit_time = df_h1.iloc[j]["timestamp"]
                        break

        if exit_reason is not None:
            break

        # Time exit 체크 (H4 hold 기준)
        if (not disable_time_exit_when_runner) and (h4_hold >= max_hold_bars_h4):
            if remaining_qty > eps:
                if side == "long":
                    realized_pnl += (bar_close - entry) * remaining_qty
                else:
                    realized_pnl += (entry - bar_close) * remaining_qty
                exit_fees += abs(bar_close * remaining_qty) * fee_rate
                remaining_qty = 0.0
            exit_reason = "time_exit"
            exit_h1_idx = j
            exit_time = df_h1.iloc[j]["timestamp"]
            break

        if disable_time_exit_when_runner and (h4_hold >= max_hold_bars_h4) and (not runner_active) and (not runner_protected):
            if remaining_qty > eps:
                if side == "long":
                    realized_pnl += (bar_close - entry) * remaining_qty
                else:
                    realized_pnl += (entry - bar_close) * remaining_qty
                exit_fees += abs(bar_close * remaining_qty) * fee_rate
                remaining_qty = 0.0
            exit_reason = "time_exit_non_runner"
            exit_h1_idx = j
            exit_time = df_h1.iloc[j]["timestamp"]
            break

    if exit_reason is None:
        j = n_h1 - 1
        bar_close = df_h1.iloc[j]["close"]
        if remaining_qty > eps:
            if side == "long":
                realized_pnl += (bar_close - entry) * remaining_qty
            else:
                realized_pnl += (entry - bar_close) * remaining_qty
            exit_fees += abs(bar_close * remaining_qty) * fee_rate
            remaining_qty = 0.0
        exit_reason = "close_at_end"
        exit_h1_idx = j
        exit_time = df_h1.iloc[j]["timestamp"]

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

    # exit_h1_idx → exit_h4_idx 환산 (기존 코드 호환 — scenario 쪽이 entry_idx, exit_idx 를 H4 기준으로 쓰므로)
    # 가장 가까운 H4 봉: exit_h1 timestamp 를 포함하는 H4 봉
    exit_h4_idx = None
    if exit_h1_idx is not None:
        # h4_to_h1_ranges 를 역으로 탐색
        for h4_i in range(entry_h4_idx, len(h4_to_h1_ranges)):
            s, e = h4_to_h1_ranges[h4_i]
            if s is None:
                continue
            if s <= exit_h1_idx <= e:
                exit_h4_idx = h4_i
                break
        if exit_h4_idx is None:
            exit_h4_idx = len(df_h4) - 1

    # hold_bars 는 H4 단위
    hold_bars = (exit_h4_idx - entry_h4_idx) if exit_h4_idx is not None else 0

    return {
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_idx": exit_h4_idx,  # H4 기준 (기존 코드 호환)
        "exit_h1_idx": exit_h1_idx,  # v1.7 추가 정보
        "exit_reason": exit_reason,
        "result": result,
        "net_pnl": net_pnl,
        "risk_amount": risk_amount,
        "r_multiple": r_multiple,
        "be_moved": be_moved,
        "runner_active": runner_active,
        "hold_bars": hold_bars,
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


def simulate_trade_with_plan_ltf(df_h4, df_h1, h4_to_h1_ranges,
                                   entry_h4_idx, entry_h1_idx,
                                   side, entry, sl, qty, fee_rate, grade, plan,
                                   use_seq_runner_protection=False,
                                   disable_time_exit_when_runner=True):
    """v1.7 LTF 버전 wrapper (runner_no_time_exit default)."""
    return _simulate_trade_with_plan_core_ltf(
        df_h4=df_h4, df_h1=df_h1, h4_to_h1_ranges=h4_to_h1_ranges,
        entry_h4_idx=entry_h4_idx, entry_h1_idx=entry_h1_idx,
        side=side, entry=entry, sl=sl, qty=qty, fee_rate=fee_rate,
        grade=grade, plan=plan,
        use_seq_runner_protection=use_seq_runner_protection,
        disable_time_exit_when_runner=disable_time_exit_when_runner,
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


print("v1.9_REALISTIC Part 2/3 loaded: structures + trade simulator")


# =========================================================
# CANDIDATE GENERATION
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
        "h4_to_h1_ranges": build_h4_to_h1_ranges(df_struct, df_h1),
    }


# =========================================================
# v1.7 LTF — H4 ↔ H1 매핑 및 fill/exit helper
# =========================================================
def build_h4_to_h1_ranges(df_h4, df_h1):
    """각 H4 봉의 [start_h1_idx, end_h1_idx] 반환.
    start_idx: H4 봉 시작 시각과 같거나 그 직후의 첫 H1
    end_idx: 다음 H4 봉 시작 전의 마지막 H1 (inclusive)
    H4 봉이 4시간이므로 보통 4개 H1 포함.
    """
    h1_ts = df_h1["timestamp"].values
    h4_ts = df_h4["timestamp"].values

    # 각 H4 봉 시작 시각을 H1 timestamp 에서 찾기 (searchsorted)
    h4_ts_pd = pd.to_datetime(h4_ts)
    h1_ts_pd = pd.to_datetime(h1_ts)

    # start_idx: h4 시각 이상의 첫 h1 index
    start_indices = np.searchsorted(h1_ts_pd, h4_ts_pd, side="left")

    ranges = []
    n_h4 = len(df_h4)
    n_h1 = len(df_h1)
    for i in range(n_h4):
        s = int(start_indices[i])
        if s >= n_h1:
            ranges.append((None, None))
            continue
        if i + 1 < n_h4:
            e = int(start_indices[i + 1]) - 1
        else:
            e = n_h1 - 1
        if e < s:
            ranges.append((None, None))
        else:
            ranges.append((s, min(e, n_h1 - 1)))
    return ranges


def find_h1_touch_in_range(df_h1, h1_start, h1_end, zone_low, zone_high):
    """H1 인덱스 범위 [h1_start, h1_end] 내에서 zone 에 처음 touch 한 H1 인덱스 반환.
    None 이면 이 범위에서 touch 없음.
    """
    if h1_start is None or h1_end is None:
        return None
    if h1_start > h1_end:
        return None
    # DataFrame 슬라이스보다 numpy 가 빠름
    highs = df_h1["high"].values[h1_start:h1_end + 1]
    lows = df_h1["low"].values[h1_start:h1_end + 1]
    for offset in range(len(highs)):
        if highs[offset] >= zone_low and lows[offset] <= zone_high:
            return h1_start + offset
    return None


def compute_h1_fill_price(h1_row, zone_low, zone_high):
    """v1.7 Entry fill 가격 계산 (Q3 Option B: H1 기반 clamp).
    = clamp(zone_low, h1_open, zone_high)
    H1 open 이 zone 안에 있으면 open, 밖이면 zone 경계.
    """
    h1_open = float(h1_row["open"])
    return max(zone_low, min(h1_open, zone_high))


def h4_range_covers_h1(h4_to_h1_ranges, h4_idx, h1_idx):
    """H1 인덱스가 해당 H4 봉의 range 에 속하는지 체크 (디버깅용)."""
    if h4_idx >= len(h4_to_h1_ranges):
        return False
    s, e = h4_to_h1_ranges[h4_idx]
    if s is None:
        return False
    return s <= h1_idx <= e


def generate_candidates_from_prepared(prepared):
    symbol = prepared["symbol"]
    df_struct = prepared["df_struct"]
    df_h1 = prepared["df_h1"]
    df_d1 = prepared["df_d1"]
    structures = prepared["structures"]
    structures_by_zone_created = prepared["structures_by_zone_created"]
    # v1.7 LTF: H4→H1 인덱스 매핑 (apply_indicators_and_build 에서 생성됨)
    h4_to_h1_ranges = prepared["h4_to_h1_ranges"]

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

    # v1.9_REALISTIC MULTIPOS:
    # 심볼당 최대 2 포지션. 2번째 진입은 tier S 또는 A 만. 반대 방향 금지.
    # 시뮬레이션은 포지션별 독립. (exit_idx 를 position-level 로 기록)
    # ★ MAX_POSITIONS_PER_SYMBOL 은 전역 설정에서 가져옴 (셀2 에서 조정)
    open_positions_multipos = []  # list of dicts: {entry_idx, exit_idx, side, tier}
    _max_pos = globals().get("MAX_POSITIONS_PER_SYMBOL", 2)
    MAX_POSITIONS_PER_SYMBOL_LOCAL = _max_pos  # alias for backward compat
    ADDITIONAL_ENTRY_ALLOWED_TIERS = {"S", "A"}

    RELAX_MIN_SCORE = MIN_SCORE - FRESHNESS_MAX_BONUS

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
            and (s["score"] >= RELAX_MIN_SCORE)
            and (s["zone_created_idx"] not in used_zone_ids)
        ]

        trade_day = str(row["timestamp"].date())
        if daily_trade_count.get(trade_day, 0) >= DAY_TRADE_LIMIT:
            i += 1
            continue

        entry_found = False
        entries_this_bar = []  # v1.9_MULTIPOS: 이 봉에서 잡은 진입들 (최대 2개)
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

        # ⭐ v1.9_REALISTIC: 모든 active zone 을 먼저 평가 (tier 계산 포함)
        evaluated_zones = evaluate_zones_at_current_time(
            df_h4=df_struct,
            df_h1=df_h1,
            active_structures=active_structures,
            i=i,
            exclude_recent_h1=EXCLUDE_RECENT_H1_FOR_TIER,
        )

        # ⭐ v1.9_REALISTIC: 정렬 키 선택 (tier 우선 or score 우선)
        if USE_TIER_PRIORITY_SORT:
            # Tier 우선: tier_mult_final 내림차순 > eff_score 내림차순 > zone_created_idx 오름차순
            evaluated_zones.sort(key=lambda z: (
                -float(z["tier_mult_final"]),
                -float(z["eff_score"]),
                int(z["zone_created_idx"]),
            ))
        else:
            # 기존 방식: eff_score 내림차순 > zone_created_idx 오름차순
            evaluated_zones.sort(key=lambda z: (
                -float(z["eff_score"]),
                int(z["zone_created_idx"]),
            ))

        for z in evaluated_zones:
            # tier 가 D (skip) 또는 RP skip 이면 즉시 스킵
            if not z["tier_passable"]:
                _track_skip(f"tier_{z['tier']}_skip_rp_action_{z['rp_action']}")
                continue

            # ⭐ v1.9_MULTIPOS: 동시 포지션 조건 체크
            # 이 봉에서 이미 잡은 진입 수 + 기존 open 포지션 수 계산
            already_this_bar = len(entries_this_bar)
            # 기존 open 포지션 (이전 봉에서 진입, 아직 exit 안 됨)
            open_count = sum(1 for p in open_positions_multipos
                              if p["entry_idx"] < i <= p["exit_idx"])
            total_count = already_this_bar + open_count
            if total_count >= MAX_POSITIONS_PER_SYMBOL_LOCAL:
                # 한도 도달 → 이 봉 진입 더 이상 시도 안 함
                _track_skip("multipos_limit_reached")
                break

            # 2번째 진입 조건: tier S 또는 A, 같은 방향
            if total_count >= 1:
                if z["tier"] not in ADDITIONAL_ENTRY_ALLOWED_TIERS:
                    _track_skip(f"multipos_2nd_tier_{z['tier']}_not_sa")
                    continue
                # 같은 방향 체크
                if already_this_bar > 0:
                    first_side = entries_this_bar[0]["_entry_side"]
                elif open_count > 0:
                    open_first = next(p for p in open_positions_multipos
                                       if p["entry_idx"] < i <= p["exit_idx"])
                    first_side = open_first["side"]
                else:
                    first_side = None
                if first_side is not None and z["type"] != first_side:
                    _track_skip(f"multipos_2nd_opposite_side_{z['type']}_vs_{first_side}")
                    continue

            # 기존 s 참조를 z 참조로 대체 (backward compat 위해 s 별칭 사용)
            s = z
            eff_score = z["eff_score"]
            fresh_reasons = z["fresh_reasons"]

            # v1.7 LTF: H4 봉 내 H1 봉 단위로 touch 판정
            h1_start, h1_end = h4_to_h1_ranges[i] if i < len(h4_to_h1_ranges) else (None, None)
            h1_touch_idx = find_h1_touch_in_range(df_h1, h1_start, h1_end, s["zone_low"], s["zone_high"])
            touched = (h1_touch_idx is not None)
            if not touched:
                continue

            # =============================================================
            # v1.7+ 필터 그룹 시스템 (개별 continue 대신 결과 수집)
            # USE_FILTER_GROUPS = True 면 FILTER_GROUPS 로 OR 그룹 평가
            # False 면 기존 AND 방식 (backward compat)
            # =============================================================
            vol_ok, vol_reason = passes_volume_filter(df_struct, s["zone_created_idx"])

            # v1.7 LTF: Entry fill 가격 = touch 한 H1 봉의 open 을 zone 으로 clamp
            h1_fill_row = df_h1.iloc[h1_touch_idx]
            fill_entry_price = compute_h1_fill_price(h1_fill_row, s["zone_low"], s["zone_high"])
            atr_val = df_struct.loc[i, "atr"] if pd.notna(df_struct.loc[i, "atr"]) else 0.0

            # ⭐ v1.9_REALISTIC: evaluate_zones_at_current_time 에서 미리 계산한 값 재사용
            rp = int(z["run_potential"])
            rp_tags = z["run_tags"]
            g = classify_grade(float(eff_score), rp)

            reasons_full = s["reasons"]
            if fresh_reasons:
                reasons_full = reasons_full + "," + ",".join(fresh_reasons) if reasons_full else ",".join(fresh_reasons)

            atr_ok, atr_reason = passes_atr_filter(df_struct, i)

            # zone 방향별 side 결정 (아래 pullback / d1 / sweep 용)
            _side_dir = s["type"]  # "short" or "long"

            # side 별 early reject (cooldown, H4 trend) — 기존 유지
            if _side_dir == "short":
                if i - last_short_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "up":
                    continue
            elif _side_dir == "long":
                if i - last_long_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "down":
                    continue

            # === 5개 필터 결과 모두 독립 계산 (continue 하지 않음) ===
            d1_ok, d1_reason = passes_d1_filter(df_d1, df_struct.loc[i, "timestamp"], _side_dir)
            sweep_ok, sweep_reason = passes_sweep_confirmation(df_struct, i, _side_dir)
            pullback_ok, pullback_reason = passes_pullback_depth(
                row["open"], s["zone_low"], s["zone_high"], _side_dir
            )

            # 필터 결과 dict (이후 candidate 에 기록)
            _filter_passes = {
                "VOLUME": bool(vol_ok),
                "LIQUIDITY_SWEEP": bool(sweep_ok),
                "D1_TREND": bool(d1_ok),
                "PULLBACK_DEPTH": bool(pullback_ok),
                "ATR": bool(atr_ok),
            }
            _filter_reasons = {
                "VOLUME": vol_reason,
                "LIQUIDITY_SWEEP": sweep_reason,
                "D1_TREND": d1_reason,
                "PULLBACK_DEPTH": pullback_reason,
                "ATR": atr_reason,
            }

            # === 필터 그룹 평가 ===
            _use_groups = globals().get("USE_FILTER_GROUPS", False)
            _filter_groups_cfg = globals().get("FILTER_GROUPS", [])

            if _use_groups and _filter_groups_cfg:
                # 각 그룹 내부 OR
                _group_results = []
                for _gi, _group in enumerate(_filter_groups_cfg):
                    _group_pass = any(_filter_passes.get(f, False) for f in _group)
                    _group_results.append(_group_pass)

                # 그룹 간 OR (하나라도 통과하면 OK)
                _overall_pass = any(_group_results)
                if not _overall_pass:
                    # 모든 그룹 전체 실패
                    _fail_detail = "_".join([f"G{i+1}" for i, p in enumerate(_group_results) if not p])
                    _track_skip(f"all_groups_failed_{_fail_detail}")
                    continue

                # 통과한 그룹 인덱스 기록
                _passing_groups = [i+1 for i, p in enumerate(_group_results) if p]
            else:
                # === 기존 AND 방식 (backward compat) ===
                if (not USE_LIQUIDITY_SWEEP_CONF) or (SWEEP_VOLUME_MODE == "AND"):
                    if not vol_ok:
                        _track_skip(vol_reason)
                        continue
                if not atr_ok:
                    _track_skip(atr_reason)
                    continue
                if not d1_ok:
                    _track_skip(d1_reason)
                    continue
                # sweep / vol OR 모드 처리
                if USE_VOLUME_FILTER and SWEEP_VOLUME_MODE == "OR":
                    if not (sweep_ok or vol_ok):
                        _track_skip(f"or_fail({sweep_reason}|{vol_reason})")
                        continue
                else:
                    if not sweep_ok:
                        _track_skip(sweep_reason)
                        continue
                if not pullback_ok:
                    _track_skip(pullback_reason)
                    continue
                _passing_groups = []  # 그룹 모드 아니면 빈 리스트

            if s["type"] == "short":

                # ⭐ v1.9_REALISTIC: tier 입력값은 evaluated 에서 재사용 (중복 계산 제거)
                pre_sweep_v = z["tier_pre_sweep"]
                pre_fvg_v = z["tier_pre_fvg"]
                pre_ob_v = z["tier_pre_ob"]
                pre_total_v = z["tier_pre_total"]
                wick_ratio_v = z["wick_ratio_5"]

                h1_confirm_short = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="short", lookback_hours=H1_CHOCH_CONFIRM_HOURS
                )

                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * SHORT_BASE_ENTRY_FRAC

                # ⭐ v1.9_REALISTIC: refine 제거 (fill_entry_price 는 위에서 이미 base 로 결정됨)
                # refine_entry_with_h1_fvg 호출 및 refined 체결 로직 제거
                refined_entry_candidate = base_entry_candidate  # 호환성 위해 base 로 세팅
                improved = False
                refine_px = np.nan
                refine_reason = ""

                # v1.7 LTF: 실제 H1 touch 시점 사용
                fill_time_h1 = df_h1.iloc[h1_touch_idx]["timestamp"]
                h4_start_h1 = h4_to_h1_ranges[i][0] if h4_to_h1_ranges[i][0] is not None else h1_touch_idx
                fill_bars_waited = h1_touch_idx - h4_start_h1
                _h1_fill_idx_short = h1_touch_idx  # 이후 exit 로직에 전달

                raw_sl = s["sweep_ref"] + atr_val * SL_BUFFER_MULT
                sl_candidate = clamp_stop_for_short(fill_entry_price, raw_sl, atr_val)
                if sl_candidate <= fill_entry_price:
                    continue

                expansion_candidate = get_expansion_state(h4_market_state, h1_confirm_short)
                plan = get_tp_plan(expansion_candidate)

                # v1.9_MULTIPOS: entry_found 대신 dict 로 저장하고 continue
                entries_this_bar.append({
                    "_entry_side": "short",
                    "_used_structure": s,
                    "_eff_score": eff_score,
                    "_reasons_full": reasons_full,
                    "_entry": fill_entry_price,
                    "_sl": sl_candidate,
                    "_grade": g,
                    "_rp": rp,
                    "_rp_tags": rp_tags,
                    "_tp_plan": plan,
                    "_expansion_state": expansion_candidate,
                    "_base_entry": base_entry_candidate,
                    "_refined_entry": np.nan,
                    "_entry_refined": False,
                    "_refine_tag": "",
                    "_fill_entry_price": fill_entry_price,
                    "_h4_market_state": h4_market_state,
                    "_pre_sweep_v": pre_sweep_v,
                    "_pre_fvg_v": pre_fvg_v,
                    "_pre_ob_v": pre_ob_v,
                    "_pre_total_v": pre_total_v,
                    "_wick_ratio_v": wick_ratio_v,
                    "_tier_label": z["tier"],
                    "_tier_mult_raw": z["tier_mult_raw"],
                    "_rp_action": z["rp_action"],
                    "_tier_mult_final": z["tier_mult_final"],
                    "_effective_cap": z["effective_notional_cap"],
                    "_v17_signal_price": float(df_struct.loc[i, "close"]),
                    "_v17_expected_entry": float(base_entry_candidate),
                    "_v17_submitted_entry": float(base_entry_candidate),
                    "_v17_filled_entry": float(fill_entry_price),
                    "_v17_fill_time_h1": fill_time_h1,
                    "_v17_fill_bars_waited": fill_bars_waited,
                    "_h1_fill_idx": _h1_fill_idx_short,  # v1.7 LTF: exit 시뮬에 필요
                    # === 필터 그룹 분석용 필드 ===
                    "_pass_vol": _filter_passes["VOLUME"],
                    "_pass_sweep": _filter_passes["LIQUIDITY_SWEEP"],
                    "_pass_d1": _filter_passes["D1_TREND"],
                    "_pass_pull": _filter_passes["PULLBACK_DEPTH"],
                    "_pass_atr": _filter_passes["ATR"],
                    "_pass_groups": ",".join([f"G{g}" for g in _passing_groups]) if _passing_groups else "NONE",
                })
                continue  # 다음 zone 으로 (multipos: 2번째 후보 탐색)

            if s["type"] == "long":
                # cooldown / trend 는 이미 위에서 체크됨
                # d1 / sweep / pullback 필터도 이미 위에서 체크됨 (그룹 또는 AND)
                pass

                # ⭐ v1.9_REALISTIC: tier 입력값은 evaluated 에서 재사용 (중복 계산 제거)
                pre_sweep_v = z["tier_pre_sweep"]
                pre_fvg_v = z["tier_pre_fvg"]
                pre_ob_v = z["tier_pre_ob"]
                pre_total_v = z["tier_pre_total"]
                wick_ratio_v = z["wick_ratio_5"]

                h1_confirm_long = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="long", lookback_hours=H1_CHOCH_CONFIRM_HOURS
                )

                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * LONG_BASE_ENTRY_FRAC

                # ⭐ v1.9_REALISTIC: refine 제거 (fill_entry_price 는 위에서 이미 base 로 결정됨)
                refined_entry_candidate = base_entry_candidate  # 호환성 위해 base 로 세팅
                improved = False
                refine_px = np.nan
                refine_reason = ""

                # v1.7 LTF: 실제 H1 touch 시점 사용
                fill_time_h1 = df_h1.iloc[h1_touch_idx]["timestamp"]
                h4_start_h1 = h4_to_h1_ranges[i][0] if h4_to_h1_ranges[i][0] is not None else h1_touch_idx
                fill_bars_waited = h1_touch_idx - h4_start_h1
                _h1_fill_idx_long = h1_touch_idx  # 이후 exit 로직에 전달

                raw_sl = s["sweep_ref"] - atr_val * SL_BUFFER_MULT
                sl_candidate = clamp_stop_for_long(fill_entry_price, raw_sl, atr_val)
                if sl_candidate >= fill_entry_price:
                    continue

                expansion_candidate = get_expansion_state(h4_market_state, h1_confirm_long)
                plan = get_tp_plan(expansion_candidate)

                # v1.9_MULTIPOS: entry_found 대신 dict 로 저장하고 continue
                entries_this_bar.append({
                    "_entry_side": "long",
                    "_used_structure": s,
                    "_eff_score": eff_score,
                    "_reasons_full": reasons_full,
                    "_entry": fill_entry_price,
                    "_sl": sl_candidate,
                    "_grade": g,
                    "_rp": rp,
                    "_rp_tags": rp_tags,
                    "_tp_plan": plan,
                    "_expansion_state": expansion_candidate,
                    "_base_entry": base_entry_candidate,
                    "_refined_entry": np.nan,
                    "_entry_refined": False,
                    "_refine_tag": "",
                    "_fill_entry_price": fill_entry_price,
                    "_h4_market_state": h4_market_state,
                    "_pre_sweep_v": pre_sweep_v,
                    "_pre_fvg_v": pre_fvg_v,
                    "_pre_ob_v": pre_ob_v,
                    "_pre_total_v": pre_total_v,
                    "_wick_ratio_v": wick_ratio_v,
                    "_tier_label": z["tier"],
                    "_tier_mult_raw": z["tier_mult_raw"],
                    "_rp_action": z["rp_action"],
                    "_tier_mult_final": z["tier_mult_final"],
                    "_effective_cap": z["effective_notional_cap"],
                    "_v17_signal_price": float(df_struct.loc[i, "close"]),
                    "_v17_expected_entry": float(base_entry_candidate),
                    "_v17_submitted_entry": float(base_entry_candidate),
                    "_v17_filled_entry": float(fill_entry_price),
                    "_v17_fill_time_h1": fill_time_h1,
                    "_v17_fill_bars_waited": fill_bars_waited,
                    "_h1_fill_idx": _h1_fill_idx_long,  # v1.7 LTF: exit 시뮬에 필요
                    # === 필터 그룹 분석용 필드 ===
                    "_pass_vol": _filter_passes["VOLUME"],
                    "_pass_sweep": _filter_passes["LIQUIDITY_SWEEP"],
                    "_pass_d1": _filter_passes["D1_TREND"],
                    "_pass_pull": _filter_passes["PULLBACK_DEPTH"],
                    "_pass_atr": _filter_passes["ATR"],
                    "_pass_groups": ",".join([f"G{g}" for g in _passing_groups]) if _passing_groups else "NONE",
                })
                continue  # 다음 zone 으로 (multipos: 2번째 후보 탐색)

        # v1.9_MULTIPOS: 이 봉에서 잡힌 진입이 하나라도 있나?
        if not entries_this_bar:
            i += 1
            continue

        # 각 진입 independent simulation (최대 2개)
        # position_num: 1 = 첫 진입, 2 = 추가 진입
        for pos_idx, ed in enumerate(entries_this_bar):
            position_num = pos_idx + 1  # 1 or 2

            # v1.7 LTF: H1 기반 exit 시뮬
            sim = simulate_trade_with_plan_ltf(
                df_h4=df_struct, df_h1=df_h1, h4_to_h1_ranges=h4_to_h1_ranges,
                entry_h4_idx=i, entry_h1_idx=ed["_h1_fill_idx"],
                side=ed["_entry_side"], entry=ed["_fill_entry_price"], sl=ed["_sl"],
                qty=1.0, fee_rate=FEE_RATE,
                grade=ed["_grade"], plan=ed["_tp_plan"],
                use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE,
                disable_time_exit_when_runner=True,  # v4.6R Runner time exit remove (baseline)
            )

            ed["_used_structure"]["used"] = True
            used_zone_ids.add(ed["_used_structure"]["zone_created_idx"])
            daily_trade_count[trade_day] = daily_trade_count.get(trade_day, 0) + 1

            # open_positions_multipos 업데이트 (다음 봉에서 total_count 체크용)
            open_positions_multipos.append({
                "entry_idx": i,
                "exit_idx": sim["exit_idx"],
                "side": ed["_entry_side"],
                "tier": ed["_tier_label"],
                "position_num": position_num,
            })

            # last_*_exit_idx 는 가장 늦은 exit 기준으로 갱신 (cooldown 용)
            if ed["_entry_side"] == "long":
                last_long_exit_idx = max(last_long_exit_idx, sim["exit_idx"])
            else:
                last_short_exit_idx = max(last_short_exit_idx, sim["exit_idx"])

            candidates.append({
                "symbol": symbol,
                "entry_time": row["timestamp"],
                "exit_time": sim["exit_time"],
                "side": ed["_entry_side"],
                "entry": ed["_entry"],
                "fill_entry": ed["_fill_entry_price"],
                "fill_vs_refined_pct": 0.0,  # refine 제거 → 0
                "entry_idx": i,
                "signal_price":    ed["_v17_signal_price"],
                "expected_entry":  ed["_v17_expected_entry"],
                "submitted_entry": ed["_v17_submitted_entry"],
                "filled_entry":    ed["_v17_filled_entry"],
                "fill_status":     "filled",
                "fill_time_h1":    ed["_v17_fill_time_h1"],
                "fill_bars_waited": ed["_v17_fill_bars_waited"],
                "h1_fill_idx":     int(ed["_h1_fill_idx"]),  # v1.7 LTF: exit 시뮬에 필요
                # === 필터 그룹 분석용 ===
                "pass_vol":    bool(ed.get("_pass_vol", False)),
                "pass_sweep":  bool(ed.get("_pass_sweep", False)),
                "pass_d1":     bool(ed.get("_pass_d1", False)),
                "pass_pull":   bool(ed.get("_pass_pull", False)),
                "pass_atr":    bool(ed.get("_pass_atr", False)),
                "pass_groups": ed.get("_pass_groups", "NONE"),
                "pass_combo":  "+".join([
                    n for n, k in [
                        ("VOL", "_pass_vol"), ("SWEEP", "_pass_sweep"),
                        ("D1", "_pass_d1"), ("PULL", "_pass_pull"), ("ATR", "_pass_atr")
                    ] if ed.get(k, False)
                ]) or "NONE",
                "pass_count":  sum(1 for k in ["_pass_vol", "_pass_sweep", "_pass_d1", "_pass_pull", "_pass_atr"] if ed.get(k, False)),
                "base_entry": ed["_base_entry"],
                "entry_improved_by": (ed["_base_entry"] - ed["_entry"]) if ed["_entry_side"] == "long" else (ed["_entry"] - ed["_base_entry"]),
                "entry_refined": ed["_entry_refined"],
                "refined_entry_px": ed["_refined_entry"],
                "refine_tag": ed["_refine_tag"],
                "sl": ed["_sl"],
                "risk_per_unit": abs(ed["_entry"] - ed["_sl"]),
                "r_multiple": sim["r_multiple"],
                "result": sim["result"],
                "exit_reason": sim["exit_reason"],
                "hold_bars": sim["hold_bars"],
                "score": ed["_eff_score"],
                "base_score": ed["_used_structure"]["score"],
                "grade": ed["_grade"],
                "run_potential": ed["_rp"],
                "run_tags": ed["_rp_tags"],
                "pre_entry_sweep": ed["_pre_sweep_v"],
                "pre_entry_fvg": ed["_pre_fvg_v"],
                "pre_entry_ob": ed["_pre_ob_v"],
                "pre_entry_total": ed["_pre_total_v"],
                "wick_ratio_5": ed["_wick_ratio_v"],
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
                "tp_plan_name": ed["_tp_plan"]["name"],
                "expansion_state": ed["_expansion_state"],
                "reasons": ed["_reasons_full"],
                "zone_created_idx": ed["_used_structure"]["zone_created_idx"],
                "market_state": ed["_h4_market_state"],
                # v1.9_MULTIPOS: position_num 추가
                "position_num": position_num,
                "tier_label": ed["_tier_label"],
                "tier_mult_final": ed["_tier_mult_final"],
            })

        # v1.9_MULTIPOS: i 는 단순히 +1 (각 봉마다 multipos 탐색)
        i += 1

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
        "h4_to_h1_ranges": h4_to_h1_ranges,  # v1.7 LTF: exit 시뮬용
        "candidates": candidates_df,
        "no_fill": no_fill_df,
        "skip_reasons": skip_reasons,  # 필터 효과 분석용
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


def execute_and_resimulate_trade(row, qty, df_h4, df_h1=None, h4_to_h1_ranges=None, h1_fill_idx=None):
    exec_info = apply_execution_model_to_trade(row, qty)

    avg_entry = float(exec_info["avg_entry"])
    fill_qty = float(exec_info["fill_qty"])
    entry_idx = int(row["entry_idx"])
    sl = float(row["sl"])

    # v1.7 LTF: df_h1 / h4_to_h1_ranges / h1_fill_idx 가 모두 제공되면 LTF simulator 사용
    if df_h1 is not None and h4_to_h1_ranges is not None and h1_fill_idx is not None:
        sim = simulate_trade_with_plan_ltf(
            df_h4=df_h4, df_h1=df_h1, h4_to_h1_ranges=h4_to_h1_ranges,
            entry_h4_idx=entry_idx, entry_h1_idx=int(h1_fill_idx),
            side=row["side"], entry=avg_entry, sl=sl, qty=fill_qty, fee_rate=FEE_RATE,
            grade=row["grade"], plan=get_tp_plan(row["expansion_state"]),
            use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE,
            disable_time_exit_when_runner=True,
        )
    else:
        # fallback: 기존 H4 simulator
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


# =========================================================
# ★★★ SIMULATION (v1.9g: tier + RP Boost + risk mult + S/A cap toggle) ★★★
# =========================================================
def simulate_scenario_v19g(scenario, candidates_dict, risk_multiplier=1.0, sa_cap_free=False):
    """
    v1.9g = v1.9b tier + RP Boost + risk multiplier + S/A notional cap toggle
      1) classify_tier_v19b() 로 tier 분류
      2) apply_rp_filter() 로 RP Boost 테이블 lookup
         - rp=0/1 → tier_mult × 1.5 (boost)
         - rp=2~5 → tier_mult × 1.0 (그대로)
         - rp>=6  → skip
      3) risk_pct_base × risk_multiplier
      4) S/A 티어 notional cap:
         - sa_cap_free=False → MAX_NOTIONAL_MULT (3.0)
         - sa_cap_free=True  → MAX_NOTIONAL_MULT_SA_FREE (999.0)  ★ v1.9g 신규
    """
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

                # v1.9_MULTIPOS: 심볼당 최대 N 포지션 (N = MAX_POSITIONS_PER_SYMBOL)
                # 기존 "symbol_already_open" 차단 로직 대체
                _max_pos_sim = globals().get("MAX_POSITIONS_PER_SYMBOL", 2)
                symbol_positions = [p for p in open_positions.values() if p["symbol"] == symbol]
                symbol_count = len(symbol_positions)

                if symbol_count >= _max_pos_sim:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": f"position_limit_{_max_pos_sim}_reached",
                        "phase_at_entry": last_phase,
                    })
                    continue

                current_phase_for_entry = get_current_phase(balance)
                risk_pct_base = get_phase_risk_pct(current_phase_for_entry, symbol) * risk_multiplier

                # ========== 1. tier 분류 (v1.9b 로직 재사용) ==========
                pre_total_v = int(row.get("pre_entry_total", 0)) if pd.notna(row.get("pre_entry_total", 0)) else 0
                sweep_v = int(row.get("pre_entry_sweep", 0)) if pd.notna(row.get("pre_entry_sweep", 0)) else 0
                score_v = float(row.get("score", 0))
                wick_v = row.get("wick_ratio_5", None)
                if pd.isna(wick_v): wick_v = None

                tier_label, tier_mult_raw = classify_tier_v19b(pre_total_v, sweep_v, score_v, wick_v)

                # v1.9_MULTIPOS: 2번째 진입 조건 체크 (tier 분류 후)
                if symbol_count >= 1:
                    # tier S/A 만
                    if tier_label not in ("S", "A"):
                        skipped_entries.append({
                            "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                            "symbol": symbol, "reason": f"multipos_2nd_tier_{tier_label}_not_sa",
                            "phase_at_entry": current_phase_for_entry,
                            "tier": tier_label,
                        })
                        continue
                    # 같은 방향만
                    first_side = symbol_positions[0]["side"]
                    if row["side"] != first_side:
                        skipped_entries.append({
                            "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                            "symbol": symbol, "reason": f"multipos_opposite_side_{row['side']}_vs_{first_side}",
                            "phase_at_entry": current_phase_for_entry,
                            "tier": tier_label,
                        })
                        continue

                # 1-1. tier D skip (기존 로직)
                if tier_mult_raw <= 0.0:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": f"tier_skip_{tier_label}",
                        "phase_at_entry": current_phase_for_entry,
                        "tier": tier_label, "tier_mult_raw": tier_mult_raw,
                        "run_potential": row.get("run_potential", None),
                        "rp_action": "n/a_tier_skip",
                    })
                    continue

                # ========== 2. run_potential 필터 (v1.9d 신규) ==========
                rp_v = row.get("run_potential", None)
                if pd.notna(rp_v):
                    rp_v_int = int(rp_v)
                else:
                    rp_v_int = None

                rp_action, tier_mult = apply_rp_filter(tier_mult_raw, rp_v_int)

                # 2-1. rp_skip
                if rp_action == "rp_skip":
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": f"rp_skip_rp{rp_v_int}",
                        "phase_at_entry": current_phase_for_entry,
                        "tier": tier_label, "tier_mult_raw": tier_mult_raw,
                        "run_potential": rp_v_int,
                        "rp_action": rp_action,
                    })
                    continue

                # 2-2. 안전장치: tier_mult이 0 이하로 떨어진 경우
                if tier_mult <= 0.0:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": f"mult_zero_after_rp({rp_action})",
                        "phase_at_entry": current_phase_for_entry,
                        "tier": tier_label, "tier_mult_raw": tier_mult_raw,
                        "run_potential": rp_v_int,
                        "rp_action": rp_action,
                    })
                    continue

                # ========== 3. 포지션 사이징 ==========
                risk_pct = risk_pct_base * tier_mult

                # ★ v1.9g 확장: S/A 티어에서 sa_cap_free=True 면 notional cap 해제 ★
                if sa_cap_free and tier_label in ("S", "A"):
                    effective_notional_cap = MAX_NOTIONAL_MULT_SA_FREE
                else:
                    effective_notional_cap = MAX_NOTIONAL_MULT

                qty, risk_per_unit, notional = calc_position_size(
                    balance=balance, risk_pct=risk_pct, entry=row["entry"], sl=row["sl"],
                    fee_rate=FEE_RATE, max_notional_mult=effective_notional_cap
                )

                if qty is None:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": "size_invalid",
                        "phase_at_entry": current_phase_for_entry,
                        "tier": tier_label, "tier_mult_raw": tier_mult_raw,
                        "run_potential": rp_v_int,
                        "rp_action": rp_action,
                    })
                    continue

                exec_adj = execute_and_resimulate_trade(
                    row=row, qty=qty, df_h4=candidates_dict[symbol]["df_h4"],
                    df_h1=candidates_dict[symbol]["df_h1"],
                    h4_to_h1_ranges=candidates_dict[symbol]["h4_to_h1_ranges"],
                    h1_fill_idx=row.get("h1_fill_idx"),
                )

                sim_exec = exec_adj["sim_result"]

                sa_tag = "saFree" if (sa_cap_free and tier_label in ("S", "A")) else "capNorm"
                open_positions[idx] = {
                    "scenario_name": scenario["name"],
                    "execution_model": EXECUTION_SPLIT_PROXY,
                    "strategy_variant": f"v19g_phase_ab_rp_boost_r{risk_multiplier:.1f}x_{'saFree' if sa_cap_free else 'capAll3'}",
                    "risk_multiplier": risk_multiplier,
                    "sa_cap_free": sa_cap_free,
                    "effective_notional_cap": effective_notional_cap,
                    "sa_cap_tag": sa_tag,
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
                    "run_potential": rp_v_int if rp_v_int is not None else np.nan,
                    "rp_action": rp_action,
                    "tier": tier_label,
                    "tier_mult": tier_mult,
                    "tier_mult_raw": tier_mult_raw,
                    "pre_entry_total": pre_total_v,
                    "pre_entry_sweep": sweep_v,
                    "wick_ratio_5": wick_v if wick_v is not None else np.nan,
                    "tp_plan_name": row["tp_plan_name"],
                    "expansion_state": row["expansion_state"],
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
                    # v1.9_MULTIPOS: position_num / tier_label 전달 (candidates 에 있음)
                    "position_num": row.get("position_num", 1),
                    "tier_label": row.get("tier_label", tier_label),
                    "tier_mult_final": row.get("tier_mult_final", tier_mult),
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
        "strategy_variant": f"v19g_phase_ab_rp_boost_r{risk_multiplier:.1f}x_{'saFree' if sa_cap_free else 'capAll3'}",
        "risk_multiplier": risk_multiplier,
        "sa_cap_free": sa_cap_free,
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


def _calc_pf(df, mask):
    gp = df.loc[mask & (df["net_pnl"] > 0), "net_pnl"].sum()
    gl = abs(df.loc[mask & (df["net_pnl"] < 0), "net_pnl"].sum())
    if gl <= 1e-9:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def print_scenario_summary_v19g(result_dict):
    trades_df = result_dict["trades"].copy()
    equity_df = result_dict["equity"].copy()
    phase_df = result_dict["phase_transitions"]
    excess_df = result_dict["excess_log"]
    skipped_df = result_dict.get("skipped", pd.DataFrame())

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
    print(f"  risk_multiplier: {result_dict.get('risk_multiplier', 1.0):.1f}x")
    sa_free = result_dict.get('sa_cap_free', False)
    print(f"  S/A notional cap: {'해제 (999.0)' if sa_free else f'기본 ({MAX_NOTIONAL_MULT})'}")

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
        print(f"  최초 Excess 시점   : {pd.Timestamp(excess_df.iloc[0]['time']).strftime('%Y-%m-%d %H:%M')}")
        print(f"  최종 Excess 시점   : {pd.Timestamp(excess_df.iloc[-1]['time']).strftime('%Y-%m-%d %H:%M')}")

    # ========== 티어별 분포 ==========
    if "tier" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🎲 티어별 분포 (실제 진입 기준)")
        tier_stat = trades_df.groupby("tier").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        tier_stat["PF"] = tier_stat["tier"].apply(
            lambda t: _calc_pf(trades_df, trades_df["tier"] == t)
        )
        total_pnl = tier_stat["net_pnl_usdt"].sum()
        if abs(total_pnl) > 1e-9:
            tier_stat["pnl_contribution_%"] = tier_stat["net_pnl_usdt"] / total_pnl * 100
        else:
            tier_stat["pnl_contribution_%"] = 0.0
        tier_stat = tier_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3, "pnl_contribution_%": 2})
        print(tier_stat.to_string(index=False))

    # ========== RP별 분포 (★ v1.9g 필터 후) ==========
    if "run_potential" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🚀 run_potential 별 분포 (v1.9g RP 테이블 Boost 필터 후)")
        rp_stat = trades_df.groupby("run_potential").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        rp_stat["PF"] = rp_stat["run_potential"].apply(
            lambda r: _calc_pf(trades_df, trades_df["run_potential"] == r)
        )
        total_pnl = rp_stat["net_pnl_usdt"].sum()
        if abs(total_pnl) > 1e-9:
            rp_stat["pnl_contribution_%"] = rp_stat["net_pnl_usdt"] / total_pnl * 100
        else:
            rp_stat["pnl_contribution_%"] = 0.0
        rp_stat = rp_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3, "pnl_contribution_%": 2})
        print(rp_stat.to_string(index=False))

    # ========== RP action 별 분포 ==========
    if "rp_action" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🎚 RP action 별 분포 (pass/damp)")
        rpa_stat = trades_df.groupby("rp_action").agg(
            trades=("symbol", "count"),
            winrate_pct=("net_pnl", lambda s: (s>0).mean()*100),
            avg_r=("r_multiple", "mean"),
            net_pnl_usdt=("net_pnl", "sum"),
        ).reset_index()
        rpa_stat["PF"] = rpa_stat["rp_action"].apply(
            lambda a: _calc_pf(trades_df, trades_df["rp_action"] == a)
        )
        rpa_stat = rpa_stat.round({"winrate_pct": 2, "avg_r": 3, "net_pnl_usdt": 2, "PF": 3})
        print(rpa_stat.to_string(index=False))

    # ========== 티어 × RP 교차 ==========
    if "tier" in trades_df.columns and "run_potential" in trades_df.columns and len(trades_df) > 0:
        print(f"\n🔀 티어 × run_potential 교차 (거래 수)")
        cross = trades_df.pivot_table(
            index="tier", columns="run_potential", values="symbol",
            aggfunc="count", fill_value=0, margins=True, margins_name="TOTAL",
        )
        print(cross.to_string())

        print(f"\n🔀 티어 × run_potential 교차 (avg R)")
        cross_r = trades_df.pivot_table(
            index="tier", columns="run_potential", values="r_multiple",
            aggfunc="mean", fill_value=np.nan,
        ).round(3)
        print(cross_r.to_string())

    # ========== 스킵 사유 분포 ==========
    if len(skipped_df) > 0 and "reason" in skipped_df.columns:
        print(f"\n🚫 스킵 사유 분포")
        skip_cnt = skipped_df["reason"].value_counts().head(15)
        for r, c in skip_cnt.items():
            print(f"  {r}: {c}")
        rp_skipped = skipped_df[skipped_df["reason"].str.startswith("rp_skip_", na=False)]
        tier_skipped = skipped_df[skipped_df["reason"].str.startswith("tier_skip_", na=False)]
        print(f"\n  └─ RP 스킵 총 {len(rp_skipped)} / 티어D 스킵 총 {len(tier_skipped)}")

    # ========== 월별 ==========
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


def plot_equity_v19g(result_dict):
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
    sa_tag = "saFree" if result_dict.get('sa_cap_free', False) else f"cap{MAX_NOTIONAL_MULT}"
    ax.set_title(f"{result_dict['scenario_name']} - Equity Curve (risk×{result_dict.get('risk_multiplier',1.0):.1f}, {sa_tag}) [KRW 100M]", fontsize=11)
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


# =========================================================
# ★★★ v1.9g 비교 리포트 함수 (risk×1 vs risk×2) ★★★
# =========================================================
def _safe_pct(num, den):
    if den is None or den == 0 or (isinstance(den, float) and pd.isna(den)):
        return np.nan
    return num / den * 100.0


def print_comparison_v19g(res_r1, res_r2):
    """risk×1 과 risk×2 시나리오를 나란히 비교"""
    total_deposit_usdt = INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS
    total_deposit_krw = total_deposit_usdt * KRW_PER_USDT

    def _extract(res):
        trades = res["trades"]
        eq = res["equity"]
        n = len(trades)
        gp = trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum() if n > 0 else 0.0
        gl = abs(trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum()) if n > 0 else 0.0
        pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else np.nan)
        win = (trades["net_pnl"] > 0).mean() * 100 if n > 0 else np.nan
        avg_r = trades["r_multiple"].mean() if n > 0 else np.nan
        mdd = eq["dd_pct"].min() if len(eq) > 0 else np.nan
        final_total_krw = res["final_total_assets_krw"]
        net_profit_krw = final_total_krw - total_deposit_krw
        ret_pct = _safe_pct(net_profit_krw, total_deposit_krw)

        return {
            "risk_multiplier": res.get("risk_multiplier", 1.0),
            "trades": n,
            "PF": pf,
            "win_pct": win,
            "avg_r": avg_r,
            "mdd_pct": mdd,
            "return_pct": ret_pct,
            "final_balance_krw": res["final_balance_krw"],
            "final_excess_krw": res["final_cumulative_excess_krw"],
            "final_total_krw": final_total_krw,
            "net_profit_krw": net_profit_krw,
        }

    m1 = _extract(res_r1)
    m2 = _extract(res_r2)

    print("\n" + "=" * 140)
    print("🔀 v1.9g  risk×1  vs  risk×2  비교 리포트")
    print("=" * 140)

    # 핵심 지표 나란히 표시
    def _fmt_num(v, fmt="{:.2f}"):
        if v is None or (isinstance(v, float) and (pd.isna(v) or not np.isfinite(v))):
            return "N/A"
        return fmt.format(v)

    labels = [
        ("거래 수",              "trades",              "{:,}"),
        ("PF",                  "PF",                  "{:.3f}"),
        ("승률 (%)",             "win_pct",             "{:.2f}"),
        ("평균 R",               "avg_r",               "{:.3f}"),
        ("MDD (%)",             "mdd_pct",             "{:.2f}"),
        ("수익률 (%)",           "return_pct",          "{:,.1f}"),
        ("최종 Balance (KRW)",   "final_balance_krw",   "{:,.0f}"),
        ("누적 Excess (KRW)",    "final_excess_krw",    "{:,.0f}"),
        ("총 자산 (KRW)",        "final_total_krw",     "{:,.0f}"),
        ("순이익 (KRW)",         "net_profit_krw",      "{:,.0f}"),
    ]

    print(f"\n{'지표':<24} | {'risk×'+str(m1['risk_multiplier'])+'  (baseline)':>30} | {'risk×'+str(m2['risk_multiplier'])+'  (aggressive)':>30} | {'변화':>18}")
    print("-" * 140)

    for label, key, fmt in labels:
        v1_str = _fmt_num(m1[key], fmt)
        v2_str = _fmt_num(m2[key], fmt)

        if key in ("PF", "win_pct", "avg_r", "mdd_pct", "return_pct"):
            if m1[key] is not None and m2[key] is not None and np.isfinite(m1[key]) and np.isfinite(m2[key]):
                diff = m2[key] - m1[key]
                if key == "mdd_pct":
                    change_str = f"{diff:+.2f}pp"
                else:
                    change_str = f"{diff:+.2f}"
            else:
                change_str = "N/A"
        elif key == "trades":
            diff = m2[key] - m1[key]
            change_str = f"{diff:+,}"
        else:
            if m1[key] != 0:
                ratio = m2[key] / m1[key]
                change_str = f"×{ratio:.2f}"
            else:
                change_str = "N/A"

        print(f"{label:<24} | {v1_str:>30} | {v2_str:>30} | {change_str:>18}")

    # MDD 대비 수익 효율 (Return / |MDD|)
    print("\n📊 MDD 효율 지표 (Return% / |MDD%|)")
    for res, m in [("risk×1", m1), ("risk×2", m2)]:
        if m["mdd_pct"] is not None and abs(m["mdd_pct"]) > 1e-9 and np.isfinite(m["return_pct"]):
            eff = m["return_pct"] / abs(m["mdd_pct"])
            print(f"  {res}: {m['return_pct']:>12,.1f}% / {abs(m['mdd_pct']):>5.2f}% = {eff:>8.1f}")
        else:
            print(f"  {res}: N/A")

    # 퇴사 조건 검증 비교
    target_man = RETIREMENT_MONTHLY_TARGET_KRW / 1e4
    print(f"\n🏠 퇴사 조건 달성 비교 (최근 {RETIREMENT_WINDOW_MONTHS}M 평균 ≥ {target_man:,.0f}만원)")

    for res, tag in [(res_r1, "risk×1"), (res_r2, "risk×2")]:
        monthly = build_monthly_pnl_krw(res["trades"], res["deposit_df"])
        retire = find_retirement_month(monthly)
        if retire is not None:
            idx = monthly[monthly["month"] == retire["month"]].index[0]
            months_taken = idx + 1
            print(f"  {tag}: ✅ {retire['month']} ({months_taken}개월차) "
                  f"| 3M 평균 {retire['rolling_3m_avg_krw']/1e4:,.0f}만원")
        else:
            print(f"  {tag}: ❌ 미달성")

    # 비교 정리
    print("\n💡 판단 포인트")
    if np.isfinite(m1["mdd_pct"]) and np.isfinite(m2["mdd_pct"]):
        mdd_ratio = abs(m2["mdd_pct"]) / abs(m1["mdd_pct"]) if abs(m1["mdd_pct"]) > 1e-9 else np.nan
        print(f"  - MDD 확대율: ×{mdd_ratio:.2f} (이론상 2배, 실제 {mdd_ratio:.2f}배)")

    if m1["net_profit_krw"] > 0 and m2["net_profit_krw"] > 0:
        profit_ratio = m2["net_profit_krw"] / m1["net_profit_krw"]
        print(f"  - 순이익 증가율: ×{profit_ratio:.2f}")

    if np.isfinite(m1["PF"]) and np.isfinite(m2["PF"]):
        pf_diff = m2["PF"] - m1["PF"]
        print(f"  - PF 변화: {pf_diff:+.3f} (이론상 동일해야 함, 차이 크면 실행 스케일 효과)")

    return m1, m2


def save_comparison_csv(res_r1, res_r2, outpath):
    """비교 테이블을 CSV로 저장"""
    total_deposit_krw = (INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS) * KRW_PER_USDT

    def _summary_row(res):
        trades = res["trades"]
        eq = res["equity"]
        n = len(trades)
        gp = trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum() if n > 0 else 0.0
        gl = abs(trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum()) if n > 0 else 0.0
        pf = (gp / gl) if gl > 0 else np.nan
        return {
            "risk_multiplier": res.get("risk_multiplier", 1.0),
            "trades": n,
            "PF": pf,
            "win_pct": (trades["net_pnl"] > 0).mean() * 100 if n > 0 else np.nan,
            "avg_r": trades["r_multiple"].mean() if n > 0 else np.nan,
            "mdd_pct": eq["dd_pct"].min() if len(eq) > 0 else np.nan,
            "final_balance_krw": res["final_balance_krw"],
            "final_excess_krw": res["final_cumulative_excess_krw"],
            "final_total_krw": res["final_total_assets_krw"],
            "net_profit_krw": res["final_total_assets_krw"] - total_deposit_krw,
            "return_pct": (res["final_total_assets_krw"] - total_deposit_krw) / total_deposit_krw * 100,
        }

    rows = [_summary_row(res_r1), _summary_row(res_r2)]
    pd.DataFrame(rows).to_csv(outpath, index=False)


# =========================================================
# ★★★ v1.9g 4-way 매트릭스 비교 (risk×1/×2 × cap/saFree) ★★★
# =========================================================
def _metric_pack(res):
    """단일 시나리오에서 핵심 지표 추출"""
    trades = res["trades"]
    eq = res["equity"]
    n = len(trades)
    gp = trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum() if n > 0 else 0.0
    gl = abs(trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum()) if n > 0 else 0.0
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else np.nan)
    total_deposit_krw = (INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS) * KRW_PER_USDT
    return {
        "trades": n,
        "PF": pf,
        "win_pct": (trades["net_pnl"] > 0).mean() * 100 if n > 0 else np.nan,
        "avg_r": trades["r_multiple"].mean() if n > 0 else np.nan,
        "mdd_pct": eq["dd_pct"].min() if len(eq) > 0 else np.nan,
        "return_pct": (res["final_total_assets_krw"] - total_deposit_krw) / total_deposit_krw * 100,
        "final_total_krw": res["final_total_assets_krw"],
        "net_profit_krw": res["final_total_assets_krw"] - total_deposit_krw,
    }


def print_matrix_v19g(results_2x2):
    """
    4-way 매트릭스 비교 리포트
    results_2x2 = {
        "r1_cap": res, "r1_free": res,
        "r2_cap": res, "r2_free": res,
    }
    """
    packs = {k: _metric_pack(v) for k, v in results_2x2.items()}

    def _fmt(v, kind):
        if v is None or (isinstance(v, float) and (pd.isna(v) or not np.isfinite(v))):
            return "N/A"
        if kind == "trades":
            return f"{int(v):>6,}"
        if kind == "PF":
            return f"{v:>6.2f}"
        if kind == "pct":
            return f"{v:>6.2f}%"
        if kind == "pct_big":
            return f"{v:>12,.0f}%"
        if kind == "krw":
            return f"{v:>18,.0f}"
        if kind == "r":
            return f"{v:>6.3f}"
        return str(v)

    print("\n" + "=" * 144)
    print("🔀 v1.9g  4-way 매트릭스 비교  (risk×1/×2  ×  cap 3.0/S-A free)")
    print("=" * 144)

    metrics = [
        ("거래 수",      "trades",          "trades"),
        ("PF",          "PF",              "PF"),
        ("승률",         "win_pct",         "pct"),
        ("평균 R",       "avg_r",           "r"),
        ("MDD",         "mdd_pct",         "pct"),
        ("수익률",       "return_pct",      "pct_big"),
        ("총 자산(KRW)", "final_total_krw", "krw"),
        ("순이익(KRW)",  "net_profit_krw",  "krw"),
    ]

    for label, key, kind in metrics:
        print(f"\n▶ {label}")
        print(f"  {'':13} | {'cap 3.0 (기본)':^22} | {'S/A cap FREE':^22}")
        print(f"  {'-'*13} + {'-'*22} + {'-'*22}")
        for tag_prefix, risk_label in [("r1", "risk × 1.0"), ("r2", "risk × 2.0")]:
            v_cap = packs[f"{tag_prefix}_cap"].get(key)
            v_free = packs[f"{tag_prefix}_free"].get(key)
            print(f"  {risk_label:<13} | {_fmt(v_cap, kind):>22} | {_fmt(v_free, kind):>22}")

    # 효과 분해 분석
    print("\n" + "=" * 144)
    print("💡 효과 분해 분석")
    print("=" * 144)

    # 1) cap 해제 효과 (risk×1 기준)
    if np.isfinite(packs["r1_cap"]["return_pct"]) and np.isfinite(packs["r1_free"]["return_pct"]):
        ret_gain = packs["r1_free"]["return_pct"] - packs["r1_cap"]["return_pct"]
        mdd_inc = packs["r1_free"]["mdd_pct"] - packs["r1_cap"]["mdd_pct"]
        print(f"\n  [cap 해제 효과 @ risk×1]")
        print(f"    Return: {packs['r1_cap']['return_pct']:>10,.1f}% → {packs['r1_free']['return_pct']:>10,.1f}%  "
              f"(Δ {ret_gain:+,.1f}pp)")
        print(f"    MDD   : {packs['r1_cap']['mdd_pct']:>10.2f}% → {packs['r1_free']['mdd_pct']:>10.2f}%  "
              f"(Δ {mdd_inc:+.2f}pp)")
        if abs(mdd_inc) > 1e-9:
            print(f"    Return/MDD 효율: ΔReturn {ret_gain:+,.1f}pp / ΔMDD {mdd_inc:+.2f}pp = {ret_gain/abs(mdd_inc):>8.1f}")

    # 2) cap 해제 효과 (risk×2 기준)
    if np.isfinite(packs["r2_cap"]["return_pct"]) and np.isfinite(packs["r2_free"]["return_pct"]):
        ret_gain = packs["r2_free"]["return_pct"] - packs["r2_cap"]["return_pct"]
        mdd_inc = packs["r2_free"]["mdd_pct"] - packs["r2_cap"]["mdd_pct"]
        print(f"\n  [cap 해제 효과 @ risk×2]")
        print(f"    Return: {packs['r2_cap']['return_pct']:>10,.1f}% → {packs['r2_free']['return_pct']:>10,.1f}%  "
              f"(Δ {ret_gain:+,.1f}pp)")
        print(f"    MDD   : {packs['r2_cap']['mdd_pct']:>10.2f}% → {packs['r2_free']['mdd_pct']:>10.2f}%  "
              f"(Δ {mdd_inc:+.2f}pp)")

    # 3) risk 배수 효과 (cap 기준)
    if np.isfinite(packs["r1_cap"]["return_pct"]) and np.isfinite(packs["r2_cap"]["return_pct"]):
        profit_r1 = packs["r1_cap"]["net_profit_krw"]
        profit_r2 = packs["r2_cap"]["net_profit_krw"]
        if profit_r1 > 0:
            profit_ratio = profit_r2 / profit_r1
            print(f"\n  [risk 배수 효과 @ cap normal]")
            print(f"    순이익 증가율: ×{profit_ratio:.2f} (이론상 ×2.0)")
            mdd_ratio = abs(packs['r2_cap']['mdd_pct']) / abs(packs['r1_cap']['mdd_pct']) if abs(packs['r1_cap']['mdd_pct']) > 1e-9 else np.nan
            if np.isfinite(mdd_ratio):
                print(f"    MDD 확대율   : ×{mdd_ratio:.2f} (이론상 ×2.0)")

    # 4) 최적 판단 힌트
    print(f"\n  [실전 적용 판단 참고 — Return/MDD 효율]")
    for tag_prefix in ["r1_cap", "r1_free", "r2_cap", "r2_free"]:
        p = packs[tag_prefix]
        if np.isfinite(p["return_pct"]) and abs(p["mdd_pct"]) > 1e-9:
            eff = p["return_pct"] / abs(p["mdd_pct"])
            label_map = {
                "r1_cap": "r×1 / cap",
                "r1_free": "r×1 / SAfree",
                "r2_cap": "r×2 / cap",
                "r2_free": "r×2 / SAfree",
            }
            print(f"    {label_map[tag_prefix]:<14}: Return {p['return_pct']:>10,.1f}% / |MDD| {abs(p['mdd_pct']):>5.2f}% = {eff:>8.1f}")

    return packs


def save_matrix_csv(results_2x2, outpath):
    """4개 시나리오 지표를 CSV 한 장으로 저장"""
    rows = []
    for tag, res in results_2x2.items():
        pack = _metric_pack(res)
        pack["scenario_tag"] = tag
        pack["risk_multiplier"] = res.get("risk_multiplier", 1.0)
        pack["sa_cap_free"] = res.get("sa_cap_free", False)
        rows.append(pack)
    pd.DataFrame(rows).to_csv(outpath, index=False)


print("v1.9_REALISTIC Part 3/3 loaded: candidate + simulation + report + 2-way/4-way comparison")


# =========================================================
# ★★★ 셀 1: 데이터 다운로드 (병렬 처리) ★★★
# =========================================================
SYMBOLS_TO_PREPARE = sorted(list(SCENARIO_MULTI["assets"].keys()))

# =========================================================
# 🔍 실행 환경 체크 (Colab / Local 구분)
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
print("🔍 실행 환경")
print("=" * 75)
print(f"  환경: {'Google Colab' if _in_colab else 'Local'}")
print(f"  CPU 코어: {_cpu_count}")
if _ram_gb:
    print(f"  RAM: {_ram_gb:.1f} GB")

# Colab CPU 2 코어 경고
if _cpu_count <= 2:
    print()
    print("  ⚠️ CPU 코어 2개 이하 → CPU 병렬 효과 제한적 (2배 정도)")
    print("     - 네트워크 다운로드는 thread 병렬로 9배 효과 O")
    print("     - indicators/candidates 는 process 병렬로 2배 효과")
else:
    print(f"  ✅ {_cpu_count} 코어 활용 가능")
print("=" * 75)
print()

# =========================================================
# 병렬 처리 유틸리티
# =========================================================
import time as _time_module

def _parallel_map(func, items, n_workers=None, task_name="task", io_bound=False):
    """
    주피터/Colab 환경에서 안정적으로 동작하는 병렬 맵.

    io_bound=True : 네트워크/디스크 I/O 용 (thread)
                    → Colab 에서도 속도 높음 (CPU 코어 제약 없음)
    io_bound=False: CPU 연산용 (process)
                    → 진짜 병렬 처리, CPU 코어 수만큼 확장

    우선순위:
      CPU bound: joblib(loky) → ProcessPoolExecutor → 순차
      IO bound:  ThreadPoolExecutor → 순차

    Colab 고려사항:
      - 무료 Colab: CPU 2 코어 → 2 워커만 유의미
      - Colab Pro: CPU 4 코어 → 4 워커
      - 자동 감지 후 적정 워커 수 설정
    """
    import os as _os
    n = len(items)

    if n_workers is None:
        if io_bound:
            # I/O bound 는 GIL 영향 없어서 많은 thread 가능
            n_workers = min(n, 9)
        else:
            # CPU bound 는 실제 코어 수 제한
            n_workers = min(n, _os.cpu_count() or 2)
    else:
        # 사용자 지정 있어도 io_bound=False 일 때는 CPU 제한 적용
        if not io_bound:
            n_workers = min(n_workers, _os.cpu_count() or 2)

    t0 = _time_module.time()
    results = None
    errors = []

    # I/O bound: thread 사용 (process 대비 오버헤드 거의 없음)
    if io_bound:
        try:
            from concurrent.futures import ThreadPoolExecutor
            print(f"  🔀 ThreadPool I/O 병렬 ({n_workers} threads, {n} {task_name})")
            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e:
            print(f"  ⚠️ Thread 실패 ({type(e).__name__}), 순차 처리")
            results = [func(item) for item in items]

        elapsed = _time_module.time() - t0
        print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
        return results

    # CPU bound: process 병렬
    # 1) joblib (loky backend) - Jupyter/Colab 호환성 최고
    try:
        from joblib import Parallel, delayed
        print(f"  🔀 joblib(loky) CPU 병렬 ({n_workers} workers, {n} {task_name})")
        results = Parallel(n_jobs=n_workers, backend="loky", verbose=0)(
            delayed(func)(item) for item in items
        )
    except Exception as e_joblib:
        errors.append(("joblib", e_joblib))

        # 2) ProcessPoolExecutor fallback
        try:
            from concurrent.futures import ProcessPoolExecutor
            print(f"  🔀 ProcessPoolExecutor fallback ({n_workers} workers, {n} {task_name})")
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e_pool:
            errors.append(("ProcessPoolExecutor", e_pool))

            # 3) 순차 처리 fallback
            print(f"  ⚠️ 병렬 처리 모두 실패, 순차 처리 fallback")
            for name, e in errors:
                print(f"     - {name}: {type(e).__name__}: {str(e)[:120]}")
            results = [func(item) for item in items]

    elapsed = _time_module.time() - t0
    print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
    return results


# 데이터 다운로드 (병렬)
# 주의: download_symbol_data 가 네트워크 I/O bound 이므로 병렬화 효과 큼
print("=" * 75)
print(f"📥 데이터 다운로드 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

raw_results = _parallel_map(
    download_symbol_data,
    SYMBOLS_TO_PREPARE,
    n_workers=min(len(SYMBOLS_TO_PREPARE), 9),
    task_name="심볼 다운로드",
    io_bound=True,  # 네트워크 I/O → thread 병렬 (Colab 에서도 효과적)
)
raw_data = dict(zip(SYMBOLS_TO_PREPARE, raw_results))

print("\n✅ 데이터 다운로드 완료. 셀 2를 실행하세요.")


# =========================================================
# ★★★ 셀 2: indicator + 구조물 + candidates ★★★
# =========================================================
H4_PIVOT_SWING_LEN = 30
H4_MSS_LOOKBACK = 80
H4_OB_LOOKBACK = 15
H4_PD_LOOKBACK = 1620
H4_MARKET_STATE_BARS = 360
H4_ZONE_MAX_AGE = 30

LONG_BASE_ENTRY_FRAC = 0.10
SHORT_BASE_ENTRY_FRAC = 0.90

# =========================================================
# ⭐⭐ MAX_POSITIONS_PER_SYMBOL (단일 vs 멀티포지션)
# =========================================================
# 1 = 단일 포지션 (심볼당 최대 1개, 기존 MULTIPOS 비활성)
# 2 = MULTIPOS (심볼당 최대 2개, 2번째는 S/A 만)
# 단일 실험 시 1 권장 (MDD 안정)
# =========================================================
MAX_POSITIONS_PER_SYMBOL = 1

# =========================================================
# ⭐⭐⭐ 필터 그룹 시스템 (신규)
# =========================================================
# 철학:
#   기존엔진 AND (그룹1 OR 그룹2 OR ... OR 그룹N)
#   각 그룹 내부는 OR
#   그룹 간 OR (하나라도 통과하면 진입)
#   → 매우 완화된 구조
#   → CSV 분석으로 실제 유효한 필터 조합 발견 목적
#
# 동작:
#   USE_FILTER_GROUPS=True: 아래 FILTER_GROUPS 사용
#   USE_FILTER_GROUPS=False: 기존 AND 방식 (baseline)
#
# CSV 출력:
#   각 거래마다 어떤 필터가 통과했는지 기록
#   pass_vol, pass_sweep, pass_d1, pass_pull, pass_atr (True/False)
#   pass_combo: "VOL+SWEEP+ATR" 등 조합 이름
#   pass_count: 통과 필터 개수
#   pass_groups: 통과한 그룹 번호 (G1, G2 등)
#
# 분석 시 trades.csv 에서:
#   - 각 조합별 승률, avg_R 계산
#   - 고성능 조합 발견 → 그 조합만 AND 로 강제
# =========================================================
USE_FILTER_GROUPS = True  # True = 그룹 OR / False = 기존 AND
FILTER_GROUPS = [
    ["VOLUME", "LIQUIDITY_SWEEP"],   # 그룹 1
    ["D1_TREND", "PULLBACK_DEPTH"],  # 그룹 2
    ["ATR"],                         # 그룹 3 (단독)
]

# =========================================================
# ⭐ 필터 제어 패널 (USE_FILTER_GROUPS=False 때만 적용)
# =========================================================
#
# 필터 설명:
#   D1_TREND_FILTER   : 일봉 추세 정합성 필터 (H4 와 D1 방향 일치 요구)
#   LIQUIDITY_SWEEP   : 진입 직전 liquidity sweep 확인 필터
#   VOLUME_FILTER     : zone 생성 봉의 volume >= 평균 필터
#   PULLBACK_DEPTH    : 현재가가 zone 깊숙이 진입했는지 검증
#   ATR_FILTER        : ATR 변동성 적정 범위 필터
#
# SWEEP_VOLUME_MODE  : LIQUIDITY_SWEEP 과 VOLUME 을 조합하는 방식 (AND/OR)
# =========================================================
USE_D1_TREND_FILTER      = True   # 그룹 실험 시 True 여야 필터 결과 계산됨
USE_LIQUIDITY_SWEEP_CONF = True
USE_VOLUME_FILTER        = True
USE_PULLBACK_DEPTH       = True
USE_ATR_FILTER           = True
SWEEP_VOLUME_MODE        = "OR"  # "AND" or "OR"

# 필터 설정 출력
print("=" * 75)
print(f"🎛  필터 시스템 설정 (MAX_POSITIONS_PER_SYMBOL = {MAX_POSITIONS_PER_SYMBOL})")
print("=" * 75)
if USE_FILTER_GROUPS:
    print(f"  모드: ⭐ FILTER_GROUPS (그룹 내부 OR, 그룹 간 OR)")
    for gi, group in enumerate(FILTER_GROUPS, 1):
        print(f"    그룹 {gi}: {' OR '.join(group)}")
    print(f"  → 진입 = 기존엔진 AND (G1 OR G2 OR ...)")
    print(f"  → CSV 에서 pass_combo 분석 후 최적 조합 발견")
else:
    print(f"  모드: 기존 AND (baseline)")
    filter_settings = [
        ("D1_TREND_FILTER",   USE_D1_TREND_FILTER),
        ("LIQUIDITY_SWEEP",   USE_LIQUIDITY_SWEEP_CONF),
        ("VOLUME_FILTER",     USE_VOLUME_FILTER),
        ("PULLBACK_DEPTH",    USE_PULLBACK_DEPTH),
        ("ATR_FILTER",        USE_ATR_FILTER),
    ]
    for name, flag in filter_settings:
        icon = "✅ ON " if flag else "⭕ OFF"
        print(f"  {icon} | {name}")
    print(f"  SWEEP_VOLUME_MODE: {SWEEP_VOLUME_MODE}")
print("=" * 75)

# =========================================================
# 병렬 처리 준비
# 중요: multiprocessing 은 전역 상태(필터 플래그 등)를 공유하지 않을 수 있음
# → 각 워커는 새 프로세스에서 import 시작점부터 재실행됨
# → USE_VOLUME_FILTER 등이 각 워커에서 어떻게 보이느냐가 관건
# → 주피터 환경에선 __main__ 이 워커에 pickle 로 전달돼 필터 플래그 반영됨
# =========================================================

# indicators + 구조물 생성 (CPU bound, 병렬화 효과 큼)
print()
print("=" * 75)
print(f"🔧 indicators + 구조물 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

# 병렬 처리를 위한 wrapper
# joblib 의 loky backend 는 부모 namespace 를 cloudpickle 로 전달해서
# 전역 변수 (USE_VOLUME_FILTER 등) 가 워커에 그대로 복사됨
# → generate_candidates_from_prepared 의 전역 참조 동작

def _apply_indicators_single(sym):
    """단일 심볼 indicators 처리. (병렬화용 wrapper)"""
    return sym, apply_indicators_and_build(raw_data[sym])

# 병렬 처리 불가능한 환경 대비 (raw_data 가 전역이라 pickle 에서 문제 가능)
# → 순차 처리로 fallback 될 수 있음
try:
    prepared_results = _parallel_map(
        _apply_indicators_single,
        SYMBOLS_TO_PREPARE,
        n_workers=min(len(SYMBOLS_TO_PREPARE), 9),
        task_name="indicators",
        io_bound=False,  # CPU 연산 → process 병렬
    )
    prepared_data = dict(prepared_results)
except Exception as e:
    print(f"  ⚠️ indicators 병렬 실패: {e}")
    print(f"  📝 순차 처리 fallback")
    prepared_data = {}
    for sym in SYMBOLS_TO_PREPARE:
        t_s = _time_module.time()
        prepared_data[sym] = apply_indicators_and_build(raw_data[sym])
        print(f"    {sym}: {_time_module.time() - t_s:.1f}초")

# candidates 생성 (가장 무거운 단계, 병렬화 효과 가장 큼)
print()
print("=" * 75)
print(f"🎯 candidates 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

def _generate_candidates_single(sym):
    """단일 심볼 candidates 생성. (병렬화용 wrapper)
    전역 변수 USE_VOLUME_FILTER 등은 joblib 의 cloudpickle 로 전달됨.
    """
    return sym, generate_candidates_from_prepared(prepared_data[sym])

try:
    candidates_results = _parallel_map(
        _generate_candidates_single,
        SYMBOLS_TO_PREPARE,
        n_workers=min(len(SYMBOLS_TO_PREPARE), 9),
        task_name="candidates",
        io_bound=False,  # CPU 연산 → process 병렬
    )
    candidates_dict = dict(candidates_results)
except Exception as e:
    print(f"  ⚠️ candidates 병렬 실패: {e}")
    print(f"  📝 순차 처리 fallback")
    candidates_dict = {}
    for sym in SYMBOLS_TO_PREPARE:
        t_s = _time_module.time()
        candidates_dict[sym] = generate_candidates_from_prepared(prepared_data[sym])
        print(f"    {sym}: {_time_module.time() - t_s:.1f}초")

# =========================================================
# 📊 셀 2 종료 후 candidates 요약 (필터 영향 분석용)
# =========================================================
print()
print("=" * 75)
print("📊 셀2 완료 — candidates 집계")
print("=" * 75)

total_candidates = 0
total_no_fill = 0
tier_agg = {"S": 0, "A": 0, "B": 0, "C": 0}

for sym in SYMBOLS_TO_PREPARE:
    cand_df = candidates_dict[sym]["candidates"]
    no_fill_df = candidates_dict[sym].get("no_fill")
    nc = len(cand_df) if cand_df is not None else 0
    nn = len(no_fill_df) if no_fill_df is not None else 0
    total_candidates += nc
    total_no_fill += nn

    if cand_df is not None and "tier_label" in cand_df.columns:
        for t in ["S", "A", "B", "C"]:
            tier_agg[t] += int((cand_df["tier_label"] == t).sum())

    print(f"  {sym:<10}: candidates={nc:>4} | no_fill={nn:>4}")

print("-" * 75)
print(f"  TOTAL     : candidates={total_candidates:>4} | no_fill={total_no_fill:>4}")
print()
print(f"  Tier 분포: S={tier_agg['S']} | A={tier_agg['A']} | B={tier_agg['B']} | C={tier_agg['C']}")
print("=" * 75)

# =========================================================
# 🔍 전체 심볼 통합 skip 사유 집계 (필터 효과 분석)
# =========================================================
print()
print("=" * 75)
print("🔍 필터별 skip 통합 집계 (9코인 전체)")
print("=" * 75)

all_skips = {}
for sym in SYMBOLS_TO_PREPARE:
    sr = candidates_dict[sym].get("skip_reasons", {}) or {}
    for reason, count in sr.items():
        all_skips[reason] = all_skips.get(reason, 0) + count

# 필터 카테고리 분류
def categorize_skip(reason):
    r = reason.lower()
    if "vol" in r and "or_fail" not in r:
        return "VOLUME"
    if "sweep" in r and "or_fail" not in r:
        return "SWEEP"
    if "atr" in r:
        return "ATR"
    if "pullback" in r or "depth" in r:
        return "PULLBACK"
    if "d1" in r or "trend" in r:
        return "D1_TREND"
    if "tier_d" in r or "tier_c" in r:
        return "TIER (D/C skip)"
    if "multipos" in r:
        return "MULTIPOS_RULE"
    if "or_fail" in r:
        return "SWEEP_OR_VOL"
    if "rp_action" in r:
        return "RP_ACTION"
    return "OTHER"

by_category = {}
for reason, count in all_skips.items():
    cat = categorize_skip(reason)
    by_category[cat] = by_category.get(cat, 0) + count

total_skips = sum(by_category.values())
print(f"\n총 skip 건수: {total_skips:,}\n")
print(f"{'카테고리':<25} {'건수':>8} {'비율':>8}")
print("-" * 50)
for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
    pct = count / total_skips * 100 if total_skips > 0 else 0
    print(f"  {cat:<23} {count:>8,} {pct:>7.1f}%")

# 상위 15개 세부 skip reason
print()
print("🔎 세부 skip 사유 TOP 15:")
for reason, count in sorted(all_skips.items(), key=lambda x: -x[1])[:15]:
    pct = count / total_skips * 100 if total_skips > 0 else 0
    print(f"  {reason:<55} {count:>6,} ({pct:>5.1f}%)")

print("=" * 75)
print()
print("💡 해석 가이드:")
print("   - VOLUME 비율이 높다 → USE_VOLUME_FILTER 완화 고려")
print("   - SWEEP 비율이 높다 → SWEEP_VOLUME_MODE='OR' 변경 고려")
print("   - TIER (D/C skip) 높다 → 정상 (저품질 zone 걸러냄)")
print("   - MULTIPOS_RULE 높다 → MULTIPOS 규칙 엄격 (정상)")
print("=" * 75)

print("\n✅ 구조물 + candidates 생성 완료. 셀 3을 실행하세요.")


# =========================================================
# ★★★ 셀 3: v1.9_BASELINE 백테스트 실행 (단일 시나리오) ★★★
#
# 설정 고정:
#   - risk_multiplier = 1.0    (실전 패널에서 배수 조절)
#   - sa_cap_free     = True   (S/A 티어 notional cap 해제 — 기준 엔진 설계)
#
# 이 값이 실전 엔진의 기준점. 패널에서 multiplier 만 조절하면
#   - multiplier 1.0 → 본 결과와 동일 (r1_free)
#   - multiplier 2.0 → r2_free 수준 (저자본 공격 모드)
# =========================================================
OUTDIR_BASELINE = "smc_crypto_9coins_v17_ltf_outputs"
import os
os.makedirs(OUTDIR_BASELINE, exist_ok=True)


# =========================================================
# v1.9_REALISTIC_MULTIPOS 비교 실행 (R1 vs R2)
# - MULTIPOS_R1: risk_multiplier = 1.0 (baseline 과 동일 risk)
# - MULTIPOS_R2: risk_multiplier = 2.0 (2배 공격)
# 같은 candidates_dict (진입 후보 동일) 에 risk 만 차이
# =========================================================

print("\n" + "=" * 100)
print("▶ v1.9_REALISTIC_MULTIPOS 비교 실행 (R1 vs R2)")
print("=" * 100)
print(f"  MULTIPOS 규칙:")
print(f"    - 심볼당 최대 2 포지션")
print(f"    - 2번째 진입: Tier S or A 만")
print(f"    - 반대 방향 금지")
print(f"    - 같은 zone 재사용 금지")
print(f"  비교:")
print(f"    - MULTIPOS_R1: risk_multiplier = 1.0")
print(f"    - MULTIPOS_R2: risk_multiplier = 2.0")
print(f"  S/A notional cap: 해제 (999.0)")
print(f"  RP table: {RP_TIER_MULT_TABLE}")
print(f"  Phase 전환점: Balance $ {TARGET_BALANCE_USDT:,.0f}")
print("=" * 100)


# ---------- MULTIPOS_R1 실행 ----------
print("\n" + "=" * 80)
print("▶ MULTIPOS_R1 실행 중... (risk×1.0)")
print("=" * 80)

res_r1 = simulate_scenario_v19g(
    scenario=SCENARIO_MULTI,
    candidates_dict=candidates_dict,
    risk_multiplier=1.0,
    sa_cap_free=True,
)

monthly_r1 = print_scenario_summary_v19g(res_r1)
plot_equity_v19g(res_r1)

# CSV 저장 (R1)
out = OUTDIR_BASELINE
res_r1["trades"].to_csv(f"{out}/multipos_r1_trades.csv", index=False)
res_r1["equity"].to_csv(f"{out}/multipos_r1_equity.csv", index=False)
res_r1["skipped"].to_csv(f"{out}/multipos_r1_skipped.csv", index=False)
res_r1["phase_transitions"].to_csv(f"{out}/multipos_r1_phase_transitions.csv", index=False)
res_r1["excess_log"].to_csv(f"{out}/multipos_r1_excess_log.csv", index=False)
monthly_r1.to_csv(f"{out}/multipos_r1_monthly_pnl.csv", index=False)


# ---------- MULTIPOS_R2 실행 ----------
print("\n" + "=" * 80)
print("▶ MULTIPOS_R2 실행 중... (risk×2.0)")
print("=" * 80)

res_r2 = simulate_scenario_v19g(
    scenario=SCENARIO_MULTI,
    candidates_dict=candidates_dict,
    risk_multiplier=2.0,
    sa_cap_free=True,
)

monthly_r2 = print_scenario_summary_v19g(res_r2)
plot_equity_v19g(res_r2)

# CSV 저장 (R2)
res_r2["trades"].to_csv(f"{out}/multipos_r2_trades.csv", index=False)
res_r2["equity"].to_csv(f"{out}/multipos_r2_equity.csv", index=False)
res_r2["skipped"].to_csv(f"{out}/multipos_r2_skipped.csv", index=False)
res_r2["phase_transitions"].to_csv(f"{out}/multipos_r2_phase_transitions.csv", index=False)
res_r2["excess_log"].to_csv(f"{out}/multipos_r2_excess_log.csv", index=False)
monthly_r2.to_csv(f"{out}/multipos_r2_monthly_pnl.csv", index=False)


# ---------- no_fill (공통) ----------
all_no_fill = []
total_filled = 0
total_no_fill = 0
for sym, pack in candidates_dict.items():
    if "no_fill" in pack and len(pack["no_fill"]) > 0:
        all_no_fill.append(pack["no_fill"])
    total_filled += len(pack["candidates"])
    total_no_fill += len(pack.get("no_fill", []))

if all_no_fill:
    no_fill_all = pd.concat(all_no_fill, ignore_index=True).sort_values("signal_time").reset_index(drop=True)
    no_fill_all.to_csv(f"{out}/multipos_no_fill.csv", index=False)


# ---------- R1 vs R2 요약 비교 ----------
def _pick_summary(res, label):
    trades = res["trades"]
    equity = res["equity"]
    if len(trades) == 0 or len(equity) == 0:
        return {
            "label": label,
            "trades": 0,
            "return_pct": 0.0,
            "final_balance": 0.0,
            "mdd_pct": 0.0,
            "pf": 0.0,
            "winrate_pct": 0.0,
            "avg_r": 0.0,
        }
    # scenario 의 실제 컬럼: r_multiple, net_pnl
    r_col = "r_multiple" if "r_multiple" in trades.columns else ("r_adjusted" if "r_adjusted" in trades.columns else None)
    pnl_col = "net_pnl" if "net_pnl" in trades.columns else ("pnl_usdt" if "pnl_usdt" in trades.columns else "pnl")

    if r_col is None:
        return {"label": label, "trades": len(trades), "return_pct": 0.0, "final_balance": 0.0,
                "mdd_pct": 0.0, "pf": 0.0, "winrate_pct": 0.0, "avg_r": 0.0}

    wins = trades[trades[r_col] > 0]
    losses = trades[trades[r_col] <= 0]

    if len(losses) > 0 and abs(losses[pnl_col].sum()) > 0:
        pf = wins[pnl_col].sum() / abs(losses[pnl_col].sum())
    else:
        pf = float("inf")

    winrate = len(wins) / len(trades) * 100 if len(trades) > 0 else 0.0
    avg_r = trades[r_col].mean()

    # equity 컬럼 탐지
    bal_col = None
    for c in ["balance_usdt", "balance", "equity", "total"]:
        if c in equity.columns:
            bal_col = c
            break
    if bal_col is None:
        bal_col = equity.select_dtypes(include="number").columns[-1]  # 마지막 숫자 컬럼

    start_bal = equity[bal_col].iloc[0]
    final_bal = equity[bal_col].iloc[-1]
    ret_pct = (final_bal / start_bal - 1) * 100 if start_bal > 0 else 0.0

    eq_series = equity[bal_col]
    running_max = eq_series.cummax()
    drawdown = (eq_series - running_max) / running_max * 100
    mdd = drawdown.min()

    return {
        "label": label,
        "trades": len(trades),
        "return_pct": ret_pct,
        "final_balance": final_bal,
        "mdd_pct": mdd,
        "pf": pf,
        "winrate_pct": winrate,
        "avg_r": avg_r,
    }


s1 = _pick_summary(res_r1, "MULTIPOS_R1 (×1.0)")
s2 = _pick_summary(res_r2, "MULTIPOS_R2 (×2.0)")

print("\n" + "=" * 100)
print("📊 v1.9_REALISTIC_MULTIPOS — R1 vs R2 비교 요약")
print("=" * 100)
print(f"{'항목':<22} | {'MULTIPOS_R1 (×1.0)':>22} | {'MULTIPOS_R2 (×2.0)':>22}")
print("-" * 100)
print(f"{'거래 수':<22} | {s1['trades']:>22,} | {s2['trades']:>22,}")
print(f"{'최종 Balance ($)':<22} | {s1['final_balance']:>22,.0f} | {s2['final_balance']:>22,.0f}")
print(f"{'Return %':<22} | {s1['return_pct']:>22,.2f} | {s2['return_pct']:>22,.2f}")
print(f"{'PF':<22} | {s1['pf']:>22.3f} | {s2['pf']:>22.3f}")
print(f"{'Win rate %':<22} | {s1['winrate_pct']:>22.2f} | {s2['winrate_pct']:>22.2f}")
print(f"{'Avg R':<22} | {s1['avg_r']:>22.3f} | {s2['avg_r']:>22.3f}")
print(f"{'MDD %':<22} | {s1['mdd_pct']:>22.2f} | {s2['mdd_pct']:>22.2f}")
print("-" * 100)

# 참고값: v1.9_REALISTIC (단일 포지션)
print(f"\n📌 참고 — v1.9_REALISTIC (단일 포지션, 기존):")
print(f"   Return 38,694% | PF 8.723 | MDD -4.90% | Win 75.62% | Trades 640")


# 포지션 번호별 통계 (R1 기준)
all_trades_r1 = res_r1["trades"]
if "position_num" in all_trades_r1.columns and len(all_trades_r1) > 0:
    print(f"\n📌 MULTIPOS_R1 포지션 번호별 통계:")
    r_col = "r_multiple" if "r_multiple" in all_trades_r1.columns else "r_adjusted"
    for pnum in sorted(all_trades_r1["position_num"].unique()):
        sub = all_trades_r1[all_trades_r1["position_num"] == pnum]
        wr = (sub[r_col] > 0).sum() / len(sub) * 100 if len(sub) > 0 else 0
        avr = sub[r_col].mean()
        # tier 분포 — tier_label 우선, 없으면 tier
        tier_col_for_stat = "tier_label" if "tier_label" in sub.columns else ("tier" if "tier" in sub.columns else None)
        if tier_col_for_stat:
            tier_dist = sub[tier_col_for_stat].value_counts().to_dict()
            tier_str = " ".join([f"{k}:{v}" for k, v in sorted(tier_dist.items())])
        else:
            tier_str = "N/A"
        print(f"   position_num={pnum}: {len(sub):>4} trades | win={wr:>5.1f}% | avg_R={avr:>+6.3f} | tiers[{tier_str}]")


# tier별 기여도 (R1 기준)
tier_col_main = "tier_label" if "tier_label" in all_trades_r1.columns else ("tier" if "tier" in all_trades_r1.columns else None)
if tier_col_main and len(all_trades_r1) > 0:
    print(f"\n📌 MULTIPOS_R1 Tier 별 기여도:")
    pnl_col = "net_pnl" if "net_pnl" in all_trades_r1.columns else ("pnl_usdt" if "pnl_usdt" in all_trades_r1.columns else "pnl")
    total_pnl = all_trades_r1[pnl_col].sum() if pnl_col in all_trades_r1.columns else 0
    for tier in ["S", "A", "B", "C", "D"]:
        sub = all_trades_r1[all_trades_r1[tier_col_main] == tier]
        if len(sub) == 0: continue
        t_pnl = sub[pnl_col].sum() if pnl_col in sub.columns else 0
        share = (t_pnl / total_pnl * 100) if total_pnl != 0 else 0
        print(f"   Tier {tier}: {len(sub):>4} trades | PnL ${t_pnl:>15,.0f} | {share:>5.1f}% of total")


print(f"\n💾 CSV 저장 완료: {OUTDIR_BASELINE}/")
print(f"\n🎯 v1.9_REALISTIC_MULTIPOS 백테스트 완료!")
print(f"   threshold: {WICK_RATIO_5_Q1_THRESHOLD}")
rp_table_str = " | ".join([f"rp{k}={v}" for k, v in sorted(RP_TIER_MULT_TABLE.items())])
print(f"   RP table: {rp_table_str} | else=skip")
print(f"   설정: S/A cap FREE + 심볼당 최대 2 포지션 (2번째는 S/A only)")
print(f"   전체 시그널: {total_filled + total_no_fill}")
if total_filled + total_no_fill > 0:
    print(f"   체결 (filled): {total_filled} ({total_filled/(total_filled+total_no_fill)*100:.1f}%)")
    print(f"   미체결 (no_fill): {total_no_fill} ({total_no_fill/(total_filled+total_no_fill)*100:.1f}%)")
else:
    print(f"   체결 (filled): {total_filled}")
    print(f"   미체결 (no_fill): {total_no_fill}")

print(f"\n   💡 실전 이식 결정 힌트:")
print(f"      - R1 Return 이 단일 포지션 대비 개선 → MULTIPOS 효과 입증")
print(f"      - R1 MDD 가 감당 가능 → 실전 이식 검토")
print(f"      - R2 는 MDD 를 평가 — 공격적 운용(패널 ×2.0)시 예상 손실")


# =========================================================
# 🔬 FILTER COMBO 분석 (필터 그룹 시스템 핵심)
# =========================================================
# 각 필터 통과 조합별 성과 집계 → 어떤 조합이 실제로 유효한지 확인
# 결과는 combo_analysis_r1.csv / combo_analysis_r2.csv 로 저장
# =========================================================

if USE_FILTER_GROUPS:
    print()
    print("=" * 85)
    print("🔬 FILTER COMBO 분석 — 어떤 필터 조합이 성과를 냈는가?")
    print("=" * 85)

    def _analyze_combos(trades_df, label):
        """pass_combo 별 성과 집계"""
        if "pass_combo" not in trades_df.columns or len(trades_df) == 0:
            print(f"   {label}: pass_combo 컬럼 없음 (필터 그룹 비활성 상태로 실행된 듯)")
            return None

        # r_multiple 과 result/net_pnl 확인
        r_col = "r_multiple" if "r_multiple" in trades_df.columns else None
        pnl_col = "net_pnl" if "net_pnl" in trades_df.columns else None

        if r_col is None:
            print(f"   {label}: r_multiple 컬럼 없음")
            return None

        # 조합별 집계
        combo_stats = []
        for combo, sub in trades_df.groupby("pass_combo"):
            n = len(sub)
            wins = int((sub[r_col] > 0).sum())
            wr = wins / n * 100 if n > 0 else 0
            avg_r = float(sub[r_col].mean()) if n > 0 else 0
            total_pnl = float(sub[pnl_col].sum()) if pnl_col else 0
            avg_count = float(sub["pass_count"].mean()) if "pass_count" in sub.columns else 0

            combo_stats.append({
                "combo": combo,
                "trades": n,
                "win_rate": round(wr, 2),
                "avg_r": round(avg_r, 3),
                "total_pnl": round(total_pnl, 0),
                "avg_pass_count": round(avg_count, 1),
                "pnl_per_trade": round(total_pnl / n, 2) if n > 0 else 0,
            })

        combo_df = pd.DataFrame(combo_stats)
        # 총 PnL 기준 정렬
        combo_df = combo_df.sort_values("total_pnl", ascending=False).reset_index(drop=True)

        # CSV 저장
        out_path = os.path.join(OUTDIR_BASELINE, f"combo_analysis_{label}.csv")
        combo_df.to_csv(out_path, index=False)

        # 콘솔 출력
        print()
        print(f"📊 {label} — 필터 조합별 성과 TOP 20 (total_pnl 순)")
        print("-" * 85)
        print(f"{'combo':<40} {'trades':>7} {'win%':>7} {'avg_R':>7} {'pnl':>12} {'$/trade':>9}")
        print("-" * 85)
        for _, row in combo_df.head(20).iterrows():
            combo_str = row["combo"][:38]
            print(f"{combo_str:<40} {int(row['trades']):>7} {row['win_rate']:>6.1f}% "
                  f"{row['avg_r']:>+7.3f} ${row['total_pnl']:>+10,.0f} ${row['pnl_per_trade']:>+8,.0f}")

        # 개별 필터 marginal contribution
        print()
        print(f"📉 {label} — 개별 필터 ON/OFF 별 성과")
        print("-" * 85)
        for fname, fcol in [
            ("VOLUME",   "pass_vol"),
            ("SWEEP",    "pass_sweep"),
            ("D1_TREND", "pass_d1"),
            ("PULLBACK", "pass_pull"),
            ("ATR",      "pass_atr"),
        ]:
            if fcol not in trades_df.columns:
                continue
            on_sub = trades_df[trades_df[fcol] == True]
            off_sub = trades_df[trades_df[fcol] == False]

            on_n, off_n = len(on_sub), len(off_sub)
            on_wr = (on_sub[r_col] > 0).sum() / on_n * 100 if on_n > 0 else 0
            off_wr = (off_sub[r_col] > 0).sum() / off_n * 100 if off_n > 0 else 0
            on_r = on_sub[r_col].mean() if on_n > 0 else 0
            off_r = off_sub[r_col].mean() if off_n > 0 else 0
            on_pnl = on_sub[pnl_col].sum() if pnl_col and on_n > 0 else 0
            off_pnl = off_sub[pnl_col].sum() if pnl_col and off_n > 0 else 0

            print(f"  {fname:<10} | PASS: {on_n:>4} trades | win {on_wr:>5.1f}% | "
                  f"avg_R {on_r:>+.3f} | PnL ${on_pnl:>+10,.0f}")
            print(f"  {'':<10} | FAIL: {off_n:>4} trades | win {off_wr:>5.1f}% | "
                  f"avg_R {off_r:>+.3f} | PnL ${off_pnl:>+10,.0f}")

        print()
        print(f"💾 저장: {out_path}")
        return combo_df

    # R1 분석
    r1_trades_path = os.path.join(OUTDIR_BASELINE, "multipos_r1_trades.csv")
    if os.path.exists(r1_trades_path):
        r1_df = pd.read_csv(r1_trades_path)
        _analyze_combos(r1_df, "r1")

    # R2 분석
    r2_trades_path = os.path.join(OUTDIR_BASELINE, "multipos_r2_trades.csv")
    if os.path.exists(r2_trades_path):
        r2_df = pd.read_csv(r2_trades_path)
        _analyze_combos(r2_df, "r2")

    print()
    print("=" * 85)
    print("💡 해석 가이드:")
    print("   - 상위 combo 중 trades 수 충분한 것 (>50) → 신뢰할 수 있는 패턴")
    print("   - win_rate 70%+ 이고 avg_R 0.8+ 인 조합 → 살려야 할 조합")
    print("   - win_rate <60% 이고 avg_R <0.3 인 조합 → 제거 후보")
    print("   - 개별 필터 ON vs FAIL 차이 큰 필터 → 중요도 높음")
    print("   - 차이 거의 없는 필터 → 제거 고려")
    print()
    print("🎯 다음 스텝:")
    print("   1. 상위 조합 식별 (예: VOL+SWEEP+ATR)")
    print("   2. 그 조합만 AND 로 강제하는 설정으로 재실행")
    print("   3. 성과 비교 → 실전 이식 결정")
    print("=" * 85)

