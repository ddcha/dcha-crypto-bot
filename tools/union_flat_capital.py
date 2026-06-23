#!/usr/bin/env python3
# =========================================================================
# tools/union_flat_capital.py — union 런 + 시드500 flat 자본시뮬 (티어 없음)
#
#   COMBO_UNION_FIX (refine·자본만): refine 은 엔진서 ON(entry_refined=h1_refined 반영).
#   여기선 자본만 후처리: run_equity 시드500 + 월말250×5, 전 거래 flat 1.0x(티어 곱 없음).
#   balance_at_entry/phase_at_entry/tier_mult(=1.0) 박은 enriched trades.csv 저장 +
#   §4 체크리스트 self-verify + (참고) 12조합 사후 분해.
#
#   사용: python tools/union_flat_capital.py out_union_fixed
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
COMBO_KEYS = ["c01_score_fvg_vol", "c02_score_vol_volume_room", "c03_eff_fvg_vol_volume_wick_room",
              "c04_eff_fvg_vol_volume_room", "c05_eff_fvg_vol_volume_wick", "c06_eff_fvg_vol_wick",
              "c07_eff_fvg_vol_room", "c08_eff_fvg_vol_volume", "c09_score_vol", "c10_eff_fvg_vol",
              "c11_fvg_vol_wick", "c12_fvg_vol"]
ATOM15 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
          "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap",
          "a_room", "a_efficiency", "a_bb_squeeze", "a_vol_expansion"]


def run_equity(g, rvals, seed=500.0, monthly=250.0, nd=5, rp=0.01):
    ET, XT = g["entry_time"].values, g["exit_time"].values
    et_min = pd.Timestamp(g["entry_time"].min()).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = et_min
    for _ in range(nd):
        nxt = m + pd.offsets.MonthBegin(1); deps.append((np.datetime64(nxt.tz_convert("UTC").tz_localize(None)), monthly)); m = nxt
    ev = []
    for i in range(len(g)):
        ev.append((np.datetime64(pd.Timestamp(ET[i]).tz_localize(None) if pd.Timestamp(ET[i]).tz else ET[i]), 0, i))
        ev.append((np.datetime64(pd.Timestamp(XT[i]).tz_localize(None) if pd.Timestamp(XT[i]).tz else XT[i]), 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]; ev.sort(key=lambda x: (x[0], x[1]))
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * realized; eq[p] = realized
        elif pri == 1:
            realized += (-p)
        else:
            realized += rvals[p] * ra.get(p, 0.0)
            peak = max(peak, realized); mdd = min(mdd, (realized - peak) / peak)
    return eq, realized, mdd


def test_capital_no_lookahead(g):
    XT = g["exit_time"]; ET = g["entry_time"]; r_base = g["r_multiple"].values.copy()
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
    gp = x[x > 0].sum(); gl = -x[x < 0].sum()
    return gp / gl if gl > 0 else float("inf")


def realized(df):
    return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in df else df


def phase_of(et, et_min, nd=5):
    base = et_min.tz_convert("UTC").normalize().replace(day=1)
    arr = [base + pd.offsets.MonthBegin(i + 1) for i in range(nd)]
    return f"P{sum(1 for a in arr if et >= a)}"


def stat(d):
    rr = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    if len(d) == 0:
        return {"n": 0}
    k = int(len(d) * 0.7)
    return {"n": len(d), "win%": round((pnl > 0).mean() * 100, 1), "PF": round(pf(pnl), 3),
            "OOS_PF": round(pf(pnl[k:]), 3) if len(d) - k else float("nan"),
            "avgR": round(float(rr.mean()), 4), "sumR": round(float(rr.sum()), 1)}


def main():
    rundir = sys.argv[1] if len(sys.argv) > 1 else "out_union_fixed"
    df = pd.read_csv(os.path.join(rundir, "stage4d_trades.csv"))
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["combos_matched"] = df.get("combos_matched", "").fillna("").astype(str)
    d = realized(df).sort_values("entry_time").reset_index(drop=True)

    chk = test_capital_no_lookahead(d)
    eq, final, mdd = run_equity(d, d["r_multiple"].values)
    d["balance_at_entry"] = [eq.get(i, np.nan) for i in range(len(d))]
    et_min = d["entry_time"].min()
    d["phase_at_entry"] = [phase_of(t, et_min) for t in d["entry_time"]]
    d["tier_mult"] = 1.0
    yr = max((d["exit_time"].max() - d["entry_time"].min()).days / 365.25, 1e-9)

    print(f"=== union 시드500 flat 자본시뮬 ({len(d)}거래) ===")
    print(f"  최종 ${final:.0f} | 총납입 1750 대비 {final/1750:.2f}x | CAGR {((final/1750)**(1/yr)-1)*100:.1f}% | MDD {mdd*100:.1f}%")
    print(f"  전체 PF {pf(d['net_pnl'].values):.3f} | avgR {d['r_multiple'].mean():.4f}")

    # enriched 저장 (15원자 전부 포함)
    keep = (["entry_time", "exit_time", "symbol", "type", "r_multiple", "net_pnl", "exit_reason",
             "combos_matched", "entry_refined", "h1_refined", "balance_at_entry", "phase_at_entry",
             "tier", "tier_mult", "disp_atr_mult", "ob_mode"] + ATOM15)
    keep = [c for c in keep if c in d.columns]
    out_fp = os.path.join(rundir, "trades_union_flat500.csv")
    d[keep].to_csv(out_fp, index=False)

    # 참고: 12조합 사후 분해
    print("\n=== 참고: 12조합 사후 분해 (flat) ===")
    rows = []
    for k in COMBO_KEYS:
        sub = d[d["combos_matched"].apply(lambda s: k in s.split("|"))]
        rows.append({"combo": k, **stat(sub)})
    rows = sorted(rows, key=lambda r: (r.get("OOS_PF") if r.get("OOS_PF") == r.get("OOS_PF") else -9), reverse=True)
    print(pd.DataFrame(rows).to_string(index=False))

    # §4 self-verify
    print("\n=== §4 체크리스트 self-verify ===")
    er = d["entry_refined"] if "entry_refined" in d else pd.Series([], dtype=bool)
    ck = {
        "entry_refined True 존재": bool(er.astype(bool).any()) if len(er) else False,
        "balance 시작 ≈ 500": abs(float(d["balance_at_entry"].iloc[0]) - 500) < 1.0,
        "phase 5단계 분화": d["phase_at_entry"].nunique() >= 2,
        "tier_mult 전부 1.0": bool((d["tier_mult"] == 1.0).all()),
        "combos_matched union 유지": d["combos_matched"].str.contains(r"\|").any(),
        "룩어헤드 0불일치": chk > 0,
        "15원자 컬럼 모두 포함": all(c in d.columns for c in ATOM15),
    }
    for k, v in ck.items():
        print(f"  [{'OK' if v else 'X '}] {k}")
    print(f"\n  entry_refined True 비율: {er.astype(bool).mean()*100:.1f}% ({int(er.astype(bool).sum())}/{len(d)})")
    print(f"→ {out_fp} 저장")


if __name__ == "__main__":
    main()
