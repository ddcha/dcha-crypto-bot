#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7월 확장: 기존 4h/1h(2022~6월) + 7월 1m 리샘플 → prepared 재빌드(7월포함) → 후보 재생성 → 1m 청산 4스킴 → 7월 월별.
   data_cache 안건드림(라이브 보호). 실행: STAGE4D_DLCACHE=data_cache python -u run_july_extend.py"""
import os, time
os.environ.setdefault("STAGE4D_DLCACHE", "data_cache")
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
import numpy as np, pandas as pd, json, glob
SYMBOLS = ["ADAUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOGEUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT"]
RAW_JUN = r"D:/smc_bot/v3 engine/data/raw_1m"; RAW_JUL = r"D:/smc_bot/v3 engine/data/raw_1m_july"
SKIP_MIN = 240; HORIZON = 7500

def resample(df1, rule):
    o = df1.set_index(pd.to_datetime(df1["timestamp_ms"], unit="ms", utc=True)).resample(rule, label="left", closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna().reset_index().rename(columns={"index":"timestamp"})
    o.columns = ["timestamp","open","high","low","close"]; return o

def build_prepared_july():
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85; F.BROAD_FVG_SIZE_ATR = 0.0
    from smc_stage4d.structures import apply_indicators_and_build
    prep = {}
    for s in SYMBOLS:
        h4 = pd.read_parquet(f"data_cache/{s}_4h.parquet"); h4["timestamp"] = pd.to_datetime(h4["timestamp"], utc=True)
        h1 = pd.read_parquet(f"data_cache/{s}_1h.parquet"); h1["timestamp"] = pd.to_datetime(h1["timestamp"], utc=True)
        jf = f"{RAW_JUL}/{s}_1m_jul.parquet"
        if os.path.exists(jf):
            j1 = pd.read_parquet(jf)
            j4 = resample(j1, "4h"); jh1 = resample(j1, "1h")
            h4 = pd.concat([h4, j4]).drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True)
            h1 = pd.concat([h1, jh1]).drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True)
        prep[s] = apply_indicators_and_build({"symbol": s, "df_raw": h4, "df_h1_raw": h1})
        print(f"  {s}: H4 {len(prep[s]['df_struct'])}봉 ~{prep[s]['df_struct']['timestamp'].max()}", flush=True)
    return prep

def gen_candidates(prep):
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    b = pd.read_parquet("data_cache/BTCUSDT_4h.parquet"); b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
    jf = f"{RAW_JUL}/BTCUSDT_1m_jul.parquet"
    if os.path.exists(jf):
        b = pd.concat([b, resample(pd.read_parquet(jf), "4h")]).drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True)
    BTS = b["timestamp"].values
    BDIST = ((b["close"].rolling(10).mean() - b["close"].rolling(30).mean()) / b["close"].rolling(30).mean() * 100.0).values
    def zone(ts):
        p = int(np.searchsorted(BTS, ts, side="left")) - 1
        if p < 0 or np.isnan(BDIST[p]): return None
        bd = BDIST[p]; return "down" if bd < -1 else ("range" if bd <= 1 else "up")
    rules = json.load(open("setups_btc_triple_a3v4.json", encoding="utf-8"))
    ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in rules]
    ORIG = Fm.compute_trade_tags
    def wrap(*a, **kw):
        tags = ORIG(*a, **kw)
        try:
            df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
            z = zone(df["timestamp"].values[min(ei + 1, len(df) - 1)])
            if z is not None: tags["__zone_" + z] = True
            tags["__side_" + side] = True
        except Exception: pass
        return tags
    Fm.compute_trade_tags = wrap; sim.compute_trade_tags = wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = ATOMSETS
    out = {}
    for s in SYMBOLS:
        out[s] = sim.generate_candidates_from_prepared(prep[s])["candidates"]
    return out

def load_1m():
    d = {}
    for s in SYMBOLS:
        parts = [pd.read_parquet(f"{RAW_JUN}/{s}_1m.parquet", columns=["timestamp_ms","high","low","close"])]
        jf = f"{RAW_JUL}/{s}_1m_jul.parquet"
        if os.path.exists(jf): parts.append(pd.read_parquet(jf, columns=["timestamp_ms","high","low","close"]))
        df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp_ms").sort_values("timestamp_ms").reset_index(drop=True)
        d[s] = (df["timestamp_ms"].astype("int64").values, df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
    return d

def exit_sim(coin, ems, side, entry, sl, d1m, scheme):
    tms, H, L, C = d1m[coin]; risk = abs(entry - sl); sgn = 1.0 if side in ("long","buy") else -1.0
    i0 = int(np.searchsorted(tms, ems + SKIP_MIN*60000, side="left")); i1 = min(i0 + HORIZON, len(tms))
    if risk <= 0 or i0 >= len(tms) or i1 - i0 < 2: return None
    h = H[i0:i1]; l = L[i0:i1]; c = C[i0:i1]; ts = tms[i0:i1]
    fav = ((h-entry)/risk) if sgn > 0 else ((entry-l)/risk); adv = ((l-entry)/risk) if sgn > 0 else ((entry-h)/risk)
    closeR = float((c[-1]-entry)/risk*sgn); stop = -1.0; peak = 0.0
    be = {"trail":None,"trailBE1":1.0,"trailBE15":1.5,"trailBE2":2.0}[scheme]
    for j in range(len(fav)):
        if adv[j] <= stop: return stop, int(ts[j])
        peak = max(peak, fav[j])
        if be is not None and peak >= be: stop = max(stop, 0.0)
        if peak >= 3.0: stop = max(stop, peak - 1.0)
    return closeR, int(ts[-1])

def main():
    t0 = time.time(); print("[7월확장] prepared 재빌드..."); prep = build_prepared_july()
    print(f"후보 재생성... ({time.time()-t0:.0f}s)"); cands = gen_candidates(prep)
    d1m = load_1m()
    schemes = [("BE@2R","trailBE2"),("순정 1R3R","trail"),("BE@1.5R","trailBE15"),("BE@1R","trailBE1")]
    # 7월 진입만 (2026-07)
    jul_entries = []
    for s in SYMBOLS:
        c = cands[s].copy(); c["entry_time"] = pd.to_datetime(c["entry_time"], utc=True)
        cj = c[(c["entry_time"] >= "2026-07-01") & (c["entry_time"] < "2026-08-01")]
        for _, r in cj.iterrows():
            jul_entries.append({"symbol": s, "entry_time": r["entry_time"], "side": str(r["side"]).lower(), "entry": float(r["entry"]), "sl": float(r["sl"])})
    print(f"\n7월 진입 후보: {len(jul_entries)}건")
    OUTD = r"D:/smc_bot/v3_2026_monthly"; os.makedirs(OUTD, exist_ok=True)
    def pf(r): r=np.asarray(r,float); g=r[r>0].sum(); l=-r[r<0].sum(); return round(g/l,2) if l>0 else float('inf')
    for name, sc in schemes:
        rows = []
        for e in jul_entries:
            o = exit_sim(e["symbol"], int(e["entry_time"].value//10**6), e["side"], e["entry"], e["sl"], d1m, sc)
            if o is None: continue
            R, exms = o; rows.append({"symbol": e["symbol"], "entry_time": e["entry_time"], "exit_time": pd.Timestamp(exms, unit="ms", tz="UTC"), "R": R})
        d = pd.DataFrame(rows)
        # 7월 청산분만 집계(청산이 7월)
        dj = d[(pd.to_datetime(d["exit_time"], utc=True) >= "2026-07-01")] if len(d) else d
        R = dj["R"].values if len(dj) else np.array([])
        d.to_csv(f"{OUTD}/july_{name.replace('@','').replace(' ','_').replace('.','')}.csv", index=False, encoding="utf-8-sig")
        s_ = f"거래 {len(dj)} | 합R {R.sum():.2f} | 평균 {R.mean():.3f} | 승률 {(R>0).mean()*100:.1f}% | PF {pf(R)}" if len(R) else "거래 0"
        print(f"@@@{name}@@@ 2026-07: {s_}")
    print(f"\n완료 {time.time()-t0:.0f}s -> {OUTD}/july_*.csv")

if __name__ == "__main__":
    main()
