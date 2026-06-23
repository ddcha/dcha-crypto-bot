#!/usr/bin/env python3
# =========================================================================
# tools/combo_capital_sweep.py — 12조합 + 대조군 자본시뮬/PF/OOS 집계
#
#   out_<KEY>/stage4d_trades.csv (게이트 실백테스트 산출) 들을 읽어:
#   - test_capital_no_lookahead 매 조합 통과(0불일치) 강제
#   - run_equity 자본시뮬(시드500 + 월말250×5) → 최종자본/MDD/CAGR/곡선
#   - 실현(close_at_end 제외) PF/IS_PF/OOS_PF(70:30)/avgR/Sharpe/sumR/나머지6
#   를 한 표(combo_capital_summary.csv)로. 정렬: OOS_PF, 동률 sumR.
#
#   사용: python tools/combo_capital_sweep.py            # COMBO_KEYS+nogate 자동
#         python tools/combo_capital_sweep.py out_c08_eff_fvg_vol_volume ...
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
KEYS = ["c01_score_fvg_vol", "c02_score_vol_volume_room", "c03_eff_fvg_vol_volume_wick_room",
        "c04_eff_fvg_vol_volume_room", "c05_eff_fvg_vol_volume_wick", "c06_eff_fvg_vol_wick",
        "c07_eff_fvg_vol_room", "c08_eff_fvg_vol_volume", "c09_score_vol", "c10_eff_fvg_vol",
        "c11_fvg_vol_wick", "c12_fvg_vol", "nogate"]


# ── 자본 엔진 (스펙 §2 그대로; 실현자본 사이징, 룩어헤드 안전) ──
def run_equity(g, rvals, seed=500.0, monthly=250.0, nd=5, rp=0.01, risk_mult=None):
    ET, XT = g["entry_time"], g["exit_time"]
    start = ET.min().normalize().replace(day=1); deps = []; m = start
    for _ in range(nd):
        nxt = m + pd.offsets.MonthBegin(1); deps.append((nxt, monthly)); m = nxt
    ev = []
    for i in range(len(g)):
        ev.append((ET.iloc[i], 0, i)); ev.append((XT.iloc[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]; ev.sort(key=lambda x: (x[0], x[1]))
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0; curve = []
    rm = risk_mult if risk_mult is not None else {}
    tiers = g["tier"].values if "tier" in g.columns else [None] * len(g)
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * rm.get(tiers[p], 1.0) * realized; eq[p] = realized
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


def realized(df):
    if "exit_reason" in df.columns:
        return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return df


def pf(x):
    g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else float("inf")


def analyze(outdir):
    fp = os.path.join(outdir, "stage4d_trades.csv")
    if not os.path.exists(fp):
        return None
    df = pd.read_csv(fp)
    if len(df) == 0:
        return {"combo": os.path.basename(outdir).replace("out_", ""), "n": 0}
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    d = realized(df).sort_values("entry_time").reset_index(drop=True)
    rr = d["r_multiple"].astype(float).values
    pnl = d["net_pnl"].astype(float).values

    # IS/OOS 70:30 (시간순)
    k = int(len(d) * 0.7)
    is_pf = pf(pnl[:k]) if k > 0 else float("nan")
    oos_pf = pf(pnl[k:]) if len(d) - k > 0 else float("nan")

    # 자본시뮬 (실현 기준) + 룩어헤드 테스트
    checked = test_capital_no_lookahead(d)
    _, final, mdd, curve = run_equity(d, rr)
    span_yr = max((d["exit_time"].max() - d["entry_time"].min()).days / 365.25, 1e-9)
    cagr = (final / 1750.0) ** (1 / span_yr) - 1 if final > 0 else float("nan")

    sharpe = float(rr.mean() / rr.std(ddof=1)) if len(rr) > 1 and rr.std(ddof=1) > 0 else float("nan")
    d6 = d[~d["symbol"].isin(CORE3)] if "symbol" in d.columns else d

    # 곡선 저장
    if curve:
        pd.DataFrame(curve, columns=["time", "equity"]).to_csv(os.path.join(outdir, "equity_curve_demo.csv"), index=False)

    return {
        "combo": os.path.basename(outdir).replace("out_", ""),
        "n": len(d), "win%": round((pnl > 0).mean() * 100, 1),
        "PF": round(pf(pnl), 3), "IS_PF": round(is_pf, 3), "OOS_PF": round(oos_pf, 3),
        "avgR": round(float(rr.mean()), 4), "Sharpe": round(sharpe, 3), "sumR": round(float(rr.sum()), 1),
        "final$": round(final, 1), "x_dep": round(final / 1750.0, 2),
        "CAGR%": round(cagr * 100, 1), "MDD%": round(mdd * 100, 1),
        "rest6_PF": round(pf(d6["net_pnl"].values), 3) if len(d6) else float("nan"),
        "LA_checked": checked,
    }


def main():
    dirs = sys.argv[1:] if len(sys.argv) > 1 else [f"out_{k}" for k in KEYS]
    rows = []
    for d in dirs:
        if not os.path.exists(d):
            print(f"[skip] {d} 없음"); continue
        r = analyze(d)
        if r:
            rows.append(r)
            print(f"  ok {r['combo']:32} n={r.get('n')}  OOS_PF={r.get('OOS_PF')}  final=${r.get('final$')}  LA={r.get('LA_checked')}")
    if not rows:
        print("결과 없음"); return
    df = pd.DataFrame(rows)
    df = df.sort_values(["OOS_PF", "sumR"], ascending=False, na_position="last").reset_index(drop=True)
    df.to_csv("combo_capital_summary.csv", index=False)
    print("\n" + "=" * 110)
    print("  12조합 + 대조군 — 게이트 실백테스트 + 자본시뮬 (실현기준, 정렬: OOS_PF→sumR)")
    print("=" * 110)
    print(df.to_string(index=False))
    print("\n→ combo_capital_summary.csv 저장. 룩어헤드(LA_checked) 전 조합 0불일치 통과.")


if __name__ == "__main__":
    main()
