#!/usr/bin/env python3
# =========================================================================
# run_union.py — 조합 OR-union 게이트 단일 백테스트 ×2 (1501 / 257)
#
#   union 게이트: 후보의 원자플래그가 "조합 리스트 중 전원자 True 인 조합이 하나라도 있으면" 진입.
#   prepared(9심볼 지표/구조)는 1회만, union 조합셋만 바꿔 simulate 2번.
#   각 결과: 전체/IS/OOS PF·승률·avgR·Sharpe·나머지6·연도별·매년삶 + 시드500 자본시뮬 + 룩어헤드.
#   저장: union1501_result/ , union257_result/  (trades.csv + summary)
#
#   실행:  set STAGE4D_DLCACHE=data_cache & python run_union.py
#   baseline: OB_MODE=engulf, DISP_ATR_MULT=1.3, USE_H1_REFINE=1, risk_multiplier=1.0
# =========================================================================
import os, json, time
os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""        # union 게이트만 — AND/OR/ANYOTHER 비활성
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON"):
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6_EXCLUDE = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
YEARS = [2022, 2023, 2024, 2025, 2026]
SEED, MONTHLY, NDEP, RISK_PCT = 500.0, 250.0, 5, 0.01
TOTAL_DEP = SEED + MONTHLY * NDEP
RUNS = [("union1501", "combos_1501.json"), ("union257", "combos_filtered.json")]


def _pf(p):
    p = np.asarray(p, float); gp = p[p > 0].sum(); gl = -p[p < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def _realized(t):
    return t[~t["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)] if "exit_reason" in t else t


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
    ev.sort(key=lambda x: (x[0], x[1]))           # 진입<입금<청산
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


def summarize(name, trades):
    d = _realized(trades).copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values; rr = d["r_multiple"].astype(float).values
    n = len(d); k = int(n * 0.7)
    row = {"name": name, "n": n,
           "win_pct": round(float((pnl > 0).mean() * 100), 2),
           "PF": round(_pf(pnl), 4), "IS_PF": round(_pf(pnl[:k]), 4), "OOS_PF": round(_pf(pnl[k:]), 4),
           "oosN": n - k, "avgR": round(float(rr.mean()), 4),
           "Sharpe": round(float(rr.mean() / rr.std(ddof=1)), 4) if rr.std(ddof=1) > 0 else float("nan")}
    d6 = d[~d["symbol"].isin(REST6_EXCLUDE)]
    row["r6_PF"] = round(_pf(d6["net_pnl"].astype(float).values), 4)
    yr = d["exit_time"].dt.year; all_ge1 = True; any_y = False
    for y in YEARS:
        s = d[yr == y]
        if len(s) > 0:
            pfy = _pf(s["net_pnl"].astype(float).values); row[f"pf_{y}"] = round(pfy, 4); any_y = True
            if pfy < 1.0:
                all_ge1 = False
    row["all_years_ge1"] = bool(all_ge1 and any_y)
    # 자본 시뮬 (entry 순)
    de = d.sort_values("entry_time").reset_index(drop=True)
    mism, checked = test_capital_no_lookahead(de)
    _, final, mdd = run_equity(de, de["r_multiple"].astype(float).values)
    yrs = max((de["exit_time"].max() - de["entry_time"].min()).days / 365.25, 1e-9)
    row["final_cap"] = round(final, 2); row["mult_vs_dep"] = round(final / TOTAL_DEP, 4)
    row["CAGR_pct"] = round(((final / TOTAL_DEP) ** (1 / yrs) - 1) * 100, 2) if final > 0 else float("nan")
    row["MDD_pct"] = round(mdd * 100, 2)
    row["LA_mismatch"] = mism; row["LA_checked"] = checked
    row["refine_pct"] = round(float(d["entry_refined"].astype(bool).mean() * 100), 1) if "entry_refined" in d else float("nan")
    return row


def main():
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} | risk_mult=1.0 | 자본 시드{SEED}+{MONTHLY}x{NDEP}")
    # STEP1: prepared 1회
    print("\n[STEP1] 데이터 + apply_indicators_and_build (9심볼 1회)")
    t0 = time.time(); prepared = {sym: apply_indicators_and_build(download_symbol_data(sym)) for sym in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    sim.USE_COMBO_UNION = True                  # union 게이트 ON (런타임)
    rows = []
    for name, jf in RUNS:
        if not os.path.exists(jf):
            print(f"[skip] {jf} 없음"); continue
        atomsets = [list(c["atoms"]) for c in json.load(open(jf, encoding="utf-8"))]
        sim.COMBO_UNION_ATOMSETS = atomsets     # union 조합셋만 교체
        print(f"\n[RUN] {name}: {jf} ({len(atomsets)}조합 OR 게이트) simulate")
        t1 = time.time()
        cand = {sym: generate_candidates_from_prepared(prepared[sym]) for sym in SYMBOLS}
        res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
        trades = res["trades"]
        outdir = f"{name}_result"; os.makedirs(outdir, exist_ok=True)
        trades.to_csv(os.path.join(outdir, "trades.csv"), index=False)
        row = summarize(name, trades)
        pd.DataFrame([row]).to_csv(os.path.join(outdir, "summary.csv"), index=False)
        rows.append(row)
        print(f"[RUN] {name} 완료 {time.time()-t1:.0f}s | n={row['n']} PF={row['PF']} OOS={row['OOS_PF']} "
              f"자본=${row['final_cap']}({row['mult_vs_dep']}x) CAGR={row['CAGR_pct']}% MDD={row['MDD_pct']}% "
              f"LA={row['LA_mismatch']}/{row['LA_checked']}")

    if rows:
        pd.DataFrame(rows).to_csv("union_summary.csv", index=False)
        print("\n=== 요약 (union_summary.csv) ===")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
