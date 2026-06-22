"""
H1 bar-by-bar simulator vs 기존 H4 event-driven 비교

H4ref: stage4l_redist_outputs_BA_h4ref/  (H4 기반, 모든 처방 + balance-aware)
H1BBB: stage4l_redist_outputs/             (H1 bar-by-bar simulator, 동일 처방)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
from pathlib import Path

H4REF = Path("stage4l_redist_outputs_BA_h4ref")
H1BBB = Path("stage4l_redist_outputs")
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

# A: 시나리오 메트릭 비교
banner("[A] 시나리오 메트릭 — H4ref vs H1BBB", "=")
for sc in SCEN:
    print(f"\n[BOOST{sc[5:]}]")
    print(f"  {'단계':<10} {'PF':>6} {'Win%':>6} {'MDD%':>6} {'MDD$':>14} {'Return%':>10} "
          f"{'total_end$':>14} {'retire_m':>9}")
    print("  " + "-" * 100)
    for label, path in [("H4ref", H4REF), ("H1BBB", H1BBB)]:
        s = pd.read_csv(path / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        mdd_dollar = calc_mdd_dollar(eq)
        end_v = float(s["total_assets_end"])
        print(f"  {label:<10} {s['PF']:>6.3f} {s['win%']:>5.2f}% {s['MDD%']:>5.2f}% "
              f"${mdd_dollar:>+13,.0f} {s['Return_%']:>9.0f}% {end_v:>14,.0f} {str(s['retirement_months']):>9}")

# B: trade 수, hold_bars, exit_reason 비교
banner("[B] Trade 통계 비교 (BOOST15 — 최종 채택본)", "=")
h4_t = pd.read_csv(H4REF / "stage4l_boost15_out_skip_trades.csv")
h1_t = pd.read_csv(H1BBB / "stage4l_boost15_out_skip_trades.csv")

print(f"\n  Trade 수: H4ref {len(h4_t)} vs H1BBB {len(h1_t)}")
print(f"  win%:     H4ref {(h4_t['net_pnl']>0).mean()*100:.2f}% vs H1BBB {(h1_t['net_pnl']>0).mean()*100:.2f}%")
print(f"  PF:       H4ref {fmt_pf(h4_t):.2f} vs H1BBB {fmt_pf(h1_t):.2f}")
print(f"  net:      H4ref ${h4_t['net_pnl'].sum():+,.0f} vs H1BBB ${h1_t['net_pnl'].sum():+,.0f}")
print(f"\n  hold_bars 분포:")
print(f"    H4ref: mean={h4_t['hold_bars'].mean():.1f}, median={h4_t['hold_bars'].median():.1f}, max={h4_t['hold_bars'].max()}")
print(f"    H1BBB: mean={h1_t['hold_bars'].mean():.1f}, median={h1_t['hold_bars'].median():.1f}, max={h1_t['hold_bars'].max()}")
print(f"    (H1BBB가 약 4× 큼이 자연스러움 — H1 단위)")

print(f"\n  [exit_reason 분포]")
print(f"    H4ref:")
for r, n in h4_t["exit_reason"].value_counts().items():
    print(f"      {r:<25} {n:>4}")
print(f"    H1BBB:")
for r, n in h1_t["exit_reason"].value_counts().items():
    print(f"      {r:<25} {n:>4}")

# C: SL 정밀도 변화 (max_adverse_excursion_pct, sl_proximity_pct)
banner("[C] SL 정밀도 변화 — H1 wick으로 더 빨리 잡혔나?", "=")
for label, df in [("H4ref", h4_t), ("H1BBB", h1_t)]:
    losers = df[df["net_pnl"] < 0]
    print(f"\n[{label}] 손실 trade {len(losers)}건")
    if "sl_proximity_pct" in losers.columns and len(losers) > 0:
        print(f"  sl_proximity_pct: mean={losers['sl_proximity_pct'].mean():.1f}%, "
              f"median={losers['sl_proximity_pct'].median():.1f}%")
    if "max_adverse_excursion_pct" in losers.columns and len(losers) > 0:
        print(f"  MAE %: mean={losers['max_adverse_excursion_pct'].mean():.2f}%")
    if "r_multiple" in losers.columns and len(losers) > 0:
        print(f"  avg loss R: {losers['r_multiple'].mean():.3f}")

# D: 같은 trade 매칭 — entry_time/symbol/side로
banner("[D] 동일 trade 결과 차이 (matched)", "=")
h4_t["entry_time"] = pd.to_datetime(h4_t["entry_time"], utc=True)
h1_t["entry_time"] = pd.to_datetime(h1_t["entry_time"], utc=True)
h4_idx = h4_t.set_index(["entry_time", "symbol", "side"])
h1_idx = h1_t.set_index(["entry_time", "symbol", "side"])
common = h4_idx.index.intersection(h1_idx.index)
print(f"\n  공통 trade: {len(common)} (H4 {len(h4_t)} vs H1 {len(h1_t)})")

if len(common) > 0:
    h4_p = h4_idx.loc[common, "net_pnl"].sum()
    h1_p = h1_idx.loc[common, "net_pnl"].sum()
    print(f"  H4 net: ${h4_p:+,.0f}")
    print(f"  H1 net: ${h1_p:+,.0f}")
    print(f"  차이:   ${h1_p - h4_p:+,.0f}")

    # 결과 다르게 끝난 trade 수
    h4_pnl = h4_idx.loc[common, "net_pnl"]
    h1_pnl = h1_idx.loc[common, "net_pnl"]
    h4_win_h1_loss = ((h4_pnl > 0) & (h1_pnl < 0)).sum()
    h4_loss_h1_win = ((h4_pnl < 0) & (h1_pnl > 0)).sum()
    print(f"\n  결과 바뀐 trade:")
    print(f"    H4=win → H1=loss: {h4_win_h1_loss}건")
    print(f"    H4=loss → H1=win: {h4_loss_h1_win}건")

# E: 12월 손실
banner("[E] 12월 손실 — H1 정밀도 영향", "=")
for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, path in [("H4ref", H4REF), ("H1BBB", H1BBB)]:
        df = pd.read_csv(path / f"stage4l_{sc}_out_skip_trades.csv")
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        dec = df[(df["entry_time"]>="2025-12-15") & (df["entry_time"]<="2025-12-31")]
        print(f"  {label:<10} n={len(dec):>3} PF={fmt_pf(dec):>5.2f} pnl=${dec['net_pnl'].sum():>+12,.0f}")

# F: 종합
banner("[F] 종합 — BOOST15 진화", "=")
s_h4 = pd.read_csv(H4REF / "stage4l_boost15_out_skip_overall_summary.csv").iloc[0]
s_h1 = pd.read_csv(H1BBB / "stage4l_boost15_out_skip_overall_summary.csv").iloc[0]
print(f"\n  PF      : {s_h4['PF']:.3f} → {s_h1['PF']:.3f}")
print(f"  MDD%    : {s_h4['MDD%']:.2f}% → {s_h1['MDD%']:.2f}%")
print(f"  Return% : {s_h4['Return_%']:.0f}% → {s_h1['Return_%']:.0f}%")
print(f"  Win%    : {s_h4['win%']:.2f}% → {s_h1['win%']:.2f}%")
print(f"  retire  : {s_h4['retirement_months']}m → {s_h1['retirement_months']}m")
print(f"  total$  : {float(s_h4['total_assets_end']):,.0f} → {float(s_h1['total_assets_end']):,.0f}")
