"""신규 원자 백테스트 검증 + 상관관계.
1) 룩어헤드 간접검증: 신규 run 의 기존 12원자 컬럼이 baseline(s5)과 (symbol,entry_time) 매칭상 100% 동일한지.
   → 12원자 코드 미변경(append-only) 구조보장 + 실측 바이트불변 확인.
2) 16원자 상관관계 행렬(phi/pearson) + 각 원자 단독 PF / OOS(2025-26) PF / 발생빈도.
사용: python atom_corr_verify.py [new_trades.csv] [baseline_trades.csv]
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
NEW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")
BASE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")
OLD12 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]


def pf(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def to_bool(col):
    return col.astype(str).str.strip().str.lower().map(
        {"true": True, "false": False, "1": True, "0": False, "o": True, ".": False}).fillna(False)


def key(d):
    return d["symbol"].astype(str) + "|" + pd.to_datetime(d["entry_time"], errors="coerce").astype(str)


d = pd.read_csv(NEW)
acols = [c for c in d.columns if c.startswith("a_")]
new_atoms = [c for c in acols if c not in OLD12]
print(f"[NEW] {NEW}\n  거래 {len(d)}행 | a_컬럼 {len(acols)}개 | 신규원자 {len(new_atoms)}: {new_atoms}")

# ── 1) 룩어헤드 간접검증: 기존 12원자 바이트불변 ──
if os.path.exists(BASE):
    b = pd.read_csv(BASE)
    d2 = d.copy(); b2 = b.copy()
    d2["_k"] = key(d2); b2["_k"] = key(b2)
    common = sorted(set(d2["_k"]) & set(b2["_k"]))
    dm = d2.drop_duplicates("_k").set_index("_k").loc[common]
    bm = b2.drop_duplicates("_k").set_index("_k").loc[common]
    print(f"\n[검증1·룩어헤드/불변] baseline={os.path.basename(os.path.dirname(BASE))} "
          f"매칭거래 {len(common)} (new {len(d)} / base {len(b)})")
    allmatch = True
    for a in OLD12:
        if a in dm.columns and a in bm.columns:
            mm = int((to_bool(dm[a]).values != to_bool(bm[a]).values).sum())
            flag = "OK" if mm == 0 else f"*** 불일치 {mm} ***"
            if mm: allmatch = False
            print(f"    {a:<20} mismatch={mm:>4}  {flag}")
    print(f"  => 기존 12원자 {'전부 바이트동일(룩어헤드 회귀 없음)' if allmatch else '불일치 발생! 점검필요'}")
else:
    print(f"\n[검증1] baseline 없음: {BASE} (구조보장 append-only 만으로 판단)")

# ── 2) 16원자 상관관계 + 단독 성과 ──
B = pd.DataFrame({a: to_bool(d[a]) for a in acols})
print(f"\n[검증2·상관관계] {len(acols)}원자 phi(=pearson on 0/1) 행렬:")
corr = B.astype(int).corr()
with pd.option_context("display.width", 200, "display.max_columns", 30):
    print(corr.round(2).to_string())

pnl = pd.to_numeric(d.get("net_pnl"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d.get("entry_time"), errors="coerce").dt.year.to_numpy()
te = np.isin(yr, [2025, 2026])
print(f"\n[원자 단독] base PF(전체)={pf(pnl):.3f}  OOS25-26 PF={pf(pnl[te]):.3f}  n={len(d)} nOOS={int(te.sum())}")
print(f"{'atom':<20}{'freq%':>7}{'PF_on':>8}{'PF_off':>8}{'PFoos_on':>10}{'n_on':>7}{'nOOS_on':>8}")
rows = []
for a in acols:
    m = B[a].values
    if m.sum() == 0:
        continue
    rows.append((a, 100*m.mean(), pf(pnl[m]), pf(pnl[~m]), pf(pnl[m & te]), int(m.sum()), int((m & te).sum())))
for a, fr, pon, poff, poos, non, noos in sorted(rows, key=lambda x: -x[4]):
    print(f"{a:<20}{fr:>7.1f}{pon:>8.3f}{poff:>8.3f}{poos:>10.3f}{non:>7}{noos:>8}")

# 최고 상관쌍 추출
print("\n[최고 상관쌍 |phi|>=0.5] (동어반복/중복 후보):")
pairs = []
for i in range(len(acols)):
    for j in range(i + 1, len(acols)):
        v = corr.iloc[i, j]
        if pd.notna(v) and abs(v) >= 0.5:
            pairs.append((acols[i], acols[j], v))
for a, b_, v in sorted(pairs, key=lambda x: -abs(x[2])):
    print(f"    {a:<20} ~ {b_:<20} phi={v:+.2f}")
if not pairs:
    print("    (|phi|>=0.5 없음 — 원자간 독립성 양호)")

out = os.path.join(os.path.dirname(NEW), "atom_corr_matrix.csv")
corr.to_csv(out)
print(f"\n상관행렬 저장 → {out}")
