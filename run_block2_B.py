#!/usr/bin/env python3
# 블록2 실측: 미측정 원자 변별력 최대후보 solo 진짜게이트 (기존 원자, 패치불필요)
import os, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)
import numpy as np, pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost
SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys()); REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2023, 2024, 2025, 2026]
GATES = [("a_ob(OB존재)", "a_ob"), ("~a_ob(OB없음)", "~a_ob"), ("a_score_ge13(≥10)", "a_score_ge13"),
         ("a_pre_total_ge1(pt≥1)", "a_pre_total_ge1"), ("a_pre_total_ge4(pt≥3)", "a_pre_total_ge4"),
         ("a_sweep_count_2_4", "a_sweep_count_2_4")]
def _pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))
def _rmdd(r):
    cum = np.cumsum(np.asarray(r, float)); pk = np.maximum.accumulate(cum) if len(cum) else cum
    return float((cum - pk).min()) if len(cum) else 0.0
def reset_prepared(prepared):
    for s in SYMBOLS:
        for z in prepared[s]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"): z.pop(k, None)
            z["used"] = False
def solo(prepared, gate):
    os.environ["ATOM_AND_LIST"] = gate; reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    d = res["trades"]; d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
    r = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    n = len(d); k = int(n * 0.7); yr = d["exit_time"].dt.year
    pfy = {y: _pf(pnl[(yr == y).values]) for y in YEARS if (yr == y).any()}; d6 = d[~d["symbol"].isin(REST6)]
    return {"n": n, "win%": round(float((pnl > 0).mean() * 100), 1), "PF": round(_pf(pnl), 3),
            "IS": round(_pf(pnl[:k]), 3), "OOS": round(_pf(pnl[k:]), 3), "expR": round(float(r.mean()), 4),
            "MDD_R": round(_rmdd(r), 1), "r6_PF": round(_pf(d6["net_pnl"].astype(float).values), 3),
            "pf2026": round(pfy.get(2026, float("nan")), 3), "allge1": all(v >= 1 for v in pfy.values()) and len(pfy) > 0}
def main():
    print("[STEP1] indicators 9심볼 1회"); t0 = time.time()
    prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s"); sim.USE_COMBO_UNION = False; rows = []
    for label, gate in GATES:
        t1 = time.time(); m = solo(prepared, gate); m.update({"run": label}); rows.append(m)
        print(f"  [{label}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} expR={m['expR']} "
              f"MDD_R={m['MDD_R']} 2026={m['pf2026']} 매년삶={m['allge1']} ({time.time()-t1:.0f}s)")
    df = pd.DataFrame(rows)[["run", "n", "win%", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1"]]
    os.makedirs("block2_result", exist_ok=True); df.to_csv("block2_result/block2_solo.csv", index=False)
    print("\n" + "=" * 100); print("블록2 실측: 미측정 원자 solo OOS"); print("=" * 100)
    print(df.to_string(index=False)); print("\n[저장] block2_result/block2_solo.csv")
if __name__ == "__main__":
    main()
