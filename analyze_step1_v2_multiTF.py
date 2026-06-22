"""
Step 1 v2 — Multi-Timeframe Trend Definition 일관성 비교

목적: 어떤 timeframe의 trend가 trade의 win/loss와 가장 일관되게 정합되는가?
     단순 align > counter PF가 아니라 *시기별 일관성*이 핵심.

검증 항목:
  P1) 7개 trend definition별 align/counter 성과 (전체 + 시기별)
  P2) 일관성 — 분기별로 aligned PF > counter PF 비율
  P3) Stale CHoCH age vs 성과 (trend_age_bars 데이터 fix됨)
  P4) PD location × side 효과 (pd_loc 데이터 fix됨)
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
SCENARIO = "boost25"

trades = pd.read_csv(OUT / f"stage4l_{SCENARIO}_out_skip_trades.csv")
trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
trades["exit_time"]  = pd.to_datetime(trades["exit_time"], utc=True)
trades["quarter"] = trades["entry_time"].dt.to_period("Q")

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch * 95); print(s); print(ch * 95)

# ─────────────────────────────────────────────────────────
# 7개 trend definition 매핑
# 각 definition에 대해 trade에 align/counter/neutral 분류
# ─────────────────────────────────────────────────────────
def make_align_col(trades, trend_col, side_col="side"):
    """
    trend_col 의 값이 'bull'/'up' 이고 side='long' → aligned
    trend_col 의 값이 'bear'/'down' 이고 side='short' → aligned
    그 반대 → counter
    그 외 (mixed/neutral 등) → neutral
    """
    s = trades[trend_col].astype(str).str.lower()
    sd = trades[side_col].astype(str).str.lower()
    out = pd.Series("neutral", index=trades.index, dtype=object)
    out[((s == "bull") | (s == "up")) & (sd == "long")] = "aligned"
    out[((s == "bear") | (s == "down")) & (sd == "short")] = "aligned"
    out[((s == "bull") | (s == "up")) & (sd == "short")] = "counter"
    out[((s == "bear") | (s == "down")) & (sd == "long")] = "counter"
    return out

# trend definition 컬럼 매핑
DEFINITIONS = [
    ("D1_EMA50_200",       "d1_ema_state"),         # bull / bear / neutral
    ("D1_close_vs_EMA200", "d1_close_vs_ema200"),   # bull / bear
    ("H4_EMA_full",        "h4_ema_state"),         # bull / bear / mixed
    ("H4_close_vs_EMA200", "h4_close_vs_ema200"),
    ("H1_EMA_full",        "h1_ema_state"),
    ("H1_close_vs_EMA200", "h1_close_vs_ema200"),
    ("H1_CHoCH_state",     "last_choch_direction"), # bull / bear / none
]

# H1_CHoCH는 bull/bear → align mapping 약간 다름 (down에 해당하는 게 'bear')
# 위 make_align_col의 mapping이 'bear'를 처리하므로 OK

banner(f"[{SCENARIO.upper()}] 전체: {len(trades)} / win {(trades['net_pnl']>0).mean()*100:.2f}% / PF {fmt_pf(trades):.2f}")

# ─────────────────────────────────────────────────────────
# P1: 전체 기간 align/counter 성과
# ─────────────────────────────────────────────────────────
banner("P1: 7개 trend definition × 전체 align/counter 성과")
print(f"\n{'definition':<22} {'cat':<10} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
all_align = {}
for label, col in DEFINITIONS:
    if col not in trades.columns:
        print(f"  [SKIP] {label} — column '{col}' not found")
        continue
    align = make_align_col(trades, col)
    all_align[label] = align
    for cat in ["aligned", "counter", "neutral"]:
        sub = trades[align == cat]
        if len(sub) == 0: continue
        print(f"{label:<22} {cat:<10} {len(sub):>5} {len(sub)/len(trades)*100:>5.1f}% "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")
    print()

# ─────────────────────────────────────────────────────────
# P2: 일관성 — 분기별 aligned PF vs counter PF
# ─────────────────────────────────────────────────────────
banner("P2: 일관성 — 분기별 aligned PF > counter PF 비율 (높을수록 신뢰)")
quarters = sorted(trades["quarter"].dropna().unique().tolist())
print(f"\n분기 수: {len(quarters)}")

print(f"\n{'definition':<22} {'aligned 우세 분기':>16} {'counter 우세':>13} {'동률':>7} {'일관성%':>9}")
consistency_results = []
for label, col in DEFINITIONS:
    if label not in all_align:
        continue
    align = all_align[label]
    n_aligned_better = 0
    n_counter_better = 0
    n_tie = 0
    n_valid = 0
    for q in quarters:
        mask = trades["quarter"] == q
        sub_a = trades[mask & (align == "aligned")]
        sub_c = trades[mask & (align == "counter")]
        if len(sub_a) < 5 or len(sub_c) < 5:  # 표본 너무 작은 분기 skip
            continue
        n_valid += 1
        pf_a = fmt_pf(sub_a)
        pf_c = fmt_pf(sub_c)
        if pf_a > pf_c * 1.1:    # aligned가 10%+ 우세
            n_aligned_better += 1
        elif pf_c > pf_a * 1.1:
            n_counter_better += 1
        else:
            n_tie += 1
    if n_valid == 0:
        consistency = 0
    else:
        consistency = n_aligned_better / n_valid * 100
    consistency_results.append((label, n_aligned_better, n_counter_better, n_tie, consistency, n_valid))
    print(f"{label:<22} {n_aligned_better:>16} {n_counter_better:>13} {n_tie:>7} "
          f"{consistency:>8.1f}% (총 {n_valid} 분기)")

# 일관성 ranking (counter dominance도 함께 — 둘 다 의미)
print(f"\n[Ranking by consistency — aligned 가 일관되게 우세한 timeframe]")
consistency_results.sort(key=lambda x: -x[4])
for i, (label, ab, cb, tie, c, n) in enumerate(consistency_results):
    if n > 0:
        cb_pct = cb / n * 100
        print(f"  {i+1}. {label:<22} aligned 우세 {c:>5.1f}%  /  counter 우세 {cb_pct:>5.1f}%  ({n} 분기)")

# ─────────────────────────────────────────────────────────
# P2-bis: 시기별 PF detail (top consistency 2개)
# ─────────────────────────────────────────────────────────
banner("P2-bis: 일관성 top2 timeframe의 분기별 aligned/counter PF")
top2 = consistency_results[:2] + consistency_results[-2:] if len(consistency_results) >= 4 else consistency_results
for label, _, _, _, _, _ in top2:
    if label not in all_align:
        continue
    align = all_align[label]
    print(f"\n[{label}]")
    print(f"  {'quarter':<10} {'al_n':>5} {'al_pf':>7} {'al_pnl':>11} {'co_n':>5} {'co_pf':>7} {'co_pnl':>11} {'winner':>10}")
    for q in quarters:
        mask = trades["quarter"] == q
        sub_a = trades[mask & (align == "aligned")]
        sub_c = trades[mask & (align == "counter")]
        if len(sub_a) < 3 and len(sub_c) < 3: continue
        pf_a = fmt_pf(sub_a) if len(sub_a) > 0 else 0
        pf_c = fmt_pf(sub_c) if len(sub_c) > 0 else 0
        winner = "aligned" if pf_a > pf_c * 1.1 else ("counter" if pf_c > pf_a * 1.1 else "tie")
        print(f"  {str(q):<10} {len(sub_a):>5} {pf_a:>7.2f} ${sub_a['net_pnl'].sum():>+10,.0f} "
              f"{len(sub_c):>5} {pf_c:>7.2f} ${sub_c['net_pnl'].sum():>+10,.0f} {winner:>10}")

# ─────────────────────────────────────────────────────────
# P3: Stale CHoCH age 분석 (trend_age_bars fix됨)
# ─────────────────────────────────────────────────────────
banner("P3: Stale CHoCH — trend_age_bars 분포 (손실 vs 승리)")
trades["age"] = pd.to_numeric(trades["trend_age_bars"], errors="coerce")
n_age = trades["age"].notna().sum()
print(f"\n  trend_age_bars 데이터 있는 trade: {n_age} / {len(trades)} ({n_age/len(trades)*100:.1f}%)")
if n_age > 100:
    win = trades[trades["net_pnl"]>0]
    loss = trades[trades["net_pnl"]<0]
    print(f"  승리 trade: n={len(win)}, age mean={win['age'].mean():.1f}h ({win['age'].mean()/24:.1f}d), median={win['age'].median():.1f}h")
    print(f"  손실 trade: n={len(loss)}, age mean={loss['age'].mean():.1f}h ({loss['age'].mean()/24:.1f}d), median={loss['age'].median():.1f}h")

    print("\n[trend_age bin별 성과]")
    bins = [0, 24, 72, 168, 336, 720, 1440, 99999]
    labels = ["0-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-60d", "60d+"]
    trades["age_bin"] = pd.cut(trades["age"], bins=bins, labels=labels)
    print(f"  {'bin':<10} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'$/trade':>10}")
    for label in labels:
        sub = trades[trades["age_bin"] == label]
        if len(sub) == 0: continue
        print(f"  {label:<10} {len(sub):>5} {len(sub)/len(trades)*100:>5.1f}% "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].mean():>10,.0f}")

# ─────────────────────────────────────────────────────────
# P4: PD location 분석 (pd_loc fix됨)
# ─────────────────────────────────────────────────────────
banner("P4: entry_pd_loc (premium/discount) × side 성과")
print(f"\n  entry_pd_loc 분포: {trades['entry_pd_loc'].value_counts().to_dict()}")
print(f"\n  {'pd_loc':<12} {'side':<7} {'n':>5} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for pd_loc in sorted(trades["entry_pd_loc"].dropna().unique()):
    for side in ["long", "short"]:
        sub = trades[(trades["entry_pd_loc"] == pd_loc) & (trades["side"] == side)]
        if len(sub) == 0: continue
        print(f"  {str(pd_loc):<12} {side:<7} {len(sub):>5} "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.3f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# ─────────────────────────────────────────────────────────
# 종합 결론
# ─────────────────────────────────────────────────────────
banner("종합 결론")
if consistency_results:
    best = consistency_results[0]
    print(f"\n[가장 일관된 trend frame]")
    print(f"  → {best[0]}: 분기 중 {best[4]:.1f}%에서 aligned가 counter보다 우세")
    print(f"     반대 (counter 우세) 분기: {best[2]/best[5]*100:.1f}%" if best[5] > 0 else "")
    if best[4] > 60:
        print(f"     → 신뢰도 충분 — 이 timeframe으로 trend filter 가능")
    elif best[4] > 50:
        print(f"     → 약한 우세 — 단독 filter는 위험. 추가 조건 결합 필요")
    else:
        print(f"     → 모든 timeframe에서 aligned 우세 패턴 약함 — trend filter 자체가 적절치 않을 수도")

    worst = consistency_results[-1]
    print(f"\n[counter가 일관되게 우세한 timeframe]")
    if worst[2] > worst[1] and worst[5] > 0:
        cb_pct = worst[2] / worst[5] * 100
        print(f"  → {worst[0]}: 분기 중 {cb_pct:.1f}%에서 counter 우세")
        print(f"     → 이 timeframe은 align 강제 시 시스템 알파를 죽임")
