"""SMC 진입 zone 가격(entry=실제 체결 zone 경계)이 피보 되돌림 band / 다중스케일 파동 PRZ와
같은 가격대에서 겹치는지(confluence)를 측정. 핵심: 종가가 아니라 entry(zone 가격)로 probe.
겹침 깊이(0/1/2/3개 합류) 사다리별 승률·avgR을 IS(23-24)/OOS(25-26)로 비교 → "겹칠수록 승률↑" 가설 검증.
룩어헤드 없음: ZigZag 피벗은 확정지연(반전이 K*ATR 넘는 봉에서만 확정), swing은 entry-1까지만.
df_struct=H4, honest bar=entry_idx-1 → 4h 캐시와 일치(코드 line 2463/2368: entry==zone경계, refine OFF).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "zone_confluence.xlsx")

ZK = [1.0, 1.5, 2.0, 3.0]
K0 = 2.0
GP = (0.618, 0.786)          # 골든포켓 되돌림
PRZ = (0.5, 0.886)           # 넓은 PRZ band
RETR_LV = [0.382, 0.5, 0.618, 0.786]
EXT_LV = [1.272, 1.618]
NEAR_ATR = 0.25              # entry가 피보레벨에 ATR*0.25 이내면 '정밀합류'
EXT_ROOM_ATR = 1.0
WARM = 60


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def zigzag(high, low, atr, K):
    L = len(high)
    last = np.full(L, np.nan); prev = np.full(L, np.nan); cdir = np.zeros(L, dtype=np.int8)
    trend = 1; ext = high[0]; c_last = np.nan; c_prev = np.nan; c_d = 0
    for i in range(L):
        a = atr[i]; thr = (K * a) if (a == a and a > 0) else np.inf
        if trend == 1:
            if high[i] > ext:
                ext = high[i]
            if (ext - low[i]) >= thr:
                c_prev = c_last; c_last = ext; c_d = 1; trend = -1; ext = low[i]
        else:
            if low[i] < ext:
                ext = low[i]
            if (high[i] - ext) >= thr:
                c_prev = c_last; c_last = ext; c_d = -1; trend = 1; ext = high[i]
        last[i] = c_last; prev[i] = c_prev; cdir[i] = c_d
    return last, prev, cdir


def frac_at(price, last, prev, cdir):
    """probe price의 임펄스 되돌림 깊이(0=임펄스끝, 1=시작). cdir!=0이고 leg>0일 때만."""
    if cdir == 0 or last != last or prev != prev:
        return np.nan, np.nan, np.nan, np.nan  # frac, hi, lo, leg
    hi = max(last, prev); lo = min(last, prev); leg = hi - lo
    if leg <= 0:
        return np.nan, hi, lo, np.nan
    if cdir == 1:    # 상승임펄스(prev=저점,last=고점), zone은 되돌림 하락 → LONG
        frac = (last - price) / leg
    else:             # 하락임펄스(prev=고점,last=저점), 되돌림 상승 → SHORT
        frac = (price - last) / leg
    return frac, hi, lo, leg


# ── 캐시 로드 & 심볼별 ZigZag 사전계산 ──
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
    c = cdf["close"].values.astype(float)
    atr = atr_series(h, l, c)
    zz = {K: zigzag(h, l, atr, K) for K in ZK}
    pre[s] = dict(pos={t: i for i, t in enumerate(ts)}, atr=atr, zz=zz)

# ── 합류원자 계산 (probe = entry 가격) ──
NEW = ["zc_gp_k2", "zc_prz2", "zc_prz3", "zc_near_fib", "zc_ext_room", "zc_full_stack"]
vals = {k: np.zeros(len(d), dtype=bool) for k in NEW}
depth = np.zeros(len(d), dtype=int)        # 겹침 깊이(gp_k2 + near_fib + prz2)
ok = np.zeros(len(d), dtype=bool)

for r in range(len(d)):
    sym = d["symbol"].iat[r]; et = d["et"].iat[r]; side = d["side"].iat[r]
    px = d["entry"].iat[r]
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

    # K0 골든포켓: entry가 GP band 안 (방향정합)
    last, prev, cdir = (P["zz"][K0][k][ei] for k in range(3))
    f0 = hi0 = lo0 = leg0 = np.nan
    if cdir == fav:
        f0, hi0, lo0, leg0 = frac_at(px, last, prev, cdir)
        if f0 == f0:
            vals["zc_gp_k2"][r] = (GP[0] <= f0 <= GP[1])

    # 다중스케일 PRZ 합의: entry가 [0.5,0.886] band 안인 스케일 수
    cnt = 0
    for K in ZK:
        la, pv, cd = (P["zz"][K][k][ei] for k in range(3))
        if cd == fav:
            fk, _, _, _ = frac_at(px, la, pv, cd)
            if fk == fk and PRZ[0] <= fk <= PRZ[1]:
                cnt += 1
    vals["zc_prz2"][r] = cnt >= 2
    vals["zc_prz3"][r] = cnt >= 3

    # 정밀합류: entry가 K0 swing의 어느 피보 retr 레벨과 ATR*NEAR 이내
    near = False
    if cdir == fav and leg0 == leg0 and leg0 > 0:
        for lv in RETR_LV:
            lvl_price = (hi0 - lv * leg0) if cdir == 1 else (lo0 + lv * leg0)
            if abs(px - lvl_price) <= NEAR_ATR * a:
                near = True; break
    vals["zc_near_fib"][r] = near

    # ext 목표 여력: entry에서 1.272 연장까지 ATR 이상 남음(방향연속)
    if cdir == fav and leg0 == leg0 and leg0 > 0:
        target = (lo0 + 1.272 * leg0) if cdir == 1 else (hi0 - 1.272 * leg0)
        room = (target - px) / a if cdir == 1 else (px - target) / a
        vals["zc_ext_room"][r] = room >= EXT_ROOM_ATR

    depth[r] = int(vals["zc_gp_k2"][r]) + int(near) + int(vals["zc_prz2"][r])
    vals["zc_full_stack"][r] = (vals["zc_gp_k2"][r] and near and vals["zc_prz2"][r])

for k in NEW:
    d[k] = vals[k]
d["conf_depth"] = depth
print(f"[재현] {int(ok.sum())}/{len(d)} 거래 (정직봉 ZigZag 계산 가능)")
D = d[ok].copy()
IS = D.year.isin([2023, 2024]); OOS = D.year.isin([2025, 2026])


def wr(x):
    return round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan


def aR(x):
    return round(float(x.r_multiple.mean()), 3) if len(x) else np.nan


# ── 1) 각 합류원자 ON/OFF 승률·avgR (IS/OOS) ──
def onoff(span, label):
    sub = D[span]; rows = []
    for nk in NEW:
        on = sub[sub[nk]]; off = sub[~sub[nk]]
        rows.append(dict(span=label, atom=nk, n_on=len(on),
                         cover=round(100 * len(on) / max(len(sub), 1), 1),
                         win_on=wr(on), win_off=wr(off),
                         d_win=round(wr(on) - wr(off), 1) if len(on) and len(off) else np.nan,
                         avgR_on=aR(on), avgR_off=aR(off),
                         d_avgR=round(aR(on) - aR(off), 3) if len(on) and len(off) else np.nan))
    return pd.DataFrame(rows)


onoff_is = onoff(IS, "IS"); onoff_oos = onoff(OOS, "OOS")

# ── 2) 핵심: 합류 깊이 사다리 (0/1/2/3) 별 승률·avgR ──
def ladder(span, label):
    sub = D[span]; rows = []
    for dlevel in [0, 1, 2, 3]:
        x = sub[sub.conf_depth == dlevel]
        rows.append(dict(span=label, conf_depth=dlevel, n=len(x),
                         win=wr(x), avgR=aR(x),
                         net=round(float(x.net_pnl.sum()), 1) if len(x) else 0.0))
    # 2+ 묶음
    x2 = sub[sub.conf_depth >= 2]
    rows.append(dict(span=label, conf_depth="2+", n=len(x2), win=wr(x2), avgR=aR(x2),
                     net=round(float(x2.net_pnl.sum()), 1) if len(x2) else 0.0))
    return pd.DataFrame(rows)


lad_is = ladder(IS, "IS"); lad_oos = ladder(OOS, "OOS"); lad_all = ladder(D.index == D.index, "ALL")

# ── 3) atr_expansion 앵커 위에서 합류 한계기여 (IS) ──
def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


atr_atom = tb(D["a_atr_expansion"]).to_numpy()
base = D[IS & pd.Series(atr_atom, index=D.index)]
marg = [dict(combo="atr_expansion (단독)", n=len(base), win=wr(base), avgR=aR(base))]
for nk in NEW + ["conf_depth>=2"]:
    if nk == "conf_depth>=2":
        m = IS & pd.Series(atr_atom, index=D.index) & (D.conf_depth >= 2)
    else:
        m = IS & pd.Series(atr_atom, index=D.index) & D[nk]
    x = D[m]
    marg.append(dict(combo=f"atr_expansion ∩ {nk}", n=len(x), win=wr(x), avgR=aR(x)))
marg = pd.DataFrame(marg)
marg["d_avgR"] = (marg["avgR"] - marg["avgR"].iloc[0]).round(3)
marg["d_win"] = (marg["win"] - marg["win"].iloc[0]).round(1)

pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
print("\n[*** 핵심: 합류 깊이(0/1/2/3=gp+near+prz2) 사다리별 승률·avgR ***]")
print("  가설: 깊이↑ → 승률↑. IS와 OOS 둘 다 단조증가해야 진짜.")
print("[ALL]"); print(lad_all.to_string(index=False))
print("[IS] "); print(lad_is.to_string(index=False))
print("[OOS]"); print(lad_oos.to_string(index=False))
print("\n[1) 합류원자 ON/OFF 승률·avgR - IS]")
print(onoff_is.to_string(index=False))
print("\n[1) 합류원자 ON/OFF 승률·avgR - OOS]")
print(onoff_oos.to_string(index=False))
print("\n[3) atr_expansion 앵커 위 합류 한계기여 - IS]")
print(marg.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    pd.concat([lad_all, lad_is, lad_oos]).to_excel(xw, sheet_name="confluence_ladder", index=False)
    onoff_is.to_excel(xw, sheet_name="atom_onoff_IS", index=False)
    onoff_oos.to_excel(xw, sheet_name="atom_onoff_OOS", index=False)
    marg.to_excel(xw, sheet_name="atr_anchor_marginal_IS", index=False)
print(f"\n저장 -> {OUT}")
