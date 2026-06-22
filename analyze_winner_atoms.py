"""양수(net_pnl>0) 거래의 원자 동시발생 분석 — s5 정직 baseline.
생존편향 방지: 승자 단독이 아니라 패자 대비 lift, 연도/사이드 분해 동반.
사용: python analyze_winner_atoms.py [trades_csv]
"""
import os, sys, io
import numpy as np
import pandas as pd
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
W = d[d.net_pnl > 0].copy()      # 승자
Lz = d[d.net_pnl < 0].copy()     # 패자
nW, nL = len(W), len(Lz)
L = "=" * 100
print(L); print(f"승자 원자 동시발생 분석 | {TRADES}")
print(f"전체 {len(d)} | 승 {nW}({100*nW/len(d):.1f}%) | 패 {nL} | BE {len(d)-nW-nL} | 승자 총이익 {W.net_pnl.sum():.0f} / 패자 총손실 {Lz.net_pnl.sum():.0f}")
print(L)

# [1] 승/패 by 연도·사이드 (과적합·편향 경보용)
print("\n[1] 승자 분포 (편향 점검)")
print("  연도별 승자수/승률:", {int(y): f"{int((W.year==y).sum())}/{100*(d[d.year==y].net_pnl>0).mean():.0f}%" for y in sorted(d.year.dropna().unique())})
print("  사이드 승자수/승률:", {s: f"{int((W.side==s).sum())}/{100*(d[d.side==s].net_pnl>0).mean():.0f}%" for s in d.side.unique()})

# [2] 원자별: 승자내 빈도 vs 패자내 빈도 + lift + 승자기여이익
print("\n[2] 원자별 승자-동시발생 (lift = 승자빈도/패자빈도, >1이면 승자에 편중)")
print(f"  {'atom':<20}{'승자%':>8}{'패자%':>8}{'lift':>7}{'승자이익합':>12}{'그원자 거래승률':>14}")
rows = []
for a in ATOMS:
    pw = W[a].mean(); pl = Lz[a].mean() if nL else 0
    lift = pw / pl if pl > 1e-9 else np.inf
    profit = W.loc[W[a], "net_pnl"].sum()
    wr = 100 * (d.loc[d[a], "net_pnl"] > 0).mean()
    rows.append((a, pw, pl, lift, profit, wr))
for a, pw, pl, lift, profit, wr in sorted(rows, key=lambda r: -r[3]):
    print(f"  {a:<20}{100*pw:>7.1f}%{100*pl:>7.1f}%{lift:>7.2f}{profit:>12.0f}{wr:>13.1f}%")

# [3] 승자 안에서 자주 함께 나타나는 원자 PAIR (동시 True 비율 + 패자대비 lift)
print("\n[3] 승자 동시발생 PAIR TOP (둘다 True | 승자) — lift=승자대비패자")
pair_rows = []
for a, b in combinations(ATOMS, 2):
    cw = (W[a] & W[b]).mean()
    cl = (Lz[a] & Lz[b]).mean() if nL else 0
    if cw < 0.05:
        continue
    lift = cw / cl if cl > 1e-9 else np.inf
    pair_rows.append((f"{a}+{b}", cw, cl, lift))
print(f"  {'pair':<40}{'승자동시%':>10}{'패자동시%':>10}{'lift':>7}")
for name, cw, cl, lift in sorted(pair_rows, key=lambda r: -r[1])[:15]:
    print(f"  {name:<40}{100*cw:>9.1f}%{100*cl:>9.1f}%{lift:>7.2f}")

# [4] 승자의 '정확한 원자 시그니처' 최빈 (어떤 조합이 통째로 함께 켜지나)
print("\n[4] 승자 최빈 원자 시그니처 (켜진 원자 집합 그대로) — 그 시그니처 전체거래 승률·PF")
def sig(row):
    return "+".join(a.replace("a_", "") for a in ATOMS if row[a]) or "(none)"
d["_sig"] = d.apply(sig, axis=1)
def pf(s):
    s = np.asarray(s, float); p = s[s > 0].sum(); n = -s[s < 0].sum()
    return p / n if n > 1e-9 else (np.inf if p > 0 else 0.0)
wsig = d[d.net_pnl > 0]["_sig"].value_counts().head(15)
print(f"  {'signature':<52}{'승자수':>6}{'전체거래':>7}{'승률':>7}{'PF':>7}")
for s, cnt in wsig.items():
    sub = d[d._sig == s]
    print(f"  {s[:50]:<52}{cnt:>6}{len(sub):>7}{100*(sub.net_pnl>0).mean():>6.0f}%{pf(sub.net_pnl):>7.2f}")

# [5] 승자 평균 원자 개수 vs 패자
print(f"\n[5] 켜진 원자 개수: 승자 평균 {d[d.net_pnl>0][ATOMS].sum(axis=1).mean():.2f} / 패자 평균 {d[d.net_pnl<0][ATOMS].sum(axis=1).mean():.2f}")
print("  ※ 승자 동시발생은 상관(생존편향)일 뿐 — lift>1 & 패자대비 차이 큰 원자만 실질 신호 후보. 인과·OOS는 별도 검증 필요.")
print(L)
