"""
옵션 A+B 효과 — 3 시나리오 모두 자세히
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
from pathlib import Path

BASE = Path("stage4l_redist_outputs_wave_baseline")
OPTA = Path("stage4l_redist_outputs_optionA")
OPTAB = Path("stage4l_redist_outputs")

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*95); print(s); print(ch*95)

for SCEN in ["boost15", "boost25", "boost35"]:
    banner(f"@@@ {SCEN.upper()} @@@", "#")

    t = pd.read_csv(OPTAB / f"stage4l_{SCEN}_out_skip_trades.csv")
    n = len(t)
    print(f"\n전체 {n} trades / win {(t['net_pnl']>0).mean()*100:.2f}% / PF {fmt_pf(t):.3f}")

    # 처방별 적용
    print("\n[처방별 적용 분포]")
    for col in ["pd_aware_mult", "weak_setup_mult", "wave_pattern_mult"]:
        if col not in t.columns:
            continue
        applied = t[t[col] != 1.0]
        n_a = len(applied)
        if n_a == 0:
            continue
        print(f"  {col:<20} 적용 {n_a:>4} ({n_a/n*100:>5.1f}%) "
              f"win%={(applied['net_pnl']>0).mean()*100:>5.2f}% "
              f"PF={fmt_pf(applied):>5.2f} pnl=${applied['net_pnl'].sum():>+12,.0f}")

    # combined mult bin
    t["combined_mult"] = t.get("pd_aware_mult",1.0) * t.get("weak_setup_mult",1.0) * t.get("wave_pattern_mult",1.0)
    print("\n[combined mult bin별 성과]")
    print(f"  {'bin':<13} {'n':>5} {'%':>6} {'win%':>7} {'PF':>7} {'pnl':>13}")
    for lo, hi in [(0,0.30),(0.30,0.50),(0.50,0.80),(0.80,1.05),(1.05,1.50),(1.50,3.0)]:
        sub = t[(t["combined_mult"] >= lo) & (t["combined_mult"] < hi)]
        if len(sub) == 0: continue
        print(f"  {f'{lo:.2f}~{hi:.2f}':<13} {len(sub):>5} {len(sub)/n*100:>5.1f}% "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+13,.0f}")

    # Tier 비교
    b_t = pd.read_csv(BASE / f"stage4l_{SCEN}_out_skip_trades.csv")
    a_t = pd.read_csv(OPTA / f"stage4l_{SCEN}_out_skip_trades.csv")
    print("\n[Tier 진화: baseline → A → A+B]")
    print(f"  {'tier':<18} {'b_PF':>5} {'b_pnl':>8}  {'a_PF':>5} {'a_pnl':>8}  {'ab_PF':>5} {'ab_pnl':>8}")
    for tier in ["ALPHA_MAX","ALPHA_HIGH","ALPHA_MED","SWEEP_GEM","SWEEP_ROOM_FVG","SWEEP_ROOM_ONLY"]:
        bs  = b_t [b_t ["tier_4e"]==tier]
        as_ = a_t [a_t ["tier_4e"]==tier]
        abs_= t   [t   ["tier_4e"]==tier]
        print(f"  {tier:<18} {fmt_pf(bs):>5.2f} ${bs['net_pnl'].sum()/1000:>6.0f}k  "
              f"{fmt_pf(as_):>5.2f} ${as_['net_pnl'].sum()/1000:>6.0f}k  "
              f"{fmt_pf(abs_):>5.2f} ${abs_['net_pnl'].sum()/1000:>6.0f}k")

    # 시나리오 overall (요약)
    b = pd.read_csv(BASE  / f"stage4l_{SCEN}_out_skip_overall_summary.csv").iloc[0]
    a = pd.read_csv(OPTA  / f"stage4l_{SCEN}_out_skip_overall_summary.csv").iloc[0]
    ab= pd.read_csv(OPTAB / f"stage4l_{SCEN}_out_skip_overall_summary.csv").iloc[0]
    print(f"\n[Overall 요약]")
    print(f"  PF      : {b['PF']:.3f} → {a['PF']:.3f} → {ab['PF']:.3f}  (총 {ab['PF']-b['PF']:+.3f})")
    print(f"  MDD%    : {b['MDD%']:.2f}% → {a['MDD%']:.2f}% → {ab['MDD%']:.2f}%")
    print(f"  Return% : {b['Return_%']:.0f}% → {a['Return_%']:.0f}% → {ab['Return_%']:.0f}%")
