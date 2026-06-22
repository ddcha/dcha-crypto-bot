r"""
Realistic Monte Carlo v3 — 정확한 백테스트 로직 매칭
=======================================================
v2의 두 가지 핵심 오류 정정:
  ① effective_return = (1 + risk_pct × r_multiple) → net_pnl / balance_at_entry
     (수수료/슬리피지 자동 반영)
  ② 출금 = 매월 $7,407 → balance cap $368,991 (excess 출금)
     백테스트 cap_and_extract_excess() 로직 매칭

검증: baseline 시뮬 → 백테스트 trading equity 곡선과 정확 매칭
  목표: MDD = -15.55%, final_equity = $370K, cum_excess ≈ $2.12M

shuffle/resample MC: trade outcome (effective_return) 만 셔플, 시간/입금/cap 보존.
"""
from __future__ import annotations
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
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

# === 백테스트 코드와 정확히 동일 ===
INITIAL_KRW          = 3_000_000
MONTHLY_DEPOSIT_KRW  = 2_000_000
NUM_DEPOSITS         = 5
KRW_PER_USDT         = 1350.0
MONTHLY_TARGET_KRW   = 10_000_000
TARGET_BALANCE_USDT  = 368_991.0          # ★ Phase A→B cap. excess 출금.

INITIAL_USD          = INITIAL_KRW / KRW_PER_USDT          # $2,222.22
MONTHLY_DEPOSIT_USD  = MONTHLY_DEPOSIT_KRW / KRW_PER_USDT  # $1,481.48
MONTHLY_TARGET_USD   = MONTHLY_TARGET_KRW / KRW_PER_USDT   # $7,407.41

N_SIMS = 5000


def load_trades(fp: Path):
    t = pd.read_csv(fp, usecols=["entry_time","r_multiple","risk_pct_requested",
                                  "net_pnl","month","balance_at_entry"])
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    t = t.sort_values("entry_time").reset_index(drop=True)
    return t


def build_static(trades: pd.DataFrame):
    n = len(trades)
    # ★ 정확한 effective return: net_pnl / balance_at_entry (수수료 포함)
    bae = trades["balance_at_entry"].values.astype(np.float64)
    npn = trades["net_pnl"].values.astype(np.float64)
    bae_safe = np.maximum(bae, 1.0)  # 0 division 방지
    trade_returns = 1.0 + (npn / bae_safe)
    trade_returns = np.maximum(trade_returns, 1e-3)  # cap

    # Deposit schedule
    first_t = trades["entry_time"].iloc[0]
    fm_start = pd.Timestamp(year=first_t.year, month=first_t.month, day=1, tz="UTC")
    deposit_dates = [fm_start + pd.offsets.MonthBegin(i) for i in range(1, NUM_DEPOSITS+1)]
    deposit_cum = np.zeros(n, dtype=np.float64)
    cum = 0.0
    di = 0
    for i, t in enumerate(trades["entry_time"]):
        while di < NUM_DEPOSITS and deposit_dates[di] <= t:
            cum += MONTHLY_DEPOSIT_USD
            di += 1
        deposit_cum[i] = cum
    deposit_inject = np.diff(np.concatenate([[0.0], deposit_cum]))

    # Month indexing
    unique_months = sorted(pd.unique(trades["month"]).tolist())
    m2n = {m: i for i, m in enumerate(unique_months)}
    trade_month_num = np.array([m2n[m] for m in trades["month"]], dtype=np.int32)

    return {
        "trade_returns": trade_returns,
        "deposit_inject": deposit_inject,
        "trade_month_num": trade_month_num,
        "n_months": len(unique_months),
        "unique_months": unique_months,
    }


def simulate_one(returns_seq, deposit_inject, trade_month_num, n_months):
    """단일 path. cap + retirement tracking."""
    n = len(returns_seq)
    balance = INITIAL_USD
    equity_history = np.empty(n, dtype=np.float64)
    total_assets_history = np.empty(n, dtype=np.float64)
    monthly_net_pnl = np.zeros(n_months, dtype=np.float64)
    cum_excess = 0.0
    retired_month = -1

    for i in range(n):
        balance += deposit_inject[i]
        balance_pre = balance
        balance *= returns_seq[i]
        pnl = balance - balance_pre
        m = trade_month_num[i]
        monthly_net_pnl[m] += pnl

        # ★ cap 로직: balance ≥ $368,991 시 excess 자동 출금
        if balance > TARGET_BALANCE_USDT:
            excess = balance - TARGET_BALANCE_USDT
            balance = TARGET_BALANCE_USDT
            cum_excess += excess

        # Retirement check (monitoring only — 출금에는 영향 없음)
        is_month_end = (i == n - 1) or (trade_month_num[i+1] != m)
        if is_month_end and retired_month < 0 and m >= 2:
            r3 = (monthly_net_pnl[m-2] + monthly_net_pnl[m-1] + monthly_net_pnl[m]) / 3.0
            if r3 >= MONTHLY_TARGET_USD:
                retired_month = m

        equity_history[i] = balance
        total_assets_history[i] = balance + cum_excess

    return equity_history, total_assets_history, retired_month, cum_excess


def path_metrics_trading(equity_history):
    cm = np.maximum.accumulate(equity_history)
    dd = (equity_history - cm) / cm * 100.0
    return float(dd.min()), float(equity_history[-1])


def path_metrics_total(total_history):
    cm = np.maximum.accumulate(total_history)
    dd = (total_history - cm) / cm * 100.0
    return float(dd.min()), float(total_history[-1])


# ── multi-process ──
_STATIC = None


def _init_worker(tr, dep, tmn, nm):
    global _STATIC
    _STATIC = (tr, dep, tmn, nm)


def _run_chunk(args):
    chunk_id, n_paths, seed_base, mode = args
    tr, dep, tmn, nm = _STATIC
    n = len(tr)
    rng = np.random.default_rng(seed_base + chunk_id)
    out_trading_mdd = np.empty(n_paths)
    out_total_mdd = np.empty(n_paths)
    out_trading_fin = np.empty(n_paths)
    out_total_fin = np.empty(n_paths)
    out_cum_excess = np.empty(n_paths)
    out_retm = np.empty(n_paths, dtype=np.int32)
    for k in range(n_paths):
        if mode == "shuffle":
            ret_seq = tr[rng.permutation(n)]
        else:
            ret_seq = tr[rng.integers(0, n, size=n)]
        eq, ta, rm, cex = simulate_one(ret_seq, dep, tmn, nm)
        m1, f1 = path_metrics_trading(eq)
        m2, f2 = path_metrics_total(ta)
        out_trading_mdd[k] = m1
        out_total_mdd[k] = m2
        out_trading_fin[k] = f1
        out_total_fin[k] = f2
        out_cum_excess[k] = cex
        out_retm[k] = rm
    return chunk_id, out_trading_mdd, out_total_mdd, out_trading_fin, out_total_fin, out_cum_excess, out_retm


def run_mc(static, n_sims: int, mode: str, seed_base: int = 1234):
    import os
    n_workers = min(12, os.cpu_count() or 4)
    chunk_size = max(1, n_sims // n_workers)
    chunks, remaining, cid = [], n_sims, 0
    while remaining > 0:
        take = min(chunk_size, remaining)
        chunks.append((cid, take, seed_base, mode))
        cid += 1
        remaining -= take

    print(f"  {mode}: {n_workers} workers × {len(chunks)} chunks")
    results = {k: [] for k in ("tmdd","tomdd","tfin","tofin","cex","rm")}
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_worker,
        initargs=(static["trade_returns"], static["deposit_inject"],
                  static["trade_month_num"], static["n_months"]),
    ) as ex:
        futs = [ex.submit(_run_chunk, c) for c in chunks]
        for f in as_completed(futs):
            _, tmdd, tomdd, tfin, tofin, cex, rm = f.result()
            results["tmdd"].append(tmdd); results["tomdd"].append(tomdd)
            results["tfin"].append(tfin); results["tofin"].append(tofin)
            results["cex"].append(cex);   results["rm"].append(rm)
    for k in results: results[k] = np.concatenate(results[k])
    return results


def main():
    OUT.mkdir(exist_ok=True)
    TRADES_FP = ROOT / "stage4l_FINAL_through_may" / "stage4l_boost15_out_skip_trades.csv"
    print(f"[1/4] Loading {TRADES_FP.name}…")
    trades = load_trades(TRADES_FP)
    static = build_static(trades)
    print(f"   {len(trades)} trades, {static['n_months']} months")
    print(f"   trade_returns range: [{static['trade_returns'].min():.4f}, "
          f"{static['trade_returns'].max():.4f}]")
    print(f"   cap (Phase A→B): ${TARGET_BALANCE_USDT:,.0f}")

    # Baseline
    print("\n[2/4] Baseline 시뮬레이션 (백테스트 매칭 검증)…")
    eq, ta, rm, cex = simulate_one(static["trade_returns"], static["deposit_inject"],
                                    static["trade_month_num"], static["n_months"])
    tmdd, tfin = path_metrics_trading(eq)
    tomdd, tofin = path_metrics_total(ta)
    print(f"   Trading equity:")
    print(f"     final:    ${tfin:,.0f}  (백테스트 $370,648)")
    print(f"     MDD:      {tmdd:.2f}%  (백테스트 -15.55%)")
    print(f"   Total assets (equity + cum_excess):")
    print(f"     final:    ${tofin:,.0f}  (백테스트 $2,491,852)")
    print(f"     MDD:      {tomdd:.2f}%  (백테스트 -11.16%)")
    print(f"   Cum excess:  ${cex:,.0f}  (백테스트 $2,121,204)")
    rmname = static["unique_months"][rm] if rm >= 0 else "미달성"
    print(f"   Retirement:  {rmname} ({rm+1 if rm >= 0 else 'X'}개월차)  (백테스트 2024-01 / 7개월)")

    # MC
    print(f"\n[3/4] Monte Carlo {N_SIMS:,} paths…")
    print("  (A) Shuffle…")
    res_A = run_mc(static, N_SIMS, "shuffle", seed_base=42)
    print("  (B) Resample…")
    res_B = run_mc(static, N_SIMS, "resample", seed_base=42 + 99999)

    # ── Summary ──
    def pct(a, p):
        return float(np.percentile(a, p)) if len(a) else np.nan

    def pct_valid(a, p):
        v = a[a >= 0]
        return float(np.percentile(v, p)) if len(v) else np.nan

    rows = [["── Baseline (실제 시퀀스) ──", "", "", ""]]
    rows.append(["Trading MDD %",          f"{tmdd:.2f}", "", ""])
    rows.append(["Trading equity final",   f"${tfin:,.0f}", "", ""])
    rows.append(["Total MDD %",            f"{tomdd:.2f}", "", ""])
    rows.append(["Total assets final",     f"${tofin:,.0f}", "", ""])
    rows.append(["cum_excess (출금)",        f"${cex:,.0f}", "", ""])
    rows.append(["퇴사 개월",                 f"{rm+1}" if rm >= 0 else "미달성", "", ""])

    for label, res in [("Shuffle", res_A), ("Resample", res_B)]:
        rows.append([f"── {label} ({N_SIMS:,} paths) ──", "", "", ""])
        rows.append(["Trading MDD %",       f"{pct(res['tmdd'],5):.2f}",  f"{pct(res['tmdd'],50):.2f}",  f"{pct(res['tmdd'],95):.2f}"])
        rows.append(["Trading MDD worst",   f"{res['tmdd'].min():.2f}", "", ""])
        rows.append(["Total MDD %",         f"{pct(res['tomdd'],5):.2f}", f"{pct(res['tomdd'],50):.2f}", f"{pct(res['tomdd'],95):.2f}"])
        rows.append(["Total assets 5%/med/95%",
                     f"${pct(res['tofin'],5):,.0f}", f"${pct(res['tofin'],50):,.0f}", f"${pct(res['tofin'],95):,.0f}"])
        rows.append(["Cum excess 5%/med/95%",
                     f"${pct(res['cex'],5):,.0f}", f"${pct(res['cex'],50):,.0f}", f"${pct(res['cex'],95):,.0f}"])
        rm_lbl = np.where(res['rm'] >= 0, res['rm'] + 1, -1)
        rows.append(["퇴사 개월 5/50/95",
                     f"{pct_valid(rm_lbl,5):.1f}", f"{pct_valid(rm_lbl,50):.1f}", f"{pct_valid(rm_lbl,95):.1f}"])
        rows.append(["퇴사 미달성률",
                     f"{np.mean(res['rm'] < 0)*100:.2f}%", "", ""])

    summary_df = pd.DataFrame(rows, columns=["metric","5% / value","median","95%"])
    summary_df.to_csv(OUT / "12_mc_v3_summary.csv", index=False, encoding="utf-8")
    print("\n" + summary_df.to_string(index=False))

    # ── 그래프 ──
    print("\n[4/4] Plotting…")
    # MDD histogram (Trading equity)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(res_A["tmdd"], bins=60, alpha=0.6, color="tab:blue", label=f"Shuffle (median {np.median(res_A['tmdd']):.2f}%)")
    ax.hist(res_B["tmdd"], bins=60, alpha=0.4, color="tab:red",  label=f"Resample (median {np.median(res_B['tmdd']):.2f}%)")
    ax.axvline(tmdd, color="black", lw=2, ls="--", label=f"Baseline {tmdd:.2f}%")
    ax.axvline(-15.55, color="green", lw=1.5, ls=":", label="백테스트 -15.55%")
    for p, c in [(5, "tab:purple"), (50, "tab:cyan"), (95, "tab:olive")]:
        v = np.percentile(res_A["tmdd"], p)
        ax.axvline(v, color=c, lw=1, alpha=0.6, label=f"Shuffle {p}%: {v:.2f}%")
    ax.set_xlabel("Trading equity MDD %")
    ax.set_ylabel("count (paths)")
    ax.set_title("Realistic MC v3 — Trading equity MDD (입금/cap 출금 모델링)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_trading_mdd.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_trading_mdd.png")

    # Total MDD
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(res_A["tomdd"], bins=60, alpha=0.6, color="tab:blue", label="Shuffle")
    ax.hist(res_B["tomdd"], bins=60, alpha=0.4, color="tab:red", label="Resample")
    ax.axvline(tomdd, color="black", lw=2, ls="--", label=f"Baseline {tomdd:.2f}%")
    ax.axvline(-11.16, color="green", lw=1.5, ls=":", label="백테스트 -11.16%")
    ax.set_xlabel("Total assets MDD % (equity + cum_excess)")
    ax.set_ylabel("count (paths)")
    ax.set_title("Realistic MC v3 — Total assets MDD")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_total_mdd.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_total_mdd.png")

    # Total assets histogram
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(np.log10(np.maximum(res_A["tofin"], 1)), bins=60, alpha=0.6, color="tab:blue", label="Shuffle")
    ax.hist(np.log10(np.maximum(res_B["tofin"], 1)), bins=60, alpha=0.4, color="tab:red", label="Resample")
    ax.axvline(np.log10(tofin), color="black", lw=2, ls="--", label=f"Baseline ${tofin:,.0f}")
    ax.set_xlabel("log10(Total assets final $)")
    ax.set_ylabel("count")
    ax.set_title("Total assets distribution")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_total_assets.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_total_assets.png")

    # 퇴사 시점
    fig, ax = plt.subplots(figsize=(11, 5))
    rm_A = np.where(res_A["rm"] >= 0, res_A["rm"] + 1, -1)
    rm_B = np.where(res_B["rm"] >= 0, res_B["rm"] + 1, -1)
    rm_A_v = rm_A[rm_A >= 0]; rm_B_v = rm_B[rm_B >= 0]
    bins = np.arange(0, static["n_months"] + 2)
    ax.hist(rm_A_v, bins=bins, alpha=0.6, color="tab:blue",
            label=f"Shuffle (미달성 {np.mean(rm_A < 0)*100:.2f}%)")
    ax.hist(rm_B_v, bins=bins, alpha=0.4, color="tab:red",
            label=f"Resample (미달성 {np.mean(rm_B < 0)*100:.2f}%)")
    if rm >= 0:
        ax.axvline(rm + 1, color="black", lw=2, ls="--", label=f"Baseline {rm + 1}개월")
    ax.set_xlabel("Retirement 개월")
    ax.set_ylabel("count")
    ax.set_title("Retirement 시점 분포 (rolling 3m monthly KRW ≥ 1000만원)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_retire.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_retire.png")

    print("\n=== Done ===")
    for f in sorted(OUT.glob("12_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
    for f in sorted(OUT.glob("fig_mc_v3_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
