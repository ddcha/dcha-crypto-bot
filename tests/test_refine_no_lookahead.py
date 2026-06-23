import numpy as np, pandas as pd
from smc_stage4d.indicators import refine_zone_with_h1

def _make_h1(n, rng):
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0,0.5,n))
    df = pd.DataFrame({"timestamp":ts,"open":close+rng.normal(0,0.2,n),
                       "high":close+rng.uniform(0,1,n),"low":close-rng.uniform(0,1,n),"close":close})
    def zone(p):
        lo=np.full(n,np.nan);hi=np.full(n,np.nan);m=rng.random(n)<p
        b=close[m]+rng.uniform(-1,1,m.sum());w=rng.uniform(0.2,1.5,m.sum());lo[m]=b;hi[m]=b+w;return lo,hi
    for c in ["bull_fvg","bear_fvg","bull_ob","bear_ob"]:
        lo,hi=zone(0.3); df[c+"_low"]=lo; df[c+"_high"]=hi
    return df

def test_refine_no_lookahead():
    rng=np.random.default_rng(11); fcols=["open","high","low","close",
        "bull_fvg_low","bull_fvg_high","bear_fvg_low","bear_fvg_high",
        "bull_ob_low","bull_ob_high","bear_ob_low","bear_ob_high"]
    mism=0; fired=0
    for _ in range(3000):
        n=rng.integers(60,200); df=_make_h1(n,rng); ei=int(rng.integers(20,n))
        ets=df["timestamp"].iloc[ei]; base=df["close"].iloc[ei]
        lo=base+rng.uniform(-2,0); hi=lo+rng.uniform(0.5,3)
        r1=refine_zone_with_h1(df,ets,lo,hi)
        dfc=df.copy(); fut=(dfc["timestamp"]>=ets).values
        for c in fcols:
            col=dfc[c].values.copy(); col[fut]=rng.uniform(-999,999,fut.sum()); dfc[c]=col
        r2=refine_zone_with_h1(dfc,ets,lo,hi)
        mism += (r1!=r2); fired += r1[2]
    assert mism==0, f"LOOKAHEAD LEAK: {mism} mismatches"
    assert fired>0, "test not exercising refine"
