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

    # ⭐ numpy화(2026-07): row-wise apply → 벡터마스크 (결과 동일, apply 오버헤드 제거)
    e20 = data["ema20"].to_numpy(); e50 = data["ema50"].to_numpy(); e200 = data["ema200"].to_numpy()
    trend = np.full(len(data), "neutral", dtype=object)
    trend[(e20 < e50) & (e50 < e200)] = "down"
    trend[(e20 > e50) & (e50 > e200)] = "up"
    data["trend"] = trend
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
    # ⭐ numpy화(2026-07): .loc 루프 → rolling.shift 벡터화. prev_high[i]=max(high[i-lb:i]).
    data = data.copy()
    n = len(data)
    close = data["close"].to_numpy()
    prev_high = data["high"].rolling(mss_lookback).max().shift(1).to_numpy()
    prev_low = data["low"].rolling(mss_lookback).min().shift(1).to_numpy()
    valid = np.arange(n) >= mss_lookback
    data["bull_mss"] = valid & (close > prev_high)   # NaN 비교→False
    data["bear_mss"] = valid & (close < prev_low)
    return data


def apply_displacement(data, disp_body_ratio=0.45, disp_atr_mult=0.90):
    # ⭐ numpy화(2026-07): .loc 루프 → 전배열 마스크. i=0 은 atr=NaN→valid False 로 자연 배제.
    data = data.copy()
    n = len(data)
    atr = data["atr"].to_numpy()
    close = data["close"].to_numpy(); open_ = data["open"].to_numpy()
    br = data["body_ratio"].to_numpy(); rng = data["range"].to_numpy()
    valid = (~np.isnan(atr)) & (atr != 0)
    valid[0] = False                                   # 원본 루프는 i=1 부터
    thr = atr * disp_atr_mult
    data["bull_disp"] = valid & (close > open_) & (br >= disp_body_ratio) & (rng >= thr)
    data["bear_disp"] = valid & (close < open_) & (br >= disp_body_ratio) & (rng >= thr)
    ds = np.zeros(n, dtype=float)
    np.divide(rng, atr, out=ds, where=valid)           # valid 아닌 곳은 0.0 유지
    data["disp_strength"] = ds
    return data


def apply_fvg(data):
    # ⭐ numpy화(2026-07): .loc 루프 → shift2 마스크. h2[i]=high[i-2], l2[i]=low[i-2].
    data = data.copy()
    n = len(data)
    high = data["high"].to_numpy(); low = data["low"].to_numpy()
    h2 = np.full(n, np.nan); l2 = np.full(n, np.nan)
    if n > 2:
        h2[2:] = high[:-2]; l2[2:] = low[:-2]
    bull = low > h2                                     # NaN 비교→False
    bear = high < l2
    data["bull_fvg_low"] = np.where(bull, h2, np.nan)
    data["bull_fvg_high"] = np.where(bull, low, np.nan)
    data["bear_fvg_low"] = np.where(bear, high, np.nan)
    data["bear_fvg_high"] = np.where(bear, l2, np.nan)
    data["bull_fvg_size"] = np.where(bull, low - h2, np.nan)
    data["bear_fvg_size"] = np.where(bear, l2 - high, np.nan)
    return data


def apply_ob(data, ob_lookback=8):
    # ⭐ numpy화(2026-07): 출력 6컬럼을 배열로 누적 후 일괄 대입. engulf 분기는 완전 벡터화,
    #   strict/legacy 분기는 제어흐름 보존(내부 역방향 탐색) 하되 write 를 arr[i] 로 교체.
    data = data.copy()
    n = len(data)
    _strict = (OB_MODE == "strict")
    _o = data["open"].values.astype(float)
    _c = data["close"].values.astype(float)
    _hh = data["high"].values.astype(float)
    _ll = data["low"].values.astype(float)

    bull_lo = np.full(n, np.nan); bull_hi = np.full(n, np.nan); bull_sz = np.full(n, np.nan)
    bear_lo = np.full(n, np.nan); bear_hi = np.full(n, np.nan); bear_sz = np.full(n, np.nan)

    if OB_MODE == "engulf":
        # ⭐ 사용자 정의 OB: 직전 반대색 캔들보다 *큰(바디)* 임펄스 캔들이 출현하면,
        #   OB = 그 *직전 반대색 캔들의 바디* 만큼 (임펄스 캔들 전체 X).
        #   컬럼은 확정봉 k에 앵커 (k-1, k 만 읽음 → 룩어헤드 0). → shift1 마스크 벡터화.
        o_p = np.full(n, np.nan); c_p = np.full(n, np.nan)
        if n > 1:
            o_p[1:] = _o[:-1]; c_p[1:] = _c[:-1]
        plo = np.minimum(o_p, c_p); phi = np.maximum(o_p, c_p)
        bk = np.abs(_c - _o); bp = np.abs(c_p - o_p)
        bull_m = (c_p < o_p) & (_c > _o) & (bk > bp)   # k=0 은 c_p NaN → False
        bear_m = (c_p > o_p) & (_c < _o) & (bk > bp)
        bull_lo = np.where(bull_m, plo, np.nan); bull_hi = np.where(bull_m, phi, np.nan); bull_sz = np.where(bull_m, phi - plo, np.nan)
        bear_lo = np.where(bear_m, plo, np.nan); bear_hi = np.where(bear_m, phi, np.nan); bear_sz = np.where(bear_m, phi - plo, np.nan)
    else:
        _bull_disp = data["bull_disp"].to_numpy()
        _bear_disp = data["bear_disp"].to_numpy()
        for i in range(2, n):
            if _bull_disp[i]:
                for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                    if _c[j] < _o[j]:                 # 직전 가장 가까운 음봉(반대색)
                        if _strict:
                            if (_ll[j] <= _ll[j:i + 1].min()) and (_hh[i] > _hh[j]):
                                lo = min(_o[j], _c[j]); hi = max(_o[j], _c[j])
                                bull_lo[i] = lo; bull_hi[i] = hi; bull_sz[i] = hi - lo
                        else:
                            bull_lo[i] = _ll[j]; bull_hi[i] = _hh[j]; bull_sz[i] = _hh[j] - _ll[j]
                        break
            if _bear_disp[i]:
                for j in range(i - 1, max(i - ob_lookback - 1, -1), -1):
                    if _c[j] > _o[j]:                 # 직전 가장 가까운 양봉(반대색)
                        if _strict:
                            if (_hh[j] >= _hh[j:i + 1].max()) and (_ll[i] < _ll[j]):
                                lo = min(_o[j], _c[j]); hi = max(_o[j], _c[j])
                                bear_lo[i] = lo; bear_hi[i] = hi; bear_sz[i] = hi - lo
                        else:
                            bear_lo[i] = _ll[j]; bear_hi[i] = _hh[j]; bear_sz[i] = _hh[j] - _ll[j]
                        break

    data["bull_ob_low"] = bull_lo; data["bull_ob_high"] = bull_hi
    data["bear_ob_low"] = bear_lo; data["bear_ob_high"] = bear_hi
    data["bull_ob_size"] = bull_sz; data["bear_ob_size"] = bear_sz
    return data


def apply_pd(data, pd_lookback=40):
    data = data.copy()
    data["pd_high"] = data["high"].rolling(pd_lookback).max()
    data["pd_low"] = data["low"].rolling(pd_lookback).min()
    data["pd_mid"] = (data["pd_high"] + data["pd_low"]) / 2
    data["pd_loc"] = np.where(data["close"] >= data["pd_mid"], "premium", "discount")
    return data


def apply_pivots(data, swing_len=3):
    # ⭐ numpy화(2026-07): 피벗검출=중심롤링 max/min 벡터화, last/prev 추적=배열 순차루프(O(n)).
    data = data.copy()
    n = len(data)
    high = data["high"].to_numpy(); low = data["low"].to_numpy()
    win = 2 * swing_len + 1
    rmax = data["high"].rolling(win, center=True).max().to_numpy()
    rmin = data["low"].rolling(win, center=True).min().to_numpy()
    piv_h = np.where(high == rmax, high, np.nan)   # 경계(NaN)는 == 실패 → NaN, 원본 range 와 동일
    piv_l = np.where(low == rmin, low, np.nan)
    data["pivot_high"] = piv_h
    data["pivot_low"] = piv_l

    last_high = np.nan; last_low = np.nan; prev_high = np.nan; prev_low = np.nan
    lph = np.empty(n); pph = np.empty(n); lpl = np.empty(n); ppl = np.empty(n)
    for i in range(n):
        lookup_bar = i - swing_len
        if lookup_bar >= 0:
            if not np.isnan(piv_h[lookup_bar]):
                prev_high = last_high; last_high = piv_h[lookup_bar]
            if not np.isnan(piv_l[lookup_bar]):
                prev_low = last_low; last_low = piv_l[lookup_bar]
        lph[i] = last_high; pph[i] = prev_high; lpl[i] = last_low; ppl[i] = prev_low
    data["last_pivot_high"] = lph; data["prev_pivot_high"] = pph
    data["last_pivot_low"] = lpl; data["prev_pivot_low"] = ppl
    return data


def apply_structure_bias(data):
    # ⭐ numpy화(2026-07): 순차 상태머신을 배열 루프로 (.loc 제거, 로직 동일).
    data = data.copy()
    n = len(data)
    lph = data["last_pivot_high"].to_numpy(); pph = data["prev_pivot_high"].to_numpy()
    lpl = data["last_pivot_low"].to_numpy(); ppl = data["prev_pivot_low"].to_numpy()
    out = np.empty(n, dtype=object)
    current_bias = "neutral"
    for i in range(n):
        a, b, c, d = lph[i], pph[i], lpl[i], ppl[i]
        if not (np.isnan(a) or np.isnan(b) or np.isnan(c) or np.isnan(d)):
            if a > b and c > d:
                current_bias = "up"
            elif a < b and c < d:
                current_bias = "down"
        out[i] = current_bias
    data["structure_bias"] = out
    return data


def apply_choch(data, break_atr_mult=0.15):
    # ⭐ numpy화(2026-07): 배열 루프 (i, i-1 참조). 결과 동일.
    data = data.copy()
    n = len(data)
    atr = data["atr"].to_numpy(); close = data["close"].to_numpy()
    bias = data["structure_bias"].to_numpy()
    last_high = data["last_pivot_high"].to_numpy(); last_low = data["last_pivot_low"].to_numpy()
    bull = np.zeros(n, dtype=bool); bear = np.zeros(n, dtype=bool)
    for i in range(1, n):
        atr_val = atr[i]
        if np.isnan(atr_val) or atr_val <= 0:
            continue
        b = bias[i - 1]; lh = last_high[i - 1]; ll = last_low[i - 1]
        if b == "down" and not np.isnan(lh):
            if close[i] > (lh + atr_val * break_atr_mult):
                bull[i] = True
        if b == "up" and not np.isnan(ll):
            if close[i] < (ll - atr_val * break_atr_mult):
                bear[i] = True
    data["bull_choch"] = bull; data["bear_choch"] = bear
    return data


def apply_h4_market_state(data, transition_bars=8):
    # ⭐ numpy화(2026-07): 순차 상태머신 배열 루프. 로직 동일.
    data = data.copy()
    n = len(data)
    bull_choch = data["bull_choch"].to_numpy(); bear_choch = data["bear_choch"].to_numpy()
    trend = data["trend"].to_numpy()
    out = np.empty(n, dtype=object)
    bull_until = -1; bear_until = -1
    for i in range(n):
        if bull_choch[i]:
            bull_until = i + transition_bars; bear_until = -1
        if bear_choch[i]:
            bear_until = i + transition_bars; bull_until = -1
        base_trend = trend[i]
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
        out[i] = state
    data["market_state"] = out
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
    # ⭐ numpy화(2026-07): build_structures Loop1 과 동일 패턴으로 벡터화. recent_high[i]=max(high[i-n:i]).
    df = df.copy()
    n = len(df)
    high = df["high"].to_numpy(); low = df["low"].to_numpy(); close = df["close"].to_numpy()
    lph = df["last_pivot_high"].to_numpy(); lpl = df["last_pivot_low"].to_numpy()
    recent_high = df["high"].rolling(recent_sweep_n).max().shift(1).to_numpy()
    recent_low = df["low"].rolling(recent_sweep_n).min().shift(1).to_numpy()
    valid = np.arange(n) >= recent_sweep_n
    df["pivot_sweep_high"] = valid & (~np.isnan(lph)) & (high > lph) & (close < lph)
    df["pivot_sweep_low"] = valid & (~np.isnan(lpl)) & (low < lpl) & (close > lpl)
    df["recent_sweep_high"] = valid & (high > recent_high) & (close < recent_high)   # NaN 비교→False
    df["recent_sweep_low"] = valid & (low < recent_low) & (close > recent_low)
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
