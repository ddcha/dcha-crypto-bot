"""둠챠 15m 정밀화 before/after 검증.

전제: DOOMCHA override 는 _atoms_final(로그단계)에만 적용 → 후보 OR게이트 불변
      → 두 실행의 '거래 집합(entry_time/side/symbol)'은 동일해야 함.
      a_trend_align / a_room 컬럼만 달라지고 나머지 10원자는 행단위 바이트동일이어야 함.

검증 항목:
 [1] 두 로그 거래 키 동일성 (같은 거래를 측정했는가)
 [2] 10원자 행단위 불변 (과교정 없이 2원자만 건드렸는가)
 [3] a_trend_align / a_room flip 수 (False→True / True→False)
 [4] a_room=True 부분집합 연도별 PF: before vs after (2025/26 의 0.00 회복 여부)
 [5] a_trend_align=True 부분집합 연도별 PF: before vs after

사용: python verify_doomcha_15m.py [baseline_csv] [doomcha_csv]
"""
import os, sys, io
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "atoms_one_bt", "stage4d_trades.csv")
DOOM = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "stage4d_honest", "atoms_doomcha_15m", "stage4d_trades.csv")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
PRECISE = ["a_trend_align", "a_room"]                  # override 대상
INVARIANT = [a for a in ATOMS if a not in PRECISE]     # 불변이어야 하는 10원자


def load(path):
    d = pd.read_csv(path)
    for a in ATOMS:
        d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
    d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
    sym = d["symbol"] if "symbol" in d.columns else ""
    d["_key"] = d["entry_time"].astype(str) + "|" + d["side"].astype(str) + "|" + sym.astype(str)
    return d


for p in (BASE, DOOM):
    if not os.path.exists(p):
        print(f"[!] 파일 없음: {p}\n    먼저 baseline(run_12atoms_one_backtest.py) 과 "
              f"doomcha(run_doomcha_15m_backtest.py) 를 모두 실행하세요.")
        sys.exit(1)

B = load(BASE); D = load(DOOM)
L = "=" * 96
print(L); print(f"둠챠 15m 정밀화 before/after 검증\n  before: {BASE}\n  after : {DOOM}"); print(L)

# [1] 거래 키 동일성
kb, kd = set(B["_key"]), set(D["_key"])
print(f"\n[1] 거래 집합 | before {len(B)} | after {len(D)} | 교집합 {len(kb & kd)}"
      f" | before만 {len(kb - kd)} | after만 {len(kd - kb)}")
if kb != kd:
    print("  ⚠ 거래 집합 불일치 — DOOMCHA 가 후보게이트에 새어들어갔을 수 있음(설계상 동일해야 함).")
else:
    print("  ✓ 거래 집합 완전 동일 (같은 거래를 측정 — 깨끗한 before/after).")

# 공통 키만 정렬 정합
B2 = B[B["_key"].isin(kb & kd)].drop_duplicates("_key").set_index("_key").sort_index()
D2 = D[D["_key"].isin(kb & kd)].drop_duplicates("_key").set_index("_key").sort_index()

# [2] 10원자 불변
print("\n[2] 불변이어야 할 10원자 행단위 비교 (diff>0 이면 과교정 의심)")
ok = True
for a in INVARIANT:
    diff = int((B2[a].values != D2[a].values).sum())
    flag = "" if diff == 0 else "  ⚠과교정"
    if diff: ok = False
    print(f"  {a:<20} diff={diff}{flag}")
print("  ✓ 10원자 전부 불변 — 과교정 없음." if ok else "  ⚠ 일부 원자 변동 — 점검 필요.")

# [3] 정밀화 2원자 flip
print("\n[3] 정밀화 대상 2원자 변화 (before→after)")
for a in PRECISE:
    bv, dv = B2[a].values, D2[a].values
    ft = int((~bv & dv).sum())   # False→True (새로 켜짐)
    tf = int((bv & ~dv).sum())   # True→False (꺼짐)
    print(f"  {a:<20} False→True {ft:>4} | True→False {tf:>4} | 순변화 {dv.sum()-bv.sum():+d}"
          f" (before True {int(bv.sum())} → after True {int(dv.sum())})")

# [4][5] 부분집합 연도별 PF before vs after
def pf_block(title, atom):
    print(f"\n{title}")
    print(f"  {'year':>6} | {'before PF(n)':>18} | {'after PF(n)':>18}")
    for y in (2023, 2024, 2025, 2026):
        mb = B2[atom].values
        md = D2[atom].values
        sb = B2.loc[mb & (B2.year == y), "net_pnl"].to_numpy(float)
        sd = D2.loc[md & (D2.year == y), "net_pnl"].to_numpy(float)
        def _pf(s):
            if not len(s): return "—", 0
            pos = s[s > 0].sum(); neg = -s[s < 0].sum()
            v = pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)
            return (f"{v:.3f}", len(s))
        vb, cb = _pf(sb); vd, cd = _pf(sd)
        print(f"  {y:>6} | {vb:>10}({cb:>4}) | {vd:>10}({cd:>4})")

pf_block("[4] a_room=True 부분집합 연도별 PF — 2025/26 의 0.00 회복 여부 핵심", "a_room")
pf_block("[5] a_trend_align=True 부분집합 연도별 PF", "a_trend_align")

print("\n" + L)
print("해석: [2] 가 전부 diff=0 이어야 정밀화가 의도한 2원자에만 적용된 것.")
print("      [4] before 2025/26 PF 가 0.00(또는 거래수 0)에서 after 유의미한 값으로 살아나면")
print("      → a_room 의 사망이 '측정붕괴(현재봉 누락)'였다는 강한 증거.")
print("      여전히 죽어있으면 → 측정이 아니라 실제 레짐 사망(둠챠로도 못 살림).")
print(L)
