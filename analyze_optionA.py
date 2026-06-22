"""
옵션 A 효과 검증 — wave-aware baseline vs weak setup blacklist 적용

Baseline: stage4l_redist_outputs_wave_baseline/  (PD-aware + wave monitoring only)
OptionA:  stage4l_redist_outputs/                (+ weak setup blacklist risk × 0.3)
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
OPTA = Path("stage4l_redist_outputs")
SCEN = ["boost15", "boost25", "boost35"]

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch * 90); print(s); print(ch * 90)

# C1: Overall
banner("C1: 시나리오 overall (wave_baseline → optionA)")
print(f"\n{'scenario':<10} {'metric':<12} {'baseline':>14} {'optionA':>14} {'change':>14}")
print("-" * 70)
for sc in SCEN:
    b = pd.read_csv(BASE / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    s = pd.read_csv(OPTA / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    for label, col, prec in [
        ("trades","trades",0), ("win%","win%",2), ("PF","PF",3),
        ("avg_R","avg_R",3), ("MDD%","MDD%",2),
        ("Return%","Return_%",1), ("ret_m","retirement_months",0),
    ]:
        try:
            bv, sv = float(b[col]), float(s[col])
            chg = sv - bv
            print(f"{sc:<10} {label:<12} {bv:>14.{prec}f} {sv:>14.{prec}f} {chg:>+14.{prec}f}")
        except Exception:
            print(f"{sc:<10} {label:<12} {str(b[col]):>14} {str(s[col]):>14}")
    print()

# C2: weak_setup mult 적용 분포 (BOOST25)
banner("C2: weak_setup mult 적용 분포 (BOOST25)")
t = pd.read_csv(OPTA / "stage4l_boost25_out_skip_trades.csv")
n_total = len(t)
print(f"\n전체: {n_total}")
if "weak_setup_mult" in t.columns:
    n_weak = (t["weak_setup_mult"] == 0.3).sum()
    weak_t = t[t["weak_setup_mult"] == 0.3]
    print(f"  weak setup 적용 (mult 0.3): {n_weak} ({n_weak/n_total*100:.1f}%)")
    if n_weak > 0:
        print(f"  적용 trade win%: {(weak_t['net_pnl']>0).mean()*100:.2f}%")
        print(f"  적용 trade PF: {fmt_pf(weak_t):.2f}")
        print(f"  적용 trade pnl: ${weak_t['net_pnl'].sum():+,.0f}")

# C3: weak setup ablation — 같은 setup의 baseline vs optionA
banner("C3: weak setup 21개 ablation (baseline vs optionA)")
b_t = pd.read_csv(BASE / "stage4l_boost25_out_skip_trades.csv")

# baseline에서 같은 setup tuple 매칭
WEAK_SETUPS = [
    ("impulse_up", "impulse_down", "impulse_up", "short"),
    ("compression", "compression", "compression", "short"),
    ("impulse_down", "impulse_down", "expansion", "short"),
    ("impulse_down", "impulse_down", "impulse_down", "short"),
    ("expansion", "impulse_up", "impulse_down", "long"),
    ("impulse_up", "compression", "impulse_down", "long"),
    ("impulse_up", "impulse_up", "expansion", "short"),
    ("expansion", "impulse_up", "compression", "long"),
    ("impulse_up", "expansion", "compression", "short"),
    ("compression", "impulse_up", "impulse_down", "long"),
    ("expansion", "impulse_up", "impulse_up", "long"),
    ("compression", "impulse_down", "expansion", "short"),
    ("impulse_down", "impulse_down", "expansion", "long"),
    ("impulse_up", "compression", "expansion", "long"),
    ("impulse_down", "expansion", "impulse_up", "short"),
    ("impulse_down", "compression", "impulse_up", "short"),
    ("impulse_down", "impulse_down", "impulse_up", "long"),
    ("compression", "compression", "impulse_up", "long"),
    ("impulse_up", "expansion", "impulse_down", "long"),
    ("impulse_up", "impulse_up", "impulse_up", "long"),
    ("impulse_down", "impulse_up", "compression", "long"),
]

def is_weak(row):
    return (str(row["d1_wave_state"]), str(row["h4_wave_state"]),
            str(row["h1_wave_state"]), str(row["side"])) in {tuple(x) for x in WEAK_SETUPS}

b_t["is_weak"] = b_t.apply(is_weak, axis=1)
t["is_weak"]   = t.apply(is_weak, axis=1)

b_weak = b_t[b_t["is_weak"]]
o_weak = t[t["is_weak"]]
b_strong = b_t[~b_t["is_weak"]]
o_strong = t[~t["is_weak"]]

print(f"\n{'group':<25} {'n':>5} {'win%':>7} {'PF':>7} {'pnl':>14} {'avg_R':>8}")
print("-" * 70)
print(f"{'baseline weak (21 setups)':<25} {len(b_weak):>5} "
      f"{(b_weak['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(b_weak):>7.2f} "
      f"{b_weak['net_pnl'].sum():>+14,.0f} {b_weak['r_multiple'].mean():>+8.3f}")
print(f"{'optionA weak (mult 0.3)':<25} {len(o_weak):>5} "
      f"{(o_weak['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(o_weak):>7.2f} "
      f"{o_weak['net_pnl'].sum():>+14,.0f} {o_weak['r_multiple'].mean():>+8.3f}")
print()
print(f"{'baseline strong':<25} {len(b_strong):>5} "
      f"{(b_strong['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(b_strong):>7.2f} "
      f"{b_strong['net_pnl'].sum():>+14,.0f} {b_strong['r_multiple'].mean():>+8.3f}")
print(f"{'optionA strong (변경 X)':<25} {len(o_strong):>5} "
      f"{(o_strong['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(o_strong):>7.2f} "
      f"{o_strong['net_pnl'].sum():>+14,.0f} {o_strong['r_multiple'].mean():>+8.3f}")

# C4: Tier 변화
banner("C4: Tier별 baseline → optionA")
print(f"\n{'tier':<18} {'b_n':>5} {'b_PF':>7} {'b_pnl':>13} {'o_n':>5} {'o_PF':>7} {'o_pnl':>13}")
for tier in ["ALPHA_MAX","ALPHA_HIGH","ALPHA_MED","SWEEP_GEM","SWEEP_ROOM_FVG","SWEEP_ROOM_ONLY"]:
    bs = b_t[b_t["tier_4e"] == tier]
    os_ = t[t["tier_4e"] == tier]
    print(f"{tier:<18} {len(bs):>5} {fmt_pf(bs):>7.2f} {bs['net_pnl'].sum():>+13,.0f} "
          f"{len(os_):>5} {fmt_pf(os_):>7.2f} {os_['net_pnl'].sum():>+13,.0f}")

# C5: 12월 손실 구간
banner("C5: 12월 손실 구간 변화 (2025-12-15~31)")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, p in [("baseline", BASE), ("optionA", OPTA)]:
        df = pd.read_csv(p / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"] >= "2025-12-15") & (df["entry_time"] <= "2025-12-31")]
        n_loss = (dec["net_pnl"] < 0).sum()
        print(f"  {label:<10} n={len(dec):>3} win%={(dec['net_pnl']>0).mean()*100:>5.1f}% "
              f"PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f} loss_n={n_loss}")

# 종합
banner("종합 요약")
b25 = pd.read_csv(BASE / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
o25 = pd.read_csv(OPTA / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
print(f"\nBOOST25:")
print(f"  PF      : {b25['PF']:.3f} → {o25['PF']:.3f} ({o25['PF']-b25['PF']:+.3f})")
print(f"  MDD%    : {b25['MDD%']:.2f}% → {o25['MDD%']:.2f}% ({o25['MDD%']-b25['MDD%']:+.2f}%)")
print(f"  Return% : {b25['Return_%']:.1f}% → {o25['Return_%']:.1f}% ({o25['Return_%']-b25['Return_%']:+.1f}%)")
print(f"  Win%    : {b25['win%']:.2f}% → {o25['win%']:.2f}% ({o25['win%']-b25['win%']:+.2f}%)")
