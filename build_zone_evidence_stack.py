"""공간적 합류(confluence-at-zone) 검증: 여러 독립 증거가 진입 zone 가격(entry)에 동시에 떨어지는가.
직교성이 아니라 '같은 가격대에 증거가 겹치느냐'. 각 증거를 entry±TOL*ATR 안에 들어오는지로 판정하고,
겹친 증거 개수(confluence score)별 승률·avgR을 IS(23-24)/OOS(25-26)로 비교 → '많이 겹칠수록 승률↑' 검증.
증거셋(전부 honest bar ei=entry-1, 룩어헤드 없음):
  ev_fib   : 확정 swing의 피보 retr레벨(0.5/0.618/0.786)이 entry 근처
  ev_prz   : 다중스케일 ZigZag 되돌림 band가 entry를 포함(>=2 스케일)
  ev_liq   : 확정된 직전 스윙고/저(유동성 레벨)가 entry 근처
  ev_htf   : 상위TF(4h->1D) 확정 스윙고/저가 entry 근처
  ev_round : 심리적 라운드넘버가 entry 근처
  ev_vnode : 볼륨프로파일 POC(최대거래 가격대)가 entry 근처
  ev_disc  : 프리미엄/디스카운트 정합(long=레인지 하단부 / short=상단부)
참고: 기존 pre_total(zone내 OB/FVG 증거수)은 이미 해로운5에 포함(음성). 여기선 더 넓은 증거셋으로 재검.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "zone_evidence_stack.xlsx")

ZK = [1.0, 1.5, 2.0, 3.0]
K0 = 2.0
PRZ = (0.5, 0.886)
RETR_LV = [0.5, 0.618, 0.786]
TOL = 0.35              # entry±TOL*ATR 안이면 '그 가격대에 증거 있음'
SWING_LEN = 3          # 스윙 피벗 확정지연(좌우 n봉)
HTF_SWING = 2          # 일봉 스윙 좌우 n봉
LIQ_LOOK = 60          # 유동성 피벗 탐색 룩백
VN_WIN, VN_BINS = 80, 40
EQ_WIN = 40
WARM = 90


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def zigzag(high, low, atr, K):
    L = len(high)
    last = np.full(L, np.nan); prev = np.full(L, np.nan); cdir = np.zeros(L, dtype=np.int8)
    trend = 1; ext = high[0]; cl = np.nan; cp = np.nan; cd = 0
    for i in range(L):
        a = atr[i]; thr = (K * a) if (a == a and a > 0) else np.inf
        if trend == 1:
            if high[i] > ext:
                ext = high[i]
            if (ext - low[i]) >= thr:
                cp = cl; cl = ext; cd = 1; trend = -1; ext = low[i]
        else:
            if low[i] < ext:
                ext = low[i]
            if (high[i] - ext) >= thr:
                cp = cl; cl = ext; cd = -1; trend = 1; ext = high[i]
        last[i] = cl; prev[i] = cp; cdir[i] = cd
    return last, prev, cdir


def confirmed_pivots(high, low, sl):
    """좌우 sl봉 기준 스윙고/저. 피벗 p는 p+sl봉에서 확정 → (확정idx, 가격) 리스트."""
    L = len(high); piv = []  # (confirm_idx, price, kind)
    for p in range(sl, L - sl):
        wl = slice(p - sl, p + sl + 1)
        if high[p] == high[wl].max() and high[p] > high[p - 1]:
            piv.append((p + sl, high[p], 1))
        if low[p] == low[wl].min() and low[p] < low[p - 1]:
            piv.append((p + sl, low[p], -1))
    piv.sort()
    return np.array([x[0] for x in piv]), np.array([x[1] for x in piv])


# ── 로드 ──
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
    h = cdf["high"].values.astype(float); l = cdf["low"].values.astype(float)
    c = cdf["close"].values.astype(float); v = cdf["volume"].values.astype(float)
    atr = atr_series(h, l, c)
    zz = {K: zigzag(h, l, atr, K) for K in ZK}
    pidx, ppx = confirmed_pivots(h, l, SWING_LEN)
    # 상위TF 일봉(4h*6) 스윙 → 확정되는 4h 인덱스로 맵핑
    g = pd.DataFrame({"ts": ts, "h": h, "l": l}).set_index("ts")
    dd = g.resample("1D").agg(h=("h", "max"), l=("l", "min")).dropna()
    dh = dd["h"].values; dl = dd["l"].values; dday = dd.index
    htf = []  # (confirm_4h_idx, price)
    for p in range(HTF_SWING, len(dd) - HTF_SWING):
        wl = slice(p - HTF_SWING, p + HTF_SWING + 1)
        confirm_day = dday[p + HTF_SWING]
        ci = ts.searchsorted(confirm_day + pd.Timedelta("1D"))  # 그 일봉 닫힌 뒤 첫 4h
        if dh[p] == dh[wl].max():
            htf.append((ci, dh[p]))
        if dl[p] == dl[wl].min():
            htf.append((ci, dl[p]))
    htf.sort()
    hidx = np.array([x[0] for x in htf]); hpx = np.array([x[1] for x in htf])
    pre[s] = dict(pos={t: i for i, t in enumerate(ts)}, atr=atr, zz=zz,
                  h=h, l=l, c=c, v=v, pidx=pidx, ppx=ppx, hidx=hidx, hpx=hpx)

EV = ["ev_fib", "ev_prz", "ev_liq", "ev_htf", "ev_round", "ev_vnode", "ev_disc"]
vals = {k: np.zeros(len(d), dtype=bool) for k in EV}
ok = np.zeros(len(d), dtype=bool)


def near_any(prices, px, tol):
    if len(prices) == 0:
        return False
    return bool(np.min(np.abs(prices - px)) <= tol)


def round_levels(px):
    if px <= 0:
        return np.array([])
    step = 10 ** (np.floor(np.log10(px)) - 1)   # 가격자릿수 기반 라운드 간격
    base = np.floor(px / step) * step
    return np.array([base + k * step for k in (-1, 0, 1, 2)] +
                    [base + 0.5 * step, base + 1.5 * step])


for r in range(len(d)):
    sym = d["symbol"].iat[r]; et = d["et"].iat[r]; side = d["side"].iat[r]
    px = d["entry"].iat[r]; P = pre[sym]
    if et not in P["pos"] or px != px:
        continue
    ei = P["pos"][et] - 1
    if ei < WARM:
        continue
    a = P["atr"][ei]
    if a != a or a <= 0:
        continue
    ok[r] = True
    tol = TOL * a
    fav = 1 if side == "long" else -1

    # ev_fib (K0 favorable swing의 retr레벨이 entry 근처)
    last, prev, cdir = (P["zz"][K0][k][ei] for k in range(3))
    if cdir == fav and last == last and prev == prev:
        hi = max(last, prev); lo = min(last, prev); leg = hi - lo
        if leg > 0:
            levels = [(hi - lv * leg) if cdir == 1 else (lo + lv * leg) for lv in RETR_LV]
            if near_any(np.array(levels), px, tol):
                vals["ev_fib"][r] = True

    # ev_prz (다중스케일 되돌림 band가 entry 포함, >=2)
    cnt = 0
    for K in ZK:
        la, pv, cd = (P["zz"][K][k][ei] for k in range(3))
        if cd == fav and la == la and pv == pv:
            hi = max(la, pv); lo = min(la, pv); leg = hi - lo
            if leg > 0:
                frac = (la - px) / leg if cd == 1 else (px - la) / leg
                if PRZ[0] <= frac <= PRZ[1]:
                    cnt += 1
    vals["ev_prz"][r] = cnt >= 2

    # ev_liq (확정 직전 스윙 피벗이 entry 근처; LIQ_LOOK 내)
    pidx = P["pidx"]; ppx = P["ppx"]
    j1 = np.searchsorted(pidx, ei - LIQ_LOOK, "left"); j2 = np.searchsorted(pidx, ei + 1, "right")
    vals["ev_liq"][r] = near_any(ppx[j1:j2], px, tol)

    # ev_htf (상위TF 확정 스윙이 entry 근처)
    hidx = P["hidx"]; hpx = P["hpx"]
    k2 = np.searchsorted(hidx, ei + 1, "right")
    vals["ev_htf"][r] = near_any(hpx[max(0, k2 - 30):k2], px, tol)

    # ev_round
    vals["ev_round"][r] = near_any(round_levels(px), px, tol)

    # ev_vnode (볼륨프로파일 POC)
    s0 = max(0, ei - VN_WIN + 1)
    cc = P["c"][s0:ei + 1]; vv = P["v"][s0:ei + 1]
    if len(cc) >= 10 and cc.max() > cc.min():
        hist, edges = np.histogram(cc, bins=VN_BINS, weights=vv)
        b = int(np.argmax(hist)); poc = 0.5 * (edges[b] + edges[b + 1])
        vals["ev_vnode"][r] = abs(px - poc) <= tol

    # ev_disc (프리미엄/디스카운트 정합)
    s1 = max(0, ei - EQ_WIN + 1)
    rng_hi = P["h"][s1:ei + 1].max(); rng_lo = P["l"][s1:ei + 1].min()
    if rng_hi > rng_lo:
        mid = 0.5 * (rng_hi + rng_lo)
        vals["ev_disc"][r] = (px <= mid) if side == "long" else (px >= mid)

for k in EV:
    d[k] = vals[k]
d["conf_score"] = sum(d[k].astype(int) for k in EV)
print(f"[재현] {int(ok.sum())}/{len(d)} 거래 (정직봉 증거계산 가능)")
D = d[ok].copy()
IS = D.year.isin([2023, 2024]); OOS = D.year.isin([2025, 2026])


def wr(x):
    return round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan


def aR(x):
    return round(float(x.r_multiple.mean()), 3) if len(x) else np.nan


# ── 핵심: 합류점수 사다리 ──
def ladder(span, label):
    sub = D[span]; rows = []
    for sc in range(0, int(D.conf_score.max()) + 1):
        x = sub[sub.conf_score == sc]
        rows.append(dict(span=label, conf_score=sc, n=len(x), win=wr(x), avgR=aR(x),
                         net=round(float(x.net_pnl.sum()), 1) if len(x) else 0.0))
    for thr in [2, 3]:
        x = sub[sub.conf_score >= thr]
        rows.append(dict(span=label, conf_score=f">={thr}", n=len(x), win=wr(x), avgR=aR(x),
                         net=round(float(x.net_pnl.sum()), 1) if len(x) else 0.0))
    return pd.DataFrame(rows)


lad_all = ladder(D.index == D.index, "ALL"); lad_is = ladder(IS, "IS"); lad_oos = ladder(OOS, "OOS")


# ── 각 증거 단독 ON/OFF (커버리지·승률) ──
def onoff(span, label):
    sub = D[span]; rows = []
    for nk in EV:
        on = sub[sub[nk]]; off = sub[~sub[nk]]
        rows.append(dict(span=label, evidence=nk, n_on=len(on),
                         cover=round(100 * len(on) / max(len(sub), 1), 1),
                         win_on=wr(on), win_off=wr(off),
                         d_win=round(wr(on) - wr(off), 1) if len(on) and len(off) else np.nan,
                         avgR_on=aR(on), d_avgR=round(aR(on) - aR(off), 3) if len(on) and len(off) else np.nan))
    return pd.DataFrame(rows)


oo_is = onoff(IS, "IS"); oo_oos = onoff(OOS, "OOS")

pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
print("\n[*** 핵심: 합류점수(증거 겹친 개수)별 승률·avgR. 가설=점수↑→승률↑, IS·OOS 둘다 단조여야 진짜 ***]")
print("[ALL]"); print(lad_all.to_string(index=False))
print("[IS] "); print(lad_is.to_string(index=False))
print("[OOS]"); print(lad_oos.to_string(index=False))
print("\n[증거 커버리지·분포]")
print(D[EV + ["conf_score"]].astype(int).describe().loc[["mean"]].round(3).to_string())
print(D["conf_score"].value_counts().sort_index().to_string())
print("\n[각 증거 단독 ON/OFF - IS]"); print(oo_is.to_string(index=False))
print("\n[각 증거 단독 ON/OFF - OOS]"); print(oo_oos.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    pd.concat([lad_all, lad_is, lad_oos]).to_excel(xw, sheet_name="confluence_ladder", index=False)
    oo_is.to_excel(xw, sheet_name="evidence_onoff_IS", index=False)
    oo_oos.to_excel(xw, sheet_name="evidence_onoff_OOS", index=False)
    D[["symbol", "entry_time", "side", "year", "entry"] + EV + ["conf_score", "r_multiple", "net_pnl"]].to_excel(
        xw, sheet_name="per_trade", index=False)
print(f"\n저장 -> {OUT}")
