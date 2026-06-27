#!/usr/bin/env python3
# 단계B 실측: 전방향 변별력 최대후보 solo 진짜게이트. room은 swing60 런타임교체(측정후 원복).
# 영구수정 없음 — 런타임 패치/몽키패치만.
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
SWING_N = 60; SWING_THR = [2.0]
_ORIG_CTT = F.compute_trade_tags


def _ctt_swing(*a, **kw):
    tags = _ORIG_CTT(*a, **kw)
    try:
        df = kw.get("df_struct"); ei = int(kw.get("entry_idx")); zlo = float(kw.get("zone_low"))
        zhi = float(kw.get("zone_high")); side = kw.get("side"); av = kw.get("atr_val")
        if df is not None and av is not None and not np.isnan(av) and av > 0:
            zmid = (zhi + zlo) / 2.0
            if side == "long":
                seg = df["high"].values[max(0, ei - SWING_N):ei + 1]; tgt = np.nanmax(seg) if len(seg) else np.nan
                rr = (max(tgt - zmid, 0.0) / av) if not np.isnan(tgt) else np.nan
            else:
                seg = df["low"].values[max(0, ei - SWING_N):ei + 1]; tgt = np.nanmin(seg) if len(seg) else np.nan
                rr = (max(zmid - tgt, 0.0) / av) if not np.isnan(tgt) else np.nan
            tags["a_room"] = bool((not np.isnan(rr)) and rr >= SWING_THR[0])
    except Exception:
        pass
    return tags


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


def solo(prepared, gate, patches):
    for cn, cv in patches:
        setattr(F, cn, cv)
    os.environ["ATOM_AND_LIST"] = gate
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    d = res["trades"]
    d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
    r = d["r_multiple"].astype(float).values; pnl = d["net_pnl"].astype(float).values
    n = len(d); k = int(n * 0.7); yr = d["exit_time"].dt.year
    pfy = {y: _pf(pnl[(yr == y).values]) for y in YEARS if (yr == y).any()}
    d6 = d[~d["symbol"].isin(REST6)]
    return {"n": n, "win%": round(float((pnl > 0).mean() * 100), 1), "PF": round(_pf(pnl), 3),
            "IS": round(_pf(pnl[:k]), 3), "OOS": round(_pf(pnl[k:]), 3), "expR": round(float(r.mean()), 4),
            "MDD_R": round(_rmdd(r), 1), "r6_PF": round(_pf(d6["net_pnl"].astype(float).values), 3),
            "pf2026": round(pfy.get(2026, float("nan")), 3),
            "allge1": all(v >= 1 for v in pfy.values()) and len(pfy) > 0}


def main():
    print("[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s"); sim.USE_COMBO_UNION = False
    rows = []

    # ── NOT/양극 게이트 (orig CTT) ──
    F.compute_trade_tags = _ORIG_CTT; sim.compute_trade_tags = _ORIG_CTT
    GATE = [
        ("~wick(긴꼬리)@0.17", "~a_wick_le_q1", [("BROAD_WICK_MAX", 0.17)]),
        ("~bb(확장)@0.40", "~a_bb_squeeze", [("REG_BB_SQUEEZE_PCTL", 0.40)]),
        ("~fvg(없음)", "~a_fvg", [("BROAD_FVG_SIZE_ATR", 0.0)]),
        ("room_pd@1.5(현행)", "a_room", [("BROAD_ROOM_RR_MIN", 1.5)]),
    ]
    for label, gate, patches in GATE:
        t1 = time.time(); m = solo(prepared, gate, patches); m.update({"run": label})
        rows.append(m); print(f"  [{label}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} "
                              f"expR={m['expR']} MDD_R={m['MDD_R']} 2026={m['pf2026']} 매년삶={m['allge1']} ({time.time()-t1:.0f}s)")

    # ── room swing60 (몽키패치) ──
    F.compute_trade_tags = _ctt_swing; sim.compute_trade_tags = _ctt_swing
    for thr in [1.5, 2.0]:
        SWING_THR[0] = thr
        t1 = time.time(); m = solo(prepared, "a_room", []); m.update({"run": f"room_swing60@{thr}"})
        rows.append(m); print(f"  [room_swing60@{thr}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} "
                              f"expR={m['expR']} MDD_R={m['MDD_R']} 2026={m['pf2026']} 매년삶={m['allge1']} ({time.time()-t1:.0f}s)")
    F.compute_trade_tags = _ORIG_CTT; sim.compute_trade_tags = _ORIG_CTT   # 원복

    df = pd.DataFrame(rows)[["run", "n", "win%", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1"]]
    os.makedirs("atom_alpha_result", exist_ok=True); df.to_csv("atom_alpha_result/stageB2_solo.csv", index=False)
    print("\n" + "=" * 100); print("단계B2 실측: NOT/room-swing solo OOS (raw r_multiple)"); print("=" * 100)
    print(df.to_string(index=False)); print("\n[저장] atom_alpha_result/stageB2_solo.csv")


if __name__ == "__main__":
    main()
