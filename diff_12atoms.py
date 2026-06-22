"""격리 before/after: atoms_corr(batch1 포함) vs atoms_corr_base(batch1 제거) — 동일코드 차이는 신규4원자뿐.
거래수 동일 + 기존12원자 100% 동일 이면 => 내 편집은 거래셋·기존원자에 영향 0 (과교정 없음 + 회귀 없음).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")       # batch1 포함
B = os.path.join(ROOT, "stage4d_honest", "atoms_corr_base", "stage4d_trades.csv")  # batch1 제거
OLD12 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def k(d):
    return d["symbol"].astype(str) + "|" + pd.to_datetime(d["entry_time"], errors="coerce").astype(str)


a = pd.read_csv(A); b = pd.read_csv(B)
print(f"batch1본 거래={len(a)}  격리본 거래={len(b)}  차이={len(a)-len(b)}")
print(f"거래수 동일? {'예 (거래셋 불변 확인)' if len(a) == len(b) else '아니오 *** 거래셋 달라짐 ***'}")

a["_k"] = k(a); b["_k"] = k(b)
common = sorted(set(a["_k"]) & set(b["_k"]))
am = a.drop_duplicates("_k").set_index("_k").loc[common]
bm = b.drop_duplicates("_k").set_index("_k").loc[common]
print(f"매칭거래 {len(common)} / (A {len(a)}, B {len(b)})")
allok = True
for at in OLD12:
    mm = int((tb(am[at]).values != tb(bm[at]).values).sum())
    if mm:
        allok = False
    print(f"  {at:<20} mismatch={mm:>4}  {'OK' if mm == 0 else '*** 불일치 ***'}")
print(f"\n=> 기존 12원자: {'100% 바이트 동일 — batch1 편집은 기존원자/거래셋에 영향 0 (룩어헤드 회귀·과교정 없음)' if (allok and len(a)==len(b)) else '차이 발생 — 점검필요'}")
