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
# ⭐ 트레이딩에 활용하는 캔들 윈도우: i-1봉 기준 과거 N개월(룩어헤드 0). 이 기간 내 생성된 OB/FVG만 후보.
#    (H4 24/7 기준 3개월 ≈ 540봉. expire_idx(생성+ZONE_MAX_AGE) 게이트를 이 시간윈도우로 대체.)
H4_TRADE_WINDOW_MONTHS = 3
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
    import os
    # 세션-로컬 캐시(누수검증 스테이지 간 동일 데이터 보장). STAGE4D_DLCACHE 지정 시 활성.
    _dlc = os.environ.get("STAGE4D_DLCACHE", "")
    _cache_fp = None
    if _dlc:
        os.makedirs(_dlc, exist_ok=True)
        _cache_fp = os.path.join(_dlc, f"{symbol}_{interval}.parquet")
        if os.path.exists(_cache_fp):
            return pd.read_parquet(_cache_fp)
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
    if _cache_fp is not None:
        out.to_parquet(_cache_fp)
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
    # SWEEP — ⭐ 엄밀화: 품질 스윕(유동성맵 + 침투 + 거절)만 인정 (qsweep_*).
    #   기존 pivot_sweep/recent_sweep(1틱 청산도 True) → add_liquidity_sweep_quality 로 정제됨.
    start = max(0, entry_idx - SWEEP_LOOKBACK_BARS)
    end = entry_idx
    if ("qsweep_high" in df_struct.columns) and ("qsweep_low" in df_struct.columns):
        if side == "long":
            qsw = df_struct.loc[start:end, "qsweep_low"].any()
        else:
            qsw = df_struct.loc[start:end, "qsweep_high"].any()
        tags["a_sweep"] = bool(qsw)
    else:
        # 폴백(품질컬럼 없을 때): 기존 정의
        if side == "long":
            pivot_sw = df_struct.loc[start:end, "pivot_sweep_low"].any()
            recent_sw = df_struct.loc[start:end, "recent_sweep_low"].any()
        else:
            pivot_sw = df_struct.loc[start:end, "pivot_sweep_high"].any()
            recent_sw = df_struct.loc[start:end, "recent_sweep_high"].any()
        tags["a_sweep"] = bool(pivot_sw or recent_sw)

    # VOLUME — ⭐broad: 존형성창(존생성-3 ~ 존생성) 최대거래량 / median(20) ≥ BROAD_VOL_RELVOL_MIN
    #   기존: 존봉 단일 / mean / 1.1배(스파이크 아님). → 변위참여도 + median(이상치robust) + 1.5배.
    tags["a_volume"] = False
    if "volume" in df_struct.columns:
        vwin_start = max(0, zone_created_idx - 3)
        bstart = max(0, zone_created_idx - VOLUME_AVG_WINDOW)
        if zone_created_idx > bstart:
            vmax = df_struct.loc[vwin_start:zone_created_idx, "volume"].max()
            vbase = df_struct.loc[bstart:zone_created_idx - 1, "volume"].median()
            if pd.notna(vbase) and vbase > 0 and pd.notna(vmax):
                tags["a_volume"] = bool((vmax / vbase) >= BROAD_VOL_RELVOL_MIN)

    # ─── Tier 구성 5개 (broad) ───
    pt = int(pre_total) if pd.notna(pre_total) else 0
    sc = int(sweep_count) if pd.notna(sweep_count) else 0
    sv = float(score) if pd.notna(score) else 0.0
    wv = wick_ratio_5

    tags["a_pre_total_ge4"]   = (pt >= 3)                       # ⭐ ge4 불가능(max=3) → ge3(강 confluence, 127건)
    tags["a_sweep_count_2_4"] = (sc >= BROAD_SWEEP_CNT_MIN)     # ⭐broad: 밴드(2~4) → 단조 ≥2
    tags["a_score_ge13"]      = (sv >= BROAD_SCORE_STRONG)      # ⭐broad: 절대 13 → 10(강)
    tags["a_wick_le_q1"]      = (wv is not None) and (not pd.isna(wv)) and (wv <= BROAD_WICK_MAX)  # ⭐broad 0.23→0.35
    tags["a_pre_total_ge1"]   = (pt >= 1)                       # 약 confluence 존재 (유지, broad)

    # ─── RP 구성 5개 ───
    reasons = str(structure_reasons) if structure_reasons is not None else ""
    reasons_set = set(r.strip() for r in reasons.split(",") if r.strip())

    # trend_align — ⭐broad: 정합 OR 중립(역행만 배제)
    h4_trend = df_struct.loc[entry_idx, "trend"] if "trend" in df_struct.columns else "neutral"
    _aligned = (side == "long" and h4_trend == "up") or (side == "short" and h4_trend == "down")
    _opposed = (side == "long" and h4_trend == "down") or (side == "short" and h4_trend == "up")
    tags["a_trend_align"] = bool(_aligned or (BROAD_TREND_INCL_NEUTRAL and not _opposed))

    # mss / overlap — 이진 존재(개념상 broad). 품질차원(돌파폭/겹침분율)은 구조내부지표라 후속.
    tags["a_mss"]     = ("bull_mss" in reasons_set) or ("bear_mss" in reasons_set)
    tags["a_overlap"] = ("bull_ob_fvg_overlap" in reasons_set) or \
                         ("bear_ob_fvg_overlap" in reasons_set)

    # fvg — ⭐broad: 존재 AND 임밸런스 크기(=존두께) ≥ BROAD_FVG_SIZE_ATR·ATR (미세 갭만 배제)
    _fvg_present = ("valid_bull_fvg" in reasons_set) or ("valid_bear_fvg" in reasons_set)
    if _fvg_present and pd.notna(atr_val) and atr_val > 0:
        _zsize = abs(zone_high - zone_low)
        tags["a_fvg"] = bool((_zsize / atr_val) >= BROAD_FVG_SIZE_ATR)
    else:
        tags["a_fvg"] = bool(_fvg_present)   # atr 없으면 존재만으로 (broad)

    # a_room — ⭐broad: 타겟까지 거리 ≥ BROAD_ROOM_RR_MIN·ATR (risk≈1ATR SL 근사)
    #   기존: risk=atr*0.08(자의적), RR≥2.8. → risk=ATR, room≥1.5·ATR(broad).
    a_room = False
    if pd.notna(atr_val) and atr_val > 0:
        zone_mid = (zone_high + zone_low) / 2.0
        if side == "long":
            tgt = df_struct.loc[entry_idx, "pd_high"] if "pd_high" in df_struct.columns else np.nan
            if pd.notna(tgt):
                a_room = (max(tgt - zone_mid, 0.0) / atr_val) >= BROAD_ROOM_RR_MIN
        else:
            tgt = df_struct.loc[entry_idx, "pd_low"] if "pd_low" in df_struct.columns else np.nan
            if pd.notna(tgt):
                a_room = (max(zone_mid - tgt, 0.0) / atr_val) >= BROAD_ROOM_RR_MIN
    tags["a_room"] = bool(a_room)

    # ════════════════════════════════════════════════════════════════════
    # ⭐ 신규축: 변동성/레짐 (3개) — 가격구조 SMC와 직교. OHLCV만 사용.
    #   전부 인덱스 ≤ entry_idx 만 읽음 → HONEST_STAGE=5 에서 i-1 정직봉 상속 → 룩어헤드 0.
    # ════════════════════════════════════════════════════════════════════
    ei = entry_idx
    _close = df_struct["close"].values.astype(float) if "close" in df_struct.columns else None
    _atrv  = df_struct["atr"].values.astype(float)   if "atr"   in df_struct.columns else None

    # a_efficiency — Kaufman 효율비(추세 vs 횡보). 높으면 추세 레짐.
    tags["a_efficiency"] = False
    if _close is not None and ei >= REG_EFF_N:
        seg = _close[ei - REG_EFF_N: ei + 1]            # [ei-N .. ei]
        denom = np.sum(np.abs(np.diff(seg)))
        if denom > 0:
            er = abs(seg[-1] - seg[0]) / denom
            tags["a_efficiency"] = bool(er >= REG_EFF_MIN)

    # a_bb_squeeze — 볼린저밴드 폭이 트레일링 분포 하위 = 변동성 압축(확장 임박)
    tags["a_bb_squeeze"] = False
    if _close is not None and ei >= (REG_BB_N + REG_BB_PCTL_WIN):
        def _bbw(j):
            s = _close[j - REG_BB_N + 1: j + 1]
            m = s.mean(); sd = s.std()
            return (2.0 * REG_BB_K * sd) / m if m > 0 else np.nan
        cur = _bbw(ei)
        hist = np.array([_bbw(j) for j in range(ei - REG_BB_PCTL_WIN, ei)])  # ei 미포함=과거만
        hist = hist[~np.isnan(hist)]
        if (not np.isnan(cur)) and len(hist) >= 20:
            tags["a_bb_squeeze"] = bool((hist < cur).mean() <= REG_BB_SQUEEZE_PCTL)

    # a_vol_expansion — ATR 백분위 ≥ 0.5 (변동성 확장 레짐). atr=트레일링 rolling14.
    tags["a_vol_expansion"] = False
    if _atrv is not None and ei >= REG_VOL_WIN:
        seg = _atrv[ei - REG_VOL_WIN: ei + 1]
        cur = _atrv[ei]
        seg = seg[~np.isnan(seg)]
        if len(seg) >= 20 and not np.isnan(cur):
            tags["a_vol_expansion"] = bool((seg < cur).mean() >= REG_VOL_PCTL)

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
            if touch_count > 1:
                return False   # ⭐ 조기종료(결과 불변): 2회 터치 즉시 not-fresh
    return touch_count <= 1


def evaluate_zone_lifespan(df_struct, zone_created_idx, zone_low, zone_high,
                           orig_side, decision_idx):
    """존을 S/R-flip 규칙으로 재구성. 룩어헤드 0: (zone_created_idx, decision_idx] 만 스캔.

    규칙(사용자 확정):
      - 터치 = 윅 진입(high>=zlo and low<=zhi)
      - 거절/돌파는 '종가'로만 판정
      - respect(거절) → 살아있음(현 역할 유지)
      - break(돌파) → 사망(broken, flip 대기)
      - broken 후 반대역할 거절(flip 확인) → 다시 살아있음(역할·매매방향 반전)
      - 현재 상태 = '가장 최근 이벤트' 기준
    역할 초기값: orig_side=="short"(bearish OB)=저항, "long"(bullish)=지지.

    Returns dict:
      alive(bool), side("long"=지지/"short"=저항, 사망시 None),
      flipped(bool, 현 방향이 원래와 반대인가), role("res"/"sup"),
      n_respect, n_break, n_flip
    """
    zlo = min(zone_low, zone_high)
    zhi = max(zone_low, zone_high)
    role = "res" if orig_side == "short" else "sup"
    broken = False
    n_respect = n_break = n_flip = 0

    start = int(zone_created_idx) + 1
    end = int(decision_idx)
    if start <= end:
        h = df_struct["high"].values
        l = df_struct["low"].values
        c = df_struct["close"].values
        for t in range(start, end + 1):
            touch = (h[t] >= zlo) and (l[t] <= zhi)
            if not broken:
                if role == "res":
                    if c[t] > zhi:                       # 저항 상방 돌파
                        broken = True; n_break += 1
                    elif touch and c[t] < zlo:           # 저항 거절
                        n_respect += 1
                else:  # sup
                    if c[t] < zlo:                       # 지지 하방 돌파
                        broken = True; n_break += 1
                    elif touch and c[t] > zhi:           # 지지 거절
                        n_respect += 1
            else:  # broken → flip 감시
                if role == "res":                        # 돌파된 저항 → 지지로 flip?
                    if touch and c[t] > zhi:             # 되돌아와 위로 거절 = 지지 확정
                        role = "sup"; broken = False; n_flip += 1
                else:                                    # 돌파된 지지 → 저항으로 flip?
                    if touch and c[t] < zlo:             # 되돌아와 아래로 거절 = 저항 확정
                        role = "res"; broken = False; n_flip += 1

    alive = not broken
    cur_side = ("short" if role == "res" else "long") if alive else None
    flipped = bool(alive and (cur_side != orig_side))
    return {"alive": alive, "side": cur_side, "flipped": flipped, "role": role,
            "n_respect": n_respect, "n_break": n_break, "n_flip": n_flip}


def advance_zone_lifespan(s, h_arr, l_arr, c_arr, upto_idx):
    """evaluate_zone_lifespan 의 *증분* 버전. 구조체 s 에 _ls_* 상태를 누적 →
    매 봉 1칸씩만 전진(O(1) 분할상환). upto_idx(=i-1)까지만 읽음 → 룩어헤드 0.
    Returns: (alive, side, flipped)
    """
    if "_ls_pos" not in s:
        s["_ls_orig"] = s["type"]
        s["_ls_role"] = "res" if s["type"] == "short" else "sup"
        s["_ls_broken"] = False
        s["_ls_pos"] = int(s["zone_created_idx"])
    zlo = s["zone_low"]; zhi = s["zone_high"]
    if zlo > zhi:
        zlo, zhi = zhi, zlo
    role = s["_ls_role"]; broken = s["_ls_broken"]
    t0 = int(s["_ls_pos"]) + 1
    for t in range(t0, int(upto_idx) + 1):
        touch = (h_arr[t] >= zlo) and (l_arr[t] <= zhi)
        if not broken:
            if role == "res":
                if c_arr[t] > zhi:
                    broken = True
                elif touch and c_arr[t] < zlo:
                    pass
            else:
                if c_arr[t] < zlo:
                    broken = True
                elif touch and c_arr[t] > zhi:
                    pass
        else:
            if role == "res":
                if touch and c_arr[t] > zhi:
                    role = "sup"; broken = False
            else:
                if touch and c_arr[t] < zlo:
                    role = "res"; broken = False
    s["_ls_role"] = role
    s["_ls_broken"] = broken
    s["_ls_pos"] = max(int(s["_ls_pos"]), int(upto_idx))
    alive = not broken
    side = ("short" if role == "res" else "long") if alive else None
    flipped = bool(alive and side != s["_ls_orig"])
    return alive, side, flipped


def add_liquidity_sweep_quality(df, eqh_lookback=40, eqh_min_touches=2,
                                pen_atr_floor=0.05, strong_pen_atr=0.25,
                                eqh_tol_atr=0.15):
    """
    ⭐ a_sweep 엄밀화 (BROAD 버전 — AND 교집합 전제).
    설계: 축1(현상 정확성)은 유지, 축2(임계값)는 느슨하게 = 진짜 스윕 high-recall.

    qsweep_high/low = True 조건:
      (1) 직전 pivot(last_pivot) 청산 + 종가 되돌림 (high>L & close<L  /  low<L & close>L)
          → close<L 자체가 '레벨 거절'이라 별도 거절% 요구는 제거(broad).
      (2) 노이즈 플로어만:  침투폭 >= pen_atr_floor * ATR  (0.05 — 1틱/부동소수점만 배제)
      (3) 유동성 풀 (관대한 OR, 셋 중 하나):
            - EQH/EQL : 최근 pivot >= eqh_min_touches 개가 ±eqh_tol_atr·ATR 군집
            - PDH/PDL : 청산 레벨이 직전기간 극값
            - 강한 스윕 : 침투폭 >= strong_pen_atr * ATR (고립 레벨이라도 결정적이면 인정)
      → 무작위 약한 중간 윅만 배제, 진짜 스윕은 폭넓게 통과. tight화는 AND가 담당.
    ※ 모든 knob 가 인자 = broad↔tight 다이얼. 더 broad: pen_atr_floor↓, strong_pen_atr↓, eqh_tol_atr↑.
    """
    n = len(df)
    qsh = np.zeros(n, dtype=bool)
    qsl = np.zeros(n, dtype=bool)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    atr = df["atr"].values.astype(float)
    lph = df["last_pivot_high"].values.astype(float)
    lpl = df["last_pivot_low"].values.astype(float)
    piv_h = df["pivot_high"].values.astype(float)
    piv_l = df["pivot_low"].values.astype(float)
    pdh = df["pd_high"].values.astype(float)
    pdl = df["pd_low"].values.astype(float)

    for i in range(eqh_lookback, n):
        a = atr[i]
        if not (a > 0):
            continue
        # ── HIGH side (short 용 buy-side liquidity) ──
        L = lph[i]
        if not np.isnan(L) and high[i] > L and close[i] < L:   # 청산 + 종가 거절(broad)
            pen = high[i] - L
            if pen >= pen_atr_floor * a:                        # 노이즈 플로어만
                tol = max(eqh_tol_atr * a, abs(L) * 0.0005)
                w = piv_h[i - eqh_lookback:i]
                w = w[~np.isnan(w)]
                touches = int(np.sum(np.abs(w - L) <= tol))
                is_pool = (touches >= eqh_min_touches) \
                          or (not np.isnan(pdh[i]) and L >= pdh[i] - tol) \
                          or (pen >= strong_pen_atr * a)
                qsh[i] = bool(is_pool)
        # ── LOW side (long 용 sell-side liquidity) ──
        Lo = lpl[i]
        if not np.isnan(Lo) and low[i] < Lo and close[i] > Lo:
            pen = Lo - low[i]
            if pen >= pen_atr_floor * a:
                tol = max(eqh_tol_atr * a, abs(Lo) * 0.0005)
                w = piv_l[i - eqh_lookback:i]
                w = w[~np.isnan(w)]
                touches = int(np.sum(np.abs(w - Lo) <= tol))
                is_pool = (touches >= eqh_min_touches) \
                          or (not np.isnan(pdl[i]) and Lo <= pdl[i] + tol) \
                          or (pen >= strong_pen_atr * a)
                qsl[i] = bool(is_pool)

    df["qsweep_high"] = qsh
    df["qsweep_low"] = qsl
    return df


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

    # ⭐ 품질 스윕(유동성맵 기반) 컬럼 추가 — a_sweep 엄밀화용
    df = add_liquidity_sweep_quality(df)

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

    # ⭐ [HONEST] 단계별 룩어헤드 정직화 env-gate (누적). 0=before(현행/누수포함)
    #   1:S0 zone생성당봉 진입금지  2:S1 run_potential·trend방향·atr(SL)  i-1
    #   3:S2 pre_entry_confluence·wick  i-1   4:S3 market_state·h1_choch  i-1
    #   5:S4 12 trade_tags(로그전용)  i-1
    #   ※ touched(지정가 터치)·freshness(이미 end=i-1)는 전 단계 불변 = 과교정 금지
    import os as _os_h
    _HONEST = int(_os_h.environ.get("HONEST_STAGE", "0"))
    def _sb(idx, need):  # signal-bar: 해당 단계 이상이면 직전 종가확정봉(i-1), 아니면 i
        return idx - 1 if _HONEST >= need else idx

    # ⭐ [ATOM_OR] 12원자 OR 진입게이트 — 실제 백테스트(단일포지션 슬롯 재배치 반영, post-hoc 아님).
    #   ATOM_OR_LIST="a_volume,a_trend_align,~a_room" → OR(리터럴) 하나라도 True 여야 진입.
    #   "~atom"=음극(NOT atom). 빈값=게이트 없음(현행). 정직값 쓰려면 HONEST_STAGE=5 와 병행.
    _ATOM_OR_RAW = [x.strip() for x in _os_h.environ.get("ATOM_OR_LIST", "").split(",") if x.strip()]
    def _atom_or_pass(tags):
        if not _ATOM_OR_RAW:
            return True
        for _lit in _ATOM_OR_RAW:
            _neg = _lit.startswith("~")
            _v = bool(tags.get(_lit[1:] if _neg else _lit, False))
            if (not _v) if _neg else _v:
                return True
        return False

    # ⭐ [ATOM_AND] 지정 리터럴이 "전부 True" 여야 진입 (AND 게이트). "~atom"=음극(NOT).
    #   ATOM_AND_LIST="~a_volume,~a_sweep,~a_fvg" → 셋 다 만족해야만 진입.
    #   빈값=AND 조건 없음(통과). 실값 atoms, _ti=정직봉. 단일포지션 슬롯 재배치 반영(post-hoc 아님).
    _ATOM_AND_RAW = [x.strip() for x in _os_h.environ.get("ATOM_AND_LIST", "").split(",") if x.strip()]
    def _atom_and_pass(tags):
        if not _ATOM_AND_RAW:
            return True
        for _lit in _ATOM_AND_RAW:
            _neg = _lit.startswith("~")
            _v = bool(tags.get(_lit[1:] if _neg else _lit, False))
            _hit = (not _v) if _neg else _v
            if not _hit:        # 하나라도 불만족이면 AND 실패
                return False
        return True

    def _track_skip(reason):
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    _ts = df_struct["timestamp"]   # ⭐ 3개월 윈도우 비교용 (positional .iat 접근)
    _h = df_struct["high"].values.astype(float)   # ⭐ 증분 수명 추적용
    _l = df_struct["low"].values.astype(float)
    _c = df_struct["close"].values.astype(float)
    i = 200
    while i < len(df_struct) - 1:
        row = df_struct.iloc[i]

        if i in structures_by_zone_created:
            active_structures.extend(structures_by_zone_created[i])

        # ⭐ 수명은 S/R-flip 상태로만 결정(나이 하드컷 제거).
        #   미돌파존(미테스트 or 지지/저항 유지) = 나이 무관 생존. 돌파-noflip만 이번 봉 후보 제외
        #   (이후 flip 시 부활). 실제 alive/dead 판정은 advance_zone_lifespan(scored_active)에서.
        active_structures = [
            s for s in active_structures
            if (not s["used"])
            and (s["score"] >= RELAX_MIN_SCORE)  # 거친 사전필터(원래 점수방식 유지)
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
        h4_market_state = df_struct.loc[_sb(i, 4), "market_state"]  # S3: 신호봉
        pre_sweep_v = pre_fvg_v = pre_ob_v = pre_total_v = 0
        wick_ratio_v = 0.0

        scored_active = []
        for s in active_structures:
            # ── S/R-flip 수명 재구성 (증분, 룩어헤드 0: i-1까지만 스캔) ──
            _alive, _eff_side, _flipped = advance_zone_lifespan(s, _h, _l, _c, i - 1)
            if not _alive:
                continue   # 돌파-noflip = 사망 → 이번 봉 후보 제외 (윈도우 내 재flip 시 다음 봉 부활)
            fresh_bonus, fresh_reasons = evaluate_freshness_at_entry(df_struct, s, i)
            eff_score = float(s["score"]) + fresh_bonus
            if eff_score < MIN_SCORE:   # ⭐ 7.5 게이트 — flip/비flip 동일(존 품질 유지: 강한 존만 flip 매매)
                continue
            if _flipped:
                # 같은 OB/FVG존, 역할·방향만 반전(breaker). score 유지.
                # 방향특정 요소는 SL 기준뿐 → sweep_ref를 존 엣지로(가격행동).
                s = dict(s)
                s["type"] = _eff_side
                s["sweep_ref"] = s["zone_high"] if _eff_side == "short" else s["zone_low"]
                s["flipped"] = True
            else:
                s["flipped"] = False
            scored_active.append((s, eff_score, fresh_reasons))

        scored_active.sort(key=lambda x: (-x[1], x[0]["zone_created_idx"]))

        for s, eff_score, fresh_reasons in scored_active:
            if _HONEST >= 1 and i <= s["zone_created_idx"]:  # S0: zone 생성당봉 진입 금지(동어반복 차단)
                continue
            touched = (row["high"] >= s["zone_low"]) and (row["low"] <= s["zone_high"])
            if not touched:
                continue

            # ⭐⭐ Stage 4D: 12 atomic 태그 계산 (모두 로그 전용, 게이트 아님)
            # pre_total / sweep_count / wick_ratio 는 structure 별로 계산된 값
            # 이 시점에선 아직 확정 안 되었으므로 임시 0 또는 structure field 이용
            # (정확한 값은 simulate 단계에서 다시 덮어씀)
            _ti = _sb(i, 5)  # S4: trade_tags(로그) 신호봉
            _atr_here = df_struct.loc[_ti, "atr"] if pd.notna(df_struct.loc[_ti, "atr"]) else 0.0
            _atoms = compute_trade_tags(
                df_struct=df_struct,
                entry_idx=_ti, zone_created_idx=s["zone_created_idx"],
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
                entry_idx=_ti, zone_created_idx=s["zone_created_idx"],
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
            _s1 = _sb(i, 2)  # S1 신호봉: run_potential·atr(SL)·trend방향
            atr_val = df_struct.loc[_s1, "atr"] if pd.notna(df_struct.loc[_s1, "atr"]) else 0.0

            rp, rp_tags = get_run_potential(df_struct, _s1, s)
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
                if df_struct.loc[_s1, "trend"] == "up":  # S1: 방향게이트 신호봉
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
                    df_struct, df_h1, _sb(i, 3), s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_v = compute_wick_ratio_5(df_struct, df_h1, _sb(i, 3), "short", WICK_LOOKBACK_BARS)

                h1_confirm_short = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[_sb(i, 4), "timestamp"],
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

                if _ATOM_OR_RAW or _ATOM_AND_RAW:  # 원자 진입게이트 (실값 atoms, _ti=정직봉)
                    _gtags = compute_trade_tags(
                            df_struct=df_struct, entry_idx=_ti, zone_created_idx=s["zone_created_idx"],
                            zone_low=s["zone_low"], zone_high=s["zone_high"], side="short",
                            pre_total=pre_total_v, sweep_count=pre_sweep_v, score=float(eff_score),
                            wick_ratio_5=wick_ratio_v, structure_reasons=s.get("reasons", ""), atr_val=_atr_here)
                    if not _atom_or_pass(_gtags):
                        _track_skip("atom_or_gate_fail")
                        continue
                    if not _atom_and_pass(_gtags):
                        _track_skip("atom_and_gate_fail")
                        continue

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
                if df_struct.loc[_s1, "trend"] == "down":  # S1: 방향게이트 신호봉
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
                    df_struct, df_h1, _sb(i, 3), s["zone_low"], s["zone_high"], PRE_ENTRY_LOOKBACK_LTF_BARS
                )
                wick_ratio_v = compute_wick_ratio_5(df_struct, df_h1, _sb(i, 3), "long", WICK_LOOKBACK_BARS)

                h1_confirm_long = has_recent_h1_choch(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[_sb(i, 4), "timestamp"],
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

                if _ATOM_OR_RAW or _ATOM_AND_RAW:  # 원자 진입게이트 (실값 atoms, _ti=정직봉)
                    _gtags = compute_trade_tags(
                            df_struct=df_struct, entry_idx=_ti, zone_created_idx=s["zone_created_idx"],
                            zone_low=s["zone_low"], zone_high=s["zone_high"], side="long",
                            pre_total=pre_total_v, sweep_count=pre_sweep_v, score=float(eff_score),
                            wick_ratio_5=wick_ratio_v, structure_reasons=s.get("reasons", ""), atr_val=_atr_here)
                    if not _atom_or_pass(_gtags):
                        _track_skip("atom_or_gate_fail")
                        continue
                    if not _atom_and_pass(_gtags):
                        _track_skip("atom_and_gate_fail")
                        continue

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
            "flipped": bool(used_structure.get("flipped", False)),  # ⭐ S/R-flip존 여부
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
            "zone_low": float(used_structure["zone_low"]),
            "zone_high": float(used_structure["zone_high"]),
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

                # ⭐⭐ Stage 4D: Tier / RP 계산은 유지 (로그용), 단 risk 에는 전혀 반영 안 함
                pre_total_v = int(row.get("pre_entry_total", 0)) if pd.notna(row.get("pre_entry_total", 0)) else 0
                sweep_v = int(row.get("pre_entry_sweep", 0)) if pd.notna(row.get("pre_entry_sweep", 0)) else 0
                score_v = float(row.get("score", 0))
                wick_v = row.get("wick_ratio_5", None)
                if pd.isna(wick_v): wick_v = None
                rp_v = int(row.get("run_potential", 0)) if pd.notna(row.get("run_potential", 0)) else 0

                # tier_label 은 로그용 (risk 에 안 씀)
                tier_label, _tier_mult_ignored, rp_action = classify_tier_v19b_rp_boost(
                    pre_total_v, sweep_v, score_v, wick_v, rp_v
                )

                # Stage 4D: 모든 risk multiplier 1.0 고정
                tier_mult = 1.0                # Tier 곱 제거
                risk_pct = risk_pct_base * 1.0 * risk_multiplier  # = risk_pct_base
                effective_notional_cap = MAX_NOTIONAL_MULT  # 3.0 고정 (S/A cap FREE 없음)
                sa_cap_tag = "capFixed"

                # Stage 4D: Tier D skip 제거 — 모든 거래 수용
                #   (기존 tier_mult <= 0 이면 skip 이었는데 Stage 4D 는 risk 고정이므로 전부 진입)

                # 12 atomic 재계산 (simulate 시점에서 정확한 값들로)
                # candidates 단계에서 structure_reasons_raw / atr_at_entry 저장해뒀음
                _struct_reasons_raw = str(row.get("structure_reasons_raw", row.get("reasons", "")))
                _atr_at_entry = float(row.get("atr_at_entry", 0.0)) if pd.notna(row.get("atr_at_entry", 0.0)) else 0.0
                # 재계산은 df_struct 에 접근이 필요하므로 candidates_dict 에서 참조
                _df_struct_here = candidates_dict[symbol].get("df_h4")
                if _df_struct_here is None:
                    # 하위 호환: 기존 스키마에 df_h4 없으면 candidates 시점 sweep/volume 그대로 사용
                    _atoms_final = {
                        "a_sweep":            bool(row.get("tag_sweep", False)),
                        "a_volume":           bool(row.get("tag_volume", False)),
                        "a_pre_total_ge4":    (pre_total_v >= 3),
                        "a_sweep_count_2_4":  (2 <= sweep_v <= 4),
                        "a_score_ge13":       (score_v >= 13.0),
                        "a_wick_le_q1":       (wick_v is not None and not pd.isna(wick_v) and wick_v <= WICK_RATIO_5_Q1_THRESHOLD),
                        "a_pre_total_ge1":    (pre_total_v >= 1),
                        "a_trend_align":      False,   # df_struct 없어서 재계산 불가
                        "a_mss":              ("bull_mss" in _struct_reasons_raw) or ("bear_mss" in _struct_reasons_raw),
                        "a_fvg":              ("valid_bull_fvg" in _struct_reasons_raw) or ("valid_bear_fvg" in _struct_reasons_raw),
                        "a_overlap":          ("bull_ob_fvg_overlap" in _struct_reasons_raw) or ("bear_ob_fvg_overlap" in _struct_reasons_raw),
                        "a_room":             False,
                    }
                else:
                    # entry_idx 찾기
                    try:
                        _entry_ts = row["entry_time"]
                        _match = _df_struct_here.index[_df_struct_here["timestamp"] == _entry_ts]
                        if len(_match) > 0:
                            _entry_idx_sim = int(_match[0])
                            _zone_created_idx = int(row.get("zone_created_idx", _entry_idx_sim))
                            # [HONEST] 로그원자 정직화: a_sweep/a_trend_align/a_room 은 entry_idx(현재봉)를
                            #   읽으므로 simulate 재계산에서도 직전 종가확정봉(i-1)로 차단.
                            #   a_volume 은 zone_created_idx 사용 → 영향 없음. (S4=5 이상에서 적용)
                            import os as _os_atom
                            _atom_idx = _entry_idx_sim - 1 if int(_os_atom.environ.get("HONEST_STAGE", "0")) >= 5 else _entry_idx_sim
                            # ⭐ 진짜 zone 경계 사용 (candidate row 에서 plumbing). 없으면 근사 폴백.
                            _zlo = float(row.get("zone_low", float(row["entry"]) - 1e-9))
                            _zhi = float(row.get("zone_high", float(row["entry"]) + 1e-9))
                            if _zhi <= _zlo:   # 안전장치
                                _zlo, _zhi = float(row["entry"]) - 1e-9, float(row["entry"]) + 1e-9
                            _atoms_final = compute_trade_tags(
                                df_struct=_df_struct_here,
                                entry_idx=_atom_idx,
                                zone_created_idx=_zone_created_idx,
                                zone_low=_zlo,
                                zone_high=_zhi,
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
                        # fallback — Tier/RP 원자만 수학적으로 판정, sweep/volume/trend_align/room 은 candidates 값 사용
                        _atoms_final = {
                            "a_sweep":            bool(row.get("tag_sweep", False)),
                            "a_volume":           bool(row.get("tag_volume", False)),
                            "a_pre_total_ge4":    (pre_total_v >= 3),
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
                    "structure_reasons_raw": _struct_reasons_raw,
                    # ⭐⭐ Stage 4D: 12 atomic 태그 (분석의 본체)
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
                    "a_efficiency":       bool(_atoms_final.get("a_efficiency", False)),
                    "a_bb_squeeze":       bool(_atoms_final.get("a_bb_squeeze", False)),
                    "a_vol_expansion":    bool(_atoms_final.get("a_vol_expansion", False)),
                    # ⭐ 시너지 분석 편의 컬럼 — 12원자 중 True 개수 / True 목록
                    "n_atoms_true": int(sum(bool(_atoms_final.get(_k, False)) for _k in (
                        "a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4",
                        "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align",
                        "a_mss", "a_fvg", "a_overlap", "a_room"))),
                    "atoms_true": (",".join([_k for _k in (
                        "a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4",
                        "a_score_ge13", "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align",
                        "a_mss", "a_fvg", "a_overlap", "a_room")
                        if bool(_atoms_final.get(_k, False))]) or "(none)"),
                    # 하위 호환 (기존 CSV 스키마 유지)
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
# ★★★ Stage 4D: candidates 생성 (atomic decomposition 실험) ★★★
# =========================================================
print()
print("=" * 75)
print("[Stage 4D] candidates 생성 — Atomic Decomposition (모든 risk mult 1.0)")
print("=" * 75)
print("  진입 조건 = MIN_SCORE 7.5 만 (모든 게이트 해제)")
print("  Tier / RP 계산은 유지, 단 risk 에 전혀 미반영")
print("  12 atomic 태그 전부 로그")

USE_FILTER_GROUPS = False
USE_VOLUME_FILTER = False
USE_LIQUIDITY_SWEEP_CONF = False
USE_D1_TREND_FILTER = False
USE_PULLBACK_DEPTH = False
USE_ATR_FILTER = False

try:
    candidates_results_stage4d = _parallel_map(
        _generate_candidates_single, SYMBOLS_TO_PREPARE,
        task_name="candidates Stage 4D", io_bound=False,
    )
    candidates_dict_stage4d = dict(candidates_results_stage4d)
except Exception as e:
    print(f"  candidates 병렬 실패: {e}, 순차 처리")
    candidates_dict_stage4d = {}
    for sym in SYMBOLS_TO_PREPARE:
        candidates_dict_stage4d[sym] = generate_candidates_from_prepared(prepared_data[sym])

total_stage4d = sum(len(candidates_dict_stage4d[s]["candidates"]) for s in SYMBOLS_TO_PREPARE)
print(f"\n  TOTAL candidates (Stage 4D): {total_stage4d}")
print("\n[OK] candidates 생성 완료 (Stage 4D). risk 는 simulate 단계에서 전부 1.0 고정.")



# =========================================================
# ★★★ 셀 3: 단일 시나리오 백테스트 실행 (Stage 4D) ★★★
# =========================================================
import os
OUTDIR = os.environ.get("STAGE4D_OUTDIR", "stage4d_outputs")
os.makedirs(OUTDIR, exist_ok=True)
print(f"\n[OUTDIR] {os.path.abspath(OUTDIR)}")

STAGE4D_CASE = {
    "name":  "stage4d",
    "label": "Stage 4D: Atomic Decomposition (all risk mult = 1.0)",
    "risk_mult": 1.0,
    "candidates": candidates_dict_stage4d,
}

print()
print("#" * 75)
print(f"# Stage 4D 백테스트 시작: {STAGE4D_CASE['label']}")
print("#" * 75)

res = simulate_scenario_v19b_rpboost(
    scenario=SCENARIO_MULTI,
    candidates_dict=STAGE4D_CASE["candidates"],
    risk_multiplier=STAGE4D_CASE["risk_mult"],
)

monthly_report = print_scenario_summary(res)

prefix = "stage4d"
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
    "scenario":  STAGE4D_CASE["name"],
    "label":     STAGE4D_CASE["label"],
    "trades":    len(trades),
    "win%":      wr_overall,
    "PF":        pf_overall,
    "avg_R":     avgr_overall,
    "MDD%":      mdd_overall,
    "Return_%":  return_pct,
    "retirement":      retirement_month,
    "retirement_months": months_taken if months_taken else "X",
}])
summary_df.to_csv(f"{OUTDIR}/stage4d_overall_summary.csv", index=False)

print()
print("=" * 75)
print("[Stage 4D] 전체 성과")
print("=" * 75)
print(f"  Trades   : {len(trades)}")
print(f"  Win%     : {wr_overall:.2f}%")
print(f"  PF       : {pf_overall:.3f}")
print(f"  avg_R    : {avgr_overall:.3f}")
print(f"  MDD%     : {mdd_overall:.2f}%")
print(f"  Return%  : {return_pct:.1f}%")
print(f"  retirement : {retirement_month} ({months_taken if months_taken else 'X'}m)")


# =========================================================
# ★★★ Stage 4D: ATOMIC DECOMPOSITION 심층 분석 (8개 산출물) ★★★
# =========================================================
print()
print("#" * 75)
print("# Stage 4D Atomic Decomposition 분석")
print("#" * 75)

tdf = res["trades"].copy()

# 12 atomic 컬럼
ATOMS_ALL = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
ATOMS_TIER = ["a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
              "a_wick_le_q1", "a_pre_total_ge1"]
ATOMS_RP   = ["a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
ATOMS_SIG  = ["a_sweep", "a_volume"]

if len(tdf) == 0:
    print("[WARN] 거래 0건 — 분석 불가")
else:
    for c in ATOMS_ALL + ["tier", "run_potential"]:
        if c not in tdf.columns:
            tdf[c] = False if c.startswith("a_") else ""

    def _pf_of(sub):
        if len(sub) == 0:
            return 0.0
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

    # ──────────────────────────────────────────────────────
    # (1) atom_solo_effect.csv — 각 원자 PASS vs FAIL
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[1] atom_solo_effect — 12 atomic PASS vs FAIL (Delta PF = 원자의 alpha)")
    print("=" * 95)
    print(f"{'atom':<22} {'status':<6} {'trades':>7} {'win%':>7} {'avg_R':>7} "
          f"{'PF':>7} {'total $':>14}")
    print("-" * 95)

    solo_rows = []
    for c in ATOMS_ALL:
        st_pass = _stats(tdf[tdf[c] == True])
        st_fail = _stats(tdf[tdf[c] == False])
        delta_pf = st_pass["PF"] - st_fail["PF"]
        solo_rows.append({"atom": c, "status": "PASS", "delta_PF": delta_pf, **st_pass})
        solo_rows.append({"atom": c, "status": "FAIL", "delta_PF": delta_pf, **st_fail})
        print(f"{c:<22} {'PASS':<6} {st_pass['trades']:>7} "
              f"{st_pass['win_pct']:>6.2f}% {st_pass['avg_R']:>7.3f} "
              f"{st_pass['PF']:>7.3f} {st_pass['total_pnl']:>14,.0f}")
        print(f"{c:<22} {'FAIL':<6} {st_fail['trades']:>7} "
              f"{st_fail['win_pct']:>6.2f}% {st_fail['avg_R']:>7.3f} "
              f"{st_fail['PF']:>7.3f} {st_fail['total_pnl']:>14,.0f}")
        print(f"{'  -> delta_PF':<22} {delta_pf:>+7.3f}")

    solo_df = pd.DataFrame(solo_rows).round(4)
    solo_df.to_csv(f"{OUTDIR}/atom_solo_effect.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (2) sweep_vol_pivot.csv — SWEEP+VOL 기준 나머지 atomic 추가 시 PF 변화
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[2] sweep_vol_pivot — SWEEP+VOLUME 기준 나머지 10 atomic 추가 시 효과")
    print("=" * 95)
    sv_base = tdf[(tdf["a_sweep"] == True) & (tdf["a_volume"] == True)]
    base_st = _stats(sv_base)
    print(f"  [BASE] SWEEP+VOLUME 통과: {base_st['trades']}t, "
          f"Win {base_st['win_pct']:.2f}%, PF {base_st['PF']:.3f}, "
          f"total ${base_st['total_pnl']:,.0f}")
    print("-" * 95)
    print(f"{'add_atom':<22} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'PF_delta':>9} {'total $':>14}")
    print("-" * 95)

    pivot_rows = [{"add_atom": "BASE_SV_ONLY", **base_st, "PF_delta": 0.0}]
    for c in ATOMS_ALL:
        if c in ATOMS_SIG:
            continue
        sub = sv_base[sv_base[c] == True]
        st = _stats(sub)
        delta = st["PF"] - base_st["PF"]
        pivot_rows.append({"add_atom": c, **st, "PF_delta": delta})
        print(f"{c:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {delta:>+9.3f} {st['total_pnl']:>14,.0f}")

    pivot_df = pd.DataFrame(pivot_rows).round(4)
    pivot_df.to_csv(f"{OUTDIR}/sweep_vol_pivot.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (3) tier_decomposition.csv — Tier 구성 5 atomic + 원본 Tier 판정 비교
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[3] tier_decomposition — Tier 구성 5 atomic 기여도 + 원본 Tier 판정")
    print("=" * 95)
    print(f"{'group':<22} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>14}")
    print("-" * 95)

    td_rows = []
    # Tier 구성 원자별
    for c in ATOMS_TIER:
        sub = tdf[tdf[c] == True]
        st = _stats(sub)
        td_rows.append({"group_type": "atomic_PASS", "group": c, **st})
        print(f"{c:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    # 원본 Tier 판정
    print("-" * 95)
    for t in ["S", "A", "B", "C", "D"]:
        sub = tdf[tdf["tier"] == t]
        st = _stats(sub)
        td_rows.append({"group_type": "original_tier", "group": t, **st})
        print(f"{'tier='+t:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    td_df = pd.DataFrame(td_rows).round(4)
    td_df.to_csv(f"{OUTDIR}/tier_decomposition.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (4) rp_decomposition.csv — RP 구성 5 atomic 기여도 + side 분리
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[4] rp_decomposition — RP 구성 5 atomic (LONG / SHORT / ALL)")
    print("=" * 95)
    print(f"{'side':<6} {'atom':<18} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'total $':>14}")
    print("-" * 95)

    rpd_rows = []
    for side_val in ("ALL", "long", "short"):
        side_sub = tdf if side_val == "ALL" else tdf[tdf["side"] == side_val]
        for c in ATOMS_RP:
            sub = side_sub[side_sub[c] == True]
            st = _stats(sub)
            rpd_rows.append({"side": side_val, "atom": c, **st})
            print(f"{side_val:<6} {c:<18} {st['trades']:>7} "
                  f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
                  f"{st['total_pnl']:>14,.0f}")

    rpd_df = pd.DataFrame(rpd_rows).round(4)
    rpd_df.to_csv(f"{OUTDIR}/rp_decomposition.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (5) rp_level_analysis.csv — RP0 vs RP1 vs RP2+ 세분
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[5] rp_level_analysis — RP0 / RP1 / RP2+ 세분 (side 별)")
    print("=" * 95)

    rpl_rows = []
    rp_buckets = [
        ("RP0",   lambda r: r == 0),
        ("RP1",   lambda r: r == 1),
        ("RP2",   lambda r: r == 2),
        ("RP3",   lambda r: r == 3),
        ("RP4+",  lambda r: r >= 4),
        ("RP_0_only",  lambda r: r == 0),
        ("RP_0_or_1",  lambda r: r in (0, 1)),
        ("RP_ge_2",    lambda r: r >= 2),
    ]
    print(f"{'side':<6} {'bucket':<14} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'avg_R':>7} {'total $':>14}")
    print("-" * 95)
    for side_val in ("ALL", "long", "short"):
        side_sub = tdf if side_val == "ALL" else tdf[tdf["side"] == side_val]
        for bname, cond in rp_buckets:
            sub = side_sub[side_sub["run_potential"].apply(cond)]
            st = _stats(sub)
            rpl_rows.append({"side": side_val, "bucket": bname, **st})
            print(f"{side_val:<6} {bname:<14} {st['trades']:>7} "
                  f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
                  f"{st['avg_R']:>7.3f} {st['total_pnl']:>14,.0f}")

    rpl_df = pd.DataFrame(rpl_rows).round(4)
    rpl_df.to_csv(f"{OUTDIR}/rp_level_analysis.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (6) side_x_atom.csv — LONG/SHORT × 12 atomic
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[6] side_x_atom — LONG / SHORT 에서 각 원자의 PASS 효과")
    print("=" * 95)
    print(f"{'side':<6} {'atom':<22} {'trades_PASS':>11} {'win% PASS':>10} "
          f"{'PF PASS':>8} {'PF FAIL':>8} {'delta_PF':>9}")
    print("-" * 95)

    sxa_rows = []
    for side_val in ("long", "short"):
        side_sub = tdf[tdf["side"] == side_val]
        for c in ATOMS_ALL:
            st_p = _stats(side_sub[side_sub[c] == True])
            st_f = _stats(side_sub[side_sub[c] == False])
            delta = st_p["PF"] - st_f["PF"]
            sxa_rows.append({
                "side": side_val, "atom": c,
                "trades_PASS": st_p["trades"], "win_pct_PASS": st_p["win_pct"],
                "PF_PASS": st_p["PF"], "total_pnl_PASS": st_p["total_pnl"],
                "trades_FAIL": st_f["trades"], "PF_FAIL": st_f["PF"],
                "delta_PF": delta,
            })
            print(f"{side_val:<6} {c:<22} {st_p['trades']:>11} "
                  f"{st_p['win_pct']:>9.2f}% {st_p['PF']:>8.3f} "
                  f"{st_f['PF']:>8.3f} {delta:>+9.3f}")

    sxa_df = pd.DataFrame(sxa_rows).round(4)
    sxa_df.to_csv(f"{OUTDIR}/side_x_atom.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (7) top_combo_analysis.csv — 2개 & 3개 atomic 조합 brute-force 탐색 상위 30
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[7] top_combo_analysis — 2-3 atomic 조합 brute-force 탐색 (PF 상위 30)")
    print("=" * 95)

    from itertools import combinations
    MIN_TRADES_COMBO = 30   # 표본 신뢰를 위해 최소 30건 이상 조합만

    combo_rows = []
    for size in (2, 3):
        for atoms_sub in combinations(ATOMS_ALL, size):
            mask = pd.Series(True, index=tdf.index)
            for a in atoms_sub:
                mask = mask & (tdf[a] == True)
            sub = tdf[mask]
            if len(sub) < MIN_TRADES_COMBO:
                continue
            st = _stats(sub)
            combo_rows.append({
                "size": size,
                "combo": "+".join(atoms_sub),
                **st,
            })

    combo_df = pd.DataFrame(combo_rows)
    if len(combo_df) > 0:
        combo_df = combo_df.sort_values("PF", ascending=False).head(30).reset_index(drop=True)
        combo_df = combo_df.round({"win_pct":2, "avg_R":3, "total_pnl":2,
                                    "pnl_per_trade":2, "PF":3})
        combo_df.to_csv(f"{OUTDIR}/top_combo_analysis.csv", index=False)

        print(f"{'#':<3} {'size':<5} {'combo':<55} {'trades':>7} "
              f"{'win%':>7} {'PF':>7}")
        print("-" * 95)
        for i, r in combo_df.iterrows():
            cstr = r["combo"][:53] if len(r["combo"]) > 53 else r["combo"]
            print(f"{i+1:<3} {int(r['size']):<5} {cstr:<55} "
                  f"{int(r['trades']):>7} {r['win_pct']:>6.2f}% {r['PF']:>7.3f}")
    else:
        print("  (min_trades 조건 만족 조합 없음)")

    # ──────────────────────────────────────────────────────
    # (8) tier_original_vs_atoms.csv — 원본 Tier S/A/B/C/D 가 어떤 atomic 으로 구성되는지
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[8] tier_original_vs_atoms — 원본 Tier 등급 × atomic 통과율")
    print("=" * 95)

    tov_rows = []
    header = f"{'tier':<6} {'trades':>7}"
    for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
        header += f"  {a[:11]:>11}"
    print(header)
    print("-" * max(len(header), 95))

    for t in ["S", "A", "B", "C", "D"]:
        sub = tdf[tdf["tier"] == t]
        if len(sub) == 0:
            continue
        row_data = {"tier": t, "trades": len(sub)}
        line = f"{t:<6} {len(sub):>7}"
        for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
            pct = (sub[a] == True).mean() * 100
            row_data[a + "_pct"] = round(pct, 2)
            line += f"  {pct:>10.1f}%"
        tov_rows.append(row_data)
        print(line)

    tov_df = pd.DataFrame(tov_rows)
    tov_df.to_csv(f"{OUTDIR}/tier_original_vs_atoms.csv", index=False)


print()
print("=" * 75)
print("[SAVED] Stage 4D 분석 산출물 (8개 + 기본 5개)")
print("=" * 75)
print(f"  {OUTDIR}/stage4d_trades.csv")
print(f"  {OUTDIR}/stage4d_equity.csv")
print(f"  {OUTDIR}/stage4d_skipped.csv")
print(f"  {OUTDIR}/stage4d_monthly.csv")
print(f"  {OUTDIR}/stage4d_overall_summary.csv")
print(f"  {OUTDIR}/atom_solo_effect.csv           [1] 각 원자 PASS vs FAIL")
print(f"  {OUTDIR}/sweep_vol_pivot.csv            [2] SWEEP+VOL 기준 원자 추가 효과")
print(f"  {OUTDIR}/tier_decomposition.csv         [3] Tier 5 원자 기여도")
print(f"  {OUTDIR}/rp_decomposition.csv           [4] RP 5 원자 기여도")
print(f"  {OUTDIR}/rp_level_analysis.csv          [5] RP0/RP1/RP2+ 세분")
print(f"  {OUTDIR}/side_x_atom.csv                [6] LONG/SHORT x 12 원자")
print(f"  {OUTDIR}/top_combo_analysis.csv         [7] 2-3 원자 조합 PF 상위 30")
print(f"  {OUTDIR}/tier_original_vs_atoms.csv     [8] 원본 Tier vs 원자 통과율")

print()
print("=" * 75)
print("[Stage 4D] 실험 완료")
print("=" * 75)
print("  설정: MIN_SCORE 7.5 만 게이트, 모든 risk mult = 1.0")
print("        Tier / RP 계산 유지(태깅 목적), risk 미반영")
print("        12 atomic 전부 독립 측정")
print("  핵심 산출물: sweep_vol_pivot.csv + top_combo_analysis.csv")
