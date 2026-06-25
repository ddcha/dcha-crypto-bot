#!/usr/bin/env python3
# =========================================================================
# run_atom_rawdist.py — 5개 원자 raw 분포 측정 + 20%통과 임계 + room 타겟정의 결함 진단
#   측정·진단 전용. config/엔진 무수정. 게이트 OFF(base candidate ~1702).
#   raw 는 candidate 저장필드(zone_created_idx/zone_low/high/entry_idx/atr_at_entry/reasons)로
#   filters.py 공식을 그대로 재현해 dump. (엔진과 일치하는지 현재임계 통과율로 검증)
# =========================================================================
import os, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)

import numpy as np, pandas as pd
from smc_stage4d.config import SCENARIO_MULTI, VOLUME_AVG_WINDOW, REG_VOL_WIN
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
HONEST = int(os.environ["HONEST_STAGE"])
SWING_N = 60   # 대안1: 최근 N봉 스윙
PCTLS = [0, 10, 20, 25, 50, 75, 80, 90, 95, 99, 100]


def reset_prepared(prepared):
    for sym in prepared:
        for s in prepared[sym]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                s.pop(k, None)
            s["used"] = False


def pctl_row(name, arr):
    a = np.asarray(arr, float); a = a[~np.isnan(a)]
    if len(a) == 0:
        return name, [np.nan] * len(PCTLS), 0
    return name, [round(float(np.percentile(a, p)), 4) for p in PCTLS], len(a)


def collect(prepared):
    rows = []
    for sym in SYMBOLS:
        out = generate_candidates_from_prepared(prepared[sym])
        df = out["df_h4"]; cdf = out["candidates"]
        if len(cdf) == 0:
            continue
        vol = df["volume"].values.astype(float)
        atr = df["atr"].values.astype(float)
        hi = df["high"].values.astype(float); lo = df["low"].values.astype(float)
        pdh = df["pd_high"].values.astype(float) if "pd_high" in df else np.full(len(df), np.nan)
        pdl = df["pd_low"].values.astype(float) if "pd_low" in df else np.full(len(df), np.nan)
        lph = df["last_pivot_high"].values.astype(float) if "last_pivot_high" in df else np.full(len(df), np.nan)
        lpl = df["last_pivot_low"].values.astype(float) if "last_pivot_low" in df else np.full(len(df), np.nan)
        n = len(df)
        for _, c in cdf.iterrows():
            i = int(c["entry_idx"]); ei = i - 1 if HONEST >= 5 else i
            zc = int(c["zone_created_idx"])
            zlo = float(c["zone_low"]); zhi = float(c["zone_high"]); zmid = (zlo + zhi) / 2.0
            av = float(c["atr_at_entry"]) if pd.notna(c["atr_at_entry"]) else np.nan
            side = c["side"]; reasons = str(c.get("structure_reasons_raw", ""))
            if ei < 0 or ei >= n:
                continue
            r = {"symbol": sym, "side": side}
            # 1) wick (candidate 저장값)
            r["wick"] = float(c["wick_ratio_5"]) if pd.notna(c["wick_ratio_5"]) else np.nan
            # 2) volume relvol
            vws = max(0, zc - 3); bst = max(0, zc - VOLUME_AVG_WINDOW)
            relvol = np.nan
            if zc < n and zc > bst:
                vmax = np.nanmax(vol[vws:zc + 1]); vbase = np.nanmedian(vol[bst:zc])
                if vbase and vbase > 0 and not np.isnan(vmax):
                    relvol = vmax / vbase
            r["relvol"] = relvol
            # 3) fvg 두께/atr (FVG 존재시만)
            fvg_present = ("valid_bull_fvg" in reasons) or ("valid_bear_fvg" in reasons)
            r["fvg_present"] = fvg_present
            r["fvg_ratio"] = (abs(zhi - zlo) / av) if (fvg_present and av and av > 0) else np.nan
            # 4) vol_expansion ATR 백분위
            r["vol_pctl"] = np.nan
            if ei >= REG_VOL_WIN:
                seg = atr[ei - REG_VOL_WIN:ei + 1]; cur = atr[ei]
                seg = seg[~np.isnan(seg)]
                if len(seg) >= 20 and not np.isnan(cur):
                    r["vol_pctl"] = float((seg < cur).mean())
            # 5) room_rr 3변형
            def rr(tgt):
                if av is None or np.isnan(av) or av <= 0 or np.isnan(tgt):
                    return np.nan
                return (max(tgt - zmid, 0.0) / av) if side == "long" else (max(zmid - tgt, 0.0) / av)
            tgt_a = pdh[ei] if side == "long" else pdl[ei]
            if side == "long":
                seg_h = hi[max(0, ei - SWING_N):ei + 1]; tgt_b = np.nanmax(seg_h) if len(seg_h) else np.nan
            else:
                seg_l = lo[max(0, ei - SWING_N):ei + 1]; tgt_b = np.nanmin(seg_l) if len(seg_l) else np.nan
            tgt_c = lph[ei] if side == "long" else lpl[ei]
            r["room_a_pd"] = rr(tgt_a)
            r["room_b_swing"] = rr(tgt_b)
            r["room_c_pivot"] = rr(tgt_c)
            rows.append(r)
    return pd.DataFrame(rows)


def main():
    print("[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")
    sim.USE_COMBO_UNION = False
    reset_prepared(prepared)
    print("[STEP2] candidate raw 수집")
    D = collect(prepared)
    N = len(D)
    print(f"  base candidate {N}건")
    os.makedirs("atom_rawdist_result", exist_ok=True)
    D.to_csv("atom_rawdist_result/raw_values.csv", index=False)

    hdr = "원자/지표        " + "".join(f"p{p:>5}" for p in PCTLS) + "   n"
    print("\n" + "=" * len(hdr)); print("5개 원자 raw 분포 (백분위)"); print("=" * len(hdr)); print(hdr)
    for nm, col in [("wick(<=)", "wick"), ("relvol(>=)", "relvol"),
                    ("fvg두께/atr(>=)", "fvg_ratio"), ("vol_pctl(>=)", "vol_pctl"),
                    ("room_a_pd(>=)", "room_a_pd")]:
        name, ps, k = pctl_row(nm, D[col])
        print(f"{name:<16}" + "".join(f"{v:>6}" for v in ps) + f"  {k}")

    # ── 현재임계 통과율 검증(stage1 NEW 값과 일치해야) ──
    print("\n=== 현재(NEW) 임계 통과율 — 엔진 일치 검증 (stage1 기대: 30.7/29.1/38.1/28.1/79.4) ===")
    pr_wick = (D["wick"] <= 0.20).mean() * 100
    pr_vol = (D["relvol"] >= 2.8).mean() * 100
    pr_fvg = ((D["fvg_present"]) & (D["fvg_ratio"] >= 0.30)).mean() * 100
    pr_ve = (D["vol_pctl"] >= 0.70).mean() * 100
    pr_room = (D["room_a_pd"] >= 2.8).mean() * 100
    print(f"  wick<=0.20: {pr_wick:.1f}% | relvol>=2.8: {pr_vol:.1f}% | fvg>=0.30: {pr_fvg:.1f}% | "
          f"vol_pctl>=0.70: {pr_ve:.1f}% | room>=2.8: {pr_room:.1f}%")

    # ── 20% 통과 정확 임계 ──
    print("\n=== '20% 통과' 정확 임계값 ===")
    wick_t = float(np.nanpercentile(D["wick"], 20))
    vol_t = float(np.nanpercentile(D["relvol"], 80))
    ve_t = float(np.nanpercentile(D["vol_pctl"], 80))
    room_t = float(np.nanpercentile(D["room_a_pd"], 80))
    # fvg: 전체의 20%가 통과하려면 present 중 상위 (0.20/frac_present)
    fr = float(D["fvg_present"].mean())
    pres = D.loc[D["fvg_present"], "fvg_ratio"].dropna().values
    if fr > 0.20 and len(pres):
        q = (1 - 0.20 / fr) * 100
        fvg_t = float(np.percentile(pres, q))
    else:
        fvg_t = float("nan")
    print(f"  a_wick_le_q1   : wick <= {wick_t:.4f}   (현재 0.20={pr_wick:.0f}%)")
    print(f"  a_volume       : relvol >= {vol_t:.4f}   (현재 2.8={pr_vol:.0f}%)")
    print(f"  a_fvg          : 두께/atr >= {fvg_t:.4f}  (FVG존재율 {fr*100:.0f}%, 현재 0.30={pr_fvg:.0f}%)")
    print(f"  a_vol_expansion: ATR백분위 >= {ve_t:.4f}  (현재 0.70={pr_ve:.0f}%)")
    print(f"  a_room(현행정의): room_rr >= {room_t:.4f}  (현재 2.8={pr_room:.0f}%)")

    # ── room 결함 진단: 3변형 분포 비교 ──
    print("\n" + "=" * 78)
    print("room 타겟정의 결함 진단 — room_rr 3방식 분포 비교")
    print("=" * 78)
    print(hdr)
    for nm, col in [("(a)pd 1620극값", "room_a_pd"), (f"(b)swing{SWING_N}봉", "room_b_swing"),
                    ("(c)last_pivot", "room_c_pivot")]:
        name, ps, k = pctl_row(nm, D[col])
        print(f"{name:<16}" + "".join(f"{v:>6}" for v in ps) + f"  {k}")
    # 변별력 판정: RR 1~5 구간 비중 + 20%통과 임계
    print("\n=== 변별력 판정 (RR 1~5 적당분산 = 좋음 / 큰값쏠림 = 결함) ===")
    for nm, col in [("(a)pd", "room_a_pd"), ("(b)swing", "room_b_swing"), ("(c)pivot", "room_c_pivot")]:
        a = D[col].dropna().values
        if len(a) == 0:
            print(f"  {nm}: 데이터없음"); continue
        in15 = ((a >= 1) & (a <= 5)).mean() * 100
        gt8 = (a > 8).mean() * 100
        t20 = float(np.percentile(a, 80))
        med = float(np.median(a))
        print(f"  {nm:<10}: 중앙값 {med:.2f} | RR1~5 비중 {in15:.0f}% | RR>8 비중 {gt8:.0f}% | 20%통과임계 {t20:.2f}")
    print("\n[저장] atom_rawdist_result/ (raw_values.csv)")


if __name__ == "__main__":
    main()
