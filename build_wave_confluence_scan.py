"""'진짜 파동' 위에서만 피보 합류 재측정 + 구조최소크기 임계 스캔(plateau 확인).
미세구조(leg 1~5봉) 제거: 임펄스 leg가 min_bars 이상 & size_atr 이상인 확정 스윙만 유효 파동으로 인정.
파동 후보 = K∈{2,3,4,5}*ATR ZigZag 피벗 풀(확정지연), 크기조건 만족하는 '가장 최근 임펄스' 선택.
probe = entry(=실제 zone 경계 가격). 각 임계마다 골든포켓/PRZ 합류의 win/avgR(IS·OOS, ON vs OFF) 보고.
가설: 구조가 충분히 크면 피보 합류가 음성에서 벗어나는가? 여러 임계서 일관(plateau)해야 진짜.
룩어헤드 없음: confirm_idx<=ei(=entry-1), last_idx<=ei.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "wave_confluence_scan.xlsx")

KSET = [2.0, 3.0, 4.0, 5.0]
THRESHOLDS = [(15, 3.0), (20, 4.0), (30, 5.0), (40, 6.0)]   # (min_bars, min_leg_ATR)
GP = (0.618, 0.786)
PRZ = (0.5, 0.886)
RETR_LV = [0.5, 0.618, 0.786]
TOL = 0.35
SEARCH_BACK = 400          # 최근 이 봉수 내 임펄스만 고려
WARM = 120


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def zigzag_events(high, low, atr, K):
    """확정 스윙 이벤트 리스트: (confirm_idx, prev_idx, last_idx, prev_px, last_px, cdir)."""
    L = len(high); ev = []
    trend = 1; ext = high[0]; ext_i = 0; cl_i = -1; cl_p = np.nan
    for i in range(L):
        a = atr[i]; thr = (K * a) if (a == a and a > 0) else np.inf
        if trend == 1:
            if high[i] > ext:
                ext = high[i]; ext_i = i
            if (ext - low[i]) >= thr:
                if cl_i >= 0:
                    ev.append((i, cl_i, ext_i, cl_p, ext, 1))   # 상승임펄스 prev=저점 last=고점
                cl_i, cl_p = ext_i, ext; trend = -1; ext = low[i]; ext_i = i
        else:
            if low[i] < ext:
                ext = low[i]; ext_i = i
            if (high[i] - ext) >= thr:
                if cl_i >= 0:
                    ev.append((i, cl_i, ext_i, cl_p, ext, -1))  # 하락임펄스 prev=고점 last=저점
                cl_i, cl_p = ext_i, ext; trend = 1; ext = high[i]; ext_i = i
    return ev


# ── 로드 + 심볼별 파동 이벤트 풀 ──
d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["et"].dt.year
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
d["entry"] = pd.to_numeric(d["entry"], errors="coerce")
syms = sorted(d["symbol"].unique())

pre = {}
for s in syms:
    cdf = pd.read_parquet(os.path.join(DLC, f"{s}_4h.parquet")).reset_index(drop=True)
    ts = pd.DatetimeIndex(pd.to_datetime(cdf["timestamp"], utc=True))
    h = cdf["high"].values.astype(float); l = cdf["low"].values.astype(float); c = cdf["close"].values.astype(float)
    atr = atr_series(h, l, c)
    pool = {}
    for K in KSET:
        for (ci, pi, li, pp, lp, cd) in zigzag_events(h, l, atr, K):
            pool[(pi, li)] = (ci, pi, li, pp, lp, cd)   # (prev,last) 중복제거
    ev = sorted(pool.values(), key=lambda x: x[2])       # last_idx 정렬
    ev = np.array(ev, dtype=float) if ev else np.zeros((0, 6))
    pre[s] = dict(pos={t: i for i, t in enumerate(ts)}, atr=atr, ev=ev)


def pick_wave(ev, ei, fav, min_bars, atr_ei):
    """confirm<=ei & last<=ei & 방향fav & leg_bars>=min_bars & legATR>=size 중 last_idx 최대(최근 임펄스)."""
    if len(ev) == 0:
        return None
    ci = ev[:, 0]; pi = ev[:, 1]; li = ev[:, 2]; pp = ev[:, 3]; lp = ev[:, 4]; cd = ev[:, 5]
    m = (ci <= ei) & (li <= ei) & (li >= ei - SEARCH_BACK) & (cd == fav)
    legbars = np.abs(li - pi)
    legatr = np.abs(lp - pp) / atr_ei if atr_ei > 0 else np.zeros_like(lp)
    m &= (legbars >= min_bars[0]) & (legatr >= min_bars[1])
    if not m.any():
        return None
    idx = np.where(m)[0]
    best = idx[np.argmax(li[idx])]
    return pp[best], lp[best], int(cd[best])


def frac_of(px, prev_px, last_px, cd):
    hi = max(prev_px, last_px); lo = min(prev_px, last_px); leg = hi - lo
    if leg <= 0:
        return np.nan, hi, lo, leg
    return ((last_px - px) / leg if cd == 1 else (px - last_px) / leg), hi, lo, leg


# ── 각 임계마다 합류 플래그 계산 ──
res = {}
for (mb, sz) in THRESHOLDS:
    gp = np.zeros(len(d), bool); prz = np.zeros(len(d), bool); near = np.zeros(len(d), bool)
    has = np.zeros(len(d), bool); ok = np.zeros(len(d), bool)
    for r in range(len(d)):
        sym = d["symbol"].iat[r]; et = d["et"].iat[r]; side = d["side"].iat[r]; px = d["entry"].iat[r]
        P = pre[sym]
        if et not in P["pos"] or px != px:
            continue
        ei = P["pos"][et] - 1
        if ei < WARM:
            continue
        a = P["atr"][ei]
        if a != a or a <= 0:
            continue
        ok[r] = True
        fav = 1 if side == "long" else -1
        w = pick_wave(P["ev"], ei, fav, (mb, sz), a)
        if w is None:
            continue
        has[r] = True
        prev_px, last_px, cd = w
        frac, hi, lo, leg = frac_of(px, prev_px, last_px, cd)
        if frac != frac:
            continue
        gp[r] = GP[0] <= frac <= GP[1]
        prz[r] = PRZ[0] <= frac <= PRZ[1]
        if leg > 0:
            lv = [(hi - x * leg) if cd == 1 else (lo + x * leg) for x in RETR_LV]
            near[r] = bool(np.min(np.abs(np.array(lv) - px)) <= TOL * a)
    res[(mb, sz)] = dict(gp=gp, prz=prz, near=near, has=has, ok=ok)

D = d.copy()
base_ok = res[THRESHOLDS[0]]["ok"]
IS = D.year.isin([2023, 2024]).to_numpy(); OOS = D.year.isin([2025, 2026]).to_numpy()
pnl = D.net_pnl.to_numpy(); rmul = D.r_multiple.to_numpy()


def stat(mask):
    n = int(mask.sum())
    if n == 0:
        return n, np.nan, np.nan
    return n, round(100 * (pnl[mask] > 0).mean(), 1), round(float(np.nanmean(rmul[mask])), 3)


# ── 스캔 결과표: 임계 x (gp/prz) x (IS/OOS) ON vs OFF ──
rows = []
for (mb, sz) in THRESHOLDS:
    R = res[(mb, sz)]; okm = R["ok"]; hasm = R["has"]
    for flag in ["gp", "prz", "near"]:
        fv = R[flag]
        for span, sm in [("IS", IS), ("OOS", OOS)]:
            on = okm & sm & fv
            off = okm & sm & hasm & ~fv          # 유효파동 있으나 합류 아님 (공정비교)
            n_on, w_on, r_on = stat(on); n_off, w_off, r_off = stat(off)
            rows.append(dict(min_bars=mb, leg_ATR=sz, flag=flag, span=span,
                             cover_has=round(100 * (okm & sm & hasm).sum() / max((okm & sm).sum(), 1), 1),
                             n_on=n_on, win_on=w_on, avgR_on=r_on,
                             n_off=n_off, win_off=w_off, avgR_off=r_off,
                             d_win=round(w_on - w_off, 1) if (n_on and n_off) else np.nan,
                             d_avgR=round(r_on - r_off, 3) if (n_on and n_off) else np.nan))
scan = pd.DataFrame(rows)

pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
print(f"[유효파동 가능 거래] {int(base_ok.sum())}/{len(D)} (WARM={WARM})")
print("\n== 파동 보유 커버리지 (크기조건 만족 임펄스가 존재하는 거래 비율) ==")
cov = scan[scan.flag == "gp"][["min_bars", "leg_ATR", "span", "cover_has"]].drop_duplicates()
print(cov.to_string(index=False))
print("\n[*** 임계 스캔: '진짜 파동' 골든포켓 합류 win/avgR (ON=합류 vs OFF=파동있으나 비합류) ***]")
print("  plateau 확인: min_bars 키워도 d_win/d_avgR이 IS·OOS 양쪽 일관 양수면 진짜.")
print(scan[scan.flag == "gp"].to_string(index=False))
print("\n[넓은 PRZ(0.5~0.886) 합류]")
print(scan[scan.flag == "prz"].to_string(index=False))
print("\n[피보레벨 정밀근접(near)]")
print(scan[scan.flag == "near"].to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    scan.to_excel(xw, sheet_name="threshold_scan", index=False)
    cov.to_excel(xw, sheet_name="wave_coverage", index=False)
print(f"\n저장 -> {OUT}")
