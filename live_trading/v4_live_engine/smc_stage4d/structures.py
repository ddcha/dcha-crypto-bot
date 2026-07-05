# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.structures
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403
from .tiers import *  # noqa: F401,F403



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
    # ⭐ numpy화(2026-06): 기존 .loc 3중루프 → 컬럼 배열 사전추출 + Loop1 벡터화.
    #   결과 바이트 동일(OLD vs NEW 차등검증 60회/19,106 structures/불일치 0, sweep컬럼 0).
    #   속도 n=6000 기준 5.24s→0.12s(≈45x). OB_MODE 무관(OB컬럼은 상류 apply_ob 산출물을 읽기만).
    recent_sweep_n = SWEEP_RECENT_N   # feature/gate-tighten: H4 recent-sweep 봉수 (기본 10)
    df = df.copy()
    n = len(df)

    # ── Loop1 벡터화: sweep 4플래그 (i<recent_sweep_n 은 valid 마스크로 False 고정) ──
    h   = df["high"].values.astype(float)
    l   = df["low"].values.astype(float)
    c   = df["close"].values.astype(float)
    lph = df["last_pivot_high"].values.astype(float)
    lpl = df["last_pivot_low"].values.astype(float)
    recent_high = df["high"].rolling(recent_sweep_n).max().shift(1).values  # = high[i-10:i].max()
    recent_low  = df["low"].rolling(recent_sweep_n).min().shift(1).values   # = low[i-10:i].min()
    valid = np.arange(n) >= recent_sweep_n
    df["pivot_sweep_high"]  = valid & (~np.isnan(lph)) & (h > lph) & (c < lph)
    df["pivot_sweep_low"]   = valid & (~np.isnan(lpl)) & (l < lpl) & (c > lpl)
    df["recent_sweep_high"] = valid & (h > recent_high) & (c < recent_high)  # NaN비교→False
    df["recent_sweep_low"]  = valid & (l < recent_low)  & (c > recent_low)

    # ⭐ 품질 스윕(유동성맵 기반) 컬럼 추가 — a_sweep 엄밀화용 (qsweep_high/low만 추가)
    df = add_liquidity_sweep_quality(df)

    structure_wait = 10
    post_structure_zone_window = 6
    zone_max_age = H4_ZONE_MAX_AGE
    structures = []

    # ── Loop2 컬럼 배열 사전추출(.loc → arr[i], post-quality df 기준) ──
    A_h = df["high"].values.astype(float); A_l = df["low"].values.astype(float)
    A_psh = df["pivot_sweep_high"].values;  A_rsh = df["recent_sweep_high"].values
    A_psl = df["pivot_sweep_low"].values;   A_rsl = df["recent_sweep_low"].values
    A_pdloc = df["pd_loc"].values;          A_trend = df["trend"].values
    A_beardisp = df["bear_disp"].values;    A_bearmss = df["bear_mss"].values
    A_bulldisp = df["bull_disp"].values;    A_bullmss = df["bull_mss"].values
    A_atr = df["atr"].values.astype(float); A_disp = df["disp_strength"].values.astype(float)
    A_bol = df["bear_ob_low"].values.astype(float);  A_boh = df["bear_ob_high"].values.astype(float);  A_bos = df["bear_ob_size"].values.astype(float)
    A_bfl = df["bear_fvg_low"].values.astype(float); A_bfh = df["bear_fvg_high"].values.astype(float); A_bfs = df["bear_fvg_size"].values.astype(float)
    A_uol = df["bull_ob_low"].values.astype(float);  A_uoh = df["bull_ob_high"].values.astype(float);  A_uos = df["bull_ob_size"].values.astype(float)
    A_ufl = df["bull_fvg_low"].values.astype(float); A_ufh = df["bull_fvg_high"].values.astype(float); A_ufs = df["bull_fvg_size"].values.astype(float)

    for i in range(60, n - 1):
        short_sweep = bool(A_psh[i] or A_rsh[i])
        if short_sweep:
            for j in range(i + 1, min(i + structure_wait + 1, n)):
                if not (A_beardisp[j] or A_bearmss[j]):
                    continue
                base_score = 2.5
                reasons = ["sweep"]

                if A_pdloc[i] == "premium":
                    base_score += 1.0
                    reasons.append("premium")
                if A_beardisp[j]:
                    base_score += 3.0
                    reasons.append("bear_disp")
                if A_bearmss[j]:
                    base_score += 3.0
                    reasons.append("bear_mss")
                if A_trend[j] == "down":
                    base_score += 1.5
                    reasons.append("trend_down")

                structure_idx = j
                found_zone = False

                for k in range(structure_idx + 1, min(structure_idx + post_structure_zone_window + 1, n)):
                    score_k = base_score
                    reasons_k = reasons.copy()

                    has_ob  = (not np.isnan(A_bol[k])) and (not np.isnan(A_boh[k]))
                    has_fvg = (not np.isnan(A_bfl[k])) and (not np.isnan(A_bfh[k]))

                    if not (has_ob or has_fvg):
                        continue

                    ob_low = ob_high = None
                    fvg_low = fvg_high = None

                    if has_ob:
                        ob_low = float(A_bol[k])
                        ob_high = float(A_boh[k])
                        ob_size = float(A_bos[k]) if not np.isnan(A_bos[k]) else 0.0
                        atr_val = float(A_atr[k]) if not np.isnan(A_atr[k]) else np.nan

                        score_k += 1.5
                        reasons_k.append("valid_bear_ob")
                        if (not np.isnan(A_disp[k])) and A_disp[k] >= 1.2:
                            score_k += 1.0
                            reasons_k.append("strong_disp_ob")
                        if (not np.isnan(atr_val)) and atr_val > 0 and ob_size / atr_val >= 0.20:
                            score_k += 0.5
                            reasons_k.append("sized_bear_ob")

                    if has_fvg:
                        fvg_low = float(A_bfl[k])
                        fvg_high = float(A_bfh[k])
                        fvg_size = float(A_bfs[k]) if not np.isnan(A_bfs[k]) else 0.0
                        atr_val = float(A_atr[k]) if not np.isnan(A_atr[k]) else np.nan

                        score_k += 1.0
                        reasons_k.append("valid_bear_fvg")
                        if (not np.isnan(atr_val)) and atr_val > 0 and fvg_size / atr_val >= 0.15:
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
                            "sweep_ref": float(A_h[i]),
                            "expire_idx": min(k + zone_max_age, n - 1),
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

        long_sweep = bool(A_psl[i] or A_rsl[i])
        if long_sweep:
            for j in range(i + 1, min(i + structure_wait + 1, n)):
                if not (A_bulldisp[j] or A_bullmss[j]):
                    continue
                base_score = 2.5
                reasons = ["sweep"]

                if A_pdloc[i] == "discount":
                    base_score += 1.0
                    reasons.append("discount")
                if A_bulldisp[j]:
                    base_score += 3.0
                    reasons.append("bull_disp")
                if A_bullmss[j]:
                    base_score += 3.0
                    reasons.append("bull_mss")
                if A_trend[j] == "up":
                    base_score += 1.5
                    reasons.append("trend_up")

                structure_idx = j
                found_zone = False

                for k in range(structure_idx + 1, min(structure_idx + post_structure_zone_window + 1, n)):
                    score_k = base_score
                    reasons_k = reasons.copy()

                    has_ob  = (not np.isnan(A_uol[k])) and (not np.isnan(A_uoh[k]))
                    has_fvg = (not np.isnan(A_ufl[k])) and (not np.isnan(A_ufh[k]))

                    if not (has_ob or has_fvg):
                        continue

                    ob_low = ob_high = None
                    fvg_low = fvg_high = None

                    if has_ob:
                        ob_low = float(A_uol[k])
                        ob_high = float(A_uoh[k])
                        ob_size = float(A_uos[k]) if not np.isnan(A_uos[k]) else 0.0
                        atr_val = float(A_atr[k]) if not np.isnan(A_atr[k]) else np.nan

                        score_k += 1.5
                        reasons_k.append("valid_bull_ob")
                        if (not np.isnan(A_disp[k])) and A_disp[k] >= 1.2:
                            score_k += 1.0
                            reasons_k.append("strong_disp_ob")
                        if (not np.isnan(atr_val)) and atr_val > 0 and ob_size / atr_val >= 0.20:
                            score_k += 0.5
                            reasons_k.append("sized_bull_ob")

                    if has_fvg:
                        fvg_low = float(A_ufl[k])
                        fvg_high = float(A_ufh[k])
                        fvg_size = float(A_ufs[k]) if not np.isnan(A_ufs[k]) else 0.0
                        atr_val = float(A_atr[k]) if not np.isnan(A_atr[k]) else np.nan

                        score_k += 1.0
                        reasons_k.append("valid_bull_fvg")
                        if (not np.isnan(atr_val)) and atr_val > 0 and fvg_size / atr_val >= 0.15:
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
                            "sweep_ref": float(A_l[i]),
                            "expire_idx": min(k + zone_max_age, n - 1),
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


def evaluate_freshness_at_entry(h_arr, l_arr, structure, entry_idx):
    side = structure["type"]
    side_tag = "bull" if side == "long" else "bear"
    bonus = 0.0
    fresh_reasons = []

    if structure.get("has_ob"):
        if is_zone_fresh_at_entry(h_arr, l_arr, structure["zone_created_idx"], entry_idx,
                                   structure["ob_low"], structure["ob_high"]):
            bonus += 1.0
            fresh_reasons.append(f"fresh_{side_tag}_ob")

    if structure.get("has_fvg"):
        if is_zone_fresh_at_entry(h_arr, l_arr, structure["zone_created_idx"], entry_idx,
                                   structure["fvg_low"], structure["fvg_high"]):
            bonus += 0.5
            fresh_reasons.append(f"fresh_{side_tag}_fvg")

    return bonus, fresh_reasons


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


def apply_indicators_and_build(raw):
    symbol = raw["symbol"]
    df = raw["df_raw"].copy()
    df_h1 = raw["df_h1_raw"].copy()

    df = apply_basic_indicators(df)
    df = apply_mss(df, mss_lookback=H4_MSS_LOOKBACK)
    # feature/gate-tighten: H4 displacement 문턱을 env 로 (H1 호출 526 은 기본값 유지)
    df = apply_displacement(df, disp_body_ratio=DISP_BODY_RATIO, disp_atr_mult=DISP_ATR_MULT)
    df = apply_fvg(df)
    df = apply_ob(df, ob_lookback=H4_OB_LOOKBACK)
    df = apply_pd(df, pd_lookback=H4_PD_LOOKBACK)
    df = apply_pivots(df, swing_len=H4_PIVOT_SWING_LEN)
    df = apply_structure_bias(df)
    df = apply_choch(df, break_atr_mult=H4_CHOCH_BREAK_ATR_MULT)
    # feature/gate-tighten: MSS=choch 면 스윙 구조 기반 CHoCH 로 H4 MSS 대체 (legacy=롤링맥스 유지)
    if MSS_MODE == "choch":
        df["bull_mss"] = df["bull_choch"]
        df["bear_mss"] = df["bear_choch"]
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
