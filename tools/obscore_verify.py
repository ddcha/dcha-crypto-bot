#!/usr/bin/env python3
# =========================================================================
# tools/obscore_verify.py — (a_ob OR a_score_ge13) 게이트 런 검증 + 시드500 flat 자본
#
#   §4 self-verify: a_ob 컬럼/표본, 게이트(전 거래 a_ob|a_score), entry_refined,
#   balance≈500, phase 5단계, tier_mult 1.0, 룩어헤드0, 16원자 포함.
#   + a_ob/a_fvg/a_score_ge13 교차표(독립성) + 시드500 flat 자본 + enriched 저장.
# =========================================================================
import os, sys
import numpy as np, pandas as pd

ATOM16 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
          "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_ob",
          "a_overlap", "a_room", "a_efficiency", "a_bb_squeeze", "a_vol_expansion"]


def run_equity(g, rvals, seed=500.0, monthly=250.0, nd=5, rp=0.01):
    ET, XT = g["entry_time"], g["exit_time"]
    et_min = pd.Timestamp(ET.min()).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = et_min
    for _ in range(nd):
        nxt = m + pd.offsets.MonthBegin(1); deps.append((nxt, monthly)); m = nxt
    ev = []
    for i in range(len(g)):
        ev.append((ET.iloc[i], 0, i)); ev.append((XT.iloc[i], 2, i))
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
    gp = x[x > 0].sum(); gl = -x[x < 0].sum()
    return gp / gl if gl > 0 else float("inf")


def realized(df):
    return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in df else df


def phase_of(et, et_min, nd=5):
    base = et_min.tz_convert("UTC").normalize().replace(day=1)
    arr = [base + pd.offsets.MonthBegin(i + 1) for i in range(nd)]
    return f"P{sum(1 for a in arr if et >= a)}"


def main():
    rundir = sys.argv[1] if len(sys.argv) > 1 else "out_obscore"
    df = pd.read_csv(os.path.join(rundir, "stage4d_trades.csv"))
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    d = realized(df).sort_values("entry_time").reset_index(drop=True)

    chk = test_capital_no_lookahead(d)
    eq, final, mdd = run_equity(d, d["r_multiple"].values)
    d["balance_at_entry"] = [eq.get(i, np.nan) for i in range(len(d))]
    et_min = d["entry_time"].min()
    d["phase_at_entry"] = [phase_of(t, et_min) for t in d["entry_time"]]
    d["tier_mult"] = 1.0
    yr = max((d["exit_time"].max() - d["entry_time"].min()).days / 365.25, 1e-9)

    print(f"=== (a_ob OR a_score_ge13) 게이트 풀 — {len(d)}거래 (전체 {len(df)}) ===")
    print(f"  시드500 flat: 최종 ${final:.0f} ({final/1750:.2f}x납입) CAGR {((final/1750)**(1/yr)-1)*100:.1f}% MDD {mdd*100:.1f}% | PF {pf(d['net_pnl'].values):.3f} avgR {d['r_multiple'].mean():.4f}")

    ob = d["a_ob"].astype(bool); sc = d["a_score_ge13"].astype(bool); fv = d["a_fvg"].astype(bool)
    print("\n=== a_ob / a_score_ge13 / a_fvg 교차 (게이트 풀 내) ===")
    print(f"  a_ob True: {int(ob.sum())} ({100*ob.mean():.1f}%) | a_score True: {int(sc.sum())} | a_fvg True: {int(fv.sum())}")
    print(f"  ob&~score(ob 단독진입): {int((ob & ~sc).sum())} | score&~ob: {int((sc & ~ob).sum())} | 둘다: {int((ob & sc).sum())}")
    print(f"  게이트 위반(ob도 score도 아님): {int((~ob & ~sc).sum())}  ← 0 이어야 정상")
    # ob vs fvg 독립성·PF
    for name, m in [("a_ob only", ob & ~fv), ("a_fvg only", fv & ~ob), ("both ob&fvg", ob & fv), ("neither", ~ob & ~fv)]:
        sub = d[m]
        if len(sub):
            print(f"  [{name:12}] n={len(sub):4} PF={pf(sub['net_pnl'].values):.3f} avgR={sub['r_multiple'].mean():+.4f}")

    keep = ["entry_time", "exit_time", "symbol", "type", "r_multiple", "net_pnl", "exit_reason",
            "entry_refined", "h1_refined", "balance_at_entry", "phase_at_entry", "tier", "tier_mult",
            "disp_atr_mult", "ob_mode"] + ATOM16
    keep = [c for c in keep if c in d.columns]
    d[keep].to_csv(os.path.join(rundir, "trades_obscore_flat500.csv"), index=False)

    print("\n=== §4 self-verify ===")
    ck = {
        "a_ob 컬럼 존재 + 표본": ("a_ob" in d.columns) and int(ob.sum()) > 0,
        "전 거래 a_ob OR a_score (게이트 작동)": int((~ob & ~sc).sum()) == 0,
        "entry_refined True 존재": bool(d["entry_refined"].astype(bool).any()) if "entry_refined" in d else False,
        "balance 시작 ≈ 500": abs(float(d["balance_at_entry"].iloc[0]) - 500) < 1.0,
        "phase 5단계 분화": d["phase_at_entry"].nunique() >= 2,
        "tier_mult 전부 1.0": bool((d["tier_mult"] == 1.0).all()),
        "룩어헤드 0불일치": chk > 0,
        "16원자 모두 포함": all(c in d.columns for c in ATOM16),
    }
    for k, v in ck.items():
        print(f"  [{'OK' if v else 'X '}] {k}")
    print(f"  entry_refined True: {d['entry_refined'].astype(bool).mean()*100:.1f}%  | 룩어헤드 checked {chk}")
    print(f"→ {rundir}/trades_obscore_flat500.csv 저장")


if __name__ == "__main__":
    main()
