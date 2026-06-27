#!/usr/bin/env python3
# 3단계(재구현): 15m MTF fill — 제대로. 결함 2개 수정:
#   ① 트레일링 atr = H4스케일 atr(4h에서 계산해 15m에 매핑) — 15m rolling atr 쓰던 버그 제거.
#   ② entry walk = H4 봉 i+1(entry_time+4h)부터 — 진입봉 공짜무빙 제거(H4 sim이 i+1부터 체크하는 것과 일치).
#   같은 entry/sl/plan(targets RR기반), max_hold ×16. H4 r vs 15m r 비교(낙관편향).
import os, time
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
import numpy as np, pandas as pd
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import get_tp_plan, _simulate_trade_with_plan_core
from smc_stage4d.config import FEE_RATE, USE_SEQ_RUNNER_PROTECTION_BASELINE

BARS = 16
sim.FAST_2R_BARS_MAX = sim.FAST_2R_BARS_MAX * BARS        # 봉수기반 runner조건 15m 스케일
sim.ABOVE_2R_BARS_MIN = sim.ABOVE_2R_BARS_MIN * BARS
SYMBOLS = ["ADAUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT"]
FOUR_H = np.timedelta64(4, "h")


def _h4_atr(sym):
    d = pd.read_parquet(f"data_cache/{sym}_4h.parquet"); d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.sort_values("timestamp").reset_index(drop=True); pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["h4atr"] = tr.rolling(14).mean()
    return d[["timestamp", "h4atr"]]


def load_15m():
    d15 = {}
    for s in SYMBOLS:
        df = pd.read_parquet(f"data_cache/{s}_15m.parquet"); df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        h4 = _h4_atr(s)
        # 15m 각 봉 → 직전(포함) H4봉의 atr (H4 스케일). merge_asof backward.
        m = pd.merge_asof(df[["timestamp"]], h4, on="timestamp", direction="backward")
        df["atr"] = m["h4atr"].values
        d15[s] = df
    return d15


def _pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else float("nan"))


def resim_15m(trades, d15):
    r15 = np.full(len(trades), np.nan); used = 0
    bmap = {s: d15[s]["timestamp"].values for s in SYMBOLS}
    for ii, t in trades.reset_index(drop=True).iterrows():
        s = t["symbol"]; df = d15[s]; bts = bmap[s]
        et = np.datetime64(pd.Timestamp(t["entry_time"]).tz_convert("UTC").tz_localize(None))
        nxt = et + FOUR_H                                  # H4 봉 i+1 시작
        pos = int(np.searchsorted(bts, nxt, side="left"))  # entry_time+4h 의 15m봉
        entry_idx = pos - 1                                 # walk 는 entry_idx+1 = i+1 첫봉부터
        if entry_idx < 0 or entry_idx >= len(df) - 2:
            continue
        plan = dict(get_tp_plan(str(t.get("tp_plan_name", "base")) == "expansion"))
        plan["max_hold_bars"] = int(plan["max_hold_bars"] * BARS)
        try:
            res = _simulate_trade_with_plan_core(
                df_local=df, entry_idx=entry_idx, side=t["side"], entry=float(t["fill_entry"]), sl=float(t["sl"]),
                qty=1.0, fee_rate=FEE_RATE, grade=t.get("grade", "C"), plan=plan,
                use_seq_runner_protection=USE_SEQ_RUNNER_PROTECTION_BASELINE, disable_time_exit_when_runner=False)
            rm = res["r_multiple"]
            if rm is not None and not np.isnan(rm):
                r15[ii] = rm; used += 1
        except Exception:
            pass
    return r15, used


def metrics(r):
    r = np.asarray(r, float); r = r[~np.isnan(r)]; n = len(r); k = int(n * 0.7)
    return {"n": n, "PF": round(_pf(r), 3), "OOS": round(_pf(r[k:]), 3), "win%": round(float((r > 0).mean() * 100), 1), "expR": round(float(r.mean()), 4)}


def main():
    print("[15m MTF 재구현] 15분봉 로드 + H4스케일 atr 매핑")
    t0 = time.time(); d15 = load_15m(); print(f"  로드 {time.time()-t0:.0f}s")
    rows = []
    for label, f in [("a3", "walkforward_result/trades_a3.csv"), ("v4", "walkforward_result/trades_v4.csv")]:
        if not os.path.exists(f):
            print(f"[skip] {f}"); continue
        tr = pd.read_csv(f); tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
        r4 = tr["r_multiple"].astype(float).values
        t1 = time.time(); r15, used = resim_15m(tr, d15)
        ok = ~np.isnan(r15); m4 = metrics(r4[ok]); m15 = metrics(r15[ok])
        flip_dn = int(((r4[ok] > 0) & (r15[ok] <= 0)).sum()); flip_up = int(((r4[ok] <= 0) & (r15[ok] > 0)).sum())
        print(f"\n##### {label} ##### 거래 {len(tr)} | 15m재현 {used} ({time.time()-t1:.0f}s)")
        print(f"  [H4 ]  PF={m4['PF']} OOS={m4['OOS']} 승률={m4['win%']}% expR={m4['expR']}")
        print(f"  [15m]  PF={m15['PF']} OOS={m15['OOS']} 승률={m15['win%']}% expR={m15['expR']}")
        print(f"  PF변화 {m15['PF']-m4['PF']:+.3f} | 부호뒤집힘 H4승→15m패 {flip_dn}({flip_dn/used*100:.1f}%) H4패→15m승 {flip_up}({flip_up/used*100:.1f}%) 순 {flip_dn-flip_up:+d}")
        tr["r15m"] = r15; os.makedirs("mtf15_result", exist_ok=True); tr.to_csv(f"mtf15_result/trades_{label}_15m.csv", index=False)
        rows.append({"label": label, "H4_PF": m4["PF"], "15m_PF": m15["PF"], "H4_OOS": m4["OOS"], "15m_OOS": m15["OOS"],
                     "H4_win": m4["win%"], "15m_win": m15["win%"], "flipdn%": round(flip_dn / used * 100, 1)})
    print("\n=== H4 vs 15m 종합 ===\n" + pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
