#!/usr/bin/env python3
# =========================================================================
# tools/compare_refine.py — feature/h1-refine-zone 효과 판정
#
#   4개 trades.csv (strict/engulf × base/refine) 를 받아
#   '실현 기준'(close_at_end 제외) PF / avgR / avgR 부트스트랩 95% CI 를 비교.
#   refined=True 거래만 따로도 비교. in-sample PF 한끗 금지 → CI 로 판단.
#
#   사용: python tools/compare_refine.py
#         python tools/compare_refine.py out_strict_base out_strict_refine out_engulf_base out_engulf_refine
# =========================================================================
import sys, os
import numpy as np, pandas as pd

DEFAULT = ["out_strict_base", "out_strict_refine", "out_engulf_base", "out_engulf_refine"]


def realized(df):
    """close_at_end(데이터 끝 강제청산) 제외 = 실현 기준."""
    if "exit_reason" in df.columns:
        m = ~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)
        return df[m]
    return df


def pf(x):
    g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else float("inf")


def boot_ci(r, B=10000, seed=12345):
    r = np.asarray(r, float)
    if len(r) == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(B, len(r)))   # 벡터화 부트스트랩
    means = r[idx].mean(axis=1)
    return float(r.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(label, df):
    d = realized(df)
    rr = d["r_multiple"].astype(float).values if "r_multiple" in d.columns else np.array([])
    pnl = d["net_pnl"].astype(float).values if "net_pnl" in d.columns else np.array([])
    avg, lo, hi = boot_ci(rr)
    return {
        "label": label,
        "trades_all": len(df),
        "trades_realized": len(d),
        "win%": round(float((pnl > 0).mean() * 100), 2) if len(pnl) else float("nan"),
        "PF": round(pf(pnl), 4) if len(pnl) else float("nan"),
        "avgR": round(avg, 4),
        "avgR_CI95_lo": round(lo, 4),
        "avgR_CI95_hi": round(hi, 4),
    }


def main():
    dirs = sys.argv[1:5] if len(sys.argv) >= 5 else DEFAULT
    rows = []
    refined_rows = []
    loaded = {}
    for d in dirs:
        fp = os.path.join(d, "stage4d_trades.csv")
        if not os.path.exists(fp):
            print(f"[skip] {fp} 없음")
            continue
        df = pd.read_csv(fp)
        loaded[d] = df
        rows.append(summarize(d, df))
        # refined=True 만 따로 (refine 런에서만 의미)
        if "h1_refined" in df.columns and df["h1_refined"].any():
            refined_rows.append(summarize(d + " [refined=True]", df[df["h1_refined"] == True]))

    print("\n================ 전체 (실현 기준, close_at_end 제외) ================")
    print(pd.DataFrame(rows).to_string(index=False))

    if refined_rows:
        print("\n================ refined=True 거래만 ================")
        print(pd.DataFrame(refined_rows).to_string(index=False))

    # on vs off 쌍 비교 (CI 분리 여부)
    print("\n================ 판정 (avgR 95% CI 분리?) ================")
    for base, refd in [("out_strict_base", "out_strict_refine"),
                        ("out_engulf_base", "out_engulf_refine")]:
        if base in loaded and refd in loaded:
            b = summarize(base, loaded[base]); r = summarize(refd, loaded[refd])
            sep = "위로 분리(단서 O)" if r["avgR_CI95_lo"] > b["avgR_CI95_hi"] else \
                  "아래로 분리(악화)" if r["avgR_CI95_hi"] < b["avgR_CI95_lo"] else "겹침(무효)"
            print(f"  {base} vs {refd}: "
                  f"avgR {b['avgR']}→{r['avgR']} | "
                  f"refine CI[{r['avgR_CI95_lo']},{r['avgR_CI95_hi']}] vs base CI[{b['avgR_CI95_lo']},{b['avgR_CI95_hi']}] "
                  f"→ {sep}")


if __name__ == "__main__":
    main()
