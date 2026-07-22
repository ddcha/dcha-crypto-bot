#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1R3R 트레일 청산 — 엔진 완전체 백테. 진입은 run_walkforward 후보생성 재사용(원시→재생성, replay아님),
   청산만 1R3R 트레일(활성화3R·트레일폭1R)로 1m 정직체결(entry+4h). 네이티브 v4와 엔진지표 나란히.
   실행: STAGE4D_DLCACHE=data_cache python -u run_1r3r_fullbt.py"""
import os, time, glob, json
os.environ.setdefault("STAGE4D_DLCACHE", "data_cache")
import multiprocessing as mp
import numpy as np, pandas as pd

RAW = r"D:/smc_bot/v3 engine/data/raw_1m"
SKIP_MIN = 240; HORIZON = 7500; ACT = 3.0; TW = 1.0   # 1R3R: 활성화3R, 트레일폭1R
SYMBOLS = ["ADAUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOGEUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT"]
# run_walkforward 자본모델
INIT_KRW=5_000_000; MONTHLY_KRW=2_500_000; NDEP=5; KRW_USDT=1540.0; RISK_PCT=0.01; FEE=0.00055; MAXNOT=3.0


def gen_entries():
    import run_walkforward as wf
    ncore = max(1, min(mp.cpu_count()-1, len(SYMBOLS)))
    with mp.Pool(ncore, initializer=wf._init_worker, initargs=(wf.CACHE, "setups_btc_triple_a3v4.json")) as pool:
        res = pool.map(wf._gen_one, SYMBOLS)
    return {s: c for s, c in res}


def trail_1r3r(fav, adv, closeR_last):
    peak = np.maximum.accumulate(fav); pp = np.empty_like(peak); pp[0]=0.0; pp[1:]=peak[:-1]
    stop = np.maximum(np.where(pp>=ACT, pp-TW, -1.0), -1.0)
    hit = adv <= stop
    if hit.any():
        j = int(np.argmax(hit)); return float(stop[j]), j
    return closeR_last, len(fav)-1


def apply_exit(cands):
    rows=[]
    for coin in SYMBOLS:
        cand = cands.get(coin)
        if cand is None or len(cand)==0: continue
        p1 = f"{RAW}/{coin}_1m.parquet"
        if not os.path.exists(p1): print(f"[skip 1m] {coin}"); continue
        df1 = pd.read_parquet(p1, columns=["timestamp_ms","high","low","close"])
        tms = df1["timestamp_ms"].astype("int64").values
        H=df1["high"].values.astype(np.float64); L=df1["low"].values.astype(np.float64); C=df1["close"].values.astype(np.float64)
        c = cand.copy(); c["entry_time"]=pd.to_datetime(c["entry_time"], utc=True)
        for _, t in c.iterrows():
            ems = int(pd.Timestamp(t["entry_time"]).value//10**6); side=str(t["side"]).lower()
            entry=float(t["entry"]); sl=float(t["sl"]); risk=abs(entry-sl)
            if risk<=0: continue
            sgn = 1.0 if side in ("long","buy") else -1.0
            i0=int(np.searchsorted(tms, ems+SKIP_MIN*60000, side="left")); i1=min(i0+HORIZON,len(tms))
            if i0>=len(tms) or i1-i0<2: continue
            h=H[i0:i1]; l=L[i0:i1]; cc=C[i0:i1]; ts=tms[i0:i1]
            fav=((h-entry)/risk) if sgn>0 else ((entry-l)/risk); adv=((l-entry)/risk) if sgn>0 else ((entry-h)/risk)
            closeR=float(((cc[-1]-entry)/risk*sgn))
            r, exj = trail_1r3r(fav, adv, closeR)
            rows.append({"symbol":coin,"side":side,"entry_time":pd.Timestamp(t["entry_time"]),
                         "exit_time":pd.to_datetime(int(ts[exj]),unit="ms",utc=True),
                         "entry":entry,"sl":sl,"r_multiple":r,"net_pnl":r})   # R단위 net_pnl(리스크1R기준)
    return pd.DataFrame(rows)


def _pf(p):
    p=np.asarray(p,float); g=p[p>0].sum(); l=-p[p<0].sum()
    return float(g/l) if l>0 else (float('inf') if g>0 else float('nan'))

def seg(d):
    r=d["r_multiple"].astype(float).values; n=len(r); k=int(n*0.7)
    cum=np.cumsum(r); peak=np.maximum.accumulate(cum) if len(cum) else cum; rmdd=float((cum-peak).min()) if len(cum) else 0.0
    yr=pd.to_datetime(d["exit_time"],utc=True).dt.year
    ypf={int(y):round(_pf(r[yr.values==y]),3) for y in sorted(set(yr))}
    return {"n":n,"PF":round(_pf(r),3),"OOS":round(_pf(r[k:]),3),"win":round(float((r>0).mean()*100),1),
            "expR":round(float(r.mean()),4),"MDD_R":round(rmdd,1),"allge1":all(v>=1 for v in ypf.values()),"ypf":ypf}

def calc_pos_krw(balance, entry, sl):
    risk=balance*RISK_PCT; rpu=abs(entry-sl)
    if rpu<=0: return None
    rpu_krw=rpu*KRW_USDT; qty=risk/rpu_krw; notional=qty*entry*KRW_USDT; maxn=balance*MAXNOT
    if notional>maxn: qty=maxn/(entry*KRW_USDT); notional=qty*entry*KRW_USDT
    if notional*FEE*2 > risk*0.35: return None
    return qty, qty*rpu_krw

def equity(g):
    g=g.sort_values("entry_time").reset_index(drop=True)
    ET=list(pd.to_datetime(g["entry_time"],utc=True)); XT=list(pd.to_datetime(g["exit_time"],utc=True))
    SYM=list(g["symbol"]); ENT=list(g["entry"].astype(float)); SL=list(g["sl"].astype(float)); RV=list(g["r_multiple"].astype(float))
    start=pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1); deps=[]; mt=start
    for _ in range(NDEP): mt=mt+pd.offsets.MonthBegin(1); deps.append((mt,MONTHLY_KRW))
    ev=[]
    for i in range(len(ET)): ev.append((ET[i],2,i)); ev.append((XT[i],1,i))
    ev+=[(dt,0,-amt) for dt,amt in deps]; ev.sort(key=lambda x:(x[0],x[1]))
    bal=float(INIT_KRW); openp={}; opensym=set(); eqpts=[]
    for ts,pri,p in ev:
        if pri==0: bal+=(-p)
        elif pri==1:
            if p in openp: rk=openp.pop(p); bal+=RV[p]*rk; opensym.discard(SYM[p])
        else:
            if SYM[p] in opensym: continue
            r=calc_pos_krw(bal,ENT[p],SL[p])
            if r is None: continue
            openp[p]=r[1]; opensym.add(SYM[p])
        eqpts.append((ts,bal))
    for p,rk in list(openp.items()): bal+=RV[p]*rk
    eq=pd.DataFrame(eqpts,columns=["time","ta"]).drop_duplicates("time").sort_values("time")
    eq["cm"]=eq["ta"].cummax(); eq["dd"]=(eq["ta"]-eq["cm"])/eq["cm"]*100
    mdd=float(eq["dd"].min()); total_in=INIT_KRW+MONTHLY_KRW*NDEP
    yrs=max((XT and (max(XT)-min(ET)).days/365.25) or 1e-9,1e-9)
    cagr=((bal/total_in)**(1/yrs)-1)*100 if bal>0 else float('nan')
    return {"final":bal,"ret":(bal-total_in)/total_in*100,"cagr":cagr,"mdd":mdd}

def walk_forward(d):
    dd=d[["exit_time","r_multiple"]].copy(); dd["exit_time"]=pd.to_datetime(dd["exit_time"],utc=True)
    start=pd.Timestamp("2022-01-01",tz="UTC"); end=dd["exit_time"].max(); wins=[]; v=start+pd.DateOffset(months=12)
    while v<end:
        ve=v+pd.DateOffset(months=3); val=dd[(dd.exit_time>=v)&(dd.exit_time<ve)]
        if len(val)>=5: wins.append(round(_pf(val["r_multiple"].values),3))
        v=v+pd.DateOffset(months=3)
    a=np.array([x for x in wins if np.isfinite(x)])
    return {"n":len(a),"mean":round(float(a.mean()),3) if len(a) else float('nan'),"ge1":round(float((a>=1).mean()*100),0) if len(a) else 0}


def main():
    t0=time.time(); print("[1R3R 완전체] 진입 재생성(run_walkforward 후보)...")
    cands=gen_entries(); print(f"  후보생성 {sum(len(c) for c in cands.values())}건 ({time.time()-t0:.0f}s)")
    tr=apply_exit(cands); print(f"  1R3R 1m청산 적용 {len(tr)}건 ({time.time()-t0:.0f}s)")
    tr.to_csv("run1r3r_result_trades.csv", index=False, encoding="utf-8-sig")
    s=seg(tr); c=equity(tr); w=walk_forward(tr)
    # 네이티브 v4 (동일 자본모델)
    v4=pd.read_csv("walkforward_result/trades_v4.csv")
    v4["r_multiple"]=pd.to_numeric(v4["r_multiple"],errors="coerce"); v4=v4.dropna(subset=["r_multiple"])
    v4["net_pnl"]=v4["r_multiple"]
    s4=seg(v4); c4=equity(v4); w4=walk_forward(v4)
    print("\n"+"="*78)
    print("=== 엔진 완전체 백테: 1R3R 트레일 vs 네이티브 v4 (동일 진입셋·자본모델) ===")
    print(f"{'지표':<16}{'1R3R트레일':>16}{'네이티브v4':>16}")
    print(f"{'거래수':<16}{s['n']:>16}{s4['n']:>16}")
    print(f"{'PF':<16}{s['PF']:>16}{s4['PF']:>16}")
    print(f"{'OOS PF':<16}{s['OOS']:>16}{s4['OOS']:>16}")
    print(f"{'승률%':<16}{s['win']:>16}{s4['win']:>16}")
    print(f"{'expR':<16}{s['expR']:>16}{s4['expR']:>16}")
    print(f"{'MDD_R':<16}{s['MDD_R']:>16}{s4['MDD_R']:>16}")
    print(f"{'매년PF≥1':<16}{str(s['allge1']):>16}{str(s4['allge1']):>16}")
    print(f"{'자본CAGR%':<16}{c['cagr']:>16.1f}{c4['cagr']:>16.1f}")
    print(f"{'자본MDD%':<16}{c['mdd']:>16.2f}{c4['mdd']:>16.2f}")
    print(f"{'최종KRW':<16}{c['final']:>16,.0f}{c4['final']:>16,.0f}")
    print(f"{'WF평균PF':<16}{w['mean']:>16}{w4['mean']:>16}")
    print(f"{'WF PF≥1%':<16}{w['ge1']:>16}{w4['ge1']:>16}")
    print(f"\n연도별PF 1R3R: {s['ypf']}")
    print(f"연도별PF   v4: {s4['ypf']}")
    print(f"\n완료 {time.time()-t0:.0f}s → run1r3r_result_trades.csv")


if __name__ == "__main__":
    mp.freeze_support(); main()
