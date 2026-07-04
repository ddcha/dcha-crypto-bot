#!/usr/bin/env python3
# ★SL 배수 실험: 스톱거리 ×{1.0, 0.75, 0.5} 로 15m 재체결 → 자본시뮬 비교.
#   기준 A(백테 트레일)·15%캡·V2(8h쿨다운)·만기컷 36h·15m fill.
#   포인트: risk% 사이징이라 −1R KRW손실은 배수무관 동일. 스톱↓ → 풀스탑률↑·승자R↑(재분포).
import os
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
import numpy as np, pandas as pd
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import get_tp_plan, _simulate_trade_with_plan_core
from smc_stage4d.config import FEE_RATE, USE_SEQ_RUNNER_PROTECTION_BASELINE
import run_15m_mtf as M
import run_reconcile as R

FOUR_H = np.timedelta64(4, "h"); EH = 36.0; CD = 8.0; CAP = 0.15


def resim_sl(trades, d15, sl_mult):
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
        entry = float(t["fill_entry"]); sl0 = float(t["sl"])
        sl = entry + sl_mult * (sl0 - entry)                      # ★스톱거리 배수
        plan = dict(get_tp_plan(str(t.get("tp_plan_name", "base")) == "expansion"))
        plan["max_hold_bars"] = int(plan["max_hold_bars"] * M.BARS)
        try:
            res = _simulate_trade_with_plan_core(
                df_local=df, entry_idx=entry_idx, side=t["side"], entry=entry, sl=sl,
                qty=1.0, fee_rate=FEE_RATE, grade=t.get("grade", "C"), plan=plan,
                use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE, disable_time_exit_when_runner=False)
            rm = res["r_multiple"]
            if rm is not None and not np.isnan(rm):
                r[ii] = rm; ex[ii] = res.get("exit_time")
        except Exception:
            pass
    return r, ex


def main():
    print("[SL실험] 15m + H4스케일 atr 로드")
    d15 = M.load_15m()
    tr = pd.read_csv("walkforward_result/trades_v4.csv")
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)

    d0, rp = R.load()
    d0["expiry_blocked"] = (d0["hours_to_expiry"] <= EH)
    rp2 = np.minimum(rp, CAP)

    print(f"\n=== SL 배수 실험 @ A(백테트레일)·15%캡·V2·만기컷{int(EH)}h·15m fill ===")
    print(f"  {'SL배수':>6s} | {'재현':>4s} | {'풀스탑률':>7s} | {'승률':>5s} | {'expR':>6s} | {'거래':>4s} | {'PF':>5s} | {'최종':>7s} | {'MDD':>7s}")
    print("  " + "-" * 100)
    for mult in (1.0, 1.5, 2.0, 2.5):
        rN, exN = resim_sl(tr, d15, mult)
        ok = ~np.isnan(rN); used = int(ok.sum())
        fullstop = float((rN[ok] <= -0.99).mean() * 100)          # ≈−1R 풀스탑 비율
        win = float((rN[ok] > 0).mean() * 100); expR = float(np.nanmean(rN[ok]))
        # 자본시뮬: 새 r + 새 sl(사이징 rpu 배수)
        d = d0.copy()
        trm = tr[["symbol", "entry_time"]].copy(); trm["rN"] = rN
        d = d.merge(trm, on=["symbol", "entry_time"], how="left")
        d["rv"] = d["rN"].fillna(d["r"])
        d["sl_scaled"] = d["entry"] + mult * (d["sl"] - d["entry"])  # 사이징도 좁은 스톱 반영
        d_eq = d.copy(); d_eq["sl"] = d["sl_scaled"]
        fin, mdd, mw, cc, taken, pnl = R.equity(d_eq, d["rv"].values, rp2, d["expiry_blocked"].values, d["pretp1"].values, CD)
        pf = R._pf(pnl[taken])
        print(f"  {mult:5.2f}x | {used:4d} | {fullstop:6.1f}% | {win:4.1f}% | {expR:+.3f} | {int(taken.sum()):4d} | {pf:5.3f} | {fin/1e8:6.2f}억 | {mdd:6.2f}% ({mw})")


if __name__ == "__main__":
    main()
