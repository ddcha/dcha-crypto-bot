"""고차 조합이 부분집합보다 값을 더하나? (IS=2023-24, OOS 미사용)
각 양수조합(k>=3)에 대해: 자기 (k-1) 부분집합들의 best avgR 대비 한계기여(marginal).
marginal>0 = 마지막 원자가 진짜 값 추가. marginal<=0 = 복잡도만 늘고 무의미(2~k-1이 이미 먹음).
"""
import os, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
SRC = os.path.join(CDIR, "all_positive_IS.csv")
OUT = os.path.join(CDIR, "marginal_value_IS.xlsx")
MIN_N = 15


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
name2col = {c.replace("a_", ""): c for c in acols}
B = {c: tb(d[c]).to_numpy() for c in acols}
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
IS = np.isin(yr, [2023, 2024])

_cache = {}
def avgR(atomset):
    key = frozenset(atomset)
    if key in _cache:
        return _cache[key]
    m = IS.copy()
    for a in atomset:
        m = m & B[name2col[a]]
    r = rmul[m]; r = r[~np.isnan(r)]
    n = int(m.sum())
    val = (n, round(float(r.mean()), 3) if len(r) else np.nan)
    _cache[key] = val
    return val

# 두 해 다 양수만 (IS-CV 통과) 대상
P = pd.read_csv(SRC)
P = P[(P.pf23 > 1) & (P.pf24 > 1)].copy()
P["atomset"] = P["combo"].apply(lambda s: tuple(s.split("∩")))

rows = []
for _, r in P.iterrows():
    aset = r["atomset"]; k = len(aset)
    n_full, ar_full = avgR(aset)
    if k < 3:
        best_sub_ar = np.nan; best_sub = ""; marg = np.nan
    else:
        subs = []
        for drop in aset:
            sub = tuple(a for a in aset if a != drop)
            ns, ars = avgR(sub)
            if ns >= MIN_N and ars == ars:
                subs.append((ars, "∩".join(sub)))
        if subs:
            best_sub_ar, best_sub = max(subs, key=lambda x: x[0])
            marg = round(ar_full - best_sub_ar, 3)
        else:
            best_sub_ar = np.nan; best_sub = ""; marg = np.nan
    rows.append(dict(combo=r["combo"], k=k, n=n_full, avgR=ar_full,
                     best_subset=best_sub, best_subset_avgR=best_sub_ar,
                     marginal_avgR=marg))

M = pd.DataFrame(rows)
hi = M[M.k >= 3].copy()
print(f"[고차 한계기여] 두해양수 {len(M)}개 중 k>=3: {len(hi)}개")
if len(hi):
    pos = (hi.marginal_avgR > 0).sum()
    print(f"  마지막 원자가 값 추가(marginal>0): {int(pos)}/{len(hi)} ({100*pos/len(hi):.0f}%)")
    print(f"  값 무의미/악화(marginal<=0): {int((hi.marginal_avgR <= 0).sum())}")
    print(f"  marginal_avgR 중앙값: {hi.marginal_avgR.median():.3f}\n")
    print("[한계기여 큰 상위 12 - 추가가 진짜 값인 조합]")
    print(hi.sort_values("marginal_avgR", ascending=False).head(12).to_string(index=False))
    print("\n[한계기여 음수 하위 8 - 원자 더했는데 오히려 나빠짐]")
    print(hi.sort_values("marginal_avgR").head(8).to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    pd.DataFrame({"항목": ["정의", "marginal", "결론지표", "OOS"],
                  "내용": ["두해양수 조합의 (k-1)부분집합 best avgR 대비 한계기여(IS)",
                          "avgR(전체) - max avgR(한 원자 뺀 부분집합). >0이면 마지막원자가 값추가.",
                          "marginal>0 비율 낮으면 '2원자면 충분, 복잡도 무의미' 증거.",
                          "2025-26 미사용."]}).to_excel(xw, sheet_name="notes", index=False)
    M.sort_values(["k", "marginal_avgR"], ascending=[True, False]).to_excel(xw, sheet_name="all_marginal", index=False)
    hi.sort_values("marginal_avgR", ascending=False).to_excel(xw, sheet_name="k3plus_marginal", index=False)
print(f"\n저장 → {OUT}")
