"""
Retire 늦어짐 원인 분석
  baseline 8m (2024-01) → 처방 12m (2024-05) — 4개월 지연

  가설:
    H1) A blacklist (×0.3) + B WEAK가 자본 작은 초기에 risk 축소 → 자본 축적 속도 감소
    H2) 옵션 C는 retire에 영향 없음 (이미 자본 큰 후반에 효과)

  분석:
    1) Equity curve 비교 (첫 1년, 2023-2024)
    2) Retire target 도달 시점 정확히
    3) 초기 6개월 trade 분포 + 처방 적용된 trade 비율
    4) 처방으로 인해 자본 축적 늦어진 정확한 규모
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
SCEN = "boost25"

# retire target = 1000만원/월 × 3개월 평균 (코드의 RETIREMENT_MONTHLY_TARGET_KRW)
RETIRE_TARGET_KRW = 10_000_000  # 월 1000만원
KRW_PER_USDT = 1350.0

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*95); print(s); print(ch*95)

# A. Equity curve 첫 1년 비교
banner("[A] 첫 1년 (2023-07 ~ 2024-06) equity curve 비교", "=")

print(f"\n  {'date':<11} {'baseline$':>14} {'AB$':>14} {'ABC$':>14} {'AB-base':>12} {'ABC-base':>12}")
print("  " + "-" * 90)
eq_curves = {}
for label, path in [("baseline", BASE), ("AB", AB), ("ABC", ABC)]:
    eq = pd.read_csv(path / f"stage4l_{SCEN}_out_skip_equity.csv")
    eq["time"] = pd.to_datetime(eq["time"], utc=True)
    eq_curves[label] = eq

# 월별 마지막 자본
b_eq = eq_curves["baseline"].copy()
a_eq = eq_curves["AB"].copy()
c_eq = eq_curves["ABC"].copy()

b_eq["ym"] = b_eq["time"].dt.to_period("M")
a_eq["ym"] = a_eq["time"].dt.to_period("M")
c_eq["ym"] = c_eq["time"].dt.to_period("M")

b_monthly = b_eq.groupby("ym")["total_assets"].last()
a_monthly = a_eq.groupby("ym")["total_assets"].last()
c_monthly = c_eq.groupby("ym")["total_assets"].last()

# 첫 18개월 출력
for ym in b_monthly.index[:18]:
    b_v = b_monthly.get(ym, np.nan)
    a_v = a_monthly.get(ym, np.nan)
    c_v = c_monthly.get(ym, np.nan)
    diff_ab = a_v - b_v if pd.notna(b_v) and pd.notna(a_v) else 0
    diff_abc = c_v - b_v if pd.notna(b_v) and pd.notna(c_v) else 0
    print(f"  {str(ym):<11} {b_v:>14,.0f} {a_v:>14,.0f} {c_v:>14,.0f} {diff_ab:>+12,.0f} {diff_abc:>+12,.0f}")

# B. 월별 보고서로 retire target 도달 정확 시기
banner("[B] 월별 자본 + retire target 도달 시점", "=")
for label, path in [("baseline", BASE), ("AB", AB), ("ABC", ABC)]:
    monthly = pd.read_csv(path / f"stage4l_{SCEN}_out_skip_monthly.csv")
    qualified = monthly[monthly['rolling_3m_avg_krw'] >= RETIRE_TARGET_KRW]
    if len(qualified) > 0:
        first_q = qualified.iloc[0]
        idx = monthly[monthly['month'] == first_q['month']].index[0]
        print(f"\n[{label}]")
        print(f"  Retire target 첫 도달: {first_q['month']} (idx={idx+1}, 즉 {idx+1}번째 월)")
        print(f"  도달 시 rolling 3m avg: {first_q['rolling_3m_avg_krw']:,.0f} KRW")
        # 그 전 3개월
        for i in range(max(0, idx-3), idx+1):
            r = monthly.iloc[i]
            print(f"    {r['month']:<10} 월수익 ${r['net_pnl_usdt']:>10,.0f}  3m_avg_KRW {r['rolling_3m_avg_krw']:>15,.0f}")
    else:
        print(f"\n[{label}] retire target 미도달")

# C. 첫 1년 처방 적용 비율
banner("[C] 첫 1년 (2023-07~2024-06) 처방 적용 분포", "=")
for label, path in [("baseline", BASE), ("AB", AB), ("ABC", ABC)]:
    t = pd.read_csv(path / f"stage4l_{SCEN}_out_skip_trades.csv")
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    first_year = t[(t["entry_time"] >= "2023-07-01") & (t["entry_time"] < "2024-07-01")]
    n = len(first_year)
    print(f"\n[{label}] 첫 1년 trade: {n}")
    print(f"  net_pnl: ${first_year['net_pnl'].sum():+,.0f}")
    print(f"  PF: {fmt_pf(first_year):.2f}")
    if "weak_setup_mult" in first_year.columns:
        weak = (first_year["weak_setup_mult"] != 1.0).sum()
        wp = (first_year["wave_pattern_mult"] != 1.0).sum() if "wave_pattern_mult" in first_year.columns else 0
        pd_a = (first_year["pd_aware_mult"] != 1.0).sum() if "pd_aware_mult" in first_year.columns else 0
        print(f"  weak_setup 적용: {weak}/{n} ({weak/max(n,1)*100:.1f}%)")
        print(f"  wave_pattern 적용: {wp}/{n} ({wp/max(n,1)*100:.1f}%)")
        print(f"  pd_aware 적용: {pd_a}/{n} ({pd_a/max(n,1)*100:.1f}%)")
        # combined mult 평균
        first_year["comb"] = (first_year.get("pd_aware_mult", 1.0) *
                              first_year.get("weak_setup_mult", 1.0) *
                              first_year.get("wave_pattern_mult", 1.0))
        print(f"  combined mult 평균: {first_year['comb'].mean():.3f}")
        print(f"    mult > 1.0: {(first_year['comb'] > 1.0).sum()}건")
        print(f"    mult < 1.0: {(first_year['comb'] < 1.0).sum()}건")

# D. 첫 1년 처방 효과 — pnl 손해/이익 측정
banner("[D] 첫 1년 처방 효과 — 만약 처방 없었다면? (반사실 추정)", "=")
b_t = pd.read_csv(BASE / f"stage4l_{SCEN}_out_skip_trades.csv")
abc_t = pd.read_csv(ABC / f"stage4l_{SCEN}_out_skip_trades.csv")
b_t["entry_time"] = pd.to_datetime(b_t["entry_time"], utc=True)
abc_t["entry_time"] = pd.to_datetime(abc_t["entry_time"], utc=True)

b_y1 = b_t[(b_t["entry_time"] >= "2023-07-01") & (b_t["entry_time"] < "2024-07-01")]
c_y1 = abc_t[(abc_t["entry_time"] >= "2023-07-01") & (abc_t["entry_time"] < "2024-07-01")]
print(f"\n  baseline 첫 1년 net: ${b_y1['net_pnl'].sum():+,.0f}")
print(f"  ABC 첫 1년 net:      ${c_y1['net_pnl'].sum():+,.0f}")
print(f"  차이 (ABC - base):   ${c_y1['net_pnl'].sum() - b_y1['net_pnl'].sum():+,.0f}")
print(f"\n  → ABC가 첫 1년에 ${c_y1['net_pnl'].sum() - b_y1['net_pnl'].sum():+,.0f} 만큼 (자본 작아서 손해)")

# 옵션 C 단독 영향 검증 — AB vs ABC 첫 1년 차이
ab_t = pd.read_csv(AB / f"stage4l_{SCEN}_out_skip_trades.csv")
ab_t["entry_time"] = pd.to_datetime(ab_t["entry_time"], utc=True)
ab_y1 = ab_t[(ab_t["entry_time"] >= "2023-07-01") & (ab_t["entry_time"] < "2024-07-01")]
print(f"\n  [옵션 C 단독 영향]")
print(f"  AB  첫 1년 net: ${ab_y1['net_pnl'].sum():+,.0f}")
print(f"  ABC 첫 1년 net: ${c_y1['net_pnl'].sum():+,.0f}")
print(f"  ABC - AB:       ${c_y1['net_pnl'].sum() - ab_y1['net_pnl'].sum():+,.0f}")

# E. 첫 1년 손실 trade 비교 (처방으로 회피했어야 할 trade가 더 작아진 효과 측정)
banner("[E] 첫 1년 처방으로 손실 줄어든 정도", "=")
# 같은 trade들 — entry_time, symbol, side로 매칭
b_y1_indexed = b_y1.set_index(["entry_time", "symbol", "side"])["net_pnl"]
c_y1_indexed = c_y1.set_index(["entry_time", "symbol", "side"])["net_pnl"]
common = b_y1_indexed.index.intersection(c_y1_indexed.index)
print(f"\n  공통 trade: {len(common)} (baseline {len(b_y1)} vs ABC {len(c_y1)})")

# baseline에선 손실인 trade들이 ABC에서 얼마나 작아졌나
b_losses = b_y1_indexed[b_y1_indexed < 0]
c_for_b_losses = c_y1_indexed.reindex(b_losses.index).dropna()
print(f"  baseline 손실 trade: {len(b_losses)} 건, total ${b_losses.sum():+,.0f}")
matched = b_losses.reindex(c_for_b_losses.index)
print(f"  같은 trade가 ABC에서: total ${c_for_b_losses.sum():+,.0f}")
print(f"  → 손실 감소 효과: ${c_for_b_losses.sum() - matched.sum():+,.0f}")

# baseline에서 이익이었지만 ABC에서 작아진 trade
b_wins = b_y1_indexed[b_y1_indexed > 0]
c_for_b_wins = c_y1_indexed.reindex(b_wins.index).dropna()
matched_w = b_wins.reindex(c_for_b_wins.index)
print(f"\n  baseline 이익 trade: {len(b_wins)} 건, total ${b_wins.sum():+,.0f}")
print(f"  같은 trade가 ABC에서: total ${c_for_b_wins.sum():+,.0f}")
print(f"  → 이익 감소 (처방 risk 축소 부작용): ${c_for_b_wins.sum() - matched_w.sum():+,.0f}")
