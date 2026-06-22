"""진단: 각 거래의 honest bar(ei=entry-1)에서 confluence에 쓰인 '구조'가 실제 몇 캔들로 만들어졌나.
ZigZag K별로 (a)임펄스 leg 봉수(prev피벗~last피벗), (b)leg 크기(ATR배수), (c)피벗 확정지연 봉수를 측정.
가설검증: leg가 3~8봉짜리 미세구조면 피보/파동 합류는 노이즈. 충분한 캔들(예 >=15~20봉)이어야 진짜 구조.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
ZK = [1.0, 1.5, 2.0, 3.0]


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def zigzag_idx(high, low, atr, K):
    """피벗 가격+인덱스+확정인덱스 추적. 반환: 각 봉 i에서 (last_idx, prev_idx, last_px, prev_px, cdir, confirm_lag)."""
    L = len(high)
    out_li = np.full(L, -1, dtype=np.int64); out_pi = np.full(L, -1, dtype=np.int64)
    out_lp = np.full(L, np.nan); out_pp = np.full(L, np.nan)
    out_d = np.zeros(L, dtype=np.int8); out_lag = np.full(L, -1, dtype=np.int64)
    trend = 1; ext = high[0]; ext_i = 0
    cl_i = -1; cp_i = -1; cl_p = np.nan; cp_p = np.nan; cd = 0; conf_i = -1
    for i in range(L):
        a = atr[i]; thr = (K * a) if (a == a and a > 0) else np.inf
        if trend == 1:
            if high[i] > ext:
                ext = high[i]; ext_i = i
            if (ext - low[i]) >= thr:
                cp_i, cp_p = cl_i, cl_p
                cl_i, cl_p = ext_i, ext; cd = 1; conf_i = i
                trend = -1; ext = low[i]; ext_i = i
        else:
            if low[i] < ext:
                ext = low[i]; ext_i = i
            if (high[i] - ext) >= thr:
                cp_i, cp_p = cl_i, cl_p
                cl_i, cl_p = ext_i, ext; cd = -1; conf_i = i
                trend = 1; ext = high[i]; ext_i = i
        out_li[i] = cl_i; out_pi[i] = cp_i; out_lp[i] = cl_p; out_pp[i] = cp_p
        out_d[i] = cd; out_lag[i] = (i - conf_i) if conf_i >= 0 else -1
    return out_li, out_pi, out_lp, out_pp, out_d, out_lag


d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
syms = sorted(d["symbol"].unique())
pre = {}
for s in syms:
    cdf = pd.read_parquet(os.path.join(DLC, f"{s}_4h.parquet")).reset_index(drop=True)
    ts = pd.DatetimeIndex(pd.to_datetime(cdf["timestamp"], utc=True))
    h = cdf["high"].values.astype(float); l = cdf["low"].values.astype(float); c = cdf["close"].values.astype(float)
    atr = atr_series(h, l, c)
    pre[s] = dict(pos={t: i for i, t in enumerate(ts)}, atr=atr,
                  zz={K: zigzag_idx(h, l, atr, K) for K in ZK})

rows = []
for r in range(len(d)):
    sym = d["symbol"].iat[r]; et = d["et"].iat[r]
    P = pre[sym]
    if et not in P["pos"]:
        continue
    ei = P["pos"][et] - 1
    if ei < 90:
        continue
    a = P["atr"][ei]
    rec = {"K%.1f_legbars" % K: np.nan for K in ZK}
    for K in ZK:
        li, pi, lp, pp, cd, lag = (P["zz"][K][k][ei] for k in range(6))
        if li >= 0 and pi >= 0 and cd != 0:
            legbars = abs(li - pi)
            legatr = abs(lp - pp) / a if (a == a and a > 0) else np.nan
            rec["K%.1f_legbars" % K] = legbars
            rec["K%.1f_legatr" % K] = legatr
            rec["K%.1f_conflag" % K] = lag        # 마지막 피벗이 확정된 뒤 지난 봉수(되돌림 진행도)
    rows.append(rec)

R = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(f"[거래 {len(R)}건의 honest bar에서 ZigZag 구조 크기]\n")
print("== 임펄스 leg 봉수 (prev피벗 ~ last피벗 사이 캔들 수) ==")
for K in ZK:
    s = R["K%.1f_legbars" % K].dropna()
    print(f"  K={K}: n={len(s):4d}  median={s.median():5.1f}  p25={s.quantile(.25):4.1f}  "
          f"p75={s.quantile(.75):5.1f}  max={s.max():5.0f}  | <=8봉비율={100*(s<=8).mean():4.1f}%  <=15봉={100*(s<=15).mean():4.1f}%")
print("\n== 임펄스 leg 크기 (ATR 배수) ==")
for K in ZK:
    s = R["K%.1f_legatr" % K].dropna()
    print(f"  K={K}: median={s.median():5.2f}ATR  p25={s.quantile(.25):4.2f}  p75={s.quantile(.75):5.2f}")
print("\n== 마지막 피벗 확정 후 경과봉(되돌림 성숙도; 0이면 갓 확정) ==")
for K in ZK:
    s = R["K%.1f_conflag" % K].dropna()
    print(f"  K={K}: median={s.median():5.1f}  p25={s.quantile(.25):4.1f}  p75={s.quantile(.75):5.1f}  ==0비율={100*(s==0).mean():4.1f}%")
