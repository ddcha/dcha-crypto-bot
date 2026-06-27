# 블록2 단계A: 미측정 7원자 전방향 변별력 스윕 (사후, 저장 CSV) — 즉시
import numpy as np, pandas as pd, json
def pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))
d = pd.read_csv("atom_alpha_result/base_trades_with_raw.csv")
d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
n = len(d); k = int(n * 0.7); oos = d.iloc[k:]
pnl_o = oos["net_pnl"].values.astype(float); rr = d["r_multiple"].values.astype(float)
print(f"base {n} / OOS {len(oos)}\n")
best = {}

def sweep(label, col, specs):
    print(f"=== {label} ===")
    print(f"{'방향':<8}{'op':>3}{'thr':>6}{'pass%':>7}{'n_oosT':>7}{'OOS_PF_T':>10}{'OOS_PF_F':>10}{'disc':>8}{'expR_T':>8}")
    raw = d[col].values.astype(float); raw_o = oos[col].values.astype(float)
    rows = []
    for direction, op, thrs in specs:
        for t in thrs:
            with np.errstate(invalid="ignore"):
                m = (raw >= t) if op == "ge" else (raw < t)
                mo = (raw_o >= t) if op == "ge" else (raw_o < t)
            m = m & ~np.isnan(raw); mo = mo & ~np.isnan(raw_o)
            pt = pf(pnl_o[mo]); pff = pf(pnl_o[~mo]); disc = pt - pff if (np.isfinite(pt) and np.isfinite(pff)) else np.nan
            er = float(np.nanmean(rr[m])) if m.any() else np.nan
            print(f"{direction:<8}{op:>3}{t:>6}{m.mean()*100:>7.1f}{int(mo.sum()):>7}{pt:>10.3f}{pff:>10.3f}{disc:>8.3f}{er:>8.4f}")
            rows.append((direction, op, t, int(mo.sum()), pt, pff, disc))
    valid = [r for r in rows if r[3] >= 20 and np.isfinite(r[6])]
    if valid:
        b = max(valid, key=lambda r: r[6]); best[label] = {"dir": b[0], "op": b[1], "thr": b[2], "disc": round(b[6], 3), "OOS_PF_T": round(b[4], 3), "n_oosT": b[3]}
        print(f"  ★ {b[0]} {b[1]} {b[2]} | disc={b[6]:.3f} OOS_PF_T={b[4]:.3f}\n")
    else:
        print("  (유효없음)\n")

def boolsweep(label, col, invert_label="없음"):
    print(f"=== {label} (존재 vs {invert_label}) ===")
    b = d[col].astype(bool).values; bo = oos[col].astype(bool).values
    for nm, mo in [("존재(True)", bo), (f"{invert_label}(False)", ~bo)]:
        pt = pf(pnl_o[mo]); pff = pf(pnl_o[~mo])
        m = b if "존재" in nm else ~b
        print(f"  {nm:<14} pass%={m.mean()*100:5.1f} n_oosT={int(mo.sum()):4} OOS_PF_T={pt:6.3f} OOS_PF_F={pff:6.3f} disc={pt-pff:+.3f}")
    print()

sweep("score_ge13", "score", [("양극", "ge", [10, 11, 12, 13, 15]), ("NOT저점수", "lt", [10, 11, 13])])
sweep("sweep_count", "pre_entry_sweep", [("양극", "ge", [2, 3, 4]), ("NOT", "lt", [2, 3])])
sweep("pre_total_ge1", "pre_entry_total", [("양극", "ge", [1, 2, 3]), ("NOT", "lt", [1, 2])])
sweep("pre_total_ge4(=pt>=3)", "pre_entry_total", [("양극", "ge", [3]), ("NOT", "lt", [3])])
boolsweep("a_ob", "a_ob", "OB없음")
boolsweep("zone_has_ob(순수OB유무)", "zone_has_ob", "OB전무")
boolsweep("a_sweep", "a_sweep", "sweep없음")
boolsweep("a_mss", "a_mss", "mss없음")
print("=== 블록2 사후 변별력 최대 후보 (→ 실측) ===")
print(json.dumps(best, indent=2, ensure_ascii=False))
