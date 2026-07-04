#!/usr/bin/env python3
# ★36h + 라이브 R래칫 트레일 + 15%캡 (기준 V2, 15m fill) 정식 trade log 저장.
import os
import numpy as np, pandas as pd
import run_reconcile as R
import run_15m_mtf as M
import run_trail_compare as T

EH = 36.0; CD = 8.0; CAP = 0.15
OUT = "reconcile_result/cap15_expiry36h_v2_Rratchet"


def main():
    os.makedirs(OUT, exist_ok=True)
    print("[R래칫] 15m + H4스케일 atr 로드 → R래칫 재체결")
    d15 = M.load_15m()
    tr = pd.read_csv("walkforward_result/trades_v4.csv")
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    rl, ex_rl = T.resim(tr, d15, live_trail=True)          # 라이브 R래칫 r
    trm = tr[["symbol", "entry_time"]].copy(); trm["r_rratchet"] = rl
    trm["exit_time_rratchet"] = pd.to_datetime(pd.Series(ex_rl), utc=True)

    d, rp = R.load()
    d = d.merge(trm, on=["symbol", "entry_time"], how="left")
    d["expiry_blocked"] = (d["hours_to_expiry"] <= EH)
    rp2 = np.minimum(rp, CAP)
    rv = d["r_rratchet"].fillna(d["r"]).values             # 재현 실패분은 r15m 대체

    fin, mdd, mw, cc, taken, pnl = R.equity(d, rv, rp2, d["expiry_blocked"].values, d["pretp1"].values, CD)

    dd = d.copy()
    dd["applied_risk_pct"] = rp2 * 100
    dd["r_rratchet"] = np.round(rv, 4)
    dd["hours_to_expiry"] = dd["hours_to_expiry"].round(1)
    dd["taken"] = taken; dd["pnl_krw"] = np.round(pnl)
    keep = ["symbol", "entry_time", "exit_time", "exit_time_rratchet", "side", "setup", "matched_rule",
            "r_multiple", "r15m", "r_rratchet", "hours_to_expiry", "expiry_blocked", "applied_risk_pct", "pretp1", "taken", "pnl_krw"]
    keep = [c for c in keep if c in dd.columns]
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
    pf = R._pf(pnl[taken]); win = (pnl[taken] > 0).mean() * 100; used = int((~np.isnan(rl)).sum())

    with open(f"{OUT}/README.md", "w", encoding="utf-8") as f:
        f.write(f"""# 만기컷 36h + 라이브 R래칫 트레일 + 15%캡 (기준 V2)

## 구성
- 기준 V2: **8h 양방향 EXIT 쿨다운**(TP1 전 청산만) + reverse_risk×1.2, 24·25제거, killer 3.5%캡
- ★**리스크캡 15%** (120% 걸던 소표본 4거래만 실효 타깃)
- ★**트레일링 = 라이브 R래칫**: 3R서 1R 잠금, +1R rr마다 +0.5R 상향 (백테 ATR트레일 아님)
- **만기컷 36h** | 체결 = 15m fill (H4스케일 atr 매핑, R래칫 재체결 {used}/{len(tr)}건)
- 자본: KRW1540/시드500만/월250만×5/fee0.00055편도/max_notional3배/MDD=settled

## 결과
| 지표 | 값 |
|---|---|
| 거래(taken) | {int(taken.sum())} |
| 승률 | {win:.1f}% |
| PF | {pf} |
| 최종자본 | {fin:,.0f}원 ({fin/1e8:.2f}억) |
| MDD(settled) | {mdd:.2f}% ({mw}) |
| 은퇴 | {retire} |

## 파일
- `trades.csv` — `r15m`(백테트레일) + **`r_rratchet`**(R래칫, 성과계산에 사용) 둘 다 포함, `exit_time_rratchet`·applied_risk·taken·pnl_krw
- `capital_curve.csv` — settled 자본곡선 / `monthly.csv` — 월별

⚠️ R래칫은 백테 트레일(−17%대) 대비 MDD −27%대. 수익 큰 대신 낙폭 깊음.
""")
    print(f"[저장] {OUT}/ | 거래 {int(taken.sum())} PF {pf} 최종 {fin/1e8:.2f}억 MDD {mdd:.2f}% ({mw}) 은퇴 {retire}")


if __name__ == "__main__":
    main()
