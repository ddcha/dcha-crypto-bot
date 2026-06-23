#!/usr/bin/env python3
# =========================================================================
# tools/compare_gate.py — feature/gate-tighten 18런 판정
#
#   gate_sweep_runs/{ob}_{variant}/stage4d_trades.csv 를 읽어,
#   OB(strict/engulf)별로 각 게이트 변형을 '그 OB의 baseline' 대비
#   실현(close_at_end 제외) avgR + 95% 부트스트랩 CI 로 비교한다.
#   전체9 + 나머지6(코어3 제외) 두 관점. in-sample PF 로 승자 고르지 말 것.
#
#   사용: python tools/compare_gate.py
#         python tools/compare_gate.py --core BTCUSDT,ETHUSDT,SOLUSDT
# =========================================================================
import os, sys, argparse
import numpy as np, pandas as pd

ROOT = "gate_sweep_runs"
VARIANTS = ["base", "sweep30", "sweep50", "atr13", "atr15", "atr17", "body60", "body75", "choch"]
OBS = ["strict", "engulf"]
CORE3_DEFAULT = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]   # '나머지6' = 이 3개 제외 (가정; --core 로 변경)


def realized(df):
    if "exit_reason" in df.columns:
        return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return df


def pf(x):
    g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else float("inf")


def boot(r, B=10000, seed=2024):
    r = np.asarray(r, float)
    if len(r) == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = r[rng.integers(0, len(r), size=(B, len(r)))].mean(axis=1)
    return float(r.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def stat(df):
    d = realized(df)
    rr = d["r_multiple"].astype(float).values
    pnl = d["net_pnl"].astype(float).values
    a, lo, hi = boot(rr)
    return dict(n=len(d), win=round((pnl > 0).mean() * 100, 1) if len(pnl) else float("nan"),
                PF=round(pf(pnl), 3) if len(pnl) else float("nan"),
                avgR=round(a, 4), lo=round(lo, 4), hi=round(hi, 4))


def verdict(base, var):
    # 변형 CI 하단이 base avgR 위 → 개선 단서 ; 상단이 base 아래 → 악화 ; else 무효
    if var["lo"] > base["hi"]:
        return "↑개선(CI분리)"
    if var["hi"] < base["lo"]:
        return "↓악화(CI분리)"
    if var["avgR"] > base["avgR"]:
        return "~상향(겹침)"
    return "~하향/무효"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default=",".join(CORE3_DEFAULT),
                    help="나머지6 산출용 제외 코인 3개 (콤마구분)")
    args = ap.parse_args()
    core = [c.strip() for c in args.core.split(",") if c.strip()]

    for view, filt in [("전체 9코인", None), (f"나머지6 (제외 {core})", core)]:
        print("\n" + "=" * 78)
        print(f"  관점: {view}   — 실현기준, 각 변형 vs 같은 OB의 base, avgR 95% CI")
        print("=" * 78)
        for ob in OBS:
            rows = []
            base_stat = None
            for v in VARIANTS:
                fp = os.path.join(ROOT, f"{ob}_{v}", "stage4d_trades.csv")
                if not os.path.exists(fp):
                    continue
                df = pd.read_csv(fp)
                if filt and "symbol" in df.columns:
                    df = df[~df["symbol"].isin(filt)]
                s = stat(df)
                if v == "base":
                    base_stat = s
                vd = "" if v == "base" else (verdict(base_stat, s) if base_stat else "")
                rows.append({"OB": ob, "variant": v, **s, "verdict": vd})
            if rows:
                print(f"\n[OB_MODE={ob}]")
                print(pd.DataFrame(rows)[["variant", "n", "win", "PF", "avgR", "lo", "hi", "verdict"]].to_string(index=False))


if __name__ == "__main__":
    main()
