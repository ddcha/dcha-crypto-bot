# 단계A 전방향(양극/넓힘/음극NOT) 변별력 스윕 + A' room swing60 — 저장 CSV 사후계산(즉시)
import numpy as np, pandas as pd, json
def pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))

d = pd.read_csv("atom_alpha_result/base_trades_with_raw.csv")
d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
d = d.sort_values("exit_time").reset_index(drop=True)
n = len(d); k = int(n * 0.7); oos = d.iloc[k:]
pnl_o = oos["net_pnl"].values.astype(float); rr = d["r_multiple"].values.astype(float)
print(f"base {n}건 / OOS {len(oos)}건\n")

def mask(raw, op, t):
    with np.errstate(invalid="ignore"):
        if op == "ge": m = raw >= t
        elif op == "le": m = raw <= t
        elif op == "gt": m = raw > t
        elif op == "lt": m = raw < t
    return m & ~np.isnan(raw)

best = {}
def sweep(label, col, specs, present=None):
    print(f"=== {label} ===")
    print(f"{'방향':<6}{'op':>3}{'thr':>7}{'pass%':>7}{'n_oosT':>7}{'OOS_PF_T':>10}{'OOS_PF_F':>10}{'disc':>8}{'expR_T':>8}")
    raw = d[col].values.astype(float); raw_o = oos[col].values.astype(float)
    pres = d[present].values.astype(bool) if present else np.ones(n, bool)
    pres_o = oos[present].values.astype(bool) if present else np.ones(len(oos), bool)
    rows = []
    for direction, op, thrs in specs:
        for t in thrs:
            m = mask(raw, op, t) & pres; mo = mask(raw_o, op, t) & pres_o
            pt = pf(pnl_o[mo]); pff = pf(pnl_o[~mo])
            disc = pt - pff if (np.isfinite(pt) and np.isfinite(pff)) else np.nan
            er = float(np.nanmean(rr[m])) if m.any() else np.nan
            print(f"{direction:<6}{op:>3}{t:>7}{m.mean()*100:>7.1f}{int(mo.sum()):>7}"
                  f"{pt:>10.3f}{pff:>10.3f}{disc:>8.3f}{er:>8.4f}")
            rows.append((direction, op, t, int(mo.sum()), pt, pff, disc))
    valid = [r for r in rows if r[3] >= 20 and np.isfinite(r[6])]
    if valid:
        b = max(valid, key=lambda r: r[6])
        best[label] = {"dir": b[0], "op": b[1], "thr": b[2], "disc": round(b[6], 3),
                       "OOS_PF_T": round(b[4], 3), "n_oosT": b[3]}
        print(f"  ★ 변별력최대: {b[0]} {b[1]} {b[2]} | disc={b[6]:.3f} OOS_PF_T={b[4]:.3f}\n")
    else:
        print("  (유효 없음)\n")

sweep("efficiency", "er", [("양극", "ge", [0.30, 0.48, 0.65]), ("넓힘", "ge", [0.20, 0.15, 0.10]),
                           ("NOT", "lt", [0.30, 0.20, 0.15])])
sweep("volume", "relvol", [("양극", "ge", [1.5, 2.0, 2.8]), ("넓힘", "ge", [1.2, 1.0]),
                           ("NOT", "lt", [1.5, 1.2, 1.0])])
sweep("vol_exp", "vol_pctl", [("재확인", "ge", [0.50, 0.70, 0.85]), ("NOT저변동", "lt", [0.50, 0.30, 0.20])])
sweep("wick", "wick", [("양극(짧)", "le", [0.17, 0.35]), ("NOT(긴꼬리)", "gt", [0.17, 0.30])])
sweep("bb", "bb_pctl", [("양극(압축)", "le", [0.20, 0.30]), ("NOT(확장)", "gt", [0.30, 0.40])])

# fvg: 양극(존재+두께) vs 음극(FVG없음)
print("=== fvg (양극: 존재+두께 / 음극: FVG없음) ===")
fp = d["fvg_present"].values.astype(bool); fp_o = oos["fvg_present"].values.astype(bool)
fr = d["fvg_ratio"].values.astype(float); fr_o = oos["fvg_ratio"].values.astype(float)
print(f"{'방향':<10}{'thr':>7}{'pass%':>7}{'n_oosT':>7}{'OOS_PF_T':>10}{'OOS_PF_F':>10}{'disc':>8}")
for t in [0.10, 0.30]:
    m = fp & (fr >= t) & ~np.isnan(fr); mo = fp_o & (fr_o >= t) & ~np.isnan(fr_o)
    pt = pf(pnl_o[mo]); pff = pf(pnl_o[~mo])
    print(f"{'양극존재':<10}{t:>7}{m.mean()*100:>7.1f}{int(mo.sum()):>7}{pt:>10.3f}{pff:>10.3f}{pt-pff:>8.3f}")
m = ~fp; mo = ~fp_o; pt = pf(pnl_o[mo]); pff = pf(pnl_o[~mo])
print(f"{'음극(없음)':<10}{'-':>7}{m.mean()*100:>7.1f}{int(mo.sum()):>7}{pt:>10.3f}{pff:>10.3f}{pt-pff:>8.3f}")
if int((~fp_o).sum()) >= 20 and np.isfinite(pt - pff):
    best["fvg"] = {"dir": "음극(없음)", "op": "notpresent", "thr": None, "disc": round(pt - pff, 3),
                   "OOS_PF_T": round(pt, 3), "n_oosT": int((~fp_o).sum())}
print()

# A' room swing60
print("=== A' room swing60 (타겟=최근60봉 swing, room_rr) ===")
sweep("room_swing", "room_b_swing", [("양극", "ge", [1.0, 1.5, 2.0, 3.0]), ("NOT", "lt", [1.0, 1.5, 2.0])])
a = d["room_b_swing"].dropna().values
print(f"  room_b_swing 분포 25/50/75/90: {np.percentile(a,[25,50,75,90]).round(2).tolist()} | "
      f"RR1~5비중 {((a>=1)&(a<=5)).mean()*100:.0f}%")

print("\n=== 단계A 변별력 최대 후보 (→ 단계B 실측) ===")
print(json.dumps(best, indent=2, ensure_ascii=False))
json.dump(best, open("atom_alpha_result/best2_directions.json", "w"), ensure_ascii=False, indent=2)
