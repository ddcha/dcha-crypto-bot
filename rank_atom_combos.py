"""trades 로그에서 12원자 AND 조합을 PF·승률·avg_R 로 정렬해 추출후보 랭킹.
- 조합 = 원자들이 '동시에 True'(AND)인 trade 부분집합.
- k=1~4, 최소표본 MIN_TR 이상만.
- 각 조합에 연도별 PF + train(2023-24)/test(2025-26) PF 동반(과적합·생존편향 점검).
- ※ post-hoc(로그필터) 랭킹 = '추출후보 탐색'용. 실제 진입게이트로 쓰면 단일포지션
   슬롯재배치로 수치가 달라짐 → 상위후보는 반드시 실전 백테스트로 재검증.
사용: python rank_atom_combos.py [trades_csv] [min_tr]
"""
import os, sys, io
import numpy as np
import pandas as pd
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
MIN_TR = int(sys.argv[2]) if len(sys.argv) > 2 else 50
KMAX = 4

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
pnl = d["net_pnl"].to_numpy(float)
rmul = d["r_multiple"].to_numpy(float)
yr = d["year"].to_numpy()
A = np.column_stack([d[a].to_numpy(bool) for a in ATOMS])  # (N,12)
N = len(d)

def pf(mask):
    s = pnl[mask]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)

base_wr = 100 * (pnl > 0).mean()
base_pf = pf(np.ones(N, bool))
base_r = rmul.mean()
print("=" * 110)
print(f"원자 AND조합 랭킹 | {TRADES}")
print(f"전체 {N}거래 | baseline 승률 {base_wr:.1f}% PF {base_pf:.3f} avgR {base_r:+.3f} | MIN_TR={MIN_TR} k<= {KMAX}")
print("=" * 110)

rows = []
for k in range(1, KMAX + 1):
    for combo in combinations(range(12), k):
        mask = A[:, combo].all(axis=1)
        n = int(mask.sum())
        if n < MIN_TR:
            continue
        s = pnl[mask]
        wr = 100 * (s > 0).mean()
        p = pf(mask)
        ar = rmul[mask].mean()
        m_tr = mask & np.isin(yr, [2023, 2024])
        m_te = mask & np.isin(yr, [2025, 2026])
        pf_tr = pf(m_tr) if m_tr.sum() else np.nan
        pf_te = pf(m_te) if m_te.sum() else np.nan
        pfy = {y: round(pf(mask & (yr == y)), 2) for y in (2023, 2024, 2025, 2026)}
        name = "+".join(ATOMS[i].replace("a_", "") for i in combo)
        rows.append(dict(combo=name, k=k, n=n, win=round(wr, 1), PF=round(p, 3),
                         avgR=round(ar, 3), PF_tr2324=round(pf_tr, 2), PF_te2526=round(pf_te, 2),
                         n_te=int(m_te.sum()),
                         y23=pfy[2023], y24=pfy[2024], y25=pfy[2025], y26=pfy[2026]))

R = pd.DataFrame(rows)
print(f"\n표본 {MIN_TR}+ 조합 수: {len(R)}\n")

def show(title, col, asc=False):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)
    sub = R.sort_values(col, ascending=asc).head(30)
    print(f"  {'#':>2} {'combo':<46}{'k':>2}{'n':>6}{'win%':>7}{'PF':>7}{'avgR':>7}"
          f"{'PFtr':>6}{'PFte':>6}{'nte':>5}  yr23/24/25/26")
    for i, (_, r) in enumerate(sub.iterrows(), 1):
        print(f"  {i:>2} {r['combo'][:44]:<46}{int(r['k']):>2}{int(r['n']):>6}{r['win']:>7}"
              f"{r['PF']:>7}{r['avgR']:>7}{r['PF_tr2324']:>6}{r['PF_te2526']:>6}{int(r['n_te']):>5}"
              f"   {r['y23']}/{r['y24']}/{r['y25']}/{r['y26']}")

show("[A] PF 높은 순 TOP 30", "PF")
show("[B] 승률 높은 순 TOP 30", "win")
show("[C] avg R 높은 순 TOP 30", "avgR")

# OOS 견고 후보(욕심 적게): test2526 PF>1 & 모든연도 PF>0.9 & 표본충분
robust = R[(R.PF_te2526 > 1.0) & (R.y23 > 0.9) & (R.y24 > 0.9) & (R.y25 > 0.9) & (R.y26 > 0.9)]
print("\n" + "=" * 110)
print(f"[D] OOS·전연도 견고 후보 (PF_te2526>1 & 매 연도 PF>0.9) — {len(robust)}개")
print("=" * 110)
if len(robust):
    for i, (_, r) in enumerate(robust.sort_values("PF_te2526", ascending=False).head(30).iterrows(), 1):
        print(f"  {i:>2} {r['combo'][:44]:<46} n={int(r['n'])} PF={r['PF']} te={r['PF_te2526']} "
              f"yr {r['y23']}/{r['y24']}/{r['y25']}/{r['y26']}")
else:
    print("  없음 — 모든 연도에서 살아남는 AND조합이 표본 내 존재하지 않음(2025-26 사망과 일치).")

out = os.path.join(os.path.dirname(TRADES), "atom_combo_ranking.csv")
R.sort_values("PF", ascending=False).to_csv(out, index=False)
print("\n전체 랭킹 CSV →", out)
print("※ post-hoc 랭킹은 추출후보 탐색용. 상위조합은 ATOM_OR_LIST/AND 실전백테스트로 재검증 필수.")
