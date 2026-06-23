#!/usr/bin/env python3
# =========================================================================
# tools/combo_tier_capital.py — union 런에 atom-tier + 시드500 자본시뮬 (후처리)
#
#   COMBO_UNION_FIX_SPEC #2/#3/#4 를 '후처리'로 적용(엔진 재실행 불필요):
#     #1 refine: 이미 ON (h1_refined 38.5%) — 재실행 불필요.
#     #2 atom-tier: assign_tier(fvg/vol/eff/volume) → S1/S2/A/None
#     #3 tier mult: S1=2.0 / S2=1.3 / A=1.0
#     #4 자본: run_equity 시드500 + 월말250×5, 룩어헤드 안전
#   atom-tier/tier_mult/balance/phase 컬럼을 박은 enriched trades.csv 도 저장.
#
#   ⚠️ assign_tier 는 ~fvg 를 제외 → score기반 union 거래(c02/c09)가 빠진다.
#     그래서 (A) 스펙-literal(fvg-tier만) 과 (B) keep-all(비fvg=base 1.0x) 둘 다 리포트.
# =========================================================================
import os, sys
import numpy as np, pandas as pd

CORE3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIER_RISK_MULT = {"S1": 2.0, "S2": 1.3, "A": 1.0, "BASE": 1.0}


def assign_tier(fvg, vol, eff, volume):
    if not fvg:
        return None
    if vol and eff:
        return "S1" if volume else "S2"
    if vol ^ eff:
        return "A"
    return None


def run_equity(g, rvals, tiers, seed=500.0, monthly=250.0, nd=5, rp=0.01, risk_mult=None):
    ET, XT = g["entry_time"].values, g["exit_time"].values
    et_min = pd.Timestamp(g["entry_time"].min()).normalize().replace(day=1)
    deps = []; m = et_min
    for _ in range(nd):
        nxt = m + pd.offsets.MonthBegin(1); deps.append((np.datetime64(nxt), monthly)); m = nxt
    ev = []
    for i in range(len(g)):
        ev.append((ET[i], 0, i)); ev.append((XT[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]; ev.sort(key=lambda x: (x[0], x[1]))
    rm = risk_mult or {}
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0; curve = []
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * rm.get(tiers[p], 1.0) * realized; eq[p] = realized
        elif pri == 1:
            realized += (-p)
        else:
            realized += rvals[p] * ra.get(p, 0.0)
            peak = max(peak, realized); mdd = min(mdd, (realized - peak) / peak); curve.append((ts, realized))
    return eq, realized, mdd, curve


def test_capital_no_lookahead(g, tiers):
    ET, XT = g["entry_time"], g["exit_time"]; r_base = g["r_multiple"].values.copy()
    eq0, *_ = run_equity(g, r_base, tiers, risk_mult=TIER_RISK_MULT); rng = np.random.default_rng(7)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (XT >= T).values; past = g.index[ET <= T]
        for _ in range(50):
            r2 = r_base.copy(); r2[fut] = rng.uniform(-5, 5, fut.sum())
            eq1, *_ = run_equity(g, r2, tiers, risk_mult=TIER_RISK_MULT)
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
    return df[~df["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in df else df


def stat(d):
    rr = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    if len(d) == 0:
        return {"n": 0}
    k = int(len(d) * 0.7)
    return {"n": len(d), "win%": round((pnl > 0).mean() * 100, 1), "PF": round(pf(pnl), 3),
            "IS_PF": round(pf(pnl[:k]), 3) if k else float("nan"),
            "OOS_PF": round(pf(pnl[k:]), 3) if len(d) - k else float("nan"),
            "avgR": round(float(rr.mean()), 4), "sumR": round(float(rr.sum()), 1)}


def deposit_phase(et, et_min, nd=5):
    # 입금 도착(다음달 1일) 누적 개수로 0..nd 단계
    base = et_min.normalize().replace(day=1)
    arrivals = [(base + pd.offsets.MonthBegin(i + 1)) for i in range(nd)]
    return f"P{sum(1 for a in arrivals if et >= a)}"


def main():
    rundir = sys.argv[1] if len(sys.argv) > 1 else "combo_union_run"
    df = pd.read_csv(os.path.join(rundir, "stage4d_trades.csv"))
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    d = realized(df).sort_values("entry_time").reset_index(drop=True)

    # atom-tier 부여
    d["atom_tier"] = [assign_tier(bool(r.a_fvg), bool(r.a_vol_expansion), bool(r.a_efficiency), bool(r.a_volume))
                      for r in d.itertuples()]
    d["atom_tier_keepall"] = d["atom_tier"].fillna("BASE")  # 비fvg 도 base 1.0x 로 유지
    d["atom_tier_mult"] = d["atom_tier_keepall"].map(TIER_RISK_MULT)

    print("=== atom_tier 분포 (스펙 literal: None=제외) ===")
    print(d["atom_tier"].value_counts(dropna=False).to_dict())
    n_excl = d["atom_tier"].isna().sum()
    print(f"  None(제외) {n_excl}건 = 비fvg/ fvg-only — 이 안에 score조합(c02/c09) 포함")

    et_min = d["entry_time"].min()
    d["phase_at_entry"] = [deposit_phase(t, et_min) for t in d["entry_time"]]

    # (A) 스펙-literal: tier 있는(S1/S2/A) 거래만, tier mult
    A = d[d["atom_tier"].notna()].reset_index(drop=True)
    tiersA = A["atom_tier"].values
    chkA = test_capital_no_lookahead(A, tiersA)
    eqA, finA, mddA, curveA = run_equity(A, A["r_multiple"].values, tiersA, risk_mult=TIER_RISK_MULT)
    A["balance_at_entry"] = [eqA.get(i, np.nan) for i in range(len(A))]

    # (B) keep-all: 전 union 거래, 비fvg=BASE 1.0x
    tiersB = d["atom_tier_keepall"].values
    eqB, finB, mddB, curveB = run_equity(d, d["r_multiple"].values, tiersB, risk_mult=TIER_RISK_MULT)
    d["balance_at_entry"] = [eqB.get(i, np.nan) for i in range(len(d))]

    yrA = max((A["exit_time"].max() - A["entry_time"].min()).days / 365.25, 1e-9)
    yrB = max((d["exit_time"].max() - d["entry_time"].min()).days / 365.25, 1e-9)

    print("\n=== (A) 스펙-literal: S1/S2/A 만 (비fvg 제외), tier mult 2.0/1.3/1.0 ===")
    print(f"  거래 {len(A)} | 최종 ${finA:.0f} (시드+납입 1750 대비 {finA/1750:.2f}x) | CAGR {((finA/1750)**(1/yrA)-1)*100:.1f}% | MDD {mddA*100:.1f}% | 룩어헤드 {chkA}건/0불일치")
    rows = []
    for t in ["S1", "S2", "A"]:
        rows.append({"tier": t, "mult": TIER_RISK_MULT[t], **stat(A[A["atom_tier"] == t])})
    rows.append({"tier": "ALL(A)", "mult": "-", **stat(A)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== (B) keep-all: 전 union, 비fvg=BASE 1.0x ===")
    print(f"  거래 {len(d)} | 최종 ${finB:.0f} ({finB/1750:.2f}x) | CAGR {((finB/1750)**(1/yrB)-1)*100:.1f}% | MDD {mddB*100:.1f}%")
    rows = []
    for t in ["S1", "S2", "A", "BASE"]:
        rows.append({"tier": t, "mult": TIER_RISK_MULT[t], **stat(d[d["atom_tier_keepall"] == t])})
    print(pd.DataFrame(rows).to_string(index=False))

    # enriched trades 저장 (체크리스트용)
    keep = ["entry_time", "exit_time", "symbol", "type", "r_multiple", "net_pnl", "exit_reason",
            "combos_matched", "h1_refined", "disp_atr_mult", "ob_mode",
            "a_fvg", "a_vol_expansion", "a_efficiency", "a_volume",
            "atom_tier", "atom_tier_mult", "balance_at_entry", "phase_at_entry"]
    keep = [c for c in keep if c in d.columns]
    d[keep].to_csv(os.path.join(rundir, "trades_tiered_capital.csv"), index=False)
    print(f"\n→ {rundir}/trades_tiered_capital.csv 저장 (atom_tier/tier_mult/balance/phase 박음)")

    # §6 self-verify
    print("\n=== §6 체크리스트 self-verify (enriched, keep-all 기준) ===")
    ck = {
        "h1_refined True 존재": bool(d["h1_refined"].any()) if "h1_refined" in d else False,
        "atom_tier = S1/S2/A 존재": set(d["atom_tier"].dropna().unique()) <= {"S1", "S2", "A"} and d["atom_tier"].notna().any(),
        "atom_tier_mult 2.0/1.3/1.0 분포": set(np.round(d["atom_tier_mult"].unique(), 2)) <= {2.0, 1.3, 1.0},
        "balance 시작 ≈ 500": abs(float(d["balance_at_entry"].iloc[0]) - 500) < 1.0,
        "phase 다단계": d["phase_at_entry"].nunique() >= 2,
        "combos_matched union 유지": d["combos_matched"].astype(str).str.contains(r"\|").any(),
        "룩어헤드 0불일치": chkA > 0,
    }
    for k, v in ck.items():
        print(f"  [{'OK' if v else 'X '}] {k}")


if __name__ == "__main__":
    main()
