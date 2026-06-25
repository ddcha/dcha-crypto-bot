#!/usr/bin/env python3
# =========================================================================
# run_negcut2_union.py — setups_pf12_negcut2.json(12셋업) union 게이트 단일 백테스트 + 자본시뮬
#   negcut(14)에서 또 음수난 2셋업(efficiency+ob+wick, fvg+score+volume+wick) 제거 = 12셋업.
#   핵심: 12셋업(pf14<)에서 강제대체로 또 변질되나. 새 음수셋업 등장 관찰.
#   독립 프로세스 1패스 + 멱등성 assert + 룩어헤드 통과 후 자본시뮬.
#   전체 + 역추세(a_trend_align=False) 둘 다 지표.
# =========================================================================
import os, json, time
os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["USE_COMBO_UNION"] = "1"
os.environ["COMBO_UNION_JSON"] = "setups_pf12_negcut2.json"
os.environ["ATOM_AND_LIST"] = ""
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6_EXCLUDE = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
YEARS = [2022, 2023, 2024, 2025, 2026]
SEED, MONTHLY, NDEP, RISK_PCT = 500.0, 250.0, 5, 0.01
TOTAL_DEP = SEED + MONTHLY * NDEP
SETUPS_JSON = "setups_pf12_negcut2.json"
OUTDIR = "pf12_negcut2_union_result"
REF_ALL = {"n": 1181, "PF": 1.25, "OOS": 1.28}      # 추가제거 사후값 (전체)
REF_CT = {"n": 489, "PF": 1.33, "OOS": 1.66}        # 역추세 사후값

SETUPS = json.load(open(SETUPS_JSON, encoding="utf-8"))


def _pf(p):
    p = np.asarray(p, float); gp = p[p > 0].sum(); gl = -p[p < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def _realized(t):
    if "exit_reason" in t:
        return t[~t["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return t


def attribute(getter):
    matched = []
    for idx, su in enumerate(SETUPS):
        if all(bool(getter(a)) for a in su["atoms"]):
            matched.append((idx, su["key"], len(su["atoms"])))
    if not matched:
        return "", 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]
    return best[1], len(matched)


def reset_prepared(prepared):
    for sym in prepared:
        for s in prepared[sym]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                s.pop(k, None)
            s["used"] = False


def run_equity(g, rvals, seed=SEED, monthly=MONTHLY, nd=NDEP, rp=RISK_PCT):
    ET = list(g["entry_time"]); XT = list(g["exit_time"])
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = start
    for _ in range(nd):
        m = m + pd.offsets.MonthBegin(1); deps.append((m, monthly))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 0, i)); ev.append((XT[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]
    ev.sort(key=lambda x: (x[0], x[1]))
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
    ET = g["entry_time"]; XT = g["exit_time"]; r_base = g["r_multiple"].values.astype(float)
    eq0, _, _ = run_equity(g, r_base); rng = np.random.default_rng(7)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01",
                             "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (XT >= T).values; past = g.index[ET <= T]
        for _ in range(50):
            r2 = r_base.copy()
            if fut.any():
                r2[fut] = rng.uniform(-5, 5, int(fut.sum()))
            eq1, _, _ = run_equity(g, r2)
            for i in past:
                checked += 1
                if abs(eq0.get(i, 0.0) - eq1.get(i, 0.0)) > 1e-9:
                    mism += 1
    return mism, checked


def r_unit_mdd(r):
    cum = np.cumsum(np.asarray(r, float))
    peak = np.maximum.accumulate(cum) if len(cum) else cum
    return float((cum - peak).min()) if len(cum) else 0.0


def metrics(name, trades, with_capital):
    d = _realized(trades).copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values; rr = d["r_multiple"].astype(float).values
    n = len(d); k = int(n * 0.7)
    row = {"name": name, "n": n,
           "win_pct": round(float((pnl > 0).mean() * 100), 2),
           "PF": round(_pf(pnl), 4), "IS_PF": round(_pf(pnl[:k]), 4), "OOS_PF": round(_pf(pnl[k:]), 4),
           "oosN": n - k, "expR": round(float(rr.mean()), 4),
           "Sharpe": round(float(rr.mean() / rr.std(ddof=1)), 4) if n > 1 and rr.std(ddof=1) > 0 else float("nan"),
           "MDD_R": round(r_unit_mdd(rr), 3), "tot_R": round(float(rr.sum()), 2)}
    d6 = d[~d["symbol"].isin(REST6_EXCLUDE)]
    row["r6_PF"] = round(_pf(d6["net_pnl"].astype(float).values), 4); row["r6_n"] = int(len(d6))
    yr = d["exit_time"].dt.year; all_ge1 = True; any_y = False
    for y in YEARS:
        s = d[yr == y]
        if len(s) > 0:
            pfy = _pf(s["net_pnl"].astype(float).values); row[f"pf_{y}"] = round(pfy, 4)
            row[f"n_{y}"] = int(len(s)); any_y = True
            if pfy < 1.0:
                all_ge1 = False
    row["all_years_ge1"] = bool(all_ge1 and any_y)
    if with_capital:
        de = d.sort_values("entry_time").reset_index(drop=True)
        mism, checked = test_capital_no_lookahead(de)
        if mism != 0:
            raise SystemExit(f"[ABORT] 자본 룩어헤드 누수 {mism}/{checked}")
        _, final, mdd = run_equity(de, de["r_multiple"].astype(float).values)
        yrs = max((de["exit_time"].max() - de["entry_time"].min()).days / 365.25, 1e-9)
        row["final_cap"] = round(final, 2); row["mult_vs_dep"] = round(final / TOTAL_DEP, 4)
        row["CAGR_pct"] = round(((final / TOTAL_DEP) ** (1 / yrs) - 1) * 100, 2) if final > 0 else float("nan")
        row["MDD_cap_pct"] = round(mdd * 100, 2); row["LA_mismatch"] = mism; row["LA_checked"] = checked
    return row


def setup_breakdown(trades):
    d = _realized(trades).copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    rows = []
    for key, grp in d.groupby("matched_setup"):
        g = grp.sort_values("exit_time").reset_index(drop=True)
        pnl = g["net_pnl"].astype(float).values; rr = g["r_multiple"].astype(float).values
        n = len(g); k = int(n * 0.7)
        rows.append({"matched_setup": key, "n": n,
                     "win_pct": round(float((pnl > 0).mean() * 100), 2),
                     "expR": round(float(rr.mean()), 4),
                     "PF": round(_pf(pnl), 4),
                     "IS_PF": round(_pf(pnl[:k]), 4) if k > 0 else float("nan"),
                     "OOS_PF": round(_pf(pnl[k:]), 4) if n - k > 0 else float("nan"),
                     "MDD_R": round(r_unit_mdd(rr), 2),
                     "tot_R": round(float(rr.sum()), 2),
                     "n_atoms": len(next((s["atoms"] for s in SETUPS if s["key"] == key), []))})
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def _print_metrics(row, title, with_capital):
    print("\n" + "=" * 70); print(f"=== {title} ==="); print("=" * 70)
    for k in ["n", "win_pct", "PF", "IS_PF", "OOS_PF", "oosN", "expR", "Sharpe", "MDD_R", "tot_R",
              "r6_PF", "r6_n", "all_years_ge1"]:
        print(f"  {k:14s}: {row.get(k)}")
    print("  연도별 PF/거래수:")
    for y in YEARS:
        if f"pf_{y}" in row:
            mark = "  ← 2026" if y == 2026 else ""
            print(f"    {y}: PF={row[f'pf_{y}']:<8} n={row.get(f'n_{y}')}{mark}")
    if with_capital:
        print("  자본 시뮬(시드500+250x5 flat, RISK 1%):")
        print(f"    final_cap={row['final_cap']}  mult={row['mult_vs_dep']}x  CAGR={row['CAGR_pct']}%  "
              f"MDD_cap={row['MDD_cap_pct']}%")
        print(f"    룩어헤드 LA={row['LA_mismatch']}/{row['LA_checked']}")


def _ref_compare(row, ref, label):
    dn = abs(row["n"] - ref["n"]) / ref["n"] * 100
    dpf = abs(row["PF"] - ref["PF"]) / ref["PF"] * 100
    doos = abs(row["OOS_PF"] - ref["OOS"]) / ref["OOS"] * 100
    print(f"\n  [{label}] 거래 {row['n']}/{ref['n']}(Δ{dn:.1f}%) | PF {row['PF']}/{ref['PF']}(Δ{dpf:.1f}%) | "
          f"OOS {row['OOS_PF']}/{ref['OOS']}(Δ{doos:.1f}%) → {'⚠️거래수15%+괴리' if dn > 15 else 'OK'}")
    return dn


def main():
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} HONEST_STAGE={os.environ['HONEST_STAGE']} | "
          f"셋업 {len(SETUPS)}개(negcut2) | 자본 시드{SEED}+{MONTHLY}x{NDEP}")

    print("\n[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    print("\n[STEP2] candidates(union 12셋업) — 멱등성 2패스")
    t1 = time.time()
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    n1 = sum(len(cand[s]["candidates"]) for s in SYMBOLS)
    reset_prepared(prepared)
    n2 = sum(len(generate_candidates_from_prepared(prepared[s])["candidates"]) for s in SYMBOLS)
    print(f"  [멱등성] 1패스 {n1} / 2패스 {n2}")
    assert n1 == n2, f"[ABORT] 비멱등 {n1}!={n2}"
    print("  → 멱등성 OK")
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    trades = res["trades"].copy()
    print(f"[STEP2] 완료 {time.time()-t1:.0f}s | 진입 거래 {len(trades)}")

    print("\n[STEP3] 최대원자 귀속")
    labels = trades.apply(lambda r: attribute(lambda a: r.get(a, False)), axis=1)
    trades["matched_setup"] = [x[0] for x in labels]
    trades["n_setups_matched"] = [x[1] for x in labels]
    zero = int((trades["n_setups_matched"] == 0).sum())
    print(f"  진입 {len(trades)} 중 매칭0 = {zero}")
    if zero != 0:
        raise SystemExit(f"[ABORT] post-hoc 매칭0 {zero}건")
    print(f"  → 전부 ≥1 매칭. n_setups_matched min/med/max = "
          f"{int(trades['n_setups_matched'].min())}/{int(trades['n_setups_matched'].median())}/{int(trades['n_setups_matched'].max())}")
    ALL_ATOMS = sorted({a for s in SETUPS for a in s["atoms"]})
    for _, r in trades.head(3).iterrows():
        ta = [a for a in ALL_ATOMS if bool(r.get(a, False))]
        print(f"    {r['symbol']} {r['entry_time']} | true={ta} → {r['matched_setup']} (n={r['n_setups_matched']})")

    os.makedirs(OUTDIR, exist_ok=True)
    trades.to_csv(os.path.join(OUTDIR, "trades.csv"), index=False)
    print(f"\n[저장] {OUTDIR}/trades.csv ({len(trades)}행, +matched_setup +n_setups_matched +a_trend_align)")

    # 전체
    row_all = metrics("negcut2_all", trades, with_capital=True)
    _print_metrics(row_all, "전체 (negcut2, 12셋업)", with_capital=True)
    # 역추세 (a_trend_align == False)
    ct = trades[~trades["a_trend_align"].astype(bool)]
    row_ct = metrics("negcut2_countertrend", ct, with_capital=False)
    _print_metrics(row_ct, "역추세만 (a_trend_align=False)", with_capital=False)

    pd.DataFrame([row_all, row_ct]).to_csv(os.path.join(OUTDIR, "summary.csv"), index=False)

    # 사후값 비교
    print("\n=== 추가제거 사후값 대비 ===")
    _ref_compare(row_all, REF_ALL, "전체")
    _ref_compare(row_ct, REF_CT, "역추세")

    # 셋업별 표 + 음수셋업 플래그
    bd = setup_breakdown(trades)
    bd.to_csv(os.path.join(OUTDIR, "setup_breakdown.csv"), index=False)
    print("\n=== 셋업별 (n/승률/기대R/PF/IS/OOS/MDD_R/총R) ===")
    print(bd.to_string(index=False))
    neg = bd[bd["tot_R"] < 0]
    print("\n=== 음수셋업(총R<0) — 강제대체 변질 관찰 ===")
    if len(neg) == 0:
        print("  없음 ✅ (새 음수셋업 미등장)")
    else:
        print(f"  ⚠️ {len(neg)}개 등장:")
        for _, r in neg.iterrows():
            print(f"    {r['matched_setup']}: 총R={r['tot_R']} PF={r['PF']} OOS={r['OOS_PF']} n={r['n']}")

    # 판정
    verdict = "pf12형 견고" if (row_all["OOS_PF"] >= 1.0 and row_all["all_years_ge1"]) else "약화(OOS<1 또는 매년실패)"
    print(f"\n[판정] {verdict} | 음수셋업 {len(neg)}개 | "
          f"{'강제대체 플래그' if (len(neg) > 0 or abs(row_all['n']-REF_ALL['n'])/REF_ALL['n']*100 > 15) else '안정'}")
    print(f"\n[저장 완료] {OUTDIR}/ (trades.csv, summary.csv, setup_breakdown.csv)")


if __name__ == "__main__":
    main()
