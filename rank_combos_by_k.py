"""12원자 모든 부분집합(2^12-1=4095, AND조합)을 k(원자개수)별로 요약.
'k를 늘리면 OOS가 살아나는가'를 보기 위함.
각 k 그룹: 표본충분 조합수 / 최고 PF전체 / 최고 OOS(test25-26)PF / OOS PF>=1 개수 /
           avgR 양수 개수 / 견고(test>1 & 전연도>0.9) 개수.
사용: python rank_combos_by_k.py [trades_csv] [min_n] [min_nte]
"""
import os, sys, io
import numpy as np
import pandas as pd
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
MIN_N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
MIN_NTE = int(sys.argv[3]) if len(sys.argv) > 3 else 20

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
SH = [a.replace("a_", "") for a in ATOMS]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
pnl = d["net_pnl"].to_numpy(float)
rmul = d["r_multiple"].to_numpy(float)
yr = d["year"].to_numpy()
A = np.column_stack([d[a].to_numpy(bool) for a in ATOMS])
N = len(d)
pos_all = np.where(pnl > 0, pnl, 0.0)
neg_all = np.where(pnl < 0, -pnl, 0.0)
te_mask = np.isin(yr, [2025, 2026])
ymask = {y: (yr == y) for y in (2023, 2024, 2025, 2026)}

def pf_of(sel):
    p = pos_all[sel].sum(); n = neg_all[sel].sum()
    return p / n if n > 1e-9 else (np.inf if p > 0 else 0.0)

rows = []
for k in range(1, 13):
    for combo in combinations(range(12), k):
        m = A[:, combo].all(axis=1)
        n = int(m.sum())
        if n < MIN_N:
            continue
        nte = int((m & te_mask).sum())
        pf = pf_of(m)
        ar = rmul[m].mean()
        pf_te = pf_of(m & te_mask) if nte else np.nan
        ys = {y: pf_of(m & ymask[y]) for y in (2023, 2024, 2025, 2026)}
        rows.append(dict(k=k, combo="+".join(SH[i] for i in combo), n=n, nte=nte,
                         PF=pf, avgR=ar, PF_te=pf_te,
                         y23=ys[2023], y24=ys[2024], y25=ys[2025], y26=ys[2026]))

R = pd.DataFrame(rows)
print("=" * 118)
print(f"k별 AND조합 요약 | {TRADES} | 전체 {N}거래 | MIN_N={MIN_N} MIN_NTE={MIN_NTE}")
print("=" * 118)
print(f"  {'k':>2}{'조합수':>7}{'최고PF':>8}{'(조합)':<34}{'최고OOS':>8}{'OOS>=1':>7}{'avgR>0':>7}{'견고':>5}")
for k in range(1, 13):
    g = R[R.k == k]
    if not len(g):
        print(f"  {k:>2}{0:>7}      —")
        continue
    best = g.loc[g.PF.idxmax()]
    gte = g[g.nte >= MIN_NTE]
    best_te = gte.loc[gte.PF_te.idxmax()] if len(gte) else None
    oos_ge1 = int((gte.PF_te >= 1.0).sum()) if len(gte) else 0
    arpos = int((g.avgR > 0).sum())
    robust = g[(g.nte >= MIN_NTE) & (g.PF_te >= 1.0) &
               (g.y23 > 0.9) & (g.y24 > 0.9) & (g.y25 > 0.9) & (g.y26 > 0.9)]
    bt = f"{best_te.PF_te:.2f}" if best_te is not None else "—"
    print(f"  {k:>2}{len(g):>7}{best.PF:>8.3f}  {best.combo[:32]:<32}{bt:>8}{oos_ge1:>7}{arpos:>7}{len(robust):>5}")

print("\n" + "=" * 118)
print(f"전체 표본충분 조합 {len(R)}개 중 OOS(test25-26) PF>=1 & OOS표본 {MIN_NTE}+ :")
sv = R[(R.nte >= MIN_NTE) & (R.PF_te >= 1.0)].sort_values("PF_te", ascending=False)
print("=" * 118)
if len(sv):
    for _, r in sv.head(40).iterrows():
        print(f"  k{int(r['k'])} {r['combo'][:50]:<52} n={int(r['n'])} nte={int(r['nte'])}"
              f" PF={r['PF']:.2f} OOS={r['PF_te']:.2f} yr {r['y23']:.2f}/{r['y24']:.2f}/{r['y25']:.2f}/{r['y26']:.2f}")
else:
    print("  없음 — k를 아무리 늘려도 OOS PF>=1(표본충분) 조합이 존재하지 않음.")

print("\n" + "=" * 118)
print("avgR 양수 조합 (k 무관) 전부:")
print("=" * 118)
ap = R[R.avgR > 0].sort_values("avgR", ascending=False)
if len(ap):
    for _, r in ap.iterrows():
        print(f"  k{int(r['k'])} {r['combo'][:50]:<52} n={int(r['n'])} PF={r['PF']:.3f}"
              f" avgR={r['avgR']:+.3f} OOS={r['PF_te']:.2f} yr {r['y23']:.2f}/{r['y24']:.2f}/{r['y25']:.2f}/{r['y26']:.2f}")
else:
    print("  없음.")

out = os.path.join(os.path.dirname(TRADES), "combos_by_k_all.csv")
R.sort_values(["k", "PF"], ascending=[True, False]).to_csv(out, index=False)
print("\n전체 CSV →", out)
print("※ post-hoc. OOS표본 작은 조합의 높은 PF_te 는 우연 — 표본·전연도 함께 봐야 함.")
