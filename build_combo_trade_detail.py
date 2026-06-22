"""정제 core 견고조합의 IS(2023-24) 거래를 한 건씩 세부 분해.
조합별 시트 = 개별 거래(심볼/시간/side/score/tier/RP/결과/R/손익).
summary 시트 = 조합 x 연도, 조합 x 심볼 분포. OOS(2025-26)는 동결검증용으로 미포함.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
OUT = os.path.join(CDIR, "combo_trade_detail_IS.xlsx")

# 견고 후보(표본 충분 + 약한해 R>0) + 참고용 두 개
COMBOS = [
    ("atr_expansion", "disp_strength"),
    ("trend_align", "atr_expansion"),
    ("volume", "atr_expansion"),
    ("killzone", "atr_expansion"),
    ("atr_expansion", "volume_strict"),
    ("fvg", "atr_expansion"),        # 참고: IS 좋으나 fvg OOS 부호역전 전력
    ("trend_align", "fvg"),          # 참고: non-atr 유일 worst_avgR>0
]

DETAIL = ["symbol", "entry_time", "exit_time", "side", "year", "score", "grade",
          "tier", "run_potential", "rp_action", "expansion_state", "hold_bars",
          "result", "exit_reason", "r_multiple", "net_pnl"]


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def pf(s):
    s = np.asarray(s, dtype=float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


d = pd.read_csv(TR)
d["year"] = pd.to_datetime(d["entry_time"], errors="coerce").dt.year
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
B = {c.replace("a_", ""): tb(d[c]).to_numpy() for c in d.columns if c.startswith("a_")}
IS = d.year.isin([2023, 2024]).to_numpy()


def sheetname(combo):
    s = "x".join(a[:6] for a in combo)
    return s[:31]


summary_rows = []
sym_rows = []
detail_sheets = {}
for combo in COMBOS:
    m = IS.copy()
    for a in combo:
        m = m & B[a]
    sub = d[m].sort_values("entry_time").copy()
    label = "∩".join(combo)
    # 연도 분포
    for y in [2023, 2024]:
        x = sub[sub.year == y]
        summary_rows.append(dict(combo=label, year=y, n=int(len(x)),
                                 PF=round(pf(x.net_pnl), 3),
                                 avgR=round(float(x.r_multiple.mean()), 3) if len(x) else np.nan,
                                 win=round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan,
                                 net=round(float(x.net_pnl.sum()), 1)))
    summary_rows.append(dict(combo=label, year="IS_all", n=int(len(sub)),
                             PF=round(pf(sub.net_pnl), 3),
                             avgR=round(float(sub.r_multiple.mean()), 3) if len(sub) else np.nan,
                             win=round(100 * (sub.net_pnl > 0).mean(), 1) if len(sub) else np.nan,
                             net=round(float(sub.net_pnl.sum()), 1)))
    # 심볼 분포
    for sym, g in sub.groupby("symbol"):
        sym_rows.append(dict(combo=label, symbol=sym, n=int(len(g)),
                             avgR=round(float(g.r_multiple.mean()), 3),
                             net=round(float(g.net_pnl.sum()), 1),
                             win=round(100 * (g.net_pnl > 0).mean(), 1)))
    detail_sheets[sheetname(combo)] = (label, sub[DETAIL].reset_index(drop=True))

summary = pd.DataFrame(summary_rows)
symdist = pd.DataFrame(sym_rows)

print("[조합별 IS 거래 요약 (연도)]")
print(summary.to_string(index=False))
print("\n[조합별 심볼 분포]")
print(symdist.sort_values(["combo", "n"], ascending=[True, False]).to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    summary.to_excel(xw, sheet_name="summary_year", index=False)
    symdist.to_excel(xw, sheet_name="summary_symbol", index=False)
    for sn, (label, df) in detail_sheets.items():
        df.to_excel(xw, sheet_name=sn, index=False)
print(f"\n저장 -> {OUT}")
print("  시트:", "summary_year, summary_symbol, " + ", ".join(detail_sheets.keys()))
for combo in COMBOS:
    sn = sheetname(combo)
    print(f"   {sn:32s} = {'∩'.join(combo)}  (n={len(detail_sheets[sn][1])})")
