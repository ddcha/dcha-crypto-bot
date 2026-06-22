"""FVG-only baseline(score 6.0~9.0) 위에서 16원자 ON subset의 IS/OOS PF 매트릭스.
원자는 진입 게이트가 아니라 로그 전용 → ON subset = '그 원자를 추가 게이트로 걸었을 때'와 동일.
plateau 판정: 한 원자가 전 score 일관 OOS PF>1 & IS도 양호하면 진짜 lift, 단발이면 노이즈.
"""
import os
import numpy as np
import pandas as pd

ROOT = r"D:\smc_bot\fvgonly_out"
SCORES = ["6.0", "6.5", "7.0", "7.5", "8.0", "8.5", "9.0"]
ATOMS = [
    "a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg",
    "a_overlap", "a_room", "a_efficiency", "a_bb_squeeze", "a_vol_expansion", "a_room",
]
ATOMS = list(dict.fromkeys(ATOMS))  # 중복 제거(16번째는 사용자 표현 맞춤, 실제 15 유니크)

def pf(p):
    pos = p[p > 0].sum(); neg = p[p < 0].sum()
    return pos / abs(neg) if neg < 0 else np.nan

data = {}
for ms in SCORES:
    fp = os.path.join(ROOT, f"s{ms}", "stage4d_trades.csv")
    if not os.path.exists(fp):
        continue
    d = pd.read_csv(fp)
    d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
    d["y"] = d["et"].dt.year
    d["p"] = pd.to_numeric(d["net_pnl"], errors="coerce")
    d["r"] = pd.to_numeric(d["r_multiple"], errors="coerce")
    data[ms] = d

def cell(d, span_years, atom):
    m = d["y"].isin(span_years) & d[atom].astype(bool)
    n = int(m.sum())
    if n == 0:
        return n, np.nan, np.nan
    return n, round(pf(d["p"][m]), 3), round(float(d["r"][m].mean()), 3)

IS_Y = [2023, 2024]; OOS_Y = [2025, 2026]

# baseline (원자 무관 전체)
def base_row(span):
    out = {}
    for ms in SCORES:
        d = data[ms]; m = d["y"].isin(span)
        out[ms] = round(pf(d["p"][m]), 3)
    return out

rows_oos_pf = []; rows_is_pf = []; rows_oos_n = []; rows_oos_r = []
bl_is = base_row(IS_Y); bl_oos = base_row(OOS_Y)
for atom in ATOMS:
    ro_pf = {"atom": atom}; ri_pf = {"atom": atom}; ro_n = {"atom": atom}; ro_r = {"atom": atom}
    for ms in SCORES:
        d = data[ms]
        nI, pfI, rI = cell(d, IS_Y, atom)
        nO, pfO, rO = cell(d, OOS_Y, atom)
        ri_pf[ms] = pfI; ro_pf[ms] = pfO; ro_n[ms] = nO; ro_r[ms] = rO
    rows_is_pf.append(ri_pf); rows_oos_pf.append(ro_pf); rows_oos_n.append(ro_n); rows_oos_r.append(ro_r)

is_pf = pd.DataFrame(rows_is_pf).set_index("atom")
oos_pf = pd.DataFrame(rows_oos_pf).set_index("atom")
oos_n = pd.DataFrame(rows_oos_n).set_index("atom")
oos_r = pd.DataFrame(rows_oos_r).set_index("atom")

pd.set_option("display.width", 200); pd.set_option("display.max_columns", 20)
print("=== baseline (FVG-only, 원자 무관) ===")
print("IS_PF :", bl_is)
print("OOS_PF:", bl_oos)
print("\n=== [OOS PF] 원자 ON subset (행=원자, 열=score) ===")
print("  baseline OOS_PF:", {k: bl_oos[k] for k in SCORES})
print(oos_pf.to_string())
print("\n=== [IS PF] 원자 ON subset ===")
print(is_pf.to_string())
print("\n=== [OOS 표본 n] (작으면 PF 노이즈 주의) ===")
print(oos_n.to_string())
print("\n=== [OOS avgR] 원자 ON subset ===")
print(oos_r.to_string())

# plateau 스코어: OOS PF가 전 score에서 baseline보다 크고 >1인 비율
print("\n=== plateau 진단: 원자별 'OOS PF>1 & baseline초과' score 개수 (/7) ===")
diag = []
for atom in ATOMS:
    cnt_gt1 = 0; cnt_beatbase = 0; vals = []
    for ms in SCORES:
        v = oos_pf.loc[atom, ms]; b = bl_oos[ms]
        if pd.notna(v):
            vals.append(v)
            if v > 1.0: cnt_gt1 += 1
            if v > b: cnt_beatbase += 1
    minv = round(min(vals), 3) if vals else np.nan
    diag.append(dict(atom=atom, oos_pf_gt1=cnt_gt1, beat_baseline=cnt_beatbase,
                     min_oos_pf=minv, mean_oos_pf=round(float(np.nanmean(vals)), 3) if vals else np.nan))
diag = pd.DataFrame(diag).sort_values(["oos_pf_gt1", "mean_oos_pf"], ascending=False)
print(diag.to_string(index=False))

OUT = os.path.join(ROOT, "fvgonly_atom_matrix.xlsx")
with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    pd.DataFrame([dict(span="IS", **bl_is), dict(span="OOS", **bl_oos)]).to_excel(xw, sheet_name="baseline", index=False)
    oos_pf.to_excel(xw, sheet_name="OOS_PF"); is_pf.to_excel(xw, sheet_name="IS_PF")
    oos_n.to_excel(xw, sheet_name="OOS_n"); oos_r.to_excel(xw, sheet_name="OOS_avgR")
    diag.to_excel(xw, sheet_name="plateau_diag", index=False)
print(f"\n저장 -> {OUT}")
