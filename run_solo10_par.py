#!/usr/bin/env python3
# 병렬판: 확정 10원자 solo 게이트 백테스트(10번) + 태깅.
#   ① indicators 멀티프로세싱(심볼 병렬) ② prepared pickle 캐시 ③ 게이트 내 9심볼 candidate 병렬.
#   room swing60 영구반영 후. 확정임계 REG_VOL_PCTL=0.85, BROAD_FVG_SIZE_ATR=0(→~a_fvg=FVG없음).
import os, sys, time, pickle
import multiprocessing as mp

CACHE = "prepared_cache.pkl"
SYMBOLS = None  # set in main


def _setup_env_patches():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    os.environ["ATOM_OR_LIST"] = ""
    for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
        os.environ.pop(_k, None)
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85
    F.BROAD_FVG_SIZE_ATR = 0.0
    return F


# ── indicators 워커 ──
def _build_one(sym):
    _setup_env_patches()
    from smc_stage4d.data import download_symbol_data
    from smc_stage4d.structures import apply_indicators_and_build
    return sym, apply_indicators_and_build(download_symbol_data(sym))


# ── candidate 워커 (Pool initializer 로 prepared 로드) ──
_PREP = None
def _init_worker(cache_path):
    _setup_env_patches()
    global _PREP
    with open(cache_path, "rb") as f:
        _PREP = pickle.load(f)


def _gen_one(args):
    sym, gate = args
    os.environ["ATOM_AND_LIST"] = gate
    import smc_stage4d.simulation as sim
    sim.USE_COMBO_UNION = False
    out = sim.generate_candidates_from_prepared(_PREP[sym])   # 엔진이 _ls_* 리셋(멱등)
    return sym, out["candidates"]


def build_prepared(symbols, ncore):
    if os.path.exists(CACHE):
        print(f"[CACHE] {CACHE} 로드");
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    print(f"[STEP1] indicators 병렬({ncore}코어)")
    t0 = time.time()
    with mp.Pool(ncore) as pool:
        res = pool.map(_build_one, symbols)
    prepared = {s: p for s, p in res}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s → 캐시 저장")
    with open(CACHE, "wb") as f:
        pickle.dump(prepared, f, protocol=pickle.HIGHEST_PROTOCOL)
    return prepared


def main():
    import numpy as np, pandas as pd
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    global SYMBOLS
    SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
    REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2023, 2024, 2025, 2026]
    OUTDIR = "solo10_result"
    ncore = max(1, min(mp.cpu_count() - 1, len(SYMBOLS)))
    _setup_env_patches()

    TAG10 = ["a_score_ge13", "a_fvg_absent", "a_volume", "a_room", "a_ob",
             "a_vol_expansion", "a_sweep", "a_mss", "a_trend_counter", "a_bb_squeeze"]
    GATES = [("a_score_ge13", "a_score_ge13", "a_score_ge13"), ("~a_fvg", "~a_fvg", "a_fvg_absent"),
             ("a_volume", "a_volume", "a_volume"), ("a_room", "a_room", "a_room"),
             ("a_ob", "a_ob", "a_ob"), ("a_vol_expansion", "a_vol_expansion", "a_vol_expansion"),
             ("a_sweep", "a_sweep", "a_sweep"), ("a_mss", "a_mss", "a_mss"),
             ("~a_trend_align", "~a_trend_align", "a_trend_counter"), ("a_bb_squeeze", "a_bb_squeeze", "a_bb_squeeze")]

    def _pf(p):
        p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
        return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))

    def _rmdd(r):
        cum = np.cumsum(np.asarray(r, float)); pk = np.maximum.accumulate(cum) if len(cum) else cum
        return float((cum - pk).min()) if len(cum) else 0.0

    def tag10(d):
        d = d.copy()
        d["a_fvg_absent"] = ~d["a_fvg"].astype(bool); d["a_trend_counter"] = ~d["a_trend_align"].astype(bool)
        for a in TAG10:
            d[a] = d[a].astype(bool)
        d["n_atoms_true"] = d[TAG10].sum(axis=1).astype(int)
        d["atoms_true"] = d[TAG10].apply(lambda r: ",".join([a for a in TAG10 if r[a]]) or "(none)", axis=1)
        return d

    def metrics(d):
        dd = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
        dd["exit_time"] = pd.to_datetime(dd["exit_time"], utc=True); dd = dd.sort_values("exit_time").reset_index(drop=True)
        r = dd["r_multiple"].astype(float).values; n = len(dd); k = int(n * 0.7); yr = dd["exit_time"].dt.year
        pfy = {y: _pf(r[(yr == y).values]) for y in YEARS if (yr == y).any()}
        d6 = dd[~dd["symbol"].isin(REST6)]
        return {"n": n, "PF": round(_pf(r), 3), "IS": round(_pf(r[:k]), 3), "OOS": round(_pf(r[k:]), 3),
                "expR": round(float(r.mean()), 4), "MDD_R": round(_rmdd(r), 1),
                "r6_PF": round(_pf(d6["r_multiple"].astype(float).values), 3),
                "pf2026": round(pfy.get(2026, float("nan")), 3), "allge1": all(v >= 1 for v in pfy.values()) and len(pfy) > 0}

    prepared = build_prepared(SYMBOLS, ncore)

    print(f"\n[STEP2] 10 게이트 solo — 게이트마다 9심볼 candidate 병렬({ncore}코어), simulate 직렬")
    t_all = time.time()
    all_trades = []; rows = []
    with mp.Pool(ncore, initializer=_init_worker, initargs=(CACHE,)) as pool:
        for label, gate, gatom in GATES:
            t1 = time.time()
            res = pool.map(_gen_one, [(s, gate) for s in SYMBOLS])
            cand = {s: {"candidates": c, "df_h4": prepared[s]["df_struct"],
                        "df_h1": prepared[s]["df_h1"], "symbol": s} for s, c in res}
            tr = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)["trades"]
            tr = tag10(tr); tr.insert(0, "atom_gate", label)
            bad = int((~tr[gatom]).sum())
            m = metrics(tr); m.update({"atom_gate": label, "bad": bad}); rows.append(m); all_trades.append(tr)
            print(f"  [{label:16s}] n={m['n']:4d} PF={m['PF']:.3f} IS={m['IS']:.3f} OOS={m['OOS']:.3f} "
                  f"expR={m['expR']:+.4f} MDD_R={m['MDD_R']:6.1f} 2026={m['pf2026']:.3f} 매년삶={m['allge1']} "
                  f"위반 {bad} ({time.time()-t1:.0f}s)")
    print(f"[STEP2] 10게이트 완료 {time.time()-t_all:.0f}s")

    full = pd.concat(all_trades, ignore_index=True)
    os.makedirs(OUTDIR, exist_ok=True)
    full.to_csv(os.path.join(OUTDIR, "trades_solo10_ALL.csv"), index=False)
    summ = pd.DataFrame(rows)[["atom_gate", "n", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1", "bad"]]
    summ.to_csv(os.path.join(OUTDIR, "solo10_summary.csv"), index=False)

    rm = next(r for r in rows if r["atom_gate"] == "a_room")
    print(f"\n[SELF-CHECK] room swing60 a_room solo: n={rm['n']} OOS={rm['OOS']} 매년삶={rm['allge1']} "
          f"(측정때 n≈1677 OOS≈1.11) → {'✅ 일치' if abs(rm['OOS']-1.11)<0.06 else '⚠️ 불일치'}")
    nbad = sum(r["bad"] for r in rows)
    print(f"[게이트조건] 위반 총 {nbad}건 {'✅' if nbad == 0 else '⚠️'} | [멱등] 엔진 _ls_* 리셋(픽스 적용)")
    print("\n" + "=" * 100); print("게이트별 지표 (raw r_multiple)"); print("=" * 100)
    print(summ.to_string(index=False))
    print(f"\n[저장] {OUTDIR}/trades_solo10_ALL.csv ({len(full)}행), solo10_summary.csv — 사후 조합분석용")


if __name__ == "__main__":
    mp.freeze_support()
    main()
