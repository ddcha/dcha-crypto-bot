"""
옵션 B Step 1 — 일반 패턴 PF 검증

baseline (wave_baseline) 데이터에서 일반화 가능한 패턴들을 정의하고
각 패턴의 PF/win%/일관성 측정.

검증할 일반 패턴 (가설):
  WEAK 후보:
    P1) D1 ≠ H4 (반대 방향): D1=impulse_up + H4=impulse_down (또는 반대)
    P2) H1=expansion + short
    P3) H1=expansion + long
    P4) D1=expansion + side=opposite of H1
    P5) D1=impulse_up + side=long + h4=expansion (D1 trend 끝물?)
    P6) D1=impulse_down + side=short + h4=expansion

  STRONG 후보:
    P7) H1=compression (모든 side, 모든 d1)
    P8) D1 = H4 = same direction (impulse continuation)
    P9) D1=expansion + H4=expansion (변동성 확장 시기)
    P10) D1=impulse_up + H4=compression + side=long (D1 trend 안의 H4 조정 끝)
    P11) D1=impulse_down + H4=compression + side=short

각 패턴: 전체 PF / 분기별 일관성 / 표본 수
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path("stage4l_redist_outputs_wave_baseline")
SCEN = "boost25"

t = pd.read_csv(DATA / f"stage4l_{SCEN}_out_skip_trades.csv")
t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
t["quarter"] = t["entry_time"].dt.to_period("Q")
t["d1"] = t["d1_wave_state"].astype(str)
t["h4"] = t["h4_wave_state"].astype(str)
t["h1"] = t["h1_wave_state"].astype(str)

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*95); print(s); print(ch*95)

baseline_pf = fmt_pf(t)
banner(f"[{SCEN.upper()}] 전체 {len(t)} trades / win {(t['net_pnl']>0).mean()*100:.2f}% / PF {baseline_pf:.3f}")

# ─────────────────────────────────────────────────────────
# 패턴 정의
# ─────────────────────────────────────────────────────────
patterns = [
    # WEAK 후보
    ("P1_D1xH4_opposite",
        ((t["d1"]=="impulse_up") & (t["h4"]=="impulse_down")) |
        ((t["d1"]=="impulse_down") & (t["h4"]=="impulse_up"))),
    ("P2_H1expansion_SHORT",
        (t["h1"]=="expansion") & (t["side"]=="short")),
    ("P3_H1expansion_LONG",
        (t["h1"]=="expansion") & (t["side"]=="long")),
    ("P4_D1expansion_short",
        (t["d1"]=="expansion") & (t["side"]=="short")),
    ("P5_D1up_H4expansion_long",
        (t["d1"]=="impulse_up") & (t["h4"]=="expansion") & (t["side"]=="long")),
    ("P6_D1down_H4expansion_short",
        (t["d1"]=="impulse_down") & (t["h4"]=="expansion") & (t["side"]=="short")),

    # STRONG 후보
    ("P7_H1compression_all",
        t["h1"]=="compression"),
    ("P7a_H1compression_LONG",
        (t["h1"]=="compression") & (t["side"]=="long")),
    ("P7b_H1compression_SHORT",
        (t["h1"]=="compression") & (t["side"]=="short")),
    ("P8_D1eqH4_continuation",
        ((t["d1"]=="impulse_up") & (t["h4"]=="impulse_up")) |
        ((t["d1"]=="impulse_down") & (t["h4"]=="impulse_down"))),
    ("P9_expansion_x_expansion",
        (t["d1"]=="expansion") & (t["h4"]=="expansion")),
    ("P10_D1up_H4compression_LONG",
        (t["d1"]=="impulse_up") & (t["h4"]=="compression") & (t["side"]=="long")),
    ("P11_D1down_H4compression_SHORT",
        (t["d1"]=="impulse_down") & (t["h4"]=="compression") & (t["side"]=="short")),
    # 추가 SMC 정통 setup
    ("P12_D1up_correction_LONG",
        (t["d1"]=="impulse_up") & (t["h4"].isin(["compression","expansion"])) & (t["side"]=="long")),
    ("P13_D1down_correction_SHORT",
        (t["d1"]=="impulse_down") & (t["h4"].isin(["compression","expansion"])) & (t["side"]=="short")),
]

# ─────────────────────────────────────────────────────────
# A) 전체 패턴 PF
# ─────────────────────────────────────────────────────────
banner("A) 일반 패턴 전체 성과")
print(f"\n{'pattern':<32} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
results = []
for name, mask in patterns:
    sub = t[mask]
    n = len(sub)
    if n == 0:
        results.append((name, 0, 0, 0, 0, 0))
        continue
    win = (sub["net_pnl"]>0).mean()*100
    pf = fmt_pf(sub)
    avr = sub["r_multiple"].mean()
    pnl = sub["net_pnl"].sum()
    results.append((name, n, win, pf, avr, pnl))
    print(f"{name:<32} {n:>5} {n/len(t)*100:>5.1f}% "
          f"{win:>6.2f}% {pf:>8.3f} {avr:>+8.3f} {pnl:>+14,.0f}")

# ─────────────────────────────────────────────────────────
# B) 분기별 일관성 — 각 패턴의 PF가 각 분기에서 baseline 대비 어떤지
# ─────────────────────────────────────────────────────────
banner("B) 분기별 일관성 — 패턴 PF가 baseline보다 일관되게 좋거나 나쁜가?")
quarters = sorted(t["quarter"].dropna().unique().tolist())
print(f"\n총 분기: {len(quarters)}")

print(f"\n{'pattern':<32} {'얼마 분기 이상우세':>16} {'동등':>6} {'열세':>6} {'일관성%':>9} {'유효 분기':>10}")
for name, mask in patterns:
    sub = t[mask]
    if len(sub) == 0: continue
    n_better = 0
    n_worse = 0
    n_tie = 0
    n_valid = 0
    for q in quarters:
        sub_q = sub[sub["quarter"]==q]
        all_q = t[t["quarter"]==q]
        if len(sub_q) < 5 or len(all_q) < 30:
            continue
        n_valid += 1
        pf_q = fmt_pf(sub_q)
        pf_q_all = fmt_pf(all_q)
        if pf_q > pf_q_all * 1.15:
            n_better += 1
        elif pf_q < pf_q_all * 0.85:
            n_worse += 1
        else:
            n_tie += 1
    if n_valid > 0:
        cons = n_better / n_valid * 100
        worse_pct = n_worse / n_valid * 100
        # 해석: better가 많으면 STRONG, worse가 많으면 WEAK 신호
        sign = "STRONG" if cons > 50 else ("WEAK" if worse_pct > 50 else "MIXED")
        print(f"{name:<32} {n_better:>16} {n_tie:>6} {n_worse:>6} {cons:>8.1f}% {n_valid:>10} [{sign}]")

# ─────────────────────────────────────────────────────────
# C) 패턴 그룹 — 같은 시그널이지만 다른 정의 비교
# ─────────────────────────────────────────────────────────
banner("C) 패턴 그룹 비교 (대조군 vs 실험군)")

# H1 wave_state 비교 — compression vs expansion vs impulse
print("\n[H1 wave_state별 (모든 side 합)]")
print(f"  {'h1':<15} {'n':>5} {'PF':>7} {'pnl':>13}")
for h1 in ["compression", "expansion", "impulse_up", "impulse_down", "unclear"]:
    sub = t[t["h1"]==h1]
    if len(sub) == 0: continue
    print(f"  {h1:<15} {len(sub):>5} {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+13,.0f}")

# H1 + side
print("\n[H1 wave_state × side]")
print(f"  {'h1':<15} {'side':<7} {'n':>5} {'PF':>7} {'pnl':>13}")
for h1 in ["compression", "expansion", "impulse_up", "impulse_down"]:
    for side in ["long", "short"]:
        sub = t[(t["h1"]==h1) & (t["side"]==side)]
        if len(sub) == 0: continue
        print(f"  {h1:<15} {side:<7} {len(sub):>5} {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+13,.0f}")

# D1=H4 vs D1≠H4 (impulse만)
print("\n[D1과 H4 정합성 (impulse 케이스만)]")
m_eq = ((t["d1"]=="impulse_up") & (t["h4"]=="impulse_up")) | \
       ((t["d1"]=="impulse_down") & (t["h4"]=="impulse_down"))
m_op = ((t["d1"]=="impulse_up") & (t["h4"]=="impulse_down")) | \
       ((t["d1"]=="impulse_down") & (t["h4"]=="impulse_up"))
sub_eq = t[m_eq]
sub_op = t[m_op]
print(f"  D1=H4 (continuation): n={len(sub_eq)}, PF={fmt_pf(sub_eq):.2f}, pnl=${sub_eq['net_pnl'].sum():+,.0f}")
print(f"  D1≠H4 (opposite)    : n={len(sub_op)}, PF={fmt_pf(sub_op):.2f}, pnl=${sub_op['net_pnl'].sum():+,.0f}")

# ─────────────────────────────────────────────────────────
# D) 종합 — 처방 후보 정렬
# ─────────────────────────────────────────────────────────
banner("D) 처방 후보 정렬 (명확한 패턴만)")
print(f"\nbaseline PF: {baseline_pf:.3f}")
print(f"\n[가장 약한 패턴 — risk 축소 후보]")
results.sort(key=lambda x: x[3])
for name, n, win, pf, avr, pnl in results:
    if n < 50: continue  # 표본 너무 적은 건 제외
    if pf < baseline_pf * 0.7:
        print(f"  → {name}: n={n}, PF={pf:.2f} (baseline {baseline_pf:.2f}의 {pf/baseline_pf*100:.0f}%) pnl=${pnl:+,.0f}")

print(f"\n[가장 강한 패턴 — risk boost 후보]")
results.sort(key=lambda x: -x[3])
for name, n, win, pf, avr, pnl in results:
    if n < 50: continue
    if pf > baseline_pf * 1.3:
        print(f"  → {name}: n={n}, PF={pf:.2f} (baseline {baseline_pf:.2f}의 {pf/baseline_pf*100:.0f}%) pnl=${pnl:+,.0f}")
