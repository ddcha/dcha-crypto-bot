"""넣을 수 있는 모든 축의 신규원자(횡단면 상대강도 + 고차모멘트/변동성구조 + 유동성 +
통계/정보이론 + 피보나치/엘리어트 PRZ)를 캐시 4h에서 진입-1봉(정직봉) 기준 재현 →
기존 16원자와 ① phi상관(직교성) ② 개별 honest-lift(avgR ON-OFF, IS/OOS) ③ atr_expansion 앵커 한계기여.
규율: in-sample 조합선택 아님. 개별 lift>0 AND IS/OOS 부호일치 = 통과. 룩어헤드 전부 ei<=entry-1.
피보/엘리어트: ZigZag(K*ATR) 피벗을 확정지연(반전이 K*ATR 넘는 봉에서만 확정)으로 만들어 entry-1까지만 사용.
            피보레벨은 상수(0.5/0.618/0.786/1.272/1.618), K만 자유 -> 다중스케일 합의로 plateau 확인.
멀티코어: 코인별 정밀 시계열 사전계산을 프로세스풀로 병렬. 거래 1457건은 사전계산 배열을 ei 인덱싱만.
"""
import os
import math
import itertools
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "allaxis_lift_corr.xlsx")

# ── 파라미터(고정; 피보레벨은 상수, ZigZag K만 다중스케일) ──
RS_N = 30          # 횡단면 수익률 룩백(봉)
RATIO_WIN = 60     # 가격비 z 윈도
SKEW_N = 20        # 실현왜도 윈도
GK_WIN, GK_MED = 20, 100
VOV_WIN, VOV_MED = 20, 100
AMI_N, AMI_MED = 20, 100
ROLL_N, ROLL_MED = 20, 100
HURST_WIN = 64
PE_WIN, PE_ORDER, PE_MED = 50, 3, 200
AC_WIN = 30
ZK = [1.0, 1.5, 2.0, 3.0]     # ZigZag ATR배수 스케일
FIB_GP = (0.618, 0.786)        # 골든포켓
FIB_PRZ = (0.5, 0.886)         # 넓은 PRZ
EXT_RATIO = 1.272              # 연장 목표
EXT_ROOM_ATR = 1.0            # ext까지 남은거리(ATR) 최소

WARM = max(HURST_WIN, PE_MED, GK_MED, VOV_MED, AMI_MED, ROLL_MED, RATIO_WIN, 120)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def hurst_win(ts):
    n = len(ts)
    if n < 16:
        return np.nan
    lags = np.arange(2, min(20, n // 2))
    tau = np.array([np.std(ts[lag:] - ts[:-lag]) for lag in lags])
    good = tau > 0
    if good.sum() < 3:
        return np.nan
    return float(np.polyfit(np.log(lags[good]), np.log(tau[good]), 1)[0])


_PERMS = {o: {p: i for i, p in enumerate(itertools.permutations(range(o)))} for o in (PE_ORDER,)}


def perm_entropy_win(x, order=PE_ORDER):
    n = len(x) - order + 1
    if n <= 1:
        return np.nan
    pidx = _PERMS[order]
    counts = np.zeros(math.factorial(order))
    for i in range(n):
        counts[pidx[tuple(np.argsort(x[i:i + order]))]] += 1
    pr = counts[counts > 0] / counts.sum()
    return float(-np.sum(pr * np.log(pr)) / np.log(math.factorial(order)))


def roll_spread_win(dp):
    # Roll(1984) 내재스프레드: 2*sqrt(-cov(dp_t, dp_{t-1})), 음공분산만 정의
    if len(dp) < 3:
        return np.nan
    c = np.cov(dp[1:], dp[:-1])[0, 1]
    return 2.0 * math.sqrt(-c) if c < 0 else 0.0


def zigzag(high, low, atr, K):
    """확정지연 ZigZag. 반환: last_piv, prev_piv, cdir(+1=last가 고점/상승임펄스, -1=저점/하락임펄스)."""
    L = len(high)
    last = np.full(L, np.nan); prev = np.full(L, np.nan); cdir = np.zeros(L, dtype=np.int8)
    trend = 1
    ext = high[0]
    c_last = np.nan; c_prev = np.nan; c_d = 0
    for i in range(L):
        a = atr[i]
        thr = (K * a) if (a == a and a > 0) else np.inf
        if trend == 1:
            if high[i] > ext:
                ext = high[i]
            if (ext - low[i]) >= thr:
                c_prev = c_last; c_last = ext; c_d = 1
                trend = -1; ext = low[i]
        else:
            if low[i] < ext:
                ext = low[i]
            if (high[i] - ext) >= thr:
                c_prev = c_last; c_last = ext; c_d = -1
                trend = 1; ext = high[i]
        last[i] = c_last; prev[i] = c_prev; cdir[i] = c_d
    return last, prev, cdir


def fib_frac(close, last, prev, cdir):
    """현 종가의 임펄스 되돌림 깊이(0=임펄스끝, 1=시작). cdir==0이면 nan. 방향은 cdir로 구분."""
    L = len(close)
    frac = np.full(L, np.nan)
    for i in range(L):
        d = cdir[i]
        if d == 0 or last[i] != last[i] or prev[i] != prev[i]:
            continue
        hi = max(last[i], prev[i]); lo = min(last[i], prev[i])
        leg = hi - lo
        if leg <= 0:
            continue
        if d == 1:   # 상승임펄스(prev=저점,last=고점) 되돌림 하락
            frac[i] = (last[i] - close[i]) / leg
        else:         # 하락임펄스(prev=고점,last=저점) 되돌림 상승
            frac[i] = (close[i] - last[i]) / leg
    return frac


def ext_room_atr(close, last, prev, cdir, atr):
    """연장목표(EXT_RATIO)까지 남은거리/ATR (방향연속 가정). cdir favorable쪽만 의미."""
    L = len(close)
    room = np.full(L, np.nan)
    for i in range(L):
        d = cdir[i]
        if d == 0 or last[i] != last[i] or prev[i] != prev[i] or atr[i] != atr[i] or atr[i] <= 0:
            continue
        hi = max(last[i], prev[i]); lo = min(last[i], prev[i]); leg = hi - lo
        if leg <= 0:
            continue
        if d == 1:
            target = lo + EXT_RATIO * leg     # 상방 연장
            room[i] = (target - close[i]) / atr[i]
        else:
            target = hi - EXT_RATIO * leg     # 하방 연장
            room[i] = (close[i] - target) / atr[i]
    return room


def precompute_symbol(args):
    sym, fp = args
    cdf = pd.read_parquet(fp).reset_index(drop=True)
    ts = pd.DatetimeIndex(pd.to_datetime(cdf["timestamp"], utc=True))
    o = cdf["open"].values.astype(float); h = cdf["high"].values.astype(float)
    l = cdf["low"].values.astype(float); c = cdf["close"].values.astype(float)
    v = cdf["volume"].values.astype(float)
    L = len(c)
    atr = atr_series(h, l, c)
    cs = pd.Series(c)
    logc = np.log(np.clip(c, 1e-12, None))
    logret = pd.Series(np.concatenate([[0.0], np.diff(logc)]))

    # 고차모멘트/변동성구조
    skew = logret.rolling(SKEW_N).skew().values
    atr7 = atr_series(h, l, c, 7); atr28 = atr_series(h, l, c, 28)
    vterm = np.where(atr28 > 0, atr7 / atr28, np.nan)
    # Garman-Klass
    with np.errstate(divide="ignore", invalid="ignore"):
        gk_bar = 0.5 * (np.log(h / l)) ** 2 - (2 * math.log(2) - 1) * (np.log(c / o)) ** 2
    gk = pd.Series(gk_bar).rolling(GK_WIN).mean().values
    gk_med = pd.Series(gk).rolling(GK_MED).median().values
    atr_s = pd.Series(atr)
    vov = atr_s.rolling(VOV_WIN).std().values
    vov_med = pd.Series(vov).rolling(VOV_MED).median().values

    # 유동성
    dollar = np.abs(logret.values) / np.where(v > 0, v, np.nan)
    ami = pd.Series(dollar).rolling(AMI_N).mean().values
    ami_med = pd.Series(ami).rolling(AMI_MED).median().values
    dp = pd.Series(np.concatenate([[0.0], np.diff(c)]))
    roll = dp.rolling(ROLL_N).apply(roll_spread_win, raw=True).values
    roll_med = pd.Series(roll).rolling(ROLL_MED).median().values

    # 통계/정보
    hurst = pd.Series(logc).rolling(HURST_WIN).apply(hurst_win, raw=True).values
    pe = logret.rolling(PE_WIN).apply(perm_entropy_win, raw=True).values
    pe_med = pd.Series(pe).rolling(PE_MED).median().values
    ac = logret.rolling(AC_WIN).apply(lambda x: pd.Series(x).autocorr(1) if np.std(x) > 0 else 0.0, raw=False).values

    # 피보/엘리어트 다중스케일
    fr = {}; rm = {}; cd = {}
    for K in ZK:
        last, prev, cdir = zigzag(h, l, atr, K)
        fr[K] = fib_frac(c, last, prev, cdir)
        rm[K] = ext_room_atr(c, last, prev, cdir, atr)
        cd[K] = cdir

    out = dict(
        ts=ts, close=c, retN=(cs / cs.shift(RS_N) - 1).values,
        skew=skew, vterm=vterm, gk=gk, gk_med=gk_med, vov=vov, vov_med=vov_med,
        ami=ami, ami_med=ami_med, roll=roll, roll_med=roll_med,
        hurst=hurst, pe=pe, pe_med=pe_med, ac=ac, atr=atr,
        fr=fr, rm=rm, cd=cd,
    )
    return sym, out


# ── 거래/심볼 로드 ──
d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["et"].dt.year
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
acols = [c for c in d.columns if c.startswith("a_")]
exist = [c.replace("a_", "") for c in acols]
syms = sorted(d["symbol"].unique())


def main():
    jobs = [(s, os.path.join(DLC, f"{s}_4h.parquet")) for s in syms]
    pre = {}
    with ProcessPoolExecutor(max_workers=min(len(jobs), os.cpu_count())) as ex:
        for sym, out in ex.map(precompute_symbol, jobs):
            pre[sym] = out
    print(f"[사전계산 완료] {len(pre)}개 코인 정밀 시계열")

    # 심볼별 ts->pos
    posmap = {s: {t: i for i, t in enumerate(pre[s]["ts"])} for s in syms}

    # ── 횡단면 패널(공유 4h ts 정렬) ──
    closes = pd.DataFrame({s: pd.Series(pre[s]["close"], index=pre[s]["ts"]) for s in syms}).sort_index()
    retP = closes / closes.shift(RS_N) - 1.0
    rankP = retP.rank(axis=1, pct=True)
    breadthP = (retP > 0).sum(axis=1) / retP.notna().sum(axis=1).clip(lower=1)
    dispP = retP.std(axis=1)
    disp_medP = dispP.rolling(100).median()
    ratio = closes.div(closes["BTCUSDT"], axis=0)
    ratio_z = (ratio - ratio.rolling(RATIO_WIN).mean()) / ratio.rolling(RATIO_WIN).std()
    pos_panel = {t: i for i, t in enumerate(closes.index)}
    rank_a = rankP.values; ret_a = retP.values; col_i = {s: j for j, s in enumerate(closes.columns)}
    breadth_a = breadthP.values; disp_a = dispP.values; dispm_a = disp_medP.values
    rz_a = ratio_z.values; btc_j = col_i["BTCUSDT"]

    NEW = ["x_rs_strong", "x_outperform_btc", "x_breadth_with", "x_dispersion_high", "x_rel_cheap",
           "m_skew_with", "v_term_expand", "v_gk_high", "v_vov_high",
           "l_amihud_high", "l_roll_high",
           "s_hurst_trend", "s_pe_low", "s_ac_pos",
           "f_golden_pocket", "f_prz_consensus", "f_fib_ext_room"]
    vals = {k: np.zeros(len(d), dtype=bool) for k in NEW}
    ok = np.zeros(len(d), dtype=bool)

    for r in range(len(d)):
        sym = d["symbol"].iat[r]; et = d["et"].iat[r]; side = d["side"].iat[r]
        P = pre[sym]; pm = posmap[sym]
        if et not in pm:
            continue
        ei = pm[et] - 1                       # 정직봉
        if ei < WARM:
            continue
        hts = P["ts"][ei]                      # 정직봉 타임스탬프(횡단면 조회용)
        long = (side == "long")
        ok[r] = True

        # 횡단면
        if hts in pos_panel:
            pj = pos_panel[hts]; sj = col_i.get(sym)
            rk = rank_a[pj, sj] if sj is not None else np.nan
            if rk == rk:
                vals["x_rs_strong"][r] = (rk >= 0.6) if long else (rk <= 0.4)
            sret = ret_a[pj, sj] if sj is not None else np.nan
            bret = ret_a[pj, btc_j]
            if sret == sret and bret == bret:
                vals["x_outperform_btc"][r] = (sret > bret) if long else (sret < bret)
            br = breadth_a[pj]
            if br == br:
                vals["x_breadth_with"][r] = (br >= 0.5) if long else (br <= 0.5)
            if disp_a[pj] == disp_a[pj] and dispm_a[pj] == dispm_a[pj]:
                vals["x_dispersion_high"][r] = disp_a[pj] >= dispm_a[pj]
            rz = rz_a[pj, sj] if sj is not None else np.nan
            if rz == rz:
                vals["x_rel_cheap"][r] = (rz <= -1.0) if long else (rz >= 1.0)

        # 고차모멘트/변동성
        sk = P["skew"][ei]
        if sk == sk:
            vals["m_skew_with"][r] = (sk > 0) if long else (sk < 0)
        vt = P["vterm"][ei]
        if vt == vt:
            vals["v_term_expand"][r] = vt >= 1.0
        if P["gk"][ei] == P["gk"][ei] and P["gk_med"][ei] == P["gk_med"][ei]:
            vals["v_gk_high"][r] = P["gk"][ei] >= P["gk_med"][ei]
        if P["vov"][ei] == P["vov"][ei] and P["vov_med"][ei] == P["vov_med"][ei]:
            vals["v_vov_high"][r] = P["vov"][ei] >= P["vov_med"][ei]

        # 유동성
        if P["ami"][ei] == P["ami"][ei] and P["ami_med"][ei] == P["ami_med"][ei]:
            vals["l_amihud_high"][r] = P["ami"][ei] >= P["ami_med"][ei]
        if P["roll"][ei] == P["roll"][ei] and P["roll_med"][ei] == P["roll_med"][ei]:
            vals["l_roll_high"][r] = P["roll"][ei] >= P["roll_med"][ei]

        # 통계/정보
        hu = P["hurst"][ei]
        if hu == hu:
            vals["s_hurst_trend"][r] = hu >= 0.5
        if P["pe"][ei] == P["pe"][ei] and P["pe_med"][ei] == P["pe_med"][ei]:
            vals["s_pe_low"][r] = P["pe"][ei] <= P["pe_med"][ei]
        acv = P["ac"][ei]
        if acv == acv:
            vals["s_ac_pos"][r] = acv >= 0.0

        # 피보/엘리어트: favorable 방향 = long이면 상승임펄스(cd==1), short이면 하락임펄스(cd==-1)
        fav = 1 if long else -1
        # golden pocket at K=2.0
        K0 = 2.0
        if P["cd"][K0][ei] == fav:
            fr0 = P["fr"][K0][ei]
            if fr0 == fr0:
                vals["f_golden_pocket"][r] = (FIB_GP[0] <= fr0 <= FIB_GP[1])
        # PRZ 합의(다중스케일)
        cnt = 0
        for K in ZK:
            if P["cd"][K][ei] == fav:
                frk = P["fr"][K][ei]
                if frk == frk and (FIB_PRZ[0] <= frk <= FIB_PRZ[1]):
                    cnt += 1
        vals["f_prz_consensus"][r] = cnt >= 2
        # ext room at K=2.0
        if P["cd"][K0][ei] == fav:
            rmv = P["rm"][K0][ei]
            if rmv == rmv:
                vals["f_fib_ext_room"][r] = rmv >= EXT_ROOM_ATR

    for k in NEW:
        d[k] = vals[k]
    print(f"[재현 성공] {int(ok.sum())}/{len(d)} 거래 (정직봉 계산 가능, WARM={WARM})")
    D = d[ok].copy()
    IS = D.year.isin([2023, 2024]); OOS = D.year.isin([2025, 2026])
    EX = {nm: tb(D[f"a_{nm}"]).to_numpy() for nm in exist}

    # ── 1) phi 상관(신규 vs 기존16) ──
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
    mat = pd.DataFrame({nk: [round(phi(D[nk].to_numpy(), EX[em]), 2) for em in exist] for nk in NEW}, index=exist)

    # ── 2) 개별 honest-lift (ON-OFF) ──
    def lift(mask_span):
        rows = []; sub = D[mask_span]
        for nk in NEW:
            on = sub[sub[nk]]; off = sub[~sub[nk]]
            rows.append(dict(new_atom=nk, n_on=len(on),
                             cover=round(100 * len(on) / max(len(sub), 1), 1),
                             avgR_on=round(on.r_multiple.mean(), 3) if len(on) else np.nan,
                             avgR_off=round(off.r_multiple.mean(), 3) if len(off) else np.nan,
                             lift_avgR=round((on.r_multiple.mean() - off.r_multiple.mean()), 3) if len(on) and len(off) else np.nan,
                             win_on=round(100 * (on.net_pnl > 0).mean(), 1) if len(on) else np.nan,
                             win_off=round(100 * (off.net_pnl > 0).mean(), 1) if len(off) else np.nan))
        return pd.DataFrame(rows)

    lift_is = lift(IS); lift_oos = lift(OOS)

    # ── 통과판정: IS lift>0 AND OOS lift>0 (부호일치) ──
    verdict = lift_is[["new_atom", "lift_avgR"]].rename(columns={"lift_avgR": "lift_IS"}).merge(
        lift_oos[["new_atom", "lift_avgR"]].rename(columns={"lift_avgR": "lift_OOS"}), on="new_atom")
    verdict = verdict.merge(corr_tbl[["new_atom", "cover_pct", "max_abs_corr"]], on="new_atom")
    verdict["both_pos"] = ((verdict.lift_IS > 0) & (verdict.lift_OOS > 0)).astype(int)
    verdict["sign_agree"] = (np.sign(verdict.lift_IS) == np.sign(verdict.lift_OOS)).astype(int)
    verdict["orthogonal"] = (verdict.max_abs_corr < 0.5).astype(int)
    verdict["PASS"] = ((verdict.both_pos == 1) & (verdict.orthogonal == 1)).astype(int)
    verdict = verdict.sort_values(["PASS", "lift_OOS"], ascending=False).reset_index(drop=True)

    # ── 3) atr_expansion 앵커 한계기여(IS) ──
    atr = EX["atr_expansion"]
    base = D[IS & pd.Series(atr, index=D.index)]
    marg_rows = [dict(combo="atr_expansion (단독)", n=len(base),
                      avgR=round(base.r_multiple.mean(), 3), win=round(100 * (base.net_pnl > 0).mean(), 1))]
    for nk in NEW:
        m = IS & pd.Series(atr, index=D.index) & D[nk]
        x = D[m]
        marg_rows.append(dict(combo=f"atr_expansion ∩ {nk}", n=len(x),
                              avgR=round(x.r_multiple.mean(), 3) if len(x) else np.nan,
                              win=round(100 * (x.net_pnl > 0).mean(), 1) if len(x) else np.nan))
    marg = pd.DataFrame(marg_rows)
    marg["d_avgR_vs_base"] = (marg["avgR"] - marg["avgR"].iloc[0]).round(3)

    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
    print("\n[1) 신규 vs 기존16 최대상관 (직교성)]")
    print(corr_tbl.to_string(index=False))
    print("\n[2) 개별 honest-lift - IS(2023-24)]")
    print(lift_is.to_string(index=False))
    print("\n[2) 개별 honest-lift - OOS(2025-26)]")
    print(lift_oos.to_string(index=False))
    print("\n[*** 통과판정: both_pos(IS&OOS lift>0) AND orthogonal(maxcorr<0.5) ***]")
    print(verdict.to_string(index=False))
    print("\n[3) atr_expansion 앵커에 신규원자 한계기여 - IS]")
    print(marg.to_string(index=False))

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        verdict.to_excel(xw, sheet_name="verdict", index=False)
        corr_tbl.to_excel(xw, sheet_name="corr_summary", index=False)
        mat.to_excel(xw, sheet_name="corr_matrix")
        lift_is.to_excel(xw, sheet_name="lift_IS", index=False)
        lift_oos.to_excel(xw, sheet_name="lift_OOS", index=False)
        marg.to_excel(xw, sheet_name="atr_anchor_marginal_IS", index=False)
    print(f"\n저장 -> {OUT}")


if __name__ == "__main__":
    main()
