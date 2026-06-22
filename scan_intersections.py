"""16원자 교집합(AND) post-hoc 전수스캔 — 유의미한 OOS 조합 탐색.
주의: post-hoc(슬롯재배치 미반영) 근사치 → 유망조합만 실전 run_and_sweep 으로 확정.
PF는 net_pnl(기존분석 일관) 기준, r_multiple PF 병기(path-independent).
출력: 페어/트리플 중 (a)OOS PF 상위 (b)walk-forward 안정(train>1.05 & OOS>0.95) 강조.
"""
import os, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")
NEW = {"a_killzone", "a_atr_expansion", "a_disp_strength", "a_volume_strict"}
MIN_N = 30          # 전체 최소표본
MIN_NOOS = 12       # OOS 최소표본 (노이즈 컷)


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
print(f"[교집합 스캔] {TR}")
print(f"  {len(d)}거래 | base 전체PF={pf(pnl):.3f} OOS={pf(pnl[te]):.3f} | 원자 {len(acols)}개 | nOOS={int(te.sum())}")
print(f"  필터: n>={MIN_N}, nOOS>={MIN_NOOS}  (post-hoc 근사 — 유망조합은 실전확정 필요)\n")


def evalmask(m):
    return dict(n=int(m.sum()), noos=int((m & te).sum()),
                pf=pf(pnl[m]), pf_tr=pf(pnl[m & tr]), pf_te=pf(pnl[m & te]),
                rpf_te=pf(rmul[m & te]), win=100*(pnl[m] > 0).mean() if m.sum() else 0.0)


rows = []
# 페어 + 트리플
for k in (2, 3):
    for combo in itertools.combinations(acols, k):
        m = np.logical_and.reduce([B[a] for a in combo])
        if m.sum() < MIN_N or (m & te).sum() < MIN_NOOS:
            continue
        r = evalmask(m)
        r["combo"] = " ∩ ".join(c.replace("a_", "") for c in combo)
        r["k"] = k
        r["has_new"] = int(bool(set(combo) & NEW))
        rows.append(r)

R = pd.DataFrame(rows)
if len(R) == 0:
    print("표본 충족 조합 없음 (MIN_NOOS 완화 필요)")
    raise SystemExit

cols = ["combo", "k", "has_new", "n", "noos", "win", "pf", "pf_tr", "pf_te", "rpf_te"]


def show(title, df, n=20):
    print(f"\n{'='*90}\n{title}\n{'='*90}")
    s = df[cols].copy()
    s.columns = ["combo", "k", "new", "n", "nOOS", "win%", "PF", "PFtrain", "PFoos", "rPFoos"]
    print(s.head(n).to_string(index=False,
          formatters={"win%": "{:.0f}".format, "PF": "{:.3f}".format,
                      "PFtrain": "{:.3f}".format, "PFoos": "{:.3f}".format, "rPFoos": "{:.3f}".format}))


show("① OOS PF(net) 상위 20", R.sort_values("pf_te", ascending=False))
stable = R[(R.pf_tr > 1.05) & (R.pf_te > 0.95)].sort_values("pf_te", ascending=False)
show(f"② walk-forward 안정 (train>1.05 & OOS>0.95) — {len(stable)}개", stable)
show("③ 신규원자 포함 + OOS 상위 15", R[R.has_new == 1].sort_values("pf_te", ascending=False), 15)

out = os.path.join(os.path.dirname(TR), "intersections_scan.csv")
R.sort_values("pf_te", ascending=False).to_csv(out, index=False)
print(f"\n전체 {len(R)}조합 저장 → {out}")
