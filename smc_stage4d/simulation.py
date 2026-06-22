# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.simulation
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403
from .tiers import *  # noqa: F401,F403
from .structures import *  # noqa: F401,F403
from .filters import *  # noqa: F401,F403



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
            fresh_bonus, fresh_reasons = evaluate_freshness_at_entry(_h, _l, s, i)
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
                    # ⭐ 존 구성 원본(only_OB / only_FVG / both 3분할 분석용) — build_structures reasons에서 정확 복원
                    "zone_has_ob":  bool(("valid_bull_ob"  in _struct_reasons_raw) or ("valid_bear_ob"  in _struct_reasons_raw)),
                    "zone_has_fvg": bool(("valid_bull_fvg" in _struct_reasons_raw) or ("valid_bear_fvg" in _struct_reasons_raw)),
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
