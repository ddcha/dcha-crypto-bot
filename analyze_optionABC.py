"""
옵션 A+B+C 효과 검증 — 3-way 비교

baseline:  Step 3 처방 없음 (wave_baseline)
AB:        A (weak setup blacklist) + B (wave pattern rules) — mult02
ABC:       AB + 신규 C 2개 (weak_T2_h1expansion, strong_T2aligned_h1comp_short)
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
AB   = Path("stage4l_redist_outputs_AB_mult02")
ABC  = Path("stage4l_redist_outputs")
SCEN = ["boost15", "boost25", "boost35"]

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*100); print(s); print(ch*100)

def calc_mdd_dollar(eq):
    eq = eq.copy()
    eq["dd_dollar"] = eq["total_assets"] - eq["cummax"]
    return float(eq["dd_dollar"].min())

# C1: 시나리오 메트릭 3-way
banner("[C1] 시나리오 메트릭 3-way 비교", "=")
for sc in SCEN:
    print(f"\n[BOOST{sc[5:]}]")
    print(f"  {'단계':<10} {'PF':>6} {'Win%':>6} {'MDD%':>6} {'MDD$':>14} "
          f"{'Return%':>10} {'total_end$':>14} {'retire_m':>9}")
    print("  " + "-" * 90)
    for label, path in [("baseline", BASE), ("AB", AB), ("ABC", ABC)]:
        s = pd.read_csv(path / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        mdd_dollar = calc_mdd_dollar(eq)
        end_v = float(s["total_assets_end"])
        print(f"  {label:<10} {s['PF']:>6.3f} {s['win%']:>5.2f}% {s['MDD%']:>5.2f}% "
              f"${mdd_dollar:>+13,.0f} "
              f"{s['Return_%']:>9.0f}% {end_v:>14,.0f} {str(s['retirement_months']):>9}")

# C2: 옵션 C 처방 적용 분포 (BOOST25 ABC)
banner("[C2] 옵션 C 처방 적용 trade 분포 (BOOST25)", "=")
abc_t = pd.read_csv(ABC / "stage4l_boost25_out_skip_trades.csv")
abc_t["entry_time"] = pd.to_datetime(abc_t["entry_time"], utc=True)
abc_t["d1"] = abc_t["d1_wave_state"].astype(str)
abc_t["h4"] = abc_t["h4_wave_state"].astype(str)
abc_t["h1"] = abc_t["h1_wave_state"].astype(str)

# weak_T2_h1expansion 매칭
weak_C_mask = abc_t["h1"].eq("expansion") & (
    (abc_t["d1"].eq("impulse_up") & abc_t["h4"].eq("impulse_up")) |
    (abc_t["d1"].eq("impulse_down") & abc_t["h4"].eq("impulse_down"))
)
strong_C_mask = (abc_t["d1"].eq("impulse_down") & abc_t["h4"].eq("impulse_down") &
                 abc_t["h1"].eq("compression") & abc_t["side"].eq("short"))

print(f"\n[옵션 C WEAK] weak_T2_h1expansion (× 0.3)")
sub = abc_t[weak_C_mask]
print(f"  적용 trade: {len(sub)}")
print(f"  win%={(sub['net_pnl']>0).mean()*100:.2f}% PF={fmt_pf(sub):.2f} pnl=${sub['net_pnl'].sum():+,.0f}")

print(f"\n[옵션 C STRONG] strong_T2aligned_h1comp_short (× 1.5)")
sub = abc_t[strong_C_mask]
print(f"  적용 trade: {len(sub)}")
print(f"  win%={(sub['net_pnl']>0).mean()*100:.2f}% PF={fmt_pf(sub):.2f} pnl=${sub['net_pnl'].sum():+,.0f}")

# C3: 같은 trade들 baseline vs AB vs ABC
banner("[C3] 옵션 C 적용된 trade들 — baseline/AB/ABC 비교", "=")
base_t = pd.read_csv(BASE / "stage4l_boost25_out_skip_trades.csv")
ab_t = pd.read_csv(AB / "stage4l_boost25_out_skip_trades.csv")

print(f"\n[WEAK 패턴 trade: D1=H4 same impulse + H1=expansion, 양 side]")
for label, df in [("baseline", base_t), ("AB", ab_t), ("ABC", abc_t)]:
    df["d1_"] = df["d1_wave_state"].astype(str)
    df["h4_"] = df["h4_wave_state"].astype(str)
    df["h1_"] = df["h1_wave_state"].astype(str)
    mask = df["h1_"].eq("expansion") & (
        (df["d1_"].eq("impulse_up") & df["h4_"].eq("impulse_up")) |
        (df["d1_"].eq("impulse_down") & df["h4_"].eq("impulse_down"))
    )
    s = df[mask]
    print(f"  {label:<10} n={len(s):>3} PF={fmt_pf(s):>5.2f} pnl=${s['net_pnl'].sum():>+12,.0f}")

print(f"\n[STRONG 패턴 trade: D1=H4=impulse_down + H1=compression + SHORT]")
for label, df in [("baseline", base_t), ("AB", ab_t), ("ABC", abc_t)]:
    df["d1_"] = df["d1_wave_state"].astype(str)
    df["h4_"] = df["h4_wave_state"].astype(str)
    df["h1_"] = df["h1_wave_state"].astype(str)
    mask = (df["d1_"].eq("impulse_down") & df["h4_"].eq("impulse_down") &
            df["h1_"].eq("compression") & df["side"].eq("short"))
    s = df[mask]
    print(f"  {label:<10} n={len(s):>3} PF={fmt_pf(s):>5.2f} pnl=${s['net_pnl'].sum():>+12,.0f}")

# C4: combined mult 분포 변화
banner("[C4] combined mult 분포 비교 (BOOST25 AB vs ABC)", "=")
for label, df in [("AB", ab_t), ("ABC", abc_t)]:
    df["combined"] = df.get("pd_aware_mult", 1.0) * df.get("weak_setup_mult", 1.0) * df.get("wave_pattern_mult", 1.0)
    print(f"\n[{label}]")
    print(f"  {'bin':<13} {'n':>5} {'%':>6} {'win%':>7} {'PF':>7} {'pnl':>13}")
    for lo, hi in [(0,0.30),(0.30,0.50),(0.50,0.80),(0.80,1.05),(1.05,1.50),(1.50,3.0)]:
        sub = df[(df["combined"] >= lo) & (df["combined"] < hi)]
        if len(sub) == 0: continue
        print(f"  {f'{lo:.2f}~{hi:.2f}':<13} {len(sub):>5} {len(sub)/len(df)*100:>5.1f}% "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+13,.0f}")

# C5: 12월 손실 변화
banner("[C5] 12월 손실 구간 — 3-way", "=")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, path in [("baseline", BASE), ("AB", AB), ("ABC", ABC)]:
        df = pd.read_csv(path / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"]>="2025-12-15") & (df["entry_time"]<="2025-12-31")]
        print(f"  {label:<10} n={len(dec):>3} win%={(dec['net_pnl']>0).mean()*100:>5.1f}% "
              f"PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f}")

# C6: worst day 변화
banner("[C6] BOOST25 worst 5 days — 옵션 C로 어떤 날들 바뀌었나", "=")
for label, df in [("AB", ab_t), ("ABC", abc_t)]:
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["date"] = df["exit_time"].dt.date
    daily = df.groupby("date")["net_pnl"].sum().sort_values()
    worst = daily.head(5)
    print(f"\n  [{label}] worst 5 days")
    for d, v in worst.items():
        print(f"    {d}: ${v:+,.0f}")

# 종합
banner("[종합] BOOST25 진화", "=")
b = pd.read_csv(BASE / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
a = pd.read_csv(AB / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
c = pd.read_csv(ABC / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
print(f"\n  PF      : {b['PF']:.3f} → {a['PF']:.3f} → {c['PF']:.3f}  (총 {c['PF']-b['PF']:+.3f})")
print(f"  MDD%    : {b['MDD%']:.2f}% → {a['MDD%']:.2f}% → {c['MDD%']:.2f}%")
print(f"  Return% : {b['Return_%']:.0f}% → {a['Return_%']:.0f}% → {c['Return_%']:.0f}%")
print(f"  Win%    : {b['win%']:.2f}% → {a['win%']:.2f}% → {c['win%']:.2f}%")
