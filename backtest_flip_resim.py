"""PRZ 합류 거래만 방향 반전해 '실제 SL/TP·수수료'로 재백테스트 (정식 재시뮬).
엔진(smc_crypto_stage4d_atomic_decomposition.py)의 청산 코어를 바이트 그대로 복사(import 불가: top-level 실행).
검증 우선: 원방향 재시뮬 r_multiple == trades.csv r_multiple 이어야 미러링 정확(통과해야 반전결과 신뢰).
반전 정의: side만 뒤집고 진입가 동일, SL은 entry 기준 대칭(sl_flip=2*entry-sl → 동일 |R|). plan/수수료 동일.
PRZ 합류 = entry 직전 WINDOW봉 dominant swing(방향정합)에서 entry가 0.5~0.886 되돌림 구간. 룩어헤드 없음(상한=entry봉-1).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")

# ── 엔진 상수 (원본과 동일) ──
FEE_RATE = 0.0005
RUNNER_PROTECT_LOCKED_R = 0.30
RUNNER_PROXY_MAX_RR = 5.0
RUNNER_PROXY_TARGET3 = True
FAST_2R_BARS_MAX = 3
ABOVE_2R_BARS_MIN = 3
MAX_RR_AFTER_2R_MIN = 3.0
RUNNER_CANDIDATE_MIN_CONDS = 2
POST_2OF3_APPLY_USE_EXPANSION_FILTER = True
POST_2OF3_APPLY_MAX_RR_AFTER_2R = 1.5
RUNNER_PROTECT_ONLY_IF_BE_MOVED = True
USE_SEQ = True  # USE_SEQ_RUNNER_PROTECTION_BASELINE

WINDOW = 90          # PRZ 합류 판정 윈도우(H4봉). build_window_confluence_scan서 OOS 신호 강했던 스케일
PRZ = (0.5, 0.886)


# ========= 엔진 청산 코어 (원본 복사) =========
def get_tp_plan(expansion_state=False):
    if expansion_state:
        return {"name": "expansion", "targets": [(1.0, 0.15), (2.0, 0.15), (3.0, 0.10)],
                "runner_frac": 0.60, "trail_activate_rr": 4.0, "be_after_rr": 1.5, "max_hold_bars": 20}
    return {"name": "base", "targets": [(1.0, 0.25), (2.0, 0.20), (3.0, 0.15)],
            "runner_frac": 0.40, "trail_activate_rr": 3.0, "be_after_rr": 1.0, "max_hold_bars": 12}


def update_trailing_stop(df_local, j, side, current_stop, entry):
    if j - 1 < 0:
        return current_stop
    prev_high = df_local.loc[j - 1, "high"]; prev_low = df_local.loc[j - 1, "low"]
    prev_range = prev_high - prev_low
    atr_val = df_local.loc[j - 1, "atr"] if pd.notna(df_local.loc[j - 1, "atr"]) else 0.0
    if side == "long":
        candidate = prev_low + prev_range * 0.50 - atr_val * 0.10
        candidate = max(candidate, entry)
        return max(current_stop, candidate)
    candidate = prev_high - prev_range * 0.50 + atr_val * 0.10
    candidate = min(candidate, entry)
    return min(current_stop, candidate)


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
    remaining_qty = qty; realized_pnl = 0.0; exit_fees = 0.0; current_stop = sl
    be_moved = False; runner_active = False; exit_reason = None; exit_idx = None; exit_time = None
    entry_fee = abs(entry * qty) * fee_rate
    max_rr_seen = 0.0; runner_max_rr_seen = np.nan
    bars_to_2r = np.nan; bars_spent_above_2r = 0; current_consecutive_above_2r = 0; max_rr_after_2r = 0.0
    cond_count_final = 0; runner_candidate_2of3 = False; post_2of3_apply_ok = False; runner_protected = False
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
            bars_spent_above_2r += 1; current_consecutive_above_2r += 1
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
            be_moved = True; current_stop = entry; stop_type_last = "be"
        if plan["trail_activate_rr"] is not None and target["rr"] >= plan["trail_activate_rr"] and plan["runner_frac"] > 0:
            runner_active = True

    loop_end = len(df_local) if disable_time_exit_when_runner else min(len(df_local), entry_idx + max_hold_bars + 1)
    for j in range(entry_idx + 1, loop_end):
        bar_open = df_local.loc[j, "open"]; bar_high = df_local.loc[j, "high"]
        bar_low = df_local.loc[j, "low"]; bar_close = df_local.loc[j, "close"]
        favorable_rr = calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low)
        register_rr_stats(j, favorable_rr); update_max_rr(bar_high, bar_low)
        if remaining_qty <= eps:
            exit_reason = "all_targets"; exit_idx = j; exit_time = df_local.loc[j, "timestamp"]; break
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
                        remaining_qty = 0.0; exit_reason = "stop"; exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]; break
            else:
                if evt == "low":
                    for tgt in targets:
                        if (not tgt["hit"]) and (bar_low <= tgt["price"]):
                            hit_target(tgt)
                elif evt == "high":
                    if bar_high >= current_stop and remaining_qty > eps:
                        realized_pnl += (entry - current_stop) * remaining_qty
                        exit_fees += abs(current_stop * remaining_qty) * fee_rate
                        remaining_qty = 0.0; exit_reason = "stop"; exit_idx = j
                        exit_time = df_local.loc[j, "timestamp"]; break
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
            exit_reason = "time_exit"; exit_idx = j; exit_time = df_local.loc[j, "timestamp"]; break
        if disable_time_exit_when_runner and (j - entry_idx >= max_hold_bars) and (not runner_active) and (not runner_protected):
            if remaining_qty > eps:
                if side == "long":
                    realized_pnl += (bar_close - entry) * remaining_qty
                else:
                    realized_pnl += (entry - bar_close) * remaining_qty
                exit_fees += abs(bar_close * remaining_qty) * fee_rate
                remaining_qty = 0.0
            exit_reason = "time_exit_non_runner"; exit_idx = j; exit_time = df_local.loc[j, "timestamp"]; break
    if exit_reason is None:
        j = len(df_local) - 1; bar_close = df_local.loc[j, "close"]
        if remaining_qty > eps:
            if side == "long":
                realized_pnl += (bar_close - entry) * remaining_qty
            else:
                realized_pnl += (entry - bar_close) * remaining_qty
            exit_fees += abs(bar_close * remaining_qty) * fee_rate
            remaining_qty = 0.0
        exit_reason = "close_at_end"; exit_idx = j; exit_time = df_local.loc[j, "timestamp"]
    net_pnl = realized_pnl - entry_fee - exit_fees
    risk_amount = risk_per_unit * qty
    r_multiple = net_pnl / risk_amount if risk_amount > 0 else np.nan
    return {"exit_reason": exit_reason, "net_pnl": net_pnl, "r_multiple": r_multiple,
            "hold_bars": (exit_idx - entry_idx) if exit_idx is not None else np.nan}


def simulate_runner_no_time_exit(df_local, entry_idx, side, entry, sl, qty, plan):
    return _simulate_trade_with_plan_core(
        df_local=df_local, entry_idx=entry_idx, side=side, entry=entry, sl=sl,
        qty=qty, fee_rate=FEE_RATE, grade="B", plan=plan,
        use_seq_runner_protection=USE_SEQ, disable_time_exit_when_runner=True)


# ========= 데이터 =========
def add_atr(cdf):
    h = cdf["high"]; l = cdf["low"]; c = cdf["close"]
    tr1 = h - l; tr2 = (h - c.shift(1)).abs(); tr3 = (l - c.shift(1)).abs()
    cdf["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    cdf["atr"] = cdf["tr"].rolling(14).mean()
    return cdf


d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["et"].dt.year
for col in ["entry", "fill_entry", "avg_entry_exec", "sl", "qty", "net_pnl", "r_multiple"]:
    d[col] = pd.to_numeric(d.get(col), errors="coerce")
# expansion_state -> bool
d["exp_bool"] = d["expansion_state"].astype(str).str.lower().isin(["true", "1", "1.0"])
syms = sorted(d["symbol"].unique())

frames = {}
for s in syms:
    cdf = pd.read_parquet(os.path.join(DLC, f"{s}_4h.parquet")).reset_index(drop=True)
    cdf["timestamp"] = pd.to_datetime(cdf["timestamp"], utc=True)
    cdf = add_atr(cdf)
    pos = {t: i for i, t in enumerate(pd.DatetimeIndex(cdf["timestamp"]))}
    frames[s] = dict(df=cdf, pos=pos,
                     h=cdf["high"].values.astype(float), l=cdf["low"].values.astype(float))

n = len(d)
r_orig = np.full(n, np.nan); r_flip = np.full(n, np.nan)
prz_on = np.zeros(n, bool); ok = np.zeros(n, bool)

for r in range(n):
    s = d["symbol"].iat[r]; et = d["et"].iat[r]
    F = frames.get(s)
    if F is None or et not in F["pos"]:
        continue
    ent_idx = F["pos"][et]
    px = d["avg_entry_exec"].iat[r]
    if px != px:
        px = d["entry"].iat[r]
    sl = d["sl"].iat[r]; side = d["side"].iat[r]
    if px != px or sl != sl or abs(px - sl) <= 0:
        continue
    plan = get_tp_plan(bool(d["exp_bool"].iat[r]))
    # 원방향 재시뮬 (검증용) — qty=1 (r_multiple은 qty 독립)
    o = simulate_runner_no_time_exit(F["df"], ent_idx, side, px, sl, 1.0, plan)
    r_orig[r] = o["r_multiple"]
    # 반전: side 뒤집고 진입가 동일, SL 대칭(동일 |R|)
    flip_side = "short" if side == "long" else "long"
    sl_flip = 2.0 * px - sl
    f = simulate_runner_no_time_exit(F["df"], ent_idx, flip_side, px, sl_flip, 1.0, plan)
    r_flip[r] = f["r_multiple"]
    ok[r] = True
    # PRZ 합류 판정 (entry 직전 WINDOW봉 dominant swing, 방향정합)
    ei = ent_idx - 1
    sidx = ei - WINDOW + 1
    if ei >= 30 and sidx >= 0:
        wh = F["h"][sidx:ei + 1]; wl = F["l"][sidx:ei + 1]
        hi_i = int(np.argmax(wh)); lo_i = int(np.argmin(wl))
        hi = float(wh[hi_i]); lo = float(wl[lo_i]); leg = hi - lo
        fav = 1 if side == "long" else -1
        cd = 1 if hi_i > lo_i else -1
        if leg > 0 and cd == fav:
            frac = (hi - px) / leg if cd == 1 else (px - lo) / leg
            if PRZ[0] <= frac <= PRZ[1]:
                prz_on[r] = True

# ========= 검증 =========
tr_r = d["r_multiple"].to_numpy()
v = ok & np.isfinite(r_orig) & np.isfinite(tr_r)
err = np.abs(r_orig[v] - tr_r[v])
print("=" * 70)
print(f"[미러링 검증] 원방향 재시뮬 r_multiple vs trades.csv r_multiple  (n={int(v.sum())})")
print(f"  평균절대오차={err.mean():.4f}  중앙값={np.median(err):.4f}  "
      f"p95={np.quantile(err,0.95):.4f}  최대={err.max():.4f}")
print(f"  |오차|<0.05 비율={100*(err<0.05).mean():.1f}%   상관={np.corrcoef(r_orig[v],tr_r[v])[0,1]:.4f}")
print("  (오차가 작아야 청산엔진 미러링이 정확 → 반전결과 신뢰 가능)")

IS = d.year.isin([2023, 2024]).to_numpy(); OOS = d.year.isin([2025, 2026]).to_numpy()


def blk(name, mask):
    m = ok & mask & np.isfinite(r_orig) & np.isfinite(r_flip)
    if m.sum() == 0:
        print(f"  {name:24s} n=0"); return
    ro = r_orig[m]; rf = r_flip[m]
    print(f"  {name:24s} n={m.sum():4d} | orig avgR={ro.mean():+.3f} win={100*(ro>0).mean():4.1f}% sumR={ro.sum():+7.1f}"
          f"  ||  flip avgR={rf.mean():+.3f} win={100*(rf>0).mean():4.1f}% sumR={rf.sum():+7.1f}")


print("\n[PRZ 합류 부분집합: 원방향 vs 반전 (정식 SL/TP·수수료 재시뮬)]")
print(f"  PRZ 합류 거래수 IS={int((ok&prz_on&IS).sum())}  OOS={int((ok&prz_on&OOS).sum())}  (WINDOW={WINDOW}봉)")
blk("PRZ_on  IS", prz_on & IS)
blk("PRZ_on  OOS", prz_on & OOS)
blk("PRZ_off IS", (~prz_on) & IS)
blk("PRZ_off OOS", (~prz_on) & OOS)

print("\n[전략: PRZ합류만 반전 적용 시 전체 포트폴리오 (나머지는 원방향 유지)]")
r_strat = np.where(prz_on, r_flip, r_orig)
for span, sm in [("IS", IS), ("OOS", OOS)]:
    mb = ok & sm & np.isfinite(r_orig)
    base = r_orig[mb]; strat = r_strat[mb]
    print(f"  {span}: baseline(원본) avgR={base.mean():+.3f} win={100*(base[np.isfinite(base)]>0).mean():4.1f}% sumR={base.sum():+8.1f}"
          f"   →  PRZ반전 avgR={strat.mean():+.3f} win={100*(strat>0).mean():4.1f}% sumR={strat.sum():+8.1f}")
print("=" * 70)


# ========= 윈도우 스윕 (강건성: PRZ_on 반전이 윈도우 무관 양수 plateau인가) =========
def prz_mask(WIN):
    pm = np.zeros(n, bool)
    for r in range(n):
        if not ok[r]:
            continue
        s = d["symbol"].iat[r]; et = d["et"].iat[r]; F = frames[s]
        ei = F["pos"][et] - 1; sidx = ei - WIN + 1
        if ei < 30 or sidx < 0:
            continue
        px = d["avg_entry_exec"].iat[r]
        if px != px:
            px = d["entry"].iat[r]
        wh = F["h"][sidx:ei + 1]; wl = F["l"][sidx:ei + 1]
        hi_i = int(np.argmax(wh)); lo_i = int(np.argmin(wl))
        hi = float(wh[hi_i]); lo = float(wl[lo_i]); leg = hi - lo
        fav = 1 if d["side"].iat[r] == "long" else -1
        cd = 1 if hi_i > lo_i else -1
        if leg > 0 and cd == fav:
            frac = (hi - px) / leg if cd == 1 else (px - lo) / leg
            if PRZ[0] <= frac <= PRZ[1]:
                pm[r] = True
    return pm


WINS = [180, 120, 90, 60, 45, 30]
swrows = []
for WIN in WINS:
    pm = prz_mask(WIN)
    for span, sm in [("IS", IS), ("OOS", OOS)]:
        for label, sub in [("PRZ_on", pm), ("PRZ_off", ~pm)]:
            m = ok & sm & sub & np.isfinite(r_orig) & np.isfinite(r_flip)
            if m.sum() == 0:
                swrows.append(dict(window=WIN, span=span, subset=label, n=0))
                continue
            ro = r_orig[m]; rf = r_flip[m]
            swrows.append(dict(window=WIN, span=span, subset=label, n=int(m.sum()),
                               orig_avgR=round(float(ro.mean()), 3), orig_win=round(100 * (ro > 0).mean(), 1),
                               flip_avgR=round(float(rf.mean()), 3), flip_win=round(100 * (rf > 0).mean(), 1),
                               flip_minus_orig=round(float(rf.mean() - ro.mean()), 3)))
sweep = pd.DataFrame(swrows)

# PRZ_on vs PRZ_off의 flip 우위 (레짐과 분리)
edge_rows = []
for WIN in WINS:
    pm = prz_mask(WIN)
    for span, sm in [("IS", IS), ("OOS", OOS)]:
        mon = ok & sm & pm & np.isfinite(r_flip)
        moff = ok & sm & (~pm) & np.isfinite(r_flip)
        if mon.sum() and moff.sum():
            edge_rows.append(dict(window=WIN, span=span, n_on=int(mon.sum()),
                                  flip_on=round(float(r_flip[mon].mean()), 3),
                                  flip_off=round(float(r_flip[moff].mean()), 3),
                                  prz_edge=round(float(r_flip[mon].mean() - r_flip[moff].mean()), 3)))
edge = pd.DataFrame(edge_rows)

pd.set_option("display.width", 220)
print("\n[윈도우 스윕: PRZ_on/off 의 원방향 vs 반전 avgR (IS·OOS)]")
print(sweep.to_string(index=False))
print("\n[PRZ 순수엣지: PRZ_on flip - PRZ_off flip (레짐역전 제거 후 PRZ 고유 기여)]")
print("  윈도우 무관하게 IS·OOS 양쪽 양수면 PRZ 합류 자체가 진짜 역방향 시그널.")
print(edge.to_string(index=False))

# ========= 거래별 trade 로그 저장 (WINDOW=90 적용 전략) =========
entry_px = d["avg_entry_exec"].fillna(d["entry"])
qty_real = pd.to_numeric(d.get("qty"), errors="coerce").fillna(1.0)
risk_amt = (entry_px - d["sl"]).abs() * qty_real
span_arr = np.where(IS, "IS", np.where(OOS, "OOS", "other"))
flip_side_arr = np.where(d["side"].to_numpy() == "long", "short", "long")
applied_is_flip = prz_on
applied_side = np.where(applied_is_flip, flip_side_arr, d["side"].to_numpy())
r_applied = np.where(applied_is_flip, r_flip, r_orig)

log = pd.DataFrame({
    "symbol": d["symbol"], "entry_time": d["entry_time"], "year": d["year"], "span": span_arr,
    "orig_side": d["side"], "entry": entry_px.round(6), "sl": d["sl"].round(6),
    "sl_flip": (2.0 * entry_px - d["sl"]).round(6),
    "qty": qty_real.round(6), "risk_amount": risk_amt.round(4),
    "prz_on_w90": prz_on,
    "r_orig": np.round(r_orig, 4), "netpnl_orig": np.round(r_orig * risk_amt.to_numpy(), 4),
    "r_flip": np.round(r_flip, 4), "netpnl_flip": np.round(r_flip * risk_amt.to_numpy(), 4),
    "applied_side": applied_side, "applied_is_flip": applied_is_flip,
    "r_applied": np.round(r_applied, 4),
    "netpnl_applied": np.round(r_applied * risk_amt.to_numpy(), 4),
    "r_trades_csv": d["r_multiple"].round(4),
})
log = log[ok].reset_index(drop=True)

LOG_OUT = os.path.join(CDIR, "flip_trade_log.csv")
RES_OUT = os.path.join(CDIR, "flip_resim_results.xlsx")
log.to_csv(LOG_OUT, index=False, encoding="utf-8-sig")

# 검증 요약 + 부분집합 요약 시트
valid_err = pd.DataFrame([{"n": int(v.sum()), "mae": round(float(err.mean()), 6),
                           "p95": round(float(np.quantile(err, 0.95)), 6),
                           "max": round(float(err.max()), 6),
                           "corr": round(float(np.corrcoef(r_orig[v], tr_r[v])[0, 1]), 6)}])
subset_rows = []
for label, mask in [("PRZ_on_IS", prz_on & IS), ("PRZ_on_OOS", prz_on & OOS),
                    ("PRZ_off_IS", (~prz_on) & IS), ("PRZ_off_OOS", (~prz_on) & OOS)]:
    m = ok & mask & np.isfinite(r_orig) & np.isfinite(r_flip)
    ro = r_orig[m]; rf = r_flip[m]
    subset_rows.append(dict(subset=label, n=int(m.sum()),
                            orig_avgR=round(float(ro.mean()), 3), orig_win=round(100 * (ro > 0).mean(), 1),
                            orig_sumR=round(float(ro.sum()), 1),
                            flip_avgR=round(float(rf.mean()), 3), flip_win=round(100 * (rf > 0).mean(), 1),
                            flip_sumR=round(float(rf.sum()), 1)))
subset = pd.DataFrame(subset_rows)

with pd.ExcelWriter(RES_OUT, engine="openpyxl") as xw:
    valid_err.to_excel(xw, sheet_name="mirror_validation", index=False)
    subset.to_excel(xw, sheet_name="subset_w90", index=False)
    sweep.to_excel(xw, sheet_name="window_sweep", index=False)
    edge.to_excel(xw, sheet_name="prz_pure_edge", index=False)

print(f"\n[저장] 거래로그 -> {LOG_OUT}  ({len(log)}행)")
print(f"[저장] 결과요약 -> {RES_OUT}  (sheets: mirror_validation, subset_w90, window_sweep, prz_pure_edge)")
