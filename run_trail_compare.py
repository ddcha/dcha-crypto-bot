#!/usr/bin/env python3
# ★트레일링 비교: 백테엔진 트레일(직전봉 range중점−0.1×H4ATR) vs 라이브 R래칫(3R서 1R잠금, +1R마다 +0.5R).
#   같은 엔진(_simulate_trade_with_plan_core)·같은 15m봉·같은 TP/러너활성(3R) — update_trailing_stop 수식만 몽키패치해 격리.
#   결과: r분포 비교 + 라이브일치 자본시뮬(2%캡)로 최종자본/MDD 비교.
import os
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
import numpy as np, pandas as pd
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import get_tp_plan, _simulate_trade_with_plan_core
from smc_stage4d.config import FEE_RATE, USE_SEQ_RUNNER_PROTECTION_BASELINE
import run_15m_mtf as M          # load_15m (15m+H4스케일 atr), BARS, SYMBOLS
import run_reconcile as R        # equity, load(risk_map/cap 로직)

FOUR_H = np.timedelta64(4, "h")
_ORIG_TRAIL = sim.update_trailing_stop
_LIVE = {"rpu": 0.0, "act": 3.0}   # 라이브 R래칫용 (거래별 set)


def _live_trail(df_local, j, side, current_stop, entry):
    """라이브 R래칫 트레일: rr>=act 서 1R 잠금, +1R rr마다 +0.5R 상향. 직전봉(j-1) 유리극값으로 rr 산정(무룩어헤드·단조클램프)."""
    if j - 1 < 0:
        return current_stop
    rpu = _LIVE["rpu"]
    if rpu <= 0:
        return current_stop
    if side == "long":
        rr = (df_local.loc[j - 1, "high"] - entry) / rpu
    else:
        rr = (entry - df_local.loc[j - 1, "low"]) / rpu
    act = _LIVE["act"]
    if rr < act:
        return current_stop
    steps = int(max(0.0, rr - act) // 1.0)           # step_rr=1.0
    lock_rr = 1.0 + steps * 0.5                       # start_lock 1.0R, increment 0.5R
    if side == "long":
        return max(current_stop, entry + rpu * lock_rr)
    return min(current_stop, entry - rpu * lock_rr)


def resim(trades, d15, live_trail):
    r = np.full(len(trades), np.nan); ex = [None] * len(trades)
    bmap = {s: d15[s]["timestamp"].values for s in M.SYMBOLS}
    for ii, t in trades.reset_index(drop=True).iterrows():
        s = t["symbol"]
        if s not in d15:
            continue
        df = d15[s]; bts = bmap[s]
        et = np.datetime64(pd.Timestamp(t["entry_time"]).tz_convert("UTC").tz_localize(None))
        pos = int(np.searchsorted(bts, et + FOUR_H, side="left")); entry_idx = pos - 1
        if entry_idx < 0 or entry_idx >= len(df) - 2:
            continue
        plan = dict(get_tp_plan(str(t.get("tp_plan_name", "base")) == "expansion"))
        plan["max_hold_bars"] = int(plan["max_hold_bars"] * M.BARS)
        _LIVE["rpu"] = abs(float(t["fill_entry"]) - float(t["sl"])); _LIVE["act"] = float(plan["trail_activate_rr"])
        sim.update_trailing_stop = _live_trail if live_trail else _ORIG_TRAIL
        try:
            res = _simulate_trade_with_plan_core(
                df_local=df, entry_idx=entry_idx, side=t["side"], entry=float(t["fill_entry"]), sl=float(t["sl"]),
                qty=1.0, fee_rate=FEE_RATE, grade=t.get("grade", "C"), plan=plan,
                use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE, disable_time_exit_when_runner=False)
            rm = res["r_multiple"]
            if rm is not None and not np.isnan(rm):
                r[ii] = rm; ex[ii] = res.get("exit_time")
        except Exception:
            pass
    sim.update_trailing_stop = _ORIG_TRAIL
    return r, ex


def _pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return round(g / l, 3) if l > 0 else 0.0


def main():
    print("[트레일 비교] 15m + H4스케일 atr 로드")
    d15 = M.load_15m()
    tr = pd.read_csv("walkforward_result/trades_v4.csv")
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)

    print("  re-sim: 백테 트레일(원본)"); rb, _ = resim(tr, d15, live_trail=False)
    print("  re-sim: 라이브 R래칫"); rl, _ = resim(tr, d15, live_trail=True)
    ok = (~np.isnan(rb)) & (~np.isnan(rl)); n = int(ok.sum())
    a, b = rb[ok], rl[ok]
    print(f"\n=== r 분포 (재현 {n}건) ===")
    print(f"  백테 트레일 : PF {_pf(a)} | 승률 {(a>0).mean()*100:.1f}% | expR {a.mean():+.4f} | rSum {a.sum():.1f} | maxR {a.max():.1f}")
    print(f"  라이브 R래칫: PF {_pf(b)} | 승률 {(b>0).mean()*100:.1f}% | expR {b.mean():+.4f} | rSum {b.sum():.1f} | maxR {b.max():.1f}")
    diff = b - a
    print(f"  차이(라이브−백테): 더나음 {int((diff>1e-9).sum())} 더나쁨 {int((diff<-1e-9).sum())} 동일 {int((np.abs(diff)<=1e-9).sum())} | expR차 {b.mean()-a.mean():+.4f}")

    # ── 자본시뮬: 기준 V2(8h 양방향쿨다운) + 15%캡(120% 4거래만 타깃, =전역15%) ──
    CD = 8.0                                          # ③ 8h 양방향 쿨다운
    CAP = 0.15                                        # ★리스크캡 15%
    d, rp = R.load()                                  # baseline setup/risk (r15m 기반)
    rp2 = np.minimum(rp, CAP)                         # 15%캡
    trm = tr[["symbol", "entry_time"]].copy(); trm["rb"] = rb; trm["rl"] = rl
    d = d.merge(trm, on=["symbol", "entry_time"], how="left")

    print(f"\n=== 트레일링 × 만기컷 그리드 @ V2 + 15%캡 (8h쿨다운) ===")
    print(f"  {'만기컷':>5s} | {'트레일링':10s} | {'거래':>4s} | {'PF':>5s} | {'최종':>7s} | {'MDD':>7s}")
    print("  " + "-" * 72)
    for eh in (30.0, 36.0, 42.0):
        blk = (d["hours_to_expiry"] <= eh).values
        for col, tag in [("rb", "백테 트레일"), ("rl", "라이브 R래칫")]:
            rv = d[col].fillna(d["r"]).values
            fin, mdd, mw, cc, taken, pnl = R.equity(d, rv, rp2, blk, d["pretp1"].values, CD)
            print(f"  {int(eh):3d}h  | {tag:10s} | {int(taken.sum()):4d} | {_pf(pnl[taken]):5.3f} | {fin/1e8:6.2f}억 | {mdd:6.2f}% ({mw})")
        print("  " + "-" * 72)


if __name__ == "__main__":
    main()
