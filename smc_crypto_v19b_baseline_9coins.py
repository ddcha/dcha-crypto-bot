# =========================================================
# smc_crypto_v19b_BASELINE_9COINS  (v1.9b 원본 entry + 9코인)
#
# [vs v1.9b 원본 7코인 baseline]
#   ★ BNBUSDT + ADAUSDT 추가 (7 → 9 coins)
#   ★ 병렬화 (download ThreadPool, indicator/candidates ProcessPool)
#   ★ entry frac / refine 모두 v1.9b 원본 그대로 (0.10/0.90, refine 0.25)
#
# [v1.9b 7코인 baseline 결과]
#   Return 21,916%, PF 9.44, WinR 79.58%, MDD -3.96%
#
# [9코인 baseline 의도]
#   - BNB/ADA 추가가 어떤 영향?
#   - 보수 entry (Avg_R 0.497, Return 14,193%) 와의 정확한 비교
#   - v1.9b 시스템이 9코인에서도 작동하는지 검증
# =========================================================

try:
    _ipy = get_ipython()  # noqa: F821
    if _ipy is not None:
        _ipy.run_line_magic('pip', 'install -q pandas numpy matplotlib requests')
except (NameError, AttributeError):
    pass

import pandas as pd
import numpy as np
import matplotlib
# headless / GUI 없는 환경 보호 (csv 저장 위주, 차트는 보너스)
try:
    matplotlib.use("Agg")  # GUI 안 띄우는 backend (안전)
except Exception:
    pass
import matplotlib.pyplot as plt
import requests, zipfile, io, os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import multiprocessing as mp

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

SAME_SIDE_COOLDOWN_BARS = 6
DAY_TRADE_LIMIT = 999

# ★★★ BASELINE entry 모드 (v1.9b 원본 그대로) ★★★
LONG_BASE_ENTRY_FRAC = 0.10      # zone_low + 폭×0.10 (깊이)
SHORT_BASE_ENTRY_FRAC = 0.90     # zone_low + 폭×0.90 (깊이)

H4_PIVOT_SWING_LEN = 3
H4_MSS_LOOKBACK = 8
H4_OB_LOOKBACK = 8
H4_PD_LOOKBACK = 40
H4_CHOCH_BREAK_ATR_MULT = 0.18
H4_MARKET_STATE_BARS = 8
H4_ZONE_MAX_AGE = 16
MAX_NOTIONAL_MULT = 3.0

H1_REFINE_LOOKBACK_HOURS = 12
H1_REFINE_MAX_IMPROVE_FRAC = 0.25  # ★ refine 활성 (zone 깊이 + 25% 까지 당김)
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
    "BNBUSDT":  0.010, "ADAUSDT":  0.008,
}

PHASE_B_RISK = {
    "BTCUSDT":  0.018715, "ETHUSDT":  0.015000, "SOLUSDT":  0.004676,
    "DOGEUSDT": 0.002636, "LINKUSDT": 0.002619, "XRPUSDT":  0.002380, "AVAXUSDT": 0.001791,
    "BNBUSDT":  0.004676, "ADAUSDT":  0.002636,
}

# =========================================================
# v1.9b TIER CONFIG
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
# EXECUTION CONFIG
# =========================================================
EXECUTION_SPLIT_PROXY = "orderbook_split_proxy"

SLIPPAGE_LIMIT_PCT = {
    "BTCUSDT": 0.07, "ETHUSDT": 0.10, "SOLUSDT": 0.12,
    "XRPUSDT": 0.13, "DOGEUSDT": 0.15, "AVAXUSDT": 0.14, "LINKUSDT": 0.13,
    "BNBUSDT": 0.10, "ADAUSDT": 0.13,
}

DIRECT_ENTRY_THRESHOLD_USDT = {
    "BTCUSDT":  2_000_000.0, "ETHUSDT":  1_500_000.0, "SOLUSDT":    280_000.0,
    "XRPUSDT":    200_000.0, "DOGEUSDT":   150_000.0, "AVAXUSDT":   175_000.0, "LINKUSDT":   175_000.0,
    "BNBUSDT":    400_000.0, "ADAUSDT":    150_000.0,
}

SPLIT_MAX_TRANCHES = {
    "BTCUSDT": 4, "ETHUSDT": 4, "SOLUSDT": 4,
    "XRPUSDT": 4, "DOGEUSDT": 4, "AVAXUSDT": 4, "LINKUSDT": 4,
    "BNBUSDT": 4, "ADAUSDT": 4,
}

TRANCHE_SLIPPAGE_WEIGHTS = [0.35, 0.60, 0.85, 1.00]

SCENARIO_MULTI = {
    "name": "v1.9b BASELINE 9coins (original entry, refine 0.25)",
    "assets": {
        "BTCUSDT":  {"risk_pct": PHASE_A_RISK["BTCUSDT"],  "enabled": True},
        "ETHUSDT":  {"risk_pct": PHASE_A_RISK["ETHUSDT"],  "enabled": True},
        "SOLUSDT":  {"risk_pct": PHASE_A_RISK["SOLUSDT"],  "enabled": True},
        "XRPUSDT":  {"risk_pct": PHASE_A_RISK["XRPUSDT"],  "enabled": True},
        "DOGEUSDT": {"risk_pct": PHASE_A_RISK["DOGEUSDT"], "enabled": True},
        "AVAXUSDT": {"risk_pct": PHASE_A_RISK["AVAXUSDT"], "enabled": True},
        "LINKUSDT": {"risk_pct": PHASE_A_RISK["LINKUSDT"], "enabled": True},
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


def _download_one_month(args):
    """단일 (symbol, interval, ym) 다운로드 — ThreadPool 워커."""
    symbol, interval, ym = args
    url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return ym, None, f"status_{r.status_code}"
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
        return ym, raw, "ok"
    except Exception as e:
        return ym, None, f"error:{e}"


def download_data(symbol="BTCUSDT", interval="4h", max_workers=8):
    """월별 ThreadPool 병렬 다운로드 (IO bound)."""
    months = month_range(START_YEAR, START_MONTH)
    tasks = [(symbol, interval, f"{y}-{m:02d}") for y, m in months]

    frames_by_ym = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_download_one_month, t): t for t in tasks}
        for fut in as_completed(futures):
            ym, raw, status = fut.result()
            if raw is not None:
                frames_by_ym[ym] = raw

    print(f"  {symbol} {interval}: {len(frames_by_ym)}/{len(tasks)} months loaded")

    # ym 정렬해서 concat (월 순서 보존)
    sorted_yms = sorted(frames_by_ym.keys())
    frames = [frames_by_ym[ym] for ym in sorted_yms]

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


def classify_tier_v19b(pre_total, sweep_count, score, wick_ratio_5):
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


print("Part 1/3 loaded: config + indicators + tier helpers")


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


def get_h1_window(df_h1_local, h4_timestamp, lookback_hours=12):
    start_ts = h4_timestamp - pd.Timedelta(hours=lookback_hours)
    end_ts = h4_timestamp
    return df_h1_local[(df_h1_local["timestamp"] > start_ts) & (df_h1_local["timestamp"] <= end_ts)].copy()


# refine_entry_with_h1_fvg: v1.9b 원본 — H1 FVG mid 위치까지 entry 당김 (zone 끝 + max_improve_frac)
def refine_entry_with_h1_fvg(df_h1_local, h4_timestamp, side, zone_low, zone_high, base_entry,
                              lookback_hours=12, max_improve_frac=0.25):
    """v1.9b 원본 — H1 FVG mid 가 zone 안에 있고 base_entry 보다 깊으면 그쪽으로 entry 당김."""
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


print("Part 2/3 loaded: structures + trade simulator")


# =========================================================
# CANDIDATE GENERATION
# =========================================================
def download_symbol_data(symbol):
    """H4 + H1 두 interval 을 병렬로 다운로드."""
    print(f"\n==================== {symbol} DATA DOWNLOAD ====================")
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_h4 = ex.submit(download_data, symbol, "4h")
        f_h1 = ex.submit(download_data, symbol, "1h")
        df = f_h4.result()
        df_h1 = f_h1.result()
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365 * LOOKBACK_YEARS)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    df_h1 = df_h1[df_h1["timestamp"] >= cutoff].reset_index(drop=True)
    print(f"{symbol} H4: {len(df)} rows, H1: {len(df_h1)} rows")
    return {"symbol": symbol, "df_raw": df, "df_h1_raw": df_h1}


def download_all_symbols_parallel(symbols, max_workers=4):
    """여러 심볼 병렬 다운로드. 각 심볼 안에서도 H4/H1 병렬."""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(download_symbol_data, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            results[sym] = fut.result()
    return results


def _prepare_one_symbol(raw):
    """ProcessPool 워커 — apply_indicators_and_build 그대로 호출."""
    return apply_indicators_and_build(raw)


def _generate_candidates_one_symbol(prepared):
    """ProcessPool 워커 — generate_candidates_from_prepared 그대로 호출."""
    return generate_candidates_from_prepared(prepared)


def prepare_all_symbols_parallel(raw_data_dict, max_workers=None):
    """심볼별 indicator + 구조물 빌드 병렬 (CPU bound, ProcessPool)."""
    if max_workers is None:
        max_workers = min(len(raw_data_dict), max(1, mp.cpu_count() - 1))
    results = {}
    print(f"\n[병렬] indicator + structures: {len(raw_data_dict)}심볼 × {max_workers} workers")
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_prepare_one_symbol, raw): raw["symbol"]
                   for raw in raw_data_dict.values()}
        for fut in as_completed(futures):
            sym = futures[fut]
            results[sym] = fut.result()
    return results


def generate_candidates_all_parallel(prepared_dict, max_workers=None):
    """심볼별 candidates 생성 병렬 (CPU bound, ProcessPool)."""
    if max_workers is None:
        max_workers = min(len(prepared_dict), max(1, mp.cpu_count() - 1))
    results = {}
    print(f"\n[병렬] candidates 생성: {len(prepared_dict)}심볼 × {max_workers} workers")
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_generate_candidates_one_symbol, prep): sym
                   for sym, prep in prepared_dict.items()}
        for fut in as_completed(futures):
            sym = futures[fut]
            results[sym] = fut.result()
    return results


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
            if eff_score < MIN_SCORE:
                continue
            scored_active.append((s, eff_score, fresh_reasons))

        scored_active.sort(key=lambda x: (-x[1], x[0]["zone_created_idx"]))

        for s, eff_score, fresh_reasons in scored_active:
            touched = (row["high"] >= s["zone_low"]) and (row["low"] <= s["zone_high"])
            if not touched:
                continue

            vol_ok, vol_reason = passes_volume_filter(df_struct, s["zone_created_idx"])
            if (not USE_LIQUIDITY_SWEEP_CONF) or (SWEEP_VOLUME_MODE == "AND"):
                if not vol_ok:
                    _track_skip(vol_reason)
                    continue

            fill_entry_price = float(max(s["zone_low"], min(row["open"], s["zone_high"])))
            atr_val = df_struct.loc[i, "atr"] if pd.notna(df_struct.loc[i, "atr"]) else 0.0

            rp, rp_tags = get_run_potential(df_struct, i, s)
            g = classify_grade(float(eff_score), rp)

            reasons_full = s["reasons"]
            if fresh_reasons:
                reasons_full = reasons_full + "," + ",".join(fresh_reasons) if reasons_full else ",".join(fresh_reasons)

            atr_ok, atr_reason = passes_atr_filter(df_struct, i)
            if not atr_ok:
                _track_skip(atr_reason)
                continue

            if s["type"] == "short":
                if i - last_short_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "up":
                    continue

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

                # ★★★ 보수 entry: SHORT_BASE_ENTRY_FRAC = 0.0 = zone_low ★★★
                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * SHORT_BASE_ENTRY_FRAC
                refined_entry_candidate, improved, refine_px, refine_reason = refine_entry_with_h1_fvg(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="short", zone_low=s["zone_low"], zone_high=s["zone_high"],
                    base_entry=base_entry_candidate,
                    lookback_hours=H1_REFINE_LOOKBACK_HOURS,
                    max_improve_frac=H1_REFINE_MAX_IMPROVE_FRAC
                )

                if row["high"] >= refined_entry_candidate:
                    fill_entry_price = float(refined_entry_candidate)
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
                refined_entry = refine_px if improved else np.nan
                entry_refined = improved
                refine_tag = refine_reason
                _v17_signal_price = float(df_struct.loc[i, "close"])
                _v17_expected_entry = float(base_entry_candidate)
                _v17_submitted_entry = float(refined_entry_candidate)
                _v17_filled_entry = float(fill_entry_price)
                _v17_fill_time_h1 = fill_time_h1
                _v17_fill_bars_waited = fill_bars_waited
                break

            if s["type"] == "long":
                if i - last_long_exit_idx < SAME_SIDE_COOLDOWN_BARS:
                    continue
                if df_struct.loc[i, "trend"] == "down":
                    continue

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

                # ★★★ 보수 entry: LONG_BASE_ENTRY_FRAC = 1.0 = zone_high ★★★
                base_entry_candidate = s["zone_low"] + (s["zone_high"] - s["zone_low"]) * LONG_BASE_ENTRY_FRAC
                refined_entry_candidate, improved, refine_px, refine_reason = refine_entry_with_h1_fvg(
                    df_h1_local=df_h1, h4_timestamp=df_struct.loc[i, "timestamp"],
                    side="long", zone_low=s["zone_low"], zone_high=s["zone_high"],
                    base_entry=base_entry_candidate,
                    lookback_hours=H1_REFINE_LOOKBACK_HOURS,
                    max_improve_frac=H1_REFINE_MAX_IMPROVE_FRAC
                )

                if row["low"] <= refined_entry_candidate:
                    fill_entry_price = float(refined_entry_candidate)
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
                refined_entry = refine_px if improved else np.nan
                entry_refined = improved
                refine_tag = refine_reason
                _v17_signal_price = float(df_struct.loc[i, "close"])
                _v17_expected_entry = float(base_entry_candidate)
                _v17_submitted_entry = float(refined_entry_candidate)
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
            "fill_vs_refined_pct": ((fill_entry_price - entry) / entry * 100.0) if entry else 0.0,
            "entry_idx": i,
            "signal_price":    _v17_signal_price,
            "expected_entry":  _v17_expected_entry,
            "submitted_entry": _v17_submitted_entry,
            "filled_entry":    _v17_filled_entry,
            "fill_status":     "filled",
            "fill_time_h1":    _v17_fill_time_h1,
            "fill_bars_waited": _v17_fill_bars_waited,
            "base_entry": base_entry,
            "entry_improved_by": (base_entry - entry) if entry_side == "long" else (entry - base_entry),
            "entry_refined": entry_refined,
            "refined_entry_px": refined_entry,
            "refine_tag": refine_tag,
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
        print(f"\n{symbol} filter skips:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1])[:15]:
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


# =========================================================
# SIMULATION (v1.9b CONSERVATIVE ENTRY)
# =========================================================
def simulate_scenario_v19b(scenario, candidates_dict):
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

                pre_total_v = int(row.get("pre_entry_total", 0)) if pd.notna(row.get("pre_entry_total", 0)) else 0
                sweep_v = int(row.get("pre_entry_sweep", 0)) if pd.notna(row.get("pre_entry_sweep", 0)) else 0
                score_v = float(row.get("score", 0))
                wick_v = row.get("wick_ratio_5", None)
                if pd.isna(wick_v): wick_v = None

                tier_label, tier_mult = classify_tier_v19b(pre_total_v, sweep_v, score_v, wick_v)

                if tier_mult <= 0.0:
                    skipped_entries.append({
                        "scenario_name": scenario["name"], "entry_time": row["entry_time"],
                        "symbol": symbol, "reason": f"tier_skip_{tier_label}",
                        "phase_at_entry": current_phase_for_entry,
                    })
                    continue

                risk_pct = risk_pct_base * tier_mult

                qty, risk_per_unit, notional = calc_position_size(
                    balance=balance, risk_pct=risk_pct, entry=row["entry"], sl=row["sl"],
                    fee_rate=FEE_RATE, max_notional_mult=MAX_NOTIONAL_MULT
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
                    "strategy_variant": "v19b_BASELINE_9COINS",
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
                    "tier": tier_label,
                    "tier_mult": tier_mult,
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
        "strategy_variant": "v19b_BASELINE_9COINS",
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
    print(f"  ★ ENTRY MODE: BASELINE (frac {LONG_BASE_ENTRY_FRAC}/{SHORT_BASE_ENTRY_FRAC}, refine={H1_REFINE_MAX_IMPROVE_FRAC}) ★")

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


def plot_equity(result_dict, save_path=None):
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

    # png 저장 (Agg backend 호환)
    if save_path:
        try:
            plt.savefig(save_path, dpi=120, bbox_inches="tight")
            print(f"   📊 차트 저장: {save_path}")
        except Exception as e:
            print(f"   [WARN] 차트 저장 실패: {e}")

    # 가능하면 화면 표시 (headless 면 무시)
    try:
        plt.show()
    except Exception:
        pass
    finally:
        plt.close(fig)


print("Part 3/3 loaded: candidate + simulation + report")


# =========================================================
# MAIN EXECUTION
# =========================================================
if __name__ == "__main__":
    # macOS / Windows 호환 — ProcessPool 안전하게
    try:
        mp.set_start_method("spawn", force=False)
    except RuntimeError:
        pass

    import time as _time
    _t_total_start = _time.time()

    print("\n" + "=" * 80)
    print("v1.9b BASELINE 9 COINS — PARALLEL")
    print("=" * 80)
    print(f"  LONG_BASE_ENTRY_FRAC  = {LONG_BASE_ENTRY_FRAC}  (zone_low + 폭×0.10, 깊이 진입)")
    print(f"  SHORT_BASE_ENTRY_FRAC = {SHORT_BASE_ENTRY_FRAC}  (zone_low + 폭×0.90, 깊이 진입)")
    print(f"  H1_REFINE             = ENABLED (max_improve_frac={H1_REFINE_MAX_IMPROVE_FRAC})")
    print(f"  Symbols               = 9 (BTC/ETH/SOL/BNB/XRP/ADA/DOGE/LINK/AVAX)")
    print(f"  Period                = {LOOKBACK_YEARS} years")
    print(f"  Wick threshold        = {WICK_RATIO_5_Q1_THRESHOLD}")
    print(f"  CPU cores             = {mp.cpu_count()}")
    print("=" * 80)

    # --- 셀 2 indicator override (사용자 첨부 코드와 동일) ---
    H4_PIVOT_SWING_LEN = 30
    H4_MSS_LOOKBACK = 80
    H4_OB_LOOKBACK = 15
    H4_PD_LOOKBACK = 1620
    H4_MARKET_STATE_BARS = 360
    H4_ZONE_MAX_AGE = 30

    SYMBOLS_TO_PREPARE = sorted(list(SCENARIO_MULTI["assets"].keys()))

    # ===================== 셀 1: 데이터 다운로드 (병렬) =====================
    _t = _time.time()
    print(f"\n[1/3] 데이터 다운로드 (9심볼 × 2 interval = 18 stream 병렬)")
    raw_data = download_all_symbols_parallel(SYMBOLS_TO_PREPARE, max_workers=4)
    print(f"\n✅ 다운로드 완료 ({_time.time()-_t:.1f}초)")

    # ===================== 셀 2: indicator + 구조물 + candidates (병렬) =====================
    _t = _time.time()
    print(f"\n[2/3] indicator + structures (9심볼 ProcessPool)")
    prepared_data = prepare_all_symbols_parallel(raw_data)
    print(f"\n✅ structures 완료 ({_time.time()-_t:.1f}초)")

    _t = _time.time()
    print(f"\n[3/3] candidates 생성 (9심볼 ProcessPool)")
    candidates_dict = generate_candidates_all_parallel(prepared_data)
    print(f"\n✅ candidates 완료 ({_time.time()-_t:.1f}초)")

    # ===================== 셀 3: 백테스트 실행 =====================
    _t = _time.time()
    OUTDIR = "smc_crypto_v19b_baseline_9coins_outputs"
    os.makedirs(OUTDIR, exist_ok=True)

    print(f"\n[백테스트] 시뮬레이션 시작")
    res = simulate_scenario_v19b(
        scenario=SCENARIO_MULTI,
        candidates_dict=candidates_dict,
    )

    # ⭐ csv 먼저 저장 (이후 단계에서 에러 나도 결과는 보존) ⭐
    try:
        res["trades"].to_csv(f"{OUTDIR}/baseline_trades.csv", index=False)
        res["equity"].to_csv(f"{OUTDIR}/baseline_equity.csv", index=False)
        res["skipped"].to_csv(f"{OUTDIR}/baseline_skipped.csv", index=False)
        res["phase_transitions"].to_csv(f"{OUTDIR}/baseline_phase_transitions.csv", index=False)
        res["excess_log"].to_csv(f"{OUTDIR}/baseline_excess_log.csv", index=False)
        print(f"\n💾 CSV 저장 완료: {OUTDIR}/")
        for f in os.listdir(OUTDIR):
            sz = os.path.getsize(f"{OUTDIR}/{f}")
            print(f"   {f}: {sz:,} bytes")
    except Exception as e:
        print(f"\n[ERROR] CSV 저장 실패: {e}")
        import traceback; traceback.print_exc()

    # 리포트 출력
    try:
        monthly_report = print_scenario_summary(res)
        monthly_report.to_csv(f"{OUTDIR}/baseline_monthly_pnl.csv", index=False)
    except Exception as e:
        print(f"\n[ERROR] 리포트 출력 실패: {e}")
        import traceback; traceback.print_exc()

    # 차트 (마지막 — 실패해도 csv 는 이미 저장됨)
    try:
        plot_equity(res, save_path=f"{OUTDIR}/baseline_equity_chart.png")
    except Exception as e:
        print(f"\n[WARN] 차트 생성 실패 (csv 는 이미 저장됨): {e}")

    total_filled = sum(len(p["candidates"]) for p in candidates_dict.values())
    total_no_fill = sum(len(p.get("no_fill", [])) for p in candidates_dict.values())
    print(f"\n🎯 v1.9b BASELINE 9코인 백테스트 완료")
    print(f"   전체 시그널: {total_filled + total_no_fill}")
    print(f"   체결: {total_filled}, 미체결: {total_no_fill}")
    print(f"   백테스트 시뮬레이션: {_time.time()-_t:.1f}초")
    print(f"   ⏱  전체 실행 시간: {_time.time()-_t_total_start:.1f}초")
