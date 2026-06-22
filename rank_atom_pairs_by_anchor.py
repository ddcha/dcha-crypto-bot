"""각 원자(anchor)별로 '다른 원자 하나를 더 AND로 얹었을 때' 성과 변화 전수 리스트업.
- anchor=True 인 trade 부분집합 기준선 → 거기에 partner=True 를 추가 AND.
- 각 (anchor, partner) 쌍: n, 승률, PF, avgR, anchor단독대비 ΔPF, 연도별/test PF.
- partner 는 anchor 블록 안에서 PF 내림차순.
- ※ post-hoc(로그필터) → 추출후보 탐색용. 실전 게이트는 슬롯재배치로 달라짐 → 재검증 필수.
사용: python rank_atom_pairs_by_anchor.py [trades_csv] [min_tr]
"""
import os, sys, io
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
MIN_TR = int(sys.argv[2]) if len(sys.argv) > 2 else 30

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
A = {a: d[a].to_numpy(bool) for a in ATOMS}
N = len(d)

def stats(mask):
    n = int(mask.sum())
    if n == 0:
        return n, np.nan, np.nan, np.nan, np.nan, np.nan
    s = pnl[mask]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    pf = pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)
    wr = 100 * (s > 0).mean()
    ar = rmul[mask].mean()
    te = mask & np.isin(yr, [2025, 2026])
    s2 = pnl[te]; p2 = s2[s2 > 0].sum(); n2 = -s2[s2 < 0].sum()
    pf_te = (p2 / n2 if n2 > 1e-9 else (np.inf if p2 > 0 else 0.0)) if te.sum() else np.nan
    return n, wr, pf, ar, pf_te, int(te.sum())

def pf_year(mask, y):
    s = pnl[mask & (yr == y)]
    if not len(s):
        return np.nan
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)

allrows = []
print("=" * 120)
print(f"앵커별 원자 페어 성과 | {TRADES} | 전체 {N}거래 | MIN_TR={MIN_TR}")
print("ΔPF = (앵커+파트너) PF − 앵커단독 PF | yr = 2023/24/25/26 연도별 PF")
print("=" * 120)

for a in ATOMS:
    am = A[a]
    bn, bwr, bpf, bar, bte, bnte = stats(am)
    print("\n" + "─" * 120)
    print(f"■ anchor={a}  (단독: n={bn} 승률={bwr:.1f}% PF={bpf:.3f} avgR={bar:+.3f} test25-26 PF={bte:.3f})")
    print(f"  {'partner':<20}{'n':>6}{'win%':>7}{'PF':>7}{'ΔPF':>7}{'avgR':>7}{'PFte':>6}{'nte':>5}   yr23/24/25/26")
    blk = []
    for b in ATOMS:
        if b == a:
            continue
        m = am & A[b]
        n, wr, pf, ar, pf_te, nte = stats(m)
        if n < MIN_TR:
            continue
        ys = [round(pf_year(m, y), 2) for y in (2023, 2024, 2025, 2026)]
        blk.append((b, n, wr, pf, pf - bpf, ar, pf_te, nte, ys))
        allrows.append(dict(anchor=a.replace("a_", ""), partner=b.replace("a_", ""), n=n,
                            win=round(wr, 1), PF=round(pf, 3), dPF=round(pf - bpf, 3),
                            avgR=round(ar, 3), PF_te2526=round(pf_te, 3), n_te=nte,
                            y23=ys[0], y24=ys[1], y25=ys[2], y26=ys[3]))
    for b, n, wr, pf, dpf, ar, pf_te, nte, ys in sorted(blk, key=lambda r: -r[3]):
        flag = " ⚠2024" if (ys[1] is not None and ys[1] > 1.3 and (ys[2] or 0) < 0.8) else ""
        print(f"  {b.replace('a_',''):<20}{n:>6}{wr:>7.1f}{pf:>7.3f}{dpf:>+7.3f}{ar:>+7.3f}"
              f"{pf_te:>6.2f}{nte:>5}   {ys[0]}/{ys[1]}/{ys[2]}/{ys[3]}{flag}")
    if not blk:
        print(f"  (표본 {MIN_TR}+ 파트너 없음)")

R = pd.DataFrame(allrows)
out = os.path.join(os.path.dirname(TRADES), "atom_pairs_by_anchor.csv")
R.to_csv(out, index=False)

print("\n" + "=" * 120)
print(f"[요약] 전체 페어 {len(R)}개 중 ΔPF 상승 TOP 15 (앵커에 얹어 PF 가장 끌어올린 파트너)")
print("=" * 120)
for _, r in R.sort_values("dPF", ascending=False).head(15).iterrows():
    print(f"  {r['anchor']}+{r['partner']:<18} n={int(r['n']):>4} PF={r['PF']:.3f} ΔPF={r['dPF']:+.3f}"
          f" avgR={r['avgR']:+.3f} te={r['PF_te2526']:.2f}  yr {r['y23']}/{r['y24']}/{r['y25']}/{r['y26']}")
print("\n" + "=" * 120)
print(f"[요약] test25-26 PF≥1 인 페어 (OOS 생존) — 표본 {MIN_TR}+")
print("=" * 120)
sv = R[R.PF_te2526 >= 1.0].sort_values("PF_te2526", ascending=False)
if len(sv):
    for _, r in sv.iterrows():
        print(f"  {r['anchor']}+{r['partner']:<18} n={int(r['n'])} nte={int(r['n_te'])} PF={r['PF']:.3f}"
              f" te={r['PF_te2526']:.2f} yr {r['y23']}/{r['y24']}/{r['y25']}/{r['y26']}")
else:
    print("  없음.")
print("\n전체 CSV →", out)
print("※ post-hoc. 상위후보는 실전 AND 게이트 백테스트로 재검증 필요.")
