"""k=4..16 전수 교집합 스캔 + 연도분산 진단.
'유효'=OOS(2025-26) PF>1. 각 조합의 연도별 거래수/PF로 '전기간 분산 vs 특정연도 집중' 판정.
주의: post-hoc(슬롯재배치 미반영) + 다중비교 폭발(수만조합) → 분산여부가 진짜/가짜 판별 핵심.
"""
import os, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")
NEW = {"a_killzone", "a_atr_expansion", "a_disp_strength", "a_volume_strict"}
MIN_N = 30
MIN_NOOS = 12
YEARS = [2023, 2024, 2025, 2026]


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
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
ymask = {y: (yr == y) for y in YEARS}
tr = np.isin(yr, [2023, 2024]); te = np.isin(yr, [2025, 2026])
print(f"[전수 스캔 k=4..16] {len(d)}거래 | base OOS PF={pf(pnl[te]):.3f}")
print(f"  전체기간 거래분포: " + " ".join(f"{y}={int(ymask[y].sum())}" for y in YEARS))
print(f"  필터 n>={MIN_N}, nOOS>={MIN_NOOS} | '유효'=OOS PF>1 (post-hoc)\n")

rows = []
tested = cnt_sample = 0
for k in range(4, len(acols) + 1):
    for combo in itertools.combinations(acols, k):
        m = np.logical_and.reduce([B[a] for a in combo])
        tested += 1
        n = int(m.sum())
        if n < MIN_N:
            continue
        noos = int((m & te).sum())
        if noos < MIN_NOOS:
            continue
        cnt_sample += 1
        pf_te = pf(pnl[m & te])
        if pf_te <= 1.0:
            continue
        ny = {y: int((m & ymask[y]).sum()) for y in YEARS}
        years_present = sum(1 for y in YEARS if ny[y] > 0)
        max_share = max(ny.values()) / n
        rows.append(dict(
            combo="∩".join(c.replace("a_", "") for c in combo), k=k, n=n,
            n23=ny[2023], n24=ny[2024], n25=ny[2025], n26=ny[2026],
            pf=round(pf(pnl[m]), 3), pf23=round(pf(pnl[m & ymask[2023]]), 2),
            pf24=round(pf(pnl[m & ymask[2024]]), 2), pf25=round(pf(pnl[m & ymask[2025]]), 2),
            pf26=round(pf(pnl[m & ymask[2026]]), 2),
            pf_tr=round(pf(pnl[m & tr]), 3), pf_te=round(pf_te, 3),
            rpf_te=round(pf(rmul[m & te]), 3),
            yrs=years_present, maxshare=round(max_share, 2)))

R = pd.DataFrame(rows)
print(f"테스트 {tested}조합 | 표본충족 {cnt_sample} | 유효(OOS>1) {len(R)}\n")
if len(R) == 0:
    raise SystemExit("유효 조합 없음")

print("차수별 [표본충족→유효(OOS>1)] 및 유효중 4연도전부거래 수:")
for k in range(4, len(acols) + 1):
    sub = R[R.k == k]
    if len(sub) == 0:
        continue
    print(f"  k={k:>2}: 유효 {len(sub):>3} | 4연도전부 {int((sub.yrs==4).sum()):>3} | "
          f"maxshare<0.5(분산) {int((sub.maxshare<0.5).sum()):>3} | nOOS최대 {int(sub.n25.add(sub.n26).max())}")

disp = R[(R.yrs == 4) & (R.maxshare < 0.5)].copy()
disp["nOOS"] = disp.n25 + disp.n26
disp = disp.sort_values(["nOOS", "pf_te"], ascending=False)
cols = ["combo", "k", "n", "n23", "n24", "n25", "n26", "pf_tr", "pf_te", "rpf_te",
        "pf23", "pf24", "pf25", "pf26", "maxshare"]
print(f"\n{'='*120}\n[진짜 후보] OOS>1 + 4연도 전부거래 + 최대연도비중<0.5(분산) — {len(disp)}개, nOOS순\n{'='*120}")
print(disp[cols].head(30).to_string(index=False) if len(disp) else "  → 0개 (분산된 유효조합 없음)")

print(f"\n{'='*120}\n[참고] OOS>1 전체 중 nOOS 큰 상위 20 (분산 무관)\n{'='*120}")
R["nOOS"] = R.n25 + R.n26
print(R.sort_values("nOOS", ascending=False)[cols].head(20).to_string(index=False))

out = os.path.join(os.path.dirname(TR), "all_orders_valid.csv")
R.sort_values("nOOS", ascending=False).to_csv(out, index=False)
print(f"\n유효조합 {len(R)}개 저장 → {out}")
