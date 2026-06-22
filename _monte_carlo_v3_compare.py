r"""
Monte Carlo v3 비교 — FINAL (REVIVE ON) vs Conservative (REVIVE OFF)
======================================================================
두 시나리오 같은 v3 cap 모델로 5,000 path 시뮬:
  ① FINAL_through_may       : ALPHA_MAX=4.0, REVIVE_CUTS=ON
  ② Conservative_AM40_15m   : ALPHA_MAX=4.0, REVIVE_CUTS=OFF
            (원본 v3_conservative_mtf_fill.py + AM=4.0 only)
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

INITIAL_KRW          = 3_000_000
MONTHLY_DEPOSIT_KRW  = 2_000_000
NUM_DEPOSITS         = 5
KRW_PER_USDT         = 1350.0
MONTHLY_TARGET_KRW   = 10_000_000
TARGET_BALANCE_USDT  = 368_991.0

INITIAL_USD          = INITIAL_KRW / KRW_PER_USDT
MONTHLY_DEPOSIT_USD  = MONTHLY_DEPOSIT_KRW / KRW_PER_USDT
MONTHLY_TARGET_USD   = MONTHLY_TARGET_KRW / KRW_PER_USDT

N_SIMS = 5000

SCENARIOS = {
    "FINAL (REVIVE_ON)":   ROOT / "stage4l_FINAL_through_may" / "stage4l_boost15_out_skip_trades.csv",
    "Conservative (OFF)":  ROOT / "stage4l_conservative_AM40_15m" / "stage4l_boost15_out_skip_trades.csv",
}


def load_trades(fp):
    t = pd.read_csv(fp, usecols=["entry_time","r_multiple","risk_pct_requested",
                                  "net_pnl","month","balance_at_entry"])
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    return t.sort_values("entry_time").reset_index(drop=True)


def build_static(trades):
    n = len(trades)
    bae = np.maximum(trades["balance_at_entry"].values.astype(np.float64), 1.0)
    npn = trades["net_pnl"].values.astype(np.float64)
    trade_returns = np.maximum(1.0 + npn / bae, 1e-3)

    first_t = trades["entry_time"].iloc[0]
    fm = pd.Timestamp(year=first_t.year, month=first_t.month, day=1, tz="UTC")
    ddates = [fm + pd.offsets.MonthBegin(i) for i in range(1, NUM_DEPOSITS+1)]
    deposit_cum = np.zeros(n)
    cum, di = 0.0, 0
    for i, t in enumerate(trades["entry_time"]):
        while di < NUM_DEPOSITS and ddates[di] <= t:
            cum += MONTHLY_DEPOSIT_USD; di += 1
        deposit_cum[i] = cum
    deposit_inject = np.diff(np.concatenate([[0.0], deposit_cum]))

    um = sorted(pd.unique(trades["month"]).tolist())
    m2n = {m: i for i, m in enumerate(um)}
    tmn = np.array([m2n[m] for m in trades["month"]], dtype=np.int32)

    return {"trade_returns": trade_returns, "deposit_inject": deposit_inject,
            "trade_month_num": tmn, "n_months": len(um), "unique_months": um}


def simulate_one(returns_seq, deposit_inject, trade_month_num, n_months):
    n = len(returns_seq)
    balance = INITIAL_USD
    eq = np.empty(n); ta = np.empty(n)
    mpnl = np.zeros(n_months)
    cex = 0.0; rm = -1
    for i in range(n):
        balance += deposit_inject[i]
        pre = balance
        balance *= returns_seq[i]
        mpnl[trade_month_num[i]] += balance - pre
        if balance > TARGET_BALANCE_USDT:
            cex += balance - TARGET_BALANCE_USDT
            balance = TARGET_BALANCE_USDT
        m = trade_month_num[i]
        is_me = (i == n-1) or (trade_month_num[i+1] != m)
        if is_me and rm < 0 and m >= 2:
            r3 = (mpnl[m-2] + mpnl[m-1] + mpnl[m]) / 3.0
            if r3 >= MONTHLY_TARGET_USD: rm = m
        eq[i] = balance
        ta[i] = balance + cex
    return eq, ta, rm, cex


def mdd(arr):
    cm = np.maximum.accumulate(arr)
    return float(((arr - cm) / cm * 100).min())


# multi-process
_STATIC = None
def _init(tr, dep, tmn, nm):
    global _STATIC
    _STATIC = (tr, dep, tmn, nm)


def _chunk(args):
    cid, n_paths, seed_base, mode = args
    tr, dep, tmn, nm = _STATIC
    n = len(tr)
    rng = np.random.default_rng(seed_base + cid)
    tmdd = np.empty(n_paths); tomdd = np.empty(n_paths)
    tfin = np.empty(n_paths); tofin = np.empty(n_paths)
    cex = np.empty(n_paths); retm = np.empty(n_paths, dtype=np.int32)
    for k in range(n_paths):
        if mode == "shuffle":
            seq = tr[rng.permutation(n)]
        else:
            seq = tr[rng.integers(0, n, size=n)]
        eq, ta, rm, ce = simulate_one(seq, dep, tmn, nm)
        tmdd[k] = mdd(eq); tomdd[k] = mdd(ta)
        tfin[k] = eq[-1]; tofin[k] = ta[-1]
        cex[k] = ce; retm[k] = rm
    return tmdd, tomdd, tfin, tofin, cex, retm


def run_mc(static, n_sims, mode, seed_base=1234):
    import os
    nw = min(12, os.cpu_count() or 4)
    cs = max(1, n_sims // nw)
    chunks, rem, cid = [], n_sims, 0
    while rem > 0:
        take = min(cs, rem)
        chunks.append((cid, take, seed_base, mode))
        cid += 1; rem -= take
    out = {k: [] for k in ("tmdd","tomdd","tfin","tofin","cex","retm")}
    with ProcessPoolExecutor(
        max_workers=nw, initializer=_init,
        initargs=(static["trade_returns"], static["deposit_inject"],
                  static["trade_month_num"], static["n_months"])) as ex:
        futs = [ex.submit(_chunk, c) for c in chunks]
        for f in as_completed(futs):
            tmdd, tomdd, tfin, tofin, cex, retm = f.result()
            out["tmdd"].append(tmdd); out["tomdd"].append(tomdd)
            out["tfin"].append(tfin); out["tofin"].append(tofin)
            out["cex"].append(cex); out["retm"].append(retm)
    return {k: np.concatenate(v) for k, v in out.items()}


def main():
    OUT.mkdir(exist_ok=True)
    results = {}
    for name, fp in SCENARIOS.items():
        print(f"\n=== {name} ({fp.parent.name}) ===")
        trades = load_trades(fp)
        st = build_static(trades)
        print(f"   {len(trades)} trades, {st['n_months']} months")

        # Baseline
        eq, ta, rm, cex = simulate_one(st["trade_returns"], st["deposit_inject"],
                                        st["trade_month_num"], st["n_months"])
        base = {
            "trading_final": eq[-1], "trading_mdd": mdd(eq),
            "total_final": ta[-1], "total_mdd": mdd(ta),
            "cum_excess": cex,
            "retire_month": (st["unique_months"][rm], rm + 1) if rm >= 0 else (None, -1),
        }
        print(f"   Baseline: trading ${eq[-1]:,.0f}, MDD {mdd(eq):.2f}%")
        print(f"             total    ${ta[-1]:,.0f}, MDD {mdd(ta):.2f}%, excess ${cex:,.0f}")
        if rm >= 0:
            print(f"             retire: {st['unique_months'][rm]} ({rm+1}개월)")

        # MC
        print(f"   Running MC {N_SIMS:,} × shuffle + resample…")
        res_A = run_mc(st, N_SIMS, "shuffle", seed_base=42)
        res_B = run_mc(st, N_SIMS, "resample", seed_base=99999)

        results[name] = {"base": base, "shuffle": res_A, "resample": res_B, "static": st}

    # ── Comparison table ──
    print("\n\n=== Comparison ===")
    names = list(results.keys())
    rows = []
    def add(label, fn, fmt="{:.2f}"):
        cells = [label]
        for n in names:
            v = fn(results[n])
            try:
                cells.append(fmt.format(v) if not isinstance(v, str) else v)
            except Exception:
                cells.append(str(v))
        rows.append(cells)

    rows.append(["── Baseline ──"] + ["" for _ in names])
    add("Trading equity final", lambda r: r["base"]["trading_final"], "${:,.0f}")
    add("Trading MDD %",        lambda r: r["base"]["trading_mdd"], "{:.2f}%")
    add("Total assets final",   lambda r: r["base"]["total_final"], "${:,.0f}")
    add("Total MDD %",          lambda r: r["base"]["total_mdd"], "{:.2f}%")
    add("Cum excess",           lambda r: r["base"]["cum_excess"], "${:,.0f}")
    add("Retire (개월)",          lambda r: r["base"]["retire_month"][1] if r["base"]["retire_month"][1] >= 0 else "X", "{}")

    rows.append(["── Shuffle 5,000 ──"] + ["" for _ in names])
    for p in [5, 50, 95]:
        add(f"Trading MDD {p}%",   lambda r, p=p: np.percentile(r["shuffle"]["tmdd"], p), "{:.2f}%")
    add("Trading MDD worst",       lambda r: r["shuffle"]["tmdd"].min(), "{:.2f}%")
    for p in [5, 50, 95]:
        add(f"Total MDD {p}%",     lambda r, p=p: np.percentile(r["shuffle"]["tomdd"], p), "{:.2f}%")
    for p in [5, 50, 95]:
        add(f"Total final {p}%",   lambda r, p=p: np.percentile(r["shuffle"]["tofin"], p), "${:,.0f}")
    for p in [5, 50, 95]:
        add(f"Retire {p}% (개월)",  lambda r, p=p: np.percentile(r["shuffle"]["retm"][r["shuffle"]["retm"] >= 0] + 1, p), "{:.1f}")
    add("Retire 미달성률",          lambda r: np.mean(r["shuffle"]["retm"] < 0) * 100, "{:.2f}%")

    rows.append(["── Resample 5,000 ──"] + ["" for _ in names])
    for p in [5, 50, 95]:
        add(f"Trading MDD {p}%",   lambda r, p=p: np.percentile(r["resample"]["tmdd"], p), "{:.2f}%")
    add("Trading MDD worst",       lambda r: r["resample"]["tmdd"].min(), "{:.2f}%")
    for p in [5, 50, 95]:
        add(f"Total MDD {p}%",     lambda r, p=p: np.percentile(r["resample"]["tomdd"], p), "{:.2f}%")
    for p in [5, 50, 95]:
        add(f"Total final {p}%",   lambda r, p=p: np.percentile(r["resample"]["tofin"], p), "${:,.0f}")
    add("Retire 미달성률",          lambda r: np.mean(r["resample"]["retm"] < 0) * 100, "{:.2f}%")

    cmp_df = pd.DataFrame(rows, columns=["metric"] + names)
    cmp_df.to_csv(OUT / "13_mc_v3_compare_FINAL_vs_Conservative.csv",
                   index=False, encoding="utf-8")
    print(cmp_df.to_string(index=False))

    # ── Plots ──
    print("\nPlotting…")
    colors = {names[0]: "tab:blue", names[1]: "tab:red"}

    # MDD histogram (trading)
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in names:
        a = results[n]["shuffle"]["tmdd"]
        ax.hist(a, bins=60, alpha=0.5, color=colors[n],
                label=f"{n} (median {np.median(a):.2f}%)")
        ax.axvline(results[n]["base"]["trading_mdd"], color=colors[n], ls="--", lw=1.5,
                   label=f"{n} baseline {results[n]['base']['trading_mdd']:.2f}%")
    ax.set_xlabel("Trading equity MDD %")
    ax.set_ylabel("count")
    ax.set_title("Trading MDD — FINAL vs Conservative (5,000 shuffle paths)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_cmp_trading_mdd.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_cmp_trading_mdd.png")

    # Total assets final
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in names:
        a = results[n]["shuffle"]["tofin"]
        ax.hist(a, bins=60, alpha=0.5, color=colors[n],
                label=f"{n} (median ${np.median(a):,.0f})")
        ax.axvline(results[n]["base"]["total_final"], color=colors[n], ls="--", lw=1.5,
                   label=f"{n} baseline ${results[n]['base']['total_final']:,.0f}")
    ax.set_xlabel("Total assets final $")
    ax.set_ylabel("count")
    ax.set_title("Total assets final — FINAL vs Conservative (5,000 shuffle paths)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_cmp_total_final.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_cmp_total_final.png")

    # Retire month
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in names:
        a = results[n]["shuffle"]["retm"]
        v = a[a >= 0] + 1
        ax.hist(v, bins=np.arange(0, results[n]["static"]["n_months"]+2),
                alpha=0.5, color=colors[n],
                label=f"{n} (median {np.median(v):.0f}m)")
    ax.set_xlabel("Retirement 개월")
    ax.set_ylabel("count")
    ax.set_title("Retirement timing — FINAL vs Conservative")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_v3_cmp_retire.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_v3_cmp_retire.png")

    print(f"\n산출물:")
    for f in sorted(OUT.glob("13_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
    for f in sorted(OUT.glob("fig_mc_v3_cmp_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
