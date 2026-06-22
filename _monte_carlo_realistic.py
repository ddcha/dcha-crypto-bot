r"""
Realistic Monte Carlo — 입금 5회 + retirement 후 매월 출금 모델링
=================================================================
이전 _monte_carlo_am4.py 의 문제:
  ① INITIAL=$2,222 만 사용 (월 입금 5회 무시)
  ② Retirement 후 매월 출금 무시
  ③ → trading equity가 실제보다 작게 시작 → MDD 과대 추정 (-31%)

이번 v2:
  ✓ INITIAL=$2,222 + 매월 1일 $1,481.48 입금 × 5회 = first 5 months
  ✓ Retirement (rolling 3m monthly PnL >= $7,407) 도달 후 매월 $7,407 출금
  ✓ Trade entry_time 보존 (캘린더 시점 deposit/withdraw 적용)
  ✓ Shuffle = trade 결과(r_multiple, risk_pct)만 셔플
  ✓ 결과: 백테스트 trading equity MDD -15.55%와 baseline 매칭

vectorize 불가 (state machine: retirement 동적 결정). Python loop + multiprocessing.
5000 paths / 12 CPU = ≈420 paths/CPU.
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

# 정확한 백테스트 설정 매칭
INITIAL_KRW          = 3_000_000
MONTHLY_DEPOSIT_KRW  = 2_000_000
NUM_DEPOSITS         = 5
KRW_PER_USDT         = 1350.0
MONTHLY_TARGET_KRW   = 10_000_000   # rolling 3m avg KRW 도달 시 retirement

INITIAL_USD          = INITIAL_KRW / KRW_PER_USDT          # $2,222.22
MONTHLY_DEPOSIT_USD  = MONTHLY_DEPOSIT_KRW / KRW_PER_USDT  # $1,481.48
MONTHLY_TARGET_USD   = MONTHLY_TARGET_KRW / KRW_PER_USDT   # $7,407.41

N_SIMS = 5000


def load_trades(fp: Path):
    t = pd.read_csv(fp, usecols=["entry_time","r_multiple","risk_pct_requested",
                                  "net_pnl","month"])
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    t = t.sort_values("entry_time").reset_index(drop=True)
    return t


def build_static(trades: pd.DataFrame):
    """모든 시뮬에 공통인 fixed array들: trade_returns, deposit_inject, trade_month_num."""
    r = trades["r_multiple"].values.astype(np.float64)
    p = trades["risk_pct_requested"].values.astype(np.float64)
    trade_returns = np.maximum(1.0 + p * r, 1e-3)  # ≥ 0.001

    # Deposit schedule: 첫 trade 시점 다음 월 1일부터 5번
    first_t = trades["entry_time"].iloc[0]
    fm_start = pd.Timestamp(year=first_t.year, month=first_t.month, day=1, tz="UTC")
    deposit_dates = [fm_start + pd.offsets.MonthBegin(i) for i in range(1, NUM_DEPOSITS+1)]
    # Per-trade: 이 trade 직전까지 누적된 deposit 횟수
    deposit_cum = np.zeros(len(trades), dtype=np.float64)
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
    n_months = len(unique_months)

    return {
        "trade_returns": trade_returns,
        "deposit_inject": deposit_inject,
        "trade_month_num": trade_month_num,
        "n_months": n_months,
        "unique_months": unique_months,
    }


def simulate_one(returns_seq: np.ndarray, deposit_inject: np.ndarray,
                 trade_month_num: np.ndarray, n_months: int):
    """단일 path 시뮬레이션. entry_time 보존, 매월 1일 입금, retirement 후 매월 출금.
    Returns:
        equity_history (n,): trade-by-trade trading equity
        retired_month_num (int or -1): 첫 rolling 3m >= target month
        cum_withdrawn (float)
    """
    n = len(returns_seq)
    balance = INITIAL_USD
    equity_history = np.empty(n, dtype=np.float64)
    monthly_net_pnl = np.zeros(n_months, dtype=np.float64)
    retired_month = -1

    for i in range(n):
        # 이 trade 직전 입금
        balance += deposit_inject[i]
        # trade outcome
        balance_pre = balance
        balance *= returns_seq[i]
        # PnL 기록 (월별)
        pnl = balance - balance_pre
        m = trade_month_num[i]
        monthly_net_pnl[m] += pnl

        # 월말이면 retirement 체크 + 출금
        is_month_end = (i == n - 1) or (trade_month_num[i+1] != m)
        if is_month_end:
            # rolling 3m avg (해당 월 포함 3개월)
            if retired_month < 0 and m >= 2:
                r3 = (monthly_net_pnl[m-2] + monthly_net_pnl[m-1] + monthly_net_pnl[m]) / 3.0
                if r3 >= MONTHLY_TARGET_USD:
                    retired_month = m
            # retirement 도달한 후 다음 월부터 출금
            if 0 <= retired_month < m:
                balance -= MONTHLY_TARGET_USD

        equity_history[i] = balance

    return equity_history, retired_month


def path_metrics(equity_history: np.ndarray):
    """단일 path의 MDD, final equity 계산. cumulative_excess (withdraw) 미포함."""
    cm = np.maximum.accumulate(equity_history)
    dd = (equity_history - cm) / cm * 100.0
    return float(dd.min()), float(equity_history[-1])


# ── multi-process worker ────────────────────────────────────────
_STATIC = None   # process-local fixed arrays


def _init_worker(trade_returns, deposit_inject, trade_month_num, n_months):
    global _STATIC
    _STATIC = (trade_returns, deposit_inject, trade_month_num, n_months)


def _run_chunk(args):
    """args = (chunk_id, n_paths, seed_base, mode)
    mode = 'shuffle' or 'resample'
    """
    chunk_id, n_paths, seed_base, mode = args
    tr, dep, tmn, nm = _STATIC
    n = len(tr)
    rng = np.random.default_rng(seed_base + chunk_id)
    mdd_arr = np.empty(n_paths, dtype=np.float64)
    fin_arr = np.empty(n_paths, dtype=np.float64)
    retm_arr = np.empty(n_paths, dtype=np.int32)
    for k in range(n_paths):
        if mode == "shuffle":
            perm = rng.permutation(n)
            ret_seq = tr[perm]
        else:  # resample
            idx = rng.integers(0, n, size=n)
            ret_seq = tr[idx]
        eq, rm = simulate_one(ret_seq, dep, tmn, nm)
        mdd, fin = path_metrics(eq)
        mdd_arr[k] = mdd
        fin_arr[k] = fin
        retm_arr[k] = rm
    return chunk_id, mdd_arr, fin_arr, retm_arr


def run_mc(static, n_sims: int, mode: str, seed_base: int = 1234):
    """multiprocess MC. mode = 'shuffle' or 'resample'."""
    import os
    n_workers = min(12, os.cpu_count() or 4)
    chunk_size = max(1, n_sims // n_workers)
    chunks = []
    remaining = n_sims
    cid = 0
    while remaining > 0:
        take = min(chunk_size, remaining)
        chunks.append((cid, take, seed_base, mode))
        cid += 1
        remaining -= take

    print(f"  {mode}: {n_workers} workers × {len(chunks)} chunks (chunk_size~{chunk_size})")
    mdd_list, fin_list, retm_list = [], [], []
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_worker,
        initargs=(static["trade_returns"], static["deposit_inject"],
                  static["trade_month_num"], static["n_months"]),
    ) as ex:
        futs = [ex.submit(_run_chunk, c) for c in chunks]
        for f in as_completed(futs):
            cid, mdd_a, fin_a, retm_a = f.result()
            mdd_list.append(mdd_a)
            fin_list.append(fin_a)
            retm_list.append(retm_a)
    mdd = np.concatenate(mdd_list)
    fin = np.concatenate(fin_list)
    retm = np.concatenate(retm_list)
    return mdd, fin, retm


def main():
    OUT.mkdir(exist_ok=True)
    TRADES_FP = ROOT / "stage4l_FINAL_through_may" / "stage4l_boost15_out_skip_trades.csv"
    print(f"[1/4] Loading trades from {TRADES_FP.name}…")
    trades = load_trades(TRADES_FP)
    print(f"   {len(trades)} trades, first {trades.entry_time.iloc[0]}, "
          f"last {trades.entry_time.iloc[-1]}")
    static = build_static(trades)
    print(f"   {static['n_months']} months, deposits 5x ${MONTHLY_DEPOSIT_USD:.2f}, "
          f"target ${MONTHLY_TARGET_USD:.2f}/mo")

    # ── Baseline (원본 시퀀스) ────────────────────────────────
    print("\n[2/4] Baseline (실제 시퀀스) 시뮬레이션…")
    eq_base, retm_base = simulate_one(
        static["trade_returns"], static["deposit_inject"],
        static["trade_month_num"], static["n_months"])
    mdd_base, fin_base = path_metrics(eq_base)
    print(f"   MDD (trading equity): {mdd_base:.2f}%")
    print(f"   Final balance: ${fin_base:,.0f}")
    if retm_base >= 0:
        rmname = static["unique_months"][retm_base]
        print(f"   Retirement: {rmname} ({retm_base + 1}개월차)")
    else:
        print(f"   Retirement: 미달성")

    # 백테스트 trading equity MDD 와 비교
    print("\n   참고: 백테스트 trading equity MDD = -15.55% (정확 매칭 목표)")

    # ── Monte Carlo ────────────────────────────────────────
    print(f"\n[3/4] Monte Carlo {N_SIMS:,} paths × {len(trades)} trades…")
    print("  (A) Shuffle (permutation)…")
    mdd_A, fin_A, retm_A = run_mc(static, N_SIMS, "shuffle", seed_base=42)
    print("  (B) Resample (with replacement)…")
    mdd_B, fin_B, retm_B = run_mc(static, N_SIMS, "resample", seed_base=42 + 99999)

    # ── 요약 ───────────────────────────────────────────────
    print("\n[4/4] Summary & plots…")

    def to_month_label(arr):
        return np.where(arr >= 0, arr + 1, -1)  # 1-based 개월, -1=미달성

    rm_A_lbl = to_month_label(retm_A)
    rm_B_lbl = to_month_label(retm_B)
    miss_A = float(np.mean(retm_A < 0) * 100)
    miss_B = float(np.mean(retm_B < 0) * 100)

    def pct(arr, p):
        if len(arr) == 0:
            return np.nan
        return float(np.percentile(arr, p))

    def pct_valid(arr, p):
        v = arr[arr >= 0]
        return float(np.percentile(v, p)) if len(v) else np.nan

    rows = [
        ["── Baseline (실제 시퀀스) ──", "", "", ""],
        ["MDD %",       f"{mdd_base:.2f}", "", ""],
        ["Final $",     f"${fin_base:,.0f}", "", ""],
        ["퇴사 개월",     f"{retm_base + 1}" if retm_base >= 0 else "미달성", "", ""],
        ["── Shuffle (5,000 paths) ──", "", "", ""],
        ["MDD %",       f"{pct(mdd_A,5):.2f}", f"{pct(mdd_A,50):.2f}", f"{pct(mdd_A,95):.2f}"],
        ["MDD worst",   f"{mdd_A.min():.2f}", "", ""],
        ["Final $",     f"${pct(fin_A,5):,.0f}", f"${pct(fin_A,50):,.0f}", f"${pct(fin_A,95):,.0f}"],
        ["퇴사 개월",     f"{pct_valid(rm_A_lbl,5):.1f}", f"{pct_valid(rm_A_lbl,50):.1f}", f"{pct_valid(rm_A_lbl,95):.1f}"],
        ["미달성률",     f"{miss_A:.2f}%", "", ""],
        ["── Resample (5,000 paths) ──", "", "", ""],
        ["MDD %",       f"{pct(mdd_B,5):.2f}", f"{pct(mdd_B,50):.2f}", f"{pct(mdd_B,95):.2f}"],
        ["MDD worst",   f"{mdd_B.min():.2f}", "", ""],
        ["Final $",     f"${pct(fin_B,5):,.0f}", f"${pct(fin_B,50):,.0f}", f"${pct(fin_B,95):,.0f}"],
        ["퇴사 개월",     f"{pct_valid(rm_B_lbl,5):.1f}", f"{pct_valid(rm_B_lbl,50):.1f}", f"{pct_valid(rm_B_lbl,95):.1f}"],
        ["미달성률",     f"{miss_B:.2f}%", "", ""],
    ]
    summary_df = pd.DataFrame(rows, columns=["metric","5% / value","median","95%"])
    summary_df.to_csv(OUT / "11_mc_realistic_summary.csv", index=False, encoding="utf-8")
    print("\n" + summary_df.to_string(index=False))

    # ── 그래프: Fan chart (Shuffle, log scale)
    print("\nPlotting fan chart…")
    # equity_paths for fan: re-run baseline + a few sample paths for env
    # 단순화: 일부 path 시뮬해 envelope. 메모리 절약 위해 N=500 미만 정도.
    n_for_fan = 1000
    fan_paths = np.empty((n_for_fan, len(trades)), dtype=np.float64)
    rng = np.random.default_rng(7)
    for k in range(n_for_fan):
        perm = rng.permutation(len(trades))
        ret_seq = static["trade_returns"][perm]
        eq, _ = simulate_one(ret_seq, static["deposit_inject"],
                              static["trade_month_num"], static["n_months"])
        fan_paths[k] = eq

    pcts_fan = np.percentile(fan_paths, [5, 25, 50, 75, 95], axis=0)
    x = np.arange(len(trades))
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.fill_between(x, pcts_fan[0], pcts_fan[4], color="tab:orange", alpha=0.18, label="5–95%")
    ax.fill_between(x, pcts_fan[1], pcts_fan[3], color="tab:orange", alpha=0.35, label="25–75%")
    ax.plot(x, pcts_fan[2], color="tab:orange", lw=1.5, label="MC median")
    ax.plot(x, eq_base, color="black", lw=1.5, label="Baseline (real)")
    ax.set_yscale("log")
    ax.set_xlabel("Trade index")
    ax.set_ylabel("Trading equity (USD, log)")
    ax.set_title(f"Realistic MC fan chart — AM=4.0 / 1,000 shuffle paths\n"
                 f"(입금 5회 + retirement 후 매월 출금 모델링)")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_realistic_fan.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_realistic_fan.png")

    # MDD histogram with vertical baseline marker
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(mdd_A, bins=60, alpha=0.6, color="tab:blue", label="Shuffle")
    ax.hist(mdd_B, bins=60, alpha=0.4, color="tab:red",  label="Resample")
    ax.axvline(mdd_base, color="black", lw=2, ls="--", label=f"Baseline {mdd_base:.2f}%")
    ax.axvline(-15.55, color="green", lw=1.5, ls=":", label="백테스트 -15.55%")
    for p, c in [(5, "tab:purple"), (50, "tab:cyan"), (95, "tab:olive")]:
        v = np.percentile(mdd_A, p)
        ax.axvline(v, color=c, lw=1, alpha=0.6, label=f"Shuffle {p}%: {v:.2f}%")
    ax.set_xlabel("Max Drawdown %")
    ax.set_ylabel("count (paths)")
    ax.set_title("Realistic MC — MDD distribution (입금/출금 모델링)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_realistic_mdd.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_realistic_mdd.png")

    # 퇴사 시점 histogram
    fig, ax = plt.subplots(figsize=(11, 5))
    m_valid_A = rm_A_lbl[rm_A_lbl >= 0]
    m_valid_B = rm_B_lbl[rm_B_lbl >= 0]
    bins = np.arange(0, static["n_months"] + 2)
    ax.hist(m_valid_A, bins=bins, alpha=0.6, color="tab:blue",
            label=f"Shuffle (미달성 {miss_A:.2f}%)")
    ax.hist(m_valid_B, bins=bins, alpha=0.4, color="tab:red",
            label=f"Resample (미달성 {miss_B:.2f}%)")
    if retm_base >= 0:
        ax.axvline(retm_base + 1, color="black", lw=2, ls="--",
                   label=f"Baseline {retm_base + 1}개월")
    ax.set_xlabel("Retirement 도달 개월")
    ax.set_ylabel("count (paths)")
    ax.set_title("Realistic MC — Retirement 시점 분포")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_mc_realistic_retire.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_mc_realistic_retire.png")

    print("\n=== Done ===")
    for f in sorted(OUT.glob("11_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
    for f in sorted(OUT.glob("fig_mc_realistic_*")):
        print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
