"""큰 윈도우(2개월=H4 360봉)부터 줄여가며 피보/PRZ 합류 재측정 (plateau).
사용자 지시: 구조를 봉 열몇개로 만드는 건 너무 작다 → 모든 합류 측정의 lookback을 2개월부터 시작.
각 거래 entry 시점 직전 N봉의 dominant swing(고·저+발생순서로 방향)으로 피보 그리드 → entry(=zone경계)가
골든포켓(0.618~0.786)/넓은PRZ(0.5~0.886)/피보레벨근접에 겹치는지. N=360→20 사다리로 IS/OOS win·avgR.
방향정합: long이면 상승임펄스(저점이 고점보다 먼저)의 되돌림 매수만 유효(fav), short는 반대.
룩어헤드 없음: 윈도우 상한 = ei(=entry봉-1), entry시점 이전 봉만. ON=합류 vs OFF=윈도우swing있으나 비합류(공정).
"""
import os
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
OUT = os.path.join(CDIR, "window_confluence_scan.xlsx")

# H4 봉. 하루 6봉 → 2개월≈360, 1.5달≈270, 1달≈180, 20일≈120, 15일≈90, 10일≈60 ...
WINDOWS = [360, 270, 180, 120, 90, 60, 45, 30, 20]
GP = (0.618, 0.786)
PRZ = (0.5, 0.886)
RETR_LV = [0.382, 0.5, 0.618, 0.786]
TOL = 0.35
WARM = 30


def atr_series(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def precompute(sym):
    cdf = pd.read_parquet(os.path.join(DLC, f"{sym}_4h.parquet")).reset_index(drop=True)
    ts = pd.DatetimeIndex(pd.to_datetime(cdf["timestamp"], utc=True))
    h = cdf["high"].values.astype(float)
    l = cdf["low"].values.astype(float)
    c = cdf["close"].values.astype(float)
    atr = atr_series(h, l, c)
    return sym, dict(pos={t: i for i, t in enumerate(ts)}, h=h, l=l, atr=atr)


d = pd.read_csv(TR)
d["et"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce")
d["year"] = d["et"].dt.year
d["net_pnl"] = pd.to_numeric(d["net_pnl"], errors="coerce")
d["r_multiple"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
d["entry"] = pd.to_numeric(d["entry"], errors="coerce")
syms = sorted(d["symbol"].unique())

if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=min(len(syms), os.cpu_count())) as ex:
        pre = dict(ex.map(precompute, syms))

    n = len(d)
    res = {}
    for N in WINDOWS:
        gp = np.zeros(n, bool); prz = np.zeros(n, bool); near = np.zeros(n, bool)
        has = np.zeros(n, bool); ok = np.zeros(n, bool)
        for r in range(n):
            sym = d["symbol"].iat[r]; et = d["et"].iat[r]
            side = d["side"].iat[r]; px = d["entry"].iat[r]
            P = pre.get(sym)
            if P is None or et not in P["pos"] or px != px:
                continue
            ei = P["pos"][et] - 1            # honest 상한 (entry봉-1)
            s = ei - N + 1
            if ei < WARM or s < 0:
                continue
            a = P["atr"][ei]
            if a != a or a <= 0:
                continue
            ok[r] = True
            wh = P["h"][s:ei + 1]; wl = P["l"][s:ei + 1]
            hi_i = int(np.argmax(wh)); lo_i = int(np.argmin(wl))
            hi = float(wh[hi_i]); lo = float(wl[lo_i])
            leg = hi - lo
            if leg <= 0:
                continue
            fav = 1 if side == "long" else -1
            cd = 1 if hi_i > lo_i else -1     # dominant swing 방향(고점이 저점보다 나중=상승임펄스)
            if cd != fav:                     # 진입방향과 임펄스방향 불일치 → 유효합류 아님
                continue
            has[r] = True
            frac = (hi - px) / leg if cd == 1 else (px - lo) / leg
            if frac != frac:
                continue
            gp[r] = GP[0] <= frac <= GP[1]
            prz[r] = PRZ[0] <= frac <= PRZ[1]
            lv = [(hi - x * leg) if cd == 1 else (lo + x * leg) for x in RETR_LV]
            near[r] = bool(np.min(np.abs(np.array(lv) - px)) <= TOL * a)
        res[N] = dict(gp=gp, prz=prz, near=near, has=has, ok=ok)

    IS = d.year.isin([2023, 2024]).to_numpy()
    OOS = d.year.isin([2025, 2026]).to_numpy()
    pnl = d.net_pnl.to_numpy(); rmul = d.r_multiple.to_numpy()

    def stat(mask):
        m = int(mask.sum())
        if m == 0:
            return m, np.nan, np.nan
        return m, round(100 * (pnl[mask] > 0).mean(), 1), round(float(np.nanmean(rmul[mask])), 3)

    def pf_of(mask):
        p = pnl[mask]
        pos = p[p > 0].sum(); neg = p[p < 0].sum()
        return round(pos / abs(neg), 3) if neg < 0 else np.nan

    def flipstat(mask):
        # 방향만 반전 근사: 동일|R|·진입가, SL/TP 비대칭·수수료 미반영(상한 근사).
        m = int(mask.sum())
        if m == 0:
            return m, np.nan, np.nan, np.nan
        r = rmul[mask]; p = pnl[mask]
        win_flip = round(100 * (p < 0).mean(), 1)       # 원래 진 거래가 이김
        avgR_flip = round(-float(np.nanmean(r)), 3)
        pos = p[p > 0].sum(); neg = p[p < 0].sum()
        pf_flip = round(abs(neg) / pos, 3) if pos > 0 else np.nan  # 반전 PF = 1/원래PF
        return m, win_flip, avgR_flip, pf_flip

    rows = []
    for N in WINDOWS:
        R = res[N]; okm = R["ok"]; hasm = R["has"]
        for flag in ["gp", "prz", "near"]:
            fv = R[flag]
            for span, sm in [("IS", IS), ("OOS", OOS)]:
                on = okm & sm & fv
                off = okm & sm & hasm & ~fv
                n_on, w_on, r_on = stat(on); n_off, w_off, r_off = stat(off)
                rows.append(dict(
                    win_bars=N, days=round(N / 6.0, 1), flag=flag, span=span,
                    cover_has=round(100 * (okm & sm & hasm).sum() / max((okm & sm).sum(), 1), 1),
                    n_on=n_on, win_on=w_on, avgR_on=r_on,
                    n_off=n_off, win_off=w_off, avgR_off=r_off,
                    d_win=round(w_on - w_off, 1) if (n_on and n_off) else np.nan,
                    d_avgR=round(r_on - r_off, 3) if (n_on and n_off) else np.nan))
    scan = pd.DataFrame(rows)

    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
    base_ok = res[WINDOWS[0]]["ok"]
    print(f"[유효거래] {int(base_ok.sum())}/{n} (가장 큰 윈도우 {WINDOWS[0]}봉 기준, WARM={WARM})")
    print("\n== dominant-swing 방향정합 커버리지 (윈도우 swing이 진입방향과 일치한 거래 비율) ==")
    cov = scan[scan.flag == "gp"][["win_bars", "days", "span", "cover_has"]].drop_duplicates()
    print(cov.to_string(index=False))
    print("\n[*** 골든포켓(0.618~0.786) 합류: ON=합류 vs OFF=swing있으나 비합류 ***]")
    print("  plateau: 윈도우 줄여도 d_win/d_avgR이 IS·OOS 양쪽 일관 양수면 진짜 엣지.")
    print(scan[scan.flag == "gp"].to_string(index=False))
    print("\n[넓은 PRZ(0.5~0.886) 합류]")
    print(scan[scan.flag == "prz"].to_string(index=False))
    print("\n[피보레벨 정밀근접(near, ±0.35ATR)]")
    print(scan[scan.flag == "near"].to_string(index=False))

    # ── PRZ 합류에서 '반대매매' 1차 스크리닝 ──
    frows = []
    for N in WINDOWS:
        R = res[N]; okm = R["ok"]; przf = R["prz"]
        for span, sm in [("IS", IS), ("OOS", OOS)]:
            on = okm & sm & przf
            n_o, w_o, r_o = stat(on)
            pf_o = pf_of(on)
            n_f, w_f, r_f, pf_f = flipstat(on)
            frows.append(dict(
                win_bars=N, days=round(N / 6.0, 1), span=span, n=n_o,
                win_orig=w_o, avgR_orig=r_o, PF_orig=pf_o,
                win_flip=w_f, avgR_flip=r_f, PF_flip=pf_f))
    flip = pd.DataFrame(frows)
    print("\n[*** PRZ 합류 '반대매매' 1차 스크리닝 (방향만 반전, 동일|R| 근사) ***]")
    print("  avgR_flip = -avgR_orig (산술), PF_flip = 1/PF_orig. 수수료왕복·SL/TP비대칭 미반영 = 상한.")
    print("  반전이 진짜면 OOS avgR_flip·PF_flip이 윈도우 줄여도 일관 양수/>1 plateau여야 함.")
    print(flip.to_string(index=False))
    print("\n  [OOS만] 반전 후 실제로 돈 버는 스케일이 있나:")
    print(flip[flip.span == "OOS"][["win_bars", "days", "n", "win_flip", "avgR_flip", "PF_flip"]].to_string(index=False))

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        scan.to_excel(xw, sheet_name="window_scan", index=False)
        cov.to_excel(xw, sheet_name="coverage", index=False)
        flip.to_excel(xw, sheet_name="prz_flip", index=False)
    print(f"\n저장 -> {OUT}")
