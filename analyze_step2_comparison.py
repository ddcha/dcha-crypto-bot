"""
Step 2 1차 처방 효과 검증 — baseline vs step2 비교

Baseline: stage4l_redist_outputs_step1_v2_baseline/  (Step 1 v2, 처방 적용 전)
Step2:    stage4l_redist_outputs/                    (PD-aware + Reverse exit + Fresh CHoCH)

검증 항목:
  C1) 시나리오 overall 비교 (PF/MDD/Return/Win%/Retirement)
  C2) 처방별 적용 trade 분포 (pd_aware/fresh_choch/reverse_exit)
  C3) Tier별 변화
  C4) MDD 구간 변화 (12월 손실이 줄었나?)
  C5) 처방별 ablation 추정 (적용 trade vs 미적용 trade)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

BASELINE = Path("stage4l_redist_outputs_step1_v2_baseline")
STEP2    = Path("stage4l_redist_outputs")
SCEN     = ["boost15", "boost25", "boost35"]

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch * 95); print(s); print(ch * 95)

# =========================================================
# C1: 시나리오 overall 비교
# =========================================================
banner("C1: 시나리오 overall 성과 비교 (baseline → step2)")

print(f"\n{'scenario':<10} {'metric':<12} {'baseline':>14} {'step2':>14} {'change':>14}")
print("-" * 70)
for sc in SCEN:
    base_df = pd.read_csv(BASELINE / f"stage4l_{sc}_out_skip_overall_summary.csv")
    s2_df   = pd.read_csv(STEP2    / f"stage4l_{sc}_out_skip_overall_summary.csv")
    b = base_df.iloc[0]
    s = s2_df.iloc[0]
    metrics = [
        ("trades",       "trades",       0),
        ("win%",         "win%",         2),
        ("PF",           "PF",           3),
        ("avg_R",        "avg_R",        3),
        ("MDD%",         "MDD%",         2),
        ("Return_%",     "Return_%",     1),
        ("ret_months",   "retirement_months", 0),
    ]
    for label, col, prec in metrics:
        bv = b.get(col, "")
        sv = s.get(col, "")
        try:
            bvf = float(bv); svf = float(sv)
            chg = svf - bvf
            chg_str = f"{chg:+.{prec}f}" if isinstance(chg, float) else str(chg)
            bv_str = f"{bvf:.{prec}f}" if isinstance(bvf, float) else str(bvf)
            sv_str = f"{svf:.{prec}f}" if isinstance(svf, float) else str(svf)
        except Exception:
            bv_str = str(bv)
            sv_str = str(sv)
            chg_str = f"{bv}→{sv}"
        print(f"{sc:<10} {label:<12} {bv_str:>14} {sv_str:>14} {chg_str:>14}")
    print()

# =========================================================
# C2: 처방별 적용 trade 분포 (BOOST25 기준)
# =========================================================
banner("C2: Step 2 처방별 적용 trade 분포 (BOOST25)")

t = pd.read_csv(STEP2 / "stage4l_boost25_out_skip_trades.csv")
n_total = len(t)
print(f"\n전체 {n_total} trades")

print("\n[A] PD-aware filter (discount SHORT risk × 0.5)")
n_pd = (t["pd_aware_mult"] == 0.5).sum() if "pd_aware_mult" in t.columns else 0
print(f"  적용된 trade: {n_pd} ({n_pd/n_total*100:.1f}%)")

print("\n[B] Reverse exit (8h cutoff)")
n_rev = (t["exit_reason"] == "reverse_choch_8h").sum()
print(f"  적용된 trade: {n_rev} ({n_rev/n_total*100:.1f}%)")
if n_rev > 0:
    rev_df = t[t["exit_reason"] == "reverse_choch_8h"]
    print(f"  reverse_exit trade 평균 r_multiple: {rev_df['r_multiple'].mean():+.3f}")
    print(f"  reverse_exit trade 총 net_pnl: ${rev_df['net_pnl'].sum():+,.0f}")
    print(f"  reverse_exit win%: {(rev_df['net_pnl']>0).mean()*100:.1f}%")
    print(f"  hold_bars 분포: mean={rev_df['hold_bars'].mean():.1f}, median={rev_df['hold_bars'].median():.1f}")

print("\n[C] Fresh CHoCH risk (trend_age < 24h, risk × 0.5)")
n_fresh = (t["fresh_choch_mult"] == 0.5).sum() if "fresh_choch_mult" in t.columns else 0
print(f"  적용된 trade: {n_fresh} ({n_fresh/n_total*100:.1f}%)")

# 중복 (둘 이상 처방 같이 적용)
both_pd_fresh = ((t["pd_aware_mult"] == 0.5) & (t["fresh_choch_mult"] == 0.5)).sum() if "pd_aware_mult" in t.columns else 0
print(f"\n  PD + Fresh 동시 적용: {both_pd_fresh}")

# =========================================================
# C3: Tier별 변화 (BOOST25)
# =========================================================
banner("C3: Tier별 baseline → step2 변화 (BOOST25)")

base_t = pd.read_csv(BASELINE / "stage4l_boost25_out_skip_trades.csv")
s2_t   = pd.read_csv(STEP2    / "stage4l_boost25_out_skip_trades.csv")

print(f"\n{'tier':<18} {'b_n':>5} {'b_PF':>7} {'b_pnl':>12} {'s_n':>5} {'s_PF':>7} {'s_pnl':>12} {'pf_chg':>8}")
tier_order = ["ALPHA_MAX","ALPHA_HIGH","ALPHA_MED","SWEEP_GEM","SWEEP_ROOM_FVG","SWEEP_ROOM_ONLY"]
for tier in tier_order:
    b_sub = base_t[base_t["tier_4e"] == tier]
    s_sub = s2_t[s2_t["tier_4e"] == tier]
    b_pf = fmt_pf(b_sub)
    s_pf = fmt_pf(s_sub)
    pf_chg = s_pf - b_pf
    print(f"{tier:<18} {len(b_sub):>5} {b_pf:>7.2f} {b_sub['net_pnl'].sum():>+12,.0f} "
          f"{len(s_sub):>5} {s_pf:>7.2f} {s_sub['net_pnl'].sum():>+12,.0f} {pf_chg:>+8.2f}")

# =========================================================
# C4: MDD 구간 변화
# =========================================================
banner("C4: MDD 시기 비교 (12월 손실 줄었나?)")

for sc in ["boost15", "boost25", "boost35"]:
    print(f"\n[{sc.upper()}]")
    for label, p in [("baseline", BASELINE), ("step2", STEP2)]:
        eq = pd.read_csv(p / f"stage4l_{sc}_out_skip_equity.csv")
        eq["time"] = pd.to_datetime(eq["time"], utc=True)
        # Dollar 기준 MDD
        eq["dd_dollar"] = eq["total_assets"] - eq["cummax"]
        idx = eq["dd_dollar"].idxmin()
        peak_eq = eq.loc[idx, "cummax"]
        trough_t = eq.loc[idx, "time"]
        pre = eq.loc[:idx]
        peak_idx = pre[pre["total_assets"] >= peak_eq * 0.999].index[-1]
        peak_t = eq.loc[peak_idx, "time"]
        mdd_dollar = eq.loc[idx, "dd_dollar"]
        mdd_pct = eq.loc[idx, "dd_pct"]
        days = (trough_t - peak_t).days
        print(f"  {label:<10} MDD${mdd_dollar:>+12,.0f}  MDD%{mdd_pct:>7.2f}%  peak={peak_t.date()}  trough={trough_t.date()} ({days}d)")

# =========================================================
# C5: 처방별 ablation 추정 (BOOST25)
# =========================================================
banner("C5: 처방별 ablation — 적용 trade vs 미적용 trade 비교 (BOOST25)")

print("\n[A] PD-aware (discount SHORT)")
if "pd_aware_mult" in s2_t.columns:
    pd_applied = s2_t[s2_t["pd_aware_mult"] == 0.5]
    pd_not = s2_t[(s2_t["pd_aware_mult"] != 0.5) & (s2_t["entry_pd_loc"] == "discount") & (s2_t["side"] == "short")]
    pd_norm_short = s2_t[(s2_t["entry_pd_loc"] == "premium") & (s2_t["side"] == "short")]
    print(f"  적용 (discount SHORT, mult 0.5): n={len(pd_applied)}, PF={fmt_pf(pd_applied):.2f}, pnl=${pd_applied['net_pnl'].sum():+,.0f}")
    print(f"  baseline 비교 (discount SHORT, mult 1.0):")
    pd_base = base_t[(base_t["entry_pd_loc"] == "discount") & (base_t["side"] == "short")] if "entry_pd_loc" in base_t.columns else pd.DataFrame()
    if len(pd_base) > 0:
        print(f"    baseline: n={len(pd_base)}, PF={fmt_pf(pd_base):.2f}, pnl=${pd_base['net_pnl'].sum():+,.0f}")
    print(f"  premium SHORT (대조군): n={len(pd_norm_short)}, PF={fmt_pf(pd_norm_short):.2f}, pnl=${pd_norm_short['net_pnl'].sum():+,.0f}")

print("\n[B] Reverse exit (8h cutoff)")
rev_df = s2_t[s2_t["exit_reason"] == "reverse_choch_8h"]
print(f"  적용 trade: n={len(rev_df)}, PF={fmt_pf(rev_df):.2f}, pnl=${rev_df['net_pnl'].sum():+,.0f}")
if len(rev_df) > 0:
    print(f"  reverse_exit win%: {(rev_df['net_pnl']>0).mean()*100:.1f}%")
    print(f"  reverse_exit avg_R: {rev_df['r_multiple'].mean():+.3f}")
    # baseline에서 같은 trade들 (entry_time 매칭)이 어떻게 끝났을지 비교는 어려움
    # 대신 baseline의 stop loss 결과 평균과 비교
    stops_b = base_t[base_t["exit_reason"] == "stop"]
    print(f"\n  [baseline] 모든 stop trade: n={len(stops_b)}, avg_R={stops_b['r_multiple'].mean():+.3f}, total=${stops_b['net_pnl'].sum():+,.0f}")
    stops_s = s2_t[s2_t["exit_reason"] == "stop"]
    print(f"  [step2]    모든 stop trade: n={len(stops_s)}, avg_R={stops_s['r_multiple'].mean():+.3f}, total=${stops_s['net_pnl'].sum():+,.0f}")
    print(f"  → step2에서 stop trade 수 {len(stops_b)-len(stops_s)} 감소 (reverse_exit으로 끊김)")

print("\n[C] Fresh CHoCH (trend_age < 24h)")
if "fresh_choch_mult" in s2_t.columns:
    fresh_applied = s2_t[s2_t["fresh_choch_mult"] == 0.5]
    print(f"  적용 trade: n={len(fresh_applied)}, PF={fmt_pf(fresh_applied):.2f}, pnl=${fresh_applied['net_pnl'].sum():+,.0f}")
    fresh_base = base_t[base_t["trend_age_bars"] < 24.0] if "trend_age_bars" in base_t.columns else pd.DataFrame()
    if len(fresh_base) > 0:
        print(f"  baseline 비교 (trend_age < 24h, mult 1.0): n={len(fresh_base)}, PF={fmt_pf(fresh_base):.2f}, pnl=${fresh_base['net_pnl'].sum():+,.0f}")

# =========================================================
# 종합 결론
# =========================================================
banner("종합 — 처방 효과 평가")

base_summary = pd.read_csv(BASELINE / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
s2_summary   = pd.read_csv(STEP2    / "stage4l_boost25_out_skip_overall_summary.csv").iloc[0]
print(f"\nBOOST25:")
print(f"  PF      : {base_summary['PF']:.3f} → {s2_summary['PF']:.3f} ({s2_summary['PF']-base_summary['PF']:+.3f})")
print(f"  MDD%    : {base_summary['MDD%']:.2f}% → {s2_summary['MDD%']:.2f}% ({s2_summary['MDD%']-base_summary['MDD%']:+.2f}%)")
print(f"  Return% : {base_summary['Return_%']:.1f}% → {s2_summary['Return_%']:.1f}% ({s2_summary['Return_%']-base_summary['Return_%']:+.1f}%)")
print(f"  Win%    : {base_summary['win%']:.2f}% → {s2_summary['win%']:.2f}% ({s2_summary['win%']-base_summary['win%']:+.2f}%)")
