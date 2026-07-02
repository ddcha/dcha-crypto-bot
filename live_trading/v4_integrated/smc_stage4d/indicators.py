# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.indicators
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403


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
    _strict = (OB_MODE == "strict")
    _o = data["open"].values.astype(float)
    _c = data["close"].values.astype(float)
    _hh = data["high"].values.astype(float)
    _ll = data["low"].values.astype(float)

    if OB_MODE == "engulf":
        # ⭐ 사용자 정의 OB: 직전 반대색 캔들보다 *큰(바디)* 임펄스 캔들이 출현하면,
        #   OB = 그 *직전 반대색 캔들의 바디* 만큼 (임펄스 캔들 전체 X).
        #   직전 음봉 + 더 큰 양봉 → bull OB = 직전 음봉(k-1) 바디
        #   직전 양봉 + 더 큰 음봉 → bear OB = 직전 양봉(k-1) 바디
        #   컬럼은 확정봉 k에 앵커 (k-1, k 만 읽음 → 룩어헤드 0).
        for k in range(1, len(data)):
            _bk = abs(_c[k] - _o[k])
            _bp = abs(_c[k - 1] - _o[k - 1])
            _plo = min(_o[k - 1], _c[k - 1])   # 직전캔들 바디 하단
            _phi = max(_o[k - 1], _c[k - 1])   # 직전캔들 바디 상단
            if (_c[k - 1] < _o[k - 1]) and (_c[k] > _o[k]) and (_bk > _bp):
                data.loc[k, "bull_ob_low"] = _plo
                data.loc[k, "bull_ob_high"] = _phi
                data.loc[k, "bull_ob_size"] = _phi - _plo
            if (_c[k - 1] > _o[k - 1]) and (_c[k] < _o[k]) and (_bk > _bp):
                data.loc[k, "bear_ob_low"] = _plo
                data.loc[k, "bear_ob_high"] = _phi
                data.loc[k, "bear_ob_size"] = _phi - _plo
        return data

    for i in range(2, len(data)):
        if data.loc[i, "bull_disp"]:
            for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                if _c[j] < _o[j]:                 # 직전 가장 가까운 음봉(반대색)
                    if _strict:
                        # 정통: j가 임펄스 *기원(base)* — j 이후 i까지 j보다 낮은 low 없음 + 위로 임펄스
                        if (_ll[j] <= _ll[j:i + 1].min()) and (_hh[i] > _hh[j]):
                            lo = min(_o[j], _c[j]); hi = max(_o[j], _c[j])   # 바디존
                            data.loc[i, "bull_ob_low"] = lo
                            data.loc[i, "bull_ob_high"] = hi
                            data.loc[i, "bull_ob_size"] = hi - lo
                        # 기원 아니면 OB 없음(reject) — stale 캔들 방지
                    else:
                        data.loc[i, "bull_ob_low"] = _ll[j]
                        data.loc[i, "bull_ob_high"] = _hh[j]
                        data.loc[i, "bull_ob_size"] = _hh[j] - _ll[j]
                    break
        if data.loc[i, "bear_disp"]:
            for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                if _c[j] > _o[j]:                 # 직전 가장 가까운 양봉(반대색)
                    if _strict:
                        # 정통: j가 임펄스 *기원(천장)* — j 이후 i까지 j보다 높은 high 없음 + 아래로 임펄스
                        if (_hh[j] >= _hh[j:i + 1].max()) and (_ll[i] < _ll[j]):
                            lo = min(_o[j], _c[j]); hi = max(_o[j], _c[j])   # 바디존
                            data.loc[i, "bear_ob_low"] = lo
                            data.loc[i, "bear_ob_high"] = hi
                            data.loc[i, "bear_ob_size"] = hi - lo
                    else:
                        data.loc[i, "bear_ob_low"] = _ll[j]
                        data.loc[i, "bear_ob_high"] = _hh[j]
                        data.loc[i, "bear_ob_size"] = _hh[j] - _ll[j]
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


# =========================================================================
# ⭐ feature/h1-refine-zone — H1×H4 존 정밀화(refine)
#    이 함수는 자동추출본이 아니라 feature 브랜치에서 직접 추가한 코드다.
# =========================================================================
def refine_zone_with_h1(df_h1, entry_h4_ts, z4_lo, z4_hi, lookback_h1_bars=12):
    """
    H4 존 [z4_lo,z4_hi]을 H1 FVG/OB 가격범위 겹침으로 정밀화.
    겹치면 '가장 크게 겹치는' H1존과의 교집합으로 좁히고, 안 겹치면 H4 존 그대로.
    ⭐ 룩어헤드 0: entry_h4_ts '미만'(strict <)으로 이미 닫힌 H1봉만 사용.
       (ts=open시각, H1봉은 ts+1h에 확정 → ts<T 이면 T 이전에 닫힘 보장)
    반환: (r_lo, r_hi, refined: bool, overlap_frac: float)
    """
    sel = (df_h1["timestamp"] < entry_h4_ts).values     # ⭐ tz-safe, strict <
    if not sel.any():
        return z4_lo, z4_hi, False, 0.0
    last_idx = int(np.where(sel)[0][-1])
    start_idx = max(0, last_idx - lookback_h1_bars + 1)
    sub = df_h1.iloc[start_idx:last_idx + 1]
    cols = [("bull_fvg_low","bull_fvg_high"),("bear_fvg_low","bear_fvg_high"),
            ("bull_ob_low","bull_ob_high"),("bear_ob_low","bear_ob_high")]
    best_lo = best_hi = None; best_ov = 0.0
    for lo_c, hi_c in cols:
        if lo_c not in sub.columns: continue
        los = sub[lo_c].values.astype(float); his = sub[hi_c].values.astype(float)
        for h1lo, h1hi in zip(los, his):
            if np.isnan(h1lo) or np.isnan(h1hi): continue
            ov = min(z4_hi, h1hi) - max(z4_lo, h1lo)
            if ov > best_ov:
                best_ov = ov; best_lo = max(z4_lo, h1lo); best_hi = min(z4_hi, h1hi)
    if best_lo is None or best_hi <= best_lo:
        return z4_lo, z4_hi, False, 0.0
    w = z4_hi - z4_lo
    return float(best_lo), float(best_hi), True, (best_ov / w if w > 0 else 0.0)
