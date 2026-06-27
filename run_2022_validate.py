#!/usr/bin/env python3
# 1단계: 2022 확장 검증 — a3(63)·v4(42) 3중게이트를 2022-2026 데이터로. 2022는 순수 OOS.
#   전체기간 + 2022구간 분리 지표 + 자본시뮬(2022 시드). 병렬, BTC룩어헤드 strict<, 자본룩어헤드.
import os, json, time, pickle
import multiprocessing as mp

CACHE = "prepared_cache_2022.pkl"
INIT_KRW = 5_000_000; MONTHLY_KRW = 2_500_000; NDEP = 5
KRW_USDT = 1540.0; RISK_PCT = 0.01; FEE = 0.00055; MAXNOT = 3.0
RULESETS = [("a3(63)", "setups_btc_triple_a3.json"), ("v4(42)", "setups_btc_triple_a3v4.json")]


def _setup():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
        os.environ.pop(_k, None)
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85; F.BROAD_FVG_SIZE_ATR = 0.0


def _btc_arrays():
    import pandas as pd, numpy as np
    b = pd.read_parquet("data_cache/BTCUSDT_4h.parquet")
    b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True); b = b.sort_values("timestamp").reset_index(drop=True)
    ma10 = b["close"].rolling(10).mean(); ma30 = b["close"].rolling(30).mean()
    return b["timestamp"].values, ((ma10 - ma30) / ma30 * 100.0).values


def _zone(bts, bdist, ts):
    import numpy as np
    p = int(np.searchsorted(bts, ts, side="left")) - 1
    if p < 0:
        return None
    bd = bdist[p]
    if np.isnan(bd):
        return None
    return "down" if bd < -1 else ("range" if bd <= 1 else "up")


_PREP = None; _ATOMSETS = None; _BTS = None; _BDIST = None; _ORIG = None
def _wrap(*a, **kw):
    tags = _ORIG(*a, **kw)
    try:
        df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
        ts = df["timestamp"].values[min(ei + 1, len(df) - 1)]
        z = _zone(_BTS, _BDIST, ts)
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
    matched = [(i, ru["key"], len(ru["atoms"])) for i, ru in enumerate(rules)
               if ru["btc_zone"] == zone and ru["side"] == side and all(_amatch(getter, at) for at in ru["atoms"])]
    if not matched:
        return "", 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]
    return best[1], len(matched)


def calc_pos_krw(balance, entry, sl):
    risk = balance * RISK_PCT; rpu = abs(entry - sl)
    if rpu <= 0:
        return None
    rpu_krw = rpu * KRW_USDT; qty = risk / rpu_krw; notional = qty * entry * KRW_USDT; maxn = balance * MAXNOT
    if notional > maxn:
        qty = maxn / (entry * KRW_USDT); notional = qty * entry * KRW_USDT
    if notional * FEE * 2 > risk * 0.35:
        return None
    return qty, qty * rpu_krw


def _equity(g, rvals, np, pd, ret_risk=False):
    ET = list(g["entry_time"]); XT = list(g["exit_time"]); SYM = list(g["symbol"]); ENT = list(g["entry"].astype(float)); SL = list(g["sl"].astype(float))
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1); deps = []; mt = start
    for _ in range(NDEP):
        mt = mt + pd.offsets.MonthBegin(1); deps.append((mt, MONTHLY_KRW))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 2, i)); ev.append((XT[i], 1, i))
    ev += [(dt, 0, -amt) for dt, amt in deps]; ev.sort(key=lambda x: (x[0], x[1]))
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


def _pf(p, np):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))


def run_one(label, rules_json, np, pd, SYMBOLS, REST6, prepared, bts, bdist, ncore):
    rules = json.load(open(rules_json, encoding="utf-8"))
    with mp.Pool(ncore, initializer=_init_worker, initargs=(CACHE, rules_json)) as pool:
        res = pool.map(_gen_one, SYMBOLS); res2 = pool.map(_gen_one, SYMBOLS)
    n1 = sum(len(c) for _, c in res); n2 = sum(len(c) for _, c in res2)
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    assert n1 == n2, "비멱등"
    cand = {s: {"candidates": c, "df_h4": prepared[s]["df_struct"], "df_h1": prepared[s]["df_h1"], "symbol": s} for s, c in res}
    tr = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)["trades"].copy()
    et = pd.to_datetime(tr["entry_time"], utc=True)
    pos = np.searchsorted(bts, et.values, side="left") - 1; pos = np.clip(pos, 0, len(bts) - 1)
    fut = int((bts[pos] >= et.values).sum())
    assert fut == 0, "BTC 룩어헤드"
    tr["btc_zone"] = ["down" if d < -1 else ("range" if d <= 1 else "up") for d in bdist[pos]]
    for a in ["a_fvg", "a_trend_align"]:
        pass
    tr["a_trend_counter"] = ~tr["a_trend_align"].astype(bool)   # 출력용
    lab = tr.apply(lambda r: attribute_rule(lambda a: bool(r.get(a, False)), r["btc_zone"], r["side"], rules), axis=1)
    tr["n_rules_matched"] = [x[1] for x in lab]
    zero = int((tr["n_rules_matched"] == 0).sum())

    rl = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    rl["exit_time"] = pd.to_datetime(rl["exit_time"], utc=True); rl["entry_time"] = pd.to_datetime(rl["entry_time"], utc=True)
    rl = rl.sort_values("exit_time").reset_index(drop=True)

    def _seg(d, name):
        pnl = d["net_pnl"].astype(float).values; r = d["r_multiple"].astype(float).values; n = len(d); k = int(n * 0.7)
        yr = d["exit_time"].dt.year
        ypf = {int(y): round(_pf(d[yr == y]["net_pnl"].astype(float).values, np), 3) for y in sorted(set(yr)) }
        # R단위 MDD
        cum = np.cumsum(r); peak = np.maximum.accumulate(cum) if len(cum) else cum; rmdd = float((cum - peak).min()) if len(cum) else 0.0
        return {"name": name, "n": n, "PF": round(_pf(pnl, np), 3), "OOS": round(_pf(pnl[k:], np), 3) if n - k else float("nan"),
                "expR": round(float(r.mean()), 4), "MDD_R": round(rmdd, 1),
                "r6_PF": round(_pf(d[~d["symbol"].isin(REST6)]["net_pnl"].astype(float).values, np), 3),
                "allge1": all(v >= 1 for v in ypf.values()), "ypf": ypf}

    full = _seg(rl, "전체2022-2026")
    s22 = _seg(rl[rl["exit_time"].dt.year == 2022], "2022구간")
    # 자본 (전체기간, 2022 시드)
    g = rl.sort_values("entry_time").reset_index(drop=True); rv = g["r_multiple"].astype(float).values
    rng = np.random.default_rng(7); base = _equity(g, rv, np, pd, ret_risk=True)
    splits = pd.to_datetime(["2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2025-01-01", "2026-01-01"], utc=True)
    mism = ch = 0
    for T in splits:
        ftr = (g["exit_time"] >= T).values; past = g.index[g["entry_time"] <= T]
        for _ in range(30):
            r2 = rv.copy()
            if ftr.any():
                r2[ftr] = rng.uniform(-5, 5, int(ftr.sum()))
            rk2 = _equity(g, r2, np, pd, ret_risk=True)
            for i in past:
                ch += 1
                if abs(base.get(i, 0.0) - rk2.get(i, 0.0)) > 1e-6:
                    mism += 1
    assert mism == 0, f"자본룩어헤드 {mism}/{ch}"
    final, eqpts, pnl_by = _equity(g, rv, np, pd)
    eq = pd.DataFrame(eqpts, columns=["time", "ta"]).drop_duplicates("time").sort_values("time")
    eq["cm"] = eq["ta"].cummax(); eq["dd"] = (eq["ta"] - eq["cm"]) / eq["cm"] * 100
    mdd = float(eq["dd"].min()); total_in = INIT_KRW + MONTHLY_KRW * NDEP
    yrs = max((g["exit_time"].max() - g["entry_time"].min()).days / 365.25, 1e-9)
    cagr = ((final / total_in) ** (1 / yrs) - 1) * 100 if final > 0 else float("nan")
    g["py"] = [pnl_by.get(i, 0.0) for i in range(len(g))]; g["ey"] = g["exit_time"].dt.year
    yearly = {int(y): {"pnl": round(float(g[g["ey"] == y]["py"].sum())), "mdd%": round(float(eq[eq["time"].dt.year == y]["dd"].min()), 2) if len(eq[eq["time"].dt.year == y]) else 0} for y in sorted(set(g["ey"]))}
    cap = {"final": final, "ret": (final - total_in) / total_in * 100, "cagr": cagr, "mdd": mdd, "yearly": yearly, "n": len(g)}
    return {"label": label, "zero": zero, "la_cap": f"{mism}/{ch}", "btc_future": fut, "full": full, "s22": s22, "cap": cap}


def main():
    import numpy as np, pandas as pd
    from smc_stage4d.config import SCENARIO_MULTI
    SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys()); REST6 = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
    ncore = max(1, min(mp.cpu_count() - 1, len(SYMBOLS))); _setup()
    if not os.path.exists(CACHE):
        print(f"[ERR] {CACHE} 없음 — build_prepared_2022 먼저"); return
    with open(CACHE, "rb") as f:
        prepared = pickle.load(f)
    span = prepared[SYMBOLS[0]]["df_struct"]["timestamp"]
    print(f"[1단계 2022확장] 데이터 {span.min()} ~ {span.max()} (H4 {len(span)}봉) | core={ncore}")
    bts, bdist = _btc_arrays()
    outs = []
    for label, rj in RULESETS:
        t1 = time.time(); o = run_one(label, rj, np, pd, SYMBOLS, REST6, prepared, bts, bdist, ncore)
        outs.append(o)
        print(f"\n##### {label} #####  (멱등✅ BTC미래참조 {o['btc_future']} 자본룩어헤드 {o['la_cap']} 규칙매칭0 {o['zero']})  [{time.time()-t1:.0f}s]")
        for seg in (o["full"], o["s22"]):
            print(f"  [{seg['name']}] n={seg['n']} PF={seg['PF']} OOS={seg['OOS']} expR={seg['expR']} "
                  f"MDD_R={seg['MDD_R']} r6={seg['r6_PF']} 매년삶={seg['allge1']} 연도={seg['ypf']}")
        c = o["cap"]; print(f"  [자본] 최종 {c['final']:,.0f}원 Return {c['ret']:.1f}% CAGR {c['cagr']:.1f}% MDD {c['mdd']:.2f}% | 연도별 {c['yearly']}")

    print("\n" + "=" * 80); print("=== a3 vs v4 — 2022 확장 핵심비교 ===")
    a, v = outs[0], outs[1]
    print(f"{'':16}{'a3(63)':>16}{'v4(42)':>16}")
    print(f"{'전체PF':16}{a['full']['PF']:>16}{v['full']['PF']:>16}")
    print(f"{'전체OOS':16}{a['full']['OOS']:>16}{v['full']['OOS']:>16}")
    print(f"{'전체매년삶':16}{str(a['full']['allge1']):>16}{str(v['full']['allge1']):>16}")
    print(f"{'2022 PF':16}{a['s22']['PF']:>16}{v['s22']['PF']:>16}")
    print(f"{'2022 n':16}{a['s22']['n']:>16}{v['s22']['n']:>16}")
    print(f"{'2022 MDD_R':16}{a['s22']['MDD_R']:>16}{v['s22']['MDD_R']:>16}")
    print(f"{'최종자본':16}{a['cap']['final']:>16,.0f}{v['cap']['final']:>16,.0f}")
    print(f"{'전체MDD%':16}{a['cap']['mdd']:>16.2f}{v['cap']['mdd']:>16.2f}")
    print(f"{'CAGR%':16}{a['cap']['cagr']:>16.1f}{v['cap']['cagr']:>16.1f}")


if __name__ == "__main__":
    mp.freeze_support(); main()
