#!/usr/bin/env python3
# 확정 10원자 각각 개별 게이트 solo 백테스트(10번) + 전 거래 10원자 태깅 → trades_solo10_ALL.csv
#   room swing60 영구반영 후. indicators 9심볼 1회 재사용, 게이트마다 _ls_*+used 리셋(멱등).
#   확정임계: a_vol_expansion=0.85, a_fvg_absent=FVG없음(BROAD_FVG_SIZE_ATR=0→a_fvg=존재) 전역패치.
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
REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2023, 2024, 2025, 2026]
OUTDIR = "solo10_result"
# 확정임계 전역패치
F.REG_VOL_PCTL = 0.85           # a_vol_expansion 조임
F.BROAD_FVG_SIZE_ATR = 0.0      # a_fvg=존재(any두께) → ~a_fvg=FVG없음(순수)

# 태깅 10원자 (게이트 의미대로; ~는 뒤집어)
TAG10 = ["a_score_ge13", "a_fvg_absent", "a_volume", "a_room", "a_ob",
         "a_vol_expansion", "a_sweep", "a_mss", "a_trend_counter", "a_bb_squeeze"]
# (게이트라벨, ATOM_AND_LIST, 그 게이트가 보장하는 태그원자)
GATES = [
    ("a_score_ge13", "a_score_ge13", "a_score_ge13"),
    ("~a_fvg", "~a_fvg", "a_fvg_absent"),
    ("a_volume", "a_volume", "a_volume"),
    ("a_room", "a_room", "a_room"),
    ("a_ob", "a_ob", "a_ob"),
    ("a_vol_expansion", "a_vol_expansion", "a_vol_expansion"),
    ("a_sweep", "a_sweep", "a_sweep"),
    ("a_mss", "a_mss", "a_mss"),
    ("~a_trend_align", "~a_trend_align", "a_trend_counter"),
    ("a_bb_squeeze", "a_bb_squeeze", "a_bb_squeeze"),
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


def run_gate(prepared, gate_list):
    os.environ["ATOM_AND_LIST"] = gate_list
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    return res["trades"].copy()


def tag10(d):
    d = d.copy()
    d["a_fvg_absent"] = ~d["a_fvg"].astype(bool)
    d["a_trend_counter"] = ~d["a_trend_align"].astype(bool)
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


def main():
    print(f"[INFO] room=swing60(영구) | a_vol_expansion REG_VOL_PCTL={F.REG_VOL_PCTL} | "
          f"a_fvg BROAD_FVG_SIZE_ATR={F.BROAD_FVG_SIZE_ATR}(→~a_fvg=FVG없음)")
    print("\n[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s"); sim.USE_COMBO_UNION = False

    # 멱등성 assert (게이트 OFF 2패스)
    os.environ["ATOM_AND_LIST"] = ""
    reset_prepared(prepared); n1 = sum(len(generate_candidates_from_prepared(prepared[s])["candidates"]) for s in SYMBOLS)
    reset_prepared(prepared); n2 = sum(len(generate_candidates_from_prepared(prepared[s])["candidates"]) for s in SYMBOLS)
    print(f"[멱등성] base 1패스 {n1} / 2패스 {n2}")
    assert n1 == n2, f"[ABORT] 비멱등 {n1}!={n2}"
    print("  → 멱등 OK")

    all_trades = []; rows = []
    print("\n[STEP2] 10원자 solo 게이트 + 태깅")
    for label, gate, gatom in GATES:
        t1 = time.time()
        tr = run_gate(prepared, gate)
        tr = tag10(tr)
        tr.insert(0, "atom_gate", label)
        # 게이트 조건 self-check: 진입거래 전부 그 게이트원자 True 여야
        bad = int((~tr[gatom]).sum())
        m = metrics(tr); m.update({"atom_gate": label, "gate_ok": (bad == 0), "bad": bad})
        rows.append(m); all_trades.append(tr)
        print(f"  [{label:16s}] n={m['n']:4d} PF={m['PF']:.3f} IS={m['IS']:.3f} OOS={m['OOS']:.3f} "
              f"expR={m['expR']:+.4f} MDD_R={m['MDD_R']:6.1f} 2026={m['pf2026']:.3f} 매년삶={m['allge1']} "
              f"| 게이트조건위반 {bad} ({time.time()-t1:.0f}s)")

    full = pd.concat(all_trades, ignore_index=True)
    os.makedirs(OUTDIR, exist_ok=True)
    full.to_csv(os.path.join(OUTDIR, "trades_solo10_ALL.csv"), index=False)
    print(f"\n[저장] {OUTDIR}/trades_solo10_ALL.csv (통합 {len(full)}행, atom_gate+10원자T/F+n_atoms_true+atoms_true)")

    summ = pd.DataFrame(rows)[["atom_gate", "n", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1", "gate_ok"]]
    summ.to_csv(os.path.join(OUTDIR, "solo10_summary.csv"), index=False)

    # room self-check
    rm = next(r for r in rows if r["atom_gate"] == "a_room")
    print("\n[SELF-CHECK] room swing60 a_room solo: "
          f"n={rm['n']} OOS={rm['OOS']} 매년삶={rm['allge1']} (측정때 n≈1677 OOS≈1.11 매년삶 True) → "
          f"{'✅ 일치' if abs(rm['OOS']-1.11)<0.06 else '⚠️ 불일치'}")
    print("  [룩어헤드] a_room=high/low[entry_idx-60..entry_idx] (정직신호봉 i-1 이하만) — 구조상 미래참조 0")
    nbad = sum(r["bad"] for r in rows)
    print(f"  [게이트조건] 10게이트 전부 진입거래가 게이트원자 True: 위반 총 {nbad}건 {'✅' if nbad == 0 else '⚠️'}")

    print("\n" + "=" * 100); print("게이트별 지표 (raw r_multiple)"); print("=" * 100)
    print(summ.to_string(index=False))
    print(f"\n[저장 완료] {OUTDIR}/ (trades_solo10_ALL.csv, solo10_summary.csv) — 사후 조합분석용")


if __name__ == "__main__":
    main()
