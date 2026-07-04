#!/usr/bin/env python3
# 만기컷 30h·36h 결과를 정식 폴더로 저장 (기준 V2: 8h양방향쿨다운·2%캡없음·백테 트레일=r15m).
import os
import numpy as np, pandas as pd
import run_reconcile as R

CD = 8.0; OUTROOT = "reconcile_result"; CAP = 0.15   # ★리스크캡 15%


def save_one(d, rp, eh):
    rp = np.minimum(rp, CAP)                          # 15%캡 적용(120% 4거래만 실효 타깃)
    out = f"{OUTROOT}/cap15_expiry{int(eh)}h_v2"; os.makedirs(out, exist_ok=True)
    blk = (d["hours_to_expiry"] <= eh).values
    fin, mdd, mw, cc, taken, pnl = R.equity(d, d["r"].values, rp, blk, d["pretp1"].values, CD)
    dd = d.copy()
    dd["applied_risk_pct"] = rp * 100
    dd["hours_to_expiry"] = dd["hours_to_expiry"].round(1)
    dd["expiry_blocked"] = blk
    dd["taken"] = taken
    dd["pnl_krw"] = np.round(pnl)
    keep = ["symbol", "entry_time", "exit_time", "exit_time_15m", "side", "setup", "matched_rule",
            "r_multiple", "r15m", "hours_to_expiry", "expiry_blocked", "applied_risk_pct", "pretp1", "taken", "pnl_krw"]
    keep = [c for c in keep if c in dd.columns]
    dd[keep].to_csv(f"{out}/trades.csv", index=False)
    cc.reset_index().rename(columns={"t": "time", "b": "balance"}).to_csv(f"{out}/capital_curve.csv", index=False)
    # monthly + 은퇴
    dd["em"] = dd["exit_time"].dt.strftime("%Y-%m")
    depm = {(pd.Timestamp(dd["entry_time"].min()).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): R.MON for k in range(R.ND)}
    mp = dd[dd["taken"]].groupby("em")["pnl_krw"].sum(); rows = []; run = R.INIT; tin = R.INIT
    for mo in sorted(mp.index):
        dep = depm.get(mo, 0); pl = float(mp[mo]); run += dep + pl; tin += dep
        rows.append({"month": mo, "deposit": dep, "pnl": round(pl), "balance": round(run), "cumRet%": round((run - tin) / tin * 100, 1)})
    m = pd.DataFrame(rows); m["ma3"] = m["pnl"].rolling(3).mean()
    m.to_csv(f"{out}/monthly.csv", index=False)
    h = m[m["ma3"] >= 10_000_000]; retire = f"{h.iloc[0]['month']}" if len(h) else "미도달"
    pf = R._pf(pnl[taken]); win = (pnl[taken] > 0).mean() * 100
    with open(f"{out}/README.md", "w", encoding="utf-8") as f:
        f.write(f"""# 만기컷 {int(eh)}h + 15%캡 백테스트 결과 (기준 V2)

## 구성
- 기준 V2: **8h 양방향 EXIT 쿨다운**(TP1 전 청산만) + reverse_risk×1.2, 24·25제거, killer 3.5%캡
- ★**리스크캡 15%**: 120% 걸던 소표본 4거래만 실효 타깃(15%초과=그 4건뿐, min(risk,15%))
- 트레일링: **백테 엔진**(직전봉 range중점−0.1×H4ATR, r15m 재체결)
- **만기컷 {int(eh)}h** (월간만기 잔여 ≤{int(eh)}h 진입 스킵)
- 자본: KRW1540/시드500만/월250만×5/fee0.00055편도/max_notional3배/MDD=settled(봉단위)

## 결과
| 지표 | 값 |
|---|---|
| 거래(taken) | {int(taken.sum())} |
| 승률 | {win:.1f}% |
| PF | {pf} |
| 최종자본 | {fin:,.0f}원 ({fin/1e8:.2f}억) |
| MDD(settled) | {mdd:.2f}% ({mw}) |
| 은퇴(3개월평균 월≥1000만) | {retire} |

## 파일
- `trades.csv` — 거래별 로그(r15m·applied_risk_pct·pretp1·taken·pnl_krw)
- `capital_curve.csv` — settled 봉단위 자본곡선
- `monthly.csv` — 월별 손익·잔고·누적수익률·ma3

※ 참고: V2는 백테 무캡(최대 120%) 기준 — 라이브 2%캡 실제치는 별도(더 낮음).
""")
    print(f"[저장] {out}/ | 거래 {int(taken.sum())} PF {pf} 최종 {fin/1e8:.2f}억 MDD {mdd:.2f}% 은퇴 {retire}")
    return out


def main():
    d, rp = R.load()
    os.makedirs(OUTROOT, exist_ok=True)
    for eh in (30.0, 36.0):
        save_one(d, rp, eh)


if __name__ == "__main__":
    main()
