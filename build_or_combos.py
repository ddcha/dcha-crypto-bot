"""12원자 OR-조합 전수탐색 (s5, HONEST_STAGE=5 미래참조제거 기준).
- OR 의미: 선택된 리터럴 중 하나라도 True 면 거래 채택.
- 양극(atom) + 음극(~atom) 리터럴 모두 탐색 (a_room=False 가 PF1.88 최강신호이므로 음극 필수).
- 핵심교훈(2024 과적합) 방어: 연도별 PF + walk-forward(train23-24 / test25-26) 컬럼 동반.
- 전체결과 CSV 저장 → 둠챠 검수용.
사용: python build_or_combos.py [trades_csv]
"""
import os, sys, io
import numpy as np
import pandas as pd
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
OUT = os.path.join(ROOT, "stage4d_honest", "s5")
MIN_TR = 80          # 의미있는 표본 하한
MAX_K = 4            # OR 리터럴 최대 개수 (많이 OR 하면 거의 전거래→baseline 수렴, 무의미)

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
net = d["net_pnl"].values.astype(float)
yr = d["year"].values
YEARS = [2023, 2024, 2025, 2026]
TRAIN = np.isin(yr, [2023, 2024]); TEST = np.isin(yr, [2025, 2026])

def pf_of(mask):
    s = net[mask]
    if len(s) == 0:
        return 0.0
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)

# 리터럴 행렬: 0..11 양극, 12..23 음극
A = np.column_stack([d[a].values.astype(bool) for a in ATOMS])     # n x 12
LIT = np.column_stack([A, ~A])                                     # n x 24
def lit_name(j):
    return ATOMS[j] if j < 12 else "~" + ATOMS[j - 12]
def lit_atom(j):
    return j % 12

print("=" * 110)
print(f"OR-조합 전수탐색 | {TRADES}")
print(f"총 {len(d)}거래 | 연도 {YEARS} | 전체 PF {pf_of(np.ones(len(d),bool)):.3f} | MIN_TR={MIN_TR} MAX_K={MAX_K} (양극+음극 24리터럴)")
print("=" * 110)

rows = []
for k in range(1, MAX_K + 1):
    for cs in combinations(range(24), k):
        atoms_used = [lit_atom(j) for j in cs]
        if len(set(atoms_used)) != len(atoms_used):     # 같은 원자 양극·음극 동시 OR 배제(항상 True)
            continue
        mask = LIT[:, cs].any(axis=1)
        n = int(mask.sum())
        if n < MIN_TR:
            continue
        p = pf_of(mask); ar = net[mask].mean()
        ytr = [pf_of(mask & (yr == y)) for y in YEARS]
        ptr = pf_of(mask & TRAIN); pte = pf_of(mask & TEST)
        rows.append({"k": k, "combo": " OR ".join(lit_name(j) for j in cs), "trades": n,
                     "PF": round(p, 3), "avgR": round(ar, 3),
                     "PF2023": round(ytr[0], 2), "PF2024": round(ytr[1], 2),
                     "PF2025": round(ytr[2], 2), "PF2026": round(ytr[3], 2),
                     "PF_train2324": round(ptr, 3), "PF_test2526": round(pte, 3),
                     "min_year_PF": round(min(ytr), 2)})

R = pd.DataFrame(rows)
R.sort_values("PF", ascending=False).to_csv(os.path.join(OUT, "or_combos_all.csv"), index=False)
print(f"\n전체 {len(R)}개 조합 → {os.path.join(OUT,'or_combos_all.csv')}\n")

def show(title, df, n=20):
    print(title)
    print(f"  {'combo':<46}{'k':>2}{'tr':>6}{'PF':>7}{'avgR':>7}{'23':>6}{'24':>6}{'25':>6}{'26':>6}{'tr2324':>8}{'te2526':>8}")
    for _, r in df.head(n).iterrows():
        print(f"  {r['combo']:<46}{int(r['k']):>2}{int(r['trades']):>6}{r['PF']:>7.3f}{r['avgR']:>+7.2f}"
              f"{r['PF2023']:>6.2f}{r['PF2024']:>6.2f}{r['PF2025']:>6.2f}{r['PF2026']:>6.2f}"
              f"{r['PF_train2324']:>8.2f}{r['PF_test2526']:>8.2f}")
    print()

show("[1] 전체기간 PF 상위", R.sort_values("PF", ascending=False))
# walk-forward 안정: train>1.05 & test>1.05 & 모든 연도>0.9
wf = R[(R.PF_train2324 > 1.05) & (R.PF_test2526 > 1.05) & (R.min_year_PF > 0.9)]
show(f"[2] ★walk-forward 안정 (train>1.05 & test>1.05 & 모든연도>0.9) — {len(wf)}개", wf.sort_values("PF_test2526", ascending=False))
# OOS(test) 우선
show("[3] OOS test25-26 PF 상위 (train도 >1)", R[R.PF_train2324 > 1.0].sort_values("PF_test2526", ascending=False))
print("=" * 110)
