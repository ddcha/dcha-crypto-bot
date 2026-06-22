r"""
2026 YTD slice 분석 (2026-01 ~ 2026-04)
========================================
데이터 마지막이 2026-04 이므로 "올해 1~5월"은 1~4월 (4 개월) 분석.

각 시나리오 (RM/AM/grid 포함, 백그라운드 완료된 것만)에 대해:
  - 4개월 trade 수 / win% / avg_R / 누적 net PnL (USD)
  - 4개월 자본 변화율 (= equity 2026-04 마지막 / 2025-12 마지막)
  - 4개월 내 MDD (slice 내 dd_pct 최저)
  - 월별 net PnL ($) breakdown

산출물 (sweep_analysis_outputs/):
  06_2026_ytd_summary.csv   ── per-scenario 4-month summary
  07_2026_ytd_monthly.csv   ── per-scenario × month long format
  fig_2026_ytd_pnl.png      ── 4-month cumulative PnL overlay
  fig_2026_ytd_bars.png     ── per-scenario YTD return bar
"""
from __future__ import annotations
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(r"D:\smc_bot")
OUT  = ROOT / "sweep_analysis_outputs"
OUT.mkdir(exist_ok=True)

SCENARIOS: dict[str, dict] = {
    "RM_1.3":   {"dir": "stage4l_sweep_rm13",          "AM": 4.0, "RM": 1.3},
    "RM_1.5":   {"dir": "stage4l_sweep_rm15",          "AM": 4.0, "RM": 1.5},
    "RM_1.8":   {"dir": "stage4l_sweep_rm18",          "AM": 4.0, "RM": 1.8},
    "RM_2.2":   {"dir": "stage4l_sweep_rm22",          "AM": 4.0, "RM": 2.2},
    "AM_3.5R":  {"dir": "stage4l_AM35_REVIVE_BOOST15", "AM": 3.5, "RM": 1.0},
    "AM_4.0R":  {"dir": "stage4l_AM40_REVIVE",         "AM": 4.0, "RM": 1.0},
    "AM_5.0R":  {"dir": "stage4l_AM50_REVIVE",         "AM": 5.0, "RM": 1.0},
    "AM_6.0R":  {"dir": "stage4l_AM60_REVIVE",         "AM": 6.0, "RM": 1.0},
    "AM_8.0R":  {"dir": "stage4l_AM80_REVIVE",         "AM": 8.0, "RM": 1.0},
    "AM_10R":   {"dir": "stage4l_AM100_REVIVE",        "AM": 10.0,"RM": 1.0},
    "AM_3.5":   {"dir": "stage4l_AM35_BOOST15",        "AM": 3.5, "RM": 1.0},
    "FINAL":    {"dir": "stage4l_FINAL_outputs",       "AM": 4.0, "RM": 1.0},
    "G_AM4_RM13": {"dir": "stage4l_grid_AM40_RM13", "AM": 4.0, "RM": 1.3},
    "G_AM4_RM15": {"dir": "stage4l_grid_AM40_RM15", "AM": 4.0, "RM": 1.5},
    "G_AM5_RM13": {"dir": "stage4l_grid_AM50_RM13", "AM": 5.0, "RM": 1.3},
    "G_AM5_RM15": {"dir": "stage4l_grid_AM50_RM15", "AM": 5.0, "RM": 1.5},
    "G_AM6_RM13": {"dir": "stage4l_grid_AM60_RM13", "AM": 6.0, "RM": 1.3},
    "G_AM6_RM15": {"dir": "stage4l_grid_AM60_RM15", "AM": 6.0, "RM": 1.5},
}

YTD_START = "2026-01"
YTD_END   = "2026-04"   # 데이터 마지막


def load_one(k, m):
    d = ROOT / m["dir"]
    mo_p = d / "stage4l_boost15_out_skip_monthly.csv"
    eq_p = d / "stage4l_boost15_out_skip_equity.csv"
    if not mo_p.exists():
        return k, None
    mo = pd.read_csv(mo_p)
    try:
        eq = pd.read_csv(eq_p, usecols=["time","total_assets","dd_pct"],
                         parse_dates=["time"])
    except Exception:
        eq = None
    return k, {"meta": m, "monthly": mo, "equity": eq}


print("[1/3] Loading…")
bundles = {}
missing = []
with ThreadPoolExecutor(max_workers=18) as ex:
    futs = [ex.submit(load_one, k, v) for k, v in SCENARIOS.items()]
    for f in as_completed(futs):
        k, b = f.result()
        if b is None:
            missing.append(k)
        else:
            bundles[k] = b
print(f"   loaded={len(bundles)}  missing={missing}")

# ── 표 06 — 4개월 summary ─────────────────────────────────────────
print("\n[2/3] 4-month slice metrics…")
rows = []
month_long = []
for k, b in bundles.items():
    m = b["meta"]
    mo = b["monthly"].copy()
    # 'month' 컬럼은 'YYYY-MM' 문자열로 가정
    slice_mo = mo[(mo["month"] >= YTD_START) & (mo["month"] <= YTD_END)].copy()

    trades_n = int(slice_mo["trades"].sum()) if len(slice_mo) else 0
    pnl_usd  = float(slice_mo["net_pnl_usdt"].sum()) if len(slice_mo) else 0.0
    pnl_krw  = float(slice_mo["net_pnl_krw"].sum()) if len(slice_mo) else 0.0
    # trade-weighted win% / avg_R
    if trades_n > 0:
        win_pct  = float((slice_mo["winrate_pct"] * slice_mo["trades"]).sum() / trades_n)
        avg_r    = float((slice_mo["avg_r"]       * slice_mo["trades"]).sum() / trades_n)
    else:
        win_pct = avg_r = np.nan

    # 자본 변화: equity에서 2025-12 마지막 → 2026-04 마지막
    period_return = np.nan
    period_mdd = np.nan
    start_assets = end_assets = np.nan
    if b["equity"] is not None and not b["equity"].empty:
        eq = b["equity"].sort_values("time").copy()
        eq["ym"] = eq["time"].dt.to_period("M").astype(str)
        # 시작 직전 = 2025-12 마지막 자본
        pre = eq[eq["ym"] == "2025-12"]
        if len(pre):
            start_assets = float(pre["total_assets"].iloc[-1])
        slice_eq = eq[(eq["ym"] >= YTD_START) & (eq["ym"] <= YTD_END)]
        if len(slice_eq):
            end_assets = float(slice_eq["total_assets"].iloc[-1])
            # period MDD = slice 시작 시점의 cummax를 reset해서 다시 계산
            ta = slice_eq["total_assets"].values
            cm = np.maximum.accumulate(ta)
            dd_pct = (ta - cm) / cm * 100.0
            period_mdd = float(dd_pct.min())
        if start_assets and start_assets > 0 and pd.notna(end_assets):
            period_return = (end_assets - start_assets) / start_assets * 100.0

    rows.append({
        "scenario": k, "AM": m["AM"], "RM": m["RM"],
        "trades_4m": trades_n, "win_pct_4m": win_pct, "avg_R_4m": avg_r,
        "net_pnl_usd_4m": pnl_usd, "net_pnl_krw_4m": pnl_krw,
        "start_assets_usd": start_assets, "end_assets_usd": end_assets,
        "period_return_pct": period_return, "period_mdd_pct": period_mdd,
    })

    # long format
    if len(slice_mo):
        s = slice_mo[["month","trades","winrate_pct","avg_r","net_pnl_usdt"]].copy()
        s["scenario"] = k
        month_long.append(s)

ytd_df = pd.DataFrame(rows).sort_values("period_return_pct", ascending=False)
ytd_df.to_csv(OUT / "06_2026_ytd_summary.csv", index=False, float_format="%.4f")
print(f"   ✓ 06_2026_ytd_summary.csv ({len(ytd_df)} scenarios)")

if month_long:
    ml = pd.concat(month_long, ignore_index=True)
    ml.to_csv(OUT / "07_2026_ytd_monthly.csv", index=False, float_format="%.4f")
    print(f"   ✓ 07_2026_ytd_monthly.csv ({len(ml)} rows)")

# ── 그래프 ──────────────────────────────────────────────────────────
print("\n[3/3] Plotting…")

# 4-month cumulative PnL overlay
fig, ax = plt.subplots(figsize=(11, 6))
for k, b in bundles.items():
    if b["equity"] is None: continue
    eq = b["equity"].sort_values("time")
    eq2 = eq[(eq["time"] >= "2026-01-01") & (eq["time"] < "2026-05-01")]
    if eq2.empty: continue
    ax.plot(eq2["time"], eq2["total_assets"], label=k, alpha=0.85, linewidth=1.1)
ax.set_yscale("log")
ax.set_title("Total assets — 2026-01 ~ 2026-04 (log)")
ax.set_xlabel("Date"); ax.set_ylabel("Total assets (USD)")
ax.legend(ncol=2, fontsize=8)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(OUT / "fig_2026_ytd_equity.png", dpi=140)
plt.close(fig)
print("   ✓ fig_2026_ytd_equity.png")

# 4-month return bar
fig, ax = plt.subplots(figsize=(11, 5))
d = ytd_df.sort_values("period_return_pct", ascending=False)
ax.bar(d["scenario"], d["period_return_pct"],
       color=["tab:red" if "G_" in s else "tab:orange" if "AM" in s
              else "tab:blue" if "RM" in s else "black" for s in d["scenario"]])
ax.set_title("2026 YTD (Jan~Apr) Return % per scenario")
ax.set_ylabel("Period Return %")
ax.tick_params(axis="x", rotation=40)
for i, (_, r) in enumerate(d.iterrows()):
    ax.text(i, r["period_return_pct"], f' {r["period_return_pct"]:.0f}%',
            ha="center", va="bottom", fontsize=8)
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(OUT / "fig_2026_ytd_bars.png", dpi=140)
plt.close(fig)
print("   ✓ fig_2026_ytd_bars.png")

print("\n=== Done ===")
print("\n[YTD summary by Period Return]")
disp = ytd_df[["scenario","AM","RM","trades_4m","win_pct_4m","avg_R_4m",
               "net_pnl_usd_4m","period_return_pct","period_mdd_pct"]]
print(disp.to_string(index=False))

print("\n[Per-month breakdown]")
if month_long:
    pivot_pnl = ml.pivot_table(index="scenario", columns="month", values="net_pnl_usdt", aggfunc="sum")
    print("\n월별 net PnL (USD)")
    print(pivot_pnl.round(0).to_string())
    pivot_avgr = ml.pivot_table(index="scenario", columns="month", values="avg_r", aggfunc="mean")
    print("\n월별 avg_R")
    print(pivot_avgr.round(3).to_string())
    pivot_n    = ml.pivot_table(index="scenario", columns="month", values="trades", aggfunc="sum")
    print("\n월별 trade 수")
    print(pivot_n.to_string())
