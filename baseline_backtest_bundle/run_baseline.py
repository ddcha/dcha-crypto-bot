#!/usr/bin/env python3
# ★확정 기준 백테스트 — 단일 실행. 이 폴더 안에서 `python run_baseline.py` 만 하면 62.52억 재현.
#   입력: walkforward_result/trades_v4.csv (H4 v4거래) + mtf15_result/trades_v4_15m.csv (15m 재체결 r15m)
#   확정 조건: 백테트레일(=r15m) · 15%캡 · 만기36h · 8h양방향쿨다운 · 구조적SL1.0x · notional3배 · 15m fill
import os
import numpy as np, pandas as pd
import run_reconcile as R

CAP = 0.15; EH = 36.0; CD = 8.0; OUT = "result"


def main():
    os.makedirs(OUT, exist_ok=True)
    d, rp = R.load()                                    # 두 CSV 병합 + reverse_risk·24/25·killer·pretp1
    d["expiry_blocked"] = (d["hours_to_expiry"] <= EH)  # 만기컷 36h
    rp2 = np.minimum(rp, CAP)                           # 리스크캡 15% (120% 3조합만 실효 타깃)
    fin, mdd, mw, cc, taken, pnl = R.equity(d, d["r"].values, rp2, d["expiry_blocked"].values, d["pretp1"].values, CD)

    dd = d.copy(); dd["applied_risk_pct"] = rp2 * 100; dd["taken"] = taken; dd["pnl_krw"] = np.round(pnl)
    dd["hours_to_expiry"] = dd["hours_to_expiry"].round(1)
    keep = [c for c in ["symbol", "entry_time", "exit_time", "side", "setup", "matched_rule", "r_multiple", "r15m",
                        "hours_to_expiry", "expiry_blocked", "applied_risk_pct", "pretp1", "taken", "pnl_krw"] if c in dd.columns]
    dd[keep].to_csv(f"{OUT}/trades.csv", index=False)
    cc.reset_index().rename(columns={"t": "time", "b": "balance"}).to_csv(f"{OUT}/capital_curve.csv", index=False)

    dd["em"] = dd["exit_time"].dt.strftime("%Y-%m")
    depm = {(pd.Timestamp(dd["entry_time"].min()).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): R.MON for k in range(R.ND)}
    mp = dd[dd["taken"]].groupby("em")["pnl_krw"].sum(); rows = []; run = R.INIT; tin = R.INIT
    for mo in sorted(mp.index):
        dep = depm.get(mo, 0); pl = float(mp[mo]); run += dep + pl; tin += dep
        rows.append({"month": mo, "deposit": dep, "pnl": round(pl), "balance": round(run), "cumRet%": round((run - tin) / tin * 100, 1)})
    m = pd.DataFrame(rows); m["ma3"] = m["pnl"].rolling(3).mean(); m.to_csv(f"{OUT}/monthly.csv", index=False)
    h = m[m["ma3"] >= 10_000_000]; retire = f"{h.iloc[0]['month']}" if len(h) else "미도달"

    print("═══ 확정 기준 백테스트 (백테트레일·15%캡·만기36h·15m fill) ═══")
    print(f"  거래(taken) {int(taken.sum())} | 승률 {(pnl[taken]>0).mean()*100:.1f}% | PF {R._pf(pnl[taken])}")
    print(f"  최종자본 {fin:,.0f}원 ({fin/1e8:.2f}억) | MDD {mdd:.2f}% ({mw}) | 은퇴 {retire}")
    print(f"  [저장] {OUT}/ (trades.csv, capital_curve.csv, monthly.csv)")
    print(f"  ※ 기대값: 62.52억 / MDD -17.75% / 은퇴 2024-01")


if __name__ == "__main__":
    main()
