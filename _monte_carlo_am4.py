r"""
Monte Carlo 5,000 시뮬레이션 — AM_4.0R / FINAL_through_may
==========================================================
1352 trades (2023-07 ~ 2026-05) 풀에서 두 방식으로 시뮬:
  (A) Trade-shuffle bootstrap  : 시퀀스 무작위 permutation
  (B) Resample with replacement: 1352 trades 풀에서 1352개 복원 추출

산출:
  09_mc_summary.csv          ── shuffle/resample percentile 비교
  09_mc_baseline.csv         ── 백테스트 원본 곡선 trade-by-trade
  fig_mc_fan.png             ── 자본 곡선 fan chart (median + 5/95 envelope)
  fig_mc_mdd_hist.png        ── MDD 분포 히스토그램
  fig_mc_retire_hist.png     ── 퇴사 시점 분포
  fig_mc_streak_hist.png     ── 연속 손실 trade 분포
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

# ── 1. 데이터 로드 ────────────────────────────────────────────────
TRADES_FP = ROOT / "stage4l_FINAL_through_may" / "stage4l_boost15_out_skip_trades.csv"
print(f"[1/5] Loading trades from {TRADES_FP.name}…")
trades = pd.read_csv(TRADES_FP,
                    usecols=["r_multiple", "risk_pct_requested",
                             "net_pnl", "month", "tier"])
print(f"   loaded {len(trades)} trades")
print(f"   r_multiple range: [{trades.r_multiple.min():.3f}, {trades.r_multiple.max():.3f}]")
print(f"   risk_pct range:  [{trades.risk_pct_requested.min():.4f}, {trades.risk_pct_requested.max():.4f}]")
print(f"   tier counts: {trades.tier.value_counts().to_dict()}")

r_arr = trades["r_multiple"].values.astype(np.float64)
p_arr = trades["risk_pct_requested"].values.astype(np.float64)
n_trades = len(r_arr)

# 단일 trade 기하 수익률 (1 + p*r). 자본 음수 방지 cap
trade_returns = np.maximum(1.0 + p_arr * r_arr, 1e-3)

# ── 2. 설정 ──────────────────────────────────────────────────────
N_SIMS = 5000
INITIAL_USD = 3_000_000 / 1350.0   # = $2222.22
TARGET_USD = 10_000_000 / 1350.0 * 3   # rolling_3m 1000만원 = 33.4억 KRW peak ≈ 환산 $7407.41 X 3...
# 실제로는 백테스트의 peak가 $2.47M이고 그게 RETIREMENT_MONTHLY_TARGET 충족 시점.
# 단순화: equity가 baseline peak의 90%에 도달한 trade index를 "retirement"로 정의
# 또는 백테스트 같은 KRW target — 33.4억 = $2.47M
TARGET_USD = 2_470_000.0

rng = np.random.default_rng(42)

# ── 3. Baseline (원본 시퀀스) ─────────────────────────────────────
print(f"\n[2/5] Baseline cumulative equity (original sequence)…")
equity_base = INITIAL_USD * np.cumprod(trade_returns)
cummax_base = np.maximum.accumulate(equity_base)
dd_base = (equity_base - cummax_base) / cummax_base * 100.0
mdd_base = dd_base.min()
final_base = equity_base[-1]
reach_idx_base = int(np.argmax(equity_base >= TARGET_USD)) if (equity_base >= TARGET_USD).any() else -1
print(f"   final equity: ${final_base:,.0f}")
print(f"   MDD: {mdd_base:.2f}%  reach trade idx: {reach_idx_base}/{n_trades}")

# trade index → month 매핑 (퇴사 시점 환산)
trade_months = trades["month"].values
month_list = sorted(pd.unique(trade_months).tolist())
month_to_num = {m: i for i, m in enumerate(month_list)}    # 0-based
trade_month_num = np.array([month_to_num[m] for m in trade_months])
n_months_total = len(month_list)
print(f"   total months: {n_months_total}, first={month_list[0]}, last={month_list[-1]}")

if reach_idx_base >= 0:
    reach_month_base = trade_month_num[reach_idx_base] + 1
    print(f"   baseline retirement month: {month_list[trade_month_num[reach_idx_base]]} "
          f"= {reach_month_base}개월차")
else:
    reach_month_base = None

# Baseline 곡선 저장
pd.DataFrame({"trade_idx": np.arange(n_trades),
              "equity_usd": equity_base,
              "dd_pct": dd_base,
              "month": trade_months,
              "month_num": trade_month_num + 1}).to_csv(
    OUT / "09_mc_baseline.csv", index=False, float_format="%.4f")

# ── 4. Monte Carlo (병렬 vectorized) ─────────────────────────────
print(f"\n[3/5] Running {N_SIMS:,} simulations × {n_trades} trades…")

# (A) Shuffle: argsort(uniform random) trick = uniform permutation
print("   (A) Trade-shuffle…")
sort_key_A = rng.random((N_SIMS, n_trades))
perm_A = np.argsort(sort_key_A, axis=1)
returns_A = trade_returns[perm_A]   # (N_SIMS, n_trades)
equity_A = INITIAL_USD * np.cumprod(returns_A, axis=1)
del sort_key_A, perm_A

# (B) Resample with replacement
print("   (B) Resample with replacement…")
idx_B = rng.integers(0, n_trades, size=(N_SIMS, n_trades))
returns_B = trade_returns[idx_B]
equity_B = INITIAL_USD * np.cumprod(returns_B, axis=1)
del idx_B

print(f"   memory: equity_A ~{equity_A.nbytes/1e6:.0f}MB, equity_B ~{equity_B.nbytes/1e6:.0f}MB")

# ── 5. Path metrics ──────────────────────────────────────────────
print("\n[4/5] Computing path metrics…")

def path_metrics(equity_paths, returns):
    cummax = np.maximum.accumulate(equity_paths, axis=1)
    dd = (equity_paths - cummax) / cummax * 100.0
    mdd_paths = dd.min(axis=1)
    final_paths = equity_paths[:, -1]
    reached = equity_paths >= TARGET_USD
    has_reach = reached.any(axis=1)
    first_reach_idx = np.where(has_reach, reached.argmax(axis=1), -1)
    # Max consecutive losing streak per path
    loss = (returns < 1.0).astype(np.int8)
    # vectorized run-length: per row find max run of 1
    max_streaks = np.zeros(equity_paths.shape[0], dtype=np.int32)
    # Loop is fine for 5000 rows
    for i in range(equity_paths.shape[0]):
        x = loss[i]
        cnt = 0; best = 0
        for v in x:
            if v:
                cnt += 1
                if cnt > best: best = cnt
            else:
                cnt = 0
        max_streaks[i] = best
    return mdd_paths, final_paths, first_reach_idx, max_streaks


mdd_A, fin_A, reach_A, streak_A = path_metrics(equity_A, returns_A)
mdd_B, fin_B, reach_B, streak_B = path_metrics(equity_B, returns_B)
del returns_A, returns_B

# reach_idx → 개월
def idx_to_month(reach_idx_arr):
    out = np.full(reach_idx_arr.shape, np.nan)
    valid = reach_idx_arr >= 0
    if valid.any():
        out[valid] = trade_month_num[reach_idx_arr[valid]] + 1
    return out

reach_m_A = idx_to_month(reach_A)
reach_m_B = idx_to_month(reach_B)

# ── 6. 요약 통계 ─────────────────────────────────────────────────
def pct_row(arr, name, fmt="{:.2f}"):
    if np.all(np.isnan(arr)):
        return {"metric": name, "5%": "nan", "median": "nan", "95%": "nan",
                "min": "nan", "max": "nan", "mean": "nan"}
    pcts = np.nanpercentile(arr, [5, 50, 95])
    return {"metric": name,
            "5%": fmt.format(pcts[0]),
            "median": fmt.format(pcts[1]),
            "95%": fmt.format(pcts[2]),
            "min": fmt.format(np.nanmin(arr)),
            "max": fmt.format(np.nanmax(arr)),
            "mean": fmt.format(np.nanmean(arr))}

summary_rows = []
summary_rows.append({"metric": "—— Shuffle (A) ——",
                     "5%":"", "median":"", "95%":"", "min":"", "max":"", "mean":""})
summary_rows.append(pct_row(mdd_A, "MDD %", "{:.2f}"))
summary_rows.append(pct_row(fin_A, "Final $ (no deposit)", "{:,.0f}"))
summary_rows.append(pct_row(reach_m_A, "퇴사 (개월)", "{:.1f}"))
summary_rows.append(pct_row(streak_A.astype(float), "Max loss streak", "{:.0f}"))
summary_rows.append({"metric": f"미달성률(target ${TARGET_USD:,.0f})",
                     "5%":"", "median":f"{np.mean(reach_A<0)*100:.2f}%",
                     "95%":"", "min":"", "max":"", "mean":""})
summary_rows.append({"metric": "—— Resample (B) ——",
                     "5%":"", "median":"", "95%":"", "min":"", "max":"", "mean":""})
summary_rows.append(pct_row(mdd_B, "MDD %", "{:.2f}"))
summary_rows.append(pct_row(fin_B, "Final $ (no deposit)", "{:,.0f}"))
summary_rows.append(pct_row(reach_m_B, "퇴사 (개월)", "{:.1f}"))
summary_rows.append(pct_row(streak_B.astype(float), "Max loss streak", "{:.0f}"))
summary_rows.append({"metric": f"미달성률(target ${TARGET_USD:,.0f})",
                     "5%":"", "median":f"{np.mean(reach_B<0)*100:.2f}%",
                     "95%":"", "min":"", "max":"", "mean":""})
summary_rows.append({"metric": "—— Baseline (원본) ——",
                     "5%":"", "median":"", "95%":"", "min":"", "max":"", "mean":""})
summary_rows.append({"metric":"MDD %","5%":"","median":f"{mdd_base:.2f}",
                     "95%":"","min":"","max":"","mean":""})
summary_rows.append({"metric":"Final $","5%":"","median":f"{final_base:,.0f}",
                     "95%":"","min":"","max":"","mean":""})
summary_rows.append({"metric":"퇴사 (개월)","5%":"",
                     "median":str(reach_month_base) if reach_month_base else "X",
                     "95%":"","min":"","max":"","mean":""})

summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(OUT / "09_mc_summary.csv", index=False, encoding="utf-8")
print("\n[Summary]")
print(summary_df.to_string(index=False))

# ── 7. 그래프 ────────────────────────────────────────────────────
print("\n[5/5] Plotting…")

# Fan chart (Shuffle 만, log scale)
fig, ax = plt.subplots(figsize=(12, 6.5))
x = np.arange(n_trades)
pcts = np.percentile(equity_A, [5, 25, 50, 75, 95], axis=0)
ax.fill_between(x, pcts[0], pcts[4], color="tab:orange", alpha=0.18, label="5–95%")
ax.fill_between(x, pcts[1], pcts[3], color="tab:orange", alpha=0.35, label="25–75%")
ax.plot(x, pcts[2], color="tab:orange", lw=1.5, label="median")
ax.plot(x, equity_base, color="black", lw=1.5, label="Baseline (원본 시퀀스)")
ax.axhline(TARGET_USD, color="red", ls="--", alpha=0.5, label=f"퇴사 target ${TARGET_USD:,.0f}")
ax.set_yscale("log")
ax.set_xlabel("Trade index")
ax.set_ylabel("Equity (USD, log)")
ax.set_title(f"Monte Carlo fan chart — AM_4.0 / 5,000 shuffle paths")
ax.legend(loc="upper left")
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(OUT / "fig_mc_fan.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_fan.png")

# MDD histogram
fig, ax = plt.subplots(figsize=(11, 5))
ax.hist(mdd_A, bins=60, alpha=0.6, color="tab:blue", label="Shuffle")
ax.hist(mdd_B, bins=60, alpha=0.4, color="tab:red", label="Resample")
ax.axvline(mdd_base, color="black", lw=2, ls="--", label=f"Baseline {mdd_base:.2f}%")
ax.axvline(np.percentile(mdd_A, 5),  color="tab:blue", lw=1, ls=":",
           label=f"Shuffle 5%: {np.percentile(mdd_A,5):.2f}%")
ax.axvline(np.percentile(mdd_A, 50), color="tab:blue", lw=1.2, ls="-",
           label=f"Shuffle 50%: {np.percentile(mdd_A,50):.2f}%")
ax.set_xlabel("Max Drawdown %")
ax.set_ylabel("count (paths)")
ax.set_title("MDD distribution across 5,000 Monte Carlo paths")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_mdd_hist.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_mdd_hist.png")

# 퇴사 시점 histogram
fig, ax = plt.subplots(figsize=(11, 5))
m_A_valid = reach_m_A[~np.isnan(reach_m_A)]
m_B_valid = reach_m_B[~np.isnan(reach_m_B)]
bins = np.arange(0, n_months_total + 2)
ax.hist(m_A_valid, bins=bins, alpha=0.6, color="tab:blue",
        label=f"Shuffle (미달성 {np.mean(reach_A<0)*100:.1f}%)")
ax.hist(m_B_valid, bins=bins, alpha=0.4, color="tab:red",
        label=f"Resample (미달성 {np.mean(reach_B<0)*100:.1f}%)")
if reach_month_base:
    ax.axvline(reach_month_base, color="black", lw=2, ls="--",
               label=f"Baseline {reach_month_base}개월")
ax.set_xlabel(f"퇴사 도달 개월 (target ${TARGET_USD:,.0f})")
ax.set_ylabel("count (paths)")
ax.set_title("퇴사 시점 분포 — 5,000 Monte Carlo paths")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_retire_hist.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_retire_hist.png")

# Loss streak histogram
fig, ax = plt.subplots(figsize=(11, 5))
sa_max = int(max(streak_A.max(), streak_B.max()))
bins = np.arange(0, sa_max + 2)
ax.hist(streak_A, bins=bins, alpha=0.6, color="tab:blue", label="Shuffle")
ax.hist(streak_B, bins=bins, alpha=0.4, color="tab:red", label="Resample")
# Baseline streak
loss_base = (trade_returns < 1.0).astype(np.int8)
cnt = 0; best_base = 0
for v in loss_base:
    cnt = cnt + 1 if v else 0
    if cnt > best_base: best_base = cnt
ax.axvline(best_base, color="black", lw=2, ls="--", label=f"Baseline {best_base}건")
ax.set_xlabel("Max consecutive losing trades")
ax.set_ylabel("count (paths)")
ax.set_title("Max loss streak distribution — 5,000 paths")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_mc_streak_hist.png", dpi=140)
plt.close(fig)
print("   ✓ fig_mc_streak_hist.png")

print("\n=== Done ===")
print(f"산출물: {OUT}")
for f in sorted(OUT.glob("09_mc*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
for f in sorted(OUT.glob("fig_mc_*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
