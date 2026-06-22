"""
T2 trade 정밀 분석
  T2 = D1 wave AND H4 wave 둘 다 같은 방향 (impulse_up or impulse_down)
  T2 aligned = 강한 trend continuation 방향 진입
  T2 counter = 강한 trend 거스르는 진입 (위험할 수도, 또는 mean-reversion alpha)

  세분화:
    - H1 wave_state별 → 어느 H1 phase가 위험/안전
    - tier별 → 어느 tier에서 발생
    - sentiment_label별
    - 분기별 시점
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
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
    print(); print(ch*100); print(s); print(ch*100)

# T2 분류
def t2_align(row):
    if row["d1"]=="impulse_up" and row["h4"]=="impulse_up":
        return "aligned" if row["side"]=="long" else "counter"
    if row["d1"]=="impulse_down" and row["h4"]=="impulse_down":
        return "aligned" if row["side"]=="short" else "counter"
    return "n/a"

t["T2"] = t.apply(t2_align, axis=1)
t2_a = t[t["T2"]=="aligned"]
t2_c = t[t["T2"]=="counter"]

banner(f"T2 aligned: n={len(t2_a)} PF={fmt_pf(t2_a):.2f}  /  T2 counter: n={len(t2_c)} PF={fmt_pf(t2_c):.2f}")

# ─────────────────────────────────────────────────────────
# A) H1 wave_state별 세분
# ─────────────────────────────────────────────────────────
banner("[A] T2 × H1 wave_state — H1 phase 따라 효과 달라지나?", "=")

print(f"\n[T2 ALIGNED] (전체 n={len(t2_a)}, PF {fmt_pf(t2_a):.2f})")
print(f"  {'h1':<15} {'n':>5} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for h1 in sorted(t2_a["h1"].unique()):
    sub = t2_a[t2_a["h1"]==h1]
    if len(sub)==0: continue
    print(f"  {h1:<15} {len(sub):>5} {(sub['net_pnl']>0).mean()*100:>6.2f}% "
          f"{fmt_pf(sub):>8.2f} {sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

print(f"\n[T2 COUNTER] (전체 n={len(t2_c)}, PF {fmt_pf(t2_c):.2f})")
print(f"  {'h1':<15} {'n':>5} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for h1 in sorted(t2_c["h1"].unique()):
    sub = t2_c[t2_c["h1"]==h1]
    if len(sub)==0: continue
    print(f"  {h1:<15} {len(sub):>5} {(sub['net_pnl']>0).mean()*100:>6.2f}% "
          f"{fmt_pf(sub):>8.2f} {sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# B) D1 방향별 (up vs down) 분리
# ─────────────────────────────────────────────────────────
banner("[B] D1=impulse_up vs D1=impulse_down 분리 — 대칭적인가?", "=")

for d1_dir in ["impulse_up", "impulse_down"]:
    print(f"\n[D1={d1_dir}]")
    print(f"  T2 (d1+h4 모두 {d1_dir})  →  side별:")
    sub = t[(t["d1"]==d1_dir) & (t["h4"]==d1_dir)]
    for side in ["long", "short"]:
        ss = sub[sub["side"]==side]
        if len(ss)==0: continue
        is_aligned = (d1_dir=="impulse_up" and side=="long") or (d1_dir=="impulse_down" and side=="short")
        tag = "[ALIGNED]" if is_aligned else "[COUNTER]"
        print(f"    {side:<6} {tag:<10} n={len(ss):>4} PF={fmt_pf(ss):>6.2f} "
              f"pnl=${ss['net_pnl'].sum():>+12,.0f}")

    # H1 분포
    print(f"  ↓ H1 wave별:")
    for side in ["long", "short"]:
        for h1 in sorted(sub["h1"].unique()):
            ss = sub[(sub["side"]==side) & (sub["h1"]==h1)]
            if len(ss) < 5: continue
            is_aligned = (d1_dir=="impulse_up" and side=="long") or (d1_dir=="impulse_down" and side=="short")
            tag = "AL" if is_aligned else "CT"
            print(f"    {side:<6} h1={h1:<15} [{tag}] n={len(ss):>4} PF={fmt_pf(ss):>6.2f} "
                  f"pnl=${ss['net_pnl'].sum():>+11,.0f}")

# ─────────────────────────────────────────────────────────
# C) tier_4e별 세분
# ─────────────────────────────────────────────────────────
banner("[C] T2 × tier_4e — 어느 tier에서 발생?", "=")

print(f"\n[T2 ALIGNED]")
print(f"  {'tier':<18} {'n':>5} {'PF':>8} {'pnl':>14}")
for tier in sorted(t2_a["tier_4e"].dropna().unique()):
    sub = t2_a[t2_a["tier_4e"]==tier]
    if len(sub)==0: continue
    print(f"  {tier:<18} {len(sub):>5} {fmt_pf(sub):>8.2f} {sub['net_pnl'].sum():>+14,.0f}")

print(f"\n[T2 COUNTER]")
print(f"  {'tier':<18} {'n':>5} {'PF':>8} {'pnl':>14}")
for tier in sorted(t2_c["tier_4e"].dropna().unique()):
    sub = t2_c[t2_c["tier_4e"]==tier]
    if len(sub)==0: continue
    print(f"  {tier:<18} {len(sub):>5} {fmt_pf(sub):>8.2f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# D) sentiment_label별
# ─────────────────────────────────────────────────────────
banner("[D] T2 × sentiment_label", "=")
if "sentiment_label" in t.columns:
    print(f"\n[T2 ALIGNED]")
    print(f"  {'sentiment':<25} {'n':>5} {'PF':>8} {'pnl':>14}")
    for sl in sorted(t2_a["sentiment_label"].dropna().unique()):
        sub = t2_a[t2_a["sentiment_label"]==sl]
        if len(sub) < 5: continue
        print(f"  {sl:<25} {len(sub):>5} {fmt_pf(sub):>8.2f} {sub['net_pnl'].sum():>+14,.0f}")

    print(f"\n[T2 COUNTER]")
    print(f"  {'sentiment':<25} {'n':>5} {'PF':>8} {'pnl':>14}")
    for sl in sorted(t2_c["sentiment_label"].dropna().unique()):
        sub = t2_c[t2_c["sentiment_label"]==sl]
        if len(sub) < 5: continue
        print(f"  {sl:<25} {len(sub):>5} {fmt_pf(sub):>8.2f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# E) T2 × H1 × side 매트릭스 — 최종 정밀 sub-pattern 식별
# ─────────────────────────────────────────────────────────
banner("[E] T2 × H1 × side — 정밀 sub-pattern (n>=10)", "=")
print(f"\n  {'T2':<10} {'h1':<15} {'side':<7} {'n':>5} {'win%':>7} {'PF':>8} {'pnl':>14}")
patterns = []
for cat in ["aligned", "counter"]:
    for h1 in sorted(t["h1"].unique()):
        for side in ["long", "short"]:
            sub = t[(t["T2"]==cat) & (t["h1"]==h1) & (t["side"]==side)]
            if len(sub) < 10: continue
            patterns.append((cat, h1, side, len(sub), fmt_pf(sub), sub["net_pnl"].sum()))
            print(f"  {cat:<10} {h1:<15} {side:<7} {len(sub):>5} "
                  f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.2f} {sub['net_pnl'].sum():>+14,.0f}")

# Top/Bottom 정리
patterns.sort(key=lambda x: -x[4])
print(f"\n  [강한 sub-pattern (PF ranked, n>=10)]")
for p in patterns[:5]:
    cat, h1, side, n, pf, pnl = p
    print(f"    T2={cat:<8} h1={h1:<15} {side:<6} n={n:>3} PF={pf:>6.2f} pnl=${pnl:>+12,.0f}")
print(f"\n  [약한 sub-pattern (PF ranked, n>=10)]")
for p in patterns[-5:]:
    cat, h1, side, n, pf, pnl = p
    print(f"    T2={cat:<8} h1={h1:<15} {side:<6} n={n:>3} PF={pf:>6.2f} pnl=${pnl:>+12,.0f}")

# 분기별 일관성 — sub-pattern별
banner("[F] 정밀 sub-pattern 분기별 일관성 (n>=10)", "=")
baseline_pf = fmt_pf(t)
quarters = sorted(t["quarter"].dropna().unique().tolist())
print(f"\n  baseline PF: {baseline_pf:.3f}")
print(f"  {'sub-pattern':<55} {'우세':>5} {'열세':>5} {'일관성':>9}")
for p in patterns:
    cat, h1, side, n, pf, pnl = p
    if n < 30: continue  # 일관성 측정용으로 표본 크게
    mask = (t["T2"]==cat) & (t["h1"]==h1) & (t["side"]==side)
    sub_q = t[mask]
    n_b = 0; n_w = 0; n_v = 0
    for q in quarters:
        sq = sub_q[sub_q["quarter"]==q]
        aq = t[t["quarter"]==q]
        if len(sq) < 3 or len(aq) < 30: continue
        n_v += 1
        pf_sq = fmt_pf(sq); pf_aq = fmt_pf(aq)
        if pf_sq > pf_aq * 1.15: n_b += 1
        elif pf_sq < pf_aq * 0.85: n_w += 1
    cons = n_b / max(n_v, 1) * 100
    name = f"T2={cat} h1={h1} {side} (n={n}, PF {pf:.2f})"
    print(f"  {name:<55} {n_b:>5} {n_w:>5} {cons:>8.1f}% [{n_v} 분기]")
