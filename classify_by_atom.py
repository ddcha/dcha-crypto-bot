"""모든 거래(1457, floor7.5 atoms_corr)를 16개 원자별로 분류.
각 원자 A에 대해: A=True 거래 vs A=False 거래의 n/PF/avgR/win 을 ALL·IS(23-24)·OOS(25-26)로 분해.
solo 효과(원자 단독 켜짐의 평균기여)와 커버리지(전체 중 비율)를 본다. 진단용, 검증 아님.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "stage4d_trades.csv")
OUT = os.path.join(ROOT, "stage4d_honest", "atoms_corr", "classify_by_atom.xlsx")


def pf(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
names = [c.replace("a_", "") for c in acols]
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
d["yr"] = pd.to_datetime(d["entry_time"], errors="coerce").dt.year
IS = d.yr.isin([2023, 2024]); OOS = d.yr.isin([2025, 2026])
N = len(d)


def stat(x):
    return dict(n=int(len(x)),
                PF=round(pf(x.net_pnl), 3),
                avgR=round(float(x.r_multiple.mean()), 3) if len(x) else np.nan,
                win=round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan,
                net=round(float(x.net_pnl.sum()), 1))


# 1) 단일원자 ON/OFF 표 (ALL/IS/OOS)
rows = []
for col, nm in zip(acols, names):
    on = tb(d[col])
    for span_tag, mask in [("ALL", pd.Series(True, index=d.index)), ("IS", IS), ("OOS", OOS)]:
        xon = d[on & mask]; xoff = d[~on & mask]
        s_on = stat(xon); s_off = stat(xoff)
        rows.append(dict(atom=nm, span=span_tag, cover_pct=round(100 * len(xon) / max(int(mask.sum()), 1), 1),
                         on_n=s_on["n"], on_PF=s_on["PF"], on_avgR=s_on["avgR"], on_win=s_on["win"],
                         off_n=s_off["n"], off_PF=s_off["PF"], off_avgR=s_off["avgR"],
                         d_avgR=round((s_on["avgR"] - s_off["avgR"]), 3)
                         if (s_on["avgR"] == s_on["avgR"] and s_off["avgR"] == s_off["avgR"]) else np.nan))
solo = pd.DataFrame(rows)

# 2) 각 거래가 켜고 있는 원자 개수 분포
d["atoms_on"] = sum(tb(d[c]).astype(int) for c in acols)
prof = []
for span_tag, mask in [("ALL", pd.Series(True, index=d.index)), ("IS", IS), ("OOS", OOS)]:
    x = d[mask]
    prof.append(dict(span=span_tag, n=int(len(x)),
                     mean_atoms_on=round(float(x.atoms_on.mean()), 2),
                     med_atoms_on=int(x.atoms_on.median()),
                     min_on=int(x.atoms_on.min()), max_on=int(x.atoms_on.max())))
profile = pd.DataFrame(prof)

# 3) 켜진 원자수 밴드별 성과 (복잡한 신호가 더 좋은가)
band_rows = []
for lo, hi, lab in [(0, 4, "0-3"), (4, 6, "4-5"), (6, 8, "6-7"), (8, 99, "8+")]:
    m = (d.atoms_on >= lo) & (d.atoms_on < hi)
    for span_tag, sm in [("ALL", m), ("IS", m & IS), ("OOS", m & OOS)]:
        x = d[sm]; s = stat(x)
        band_rows.append(dict(atoms_on=lab, span=span_tag, **s))
bands = pd.DataFrame(band_rows)

print(f"[전 거래 {N}개 원자분류] IS={int(IS.sum())} OOS={int(OOS.sum())}\n")
print("[거래당 켜진 원자수 프로파일]")
print(profile.to_string(index=False))
print("\n[단일원자 ON/OFF - OOS 기준 d_avgR(ON-OFF) 내림차순]")
oos = solo[solo.span == "OOS"].sort_values("d_avgR", ascending=False)
print(oos[["atom", "cover_pct", "on_n", "on_PF", "on_avgR", "off_avgR", "d_avgR"]].to_string(index=False))
print("\n[단일원자 ON/OFF - IS 기준 d_avgR 내림차순]")
isb = solo[solo.span == "IS"].sort_values("d_avgR", ascending=False)
print(isb[["atom", "cover_pct", "on_n", "on_PF", "on_avgR", "off_avgR", "d_avgR"]].to_string(index=False))
print("\n[켜진 원자수 밴드별 성과]")
print(bands.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    solo.to_excel(xw, sheet_name="solo_atom_on_off", index=False)
    profile.to_excel(xw, sheet_name="atoms_on_profile", index=False)
    bands.to_excel(xw, sheet_name="atoms_on_bands", index=False)
print(f"\n저장 -> {OUT}")
