"""
옵션 1 (Balance-aware WEAK skip) 효과 검증
  비교:
    baseline: wave_baseline
    ABC: 모든 처방 (자본 작은 시기에도 적용)
    BA: balance-aware (자본 < $50k시 WEAK 비활성, STRONG만 활성)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
from pathlib import Path

BASE = Path("stage4l_redist_outputs_wave_baseline")
ABC  = Path("stage4l_redist_outputs_optionABC")
BA   = Path("stage4l_redist_outputs")
SCEN = ["boost15", "boost25", "boost35"]
RETIRE_TARGET_KRW = 10_000_000

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

# A: 시나리오 메트릭 3-way
banner("[A] 3-way 시나리오 메트릭 (baseline / ABC / BA)", "=")
for sc in SCEN:
    print(f"\n[BOOST{sc[5:]}]")
    print(f"  {'단계':<10} {'PF':>6} {'MDD%':>6} {'MDD$':>14} {'Return%':>10} {'total_end$':>14} {'retire_m':>9} {'retire':>12}")
    print("  " + "-" * 100)
    for label, path in [("baseline", BASE), ("ABC", ABC), ("BA", BA)]:
        s = pd.read_csv(path / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        mdd_dollar = calc_mdd_dollar(eq)
        end_v = float(s["total_assets_end"])
        print(f"  {label:<10} {s['PF']:>6.3f} {s['MDD%']:>5.2f}% "
              f"${mdd_dollar:>+13,.0f} {s['Return_%']:>9.0f}% {end_v:>14,.0f} "
              f"{str(s['retirement_months']):>9} {str(s['retirement']):>12}")

# B: 첫 1년 자본 비교
banner("[B] 첫 1년 (2023-07~2024-06) 자본 비교 (BOOST25)", "=")
print(f"\n  {'date':<11} {'baseline$':>14} {'ABC$':>14} {'BA$':>14} {'BA-base':>12} {'BA-ABC':>12}")
print("  " + "-" * 90)
b_eq = pd.read_csv(BASE / "stage4l_boost25_out_skip_equity.csv")
c_eq = pd.read_csv(ABC / "stage4l_boost25_out_skip_equity.csv")
a_eq = pd.read_csv(BA / "stage4l_boost25_out_skip_equity.csv")
b_eq["time"] = pd.to_datetime(b_eq["time"], utc=True)
c_eq["time"] = pd.to_datetime(c_eq["time"], utc=True)
a_eq["time"] = pd.to_datetime(a_eq["time"], utc=True)
b_eq["ym"] = b_eq["time"].dt.to_period("M")
c_eq["ym"] = c_eq["time"].dt.to_period("M")
a_eq["ym"] = a_eq["time"].dt.to_period("M")
b_m = b_eq.groupby("ym")["total_assets"].last()
c_m = c_eq.groupby("ym")["total_assets"].last()
a_m = a_eq.groupby("ym")["total_assets"].last()
for ym in b_m.index[:18]:
    b_v = b_m.get(ym, 0); c_v = c_m.get(ym, 0); a_v = a_m.get(ym, 0)
    diff_a = a_v - b_v; diff_ac = a_v - c_v
    print(f"  {str(ym):<11} {b_v:>14,.0f} {c_v:>14,.0f} {a_v:>14,.0f} {diff_a:>+12,.0f} {diff_ac:>+12,.0f}")

# C: retire target 도달
banner("[C] Retire target 도달 시기 — 회복 확인", "=")
for sc in SCEN:
    print(f"\n[BOOST{sc[5:]}]")
    for label, path in [("baseline", BASE), ("ABC", ABC), ("BA", BA)]:
        monthly = pd.read_csv(path / f"stage4l_{sc}_out_skip_monthly.csv")
        qualified = monthly[monthly['rolling_3m_avg_krw'] >= RETIRE_TARGET_KRW]
        if len(qualified) > 0:
            first_q = qualified.iloc[0]
            idx = monthly[monthly['month'] == first_q['month']].index[0]
            print(f"  {label:<10} {first_q['month']} ({idx+1}m, rolling={first_q['rolling_3m_avg_krw']:,.0f} KRW)")

# D: 첫 1년 처방 적용 비교
banner("[D] 첫 1년 처방 적용 (BOOST25)", "=")
for label, path in [("ABC", ABC), ("BA", BA)]:
    t = pd.read_csv(path / "stage4l_boost25_out_skip_trades.csv")
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    y1 = t[(t["entry_time"] >= "2023-07-01") & (t["entry_time"] < "2024-07-01")]
    print(f"\n[{label}] 첫 1년 trade: {len(y1)}, net=${y1['net_pnl'].sum():+,.0f}, PF={fmt_pf(y1):.2f}")
    weak = (y1["weak_setup_mult"] != 1.0).sum()
    wp = (y1["wave_pattern_mult"] != 1.0).sum()
    pd_a = (y1["pd_aware_mult"] != 1.0).sum()
    print(f"  weak_setup 적용: {weak}, wave_pattern 적용: {wp}, pd_aware 적용: {pd_a}")
    y1["comb"] = y1.get("pd_aware_mult", 1.0) * y1.get("weak_setup_mult", 1.0) * y1.get("wave_pattern_mult", 1.0)
    n_boost = (y1["comb"] > 1.0).sum()
    n_red = (y1["comb"] < 1.0).sum()
    print(f"  combined mult > 1.0 (boost): {n_boost}, < 1.0 (reduce): {n_red}")
    print(f"  combined mult 평균: {y1['comb'].mean():.3f}")

# E: 후반 (자본 큰 시기) 처방은 그대로 적용되는지 확인
banner("[E] 후반 (2025-2026) 처방 적용 — 정상 작동 확인", "=")
for label, path in [("ABC", ABC), ("BA", BA)]:
    t = pd.read_csv(path / "stage4l_boost25_out_skip_trades.csv")
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    late = t[t["entry_time"] >= "2025-01-01"]
    print(f"\n[{label}] 2025+ trade: {len(late)}, net=${late['net_pnl'].sum():+,.0f}, PF={fmt_pf(late):.2f}")
    weak = (late["weak_setup_mult"] != 1.0).sum()
    wp = (late["wave_pattern_mult"] != 1.0).sum()
    print(f"  weak_setup 적용: {weak}, wave_pattern 적용: {wp}")

# F: 12월 손실
banner("[F] 12월 손실 — 처방이 유지되는지", "=")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, path in [("baseline", BASE), ("ABC", ABC), ("BA", BA)]:
        df = pd.read_csv(path / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"]>="2025-12-15") & (df["entry_time"]<="2025-12-31")]
        print(f"  {label:<10} n={len(dec):>3} PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f}")

# G: 종합
banner("[G] BOOST25 진화 종합", "=")
b = pd.read_csv(BASE / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
c = pd.read_csv(ABC / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
a = pd.read_csv(BA / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
print(f"\n  PF      : {b['PF']:.3f} → {c['PF']:.3f} → {a['PF']:.3f}")
print(f"  MDD%    : {b['MDD%']:.2f}% → {c['MDD%']:.2f}% → {a['MDD%']:.2f}%")
print(f"  Return% : {b['Return_%']:.0f}% → {c['Return_%']:.0f}% → {a['Return_%']:.0f}%")
print(f"  retire  : {b['retirement_months']}m → {c['retirement_months']}m → {a['retirement_months']}m")
