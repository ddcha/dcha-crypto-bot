"""12원자 × 양극(True)/음극(False) = 24 단일조건 트레이딩 결과 전수 리스트업.
각 조건: n, 승률, PF, avgR, train(2023-24)PF, test(2025-26)PF, OOS표본, 연도별PF.
사용: python rank_atoms_single.py [trades_csv]
"""
import os, sys, io
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "atoms_doomcha_15m", "stage4d_trades.csv")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
pnl = d["net_pnl"].to_numpy(float)
rmul = d["r_multiple"].to_numpy(float)
yr = d["year"].to_numpy()
N = len(d)


def pf(mask):
    s = pnl[mask]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def stats(mask):
    n = int(mask.sum())
    if n == 0:
        return dict(n=0, win=np.nan, PF=np.nan, avgR=np.nan, tr=np.nan, te=np.nan,
                    nte=0, y23=np.nan, y24=np.nan, y25=np.nan, y26=np.nan)
    tr = mask & np.isin(yr, [2023, 2024])
    te = mask & np.isin(yr, [2025, 2026])
    return dict(
        n=n, win=100 * (pnl[mask] > 0).mean(), PF=pf(mask), avgR=rmul[mask].mean(),
        tr=pf(tr) if tr.sum() else np.nan, te=pf(te) if te.sum() else np.nan, nte=int(te.sum()),
        y23=pf(mask & (yr == 2023)), y24=pf(mask & (yr == 2024)),
        y25=pf(mask & (yr == 2025)), y26=pf(mask & (yr == 2026)),
    )


base_pf = pf(np.ones(N, bool))
base_wr = 100 * (pnl > 0).mean()
L = "=" * 116
print(L)
print(f"12원자 × 양극/음극 단일조건 전수 | {TRADES}")
print(f"전체 {N}거래 | baseline 승률 {base_wr:.1f}% PF {base_pf:.3f} avgR {rmul.mean():+.3f}")
print(L)


def fmt(v, p=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if np.isinf(v):
        return "inf"
    return f"{v:.{p}f}"


rows = []
for a in ATOMS:
    sh = a.replace("a_", "")
    mT = d[a].to_numpy(bool)
    rows.append(("+" + sh, mT, stats(mT)))
    rows.append(("~" + sh, ~mT, stats(~mT)))

header = (f"  {'literal':<22}{'n':>5}{'win%':>7}{'PF':>7}{'avgR':>8}"
          f"{'PFtr':>7}{'PFte':>7}{'nte':>5}   yr23/24/25/26")


def block(title, key, asc=False, only_finite_te=False):
    print("\n" + L); print(title); print(L); print(header)
    rs = [r for r in rows if not (only_finite_te and (np.isnan(r[2]["te"])))]
    rs = sorted(rs, key=lambda r: (-1e9 if (r[2][key] is None or np.isnan(r[2][key])) else r[2][key]),
                reverse=not asc)
    for name, _, s in rs:
        print(f"  {name:<22}{s['n']:>5}{fmt(s['win'],1):>7}{fmt(s['PF']):>7}{fmt(s['avgR'],3):>8}"
              f"{fmt(s['tr']):>7}{fmt(s['te']):>7}{s['nte']:>5}   "
              f"{fmt(s['y23'])}/{fmt(s['y24'])}/{fmt(s['y25'])}/{fmt(s['y26'])}")


block("[A] 전체 PF 높은 순 (24개 전부)", "PF")
block("[B] OOS test(2025-26) PF 높은 순 (24개 전부)", "te")
block("[C] avgR 높은 순 (24개 전부)", "avgR")

print("\n" + L)
print("※ PFtr=train23-24, PFte=test25-26. te가 train보다 크게 낮으면 2023-24 과적합.")
print("  단일조건이라 슬롯재배치 미반영(post-hoc 필터) — 실전게이트는 run_or_sweep 류로 재검증.")
print(L)
