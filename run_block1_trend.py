#!/usr/bin/env python3
# 블록1: trend H1 CHOCH 엄밀화 — apply_h1_choch_trend 이식 + 룩어헤드 검증 + trend 4종 solo 실측.
#   stage4d df_h1 엔 이미 apply_choch 적용됨(bull/bear_choch 존재). apply_choch도 0.15로 재적용(소스 기준).
#   영구수정 없음 — 측정용 컬럼추가 + compute_trade_tags 몽키패치(a_trend_align_h1choch).
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
from smc_stage4d.indicators import apply_choch
import smc_stage4d.filters as F
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2023, 2024, 2025, 2026]
_ORIG_CTT = F.compute_trade_tags


# ── 이식: apply_h1_choch_trend (trend/ts 배열만 반환, 컬럼명 분리) ──
def h1_choch_trend_arrays(df_h4, df_h1):
    if "bull_choch" not in df_h1.columns:
        raise ValueError("df_h1 에 bull_choch 없음")
    bull = df_h1.loc[df_h1["bull_choch"], "timestamp"].sort_values().values
    bear = df_h1.loc[df_h1["bear_choch"], "timestamp"].sort_values().values
    h4 = df_h4["timestamp"].values; n = len(h4)
    bp = (np.searchsorted(bull, h4, side="right") - 1) if len(bull) else np.full(n, -1)
    rp = (np.searchsorted(bear, h4, side="right") - 1) if len(bear) else np.full(n, -1)
    trends = np.array(["neutral"] * n, dtype=object); ts = np.array([pd.NaT] * n, dtype=object)
    for k in range(n):
        hb, hr = bp[k] >= 0, rp[k] >= 0
        if not hb and not hr:
            continue
        if hb and not hr:
            trends[k] = "up"; ts[k] = bull[bp[k]]; continue
        if hr and not hb:
            trends[k] = "down"; ts[k] = bear[rp[k]]; continue
        tb, tr = bull[bp[k]], bear[rp[k]]
        if tb > tr: trends[k] = "up"; ts[k] = tb
        elif tr > tb: trends[k] = "down"; ts[k] = tr
        else: ts[k] = tb
    return trends, ts


def _wrap(*a, **kw):
    tags = _ORIG_CTT(*a, **kw)
    try:
        df = kw.get("df_struct"); ei = int(kw.get("entry_idx")); side = kw.get("side")
        ht = df.loc[ei, "h1choch_trend"]
        opposed = (side == "long" and ht == "down") or (side == "short" and ht == "up")
        tags["a_trend_align_h1choch"] = bool(not opposed)
    except Exception:
        tags["a_trend_align_h1choch"] = False
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


def solo(prepared, gate):
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

    # ── 이식 적용: df_h1 apply_choch(0.15 소스기준) → h1choch_trend ──
    print("\n[STEP2] apply_h1_choch_trend 이식 적용")
    for s in SYMBOLS:
        dfh1 = prepared[s]["df_h1"]
        dfh1 = apply_choch(dfh1, break_atr_mult=0.15)   # 소스 기본값 재적용
        prepared[s]["df_h1"] = dfh1
        df_struct = prepared[s]["df_struct"]
        trends, ts = h1_choch_trend_arrays(df_struct, dfh1)
        df_struct["h1choch_trend"] = trends
        df_struct["h1choch_ts"] = ts

    # ── ★룩어헤드 검증 ──
    print("\n[STEP3] ★룩어헤드 검증")
    tot_future = 0; tot_bars = 0; samp = []
    for s in SYMBOLS:
        df = prepared[s]["df_struct"]
        tsv = pd.to_datetime(df["timestamp"], utc=True)
        ctv = pd.to_datetime(pd.Series(df["h1choch_ts"].values), utc=True)
        has = ctv.notna().values
        future = (ctv[has].values > tsv[has].values)
        tot_future += int(future.sum()); tot_bars += int(has.sum())
        if len(samp) < 50:
            idx = np.where(has)[0][:max(0, 50 - len(samp))]
            for i in idx:
                samp.append((s, tsv.iloc[i], ctv.iloc[i], bool(ctv.iloc[i] > tsv.iloc[i])))
    n_samp_future = sum(1 for x in samp if x[3])
    print(f"  [검증1] apply_choch: i-1 구조 + i 종가만 참조 (소스 L2034-2046, 미래봉 0참조) — 구조상 보장")
    print(f"  [검증2] apply_h1_choch_trend: searchsorted(right)-1 → t이하 H1 CHoCH만 (소스 L2128) — 구조상 보장")
    print(f"  [검증3] 전 H4봉 last_choch_ts > timestamp(미래참조): {tot_future} / {tot_bars}건")
    print(f"          샘플 50건 미래참조: {n_samp_future}건")
    if tot_future != 0:
        print("  ❌ 미래참조 발견 — 블록1 중단"); raise SystemExit(2)
    print("  ✅ 미래참조 0건 — 룩어헤드 통과, 실측 진행")
    # H4 trend 분포 참고
    for s in SYMBOLS[:1]:
        d = prepared[s]["df_struct"]; vc = d["h1choch_trend"].value_counts()
        print(f"  ({s}) h1choch_trend 분포: {dict(vc)}")

    # ── 실측: trend 4종 solo (wrapper 활성) ──
    print("\n[STEP4] trend 4종 solo 실측")
    F.compute_trade_tags = _wrap; sim.compute_trade_tags = _wrap
    GATES = [("단순 정극 a_trend_align", "a_trend_align"),
             ("단순 역추세 ~a_trend_align", "~a_trend_align"),
             ("엄밀 정극 a_trend_align_h1choch", "a_trend_align_h1choch"),
             ("엄밀 역추세 ~a_trend_align_h1choch", "~a_trend_align_h1choch")]
    rows = []
    for label, gate in GATES:
        t1 = time.time(); m = solo(prepared, gate); m.update({"run": label})
        rows.append(m); print(f"  [{label}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} "
                              f"expR={m['expR']} MDD_R={m['MDD_R']} 2026={m['pf2026']} 매년삶={m['allge1']} ({time.time()-t1:.0f}s)")
    F.compute_trade_tags = _ORIG_CTT; sim.compute_trade_tags = _ORIG_CTT

    df = pd.DataFrame(rows)[["run", "n", "win%", "PF", "IS", "OOS", "expR", "MDD_R", "r6_PF", "pf2026", "allge1"]]
    os.makedirs("block1_trend_result", exist_ok=True); df.to_csv("block1_trend_result/trend4_solo.csv", index=False)
    print("\n" + "=" * 100); print("블록1 실측: trend 4종 solo (단순 vs 엄밀H1CHOCH, 정극/역추세)"); print("=" * 100)
    print(df.to_string(index=False)); print("\n[저장] block1_trend_result/trend4_solo.csv")


if __name__ == "__main__":
    main()
