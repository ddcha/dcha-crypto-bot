"""MIN_SCORE 7.5 floor 있음(atoms_corr) vs 제거(atoms_corr_noscore) 비교.
거래수 / base PF / IS·OOS PF / avgR / 승률 / 점수분포. OOS=2025-26.
score<7.5 구간이 실제로 얼마나 생기고 그 구간 edge가 +인지 -인지를 본다.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")          # floor 7.5
B = os.path.join(ROOT, "stage4d_honest", "atoms_corr_noscore", "stage4d_trades.csv")  # floor 제거
OUT = os.path.join(ROOT, "stage4d_honest", "atoms_corr_noscore", "compare_noscore.xlsx")


def pf(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


da = pd.read_csv(A); db = pd.read_csv(B)
rows = []
for d, lab in [(da, "floor7.5"), (db, "no_floor")]:
    d2 = d.copy()
    d2["yr"] = pd.to_datetime(d2["entry_time"], errors="coerce").dt.year
    d2["net_pnl"] = pd.to_numeric(d2["net_pnl"], errors="coerce")
    d2["r_multiple"] = pd.to_numeric(d2.get("r_multiple"), errors="coerce")
    for tag, m in [("ALL", d2.yr.notna()),
                   ("IS_23_24", d2.yr.isin([2023, 2024])),
                   ("OOS_25_26", d2.yr.isin([2025, 2026]))]:
        x = d2[m]
        rows.append(dict(set=lab, span=tag, n=int(len(x)),
                         PF=round(pf(x.net_pnl), 3),
                         avgR=round(float(x.r_multiple.mean()), 3) if len(x) else np.nan,
                         win=round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan,
                         net=round(float(x.net_pnl.sum()), 1)))
summary = pd.DataFrame(rows)

# no_floor 에서 새로 생긴 score<7.5 구간만 따로
db2 = db.copy()
db2["score"] = pd.to_numeric(db2["score"], errors="coerce")
db2["yr"] = pd.to_datetime(db2["entry_time"], errors="coerce").dt.year
db2["net_pnl"] = pd.to_numeric(db2["net_pnl"], errors="coerce")
db2["r_multiple"] = pd.to_numeric(db2.get("r_multiple"), errors="coerce")
band_rows = []
for lo, hi in [(0, 7.5), (7.5, 999)]:
    m = (db2.score >= lo) & (db2.score < hi)
    for tag, mm in [("ALL", m), ("IS", m & db2.yr.isin([2023, 2024])),
                    ("OOS", m & db2.yr.isin([2025, 2026]))]:
        x = db2[mm]
        band_rows.append(dict(band=f"[{lo},{hi})", span=tag, n=int(len(x)),
                              PF=round(pf(x.net_pnl), 3),
                              avgR=round(float(x.r_multiple.mean()), 3) if len(x) else np.nan,
                              win=round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan,
                              net=round(float(x.net_pnl.sum()), 1)))
bands = pd.DataFrame(band_rows)

print("[floor7.5 vs no_floor 전체 비교]")
print(summary.to_string(index=False))
print("\n[no_floor 점수밴드: 새로 들어온 score<7.5 가 +인가 -인가]")
print(bands.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    summary.to_excel(xw, sheet_name="compare", index=False)
    bands.to_excel(xw, sheet_name="score_bands_nofloor", index=False)
print(f"\n저장 -> {OUT}")
