"""or_sweep 24개 단독게이트 백테스트의 '거래내역 전부'를 하나의 엑셀로 추출.
- 합본 시트(all_trades): gate 컬럼 + 12원자 보유여부(O/.) + 핵심컬럼.
- 게이트별 시트 24개: 각 백테스트 거래 그대로.
- 요약 시트(summary): 게이트별 n/win%/PF/avgR/train·test PF/연도PF.
각 원자 항목 보유여부는 12원자 컬럼(a_*)을 O(True)/.(False)로 표시 → 한눈에 평가가능.
사용: python export_24_backtests.py [or_sweep_dir] [out_xlsx]
"""
import os, sys, glob
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
SWEEP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "or_sweep")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SWEEP, "all_24_backtests_trades.xlsx")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
FRONT = ["gate", "gate_atom", "gate_pol", "symbol", "side", "entry_time", "exit_time",
         "net_pnl", "r_multiple", "result", "exit_reason", "hold_bars",
         "tier", "grade", "score", "run_potential", "year"]


def pf(s):
    s = np.asarray(s, float)
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def to_bool(col):
    return col.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def gate_meta(name):
    # 디렉토리명: 양극=원자명(volume), 음극=n_원자명(n_room)
    if name.startswith("n_"):
        return name[2:], "음극(False진입)"
    return name, "양극(True진입)"


frames = {}
summ = []
for fp in sorted(glob.glob(os.path.join(SWEEP, "*", "stage4d_trades.csv"))):
    gate = os.path.basename(os.path.dirname(fp))
    d = pd.read_csv(fp)
    if "net_pnl" not in d.columns or len(d) == 0:
        continue
    atom_name, pol = gate_meta(gate)
    d["gate"] = gate
    d["gate_atom"] = atom_name
    d["gate_pol"] = pol
    # 시간/연도
    for c in ["entry_time", "exit_time"]:
        if c in d.columns:
            dt = pd.to_datetime(d[c], utc=True, errors="coerce")
            d[c] = dt.dt.tz_localize(None)
    d["year"] = pd.to_datetime(d["gate"].map(lambda _: None) if False else d["entry_time"], errors="coerce").dt.year \
        if "entry_time" in d.columns else np.nan
    # 12원자 → O/. (보유여부 한눈에)
    for a in ATOMS:
        if a in d.columns:
            d[a] = np.where(to_bool(d[a]), "O", ".")
        else:
            d[a] = "?"
    front = [c for c in FRONT if c in d.columns]
    rest = [c for c in d.columns if c not in front and c not in ATOMS]
    d = d[front + ATOMS + rest]
    frames[gate] = d
    # 요약
    pnl = pd.to_numeric(frames[gate]["net_pnl"], errors="coerce").to_numpy(float)
    yr = frames[gate]["year"].to_numpy()
    rmul = pd.to_numeric(frames[gate].get("r_multiple", pd.Series(np.nan, index=d.index)),
                         errors="coerce").to_numpy(float)
    tr = np.isin(yr, [2023, 2024]); te = np.isin(yr, [2025, 2026])
    summ.append(dict(
        gate=gate, atom=atom_name, pol=pol, n=len(d),
        win_pct=round(100 * (pnl > 0).mean(), 1), PF=round(pf(pnl), 3),
        avgR=round(np.nanmean(rmul), 3),
        PF_train2324=round(pf(pnl[tr]), 3) if tr.sum() else np.nan,
        PF_test2526=round(pf(pnl[te]), 3) if te.sum() else np.nan, nte=int(te.sum()),
        netPnL=round(float(np.nansum(pnl)), 1),
        PF2023=round(pf(pnl[yr == 2023]), 3), PF2024=round(pf(pnl[yr == 2024]), 3),
        PF2025=round(pf(pnl[yr == 2025]), 3), PF2026=round(pf(pnl[yr == 2026]), 3),
    ))

S = pd.DataFrame(summ).sort_values("PF", ascending=False).reset_index(drop=True)
ALL = pd.concat(frames.values(), ignore_index=True)

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    S.to_excel(xw, sheet_name="summary", index=False)
    ALL.to_excel(xw, sheet_name="all_trades", index=False)
    for gate in sorted(frames):
        sheet = gate[:31]  # 엑셀 시트명 31자 제한
        frames[gate].to_excel(xw, sheet_name=sheet, index=False)

print(f"24백테스트 거래 통합 → {OUT}")
print(f"  게이트 {len(frames)}개 | 합본 거래 {len(ALL)}행 | 시트: summary + all_trades + {len(frames)}게이트")
print(f"  원자컬럼 표기: O=보유(True) / .=미보유(False)  ({', '.join(a.replace('a_','') for a in ATOMS)})")
print("  게이트별 거래수:")
for _, r in S.iterrows():
    print(f"    {r['gate']:<20} n={int(r['n']):>5}  PF={r['PF']:.3f}  test2526={r['PF_test2526']}")
