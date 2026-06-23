# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.filters
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403
from .tiers import *  # noqa: F401,F403
from .structures import *  # noqa: F401,F403



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
