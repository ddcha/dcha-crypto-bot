"""(A) 표본·안정성 우선 좁히기 — all_positive_IS.csv 에서 robust 후보 추출. OOS 미사용.
안정성 = 두 해(2023·2024) 다 여유 양수 + worst-year도 양수 + 표본 충분.
worst_pf=min(pf23,pf24), worst_avgR=min(avgR23,avgR24) 로 '약한 해' 기준 랭킹(한해운발 컷).
중복표시: 어떤 후보가 더 작은 후보의 상위집합(superset)이면 redundant=1.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
SRC = os.path.join(CDIR, "all_positive_IS.csv")
OUT = os.path.join(CDIR, "stable_shortlist_IS.xlsx")

# 안정성 임계
N_MIN = 30          # IS 표본 하한
PF_MARGIN = 1.15    # 두 해 각각 PF 이 이상 (간당간당 1.0~1.15 제외)

R = pd.read_csv(SRC)
R["worst_pf"] = R[["pf23", "pf24"]].min(axis=1)
R["worst_avgR"] = R[["avgR23", "avgR24"]].min(axis=1)
R["pf_gap"] = (R[["pf23", "pf24"]].max(axis=1) - R[["pf23", "pf24"]].min(axis=1)).round(3)
R["atoms"] = R["combo"].apply(lambda s: frozenset(s.split("∩")))

stab = R[(R.n >= N_MIN) & (R.pf23 >= PF_MARGIN) & (R.pf24 >= PF_MARGIN)
         & (R.avgR23 > 0) & (R.avgR24 > 0)].copy()
stab = stab.sort_values(["worst_avgR", "n"], ascending=False).reset_index(drop=True)

# 중복(superset) 표시: 더 작은 후보집합을 포함하면 redundant
sets = list(stab["atoms"])
red = []
for i, s in enumerate(sets):
    is_red = any(j != i and sets[j] < s for j in range(len(sets)))
    red.append(int(is_red))
stab["redundant"] = red
core = stab[stab.redundant == 0].reset_index(drop=True)  # 최소(비중복) 후보만

cols = ["combo", "k", "n", "PF", "avgR", "win", "n23", "n24",
        "pf23", "pf24", "avgR23", "avgR24", "worst_pf", "worst_avgR", "pf_gap", "redundant"]

print(f"[A: 안정성 좁히기] 원본 양수 {len(R)} → 필터(n>={N_MIN}, pf23·pf24>={PF_MARGIN}, 두해avgR>0) {len(stab)}")
print(f"  그중 비중복(core) {len(core)}개\n")
print("[core 후보 - worst-year avgR 순, 표본 큰 순]")
print(core[cols[:-1]].to_string(index=False))

notes = pd.DataFrame({"항목": [
    "생성일", "스코프", "★OOS", "안정성기준", "worst_pf/avgR", "pf_gap", "redundant", "core", "위상", "다음",
], "내용": [
    "2026-06-15", "IS=2023-24 710거래. all_positive_IS 에서 추출.", "2025-26 일절 미참조.",
    f"n>={N_MIN} AND pf23>={PF_MARGIN} AND pf24>={PF_MARGIN} AND 두 해 avgR>0",
    "두 해 중 약한 해의 PF/avgR. 랭킹 1차키(한해운발 방지).",
    "pf23·pf24 격차. 작을수록 두 해 균질(더 안정).",
    "더 작은 후보집합의 상위집합이면 1(중복). core=redundant 0 만.",
    "비중복 최소 후보 — 진짜 독립 시작점.",
    "여전히 IS 가설. 검증 아님.",
    "core에서 소수 동결 → 그때 처음 2025-26 1회 조회(또는 워크포워드).",
]})
with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    notes.to_excel(xw, sheet_name="notes", index=False)
    stab[cols].to_excel(xw, sheet_name="stable_all", index=False)
    core[cols].to_excel(xw, sheet_name="stable_core_nonredundant", index=False)
print(f"\n저장 → {OUT}")
print(f"  stable_all {len(stab)} / stable_core_nonredundant {len(core)}")
