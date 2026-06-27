#!/usr/bin/env python3
# 2단계: 확정 10원자 태깅 + 게이트OFF 베이스 백테스트. (room swing60 영구반영 후)
#   폐기원자 제외. ~fvg/~trend 는 뒤집어 태깅(a_fvg_absent / a_trend_counter).
#   a_vol_expansion 은 확정임계 0.85 로 태깅(REG_VOL_PCTL 런타임 패치).
import os, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
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
REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2023, 2024, 2025, 2026]
OUTDIR = "tagged_base_result"
# 확정 임계: a_vol_expansion 0.85 (조임)
F.REG_VOL_PCTL = 0.85
ATOMS10 = ["a_score_ge13", "a_fvg_absent", "a_volume", "a_room", "a_ob",
           "a_vol_expansion", "a_sweep", "a_mss", "a_trend_counter", "a_bb_squeeze"]


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


def metrics(d):
    d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
    r = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    n = len(d); k = int(n * 0.7); yr = d["exit_time"].dt.year
    pfy = {y: _pf(pnl[(yr == y).values]) for y in YEARS if (yr == y).any()}
    return {"n": n, "PF": round(_pf(pnl), 3), "IS": round(_pf(pnl[:k]), 3), "OOS": round(_pf(pnl[k:]), 3),
            "expR": round(float(r.mean()), 4), "MDD_R": round(_rmdd(r), 1),
            "pf2026": round(pfy.get(2026, float("nan")), 3), "allge1": all(v >= 1 for v in pfy.values()) and len(pfy) > 0,
            "pfy": {y: round(v, 3) for y, v in pfy.items()}}


def main():
    print(f"[INFO] baseline engulf/1.3/refine1/honest5 | a_vol_expansion 임계 REG_VOL_PCTL={F.REG_VOL_PCTL} | room=swing60(영구)")
    print("\n[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s"); sim.USE_COMBO_UNION = False

    # 멱등성 2패스
    print("\n[STEP2] candidate 멱등성 2패스 + base simulate")
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    n1 = sum(len(cand[s]["candidates"]) for s in SYMBOLS)
    reset_prepared(prepared)
    n2 = sum(len(generate_candidates_from_prepared(prepared[s])["candidates"]) for s in SYMBOLS)
    print(f"  [멱등성] 1패스 {n1} / 2패스 {n2}")
    assert n1 == n2, f"[ABORT] 비멱등 {n1}!={n2}"
    print("  → 멱등 OK")
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    trades = res["trades"].copy()
    print(f"[STEP2] base 거래 {len(trades)}")

    # ── 10원자 태깅 (뒤집기: a_fvg_absent, a_trend_counter) ──
    trades["a_fvg_absent"] = ~trades["a_fvg"].astype(bool)
    trades["a_trend_counter"] = ~trades["a_trend_align"].astype(bool)
    for a in ATOMS10:
        trades[a] = trades[a].astype(bool)
    trades["n_atoms_true"] = trades[ATOMS10].sum(axis=1).astype(int)
    trades["atoms_true"] = trades[ATOMS10].apply(lambda row: ",".join([a for a in ATOMS10 if row[a]]) or "(none)", axis=1)

    os.makedirs(OUTDIR, exist_ok=True)
    trades.to_csv(os.path.join(OUTDIR, "trades_tagged.csv"), index=False)
    print(f"[저장] {OUTDIR}/trades_tagged.csv ({len(trades)}행, +10원자 +n_atoms_true +atoms_true)")

    # ── self-check: room swing60 통과율 + a_room solo OOS(측정때 1.11) ──
    print("\n[SELF-CHECK] room swing60")
    rl = trades[~trades["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    print(f"  a_room 통과율(base): {rl['a_room'].mean()*100:.1f}%")
    os.environ["ATOM_AND_LIST"] = "a_room"; reset_prepared(prepared)
    cr = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    mr = metrics(simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cr, risk_multiplier=1.0)["trades"])
    os.environ["ATOM_AND_LIST"] = ""
    print(f"  a_room solo: n={mr['n']} OOS={mr['OOS']} 매년삶={mr['allge1']} (측정때 n≈1677 OOS≈1.11 매년삶 True)")
    print(f"  → {'✅ 일치' if abs(mr['OOS']-1.11)<0.05 else '⚠️ 불일치 — 확인필요'}")
    print("  [룩어헤드] a_room=high/low[entry_idx-60..entry_idx] (entry_idx=정직신호봉 i-1 이하만) — 구조상 미래참조 0")

    # ── 베이스 지표 + 원자 통과율 ──
    m = metrics(trades)
    print("\n" + "=" * 70); print("=== 베이스(게이트OFF) 지표 ==="); print("=" * 70)
    for kk in ["n", "PF", "IS", "OOS", "expR", "MDD_R", "pf2026", "allge1"]:
        print(f"  {kk:10s}: {m.get(kk)}")
    print(f"  연도별 PF: {m['pfy']}")
    print(f"\n  평균 n_atoms_true(10중): {trades.loc[rl.index, 'n_atoms_true'].mean():.2f}")
    print("  원자별 통과율(realized base):")
    for a in ATOMS10:
        print(f"    {a:18s}: {rl[a].mean()*100:5.1f}%")
    print(f"\n[저장 완료] {OUTDIR}/trades_tagged.csv — 사후 조합분석용")


if __name__ == "__main__":
    main()
