"""
MDD 원인 진단 — 3개 구조적 가설 검증
  H1) 단일 종목/사이드 집중 손실
  H2) 시장 regime 변화에 따른 시스템 전반 동시 패배 (다종목 동시 SL)
  H3) 연속 SL streak (kill streak)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("stage4l_redist_outputs")
SCENARIOS = ["boost15", "boost25", "boost35"]

def banner(s, ch="="):
    print(); print(ch * 90); print(s); print(ch * 90)

def find_mdd_window(eq, use_dollar=False):
    """equity.csv에서 DD 구간 추출. use_dollar=True 면 절대 달러 기준."""
    eq = eq.copy()
    eq["time"] = pd.to_datetime(eq["time"], utc=True)
    if use_dollar:
        eq["dd_dollar"] = eq["total_assets"] - eq["cummax"]
        trough_idx = eq["dd_dollar"].idxmin()
    else:
        trough_idx = eq["dd_pct"].idxmin()
    trough_time = eq.loc[trough_idx, "time"]
    peak_eq = eq.loc[trough_idx, "cummax"]
    pre = eq.loc[:trough_idx]
    peak_idx = pre[pre["total_assets"] >= peak_eq * 0.999].index[-1]
    peak_time = eq.loc[peak_idx, "time"]
    return peak_time, trough_time, eq.loc[trough_idx, "dd_pct"]

def streak_stats(trades):
    """전체 기간 연속 손실 streak."""
    losers = (trades["net_pnl"] < 0).astype(int).values
    max_streak = cur = 0
    streak_starts = []
    cur_start = None
    for i, x in enumerate(losers):
        if x:
            if cur == 0: cur_start = i
            cur += 1
            if cur > max_streak:
                max_streak = cur
                streak_starts = [cur_start]
        else:
            cur = 0
    return max_streak, streak_starts

def streak_distribution(trades):
    """모든 연속 손실 streak 길이 분포."""
    losers = (trades["net_pnl"] < 0).astype(int).values
    streaks = []
    cur = 0
    for x in losers:
        if x: cur += 1
        else:
            if cur > 0: streaks.append(cur)
            cur = 0
    if cur > 0: streaks.append(cur)
    s = pd.Series(streaks)
    return s

def analyze_window(scenario, trades, eq, label, use_dollar=False):
    peak_t, trough_t, mdd_pct = find_mdd_window(eq, use_dollar=use_dollar)
    banner(f"[{scenario.upper()}] {label}", "-")
    print(f"  MDD%   : {mdd_pct:.2f}%")
    print(f"  Peak   : {peak_t}  total_assets=${eq.loc[eq['time']==peak_t,'total_assets'].iloc[0] if (eq['time']==peak_t).any() else 0:,.0f}")
    print(f"  Trough : {trough_t}")
    print(f"  Days   : {(trough_t - peak_t).days}")

    mask = (trades["exit_time"] >= peak_t) & (trades["exit_time"] <= trough_t)
    win = trades.loc[mask].copy()
    print(f"\n  MDD 구간 내 트레이드: {len(win)} (전체 {len(trades)} 중 {len(win)/len(trades)*100:.1f}%)")
    if len(win) == 0:
        return
    print(f"  win%   : {(win['net_pnl']>0).mean()*100:.2f}%")
    print(f"  net_pnl: ${win['net_pnl'].sum():,.0f}")
    print(f"  avg_R  : {win['r_multiple'].mean():.3f}")

    losers = win[win["net_pnl"] < 0]
    print(f"\n  ── MDD 구간 손실 트레이드 ({len(losers)}건) 분포 ──")

    print("\n  [심볼별 손실]")
    s = losers.groupby("symbol").agg(
        n=("net_pnl", "size"),
        loss=("net_pnl", "sum"),
        avg_R=("r_multiple", "mean"),
    ).sort_values("loss")
    s["share%"] = s["n"] / len(losers) * 100
    print(s.to_string(float_format=lambda v: f"{v:,.2f}"))

    print("\n  [사이드별 손실]")
    s = losers.groupby("side").agg(
        n=("net_pnl", "size"),
        loss=("net_pnl", "sum"),
        avg_R=("r_multiple", "mean"),
    )
    print(s.to_string(float_format=lambda v: f"{v:,.2f}"))

    print("\n  [Tier별 손실]")
    s = losers.groupby("tier_4e").agg(
        n=("net_pnl", "size"),
        loss=("net_pnl", "sum"),
        avg_R=("r_multiple", "mean"),
    ).sort_values("loss")
    print(s.to_string(float_format=lambda v: f"{v:,.2f}"))

    print("\n  [Sentiment label별 손실]")
    if "sentiment_label" in losers.columns:
        s = losers.groupby("sentiment_label").agg(
            n=("net_pnl", "size"),
            loss=("net_pnl", "sum"),
            avg_R=("r_multiple", "mean"),
        ).sort_values("loss")
        print(s.to_string(float_format=lambda v: f"{v:,.2f}"))

    print("\n  [exit_reason별]")
    s = win.groupby("exit_reason").agg(
        n=("net_pnl", "size"),
        pnl=("net_pnl", "sum"),
        win_pct=("net_pnl", lambda x: (x>0).mean()*100),
    ).sort_values("pnl")
    print(s.to_string(float_format=lambda v: f"{v:,.2f}"))

    # H2: 동시 패배 검증 - MDD 구간 일별 트레이드 수와 손실
    print("\n  [H2 검증] MDD 구간 일별 손실 클러스터 (loss <= -$5,000 day만)")
    win["date"] = win["exit_time"].dt.date
    daily = win.groupby("date").agg(
        n=("net_pnl", "size"),
        loss_n=("net_pnl", lambda x: (x<0).sum()),
        win_n=("net_pnl", lambda x: (x>0).sum()),
        net=("net_pnl", "sum"),
        symbols=("symbol", lambda x: ",".join(sorted(set(x)))),
    ).sort_values("net")
    bad_days = daily[daily["net"] <= -5000].head(10)
    if len(bad_days):
        print(bad_days.to_string(float_format=lambda v: f"{v:,.0f}"))
    else:
        print("    (단일 큰 손실일 없음 — 손실이 분산됨)")

    # H3: 연속 SL streak — 전체 기간
    print("\n  [H3 검증] 전체 기간 연속 손실 streak 분포")
    s = streak_distribution(trades)
    print(f"    max streak = {s.max()}, mean = {s.mean():.2f}")
    print(f"    streak 길이 분포 (1~10):")
    bins = s.value_counts().sort_index()
    for k in range(1, 11):
        v = bins.get(k, 0)
        bar = "#" * int(v / max(1, bins.max()) * 30)
        print(f"      {k:2d}연패: {v:4d} {bar}")
    long_streaks = s[s >= 5]
    print(f"    5연패 이상: {len(long_streaks)} 회")

    # H3: MDD 구간 내 streak
    print("\n  [H3] MDD 구간 내 max 연속 손실 streak")
    win_sorted = win.sort_values("exit_time").reset_index(drop=True)
    max_s, _ = streak_stats(win_sorted)
    print(f"    MDD 구간 max 연속 SL: {max_s}")

    # 종합 진단
    print("\n  ── 종합 진단 ──")
    sym_top = losers.groupby("symbol")["net_pnl"].sum().sort_values()
    if len(sym_top):
        top1_share = abs(sym_top.iloc[0]) / abs(losers["net_pnl"].sum()) * 100
        print(f"    Top1 심볼({sym_top.index[0]}) 손실 비중: {top1_share:.1f}%")
        side_count = losers["side"].value_counts()
        if len(side_count) == 1:
            print(f"    H1 강력 지지: 단일 사이드({side_count.index[0]}) only")
        elif side_count.iloc[0] / len(losers) > 0.7:
            print(f"    H1 부분 지지: {side_count.index[0]} side가 {side_count.iloc[0]/len(losers)*100:.0f}% 차지")
        if top1_share > 40:
            print(f"    → H1(단일 종목 집중) 가능성 높음")
        elif len(daily[daily['net'] <= -5000]) >= 2:
            print(f"    → H2(시장 regime / 동시 패배) 가능성 높음")
        else:
            print(f"    → H3(연속 streak) 또는 분산 손실 가능성")

def analyze(scenario):
    banner(f"{'#'*4} [{scenario.upper()}] MDD 원인 진단 {'#'*4}", "=")
    trades = pd.read_csv(OUT / f"stage4l_{scenario}_out_skip_trades.csv")
    eq = pd.read_csv(OUT / f"stage4l_{scenario}_out_skip_equity.csv")
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"]  = pd.to_datetime(trades["exit_time"], utc=True)
    eq["time"] = pd.to_datetime(eq["time"], utc=True)

    # Percent 기준 (전체 통계 기록 유지를 위해)
    analyze_window(scenario, trades, eq, "MDD% 기준 (백분율 최저점)", use_dollar=False)
    # Dollar 기준 (자본 큰 후반에 발생할 가능성)
    analyze_window(scenario, trades, eq, "MDD$ 기준 (절대 달러 최대 손실)", use_dollar=True)

for sc in SCENARIOS:
    analyze(sc)
