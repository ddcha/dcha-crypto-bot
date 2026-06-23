#!/usr/bin/env python3
# =========================================================================
# tools/solo_sweep_analyze.py — 15원자 단독 게이트 스윕 한 표
#
#   out_solo_<X>/stage4d_trades.csv 들을 모아 원자별 n/win/PF/IS_PF/OOS_PF/나머지6/avgR/refine%
#   + 게이트 작동(전 거래 a_X=True) 검증. 정렬 OOS_PF→나머지6. 자본 미사용(r_multiple 기반).
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg",
         "a_ob", "a_room", "a_efficiency", "a_bb_squeeze", "a_vol_expansion"]


def pf(x):
    gp = x[x > 0].sum(); gl = -x[x < 0].sum()
    return gp / gl if gl > 0 else float("inf")


def realized(df):
    return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in df else df


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    rows = []
    for X in ATOMS:
        fp = os.path.join(root, f"out_solo_{X}", "stage4d_trades.csv")
        if not os.path.exists(fp):
            print(f"[skip] {fp} 없음"); continue
        df = pd.read_csv(fp)
        if len(df) == 0:
            rows.append({"atom": X, "n": 0}); continue
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        d = realized(df).sort_values("entry_time").reset_index(drop=True)
        rr = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
        k = int(len(d) * 0.7)
        d6 = d[~d["symbol"].isin(CORE3)] if "symbol" in d else d
        gate_ok = bool(d[X].astype(bool).all()) if X in d.columns else False
        ref = d["entry_refined"].astype(bool).mean() * 100 if "entry_refined" in d else float("nan")
        rows.append({
            "atom": X, "n": len(d), "win%": round((pnl > 0).mean() * 100, 1),
            "PF": round(pf(pnl), 3),
            "IS_PF": round(pf(pnl[:k]), 3) if k else float("nan"),
            "OOS_PF": round(pf(pnl[k:]), 3) if len(d) - k else float("nan"),
            "avgR": round(float(rr.mean()), 4),
            "rest6_PF": round(pf(d6["net_pnl"].values), 3) if len(d6) else float("nan"),
            "refine%": round(ref, 0), "gate_ok": gate_ok,
        })
    out = pd.DataFrame(rows).sort_values("OOS_PF", ascending=False, na_position="last").reset_index(drop=True)
    out.to_csv("solo_sweep_summary.csv", index=False)
    print("=" * 100)
    print("  15원자 단독 게이트 스윕 (실현기준, 정렬 OOS_PF) — 편향 없는 공정 순위")
    print("=" * 100)
    print(out.to_string(index=False))
    print("\n→ solo_sweep_summary.csv 저장. (gate_ok 전부 True 여야 게이트 정상)")


if __name__ == "__main__":
    main()
