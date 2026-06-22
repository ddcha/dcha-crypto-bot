"""신규축 원자(레짐3 + OHLCV신규3)를 캐시 H4에서 진입-1봉 기준 재현 → 기존 16원자와
① 상관(phi, 직교성) ② 개별 honest-lift(avgR/win, ON-OFF) ③ atr_expansion 앵커 한계기여.
레짐3은 다른 플랫폼 정의와 동일 공식(독립 재현=교차검증). 룩어헤드: 전부 ei=entry-1 까지만 읽음.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "newaxis_lift_corr.xlsx")

# 다른 플랫폼 REG_* 와 동일
EFF_N, EFF_MIN = 10, 0.30
BB_N, BB_K, BB_WIN, BB_SQ = 20, 2.0, 100, 0.30
VOL_WIN, VOL_PCTL = 100, 0.50


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def atr_series(df):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(14).mean().values


def bbw(close, j):
    s = close[j - BB_N + 1: j + 1]
    m = s.mean(); sd = s.std()
    return (2.0 * BB_K * sd) / m if m > 0 else np.nan


d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["et"].dt.year
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
acols = [c for c in d.columns if c.startswith("a_")]
exist = [c.replace("a_", "") for c in acols]

# 심볼별 캐시 인덱싱
cache = {}
for sym in d["symbol"].unique():
    fp = os.path.join(DLC, f"{sym}_4h.parquet")
    cdf = pd.read_parquet(fp).reset_index(drop=True)
    cdf["ts"] = pd.to_datetime(cdf["timestamp"], utc=True)
    pos = {t: i for i, t in enumerate(cdf["ts"])}
    cache[sym] = (cdf, pos, cdf["close"].values.astype(float),
                  cdf["volume"].values.astype(float), atr_series(cdf),
                  cdf["high"].values.astype(float), cdf["low"].values.astype(float))

NEW = ["n_efficiency", "n_bb_squeeze", "n_vol_expansion", "n_at_discount", "n_vol_rising", "n_mom_with"]
vals = {k: np.zeros(len(d), dtype=bool) for k in NEW}
ok = np.zeros(len(d), dtype=bool)

for r in range(len(d)):
    sym = d["symbol"].iat[r]; et = d["et"].iat[r]; side = d["side"].iat[r]
    cdf, pos, close, vol, atr, high, low = cache[sym]
    if et not in pos:
        continue
    ei = pos[et] - 1               # ⭐ 진입-1 = 정직봉
    if ei < (BB_N + BB_WIN) or ei < VOL_WIN or ei < 20:
        continue
    ok[r] = True
    # efficiency (Kaufman ER)
    seg = close[ei - EFF_N: ei + 1]
    den = np.sum(np.abs(np.diff(seg)))
    if den > 0:
        vals["n_efficiency"][r] = (abs(seg[-1] - seg[0]) / den) >= EFF_MIN
    # bb_squeeze
    cur = bbw(close, ei)
    hist = np.array([bbw(close, j) for j in range(ei - BB_WIN, ei)])
    hist = hist[~np.isnan(hist)]
    if (not np.isnan(cur)) and len(hist) >= 20:
        vals["n_bb_squeeze"][r] = (hist < cur).mean() <= BB_SQ
    # vol_expansion
    aseg = atr[ei - VOL_WIN: ei + 1]; acur = atr[ei]
    aseg = aseg[~np.isnan(aseg)]
    if len(aseg) >= 20 and not np.isnan(acur):
        vals["n_vol_expansion"][r] = (aseg < acur).mean() >= VOL_PCTL
    # at_discount: 진입가가 최근20봉 레인지의 유리한 절반 (롱=하단, 숏=상단)
    rng_hi = high[ei - 20: ei + 1].max(); rng_lo = low[ei - 20: ei + 1].min()
    if rng_hi > rng_lo:
        p = (close[ei] - rng_lo) / (rng_hi - rng_lo)
        vals["n_at_discount"][r] = (p <= 0.4) if side == "long" else (p >= 0.6)
    # vol_rising: 최근3봉 평균 거래량 > 직전3봉 평균
    if vol[ei - 6: ei - 3].mean() > 0:
        vals["n_vol_rising"][r] = vol[ei - 3: ei + 1].mean() > vol[ei - 6: ei - 3].mean()
    # mom_with: 최근5봉 모멘텀이 방향과 정합
    vals["n_mom_with"][r] = (close[ei] > close[ei - 5]) if side == "long" else (close[ei] < close[ei - 5])

for k in NEW:
    d[k] = vals[k]
print(f"[재현 성공] {int(ok.sum())}/{len(d)} 거래 (정직봉 계산 가능)")
D = d[ok].copy()
IS = D.year.isin([2023, 2024]); OOS = D.year.isin([2025, 2026])

# 기존 16 booleans
EX = {nm: tb(D[f"a_{nm}"]).to_numpy() for nm in exist}

# ── 1) 상관(phi) : 신규 vs 기존16 ──
def phi(a, b):
    a = a.astype(float); b = b.astype(float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])

corr_rows = []
for nk in NEW:
    na = D[nk].to_numpy()
    cors = sorted(((phi(na, EX[em]), em) for em in exist), key=lambda x: -abs(x[0]))
    top = "; ".join(f"{em}:{c:+.2f}" for c, em in cors[:4])
    corr_rows.append(dict(new_atom=nk, cover_pct=round(100 * na.mean(), 1),
                          max_abs_corr=round(abs(cors[0][0]), 2), top4_corr_existing=top))
corr_tbl = pd.DataFrame(corr_rows)

# 전체 상관행렬(신규 x 기존)
mat = pd.DataFrame({nk: [round(phi(D[nk].to_numpy(), EX[em]), 2) for em in exist] for nk in NEW}, index=exist)

# ── 2) 개별 honest-lift (ON-OFF) IS/OOS ──
def lift(mask_span):
    rows = []
    sub = D[mask_span]
    for nk in NEW:
        on = sub[sub[nk]]; off = sub[~sub[nk]]
        rows.append(dict(new_atom=nk, n_on=len(on), cover=round(100*len(on)/max(len(sub),1),1),
                         avgR_on=round(on.r_multiple.mean(),3) if len(on) else np.nan,
                         avgR_off=round(off.r_multiple.mean(),3) if len(off) else np.nan,
                         lift_avgR=round((on.r_multiple.mean()-off.r_multiple.mean()),3) if len(on) and len(off) else np.nan,
                         win_on=round(100*(on.net_pnl>0).mean(),1) if len(on) else np.nan,
                         win_off=round(100*(off.net_pnl>0).mean(),1) if len(off) else np.nan))
    return pd.DataFrame(rows)

lift_is = lift(IS); lift_oos = lift(OOS)

# ── 3) atr_expansion 앵커 한계기여: atr만 vs atr∩신규 (IS) ──
atr = EX["atr_expansion"]
base = D[IS & pd.Series(atr, index=D.index)]
marg_rows = [dict(combo="atr_expansion (단독)", n=len(base),
                  avgR=round(base.r_multiple.mean(),3), win=round(100*(base.net_pnl>0).mean(),1))]
for nk in NEW:
    m = IS & pd.Series(atr, index=D.index) & D[nk]
    x = D[m]
    marg_rows.append(dict(combo=f"atr_expansion ∩ {nk}", n=len(x),
                          avgR=round(x.r_multiple.mean(),3) if len(x) else np.nan,
                          win=round(100*(x.net_pnl>0).mean(),1) if len(x) else np.nan))
marg = pd.DataFrame(marg_rows)
marg["d_avgR_vs_base"] = (marg["avgR"] - marg["avgR"].iloc[0]).round(3)

print("\n[1) 신규 vs 기존16 최대상관 (직교성)]")
print(corr_tbl.to_string(index=False))
print("\n[2) 개별 honest-lift - IS(2023-24)]")
print(lift_is.to_string(index=False))
print("\n[2) 개별 honest-lift - OOS(2025-26) 참고]")
print(lift_oos.to_string(index=False))
print("\n[3) atr_expansion 앵커에 신규원자 한계기여 - IS]")
print(marg.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    corr_tbl.to_excel(xw, sheet_name="corr_summary", index=False)
    mat.to_excel(xw, sheet_name="corr_matrix")
    lift_is.to_excel(xw, sheet_name="lift_IS", index=False)
    lift_oos.to_excel(xw, sheet_name="lift_OOS", index=False)
    marg.to_excel(xw, sheet_name="atr_anchor_marginal_IS", index=False)
print(f"\n저장 -> {OUT}")
