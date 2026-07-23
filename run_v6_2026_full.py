#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 2026 완전판 — prepared 7/21 재빌드 + 후보 재생성(7월 신규진입 포함) + v6 프레임(만기36h컷·0%combo차단)
   + v5청산 + 1.5%/2% 월별. data_cache 무접촉(격리). 실행: STAGE4D_DLCACHE=data_cache python -u run_v6_2026_full.py"""
import os, json, time
os.environ.setdefault("STAGE4D_DLCACHE","data_cache")
os.environ.setdefault("OB_MODE","engulf"); os.environ.setdefault("DISP_ATR_MULT","1.3")
os.environ.setdefault("USE_H1_REFINE","1"); os.environ.setdefault("HONEST_STAGE","5")
os.environ["ATOM_AND_LIST"]=""; os.environ["ATOM_OR_LIST"]=""
import numpy as np, pandas as pd, glob
LIVE=r'D:/smc_bot/live_trading/v4_live_engine'
RAW=r'D:/smc_bot/v3 engine/data/raw_1m'; RAWJ=r'D:/smc_bot/v3 engine/data/raw_1m_july'; SKIP=240; HZ=7500
SYMBOLS=["ADAUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOGEUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT"]
INIT=5_000_000;MONTHLY=2_500_000;NDEP=5;KRW=1540.0;FEE=0.00055;MAXNOT=3.0;EXPH=36.0
RISK=json.load(open(f"{LIVE}/combo_risk_table.json",encoding="utf-8"))["combos"]
def srisk(k):
    i=RISK.get(k);return float(i.get("applied_risk_pct",0)) if i else 0.0
def _mexp():
    days=pd.date_range("2022-01-01","2028-12-31",freq="D",tz="UTC");fri=[d for d in days if d.weekday()==4]
    last={}
    for f in fri: last[(f.year,f.month)]=f
    return pd.DatetimeIndex(sorted(v.replace(hour=8) for v in last.values())).tz_localize(None).values
MEXP=_mexp()
def h2e(ts):
    et=np.datetime64(pd.Timestamp(ts).tz_convert("UTC").tz_localize(None));nxt=MEXP[min(int(np.searchsorted(MEXP,et,"left")),len(MEXP)-1)]
    return float((nxt-et)/np.timedelta64(1,"h"))

def resample(df1,rule):
    o=df1.set_index(pd.to_datetime(df1["timestamp_ms"],unit="ms",utc=True)).resample(rule,label="left",closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna().reset_index()
    o.columns=["timestamp","open","high","low","close"];return o

def build_prepared():
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL=0.85;F.BROAD_FVG_SIZE_ATR=0.0
    from smc_stage4d.structures import apply_indicators_and_build
    prep={}
    for s in SYMBOLS:
        h4=pd.read_parquet(f"data_cache/{s}_4h.parquet");h4["timestamp"]=pd.to_datetime(h4["timestamp"],utc=True)
        h1=pd.read_parquet(f"data_cache/{s}_1h.parquet");h1["timestamp"]=pd.to_datetime(h1["timestamp"],utc=True)
        jf=f"{RAWJ}/{s}_1m_jul.parquet"
        if os.path.exists(jf):
            j1=pd.read_parquet(jf)
            h4=pd.concat([h4,resample(j1,"4h")]).drop_duplicates("timestamp",keep="first").sort_values("timestamp").reset_index(drop=True)
            h1=pd.concat([h1,resample(j1,"1h")]).drop_duplicates("timestamp",keep="first").sort_values("timestamp").reset_index(drop=True)
        prep[s]=apply_indicators_and_build({"symbol":s,"df_raw":h4,"df_h1_raw":h1})
        print(f"  {s}: H4 {len(prep[s]['df_struct'])}봉 ~{prep[s]['df_struct']['timestamp'].max()}",flush=True)
    return prep

def gen_all(prep):
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    b=pd.read_parquet("data_cache/BTCUSDT_4h.parquet");b["timestamp"]=pd.to_datetime(b["timestamp"],utc=True)
    jf=f"{RAWJ}/BTCUSDT_1m_jul.parquet"
    if os.path.exists(jf): b=pd.concat([b,resample(pd.read_parquet(jf),"4h")]).drop_duplicates("timestamp",keep="first").sort_values("timestamp").reset_index(drop=True)
    BTS=b["timestamp"].values;BDIST=((b["close"].rolling(10).mean()-b["close"].rolling(30).mean())/b["close"].rolling(30).mean()*100.0).values
    def zone(ts):
        p=int(np.searchsorted(BTS,ts,"left"))-1
        if p<0 or np.isnan(BDIST[p]): return None
        bd=BDIST[p];return "down" if bd<-1 else ("range" if bd<=1 else "up")
    rules=json.load(open(f"{LIVE}/setups_btc_triple_a3v4.json",encoding="utf-8"))
    ATOMSETS=[r["atoms"]+["__zone_"+r["btc_zone"],"__side_"+r["side"]] for r in rules]
    ORIG=Fm.compute_trade_tags
    def wrap(*a,**kw):
        tags=ORIG(*a,**kw)
        try:
            df=kw["df_struct"];ei=int(kw["entry_idx"]);side=kw["side"]
            z=zone(df["timestamp"].values[min(ei+1,len(df)-1)])
            if z is not None: tags["__zone_"+z]=True
            tags["__side_"+side]=True
        except Exception: pass
        return tags
    Fm.compute_trade_tags=wrap;sim.compute_trade_tags=wrap
    sim.USE_COMBO_UNION=True;sim.COMBO_UNION_ATOMSETS=ATOMSETS
    from smc_stage4d.config import SCENARIO_MULTI
    from smc_stage4d.simulation import simulate_scenario_v19b_rpboost
    cand={s:{"candidates":sim.generate_candidates_from_prepared(prep[s])["candidates"],"df_h4":prep[s]["df_struct"],"df_h1":prep[s]["df_h1"],"symbol":s} for s in SYMBOLS}
    tr=simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI,candidates_dict=cand,risk_multiplier=1.0)["trades"].copy()
    tr=tr[~tr["exit_reason"].astype(str).str.contains("close_at_end",case=False,na=False)].reset_index(drop=True)
    # matched_rule 귀속
    et=pd.to_datetime(tr["entry_time"],utc=True);pos=np.clip(np.searchsorted(BTS,et.values,"left")-1,0,len(BTS)-1)
    tr["btc_zone"]=["down" if d<-1 else ("range" if d<=1 else "up") for d in BDIST[pos]]
    def amatch(g,a): return (not bool(g(a[1:]))) if a.startswith("~") else bool(g(a))
    def attr(r):
        z=r["btc_zone"];side=r["side"]
        m=[(i,ru["key"],len(ru["atoms"])) for i,ru in enumerate(rules) if ru["btc_zone"]==z and ru["side"]==side and all(amatch(lambda a:bool(r.get(a,False)),at) for at in ru["atoms"])]
        return sorted(m,key=lambda x:(-x[2],x[0]))[0][1] if m else ""
    tr["matched_rule"]=tr.apply(attr,axis=1)
    return tr

PX={}
def load_px():
    for c in SYMBOLS:
        parts=[pd.read_parquet(f"{RAW}/{c}_1m.parquet",columns=["timestamp_ms","high","low","close"])]
        if os.path.exists(f"{RAWJ}/{c}_1m_jul.parquet"): parts.append(pd.read_parquet(f"{RAWJ}/{c}_1m_jul.parquet",columns=["timestamp_ms","high","low","close"]))
        df=pd.concat(parts).drop_duplicates("timestamp_ms").sort_values("timestamp_ms")
        PX[c]=(df["timestamp_ms"].astype("int64").values,df["high"].values.astype(float),df["low"].values.astype(float),df["close"].values.astype(float))
def exit_v5(c,ems,side,entry,sl):
    tms,H,L,C=PX[c];risk=abs(entry-sl);sgn=1.0 if side in("long","buy") else -1.0
    i0=int(np.searchsorted(tms,ems+SKIP*60000,"left"));i1=min(i0+HZ,len(tms))
    if risk<=0 or i0>=len(tms) or i1-i0<2: return None
    h=H[i0:i1];l=L[i0:i1];cc=C[i0:i1];ts=tms[i0:i1]
    fav=((h-entry)/risk) if sgn>0 else ((entry-l)/risk);adv=((l-entry)/risk) if sgn>0 else ((entry-h)/risk)
    stop=-1.0;peak=0.0
    for j in range(len(fav)):
        if adv[j]<=stop: return stop,int(ts[j])
        peak=max(peak,fav[j])
        if peak>=1.5: stop=max(stop,0.0)
        if peak>=3.0: stop=max(stop,peak-1.0)
    return float((cc[-1]-entry)/risk*sgn),int(ts[-1])
def calc_pos(bal,e,sl,rp):
    risk=bal*(rp/100.0);rpu=abs(e-sl)
    if rpu<=0 or risk<=0 or bal<=0: return None
    qty=risk/(rpu*KRW)
    if qty*e*KRW>bal*MAXNOT: qty=bal*MAXNOT/(e*KRW)
    if (qty*e*KRW)*FEE*2>risk*0.35: return None
    return qty*rpu*KRW
def monthly(g,rp):
    g=g.sort_values("entry_time").reset_index(drop=True)
    ET=list(g["entry_time"]);XT=list(pd.to_datetime(g["exit_ms"],unit="ms",utc=True));SY=list(g["symbol"]);EN=list(g["entry"].astype(float));SL=list(g["sl"].astype(float));RV=list(g["R"].astype(float))
    start=pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1);deps=[];mt=start
    for _ in range(NDEP): mt=mt+pd.offsets.MonthBegin(1);deps.append((mt,MONTHLY))
    ev=[]
    for i in range(len(ET)): ev.append((ET[i],2,i));ev.append((XT[i],1,i))
    ev+=[(dt,0,-a) for dt,a in deps];ev.sort(key=lambda z:(z[0],z[1]))
    bal=float(INIT);op={};osy=set();pts=[];depos={}
    for ts,pri,p in ev:
        if pri==0: bal+=(-p);depos[pd.Timestamp(ts)]=depos.get(pd.Timestamp(ts),0)+(-p)
        elif pri==1:
            if p in op: bal+=RV[p]*op.pop(p);osy.discard(SY[p])
        else:
            if SY[p] in osy: continue
            rk=calc_pos(bal,EN[p],SL[p],rp)
            if rk is None: continue
            op[p]=rk;osy.add(SY[p])
        pts.append((pd.Timestamp(ts),max(bal,1)))
    for p,rk in list(op.items()): bal+=RV[p]*rk
    e=pd.DataFrame(pts,columns=["t","b"]).drop_duplicates("t",keep="last").set_index("t").sort_index()
    me=e["b"].resample("ME").last();dser=pd.Series(depos).resample("ME").sum() if depos else pd.Series(dtype=float)
    out={};vals=list(me.items())
    for i,(mo,v) in enumerate(vals):
        prev=INIT if i==0 else vals[i-1][1];dep=float(dser.get(mo,0.0));ret=(v-prev-dep)/prev*100 if prev>0 else 0
        mm=e[(e.index>=mo.replace(day=1))&(e.index<=mo)];mdd=((mm["b"]-mm["b"].cummax())/mm["b"].cummax()*100).min() if len(mm) else 0
        out[str(mo)[:7]]=(ret,mdd)
    return out

def main():
    t0=time.time();print("[v6 2026완전판] prepared 7/21 재빌드...")
    prep=build_prepared();print(f"[gen] 후보 재생성...({time.time()-t0:.0f}s)")
    tr=gen_all(prep);print(f"  전체 트레이드 {len(tr)}건 ({time.time()-t0:.0f}s)")
    load_px()
    # v6 프레임: 만기컷 + 0%combo차단 + v5청산
    tr["entry_time"]=pd.to_datetime(tr["entry_time"],utc=True)
    rows=[];be=bz=0
    for _,r in tr.iterrows():
        c=r["symbol"];ems=int(pd.Timestamp(r["entry_time"]).value//10**6);side=str(r["side"]).lower()
        entry=float(r["entry"]);sl=float(r["sl"]);setup=str(r.get("matched_rule","")).split("||")[0]
        if h2e(r["entry_time"])<=EXPH: be+=1; continue
        if srisk(setup)<=0: bz+=1; continue
        o=exit_v5(c,ems,side,entry,sl)
        if o is None: continue
        rows.append({"symbol":c,"entry_time":r["entry_time"],"exit_ms":o[1],"entry":entry,"sl":sl,"R":o[0]})
    g=pd.DataFrame(rows)
    print(f"  v6 진입 {len(g)}건 (만기컷{be}·0%차단{bz})")
    m15=monthly(g,1.5);m20=monthly(g,2.0)
    y26=[k for k in sorted(set(m15)|set(m20)) if k.startswith("2026")]
    print(f"\n=== v6 2026년 월별 수익률% (입금보정, 7월 신규진입 포함) — 1.5% vs 2.0% ===")
    print(f"{'월':<9}{'1.5%수익':>9}{'1.5%MDD':>9}  |{'2.0%수익':>9}{'2.0%MDD':>9}")
    for mo in y26:
        r15,d15=m15.get(mo,(0,0));r20,d20=m20.get(mo,(0,0))
        print(f"{mo:<9}{r15:>8.1f}%{d15:>8.1f}%  |{r20:>8.1f}%{d20:>8.1f}%")
    y15=sum(m15[k][0] for k in y26);y20=sum(m20[k][0] for k in y26)
    print(f"{'YTD':<9}{y15:>8.1f}%{'':>9}  |{y20:>8.1f}%")
    # 7월 진입 건수
    jul=g[pd.to_datetime(g["entry_time"],utc=True)>="2026-07-01"]
    print(f"\n7월 신규진입: {len(jul)}건 (데이터 ~7/21)")
    print(f"완료 {time.time()-t0:.0f}s")

if __name__=="__main__":
    import multiprocessing as mp; mp.freeze_support(); main()
