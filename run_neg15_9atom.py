#!/usr/bin/env python3
# 196셋업(setups_solo10_neg15) union 진짜게이트 백테스트 + 4L KRW 자본시뮬.
#   음극게이트(~a_fvg/~a_trend_align) — _combo_union_match 음극패치됨. 병렬 candidate(prepared 캐시).
#   확정임계 REG_VOL_PCTL=0.85, BROAD_FVG_SIZE_ATR=0(→~a_fvg=FVG없음). room swing60 영구.
#   자본시뮬: 4L 이식(BOOST/tier/phase/excess 제외), KRW, 룩어헤드테스트 필수.
import os, json, time, pickle
import multiprocessing as mp

CACHE = "prepared_cache.pkl"
SETUPS_JSON = "setups_9atom_neg15.json"
OUTDIR = "neg15_9atom_result"
# 자본시뮬 설정 (KRW)
INIT_KRW = 5_000_000; MONTHLY_KRW = 2_500_000; NDEP = 5
KRW_USDT = 1540.0; RISK_PCT = 0.01; FEE = 0.00055; MAXNOT = 3.0
REF = {"n": 1780, "PF": 1.18, "OOS": 1.22}


def _setup():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
        os.environ.pop(_k, None)
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85; F.BROAD_FVG_SIZE_ATR = 0.0
    return F


_PREP = None; _ATOMSETS = None
def _init_worker(cache_path, json_path):
    _setup()
    global _PREP, _ATOMSETS
    _ATOMSETS = [s["atoms"] for s in json.load(open(json_path, encoding="utf-8"))]
    import smc_stage4d.simulation as sim
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    with open(cache_path, "rb") as f:
        _PREP = pickle.load(f)


def _gen_one(sym):
    import smc_stage4d.simulation as sim
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    out = sim.generate_candidates_from_prepared(_PREP[sym])
    return sym, out["candidates"]


# ── 음극지원 매칭/귀속 ──
def _amatch(getter, a):
    return (not bool(getter(a[1:]))) if a.startswith("~") else bool(getter(a))


def attribute(getter, setups):
    matched = []
    for idx, su in enumerate(setups):
        if all(_amatch(getter, a) for a in su["atoms"]):
            matched.append((idx, su["key"], len(su["atoms"])))
    if not matched:
        return "", 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]
    return best[1], len(matched)


def main():
    import numpy as np, pandas as pd
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
    REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2022, 2023, 2024, 2025, 2026]
    setups = json.load(open(SETUPS_JSON, encoding="utf-8"))
    ncore = max(1, min(mp.cpu_count() - 1, len(SYMBOLS)))
    _setup()
    if not os.path.exists(CACHE):
        print("[ERR] prepared_cache.pkl 없음 — run_solo10_par 먼저"); return
    with open(CACHE, "rb") as f:
        prepared = pickle.load(f)
    print(f"[INFO] 196셋업 union | core={ncore} | REG_VOL_PCTL=0.85 BROAD_FVG=0 room=swing60 | "
          f"자본 시드{INIT_KRW:,}+월{MONTHLY_KRW:,}x{NDEP}")

    # ── candidate 병렬 + simulate ──
    print("\n[STEP1] union candidate 병렬 + simulate")
    t1 = time.time()
    with mp.Pool(ncore, initializer=_init_worker, initargs=(CACHE, SETUPS_JSON)) as pool:
        res = pool.map(_gen_one, SYMBOLS)
        # 멱등성: 재실행
        res2 = pool.map(_gen_one, SYMBOLS)
    n1 = sum(len(c) for _, c in res); n2 = sum(len(c) for _, c in res2)
    print(f"  [멱등성] 1패스 {n1} / 2패스 {n2} {'✅' if n1 == n2 else '❌비멱등'}")
    assert n1 == n2, "비멱등"
    cand = {s: {"candidates": c, "df_h4": prepared[s]["df_struct"], "df_h1": prepared[s]["df_h1"], "symbol": s}
            for s, c in res}
    trades = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)["trades"].copy()
    print(f"[STEP1] 완료 {time.time()-t1:.0f}s | 진입 거래 {len(trades)}")

    # ── 귀속(음극) + 태깅 ──
    lab = trades.apply(lambda r: attribute(lambda a: r.get(a, False), setups), axis=1)
    trades["matched_setup"] = [x[0] for x in lab]; trades["n_setups_matched"] = [x[1] for x in lab]
    zero = int((trades["n_setups_matched"] == 0).sum())
    TAG10 = ["a_score_ge13", "a_fvg_absent", "a_volume", "a_room", "a_ob",
             "a_vol_expansion", "a_sweep", "a_mss", "a_trend_counter"]   # 9원자 (bb_squeeze 제외)
    trades["a_fvg_absent"] = ~trades["a_fvg"].astype(bool); trades["a_trend_counter"] = ~trades["a_trend_align"].astype(bool)
    for a in TAG10:
        trades[a] = trades[a].astype(bool)
    trades["n_atoms_true"] = trades[TAG10].sum(axis=1).astype(int)
    print(f"[귀속] 매칭0 거래(음극 self-check) = {zero}")
    if zero != 0:
        raise SystemExit(f"[ABORT] 매칭0 {zero}건 — 음극매칭 오류 의심")
    # self-check 샘플: ~a_fvg 든 셋업으로 귀속된 거래는 a_fvg_absent=True 여야
    sample = trades[trades["matched_setup"].str.contains("fvg_absent", na=False)].head(3)
    print("  [음극 self-check 샘플] matched가 fvg_absent 포함 → a_fvg_absent True 확인:")
    for _, r in sample.iterrows():
        print(f"    {r['symbol']} {r['entry_time']} matched={r['matched_setup'][:40]} a_fvg_absent={r['a_fvg_absent']}")

    os.makedirs(OUTDIR, exist_ok=True)
    trades.to_csv(os.path.join(OUTDIR, "trades.csv"), index=False)
    print(f"[저장] {OUTDIR}/trades.csv ({len(trades)}행)")

    # ── 거래지표 ──
    def _pf(p):
        p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
        return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))

    def tmetrics(d, name):
        d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
        d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
        pnl = d["net_pnl"].astype(float).values; r = d["r_multiple"].astype(float).values
        n = len(d); k = int(n * 0.7); yr = d["exit_time"].dt.year
        row = {"name": name, "n": n, "win%": round(float((pnl > 0).mean() * 100), 2),
               "PF": round(_pf(pnl), 4), "IS": round(_pf(pnl[:k]), 4), "OOS": round(_pf(pnl[k:]), 4),
               "expR": round(float(r.mean()), 4),
               "r6_PF": round(_pf(d[~d["symbol"].isin(REST6)]["net_pnl"].astype(float).values), 4)}
        allge1 = True; any_y = False
        for y in YEARS:
            s = d[yr == y]
            if len(s):
                pfy = _pf(s["net_pnl"].astype(float).values); row[f"pf{y}"] = round(pfy, 3); any_y = True
                if pfy < 1: allge1 = False
        row["allge1"] = allge1 and any_y
        return row

    rl = trades[~trades["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    m_all = tmetrics(trades, "전체")
    m_ct = tmetrics(trades[trades["a_trend_counter"]], "역추세")
    print("\n=== 거래지표 ===")
    for m in (m_all, m_ct):
        ypf = {y: m.get(f"pf{y}") for y in YEARS if f"pf{y}" in m}
        print(f"  [{m['name']}] n={m['n']} PF={m['PF']} IS={m['IS']} OOS={m['OOS']} 승률={m['win%']}% "
              f"expR={m['expR']} 나머지6={m['r6_PF']} 매년삶={m['allge1']} | 연도={ypf}")

    # 사후대비
    dn = abs(m_all["n"] - REF["n"]) / REF["n"] * 100; dpf = abs(m_all["PF"] - REF["PF"]) / REF["PF"] * 100
    print(f"\n=== 사후대비 === 거래 {m_all['n']}/{REF['n']}(Δ{dn:.1f}%) PF {m_all['PF']}/{REF['PF']}(Δ{dpf:.1f}%) "
          f"OOS {m_all['OOS']}/{REF['OOS']} → {'⚠️괴리' if dn > 15 else 'OK'}")

    # 셋업별표 (총R<0 음수재발생 플래그)
    bd = []
    for key, g in rl.groupby("matched_setup"):
        g = g.sort_values("exit_time"); pnl = g["net_pnl"].astype(float).values; r = g["r_multiple"].astype(float).values
        n = len(g); k = int(n * 0.7)
        bd.append({"matched_setup": key, "n": n, "win%": round(float((pnl > 0).mean() * 100), 1),
                   "expR": round(float(r.mean()), 4), "PF": round(_pf(pnl), 3),
                   "IS": round(_pf(pnl[:k]), 3) if k else float("nan"),
                   "OOS": round(_pf(pnl[k:]), 3) if n - k else float("nan"), "totR": round(float(r.sum()), 2)})
    bdf = pd.DataFrame(bd).sort_values("n", ascending=False)
    bdf.to_csv(os.path.join(OUTDIR, "setup_breakdown.csv"), index=False)
    neg = bdf[bdf["totR"] < 0]
    print(f"\n=== 셋업별 음수(totR<0) 재발생: {len(neg)}개 / {len(bdf)} ===")
    if len(neg):
        print(neg.head(8).to_string(index=False))

    # ── KRW 자본시뮬 (4L 이식) ──
    cap = capital_sim_krw(rl.copy(), np, pd)
    print("\n=== KRW 자본시뮬 (시드500만+월250만x5, RISK1%, 3배캡, fee0.055%) ===")
    print(f"  최종자본 {cap['final']:,.0f}원 | Return {cap['ret']:.1f}% | CAGR {cap['cagr']:.1f}% | "
          f"MDD {cap['mdd']:.2f}% | peak {cap['peak']:,.0f}원")
    print(f"  거래 {cap['n']} | 승률 {cap['win']:.1f}% | PF {cap['pf']:.3f} | avgR {cap['avgr']:.4f} | 룩어헤드 {cap['la']}")
    print("  월별 자본추이(말잔/입금/손익/누적Ret%):")
    print(cap["monthly"].to_string(index=False))
    print(f"  연도별: {cap['yearly']}")
    print(f"  ★퇴사시점(월손익 1000만 3개월연속): {cap['retire']}")
    cap["equity"].to_csv(os.path.join(OUTDIR, "equity_curve.csv"), index=False)
    cap["monthly"].to_csv(os.path.join(OUTDIR, "monthly.csv"), index=False)
    print(f"\n[저장완료] {OUTDIR}/ (trades.csv, setup_breakdown.csv, equity_curve.csv, monthly.csv)")


def calc_pos_krw(balance, entry, sl):
    risk = balance * RISK_PCT; rpu = abs(entry - sl)
    if rpu <= 0: return None
    rpu_krw = rpu * KRW_USDT; qty = risk / rpu_krw
    notional = qty * entry * KRW_USDT; maxn = balance * MAXNOT
    if notional > maxn:
        qty = maxn / (entry * KRW_USDT); notional = qty * entry * KRW_USDT
    if notional * FEE * 2 > risk * 0.35:
        return None
    return qty, qty * rpu_krw  # actual risk (capped 반영)


def _equity_curve(g, rvals, np, pd, ret_risk=False):
    import pandas as _pd
    ET = list(g["entry_time"]); XT = list(g["exit_time"]); SYM = list(g["symbol"])
    ENT = list(g["entry"].astype(float)); SL = list(g["sl"].astype(float))
    start = _pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; mt = start
    for _ in range(NDEP):
        mt = mt + _pd.offsets.MonthBegin(1); deps.append((mt, MONTHLY_KRW))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 2, i)); ev.append((XT[i], 1, i))     # 진입=2, 청산=1
    ev += [(dt, 0, -amt) for dt, amt in deps]                  # 입금=0
    ev.sort(key=lambda x: (x[0], x[1]))                        # 입금<청산<진입
    bal = float(INIT_KRW); openp = {}; opensym = set(); risk_at = {}; eqpts = []; pnl_by = {}
    for ts, pri, p in ev:
        if pri == 0:
            bal += (-p)
        elif pri == 1:
            if p in openp:
                rk = openp.pop(p); bal += rvals[p] * rk; opensym.discard(SYM[p])
                pnl_by[p] = rvals[p] * rk
        else:
            if SYM[p] in opensym:
                continue
            r = calc_pos_krw(bal, ENT[p], SL[p])
            if r is None:
                continue
            openp[p] = r[1]; opensym.add(SYM[p]); risk_at[p] = r[1]
        eqpts.append((ts, bal))
    for p, rk in list(openp.items()):
        bal += rvals[p] * rk; pnl_by[p] = rvals[p] * rk
    if ret_risk:
        return risk_at
    return bal, eqpts, pnl_by


def capital_sim_krw(rl, np, pd):
    g = rl.copy()
    g["entry_time"] = pd.to_datetime(g["entry_time"], utc=True); g["exit_time"] = pd.to_datetime(g["exit_time"], utc=True)
    g = g.sort_values("entry_time").reset_index(drop=True)
    rv = g["r_multiple"].astype(float).values
    # 룩어헤드 테스트
    rng = np.random.default_rng(7); base = _equity_curve(g, rv, np, pd, ret_risk=True)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (g["exit_time"] >= T).values; past = g.index[g["entry_time"] <= T]
        for _ in range(50):
            r2 = rv.copy()
            if fut.any(): r2[fut] = rng.uniform(-5, 5, int(fut.sum()))
            rk2 = _equity_curve(g, r2, np, pd, ret_risk=True)
            for i in past:
                checked += 1
                if abs(base.get(i, 0.0) - rk2.get(i, 0.0)) > 1e-6: mism += 1
    la = f"{mism}/{checked} {'✅' if mism == 0 else '❌누수'}"
    if mism != 0:
        raise SystemExit(f"[ABORT] 자본 룩어헤드 누수 {mism}/{checked}")

    final, eqpts, pnl_by = _equity_curve(g, rv, np, pd)
    eq = pd.DataFrame(eqpts, columns=["time", "total_assets"]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    eq["cummax"] = eq["total_assets"].cummax(); eq["dd_pct"] = (eq["total_assets"] - eq["cummax"]) / eq["cummax"] * 100
    mdd = float(eq["dd_pct"].min()); peak = float(eq["total_assets"].max())
    total_in = INIT_KRW + MONTHLY_KRW * NDEP
    ret = (final - total_in) / total_in * 100
    yrs = max((g["exit_time"].max() - g["entry_time"].min()).days / 365.25, 1e-9)
    cagr = ((final / total_in) ** (1 / yrs) - 1) * 100 if final > 0 else float("nan")
    pnl = g["net_pnl"].astype(float).values
    # 월별
    g["pnl_krw"] = [pnl_by.get(i, 0.0) for i in range(len(g))]
    g["emonth"] = g["exit_time"].dt.strftime("%Y-%m")
    dep_months = {(pd.Timestamp(min(g["entry_time"])).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): MONTHLY_KRW for k in range(NDEP)}
    rows = []; run = INIT_KRW; total_in_run = INIT_KRW
    for mo in sorted(g["emonth"].unique()):
        dep = dep_months.get(mo, 0); mpnl = float(g[g["emonth"] == mo]["pnl_krw"].sum())
        run += dep + mpnl; total_in_run += dep
        rows.append({"month": mo, "deposit": dep, "pnl": round(mpnl), "balance": round(run),
                     "cumRet%": round((run - total_in_run) / total_in_run * 100, 1)})
    monthly = pd.DataFrame(rows)
    # 퇴사: 월손익>=1000만 3개월 연속
    retire = "미도달"
    mp_series = monthly.set_index("month")["pnl"]
    streak = 0
    for mo, v in mp_series.items():
        streak = streak + 1 if v >= 10_000_000 else 0
        if streak >= 3:
            retire = f"{mo} (직전3개월 연속 ≥1000만, 그시점 잔고 {int(monthly[monthly['month']==mo]['balance'].iloc[0]):,}원)"; break
    if retire == "미도달":
        retire = f"미도달 (최종자본 {final:,.0f}원)"
    # 연도별
    g["eyear"] = g["exit_time"].dt.year
    yearly = {}
    for y in sorted(g["eyear"].unique()):
        sub = eq[eq["time"].dt.year == y]
        yearly[int(y)] = {"pnl": round(float(g[g['eyear'] == y]["pnl_krw"].sum())),
                          "mdd%": round(float(sub["dd_pct"].min()), 2) if len(sub) else 0.0}
    return {"final": final, "ret": ret, "cagr": cagr, "mdd": mdd, "peak": peak, "n": len(g),
            "win": float((pnl > 0).mean() * 100), "pf": float(np.sum(pnl[pnl > 0]) / -np.sum(pnl[pnl < 0])) if (pnl < 0).any() else float("inf"),
            "avgr": float(rv.mean()), "la": la, "monthly": monthly, "yearly": yearly, "retire": retire, "equity": eq}


if __name__ == "__main__":
    mp.freeze_support()
    main()
