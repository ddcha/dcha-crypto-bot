#!/usr/bin/env python3
# =========================================================================
# tools/combo_union_analyze.py — 단일 UNION 런에서 조합별 성과 분해
#
#   USE_COMBO_UNION=1 한 번의 백테스트(어느 조합이든 만족하면 매매, combos_matched 태그)
#   결과 trades.csv 를 받아, 조합별 subset(= combos_matched 에 그 키 포함) 성과를:
#   실현 PF/IS_PF/OOS_PF(70:30)/avgR/Sharpe/sumR + 자본시뮬(시드500+250×5) + 나머지6
#   로 한 표(combo_union_summary.csv). 룩어헤드 테스트 통과 강제.
#
#   사용: python tools/combo_union_analyze.py <union_run_dir>
#         python tools/combo_union_analyze.py combo_union_run
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
COMBO_KEYS = ["c01_score_fvg_vol", "c02_score_vol_volume_room", "c03_eff_fvg_vol_volume_wick_room",
              "c04_eff_fvg_vol_volume_room", "c05_eff_fvg_vol_volume_wick", "c06_eff_fvg_vol_wick",
              "c07_eff_fvg_vol_room", "c08_eff_fvg_vol_volume", "c09_score_vol", "c10_eff_fvg_vol",
              "c11_fvg_vol_wick", "c12_fvg_vol"]


def run_equity(g, rvals, seed=500.0, monthly=250.0, nd=5, rp=0.01):
    ET, XT = g["entry_time"], g["exit_time"]
    start = ET.min().normalize().replace(day=1); deps = []; m = start
    for _ in range(nd):
        nxt = m + pd.offsets.MonthBegin(1); deps.append((nxt, monthly)); m = nxt
    ev = []
    for i in range(len(g)):
        ev.append((ET.iloc[i], 0, i)); ev.append((XT.iloc[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]; ev.sort(key=lambda x: (x[0], x[1]))
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0; curve = []
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * realized; eq[p] = realized
        elif pri == 1:
            realized += (-p)
        else:
            realized += rvals[p] * ra.get(p, 0.0)
            peak = max(peak, realized); mdd = min(mdd, (realized - peak) / peak); curve.append((ts, realized))
    return eq, realized, mdd, curve


def test_capital_no_lookahead(g):
    ET, XT = g["entry_time"], g["exit_time"]; r_base = g["r_multiple"].values.copy()
    eq0, *_ = run_equity(g, r_base); rng = np.random.default_rng(7)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (XT >= T).values; past = g.index[ET <= T]
        for _ in range(50):
            r2 = r_base.copy(); r2[fut] = rng.uniform(-5, 5, fut.sum())
            eq1, *_ = run_equity(g, r2)
            for i in past:
                checked += 1
                if abs(eq0[i] - eq1[i]) > 1e-9:
                    mism += 1
    assert mism == 0, f"CAPITAL LOOKAHEAD LEAK {mism}/{checked}"
    return checked


def pf(x):
    g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else float("inf")


def realized(df):
    if "exit_reason" in df.columns:
        return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return df


def metrics(d, label, do_la=False):
    d = d.sort_values("entry_time").reset_index(drop=True)
    rr = d["r_multiple"].astype(float).values
    pnl = d["net_pnl"].astype(float).values
    if len(d) == 0:
        return {"combo": label, "n": 0}
    k = int(len(d) * 0.7)
    checked = test_capital_no_lookahead(d) if do_la else -1
    _, final, mdd, _ = run_equity(d, rr)
    yr = max((d["exit_time"].max() - d["entry_time"].min()).days / 365.25, 1e-9)
    cagr = (final / 1750.0) ** (1 / yr) - 1 if final > 0 else float("nan")
    sh = float(rr.mean() / rr.std(ddof=1)) if len(rr) > 1 and rr.std(ddof=1) > 0 else float("nan")
    d6 = d[~d["symbol"].isin(CORE3)] if "symbol" in d.columns else d
    return {"combo": label, "n": len(d), "win%": round((pnl > 0).mean() * 100, 1),
            "PF": round(pf(pnl), 3), "IS_PF": round(pf(pnl[:k]), 3) if k else float("nan"),
            "OOS_PF": round(pf(pnl[k:]), 3) if len(d) - k else float("nan"),
            "avgR": round(float(rr.mean()), 4), "Sharpe": round(sh, 3), "sumR": round(float(rr.sum()), 1),
            "final$": round(final, 1), "x_dep": round(final / 1750.0, 2),
            "CAGR%": round(cagr * 100, 1), "MDD%": round(mdd * 100, 1),
            "rest6_PF": round(pf(d6["net_pnl"].values), 3) if len(d6) else float("nan"),
            "LA_chk": checked}


def main():
    rundir = sys.argv[1] if len(sys.argv) > 1 else "combo_union_run"
    fp = os.path.join(rundir, "stage4d_trades.csv")
    df = pd.read_csv(fp)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["combos_matched"] = df["combos_matched"].fillna("").astype(str)
    allr = realized(df)

    rows = [metrics(allr, "ALL_union", do_la=True)]  # 전체 union (룩어헤드 1회 검증)
    for key in COMBO_KEYS:
        sub = allr[allr["combos_matched"].apply(lambda s: key in s.split("|"))]
        rows.append(metrics(sub, key))
    out = pd.DataFrame(rows).sort_values(["OOS_PF", "sumR"], ascending=False, na_position="last").reset_index(drop=True)
    out.to_csv("combo_union_summary.csv", index=False)
    print("\n" + "=" * 120)
    print(f"  단일 UNION 런 조합별 성과 (실현기준, 정렬 OOS_PF→sumR)  — 전체 union {len(allr)}거래")
    print("=" * 120)
    print(out.to_string(index=False))
    print("\n→ combo_union_summary.csv 저장.")


if __name__ == "__main__":
    main()
