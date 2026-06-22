"""[1]+[2] 병행 정직 tier 재정립 harness — s5(HONEST_STAGE=5, 미래참조 제거) 기준.
[2] 정직 원자 ΔPF 전수표: solo / 연도 walk-forward / 롱숏 분리 / 조합.
[1] D-tier 교차검증: D 생존이 volume×trend×fvg 로 설명되는가, 갈리는 지점은 어디인가.
입력만 바뀌고 로직 동일 → 둠챠 2단계(H1-fill) atom 재생성 후 같은 harness 재실행용.
사용: python build_honest_tier_harness.py [trades_csv]
"""
import os, sys, io
import numpy as np
import pandas as pd
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "s5", "stage4d_trades.csv")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
EDGE3 = ["a_volume", "a_trend_align", "a_fvg"]  # s5 solo +기여 3원자

def pf(s):
    pos = s[s > 0].sum(); neg = abs(s[s < 0].sum())
    return pos / neg if neg > 1e-9 else np.inf

def block(d, mask):
    sub = d.loc[mask, "net_pnl"]
    if len(sub) == 0:
        return (0, 0.0, 0.0, 0.0)
    return (len(sub), 100 * (sub > 0).mean(), pf(sub), sub.mean())

d = pd.read_csv(TRADES)
for a in ATOMS:
    if a in d.columns:
        d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
YEARS = sorted(d["year"].dropna().unique().astype(int))
L = "=" * 96
print(L); print(f"정직 tier harness  |  {TRADES}"); print(f"총 {len(d)}거래 | 연도 {YEARS} | 전체 PF {pf(d['net_pnl']):.3f}"); print(L)

# [A] solo ΔPF: 전체 + 연도 + 사이드
print("\n[A] SOLO 원자 ΔPF (PASS PF − FAIL PF) + 연도/사이드 PF")
print(f"  {'atom':<20}{'tr':>5}{'PF_T':>7}{'PF_F':>7}{'ΔPF':>8}{'long':>7}{'short':>7}" + "".join(f"{y:>7}" for y in YEARS))
rowsA = []
for a in ATOMS:
    nT, _, pfT, _ = block(d, d[a]); nF, _, pfF, _ = block(d, ~d[a])
    dPF = pfT - pfF
    lp = block(d, d[a] & (d["side"] == "long"))[2]; sp = block(d, d[a] & (d["side"] == "short"))[2]
    ycell = "".join(f"{block(d, d[a] & (d['year']==y))[2]:>7.2f}" for y in YEARS)
    print(f"  {a:<20}{nT:>5}{pfT:>7.2f}{pfF:>7.2f}{dPF:>+8.3f}{lp:>7.2f}{sp:>7.2f}{ycell}")
    rowsA.append((a, dPF, pfT, nT))

# [B] 조합 PF (size 1~3, min 60거래) + 연도 안정성
print("\n[B] 조합 PF (모든 원자 AND, ≥60거래, PF 상위) — ★연도 walk-forward 안정성")
print(f"  {'combo':<48}{'tr':>5}{'PF':>7}{'avgR':>7}" + "".join(f"{y:>8}" for y in YEARS))
combo_rows = []
for k in (1, 2, 3):
    for cs in combinations(ATOMS, k):
        m = np.ones(len(d), bool)
        for a in cs:
            m &= d[a].values
        if m.sum() < 60:
            continue
        sub = d.loc[m, "net_pnl"]
        combo_rows.append(("+".join(cs), m.sum(), pf(sub), sub.mean(), m))
combo_rows.sort(key=lambda r: -r[2])
for name, n, p, ar, m in combo_rows[:14]:
    ycell = "".join(f"{block(d, m & (d['year']==y).values)[2]:>8.2f}" for y in YEARS)
    print(f"  {name:<48}{n:>5}{p:>7.3f}{ar:>+7.3f}{ycell}")

# [B2] EDGE3 롱전용 + walk-forward train/test
print("\n[B2] EDGE3 (volume×trend×fvg) 정밀 — 전체 / 롱전용 / walk-forward(train 2023-24 → test 2025-26)")
m3 = np.ones(len(d), bool)
for a in EDGE3:
    m3 &= d[a].values
for tag, mm in [("EDGE3 전체", m3), ("EDGE3 롱전용", m3 & (d["side"] == "long").values)]:
    n, w, p, ar = block(d, mm)
    tr_m = mm & d["year"].isin([2023, 2024]).values
    te_m = mm & d["year"].isin([2025, 2026]).values
    ntr, _, ptr, _ = block(d, tr_m); nte, _, pte, _ = block(d, te_m)
    print(f"  {tag:<16} 전체 tr={n:>4} win={w:5.1f}% PF={p:6.3f} avgR={ar:+.3f}  |  "
          f"train23-24 tr={ntr:>3} PF={ptr:6.3f}  →  test25-26 tr={nte:>3} PF={pte:6.3f}")

# [C] D-tier 교차검증 [1]
print("\n[C] D-tier 분해 [1] — D 생존(PF1.61)이 EDGE3 로 설명되는가, 갈리는 지점")
if "tier" in d.columns:
    dD = d[d["tier"] == "D"]
    print(f"  D 전체: tr={len(dD)} PF={pf(dD['net_pnl']):.3f}  롱={pf(dD[dD.side=='long']['net_pnl']):.3f} 숏={pf(dD[dD.side=='short']['net_pnl']):.3f}")
    print("  D 내부 원자 True-rate & 그 원자 PASS시 D-PF:")
    for a in ATOMS:
        rate = 100 * dD[a].mean()
        pp = pf(dD.loc[dD[a], "net_pnl"]); nn = int(dD[a].sum())
        print(f"    {a:<20} rate={rate:5.1f}%  PASS_PF={pp:6.3f}({nn})")
    mD3 = np.ones(len(dD), bool)
    for a in EDGE3:
        mD3 &= dD[a].values
    print(f"  D∩EDGE3: tr={int(mD3.sum())} PF={pf(dD.loc[mD3,'net_pnl']):.3f}   "
          f"D∖EDGE3: tr={int((~mD3).sum())} PF={pf(dD.loc[~mD3,'net_pnl']):.3f}")
    print("  → D∖EDGE3 PF가 여전히 >1 이면 D 생존은 EDGE3 밖 요인 = 추가조사 지점")
print(L)
