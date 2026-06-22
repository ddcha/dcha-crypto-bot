"""
Step 1 모니터링 컬럼 분석 — 처방 우선순위 결정

검증 항목:
  Q1) Reverse CHoCH가 SL보다 먼저 발생한 비율 (사용자 의심: 이미 SL 맞지 않나?)
  Q2) D1 EMA state vs 진입 방향 정합성 (HTF 컨텍스트 효과)
  Q3) 12월 손실 클러스터의 신규 컬럼 분포
  Q4) Stale CHoCH age — 손실 vs 승리 trade의 trend_age 분포
  Q5) PD location (premium/discount) — 진입 위치 효과
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("stage4l_redist_outputs")
SCENARIO = "boost25"  # sweet spot

trades = pd.read_csv(OUT / f"stage4l_{SCENARIO}_out_skip_trades.csv")
trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
trades["exit_time"]  = pd.to_datetime(trades["exit_time"], utc=True)

def banner(s, ch="="):
    print(); print(ch * 90); print(s); print(ch * 90)

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

# =========================================================
banner(f"[{SCENARIO.upper()}] 전체: {len(trades)} trades / win% {(trades['net_pnl']>0).mean()*100:.2f} / PF {fmt_pf(trades):.2f}")

# =========================================================
banner("Q1: Reverse CHoCH가 SL보다 먼저 발생한 비율 (Q6 검증)")
# =========================================================
print("\n[전체 trade의 reverse_choch_before_sl 분포]")
v = trades["reverse_choch_before_sl"].value_counts(dropna=False)
v_pct = v / len(trades) * 100
for k, n in v.items():
    print(f"  {str(k):<15} {n:>5} ({v_pct[k]:>5.1f}%)")

print("\n[손실 trade만 — exit_reason='stop' 인 경우 reverse 발생 timing]")
losers = trades[(trades["net_pnl"]<0) & (trades["exit_reason"]=="stop")]
print(f"  총 stop 손실 trade: {len(losers)}")
v = losers["reverse_choch_before_sl"].value_counts(dropna=False)
for k, n in v.items():
    pct = n / len(losers) * 100
    print(f"  {str(k):<15} {n:>5} ({pct:>5.1f}%)")

# bars_to_reverse_choch 분포 (반대 CHoCH 발생한 trade만)
print("\n[bars_to_reverse_choch 분포 — 반대 CHoCH가 발생한 trade]")
sub = trades[trades["bars_to_reverse_choch"].notna()]
print(f"  총 {len(sub)} ({len(sub)/len(trades)*100:.1f}%) — 진입 후 hold 중 반대 CHoCH 등장")
if len(sub) > 0:
    print(f"  bars_to_reverse 분포:")
    print(f"    mean={sub['bars_to_reverse_choch'].mean():.1f}h, median={sub['bars_to_reverse_choch'].median():.1f}h")
    print(f"    min={sub['bars_to_reverse_choch'].min():.1f}h, max={sub['bars_to_reverse_choch'].max():.1f}h")
    # bin 분포
    bins = [0, 4, 8, 16, 24, 48, 96, 1000]
    labels = ["0-4h", "4-8h", "8-16h", "16-24h", "24-48h", "48-96h", "96+h"]
    sub_c = sub.copy()
    sub_c["bin"] = pd.cut(sub_c["bars_to_reverse_choch"], bins=bins, labels=labels)
    print(f"\n    bin 분포 (반대 CHoCH 등장 시점):")
    for label in labels:
        b = sub_c[sub_c["bin"] == label]
        if len(b) == 0: continue
        b_pf = fmt_pf(b)
        b_win = (b["net_pnl"]>0).mean()*100
        print(f"      {label:<10} n={len(b):>4} win={b_win:>5.1f}% PF={b_pf:.2f}")

# =========================================================
banner("Q2: D1 EMA state vs 진입 방향 정합성")
# =========================================================
trades["d1_align"] = "neutral"
trades.loc[(trades["side"]=="long") & (trades["d1_ema_state"]=="bull"), "d1_align"] = "aligned"
trades.loc[(trades["side"]=="short") & (trades["d1_ema_state"]=="bear"), "d1_align"] = "aligned"
trades.loc[(trades["side"]=="long") & (trades["d1_ema_state"]=="bear"), "d1_align"] = "counter"
trades.loc[(trades["side"]=="short") & (trades["d1_ema_state"]=="bull"), "d1_align"] = "counter"

print("\n[D1 정합성별 성과]")
print(f"{'category':<12} {'n':>5} {'%':>6} {'win%':>7} {'PF':>7} {'avg_R':>8} {'pnl':>14}")
for cat in ["aligned", "counter", "neutral"]:
    sub = trades[trades["d1_align"]==cat]
    if len(sub)==0: continue
    print(f"{cat:<12} {len(sub):>5} {len(sub)/len(trades)*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} "
          f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# 12월 구간만 별도
print("\n[2025-12 구간만 D1 정합성]")
dec = trades[(trades["exit_time"] >= "2025-12-15") & (trades["exit_time"] <= "2025-12-31")]
print(f"  12월 후반 trade: {len(dec)}")
for cat in ["aligned", "counter", "neutral"]:
    sub = dec[dec["d1_align"]==cat]
    if len(sub)==0: continue
    print(f"  {cat:<10} n={len(sub):>3} win={((sub['net_pnl']>0).mean()*100):>5.1f}% PF={fmt_pf(sub):.2f} pnl=${sub['net_pnl'].sum():>+12,.0f}")

# =========================================================
banner("Q3: 12월 손실 클러스터의 신규 컬럼 분포")
# =========================================================
dec_loss = trades[(trades["exit_time"] >= "2025-12-15") & (trades["exit_time"] <= "2025-12-31") & (trades["net_pnl"]<0)]
print(f"\n12월 손실 trade ({len(dec_loss)}건):")
if len(dec_loss):
    print("\n  [d1_ema_state 분포]")
    print(dec_loss["d1_ema_state"].value_counts().to_string())
    print("\n  [d1_align 분포]")
    print(dec_loss["d1_align"].value_counts().to_string())
    print(f"\n  [d1_ema200_slope_pct]")
    print(f"    mean={dec_loss['d1_ema200_slope_pct'].mean():.2f}%, median={dec_loss['d1_ema200_slope_pct'].median():.2f}%")
    print(f"    range: [{dec_loss['d1_ema200_slope_pct'].min():.2f}%, {dec_loss['d1_ema200_slope_pct'].max():.2f}%]")
    print("\n  [trend_age_bars (마지막 H1 CHoCH로부터 시간)]")
    age = dec_loss["trend_age_bars"].dropna()
    if len(age):
        print(f"    mean={age.mean():.1f}h ({age.mean()/24:.1f}일), median={age.median():.1f}h")
        print(f"    range: [{age.min():.1f}h, {age.max():.1f}h]")
    print("\n  [reverse_choch_before_sl]")
    print(dec_loss["reverse_choch_before_sl"].value_counts().to_string())
    print("\n  [entry_pd_loc]")
    print(dec_loss["entry_pd_loc"].value_counts().to_string())

# =========================================================
banner("Q4: trend_age_bars — 손실 vs 승리 분포")
# =========================================================
win = trades[trades["net_pnl"]>0]
loss = trades[trades["net_pnl"]<0]

age_w = win["trend_age_bars"].dropna()
age_l = loss["trend_age_bars"].dropna()
print(f"\n승리 trade trend_age (H1 bars):")
print(f"  n={len(age_w)}, mean={age_w.mean():.1f}h ({age_w.mean()/24:.1f}d), median={age_w.median():.1f}h")
print(f"\n손실 trade trend_age:")
print(f"  n={len(age_l)}, mean={age_l.mean():.1f}h ({age_l.mean()/24:.1f}d), median={age_l.median():.1f}h")

# bin 분포로 PF 비교
print("\n[trend_age bin × 성과]")
bins = [0, 24, 72, 168, 336, 720, 1440, 99999]
labels = ["0-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-60d", "60d+"]
trades["age_bin"] = pd.cut(trades["trend_age_bars"], bins=bins, labels=labels)
print(f"{'age_bin':<10} {'n':>5} {'%':>6} {'win%':>7} {'PF':>7} {'avg_R':>8}")
for label in labels:
    sub = trades[trades["age_bin"]==label]
    if len(sub)==0: continue
    print(f"{label:<10} {len(sub):>5} {len(sub)/len(trades)*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} "
          f"{sub['r_multiple'].mean():>+8.3f}")

# =========================================================
banner("Q5: entry_pd_loc (premium/discount) × side 성과")
# =========================================================
print(f"\n{'pd_loc':<12} {'side':<7} {'n':>5} {'win%':>7} {'PF':>7} {'avg_R':>8}")
for pd_loc in trades["entry_pd_loc"].unique():
    for side in ["long", "short"]:
        sub = trades[(trades["entry_pd_loc"]==pd_loc) & (trades["side"]==side)]
        if len(sub)==0: continue
        print(f"{str(pd_loc):<12} {side:<7} {len(sub):>5} "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} "
              f"{sub['r_multiple'].mean():>+8.3f}")

# =========================================================
banner("종합 요약 — 처방 우선순위 결정")
# =========================================================
print("\n[Q1 결론] reverse_choch_before_sl 분포 보고 다음 결정:")
y_n = losers["reverse_choch_before_sl"].value_counts(dropna=False)
n_yes = y_n.get("yes", 0)
n_no = y_n.get("no", 0)
n_no_rev = y_n.get("no_reverse", 0)
total = n_yes + n_no + n_no_rev
if total > 0:
    yes_pct = n_yes / total * 100
    no_pct = n_no / total * 100
    print(f"  손실 stop trade {total}건 중:")
    print(f"    reverse가 SL보다 먼저: {n_yes} ({yes_pct:.1f}%)")
    print(f"    SL이 먼저: {n_no} ({no_pct:.1f}%)")
    print(f"    reverse 자체 없음: {n_no_rev} ({n_no_rev/total*100:.1f}%)")
    if yes_pct > 30:
        print(f"  → reverse exit 처방 효과 큼 (yes {yes_pct:.0f}% > 30%)")
    elif yes_pct > 10:
        print(f"  → reverse exit 처방 일부 효과 (yes {yes_pct:.0f}%)")
    else:
        print(f"  → reverse exit 처방 효과 미미 — H1 CHoCH가 SL과 거의 동시 (yes {yes_pct:.0f}%)")

print("\n[Q2 결론] D1 정합성:")
ali = trades[trades["d1_align"]=="aligned"]
ctr = trades[trades["d1_align"]=="counter"]
neu = trades[trades["d1_align"]=="neutral"]
if len(ctr) > 0:
    counter_pf = fmt_pf(ctr)
    aligned_pf = fmt_pf(ali) if len(ali) > 0 else 0
    print(f"  Counter trade {len(ctr)}건 PF={counter_pf:.2f} vs Aligned {len(ali)}건 PF={aligned_pf:.2f}")
    if counter_pf < aligned_pf * 0.7:
        print(f"  → D1 align 처방 효과 클 것 (counter PF가 aligned 대비 30%+ 낮음)")
    else:
        print(f"  → D1 align 효과 제한적 (counter PF가 별로 안 나쁨)")

print("\n[Q4 결론] stale CHoCH:")
if len(age_w) and len(age_l):
    if age_l.mean() > age_w.mean() * 1.3:
        print(f"  → stale 영향 있음 (손실 trade의 평균 trend_age {age_l.mean():.0f}h > 승리 {age_w.mean():.0f}h)")
    else:
        print(f"  → stale 영향 미미 (손실 vs 승리 trend_age 비슷: {age_l.mean():.0f}h vs {age_w.mean():.0f}h)")
