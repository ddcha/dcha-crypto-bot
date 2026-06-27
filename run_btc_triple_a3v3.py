#!/usr/bin/env python3
# setups_btc_triple_a3v3.json(114규칙) 3중게이트(atoms × btc_zone × side) 진짜게이트 + KRW 자본시뮬.
#   btc_zone/side 를 게이트에 토큰(__zone_/__side_)으로 주입 → _combo_union_match(음극패치)가 규칙 매칭.
#   BTC zone 룩어헤드-free(strict<). 병렬(prepared 캐시). room=swing60, bb 없음.
import os, json, time, pickle
import multiprocessing as mp

CACHE = "prepared_cache.pkl"; RULES_JSON = "setups_btc_triple_a3v3.json"; OUTDIR = "btc_triple_a3v3_result"
INIT_KRW = 5_000_000; MONTHLY_KRW = 2_500_000; NDEP = 5
KRW_USDT = 1540.0; RISK_PCT = 0.01; FEE = 0.00055; MAXNOT = 3.0
REF = {"n": 661, "PF": 1.60, "OOS": 1.24}


def _setup():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
        os.environ.pop(_k, None)
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85; F.BROAD_FVG_SIZE_ATR = 0.0
    return F


def _btc_arrays():
    import pandas as pd, numpy as np
    b = pd.read_parquet("data_cache/BTCUSDT_4h.parquet")
    b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True); b = b.sort_values("timestamp").reset_index(drop=True)
    ma10 = b["close"].rolling(10).mean(); ma30 = b["close"].rolling(30).mean()
    return b["timestamp"].values, ((ma10 - ma30) / ma30 * 100.0).values


def btc_zone_of(bts, bdist, ts):
    import numpy as np
    p = int(np.searchsorted(bts, ts, side="left")) - 1   # strict < (같은시각 제외)
    if p < 0:
        return None, float("nan")
    bd = bdist[p]
    if np.isnan(bd):
        return None, float("nan")
    z = "down" if bd < -1 else ("range" if bd <= 1 else "up")
    return z, float(bd)


_PREP = None; _ATOMSETS = None; _BTS = None; _BDIST = None; _ORIG = None
def _wrap(*a, **kw):
    tags = _ORIG(*a, **kw)
    try:
        df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
        bi = min(ei + 1, len(df) - 1)                 # 실제 entry봉 = i (= 정직신호봉 ei + 1)
        ts = df["timestamp"].values[bi]
        z, _ = btc_zone_of(_BTS, _BDIST, ts)
        if z is not None:
            tags["__zone_" + z] = True
        tags["__side_" + side] = True
    except Exception:
        pass
    return tags


def _init_worker(cache_path, json_path):
    _setup()
    global _PREP, _ATOMSETS, _BTS, _BDIST, _ORIG
    rules = json.load(open(json_path, encoding="utf-8"))
    _ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in rules]
    _BTS, _BDIST = _btc_arrays()
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    _ORIG = Fm.compute_trade_tags
    Fm.compute_trade_tags = _wrap; sim.compute_trade_tags = _wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    with open(cache_path, "rb") as f:
        _PREP = pickle.load(f)


def _gen_one(sym):
    import smc_stage4d.simulation as sim
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    return sym, sim.generate_candidates_from_prepared(_PREP[sym])["candidates"]


def _amatch(getter, a):
    return (not bool(getter(a[1:]))) if a.startswith("~") else bool(getter(a))


def attribute_rule(getter, zone, side, rules):
    matched = []
    for idx, ru in enumerate(rules):
        if ru["btc_zone"] != zone or ru["side"] != side:
            continue
        if all(_amatch(getter, at) for at in ru["atoms"]):
            matched.append((idx, ru["key"], len(ru["atoms"])))
    if not matched:
        return "", 0, 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]
    return best[1], len(matched), best[2]   # key, n_rules, rule_natoms


# ── KRW 자본시뮬 (4L 이식) ──
def calc_pos_krw(balance, entry, sl):
    risk = balance * RISK_PCT; rpu = abs(entry - sl)
    if rpu <= 0:
        return None
    rpu_krw = rpu * KRW_USDT; qty = risk / rpu_krw
    notional = qty * entry * KRW_USDT; maxn = balance * MAXNOT
    if notional > maxn:
        qty = maxn / (entry * KRW_USDT); notional = qty * entry * KRW_USDT
    if notional * FEE * 2 > risk * 0.35:
        return None
    return qty, qty * rpu_krw


def _equity_curve(g, rvals, np, pd, ret_risk=False):
    ET = list(g["entry_time"]); XT = list(g["exit_time"]); SYM = list(g["symbol"])
    ENT = list(g["entry"].astype(float)); SL = list(g["sl"].astype(float))
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; mt = start
    for _ in range(NDEP):
        mt = mt + pd.offsets.MonthBegin(1); deps.append((mt, MONTHLY_KRW))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 2, i)); ev.append((XT[i], 1, i))
    ev += [(dt, 0, -amt) for dt, amt in deps]
    ev.sort(key=lambda x: (x[0], x[1]))      # 입금<청산<진입
    bal = float(INIT_KRW); openp = {}; opensym = set(); risk_at = {}; eqpts = []; pnl_by = {}
    for ts, pri, p in ev:
        if pri == 0:
            bal += (-p)
        elif pri == 1:
            if p in openp:
                rk = openp.pop(p); bal += rvals[p] * rk; opensym.discard(SYM[p]); pnl_by[p] = rvals[p] * rk
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
    return risk_at if ret_risk else (bal, eqpts, pnl_by)


def capital_sim_krw(rl, np, pd):
    g = rl.copy()
    g["entry_time"] = pd.to_datetime(g["entry_time"], utc=True); g["exit_time"] = pd.to_datetime(g["exit_time"], utc=True)
    g = g.sort_values("entry_time").reset_index(drop=True); rv = g["r_multiple"].astype(float).values
    rng = np.random.default_rng(7); base = _equity_curve(g, rv, np, pd, ret_risk=True)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (g["exit_time"] >= T).values; past = g.index[g["entry_time"] <= T]
        for _ in range(50):
            r2 = rv.copy()
            if fut.any():
                r2[fut] = rng.uniform(-5, 5, int(fut.sum()))
            rk2 = _equity_curve(g, r2, np, pd, ret_risk=True)
            for i in past:
                checked += 1
                if abs(base.get(i, 0.0) - rk2.get(i, 0.0)) > 1e-6:
                    mism += 1
    if mism != 0:
        raise SystemExit(f"[ABORT] 자본 룩어헤드 누수 {mism}/{checked}")
    final, eqpts, pnl_by = _equity_curve(g, rv, np, pd)
    eq = pd.DataFrame(eqpts, columns=["time", "total_assets"]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    eq["cummax"] = eq["total_assets"].cummax(); eq["dd_pct"] = (eq["total_assets"] - eq["cummax"]) / eq["cummax"] * 100
    mdd = float(eq["dd_pct"].min()); peak = float(eq["total_assets"].max())
    total_in = INIT_KRW + MONTHLY_KRW * NDEP; ret = (final - total_in) / total_in * 100
    yrs = max((g["exit_time"].max() - g["entry_time"].min()).days / 365.25, 1e-9)
    cagr = ((final / total_in) ** (1 / yrs) - 1) * 100 if final > 0 else float("nan")
    pnl = g["net_pnl"].astype(float).values
    g["pnl_krw"] = [pnl_by.get(i, 0.0) for i in range(len(g))]; g["emonth"] = g["exit_time"].dt.strftime("%Y-%m")
    dep_months = {(pd.Timestamp(min(g["entry_time"])).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): MONTHLY_KRW for k in range(NDEP)}
    rows = []; run = INIT_KRW; tin = INIT_KRW
    for mo in sorted(g["emonth"].unique()):
        dep = dep_months.get(mo, 0); mpnl = float(g[g["emonth"] == mo]["pnl_krw"].sum()); run += dep + mpnl; tin += dep
        rows.append({"month": mo, "deposit": dep, "pnl": round(mpnl), "balance": round(run), "cumRet%": round((run - tin) / tin * 100, 1)})
    monthly = pd.DataFrame(rows)
    retire = "미도달"; streak = 0
    for _, rr in monthly.iterrows():
        streak = streak + 1 if rr["pnl"] >= 10_000_000 else 0
        if streak >= 3:
            retire = f"{rr['month']} (직전3개월 연속 ≥1000만, 잔고 {int(rr['balance']):,}원)"; break
    if retire == "미도달":
        retire = f"미도달 (최종 {final:,.0f}원)"
    g["eyear"] = g["exit_time"].dt.year; yearly = {}
    for y in sorted(g["eyear"].unique()):
        sub = eq[eq["time"].dt.year == y]
        yearly[int(y)] = {"pnl": round(float(g[g['eyear'] == y]["pnl_krw"].sum())), "mdd%": round(float(sub["dd_pct"].min()), 2) if len(sub) else 0.0}
    return {"final": final, "ret": ret, "cagr": cagr, "mdd": mdd, "peak": peak, "n": len(g),
            "win": float((pnl > 0).mean() * 100), "pf": float(np.sum(pnl[pnl > 0]) / -np.sum(pnl[pnl < 0])) if (pnl < 0).any() else float("inf"),
            "avgr": float(rv.mean()), "monthly": monthly, "yearly": yearly, "retire": retire, "equity": eq}


def main():
    import numpy as np, pandas as pd
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
    REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}; YEARS = [2022, 2023, 2024, 2025, 2026]
    rules = json.load(open(RULES_JSON, encoding="utf-8"))
    ncore = max(1, min(mp.cpu_count() - 1, len(SYMBOLS))); _setup()
    if not os.path.exists(CACHE):
        print("[ERR] prepared_cache.pkl 없음"); return
    with open(CACHE, "rb") as f:
        prepared = pickle.load(f)
    bts, bdist = _btc_arrays()
    print(f"[INFO] 114규칙 3중게이트(atoms×btc_zone×side) | core={ncore} | room=swing60")

    print("\n[STEP1] 3중게이트 candidate 병렬 + simulate")
    t1 = time.time()
    with mp.Pool(ncore, initializer=_init_worker, initargs=(CACHE, RULES_JSON)) as pool:
        res = pool.map(_gen_one, SYMBOLS); res2 = pool.map(_gen_one, SYMBOLS)
    n1 = sum(len(c) for _, c in res); n2 = sum(len(c) for _, c in res2)
    print(f"  [멱등성] 1패스 {n1} / 2패스 {n2} {'✅' if n1 == n2 else '❌'}"); assert n1 == n2
    cand = {s: {"candidates": c, "df_h4": prepared[s]["df_struct"], "df_h1": prepared[s]["df_h1"], "symbol": s} for s, c in res}
    trades = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)["trades"].copy()
    print(f"[STEP1] 완료 {time.time()-t1:.0f}s | 진입 거래 {len(trades)}")

    # BTC 태깅(post-hoc, strict<) + 룩어헤드 검증
    et = pd.to_datetime(trades["entry_time"], utc=True)
    pos = np.searchsorted(bts, et.values, side="left") - 1; pos = np.clip(pos, 0, len(bts) - 1)
    trades["btc_match_ts"] = bts[pos]; trades["btc_dist"] = bdist[pos]
    trades["btc_zone"] = ["down" if (d < -1) else ("range" if d <= 1 else "up") for d in bdist[pos]]
    future = int((trades["btc_match_ts"].values >= et.values).sum())
    print(f"[BTC룩어헤드] 미래참조 {future}건 {'✅' if future == 0 else '❌'}");
    if future != 0: raise SystemExit("BTC 룩어헤드 누수")

    # 9원자 태깅 + 규칙 귀속(3중)
    TAG9 = ["a_score_ge13", "a_fvg_absent", "a_volume", "a_room", "a_ob", "a_vol_expansion", "a_sweep", "a_mss", "a_trend_counter"]
    trades["a_fvg_absent"] = ~trades["a_fvg"].astype(bool); trades["a_trend_counter"] = ~trades["a_trend_align"].astype(bool)
    for a in TAG9:
        trades[a] = trades[a].astype(bool)
    trades["n_atoms_true"] = trades[TAG9].sum(axis=1).astype(int)
    lab = trades.apply(lambda r: attribute_rule(lambda a: r.get(a, False), r["btc_zone"], r["side"], rules), axis=1)
    trades["matched_rule"] = [x[0] for x in lab]; trades["n_rules_matched"] = [x[1] for x in lab]
    trades["rule_natoms"] = [x[2] for x in lab]
    zero = int((trades["n_rules_matched"] == 0).sum())
    print(f"[3중 self-check] 규칙매칭0 거래 = {zero} {'✅' if zero == 0 else '❌게이트/귀속불일치'}")
    if zero != 0:
        print(trades[trades["n_rules_matched"] == 0][["symbol", "entry_time", "btc_zone", "side"]].head().to_string(index=False))
        raise SystemExit("규칙매칭0 — 3중 불일치")
    print("  [샘플3] atoms+btc_zone+side 3중 일치 확인:")
    for _, r in trades.head(3).iterrows():
        print(f"    {r['symbol']} {r['entry_time']} zone={r['btc_zone']} side={r['side']} → rule={r['matched_rule'][:55]}")

    os.makedirs(OUTDIR, exist_ok=True); trades.to_csv(os.path.join(OUTDIR, "trades.csv"), index=False)
    print(f"[저장] {OUTDIR}/trades.csv ({len(trades)}행, +matched_rule +n_rules_matched +9원자 +btc_dist +btc_zone +side)")

    def _pf(p):
        p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
        return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))

    rl = trades[~trades["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d = rl.copy(); d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True); d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values; r = d["r_multiple"].astype(float).values; n = len(d); k = int(n * 0.7); yr = d["exit_time"].dt.year
    ypf = {int(y): round(_pf(d[yr == y]["net_pnl"].astype(float).values), 3) for y in YEARS if (yr == y).any()}
    allge1 = all(v >= 1 for v in ypf.values())
    print(f"\n=== 거래지표(전체) === n={n} PF={round(_pf(pnl),4)} IS={round(_pf(pnl[:k]),4)} OOS={round(_pf(pnl[k:]),4)} "
          f"승률={round(float((pnl>0).mean()*100),2)}% expR={round(float(r.mean()),4)} "
          f"r6={round(_pf(d[~d['symbol'].isin(REST6)]['net_pnl'].astype(float).values),4)} 매년삶={allge1} 연도={ypf}")
    dn = abs(n - REF["n"]) / REF["n"] * 100; oos = _pf(pnl[k:])
    print(f"=== 사후대비 === 거래 {n}/{REF['n']}(Δ{dn:.1f}%) PF {round(_pf(pnl),3)}/{REF['PF']} OOS {round(oos,3)}/{REF['OOS']} "
          f"→ {'⚠️강제대체플래그' if dn > 15 else 'OK(BTC는 진입가 안바꿈→대체 거의없어야 정상)'}")

    # 규칙별표
    bd = []
    for key, g in d.groupby("matched_rule"):
        g = g.sort_values("exit_time"); p2 = g["net_pnl"].astype(float).values; r2 = g["r_multiple"].astype(float).values; m = len(g); kk = int(m * 0.7)
        bd.append({"matched_rule": key, "n": m, "PF": round(_pf(p2), 3), "OOS": round(_pf(p2[kk:]), 3) if m - kk else float("nan"), "totR": round(float(r2.sum()), 2)})
    bdf = pd.DataFrame(bd).sort_values("n", ascending=False); bdf.to_csv(os.path.join(OUTDIR, "rule_breakdown.csv"), index=False)
    neg = bdf[bdf["totR"] < 0]
    print(f"\n=== 규칙별 음수(totR<0): {len(neg)}개 / {len(bdf)} (상위8 n) ===")
    print(bdf.head(8).to_string(index=False))

    # 규칙 원자수별 PF (단순규칙이 또 흡수하나)
    print("\n=== 규칙 원자수(rule_natoms)별 — 거래흡수/성과 ===")
    print(f"{'natoms':>7}{'n':>6}{'거래비중%':>9}{'PF':>8}{'OOS':>8}{'totR':>9}")
    for na in sorted(d["rule_natoms"].unique()):
        gg = d[d["rule_natoms"] == na].sort_values("exit_time")
        p2 = gg["net_pnl"].astype(float).values; r2 = gg["r_multiple"].astype(float).values; m = len(gg); kk = int(m * 0.7)
        print(f"{int(na):>7}{m:>6}{m/len(d)*100:>8.1f}%{_pf(p2):>8.3f}{(_pf(p2[kk:]) if m-kk else float('nan')):>8.3f}{float(r2.sum()):>9.1f}")

    # 자본시뮬
    cap = capital_sim_krw(rl, np, pd)
    print(f"\n=== KRW 자본시뮬 === 최종 {cap['final']:,.0f}원 | Return {cap['ret']:.1f}% | CAGR {cap['cagr']:.1f}% | "
          f"MDD {cap['mdd']:.2f}% | peak {cap['peak']:,.0f} | 거래 {cap['n']} 승률 {cap['win']:.1f}% PF {cap['pf']:.3f}")
    print("  월별:"); print(cap["monthly"].to_string(index=False))
    print(f"  연도별: {cap['yearly']}"); print(f"  ★퇴사시점: {cap['retire']}")
    cap["equity"].to_csv(os.path.join(OUTDIR, "equity_curve.csv"), index=False); cap["monthly"].to_csv(os.path.join(OUTDIR, "monthly.csv"), index=False)
    print(f"\n[저장완료] {OUTDIR}/")


if __name__ == "__main__":
    mp.freeze_support(); main()
