"""
옵션 A+B 결합 효과 검증 — 3-way 비교

  baseline:  stage4l_redist_outputs_wave_baseline/  (Step 3 처방 없음)
  optionA:   stage4l_redist_outputs_optionA/        (weak setup blacklist)
  optionAB:  stage4l_redist_outputs/                (A + 일반 패턴 규칙)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("stage4l_redist_outputs_wave_baseline")
OPTA = Path("stage4l_redist_outputs_optionA")
OPTAB = Path("stage4l_redist_outputs")
SCEN = ["boost15", "boost25", "boost35"]

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*95); print(s); print(ch*95)

# C1: 3-way overall
banner("C1: 3-way 시나리오 overall 비교")
print(f"\n{'scenario':<10} {'metric':<12} {'baseline':>14} {'optionA':>14} {'optionAB':>14} {'AB-base':>12}")
print("-" * 80)
for sc in SCEN:
    b = pd.read_csv(BASE  / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    a = pd.read_csv(OPTA  / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    ab= pd.read_csv(OPTAB / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    for label, col, prec in [
        ("trades","trades",0), ("win%","win%",2), ("PF","PF",3),
        ("MDD%","MDD%",2), ("Return%","Return_%",1), ("ret_m","retirement_months",0),
    ]:
        try:
            bv,av,abv = float(b[col]), float(a[col]), float(ab[col])
            chg = abv - bv
            print(f"{sc:<10} {label:<12} {bv:>14.{prec}f} {av:>14.{prec}f} {abv:>14.{prec}f} {chg:>+12.{prec}f}")
        except Exception:
            pass
    print()

# C2: 처방 적용 분포 (BOOST25 OPTAB)
banner("C2: 처방 적용 분포 (BOOST25 optionAB)")
t = pd.read_csv(OPTAB / "stage4l_boost25_out_skip_trades.csv")
n = len(t)
print(f"\n전체: {n}")
for col in ["pd_aware_mult", "weak_setup_mult", "wave_pattern_mult"]:
    if col in t.columns:
        # 1.0 이 아닌 (처방 적용된) trade
        applied = t[t[col] != 1.0]
        n_a = len(applied)
        print(f"\n  [{col}] 적용: {n_a} ({n_a/n*100:.1f}%)")
        if n_a > 0:
            print(f"    값 분포: {applied[col].value_counts().to_dict()}")
            print(f"    적용 trade win%: {(applied['net_pnl']>0).mean()*100:.2f}%")
            print(f"    적용 trade PF: {fmt_pf(applied):.2f}")
            print(f"    적용 trade pnl: ${applied['net_pnl'].sum():+,.0f}")

# C3: optionAB ablation — 처방 적용 그룹 vs 미적용 그룹
banner("C3: optionAB ablation — 어느 trade에 처방이 가장 강하게 적용됐나")
# combined mult 계산
t["combined_mult"] = t.get("pd_aware_mult",1.0) * t.get("weak_setup_mult",1.0) * t.get("wave_pattern_mult",1.0)
print(f"\n  [combined mult 분포]")
print(f"  {'mult bin':<15} {'n':>5} {'%':>6} {'win%':>7} {'PF':>7} {'pnl':>14}")
bins = [(0, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.05), (1.05, 1.5), (1.5, 3.0)]
for lo, hi in bins:
    sub = t[(t["combined_mult"] >= lo) & (t["combined_mult"] < hi)]
    if len(sub) == 0: continue
    print(f"  {f'{lo:.2f}~{hi:.2f}':<15} {len(sub):>5} {len(sub)/n*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+14,.0f}")

# C4: 12월 손실 비교
banner("C4: 12월 손실 구간 (2025-12-15~31) — 3-way")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, p in [("baseline", BASE), ("optionA", OPTA), ("optionAB", OPTAB)]:
        df = pd.read_csv(p / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"] >= "2025-12-15") & (df["entry_time"] <= "2025-12-31")]
        print(f"  {label:<12} n={len(dec):>3} win%={(dec['net_pnl']>0).mean()*100:>5.1f}% "
              f"PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f}")

# C5: Tier별 비교 (BOOST25)
banner("C5: Tier별 비교 (BOOST25)")
b_t = pd.read_csv(BASE / "stage4l_boost25_out_skip_trades.csv")
a_t = pd.read_csv(OPTA / "stage4l_boost25_out_skip_trades.csv")
ab_t = t  # optionAB
print(f"\n{'tier':<18} {'baseline':>12} {'optionA':>12} {'optionAB':>12}")
print(f"{'':<18} {'PF':>5}{'pnl':>7}    {'PF':>5}{'pnl':>7}    {'PF':>5}{'pnl':>7}")
for tier in ["ALPHA_MAX","ALPHA_HIGH","ALPHA_MED","SWEEP_GEM","SWEEP_ROOM_FVG","SWEEP_ROOM_ONLY"]:
    bs  = b_t [b_t ["tier_4e"]==tier]
    as_ = a_t [a_t ["tier_4e"]==tier]
    abs_= ab_t[ab_t["tier_4e"]==tier]
    print(f"{tier:<18} {fmt_pf(bs):>5.2f} ${bs['net_pnl'].sum()/1000:>5.0f}k    "
          f"{fmt_pf(as_):>5.2f} ${as_['net_pnl'].sum()/1000:>5.0f}k    "
          f"{fmt_pf(abs_):>5.2f} ${abs_['net_pnl'].sum()/1000:>5.0f}k")

# 종합
banner("종합")
b25 = pd.read_csv(BASE  / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
a25 = pd.read_csv(OPTA  / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
ab25= pd.read_csv(OPTAB / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
print(f"\nBOOST25 진화 (baseline → A → A+B):")
print(f"  PF      : {b25['PF']:.3f} → {a25['PF']:.3f} → {ab25['PF']:.3f} (총 {ab25['PF']-b25['PF']:+.3f})")
print(f"  MDD%    : {b25['MDD%']:.2f}% → {a25['MDD%']:.2f}% → {ab25['MDD%']:.2f}%")
print(f"  Return% : {b25['Return_%']:.0f}% → {a25['Return_%']:.0f}% → {ab25['Return_%']:.0f}%")
print(f"  Win%    : {b25['win%']:.2f}% → {a25['win%']:.2f}% → {ab25['win%']:.2f}%")
