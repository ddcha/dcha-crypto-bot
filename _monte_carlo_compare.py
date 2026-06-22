r"""
Monte Carlo 비교 — AM=1.0 vs AM=4.0 (5월 포함)
================================================
ALPHA_MAX tier multiplier 효과 측정:
  AM=1.0: ALPHA_MAX risk x 1.0 (다른 tier들과 동일, ALPHA_HIGH 1.5보다 오히려 낮음)
  AM=4.0: ALPHA_MAX risk x 4.0 (FINAL baseline)

ALPHA_MAX edge가 진짜 가치가 있는지 통계적으로 검증.

5,000 path × 1,352 trades shuffle + resample 양쪽 모두.
"""
from __future__ import annotations
import sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"D:\smc_bot")
OUT  = ROOT / "sweep_analysis_outputs"
OUT.mkdir(exist_ok=True)

SCENARIOS = {
    "AM=4.0 (FINAL)":  ROOT / "stage4l_FINAL_through_may" / "stage4l_boost15_out_skip_trades.csv",
    "AM=1.0 (ablation)": ROOT / "stage4l_AM10_through_may" / "stage4l_boost15_out_skip_trades.csv",
}

INITIAL_USD = 3_000_000 / 1350.0
TARGET_USD = 2_470_000.0
N_SIMS = 5000


def load_trades(fp):
    if not fp.exists():
        return None
    return pd.read_csv(fp, usecols=["r_multiple", "risk_pct_requested",
                                     "net_pnl", "month", "tier"])


def run_one(name, trades, rng):
    """단일 시나리오에 대해 baseline + shuffle + resample MC 실행."""
    r = trades["r_multiple"].values.astype(np.float64)
    p = trades["risk_pct_requested"].values.astype(np.float64)
    n = len(r)
    trade_returns = np.maximum(1.0 + p * r, 1e-3)
    overall_geomean = trade_returns.prod()  # 한 번 곱셈하면 final equity factor

    # Baseline
    equity_b = INITIAL_USD * np.cumprod(trade_returns)
    cm_b = np.maximum.accumulate(equity_b)
    dd_b = (equity_b - cm_b) / cm_b * 100.0
    base = {
        "name": name, "n": n,
        "mdd_pct": float(dd_b.min()),
        "final_usd": float(equity_b[-1]),
        "geom_mean_per_trade": float(trade_returns.mean()),
        "geom_factor_total": float(overall_geomean),
        "winrate_pct": float((r > 0).mean() * 100),
        "avg_R": float(r.mean()),
    }
    # Baseline streak
    loss_b = (trade_returns < 1.0).astype(np.int8)
    cnt = 0; best_streak_b = 0
    for v in loss_b:
        cnt = cnt + 1 if v else 0
        if cnt > best_streak_b: best_streak_b = cnt
    base["max_loss_streak"] = best_streak_b

    # Trade index → month for retirement
    trade_months = trades["month"].values
    months = sorted(pd.unique(trade_months).tolist())
    m2n = {m: i for i, m in enumerate(months)}
    tmnum = np.array([m2n[m] for m in trade_months])
    reach_b = int(np.argmax(equity_b >= TARGET_USD)) if (equity_b >= TARGET_USD).any() else -1
    base["reach_month"] = int(tmnum[reach_b] + 1) if reach_b >= 0 else None

    # Shuffle MC
    sort_key = rng.random((N_SIMS, n))
    perm = np.argsort(sort_key, axis=1)
    returns_s = trade_returns[perm]
    equity_s = INITIAL_USD * np.cumprod(returns_s, axis=1)
    cm_s = np.maximum.accumulate(equity_s, axis=1)
    dd_s = (equity_s - cm_s) / cm_s * 100.0
    mdd_s = dd_s.min(axis=1)
    fin_s = equity_s[:, -1]
    reach_s = np.where((equity_s >= TARGET_USD).any(axis=1),
                        (equity_s >= TARGET_USD).argmax(axis=1), -1)
    # Streak per path (loop OK at 5000)
    loss_s = (returns_s < 1.0).astype(np.int8)
    streak_s = np.zeros(N_SIMS, dtype=np.int32)
    for i in range(N_SIMS):
        cnt = 0; best = 0
        for v in loss_s[i]:
            cnt = cnt + 1 if v else 0
            if cnt > best: best = cnt
        streak_s[i] = best
    del sort_key, perm, returns_s, loss_s

    # Resample MC
    idx = rng.integers(0, n, size=(N_SIMS, n))
    returns_r = trade_returns[idx]
    equity_r = INITIAL_USD * np.cumprod(returns_r, axis=1)
    cm_r = np.maximum.accumulate(equity_r, axis=1)
    dd_r = (equity_r - cm_r) / cm_r * 100.0
    mdd_r = dd_r.min(axis=1)
    fin_r = equity_r[:, -1]
    reach_r = np.where((equity_r >= TARGET_USD).any(axis=1),
                        (equity_r >= TARGET_USD).argmax(axis=1), -1)
    loss_r = (returns_r < 1.0).astype(np.int8)
    streak_r = np.zeros(N_SIMS, dtype=np.int32)
    for i in range(N_SIMS):
        cnt = 0; best = 0
        for v in loss_r[i]:
            cnt = cnt + 1 if v else 0
            if cnt > best: best = cnt
        streak_r[i] = best
    del idx, returns_r, loss_r

    # Reach to months (Shuffle/Resample)
    def idx_to_month(arr):
        out = np.full(arr.shape, np.nan)
        valid = arr >= 0
        if valid.any():
            out[valid] = tmnum[arr[valid]] + 1
        return out

    rm_s = idx_to_month(reach_s)
    rm_r = idx_to_month(reach_r)
    miss_rate_s = float(np.mean(reach_s < 0) * 100)
    miss_rate_r = float(np.mean(reach_r < 0) * 100)

    # Tier 분포
    tier_dist = trades["tier"].value_counts().to_dict()

    return {
        "name": name,
        "base": base,
        "tier_dist": tier_dist,
        "shuffle": {"mdd": mdd_s, "final": fin_s, "reach_m": rm_s,
                    "streak": streak_s, "miss_rate": miss_rate_s,
                    "equity_paths": equity_s},
        "resample": {"mdd": mdd_r, "final": fin_r, "reach_m": rm_r,
                     "streak": streak_r, "miss_rate": miss_rate_r,
                     "equity_paths": equity_r},
    }


def pct(arr, p):
    if np.all(np.isnan(arr)): return np.nan
    return float(np.nanpercentile(arr, p))


# ── Load both & run ──
rng = np.random.default_rng(42)
results = {}
for name, fp in SCENARIOS.items():
    print(f"\n=== Loading {name} ({fp.name}) ===")
    trades = load_trades(fp)
    if trades is None:
        print(f"   ✗ MISSING")
        continue
    print(f"   loaded {len(trades)} trades, tiers={trades.tier.value_counts().to_dict()}")
    print(f"   Running MC 5,000×{len(trades)}…")
    results[name] = run_one(name, trades, rng)


# ── Build comparison table ──
def summary_row(label, val, fmt="{:.2f}"):
    return [label] + [fmt.format(v) if isinstance(v, (int, float, np.floating)) and not np.isnan(v) else str(v) for v in val]


rows = []
names = list(results.keys())
cols = ["metric"] + names

# Baseline
rows.append(["── Baseline (원본 시퀀스) ──"] + ["" for _ in names])
rows.append(summary_row("trades",        [results[n]["base"]["n"] for n in names], "{:.0f}"))
rows.append(summary_row("win_pct",       [results[n]["base"]["winrate_pct"] for n in names], "{:.2f}%"))
rows.append(summary_row("avg_R",         [results[n]["base"]["avg_R"] for n in names], "{:.3f}"))
rows.append(summary_row("MDD%",          [results[n]["base"]["mdd_pct"] for n in names], "{:.2f}"))
rows.append(summary_row("Final $",       [results[n]["base"]["final_usd"] for n in names], "${:,.0f}"))
rows.append(summary_row("퇴사 (개월)",     [results[n]["base"]["reach_month"] for n in names], "{:.0f}"))
rows.append(summary_row("max streak",    [results[n]["base"]["max_loss_streak"] for n in names], "{:.0f}"))

# Shuffle
rows.append(["── Shuffle (5,000 paths) ──"] + ["" for _ in names])
rows.append(summary_row("MDD 5%",        [pct(results[n]["shuffle"]["mdd"], 5)  for n in names]))
rows.append(summary_row("MDD median",    [pct(results[n]["shuffle"]["mdd"], 50) for n in names]))
rows.append(summary_row("MDD 95%",       [pct(results[n]["shuffle"]["mdd"], 95) for n in names]))
rows.append(summary_row("MDD worst",     [float(np.nanmin(results[n]["shuffle"]["mdd"])) for n in names]))
rows.append(summary_row("퇴사 5% (개월)",  [pct(results[n]["shuffle"]["reach_m"], 5)  for n in names], "{:.1f}"))
rows.append(summary_row("퇴사 median",    [pct(results[n]["shuffle"]["reach_m"], 50) for n in names], "{:.1f}"))
rows.append(summary_row("퇴사 95%",       [pct(results[n]["shuffle"]["reach_m"], 95) for n in names], "{:.1f}"))
rows.append(summary_row("미달성률",       [results[n]["shuffle"]["miss_rate"] for n in names], "{:.2f}%"))
rows.append(summary_row("streak median", [pct(results[n]["shuffle"]["streak"].astype(float), 50) for n in names], "{:.0f}"))
rows.append(summary_row("streak 95%",    [pct(results[n]["shuffle"]["streak"].astype(float), 95) for n in names], "{:.0f}"))
rows.append(summary_row("streak max",    [int(results[n]["shuffle"]["streak"].max()) for n in names], "{:.0f}"))

# Resample
rows.append(["── Resample (replacement) ──"] + ["" for _ in names])
rows.append(summary_row("Final $ 5%",    [pct(results[n]["resample"]["final"], 5)  for n in names], "${:,.0f}"))
rows.append(summary_row("Final $ median",[pct(results[n]["resample"]["final"], 50) for n in names], "${:,.0f}"))
rows.append(summary_row("Final $ 95%",   [pct(results[n]["resample"]["final"], 95) for n in names], "${:,.0f}"))
rows.append(summary_row("MDD median",    [pct(results[n]["resample"]["mdd"], 50)   for n in names]))
rows.append(summary_row("MDD 5%",        [pct(results[n]["resample"]["mdd"], 5)    for n in names]))
rows.append(summary_row("미달성률",       [results[n]["resample"]["miss_rate"] for n in names], "{:.2f}%"))

cmp_df = pd.DataFrame(rows, columns=cols)
cmp_df.to_csv(OUT / "10_mc_compare_AM10_vs_AM40.csv", index=False, encoding="utf-8")
print("\n[Compare]")
print(cmp_df.to_string(index=False))

# ── 그래프: fan chart 2개 나란히 ──
print("\nPlotting…")
fig, axes = plt.subplots(1, 2, figsize=(16, 6.5), sharey=True)
for ax, name in zip(axes, names):
    eq = results[name]["shuffle"]["equity_paths"]
    n_tr = eq.shape[1]
    x = np.arange(n_tr)
    pcts = np.percentile(eq, [5, 25, 50, 75, 95], axis=0)
    ax.fill_between(x, pcts[0], pcts[4], color="tab:orange", alpha=0.18, label="5–95%")
    ax.fill_between(x, pcts[1], pcts[3], color="tab:orange", alpha=0.35, label="25–75%")
    ax.plot(x, pcts[2], color="tab:orange", lw=1.5, label="median")
    # Baseline equity
    trades = load_trades(SCENARIOS[name])
    base_returns = np.maximum(
        1.0 + trades["risk_pct_requested"].values * trades["r_multiple"].values, 1e-3)
    base_eq = INITIAL_USD * np.cumprod(base_returns)
    ax.plot(x, base_eq, "k-", lw=1.5, label="Baseline")
    ax.axhline(TARGET_USD, color="red", ls="--", alpha=0.5, label=f"target ${TARGET_USD:,.0f}")
    ax.set_yscale("log")
    ax.set_xlabel("Trade index")
    ax.set_title(f"{name}\nbaseline final=${results[name]['base']['final_usd']:,.0f}, "
                 f"MDD={results[name]['base']['mdd_pct']:.2f}%")
    ax.grid(alpha=0.3, which="both")
    ax.legend(loc="upper left", fontsize=8)
axes[0].set_ylabel("Equity (USD, log)")
fig.suptitle("Monte Carlo fan charts — AM=1.0 vs AM=4.0 (shuffle)", fontsize=13)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_compare_fan.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_compare_fan.png")

# MDD histogram overlay
fig, ax = plt.subplots(figsize=(11, 5))
colors = {"AM=4.0 (FINAL)": "tab:blue", "AM=1.0 (ablation)": "tab:red"}
for name in names:
    arr = results[name]["shuffle"]["mdd"]
    ax.hist(arr, bins=60, alpha=0.5, color=colors[name], label=f"{name} (median {np.median(arr):.2f}%)")
ax.set_xlabel("MDD %")
ax.set_ylabel("count (paths)")
ax.set_title("MDD distribution — AM=1.0 vs AM=4.0 (Shuffle 5,000 paths)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_compare_mdd.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_compare_mdd.png")

# Final $ histogram (Resample)
fig, ax = plt.subplots(figsize=(11, 5))
for name in names:
    arr = results[name]["resample"]["final"]
    ax.hist(np.log10(np.maximum(arr, 1.0)), bins=70, alpha=0.5, color=colors[name],
            label=f"{name} (median log10=${np.log10(np.median(arr)):.2f} → ${np.median(arr):,.0f})")
ax.set_xlabel("log10(Final $)")
ax.set_ylabel("count (paths)")
ax.set_title("Final $ distribution (Resample, 5,000 paths)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_compare_final.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_compare_final.png")

print(f"\n=== Done ===\n산출물:")
for f in sorted(OUT.glob("10_mc*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
for f in sorted(OUT.glob("fig_mc_compare_*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
