#!/usr/bin/env python3
# =========================================================================
# tools/score_pool_verify.py — score_ge13 AND ANY_OTHER 게이트 풀 검증 + 원자 lift
#
#   §3 self-verify(자본 미검증): 전 거래 a_score_ge13=True, entry_refined 존재, 16원자, engulf/1.3.
#   + 풀 안 15원자 honest-lift(전체/나머지6/OOS) — 다음 조합탐색 재료. 자본은 안 건드림(r_multiple 기반).
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ATOM16 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
          "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_ob",
          "a_overlap", "a_room", "a_efficiency", "a_bb_squeeze", "a_vol_expansion"]
OTHERS = [a for a in ATOM16 if a not in ("a_score_ge13",)]


def pf(x):
    gp = x[x > 0].sum(); gl = -x[x < 0].sum()
    return gp / gl if gl > 0 else float("inf")


def realized(df):
    return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in df else df


def subset_stat(d):
    rr = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    if len(d) == 0:
        return dict(n=0, PF=float("nan"), avgR=float("nan"), OOS_PF=float("nan"), rest6_PF=float("nan"))
    k = int(len(d) * 0.7)
    d6 = d[~d["symbol"].isin(CORE3)] if "symbol" in d else d
    return dict(n=len(d), PF=round(pf(pnl), 3), avgR=round(float(rr.mean()), 4),
                OOS_PF=round(pf(pnl[k:]), 3) if len(d) - k else float("nan"),
                rest6_PF=round(pf(d6["net_pnl"].values), 3) if len(d6) else float("nan"))


def main():
    rundir = sys.argv[1] if len(sys.argv) > 1 else "out_score"
    df = pd.read_csv(os.path.join(rundir, "stage4d_trades.csv"))
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    d = realized(df).sort_values("entry_time").reset_index(drop=True)

    print(f"=== score_ge13 게이트 풀 — {len(d)}거래 (전체 {len(df)}) ===")
    base = subset_stat(d)
    print(f"  풀 전체: PF {base['PF']} | avgR {base['avgR']} | OOS_PF {base['OOS_PF']} | 나머지6 {base['rest6_PF']}")

    print("\n=== 풀 안 15원자 honest-lift (정렬: avgR_pass) ===")
    rows = []
    for a in OTHERS:
        if a not in d.columns:
            continue
        m = d[a].astype(bool)
        sp = subset_stat(d[m]); sf = subset_stat(d[~m])
        rows.append({"atom": a, "n_pass": sp["n"],
                     "PF_pass": sp["PF"], "avgR_pass": sp["avgR"], "OOS_pass": sp["OOS_PF"], "rest6_pass": sp["rest6_PF"],
                     "avgR_fail": sf["avgR"], "lift": round((sp["avgR"] or 0) - (sf["avgR"] or 0), 4)})
    rdf = pd.DataFrame(rows).sort_values("avgR_pass", ascending=False, na_position="last")
    print(rdf.to_string(index=False))
    rdf.to_csv(os.path.join(rundir, "score_pool_atom_lift.csv"), index=False)

    # §3 self-verify
    print("\n=== §3 self-verify (자본 제외) ===")
    sc = d["a_score_ge13"].astype(bool)
    ck = {
        "전 거래 a_score_ge13=True": bool(sc.all()),
        "entry_refined True 존재": bool(d["entry_refined"].astype(bool).any()) if "entry_refined" in d else False,
        "16원자 전부 로그": all(c in d.columns for c in ATOM16),
        "OB_MODE=engulf": ("ob_mode" in d.columns) and (d["ob_mode"].astype(str).iloc[0] == "engulf"),
        "disp_atr_mult=1.3": ("disp_atr_mult" in d.columns) and abs(float(d["disp_atr_mult"].iloc[0]) - 1.3) < 1e-6,
    }
    for k, v in ck.items():
        print(f"  [{'OK' if v else 'X '}] {k}")
    print(f"  entry_refined True: {d['entry_refined'].astype(bool).mean()*100:.1f}%" if "entry_refined" in d else "")

    keep = [c for c in (["entry_time", "exit_time", "symbol", "type", "r_multiple", "net_pnl", "exit_reason",
            "entry_refined", "h1_refined", "tier", "tier_mult", "disp_atr_mult", "ob_mode"] + ATOM16) if c in d.columns]
    d[keep].to_csv(os.path.join(rundir, "trades_score_pool.csv"), index=False)
    print(f"→ {rundir}/trades_score_pool.csv + score_pool_atom_lift.csv 저장")


if __name__ == "__main__":
    main()
