#!/usr/bin/env python3
# =========================================================================
# tools/walkforward_year.py — engulf+atr1.3 채택안 연도별 walk-forward
#
#   고정 파라미터(재최적화 없음)로 trades.csv 를 entry 연도별로 분할,
#   각 연도의 실현(close_at_end 제외) PF/avgR/95% CI/나머지6/+코인수 를
#   engulf_atr13 vs engulf_base 로 비교. "매 연도 사는가, 한 해 몰빵인가".
#
#   사용: python tools/walkforward_year.py
#         python tools/walkforward_year.py <atr13_trades.csv> <base_trades.csv>
# =========================================================================
import sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]   # 나머지6 = 제외


def realized(df):
    if "exit_reason" in df.columns:
        return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return df


def pf(x):
    g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else float("inf")


def boot(r, B=10000, seed=909):
    r = np.asarray(r, float)
    if len(r) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    m = r[rng.integers(0, len(r), size=(B, len(r)))].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def pos_coins(df):
    if "symbol" not in df.columns:
        return None
    g = df.groupby("symbol")["net_pnl"].sum()
    return f"{int((g > 0).sum())}/{g.size}"


def block(df):
    d = realized(df)
    rr = d["r_multiple"].astype(float).values
    pnl = d["net_pnl"].astype(float).values
    lo, hi = boot(rr)
    d6 = d[~d["symbol"].isin(CORE3)] if "symbol" in d.columns else d
    return {
        "n": len(d),
        "PF": round(pf(pnl), 3) if len(pnl) else float("nan"),
        "win%": round((pnl > 0).mean() * 100, 1) if len(pnl) else float("nan"),
        "avgR": round(float(rr.mean()), 4) if len(rr) else float("nan"),
        "CI_lo": round(lo, 4), "CI_hi": round(hi, 4),
        "+coins": pos_coins(d),
        "rest6_PF": round(pf(d6["net_pnl"].values), 3) if len(d6) else float("nan"),
        "rest6_avgR": round(float(d6["r_multiple"].mean()), 4) if len(d6) else float("nan"),
    }


def main():
    a_fp = sys.argv[1] if len(sys.argv) > 2 else "gate_sweep_runs/engulf_atr13/stage4d_trades.csv"
    b_fp = sys.argv[2] if len(sys.argv) > 2 else "gate_sweep_runs/engulf_base/stage4d_trades.csv"
    A = pd.read_csv(a_fp); B = pd.read_csv(b_fp)
    for df in (A, B):
        df["year"] = pd.to_datetime(df["entry_time"], utc=True).dt.year

    years = sorted(set(A["year"]) | set(B["year"]))
    print(f"\natr13 = {a_fp}\nbase  = {b_fp}")
    print("=" * 100)
    for label, df in [("engulf+atr1.3 (채택안)", A), ("engulf base (0.9, 대조군)", B)]:
        print(f"\n[{label}]  연도별 walk-forward (실현기준)")
        rows = [{"year": "ALL", **block(df)}]
        for y in years:
            sub = df[df["year"] == y]
            if len(sub):
                rows.append({"year": str(y), **block(sub)})
        print(pd.DataFrame(rows).to_string(index=False))

    # 연도별 atr13 vs base 직접 비교(PF / avgR)
    print("\n" + "=" * 100)
    print("연도별 atr13 vs base  (PF | avgR | 나머지6 PF)  — atr13 이 매 연도 base 를 이기나?")
    rows = []
    for y in ["ALL"] + [str(x) for x in years]:
        sa = A if y == "ALL" else A[A["year"] == int(y)]
        sb = B if y == "ALL" else B[B["year"] == int(y)]
        if len(sa) == 0 or len(sb) == 0:
            continue
        ba, bb = block(sa), block(sb)
        win = "atr13 ✓" if (ba["avgR"] > bb["avgR"] and (ba["PF"] or 0) > (bb["PF"] or 0)) else "—"
        rows.append({"year": y,
                     "atr13_PF": ba["PF"], "base_PF": bb["PF"],
                     "atr13_avgR": ba["avgR"], "base_avgR": bb["avgR"],
                     "atr13_rest6PF": ba["rest6_PF"], "base_rest6PF": bb["rest6_PF"],
                     "승자": win})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
