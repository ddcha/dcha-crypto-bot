"""해로운 5원자 제외 후 남은 11원자만으로 IS(2023-24) 전 부분집합 양수 재스캔. OOS 미사용.
제외: wick_le_q1, sweep, pre_total_ge4, sweep_count_2_4, pre_total_ge1 (IS·OOS 양쪽 d_avgR<0).
남은 11: volume, score_ge13, trend_align, mss, fvg, overlap, room, killzone,
        atr_expansion, disp_strength, volume_strict.
양수=net PF>1, n>=MIN_N. both_years=pf23>1 AND pf24>1. worst_avgR=min(avgR23,avgR24).
redundant=더 작은 양수조합의 상위집합. core=비중복. 이건 가설집합(IS), 검증 아님.
"""
import os, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
OUT = os.path.join(CDIR, "clean_atoms_IS.xlsx")
MIN_N = 15

EXCLUDE = {"wick_le_q1", "sweep", "pre_total_ge4", "sweep_count_2_4", "pre_total_ge1"}


def pf(s):
    s = np.asarray(s, dtype=float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
names_all = [c.replace("a_", "") for c in acols]
keep = [nm for nm in names_all if nm not in EXCLUDE]
print(f"[정제 원자셋] 전체 {len(names_all)} -> 제외 {len(EXCLUDE)} -> 사용 {len(keep)}")
print("  사용:", keep)

B = {nm: tb(d[f"a_{nm}"]).to_numpy() for nm in keep}
pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
IS = np.isin(yr, [2023, 2024]); y23 = (yr == 2023); y24 = (yr == 2024)

rows = []
for k in range(2, len(keep) + 1):
    for combo in itertools.combinations(keep, k):
        m = IS.copy()
        for a in combo:
            m = m & B[a]
        n = int(m.sum())
        if n < MIN_N:
            continue
        p = pnl[m]; PF = pf(p)
        if PF <= 1.0:
            continue
        r = rmul[m]; r = r[~np.isnan(r)]
        m23 = m & y23; m24 = m & y24
        r23 = rmul[m23]; r23 = r23[~np.isnan(r23)]
        r24 = rmul[m24]; r24 = r24[~np.isnan(r24)]
        rows.append(dict(
            combo="∩".join(combo), k=k, n=n, PF=round(PF, 3),
            avgR=round(float(r.mean()), 3) if len(r) else np.nan,
            win=round(100 * (p > 0).mean(), 1),
            n23=int(m23.sum()), n24=int(m24.sum()),
            pf23=round(pf(pnl[m23]), 3), pf24=round(pf(pnl[m24]), 3),
            avgR23=round(float(r23.mean()), 3) if len(r23) else np.nan,
            avgR24=round(float(r24.mean()), 3) if len(r24) else np.nan,
        ))

R = pd.DataFrame(rows)
R["both_years_pos"] = ((R.pf23 > 1) & (R.pf24 > 1)).astype(int)
R["worst_pf"] = R[["pf23", "pf24"]].min(axis=1).round(3)
R["worst_avgR"] = R[["avgR23", "avgR24"]].min(axis=1).round(3)
R["pf_gap"] = (R[["pf23", "pf24"]].max(axis=1) - R[["pf23", "pf24"]].min(axis=1)).round(3)
R["atomset"] = R["combo"].apply(lambda s: frozenset(s.split("∩")))

both = R[R.both_years_pos == 1].copy().sort_values(["worst_avgR", "n"], ascending=False).reset_index(drop=True)

# redundant / core on both-years set
sets = list(both["atomset"])
red = [int(any(j != i and sets[j] < s for j in range(len(sets)))) for i, s in enumerate(sets)]
both["redundant"] = red
core = both[both.redundant == 0].reset_index(drop=True)

cols = ["combo", "k", "n", "PF", "avgR", "win", "n23", "n24",
        "pf23", "pf24", "avgR23", "avgR24", "worst_pf", "worst_avgR", "pf_gap", "redundant"]

print(f"\n[정제셋 IS 전수] 양수조합 {len(R)}개")
print("  차수별 양수: " + " ".join(f"k{k}={int((R.k==k).sum())}" for k in sorted(R.k.unique())))
print(f"  두해다양수(IS-CV): {int(R.both_years_pos.sum())}개 / 그중 비중복 core {len(core)}개")
print(f"  worst_avgR>0 (약한해도 R양수): {int((both.worst_avgR>0).sum())}개\n")
print("[두해양수 core - worst_avgR 순 상위]")
print(core[cols[:-1]].head(25).to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    pd.DataFrame({"항목": ["정의", "제외원자", "사용원자", "양수", "both_years", "worst_avgR", "core", "OOS"],
                  "내용": ["해로운5 제외 후 11원자 IS 전수 양수조합",
                          ", ".join(sorted(EXCLUDE)), ", ".join(keep),
                          "net PF>1 & n>=15 (IS=23-24)",
                          "pf23>1 AND pf24>1 (IS 내부 교차검증)",
                          "min(avgR23,avgR24). >0이면 약한해도 R기준 양수.",
                          "더작은 양수조합의 상위집합 아닌 최소후보.",
                          "2025-26 일절 미사용."]}).to_excel(xw, sheet_name="notes", index=False)
    R.sort_values(["both_years_pos", "worst_avgR"], ascending=False).to_excel(xw, sheet_name="all_positive_clean", index=False)
    both[cols].to_excel(xw, sheet_name="both_years_clean", index=False)
    core[cols].to_excel(xw, sheet_name="core_nonredundant", index=False)
print(f"\n저장 -> {OUT}")
