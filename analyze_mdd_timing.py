"""
MDD% vs MDD$ 시점 분리 분석
  - MDD%는 percent 기준 → 자본 작을 때 작은 $ 손실도 percent 크게
  - MDD$는 절대 달러 → 자본 클 때 큰 $ 손실
  - 두 시점이 다를 수 있다 — 처방 효과가 percent MDD에 안 통하는 이유 검증
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
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

def find_mdd_pct_window(eq):
    eq = eq.copy()
    eq["time"] = pd.to_datetime(eq["time"], utc=True)
    trough_idx = eq["dd_pct"].idxmin()
    trough_t = eq.loc[trough_idx, "time"]
    peak_eq = eq.loc[trough_idx, "cummax"]
    pre = eq.loc[:trough_idx]
    peak_idx = pre[pre["total_assets"] >= peak_eq * 0.999].index[-1]
    peak_t = eq.loc[peak_idx, "time"]
    mdd_pct = eq.loc[trough_idx, "dd_pct"]
    mdd_dollar_at_pct_trough = eq.loc[trough_idx, "total_assets"] - eq.loc[trough_idx, "cummax"]
    return peak_t, trough_t, mdd_pct, mdd_dollar_at_pct_trough, eq.loc[trough_idx, "cummax"]

def find_mdd_dollar_window(eq):
    eq = eq.copy()
    eq["time"] = pd.to_datetime(eq["time"], utc=True)
    eq["dd_dollar"] = eq["total_assets"] - eq["cummax"]
    trough_idx = eq["dd_dollar"].idxmin()
    trough_t = eq.loc[trough_idx, "time"]
    peak_eq = eq.loc[trough_idx, "cummax"]
    pre = eq.loc[:trough_idx]
    peak_idx = pre[pre["total_assets"] >= peak_eq * 0.999].index[-1]
    peak_t = eq.loc[peak_idx, "time"]
    mdd_dollar = eq.loc[trough_idx, "dd_dollar"]
    mdd_pct_at_dollar_trough = eq.loc[trough_idx, "dd_pct"]
    return peak_t, trough_t, mdd_dollar, mdd_pct_at_dollar_trough, eq.loc[trough_idx, "cummax"]

def banner(s, ch="="):
    print(); print(ch*100); print(s); print(ch*100)

banner("[A] MDD% vs MDD$ — 두 MDD가 같은 시점인지 검증", "█")

for sc in SCEN:
    banner(f"BOOST{sc[5:]}", "=")
    print(f"\n  {'mult':<10} | {'MDD% 시점':<35} | {'MDD$ 시점':<35}")
    print(f"  {'':<10} | {'peak':<22} {'pct':>10} | {'peak':<22} {'dollar':>11}")
    print(f"  {'':<10} | {'trough':<22} {'cap@peak':>10} | {'trough':<22} {'cap@peak':>11}")
    print("  " + "-" * 100)
    for label, path in PATHS.items():
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        p_t, t_t, pct, dol_at_pct, cap_pct = find_mdd_pct_window(eq)
        pd_t, dt_t, dol, pct_at_dol, cap_dol = find_mdd_dollar_window(eq)
        print(f"  {label:<10} | {str(p_t)[:19]:<22} {pct:>9.2f}% | {str(pd_t)[:19]:<22} ${dol:>+10,.0f}")
        print(f"  {'':<10} | {str(t_t)[:19]:<22} ${cap_pct:>9,.0f} | {str(dt_t)[:19]:<22} ${cap_dol:>+10,.0f}")
        print()

banner("[B] MDD% 발생 시점 자본 + 그 시기 trade", "=")

for sc in SCEN:
    print(f"\n[{sc.upper()}]")
    for label, path in PATHS.items():
        eq = pd.read_csv(path / f"stage4l_{sc}_out_skip_equity.csv")
        p_t, t_t, pct, dol_at_pct, cap_pct = find_mdd_pct_window(eq)
        days = (pd.to_datetime(t_t) - pd.to_datetime(p_t)).days
        print(f"  {label:<10} MDD%={pct:.2f}%  자본 @peak ${cap_pct:>10,.0f}  $-loss=${dol_at_pct:>+10,.0f}  "
              f"({str(p_t)[:10]} → {str(t_t)[:10]}, {days}d)")

# BOOST25 MDD% 시점의 trade들 상세
banner("[C] BOOST25 MDD% 발생 시기 trade 상세 (mult별)", "=")
for label, path in PATHS.items():
    eq = pd.read_csv(path / f"stage4l_boost25_out_skip_equity.csv")
    p_t, t_t, pct, dol, cap = find_mdd_pct_window(eq)
    df = pd.read_csv(path / f"stage4l_boost25_out_skip_trades.csv")
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    win = df[(df["exit_time"] >= p_t) & (df["exit_time"] <= t_t)]
    print(f"\n  [{label}] MDD% 시기: {str(p_t)[:10]} ~ {str(t_t)[:10]}  ({pct:.2f}%, 자본 ${cap:,.0f})")
    if len(win) > 0:
        print(f"    구간 trade: {len(win)}, net=${win['net_pnl'].sum():+,.0f}, win={(win['net_pnl']>0).mean()*100:.0f}%")
        # 손실 trade
        loss = win[win["net_pnl"] < 0]
        if len(loss) > 0:
            print(f"    손실 trade {len(loss)}건 symbol/side 분포:")
            for (sym, side), n_ in loss.groupby(["symbol","side"]).size().sort_values(ascending=False).items():
                pnl_sum = loss[(loss["symbol"]==sym) & (loss["side"]==side)]["net_pnl"].sum()
                print(f"      {sym} {side}: n={n_}, pnl=${pnl_sum:+,.0f}")

# 추가: 모든 손실 클러스터 (일별 손실 큰 날들) 4-way 비교 (BOOST25)
banner("[D] BOOST25 일별 손실 클러스터 — 가장 나쁜 일자 (mult별 변화)", "=")
for label, path in PATHS.items():
    df = pd.read_csv(path / f"stage4l_boost25_out_skip_trades.csv")
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["date"] = df["exit_time"].dt.date
    daily = df.groupby("date")["net_pnl"].sum().sort_values()
    worst5 = daily.head(5)
    print(f"\n  [{label}] worst 5 days")
    for d, v in worst5.items():
        print(f"    {d}: ${v:+,.0f}")
