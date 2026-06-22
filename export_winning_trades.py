"""양수(net_pnl>0) 트레이드만 추려 엑셀로 저장. net_pnl 내림차순.
사용: python export_winning_trades.py [trades_csv] [out_xlsx]
"""
import os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "atoms_doomcha_15m", "stage4d_trades.csv")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(TRADES), "winning_trades.xlsx")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["entry_time"].dt.year
# Excel 은 tz-aware datetime 미지원 → tz 제거(UTC naive)
for c in ["entry_time", "exit_time"]:
    if c in d.columns:
        dt = pd.to_datetime(d[c], utc=True, errors="coerce")
        d[c] = dt.dt.tz_localize(None)

W = d[d["net_pnl"] > 0].copy().sort_values("net_pnl", ascending=False).reset_index(drop=True)

# 읽기 좋게 핵심 컬럼 앞으로 재배치
front = ["symbol", "side", "entry_time", "exit_time", "net_pnl", "r_multiple", "result",
         "exit_reason", "hold_bars", "tier", "grade", "score", "run_potential",
         "entry", "fill_entry", "sl", "qty", "notional", "year"] + ATOMS
front = [c for c in front if c in W.columns]
rest = [c for c in W.columns if c not in front]
W = W[front + rest]

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    W.to_excel(xw, sheet_name="winning_trades", index=False)
    # 요약 시트: 연도/사이드/심볼/티어별 양수거래 수·총이익·평균R
    def grp(col):
        g = W.groupby(col).agg(win_n=("net_pnl", "size"),
                               profit=("net_pnl", "sum"),
                               avgR=("r_multiple", "mean")).reset_index()
        return g.sort_values("profit", ascending=False)
    row = 0
    summ = pd.ExcelWriter  # noqa
    for col in ["year", "side", "symbol", "tier"]:
        if col in W.columns:
            g = grp(col)
            g.insert(0, "group", col)
            g.to_excel(xw, sheet_name="summary", index=False, startrow=row)
            row += len(g) + 2

print(f"양수 트레이드 {len(W)}개 → {OUT}")
print(f"  총이익 {W['net_pnl'].sum():.0f} | 평균 net_pnl {W['net_pnl'].mean():.1f}"
      f" | 평균R {W['r_multiple'].mean():+.3f}")
print(f"  연도별 양수거래수: " + ", ".join(f"{int(y)}:{int((W.year==y).sum())}" for y in sorted(W.year.dropna().unique())))
print(f"  TOP5 net_pnl: " + ", ".join(f"{r.symbol} {r.net_pnl:.0f}" for r in W.head(5).itertuples()))
