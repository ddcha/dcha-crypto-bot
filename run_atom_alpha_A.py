#!/usr/bin/env python3
# =========================================================================
# run_atom_alpha_A.py — 단계A: 원자 임계 변별력 스윕 + 단계A' room 정의 3종 비교
#   측정 전용. 게이트 OFF base candidate ~1702. 변별력 = (True OOS_PF) - (False OOS_PF), OOS=exit 70:30.
#   raw 는 candidate 필드로 filters.py 공식 재현(엔진 일치). config/엔진 무수정.
# =========================================================================
import os, json, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)

import numpy as np, pandas as pd
from smc_stage4d.config import (SCENARIO_MULTI, VOLUME_AVG_WINDOW, REG_VOL_WIN,
                                REG_EFF_N, REG_BB_N, REG_BB_K, REG_BB_PCTL_WIN)
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
HONEST = int(os.environ["HONEST_STAGE"])
SWING_N = 60
OUTDIR = "atom_alpha_result"


def _pf(p):
    p = np.asarray(p, float); gp = p[p > 0].sum(); gl = -p[p < 0].sum()
    return float(gp / gl) if gl > 0 else (float("inf") if gp > 0 else float("nan"))


def reset_prepared(prepared):
    for sym in prepared:
        for s in prepared[sym]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                s.pop(k, None)
            s["used"] = False


def collect_raw(prepared):
    """candidate 생성 + raw 값 재현. returns (cand_dict, raw_df keyed symbol|entry_time)."""
    reset_prepared(prepared)
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    rows = []
    for sym in SYMBOLS:
        df = cand[sym]["df_h4"]; cdf = cand[sym]["candidates"]
        if len(cdf) == 0:
            continue
        vol = df["volume"].values.astype(float); atr = df["atr"].values.astype(float)
        clo = df["close"].values.astype(float)
        hi = df["high"].values.astype(float); lo = df["low"].values.astype(float)
        pdh = df["pd_high"].values.astype(float); pdl = df["pd_low"].values.astype(float)
        lph = df["last_pivot_high"].values.astype(float); lpl = df["last_pivot_low"].values.astype(float)
        n = len(df)
        for _, c in cdf.iterrows():
            i = int(c["entry_idx"]); ei = i - 1 if HONEST >= 5 else i
            if ei < 0 or ei >= n:
                continue
            zc = int(c["zone_created_idx"]); zlo = float(c["zone_low"]); zhi = float(c["zone_high"])
            zmid = (zlo + zhi) / 2.0
            av = float(c["atr_at_entry"]) if pd.notna(c["atr_at_entry"]) else np.nan
            side = c["side"]; reasons = str(c.get("structure_reasons_raw", ""))
            r = {"key": f"{sym}|{pd.Timestamp(c['entry_time'])}"}
            r["wick"] = float(c["wick_ratio_5"]) if pd.notna(c["wick_ratio_5"]) else np.nan
            # relvol
            vws = max(0, zc - 3); bst = max(0, zc - VOLUME_AVG_WINDOW); r["relvol"] = np.nan
            if zc < n and zc > bst:
                vmax = np.nanmax(vol[vws:zc + 1]); vbase = np.nanmedian(vol[bst:zc])
                if vbase and vbase > 0 and not np.isnan(vmax):
                    r["relvol"] = vmax / vbase
            # fvg
            fp = ("valid_bull_fvg" in reasons) or ("valid_bear_fvg" in reasons)
            r["fvg_present"] = fp
            r["fvg_ratio"] = (abs(zhi - zlo) / av) if (fp and av and av > 0) else np.nan
            # vol_pctl
            r["vol_pctl"] = np.nan
            if ei >= REG_VOL_WIN:
                seg = atr[ei - REG_VOL_WIN:ei + 1]; cur = atr[ei]; seg = seg[~np.isnan(seg)]
                if len(seg) >= 20 and not np.isnan(cur):
                    r["vol_pctl"] = float((seg < cur).mean())
            # efficiency ER
            r["er"] = np.nan
            if ei >= REG_EFF_N:
                sg = clo[ei - REG_EFF_N:ei + 1]; den = np.sum(np.abs(np.diff(sg)))
                if den > 0:
                    r["er"] = abs(sg[-1] - sg[0]) / den
            # bb width pctl
            r["bb_pctl"] = np.nan
            if ei >= (REG_BB_N + REG_BB_PCTL_WIN):
                def bbw(j):
                    s = clo[j - REG_BB_N + 1:j + 1]; m = s.mean(); sd = s.std()
                    return (2.0 * REG_BB_K * sd) / m if m > 0 else np.nan
                cur = bbw(ei); hist = np.array([bbw(j) for j in range(ei - REG_BB_PCTL_WIN, ei)])
                hist = hist[~np.isnan(hist)]
                if (not np.isnan(cur)) and len(hist) >= 20:
                    r["bb_pctl"] = float((hist < cur).mean())
            # room 3 defs
            def rr(tgt):
                if av is None or np.isnan(av) or av <= 0 or np.isnan(tgt):
                    return np.nan
                return (max(tgt - zmid, 0.0) / av) if side == "long" else (max(zmid - tgt, 0.0) / av)
            tgt_a = pdh[ei] if side == "long" else pdl[ei]
            if side == "long":
                sh = hi[max(0, ei - SWING_N):ei + 1]; tgt_b = np.nanmax(sh) if len(sh) else np.nan
            else:
                sl = lo[max(0, ei - SWING_N):ei + 1]; tgt_b = np.nanmin(sl) if len(sl) else np.nan
            tgt_c = lph[ei] if side == "long" else lpl[ei]
            r["room_a_pd"] = rr(tgt_a); r["room_b_swing"] = rr(tgt_b); r["room_c_pivot"] = rr(tgt_c)
            rows.append(r)
    return cand, pd.DataFrame(rows)


def sweep(trades, col, op, thrs, present_col=None):
    d = trades.sort_values("exit_time").reset_index(drop=True)
    n = len(d); k = int(n * 0.7)
    oos = d.iloc[k:]
    raw = d[col].values.astype(float); raw_oos = oos[col].values.astype(float)
    pnl = d["net_pnl"].values.astype(float); rr = d["r_multiple"].values.astype(float)
    pnl_oos = oos["net_pnl"].values.astype(float)
    pres = d[present_col].values.astype(bool) if present_col else np.ones(n, bool)
    pres_oos = oos[present_col].values.astype(bool) if present_col else np.ones(len(oos), bool)
    out = []
    for t in thrs:
        if op == "le":
            m = pres & (raw <= t); mo = pres_oos & (raw_oos <= t)
        else:
            m = pres & (raw >= t); mo = pres_oos & (raw_oos >= t)
        m = m & ~np.isnan(raw); mo = mo & ~np.isnan(raw_oos)
        pf_t = _pf(pnl_oos[mo]); pf_f = _pf(pnl_oos[~mo])
        disc = (pf_t - pf_f) if (np.isfinite(pf_t) and np.isfinite(pf_f)) else np.nan
        out.append({"thr": t, "pass%": round(m.mean() * 100, 1), "n_true": int(m.sum()),
                    "n_oosT": int(mo.sum()), "OOS_PF_T": round(pf_t, 3), "OOS_PF_F": round(pf_f, 3),
                    "disc": round(disc, 3) if np.isfinite(disc) else disc,
                    "expR_T": round(float(np.nanmean(rr[m])), 4) if m.any() else np.nan})
    return pd.DataFrame(out)


def print_sweep(name, df):
    print(f"\n--- {name} ---")
    print(df.to_string(index=False))
    valid = df[(df["n_oosT"] >= 20) & df["disc"].apply(lambda x: isinstance(x, (int, float)) and np.isfinite(x))]
    if len(valid):
        best = valid.loc[valid["disc"].idxmax()]
        print(f"  ★ 변별력 최대(n_oosT≥20): thr={best['thr']} disc={best['disc']} "
              f"OOS_PF_T={best['OOS_PF_T']} pass={best['pass%']}%")
    else:
        print("  (유효 변별력 없음 — n_oosT<20만)")


def main():
    print("[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")
    sim.USE_COMBO_UNION = False
    print("[STEP2] candidate raw 수집 + base simulate")
    cand, raw = collect_raw(prepared)
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    tr = res["trades"].copy()
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    tr["key"] = tr["symbol"].astype(str) + "|" + pd.to_datetime(tr["entry_time"], utc=True).astype(str)
    tr["exit_time"] = pd.to_datetime(tr["exit_time"], utc=True)
    raw_idx = raw.set_index("key")
    for c in ["wick", "relvol", "fvg_present", "fvg_ratio", "vol_pctl", "er", "bb_pctl",
              "room_a_pd", "room_b_swing", "room_c_pivot"]:
        tr[c] = tr["key"].map(raw_idx[c])
    miss = tr[["wick", "relvol", "er"]].isna().all(axis=1).sum()
    print(f"  base 거래 {len(tr)} | raw 매칭실패 {int(tr['relvol'].isna().sum())} (relvol) | 전부NaN {int(miss)}")
    os.makedirs(OUTDIR, exist_ok=True)
    tr.to_csv(f"{OUTDIR}/base_trades_with_raw.csv", index=False)

    print("\n" + "=" * 90)
    print("단계A: 변별력 스윕 (변별력 = OOS_PF_True - OOS_PF_False, OOS=exit 70:30)")
    print("=" * 90)
    SWEEPS = [
        ("a_wick_le_q1 (wick<=)", "wick", "le", [0.10, 0.13, 0.15, 0.17, 0.20, 0.23, 0.30, 0.35], None),
        ("a_volume (relvol>=)", "relvol", "ge", [1.5, 2.0, 2.5, 2.8, 3.2, 3.5, 4.0, 5.0], None),
        ("a_fvg (두께/atr>=, FVG존재)", "fvg_ratio", "ge", [0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 1.0], "fvg_present"),
        ("a_vol_expansion (ATR백분위>=)", "vol_pctl", "ge", [0.40, 0.50, 0.60, 0.70, 0.78, 0.85], None),
        ("a_efficiency (ER>=)", "er", "ge", [0.25, 0.30, 0.40, 0.48, 0.55, 0.65], None),
        ("a_bb_squeeze (밴드폭백분위<=)", "bb_pctl", "le", [0.15, 0.20, 0.25, 0.30, 0.40], None),
    ]
    best_thr = {}
    for name, col, op, thrs, pc in SWEEPS:
        df = sweep(tr, col, op, thrs, pc)
        print_sweep(name, df)
        df.to_csv(f"{OUTDIR}/sweep_{col}.csv", index=False)
        valid = df[(df["n_oosT"] >= 20) & df["disc"].apply(lambda x: isinstance(x, (int, float)) and np.isfinite(x))]
        if len(valid):
            best_thr[col] = float(valid.loc[valid["disc"].idxmax(), "thr"])

    print("\n" + "=" * 90)
    print("단계A': room 타겟정의 3종 비교 (room_rr = 타겟거리/ATR)")
    print("=" * 90)
    for nm, col in [("(a) pd 1620봉극값", "room_a_pd"), (f"(b) swing{SWING_N}봉", "room_b_swing"),
                    ("(c) last_pivot", "room_c_pivot")]:
        a = tr[col].dropna().values
        ps = {p: round(float(np.percentile(a, p)), 2) for p in [0, 25, 50, 75, 90, 100]} if len(a) else {}
        in15 = ((a >= 1) & (a <= 5)).mean() * 100 if len(a) else 0
        print(f"\n  {nm}: 분포 {ps} | RR1~5비중 {in15:.0f}% | n={len(a)}")
        thrs = [1, 2, 3, 5, 8, 12] if col == "room_a_pd" else [0.5, 1, 1.5, 2, 3, 5]
        df = sweep(tr, col, "ge", thrs)
        print(df.to_string(index=False))
        df.to_csv(f"{OUTDIR}/sweep_{col}.csv", index=False)

    json.dump(best_thr, open(f"{OUTDIR}/best_thresholds.json", "w"), indent=2)
    print("\n=== 단계A 변별력 최대 임계 (→ 단계B solo 후보) ===")
    print(json.dumps(best_thr, indent=2, ensure_ascii=False))
    print(f"\n[저장] {OUTDIR}/ (base_trades_with_raw.csv, sweep_*.csv, best_thresholds.json)")


if __name__ == "__main__":
    main()
