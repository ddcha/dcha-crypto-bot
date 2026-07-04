#!/usr/bin/env python3
# ★기존 라이브 조건 vs 현재 백테 조건 head-to-head (15m fill, V2 8h쿨다운·구조적SL1.0x·notional3배 공통).
#   기존 라이브 = R래칫 트레일 + 2%캡 + 만기컷48h
#   현재 백테  = 백테 트레일   + 15%캡 + 만기컷36h  (참고로 30h 도 표시)
import os
import numpy as np, pandas as pd
import run_reconcile as R
import run_15m_mtf as M
import run_trail_compare as T

CD = 8.0; OUTROOT = "reconcile_result"


def retire(d, taken, pnl):
    dd = d.copy(); dd["pnl_krw"] = np.round(pnl); dd["taken"] = taken; dd["em"] = dd["exit_time"].dt.strftime("%Y-%m")
    depm = {(pd.Timestamp(dd["entry_time"].min()).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): R.MON for k in range(R.ND)}
    mp = dd[dd["taken"]].groupby("em")["pnl_krw"].sum(); run = R.INIT; rows = []
    for mo in sorted(mp.index):
        run += depm.get(mo, 0) + float(mp[mo]); rows.append(float(mp[mo]))
    ma3 = pd.Series(rows).rolling(3).mean(); h = np.where(ma3 >= 10_000_000)[0]
    return sorted(mp.index)[h[0]] if len(h) else "미도달"


def save(d, rv, rp2, blk, tag, out, meta):
    os.makedirs(out, exist_ok=True)
    fin, mdd, mw, cc, taken, pnl = R.equity(d, rv, rp2, blk, d["pretp1"].values, CD)
    ret = retire(d, taken, pnl); pf = R._pf(pnl[taken]); win = (pnl[taken] > 0).mean() * 100
    dd = d.copy(); dd["applied_risk_pct"] = rp2 * 100; dd["r_used"] = np.round(rv, 4)
    dd["taken"] = taken; dd["pnl_krw"] = np.round(pnl); dd["expiry_blocked"] = blk
    keep = [c for c in ["symbol", "entry_time", "exit_time", "side", "setup", "matched_rule", "r15m", "r_used",
                        "hours_to_expiry", "expiry_blocked", "applied_risk_pct", "pretp1", "taken", "pnl_krw"] if c in dd.columns]
    dd[keep].to_csv(f"{out}/trades.csv", index=False)
    cc.reset_index().rename(columns={"t": "time", "b": "balance"}).to_csv(f"{out}/capital_curve.csv", index=False)
    with open(f"{out}/README.md", "w", encoding="utf-8") as f:
        f.write(f"# {tag}\n\n{meta}\n\n## 결과\n| 지표 | 값 |\n|---|---|\n"
                f"| 거래 | {int(taken.sum())} |\n| 승률 | {win:.1f}% |\n| PF | {pf} |\n"
                f"| 최종자본 | {fin:,.0f}원 ({fin/1e8:.2f}억) |\n| MDD | {mdd:.2f}% ({mw}) |\n| 은퇴 | {ret} |\n\n"
                f"15m fill · V2(8h쿨다운) · 구조적SL 1.0x · notional 3배.\n")
    return dict(tag=tag, taken=int(taken.sum()), win=win, pf=pf, fin=fin, mdd=mdd, mw=mw, ret=ret)


def main():
    print("[live vs bt] 15m + H4스케일 atr 로드 → 백테트레일·R래칫 재체결")
    d15 = M.load_15m()
    tr = pd.read_csv("walkforward_result/trades_v4.csv")
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    rb, _ = T.resim(tr, d15, live_trail=False)      # 백테 트레일
    rl, _ = T.resim(tr, d15, live_trail=True)       # R래칫(라이브)

    d, rp = R.load()
    trm = tr[["symbol", "entry_time"]].copy(); trm["rb"] = rb; trm["rl"] = rl
    d = d.merge(trm, on=["symbol", "entry_time"], how="left")
    hte = d["hours_to_expiry"].values

    rows = []
    # 기존 라이브: R래칫 + 2%캡 + 48h
    rows.append(save(d, d["rl"].fillna(d["r"]).values, np.minimum(rp, 0.02), hte <= 48.0,
                     "기존 라이브 조건 (R래칫·2%캡·만기48h)", f"{OUTROOT}/CMP_live_Rratchet_2pct_48h",
                     "- 트레일링 **R래칫**(3R서 1R잠금) / 리스크캡 **2%** / 만기컷 **48h**"))
    # 현재 백테: 백테트레일 + 15%캡 + 36h
    rows.append(save(d, d["rb"].fillna(d["r"]).values, np.minimum(rp, 0.15), hte <= 36.0,
                     "현재 백테 조건 (백테트레일·15%캡·만기36h)", f"{OUTROOT}/CMP_bt_trail_15pct_36h",
                     "- 트레일링 **백테**(직전봉range−0.1ATR) / 리스크캡 **15%** / 만기컷 **36h**"))
    # 참고: 현재 백테 30h
    fin, mdd, mw, cc, taken, pnl = R.equity(d, d["rb"].fillna(d["r"]).values, np.minimum(rp, 0.15), hte <= 30.0, d["pretp1"].values, CD)
    rows.append(dict(tag="현재 백테 (백테트레일·15%캡·만기30h)", taken=int(taken.sum()), win=(pnl[taken] > 0).mean() * 100,
                     pf=R._pf(pnl[taken]), fin=fin, mdd=mdd, mw=mw, ret=retire(d, taken, pnl)))

    print(f"\n{'조건':40s} | {'거래':>4s} | {'승률':>5s} | {'PF':>5s} | {'최종':>8s} | {'MDD':>8s}    | 은퇴")
    print("-" * 120)
    for r in rows:
        print(f"{r['tag']:40s} | {r['taken']:4d} | {r['win']:4.1f}% | {r['pf']:5.3f} | {r['fin']/1e8:6.2f}억 | {r['mdd']:6.2f}% | {r['ret']} ({r['mw'] if 'mw' in r else ''})")


if __name__ == "__main__":
    main()
