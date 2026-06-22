"""16원자 고차 교집합(k=4,5,6) post-hoc 전수스캔 — 4원자 이상 유의미 조합 탐색.
주의: 차수↑ = 표본↓ = 과적합/다중비교 위험↑. 표본필터+walk-forward 안정성으로 노이즈 컷.
post-hoc 근사 → 유망조합만 실전 run_and_sweep 확정.
"""
import os, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")
NEW = {"a_killzone", "a_atr_expansion", "a_disp_strength", "a_volume_strict"}
MIN_N = 30
MIN_NOOS = 12
KS = (4, 5, 6)


def pf(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
B = {a: tb(d[a]).to_numpy() for a in acols}
pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
rmul = pd.to_numeric(d.get("r_multiple", pd.Series(np.nan, index=d.index)), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
tr = np.isin(yr, [2023, 2024]); te = np.isin(yr, [2025, 2026])
print(f"[고차 교집합 스캔 k={KS}] {len(d)}거래 | base OOS PF={pf(pnl[te]):.3f} | nOOS={int(te.sum())}")
print(f"  필터 n>={MIN_N}, nOOS>={MIN_NOOS} (post-hoc 근사)\n")

rows = []
tested = 0
for k in KS:
    for combo in itertools.combinations(acols, k):
        m = np.logical_and.reduce([B[a] for a in combo])
        tested += 1
        ns = int(m.sum())
        if ns < MIN_N:
            continue
        noos = int((m & te).sum())
        if noos < MIN_NOOS:
            continue
        rows.append(dict(
            combo=" ∩ ".join(c.replace("a_", "") for c in combo), k=k,
            has_new=int(bool(set(combo) & NEW)), n=ns, noos=noos,
            win=100 * (pnl[m] > 0).mean(),
            pf=pf(pnl[m]), pf_tr=pf(pnl[m & tr]), pf_te=pf(pnl[m & te]), rpf_te=pf(rmul[m & te]),
        ))

R = pd.DataFrame(rows)
print(f"테스트 {tested}조합 → 표본충족 {len(R)}개\n")
if len(R) == 0:
    print("표본 충족 4원자+ 조합 없음 — 4원자 이상은 표본붕괴로 평가불가.")
    raise SystemExit

cols = ["combo", "k", "has_new", "n", "noos", "win", "pf", "pf_tr", "pf_te", "rpf_te"]


def show(title, df, n=25):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    s = df[cols].copy()
    s.columns = ["combo", "k", "new", "n", "nOOS", "win%", "PF", "PFtrain", "PFoos", "rPFoos"]
    print(s.head(n).to_string(index=False,
          formatters={"win%": "{:.0f}".format, "PF": "{:.3f}".format, "PFtrain": "{:.3f}".format,
                      "PFoos": "{:.3f}".format, "rPFoos": "{:.3f}".format}))


show("① OOS PF(net) 상위 25", R.sort_values("pf_te", ascending=False))
stable = R[(R.pf_tr > 1.05) & (R.pf_te > 0.95) & (R.rpf_te > 0.95)].sort_values("pf_te", ascending=False)
show(f"② walk-forward 안정 (train>1.05 & OOSnet>0.95 & OOSr>0.95) — {len(stable)}개", stable)
bign = R[R.noos >= 25].sort_values("pf_te", ascending=False)
show(f"③ 표본 비교적 큰 것 (nOOS>=25) OOS 상위 — {len(bign)}개", bign, 15)

print(f"\n차수별 표본충족 수: {R.groupby('k').size().to_dict()}")
print(f"차수별 OOS PF>1 수: {R[R.pf_te>1].groupby('k').size().to_dict()}")
out = os.path.join(os.path.dirname(TR), "intersections_hi_scan.csv")
R.sort_values("pf_te", ascending=False).to_csv(out, index=False)
print(f"전체 저장 → {out}")
