"""
A fine-tuning — WEAK_SETUP_RISK_MULT sweep 비교
  baseline: wave-aware monitoring only (Step 3 처방 없음)
  mult02:   weak setup × 0.2 (더 강하게)
  mult03:   weak setup × 0.3 (현재)
  mult05:   weak setup × 0.5 (완화)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

PATHS = {
    "baseline": Path("stage4l_redist_outputs_wave_baseline"),
    "mult02":   Path("stage4l_redist_outputs_AB_mult02"),
    "mult03":   Path("stage4l_redist_outputs_AB_mult03"),
    "mult05":   Path("stage4l_redist_outputs_AB_mult05"),
}
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

# 4-way 메트릭 표 (시나리오별)
banner("[A] 4-way 비교 — 각 시나리오의 mult sweep", "█")

for sc in SCEN:
    banner(f"BOOST{sc[5:]}", "=")
    print(f"\n  {'mult':<10} {'PF':>6} {'Win%':>6} {'MDD%':>6} {'MDD$':>14} "
          f"{'Return%':>10} {'total_end$':>14} {'retire_m':>9}")
    print("  " + "-" * 90)
    for label, path in PATHS.items():
        s = pd.read_csv(path / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        mdd_dollar = calc_mdd_dollar(eq)
        end_v = float(s["total_assets_end"])
        print(f"  {label:<10} {s['PF']:>6.3f} {s['win%']:>5.2f}% {s['MDD%']:>5.2f}% "
              f"${mdd_dollar:>+13,.0f} "
              f"{s['Return_%']:>9.0f}% {end_v:>14,.0f} {str(s['retirement_months']):>9}")

# 12월 손실 회복 비교
banner("[B] 12월 regime 전환 시기 손실 비교 (4-way)", "=")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, path in PATHS.items():
        df = pd.read_csv(path / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"]>="2025-12-15") & (df["entry_time"]<="2025-12-31")]
        print(f"  {label:<10} n={len(dec):>3} win%={(dec['net_pnl']>0).mean()*100:>5.1f}% "
              f"PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f}")

# weak setup mult 적용 trade 효과 변화
banner("[C] weak_setup 적용 trade 자체의 변화 (BOOST25)", "=")
print(f"\n  {'mult':<10} {'n_applied':>10} {'win%':>7} {'PF':>7} {'pnl':>15}")
for label, path in PATHS.items():
    df = pd.read_csv(path / "stage4l_boost25_out_skip_trades.csv")
    if "weak_setup_mult" in df.columns:
        applied = df[df["weak_setup_mult"] != 1.0]
        print(f"  {label:<10} {len(applied):>10} "
              f"{(applied['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(applied):>7.2f} "
              f"${applied['net_pnl'].sum():>+14,.0f}")
    else:
        # baseline
        # WEAK_SETUPS 매칭으로 식별
        weak_keys = [
            ("impulse_up","impulse_down","impulse_up","short"),
            ("compression","compression","compression","short"),
            ("impulse_down","impulse_down","expansion","short"),
            ("impulse_down","impulse_down","impulse_down","short"),
            ("expansion","impulse_up","impulse_down","long"),
            ("impulse_up","compression","impulse_down","long"),
            ("impulse_up","impulse_up","expansion","short"),
            ("expansion","impulse_up","compression","long"),
            ("impulse_up","expansion","compression","short"),
            ("compression","impulse_up","impulse_down","long"),
            ("expansion","impulse_up","impulse_up","long"),
            ("compression","impulse_down","expansion","short"),
            ("impulse_down","impulse_down","expansion","long"),
            ("impulse_up","compression","expansion","long"),
            ("impulse_down","expansion","impulse_up","short"),
            ("impulse_down","compression","impulse_up","short"),
            ("impulse_down","impulse_down","impulse_up","long"),
            ("compression","compression","impulse_up","long"),
            ("impulse_up","expansion","impulse_down","long"),
            ("impulse_up","impulse_up","impulse_up","long"),
            ("impulse_down","impulse_up","compression","long"),
        ]
        weak_set = set(weak_keys)
        df["is_weak"] = df.apply(
            lambda r: (str(r["d1_wave_state"]),str(r["h4_wave_state"]),
                       str(r["h1_wave_state"]),str(r["side"])) in weak_set, axis=1)
        applied = df[df["is_weak"]]
        print(f"  {label:<10} {len(applied):>10} "
              f"{(applied['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(applied):>7.2f} "
              f"${applied['net_pnl'].sum():>+14,.0f}  [baseline 측정]")

# 종합 — sweet spot 식별
banner("[D] sweet spot 식별 (BOOST25 기준)", "=")
print(f"\n  {'mult':<10} {'PF':>6} {'MDD%':>7} {'Return%':>10} {'PF/|MDD|':>10} {'retire':>8}")
for label, path in PATHS.items():
    s = pd.read_csv(path / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
    pf_per_mdd = s["PF"] / abs(s["MDD%"])
    print(f"  {label:<10} {s['PF']:>6.3f} {s['MDD%']:>6.2f}% "
          f"{s['Return_%']:>9.0f}% {pf_per_mdd:>10.4f} {str(s['retirement_months']):>8}")
