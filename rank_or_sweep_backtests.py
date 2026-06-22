"""or_sweep 의 24개 단독 진입조건 '실제 백테스트'를 백테스트단위로 집계·랭킹.
각 백테스트: n, 승률, PF, avgR, train(23-24)PF, test(25-26)PF, 연도별PF.
지표별(PF/승률/avgR) 상위 5 + OOS(test) 상위 5 + 전체표.
사용: python rank_or_sweep_backtests.py [or_sweep_dir]
"""
import os, sys, io, glob
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
SWEEP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "or_sweep")


def pf_of(s):
    s = np.asarray(s, float)
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


rows = []
for fp in sorted(glob.glob(os.path.join(SWEEP, "*", "stage4d_trades.csv"))):
    name = os.path.basename(os.path.dirname(fp))
    d = pd.read_csv(fp)
    if "net_pnl" not in d.columns or len(d) == 0:
        continue
    yr = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year.to_numpy()
    pnl = d["net_pnl"].to_numpy(float)
    rmul = d["r_multiple"].to_numpy(float) if "r_multiple" in d.columns else np.full(len(d), np.nan)
    tr = np.isin(yr, [2023, 2024]); teM = np.isin(yr, [2025, 2026])
    rows.append(dict(
        rule=name, n=len(d), win=100 * (pnl > 0).mean(), PF=pf_of(pnl), avgR=np.nanmean(rmul),
        PFtr=pf_of(pnl[tr]) if tr.sum() else np.nan,
        PFte=pf_of(pnl[teM]) if teM.sum() else np.nan, nte=int(teM.sum()),
        ret=pnl.sum(),
        y23=pf_of(pnl[yr == 2023]), y24=pf_of(pnl[yr == 2024]),
        y25=pf_of(pnl[yr == 2025]), y26=pf_of(pnl[yr == 2026]),
    ))

R = pd.DataFrame(rows)
L = "=" * 116
print(L)
print(f"24개 단독 진입조건 '실제 백테스트' 랭킹 | {SWEEP}")
print(f"(접두 n_ = 음극=원자 False 진입 | 슬롯재배치 반영된 실전수치) | 백테스트 {len(R)}개")
print(L)

hdr = (f"  {'#':>2} {'진입조건':<20}{'n':>6}{'win%':>7}{'PF':>7}{'avgR':>8}"
       f"{'PFtr':>7}{'PFte':>7}{'nte':>5}{'netPnL':>9}  yr23/24/25/26")


def fmt(v, p=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return "inf" if np.isinf(v) else f"{v:.{p}f}"


def show(title, col, asc=False, n=5):
    print("\n" + L); print(title); print(L); print(hdr)
    sub = R.sort_values(col, ascending=asc).head(n)
    for i, (_, r) in enumerate(sub.iterrows(), 1):
        print(f"  {i:>2} {r['rule']:<20}{int(r['n']):>6}{fmt(r['win'],1):>7}{fmt(r['PF']):>7}"
              f"{fmt(r['avgR'],3):>8}{fmt(r['PFtr']):>7}{fmt(r['PFte']):>7}{int(r['nte']):>5}"
              f"{r['ret']:>9.0f}  {fmt(r['y23'])}/{fmt(r['y24'])}/{fmt(r['y25'])}/{fmt(r['y26'])}")


show("[A] PF 상위 5", "PF")
show("[B] 승률 상위 5", "win")
show("[C] avgR 상위 5", "avgR")
show("[D] OOS test(2025-26) PF 상위 5  ← 실전 생존 핵심", "PFte")

print("\n" + L); print("[전체 24개 — PF 내림차순]"); print(L); print(hdr)
for i, (_, r) in enumerate(R.sort_values("PF", ascending=False).iterrows(), 1):
    print(f"  {i:>2} {r['rule']:<20}{int(r['n']):>6}{fmt(r['win'],1):>7}{fmt(r['PF']):>7}"
          f"{fmt(r['avgR'],3):>8}{fmt(r['PFtr']):>7}{fmt(r['PFte']):>7}{int(r['nte']):>5}"
          f"{r['ret']:>9.0f}  {fmt(r['y23'])}/{fmt(r['y24'])}/{fmt(r['y25'])}/{fmt(r['y26'])}")

R.sort_values("PF", ascending=False).to_csv(os.path.join(SWEEP, "sweep_singles_ranked.csv"), index=False)
print("\n전체 CSV →", os.path.join(SWEEP, "sweep_singles_ranked.csv"))
print("※ PFtr=train23-24, PFte=test25-26. 실전 진입게이트 수치(슬롯재배치 반영).")
