"""
Wave-aware Trend Filter 검증

가설: D1 wave_state 기반 trend 인식 + 방향 제한이 효과 있을까?
  3가지 trend 정의:
    T1) D1 wave single (D1=impulse_up → bullish trend)
    T2) D1 + H4 둘 다 같은 방향 = 강한 trend (continuation)
    T3) 3-TF 모두 같은 방향 = 가장 강한 trend
  각 정의별로:
    - aligned PF (trend 방향 진입) vs counter PF (반대 방향)
    - 분기별 일관성 (aligned가 더 좋은 분기 비율)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
from pathlib import Path

DATA = Path("stage4l_redist_outputs_wave_baseline")  # 처방 없는 깨끗한 데이터
SCEN = "boost25"

t = pd.read_csv(DATA / f"stage4l_{SCEN}_out_skip_trades.csv")
t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
t["quarter"] = t["entry_time"].dt.to_period("Q")
t["d1"] = t["d1_wave_state"].astype(str)
t["h4"] = t["h4_wave_state"].astype(str)
t["h1"] = t["h1_wave_state"].astype(str)

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*100); print(s); print(ch*100)

baseline_pf = fmt_pf(t)
banner(f"[{SCEN.upper()}] 전체 {len(t)} trades / win {(t['net_pnl']>0).mean()*100:.2f}% / PF {baseline_pf:.3f}")

# ─────────────────────────────────────────────────────────
# T1: D1 wave single trend
# ─────────────────────────────────────────────────────────
banner("[T1] D1 wave 단독 — bullish (impulse_up) vs bearish (impulse_down)", "=")

def trend_T1(row):
    if row["d1"] == "impulse_up": return "bullish"
    if row["d1"] == "impulse_down": return "bearish"
    return "neutral"

t["T1_trend"] = t.apply(trend_T1, axis=1)
t["T1_align"] = "n/a"
t.loc[(t["T1_trend"]=="bullish") & (t["side"]=="long"), "T1_align"] = "aligned"
t.loc[(t["T1_trend"]=="bearish") & (t["side"]=="short"), "T1_align"] = "aligned"
t.loc[(t["T1_trend"]=="bullish") & (t["side"]=="short"), "T1_align"] = "counter"
t.loc[(t["T1_trend"]=="bearish") & (t["side"]=="long"), "T1_align"] = "counter"

print(f"\n[T1] 전체 성과")
print(f"  {'category':<12} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for cat in ["aligned", "counter", "n/a"]:
    sub = t[t["T1_align"]==cat]
    if len(sub)==0: continue
    print(f"  {cat:<12} {len(sub):>5} {len(sub)/len(t)*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
          f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# T2: D1 + H4 동시 (강한 trend = continuation)
# ─────────────────────────────────────────────────────────
banner("[T2] D1 + H4 동시 같은 방향 — 강한 trend (continuation)", "=")

def trend_T2(row):
    if row["d1"] == "impulse_up" and row["h4"] == "impulse_up": return "bullish"
    if row["d1"] == "impulse_down" and row["h4"] == "impulse_down": return "bearish"
    return "neutral"

t["T2_trend"] = t.apply(trend_T2, axis=1)
t["T2_align"] = "n/a"
t.loc[(t["T2_trend"]=="bullish") & (t["side"]=="long"), "T2_align"] = "aligned"
t.loc[(t["T2_trend"]=="bearish") & (t["side"]=="short"), "T2_align"] = "aligned"
t.loc[(t["T2_trend"]=="bullish") & (t["side"]=="short"), "T2_align"] = "counter"
t.loc[(t["T2_trend"]=="bearish") & (t["side"]=="long"), "T2_align"] = "counter"

print(f"\n[T2] 전체 성과")
print(f"  {'category':<12} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for cat in ["aligned", "counter", "n/a"]:
    sub = t[t["T2_align"]==cat]
    if len(sub)==0: continue
    print(f"  {cat:<12} {len(sub):>5} {len(sub)/len(t)*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
          f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# T3: 3-TF 모두 같은 방향 = 가장 강한 trend
# ─────────────────────────────────────────────────────────
banner("[T3] D1 + H4 + H1 모두 같은 방향 — 가장 강한 trend", "=")

def trend_T3(row):
    if row["d1"]=="impulse_up" and row["h4"]=="impulse_up" and row["h1"]=="impulse_up": return "bullish"
    if row["d1"]=="impulse_down" and row["h4"]=="impulse_down" and row["h1"]=="impulse_down": return "bearish"
    return "neutral"

t["T3_trend"] = t.apply(trend_T3, axis=1)
t["T3_align"] = "n/a"
t.loc[(t["T3_trend"]=="bullish") & (t["side"]=="long"), "T3_align"] = "aligned"
t.loc[(t["T3_trend"]=="bearish") & (t["side"]=="short"), "T3_align"] = "aligned"
t.loc[(t["T3_trend"]=="bullish") & (t["side"]=="short"), "T3_align"] = "counter"
t.loc[(t["T3_trend"]=="bearish") & (t["side"]=="long"), "T3_align"] = "counter"

print(f"\n[T3] 전체 성과")
print(f"  {'category':<12} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for cat in ["aligned", "counter", "n/a"]:
    sub = t[t["T3_align"]==cat]
    if len(sub)==0: continue
    print(f"  {cat:<12} {len(sub):>5} {len(sub)/len(t)*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
          f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# 분기별 일관성
# ─────────────────────────────────────────────────────────
banner("[일관성] 각 trend 정의의 분기별 aligned vs counter PF", "=")

quarters = sorted(t["quarter"].dropna().unique().tolist())
print(f"\n총 분기: {len(quarters)}")

print(f"\n{'정의':<8} {'aligned 우세':>12} {'counter 우세':>13} {'동등':>6} {'일관성%':>9} {'유효 분기':>10}")
for label, col in [("T1", "T1_align"), ("T2", "T2_align"), ("T3", "T3_align")]:
    n_better = 0; n_worse = 0; n_tie = 0; n_valid = 0
    for q in quarters:
        sub_a = t[(t["quarter"]==q) & (t[col]=="aligned")]
        sub_c = t[(t["quarter"]==q) & (t[col]=="counter")]
        if len(sub_a) < 5 or len(sub_c) < 5: continue
        n_valid += 1
        pf_a = fmt_pf(sub_a); pf_c = fmt_pf(sub_c)
        if pf_a > pf_c * 1.15: n_better += 1
        elif pf_c > pf_a * 1.15: n_worse += 1
        else: n_tie += 1
    cons = n_better / max(n_valid, 1) * 100
    cnt_w = n_worse / max(n_valid, 1) * 100
    sign = "STRONG aligned" if cons > 60 else ("STRONG counter" if cnt_w > 60 else "MIXED")
    print(f"{label:<8} {n_better:>12} {n_worse:>13} {n_tie:>6} {cons:>8.1f}% {n_valid:>10}  [{sign}]")

# ─────────────────────────────────────────────────────────
# T3 자세히 — 3-TF aligned 시기에 정말 counter가 좋나?
# ─────────────────────────────────────────────────────────
banner("[T3 상세] 가장 강한 trend (3-TF aligned) 시기 — 분기별 PF", "=")

print(f"\n{'quarter':<10} {'al_n':>5} {'al_pf':>8} {'al_pnl':>11} {'co_n':>5} {'co_pf':>8} {'co_pnl':>11} {'winner':>10}")
for q in quarters:
    sub_a = t[(t["quarter"]==q) & (t["T3_align"]=="aligned")]
    sub_c = t[(t["quarter"]==q) & (t["T3_align"]=="counter")]
    if len(sub_a) < 3 and len(sub_c) < 3: continue
    pf_a = fmt_pf(sub_a) if len(sub_a) > 0 else 0
    pf_c = fmt_pf(sub_c) if len(sub_c) > 0 else 0
    winner = "aligned" if pf_a > pf_c * 1.15 else ("counter" if pf_c > pf_a * 1.15 else "tie")
    print(f"{str(q):<10} {len(sub_a):>5} {pf_a:>8.2f} ${sub_a['net_pnl'].sum():>+10,.0f} "
          f"{len(sub_c):>5} {pf_c:>8.2f} ${sub_c['net_pnl'].sum():>+10,.0f} {winner:>10}")

# ─────────────────────────────────────────────────────────
# 결론 + 처방 후보
# ─────────────────────────────────────────────────────────
banner("[결론]", "=")
print(f"\n  baseline PF: {baseline_pf:.3f}")
for label, col in [("T1 (D1 wave 단독)", "T1_align"),
                   ("T2 (D1+H4 동시)", "T2_align"),
                   ("T3 (3-TF aligned)", "T3_align")]:
    a = t[t[col]=="aligned"]
    c = t[t[col]=="counter"]
    if len(a) and len(c):
        pf_a = fmt_pf(a); pf_c = fmt_pf(c)
        ratio = pf_c / max(pf_a, 0.01)
        print(f"\n  [{label}]  aligned PF={pf_a:.2f} (n={len(a)})  vs  counter PF={pf_c:.2f} (n={len(c)})")
        if pf_a > pf_c * 1.2:
            print(f"      → aligned가 {(pf_a/pf_c-1)*100:.0f}% 우세 — trend filter 효과 있을 수 있음")
        elif pf_c > pf_a * 1.2:
            print(f"      → counter가 {(pf_c/pf_a-1)*100:.0f}% 우세 — trend filter 잘못된 처방 (counter 차단하면 알파 죽음)")
        else:
            print(f"      → 거의 동등 — 단독 trend filter 의미 X")
