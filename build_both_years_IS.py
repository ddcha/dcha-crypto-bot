"""두 해 다 양수(pf23>1 AND pf24>1) = IS 내부 교차검증 통과 119개 정밀분석. OOS 미사용.
① 원자 참여빈도(무엇이 두해양수 신호를 떠받치나) ② 비중복 core ③ 전체 정렬 리스트.
worst_pf=min(pf23,pf24), worst_avgR=min(avgR23,avgR24): 약한 해 기준(한해운발 방지).
"""
import os
import numpy as np
import pandas as pd
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
SRC = os.path.join(CDIR, "all_positive_IS.csv")
OUT = os.path.join(CDIR, "both_years_pos_IS.xlsx")

R = pd.read_csv(SRC)
B = R[(R.pf23 > 1) & (R.pf24 > 1)].copy()
B["worst_pf"] = B[["pf23", "pf24"]].min(axis=1).round(3)
B["worst_avgR"] = B[["avgR23", "avgR24"]].min(axis=1).round(3)
B["pf_gap"] = (B[["pf23", "pf24"]].max(axis=1) - B[["pf23", "pf24"]].min(axis=1)).round(3)
B["atoms"] = B["combo"].apply(lambda s: frozenset(s.split("∩")))
B = B.sort_values(["worst_avgR", "n"], ascending=False).reset_index(drop=True)

# 원자 참여빈도 (119개 중 몇 조합에 등장 + 그 조합들 worst_avgR 중앙값)
cnt = Counter()
wmed = {}
for _, r in B.iterrows():
    for a in r["atoms"]:
        cnt[a] += 1
for a in cnt:
    wmed[a] = round(float(B[B["combo"].str.split("∩").apply(lambda s: a in s)]["worst_avgR"].median()), 3)
freq = pd.DataFrame([dict(atom=a, in_combos=cnt[a], pct_of_119=round(100*cnt[a]/len(B), 1),
                          median_worst_avgR=wmed[a]) for a in cnt]
                    ).sort_values("in_combos", ascending=False).reset_index(drop=True)

# 비중복 core: 더 작은 조합의 상위집합이면 제외
sets = list(B["atoms"])
red = [int(any(j != i and sets[j] < s for j in range(len(sets)))) for i, s in enumerate(sets)]
B["redundant"] = red
core = B[B.redundant == 0].reset_index(drop=True)

cols = ["combo", "k", "n", "PF", "avgR", "win", "n23", "n24",
        "pf23", "pf24", "avgR23", "avgR24", "worst_pf", "worst_avgR", "pf_gap", "redundant"]

print(f"[두 해 다 양수 = IS-CV 통과] {len(B)}개")
print(f"  차수별: " + " ".join(f"k{k}={int((B.k==k).sum())}" for k in sorted(B.k.unique())))
print(f"  비중복 core: {len(core)}개\n")
print("[원자 참여빈도 (119조합 중)]")
print(freq.to_string(index=False))
print(f"\n[비중복 core - worst_avgR 순] {len(core)}개")
print(core[cols[:-1]].to_string(index=False))

notes = pd.DataFrame({"항목": [
    "생성일", "정의", "★OOS", "worst_pf/avgR", "pf_gap", "원자빈도",
    "redundant/core", "표본주의", "위상", "다음",
], "내용": [
    "2026-06-15", "pf23>1 AND pf24>1 (2023·2024 둘 다 양수, IS 내부 교차검증)", "2025-26 일절 미참조.",
    "두 해 중 약한 해의 PF/avgR. 한해운발 방지 1차키.",
    "두 해 PF 격차. 작을수록 균질.",
    "각 원자가 119조합 중 몇 개에 등장 + 그 조합들 worst_avgR 중앙값. 신호 떠받치는 축 식별.",
    "redundant=더 작은조합의 상위집합. core=비중복 최소후보.",
    "2023 얇음(203거래) → pf23 노이즈. worst가 2023쪽이면 더 의심.",
    "여전히 IS 가설집합. 검증 아님.",
    "core에서 소수 동결 → 그때 처음 2025-26 1회(또는 워크포워드 LB5).",
]})
with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    notes.to_excel(xw, sheet_name="notes", index=False)
    B[cols].to_excel(xw, sheet_name="both_years_119", index=False)
    core[cols].to_excel(xw, sheet_name="core_nonredundant", index=False)
    freq.to_excel(xw, sheet_name="atom_frequency", index=False)
print(f"\n저장 → {OUT}")
print(f"  both_years_119 {len(B)} / core_nonredundant {len(core)} / atom_frequency {len(freq)}")
