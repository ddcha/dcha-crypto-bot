#!/usr/bin/env python3
# =========================================================================
# run_atom_alpha_B.py — 단계B: 변별력 후보 임계로 solo 게이트 진짜 백테스트 (현재값 대비)
#   각 원자 solo(ATOM_AND_LIST=원자) 를 현재값/알파값으로 실행. raw r_multiple 기준.
#   prepared 1회 재사용, 패스마다 _ls_*+used 리셋(멱등). config/엔진 무수정(런타임 패치).
# =========================================================================
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
import smc_stage4d.filters as F
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
YEARS = [2023, 2024, 2025, 2026]

# (라벨, 원자게이트, filters상수, 현재값, [테스트값들])
RUNS = [
    ("wick",     "a_wick_le_q1",    "BROAD_WICK_MAX",       0.35, [0.35, 0.17]),
    ("volume",   "a_volume",        "BROAD_VOL_RELVOL_MIN",  1.5, [1.5, 2.8]),
    ("fvg",      "a_fvg",           "BROAD_FVG_SIZE_ATR",   0.10, [0.10, 0.30]),
    ("vol_exp",  "a_vol_expansion", "REG_VOL_PCTL",         0.50, [0.50, 0.85]),
    ("eff",      "a_efficiency",    "REG_EFF_MIN",          0.30, [0.30, 0.65]),
    ("bb",       "a_bb_squeeze",    "REG_BB_SQUEEZE_PCTL",  0.30, [0.30, 0.15]),
]


def _pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))


def _rmdd(r):
    cum = np.cumsum(np.asarray(r, float)); pk = np.maximum.accumulate(cum) if len(cum) else cum
    return float((cum - pk).min()) if len(cum) else 0.0


def reset_prepared(prepared):
    for s in SYMBOLS:
        for z in prepared[s]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                z.pop(k, None)
            z["used"] = False


def solo(prepared, atom, val, const):
    setattr(F, const, val)
    os.environ["ATOM_AND_LIST"] = atom
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    d = res["trades"]
    d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    r = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    n = len(d); k = int(n * 0.7)
    yr = d["exit_time"].dt.year
    pf_y = {y: _pf(pnl[(yr == y).values]) for y in YEARS if (yr == y).any()}
    allge1 = all(v >= 1.0 for v in pf_y.values()) and len(pf_y) > 0
    d6 = d[~d["symbol"].isin(REST6)]
    return {"n": n, "win%": round(float((pnl > 0).mean() * 100), 1),
            "PF": round(_pf(pnl), 3), "IS": round(_pf(pnl[:k]), 3), "OOS": round(_pf(pnl[k:]), 3),
            "expR": round(float(r.mean()), 4), "MDD_R": round(_rmdd(r), 1),
            "r6_PF": round(_pf(d6["net_pnl"].astype(float).values), 3),
            "pf2026": round(pf_y.get(2026, float("nan")), 3), "allge1": allge1}


def main():
    print("[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")
    sim.USE_COMBO_UNION = False
    rows = []
    for label, atom, const, cur, vals in RUNS:
        for v in vals:
            t1 = time.time()
            m = solo(prepared, atom, v, const)
            tag = "현재" if v == cur else "테스트"
            m.update({"atom": label, "thr": v, "tag": tag})
            rows.append(m)
            print(f"  [{label} {const}={v} {tag}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} "
                  f"expR={m['expR']} MDD_R={m['MDD_R']} 2026={m['pf2026']} 매년삶={m['allge1']} ({time.time()-t1:.0f}s)")
    df = pd.DataFrame(rows)[["atom", "thr", "tag", "n", "win%", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1"]]
    os.makedirs("atom_alpha_result", exist_ok=True)
    df.to_csv("atom_alpha_result/stageB_solo.csv", index=False)
    print("\n" + "=" * 100)
    print("단계B: solo 게이트 OOS (현재값 vs 알파임계) — raw r_multiple 기준")
    print("=" * 100)
    print(df.to_string(index=False))
    print("\n[저장] atom_alpha_result/stageB_solo.csv")


if __name__ == "__main__":
    main()
