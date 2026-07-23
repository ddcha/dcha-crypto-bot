#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6.1 백테 — 현재 라이브(v6)와 완전 동일. 자기완결(이 폴더만 옮기면 실행 가능). (버전 v6.1, fix 2026-07-24)
   v6 = 진입(42룰 + 만기36h컷 + 0%combo차단) + 청산(BT15·3: 부분익절없음·BE@1.5R·트레일 peak-1R, 풀포지션)
        + 균일 리스크(기본 2%, --risk 로 변경).
   진입 재생성: prepared_cache_2022.pkl(동봉) → 엔진 후보 재생성(원시 4h/1h부터). trades_v4.csv 는 파리티 대조용.
   청산: raw_1m(동봉) entry+4h 1m 정직체결.
   실행: python run_v6.1_backtest.py [--risk 2.0] [--regen]
     --risk R : 균일 리스크%(기본 2.0). 1.5/1.0 등.
     --regen  : 진입을 prepared 캐시로 재생성(완전체). 생략시 동봉 trades_v4.csv 사용(빠른경로).
   환경: Python 3.10+, pip install pandas numpy pyarrow
"""
import os, sys, json, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # smc_stage4d import
os.environ["STAGE4D_DLCACHE"] = os.path.join(HERE, "data", "data_cache")
import numpy as np, pandas as pd

DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "raw_1m"); RAWJ = os.path.join(DATA, "raw_1m_july")
RULES_DIR = os.path.join(HERE, "rules")
SYM = ["ADAUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOGEUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT"]
SKIP = 240; HZ = 7500          # entry+4h, 125h horizon(탐색상한)
EXPH = 36.0                    # 만기 36h 컷 (라이브 _EXPIRY_BLOCK_HOURS)
MAXHOLD_MIN = 48 * 60          # ★max_hold 48h (=12 H4봉, 라이브 tp_plan max_hold_bars×4h). 러너는 면제.
# 자본 시뮬 (라이브 walkforward 동일)
INIT = 5_000_000; MONTHLY = 2_500_000; NDEP = 5; KRW = 1540.0; FEE = 0.00055; MAXNOT = 3.0

# ── 라이브 오버레이 ──
_RISK_TABLE = json.load(open(os.path.join(RULES_DIR, "combo_risk_table.json"), encoding="utf-8"))["combos"]
def combo_active(setup_key):
    """0%combo 차단 여부 (라이브 v6 진입프레임). applied_risk_pct>0 이어야 진입."""
    info = _RISK_TABLE.get(setup_key)
    return info is not None and float(info.get("applied_risk_pct", 0.0)) > 0

def _monthly_expiries():
    days = pd.date_range("2022-01-01", "2028-12-31", freq="D", tz="UTC"); fri = [d for d in days if d.weekday() == 4]
    last = {}
    for f in fri: last[(f.year, f.month)] = f
    return pd.DatetimeIndex(sorted(v.replace(hour=8) for v in last.values())).tz_localize(None).values
_MEXP = _monthly_expiries()
def hours_to_expiry(ts):
    et = np.datetime64(pd.Timestamp(ts).tz_convert("UTC").tz_localize(None))
    nxt = _MEXP[min(int(np.searchsorted(_MEXP, et, "left")), len(_MEXP) - 1)]
    return float((nxt - et) / np.timedelta64(1, "h"))

# ── 1m 가격 로드 (청산용) ──
def load_px():
    px = {}
    for c in SYM:
        parts = [pd.read_parquet(f"{RAW}/{c}_1m.parquet", columns=["timestamp_ms","high","low","close"])]
        jf = f"{RAWJ}/{c}_1m_jul.parquet"
        if os.path.exists(jf): parts.append(pd.read_parquet(jf, columns=["timestamp_ms","high","low","close"]))
        df = pd.concat(parts).drop_duplicates("timestamp_ms").sort_values("timestamp_ms")
        px[c] = (df["timestamp_ms"].astype("int64").values, df["high"].values.astype(float),
                 df["low"].values.astype(float), df["close"].values.astype(float))
    return px

# ── v6 청산 (BT15·3): BE@1.5R, 3R서 peak-1R 트레일, 풀포지션, 48h max_hold(러너 면제) ──
def exit_v6(px, c, ems, side, entry, sl):
    tms, H, L, C = px[c]; risk = abs(entry - sl); sgn = 1.0 if side in ("long","buy") else -1.0
    i0 = int(np.searchsorted(tms, ems + SKIP*60000, "left")); i1 = min(i0 + HZ, len(tms))
    if risk <= 0 or i0 >= len(tms) or i1 - i0 < 2: return None
    h = H[i0:i1]; l = L[i0:i1]; cc = C[i0:i1]; ts = tms[i0:i1]
    fav = ((h-entry)/risk) if sgn > 0 else ((entry-l)/risk); adv = ((l-entry)/risk) if sgn > 0 else ((entry-h)/risk)
    stop = -1.0; peak = 0.0; runner = False
    for j in range(len(fav)):
        if adv[j] <= stop: return stop, int(ts[j])
        peak = max(peak, fav[j])
        if peak >= 1.5: stop = max(stop, 0.0)          # BE@1.5R
        if peak >= 3.0: runner = True; stop = max(stop, peak - 1.0)  # 3R 트레일 peak-1R (러너 활성)
        # ★48h max_hold: 러너 아니면 시간청산(현재봉 close). 라이브 time_exit_max_hold_bars 동일.
        if (not runner) and (ts[j] - ts[0]) / 60000 >= MAXHOLD_MIN:
            return float((cc[j]-entry)/risk*sgn), int(ts[j])
    return float((cc[-1]-entry)/risk*sgn), int(ts[-1])

# ── 진입 재생성 (완전체, --regen) ──
def regen_entries():
    import pickle, multiprocessing as mp
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    from smc_stage4d.structures import apply_indicators_and_build
    Fm.REG_VOL_PCTL = 0.85; Fm.BROAD_FVG_SIZE_ATR = 0.0
    prepared = pickle.load(open(os.path.join(DATA, "prepared_cache_2022.pkl"), "rb"))
    b = pd.read_parquet(f"{DATA}/data_cache/BTCUSDT_4h.parquet"); b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
    BTS = b["timestamp"].values; BDIST = ((b["close"].rolling(10).mean()-b["close"].rolling(30).mean())/b["close"].rolling(30).mean()*100.0).values
    def zone(ts):
        p = int(np.searchsorted(BTS, ts, "left")) - 1
        if p < 0 or np.isnan(BDIST[p]): return None
        bd = BDIST[p]; return "down" if bd < -1 else ("range" if bd <= 1 else "up")
    rules = json.load(open(os.path.join(RULES_DIR, "setups_btc_triple_a3v4.json"), encoding="utf-8"))
    ATOMSETS = [r["atoms"] + ["__zone_"+r["btc_zone"], "__side_"+r["side"]] for r in rules]
    ORIG = Fm.compute_trade_tags
    def wrap(*a, **kw):
        tags = ORIG(*a, **kw)
        try:
            df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
            z = zone(df["timestamp"].values[min(ei+1, len(df)-1)])
            if z is not None: tags["__zone_"+z] = True
            tags["__side_"+side] = True
        except Exception: pass
        return tags
    Fm.compute_trade_tags = wrap; sim.compute_trade_tags = wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = ATOMSETS
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    cand = {s: {"candidates": sim.generate_candidates_from_prepared(prepared[s])["candidates"],
                "df_h4": prepared[s]["df_struct"], "df_h1": prepared[s]["df_h1"], "symbol": s} for s in SYM}
    tr = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)["trades"].copy()
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    et = pd.to_datetime(tr["entry_time"], utc=True); pos = np.clip(np.searchsorted(BTS, et.values, "left")-1, 0, len(BTS)-1)
    tr["btc_zone"] = ["down" if d < -1 else ("range" if d <= 1 else "up") for d in BDIST[pos]]
    def amatch(g, a): return (not bool(g(a[1:]))) if a.startswith("~") else bool(g(a))
    def attr(r):
        z = r["btc_zone"]; sd = r["side"]
        m = [(i, ru["key"], len(ru["atoms"])) for i, ru in enumerate(rules)
             if ru["btc_zone"] == z and ru["side"] == sd and all(amatch(lambda a: bool(r.get(a, False)), at) for at in ru["atoms"])]
        return sorted(m, key=lambda x:(-x[2], x[0]))[0][1] if m else ""
    tr["matched_rule"] = tr.apply(attr, axis=1)
    return tr

# ── 자본 시뮬 ──
def calc_pos(bal, e, sl, rp):
    risk = bal*(rp/100.0); rpu = abs(e-sl)
    if rpu <= 0 or risk <= 0 or bal <= 0: return None
    qty = risk/(rpu*KRW)
    if qty*e*KRW > bal*MAXNOT: qty = bal*MAXNOT/(e*KRW)
    if (qty*e*KRW)*FEE*2 > risk*0.35: return None
    return qty*rpu*KRW
def equity(g, rp):
    g = g.sort_values("entry_time").reset_index(drop=True)
    ET = list(g["entry_time"]); XT = list(pd.to_datetime(g["exit_ms"], unit="ms", utc=True)); SY = list(g["symbol"])
    EN = list(g["entry"].astype(float)); SL = list(g["sl"].astype(float)); RV = list(g["R"].astype(float))
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1); deps = []; mt = start
    for _ in range(NDEP): mt = mt + pd.offsets.MonthBegin(1); deps.append((mt, MONTHLY))
    ev = []
    for i in range(len(ET)): ev.append((ET[i], 2, i)); ev.append((XT[i], 1, i))
    ev += [(dt, 0, -a) for dt, a in deps]; ev.sort(key=lambda z:(z[0], z[1]))
    bal = float(INIT); op = {}; osy = set(); pts = []
    for ts, pri, p in ev:
        if pri == 0: bal += (-p)
        elif pri == 1:
            if p in op: bal += RV[p]*op.pop(p); osy.discard(SY[p])
        else:
            if SY[p] in osy: continue
            rk = calc_pos(bal, EN[p], SL[p], rp)
            if rk is None: continue
            op[p] = rk; osy.add(SY[p])
        pts.append((ts, max(bal, 1)))
    for p, rk in list(op.items()): bal += RV[p]*rk
    e = pd.DataFrame(pts, columns=["t","b"]).drop_duplicates("t").sort_values("t")
    dd = ((e["b"]-e["b"].cummax())/e["b"].cummax()*100).min()
    yrs = max((max(XT)-min(ET)).days/365.25, 1e-9); tin = INIT+MONTHLY*NDEP
    return bal, (((bal/tin)**(1/yrs)-1)*100 if bal > 0 else np.nan), dd

def main():
    risk = 2.0; regen = False
    if "--risk" in sys.argv: risk = float(sys.argv[sys.argv.index("--risk")+1])
    if "--regen" in sys.argv: regen = True
    t0 = time.time()
    print(f"=== v6 백테 (라이브 동일) | 균일리스크 {risk}% | 진입={'재생성(완전체)' if regen else 'trades_v4(빠른경로)'} ===")
    if regen:
        print("진입 재생성 중(원시→후보)...")
        tr = regen_entries(); print(f"  재생성 {len(tr)}건 ({time.time()-t0:.0f}s)")
    else:
        tr = pd.read_csv(os.path.join(DATA, "trades_v4.csv"))
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    px = load_px()
    # v6 프레임: 만기36h컷 + 0%combo차단 + v6청산
    rows = []; be = bz = 0
    for _, r in tr.iterrows():
        c = r["symbol"]; ems = int(pd.Timestamp(r["entry_time"]).value//10**6); side = str(r["side"]).lower()
        entry = float(r["entry"]); sl = float(r["sl"]); setup = str(r.get("matched_rule","")).split("||")[0]
        if hours_to_expiry(r["entry_time"]) <= EXPH: be += 1; continue
        if not combo_active(setup): bz += 1; continue
        o = exit_v6(px, c, ems, side, entry, sl)
        if o is None: continue
        rows.append({"symbol": c, "entry_time": r["entry_time"], "exit_ms": o[1], "entry": entry, "sl": sl, "R": o[0]})
    g = pd.DataFrame(rows)
    R = g["R"].values; w = R[R>0].sum(); l = -R[R<0].sum(); pf = w/l if l > 0 else 9
    fin, cagr, mdd = equity(g, risk)
    print(f"\n  진입 {len(g)}건 (만기컷{be}·0%차단{bz}) | 청산 v6(BE@1.5·트레일peak-1R)")
    print(f"  PF {pf:.2f} | 승률 {(R>0).mean()*100:.1f}% | expR {R.mean():.3f} | 합R {R.sum():.0f}")
    print(f"  CAGR {cagr:.0f}% | 자본MDD {mdd:.1f}% | 최종 {fin/1e8:.1f}억 (시드5백만·월납입2.5백만·{NDEP}회)")
    g.to_csv(os.path.join(HERE, f"v6_result_risk{risk}.csv"), index=False, encoding="utf-8-sig")
    print(f"\n저장 -> v6_result_risk{risk}.csv | 완료 {time.time()-t0:.0f}s")

if __name__ == "__main__":
    import multiprocessing as mp; mp.freeze_support(); main()
