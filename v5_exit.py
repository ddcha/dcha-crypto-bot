#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5 청산 스킴 레퍼런스 구현 — BT15·3 (BE@1.5R 본전 + 3R 와이드트레일, 풀포지션).
   진입은 v4와 동일(존 근접엣지·H1refine). 청산만 v5. 체결=entry+4h 1m 정직.
   스펙: V5_EXIT_SPEC.md. 실행(백테): python v5_exit.py"""
import os, numpy as np, pandas as pd

BE_R = 1.5        # 본전 이동 임계
TRAIL_ACT = 3.0   # 트레일 활성 임계
TRAIL_W = 1.0     # 트레일 폭 (stop = peak - TRAIL_W)
SKIP_MIN = 240    # entry+4h (진입 H4봉 스킵, 정직체결)
HORIZON = 7500    # 1m 최대보유(125h)


def v5_exit(fav, adv, closeR_last):
    """v5 청산. fav/adv = 1m봉별 유리/불리 R (진입가·SL 기준, side부호 반영, entry+4h 시작).
       반환: (실현R, 청산봉인덱스). 스탑은 직전봉 peak 기준(같은봉 룩어헤드 방지=보수)."""
    peak = np.maximum.accumulate(fav)
    pp = np.empty_like(peak); pp[0] = 0.0; pp[1:] = peak[:-1]      # 직전봉까지 peak
    be = np.where(pp >= BE_R, 0.0, -1.0)                           # 본전(1.5R 이후) or 원SL
    tr = np.where(pp >= TRAIL_ACT, pp - TRAIL_W, -1.0)             # 3R 이후 와이드트레일
    stop = np.maximum(np.maximum(be, tr), -1.0)
    hit = adv <= stop
    if hit.any():
        j = int(np.argmax(hit)); return float(stop[j]), j
    return float(closeR_last), len(fav) - 1


def apply_to_entries(entries, px):
    """entries: DataFrame[symbol, entry_time(utc), side, entry, sl]. px: {sym:(tms,H,L,C)}.
       반환: DataFrame[symbol, entry_time, exit_time, entry, sl, R]."""
    rows = []
    for _, t in entries.iterrows():
        c = t["symbol"]
        if c not in px: continue
        tms, H, L, C = px[c]
        ems = int(pd.Timestamp(t["entry_time"]).value // 10**6); side = str(t["side"]).lower()
        entry = float(t["entry"]); sl = float(t["sl"]); risk = abs(entry - sl)
        sgn = 1.0 if side in ("long", "buy") else -1.0
        i0 = int(np.searchsorted(tms, ems + SKIP_MIN * 60000, "left")); i1 = min(i0 + HORIZON, len(tms))
        if risk <= 0 or i0 >= len(tms) or i1 - i0 < 2: continue
        h = H[i0:i1]; l = L[i0:i1]; cc = C[i0:i1]; ts = tms[i0:i1]
        fav = ((h - entry) / risk) if sgn > 0 else ((entry - l) / risk)
        adv = ((l - entry) / risk) if sgn > 0 else ((entry - h) / risk)
        closeR = float((cc[-1] - entry) / risk * sgn)
        R, exj = v5_exit(fav.astype(float), adv.astype(float), closeR)
        rows.append({"symbol": c, "entry_time": t["entry_time"],
                     "exit_time": pd.to_datetime(int(ts[exj]), unit="ms", utc=True),
                     "entry": entry, "sl": sl, "R": R})
    return pd.DataFrame(rows)


def _load_px():
    RAW = r"D:/smc_bot/v3 engine/data/raw_1m"; RAWJ = r"D:/smc_bot/v3 engine/data/raw_1m_july"
    SYM = ["ADAUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOGEUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT"]
    px = {}
    for c in SYM:
        parts = [pd.read_parquet(f"{RAW}/{c}_1m.parquet", columns=["timestamp_ms","high","low","close"])]
        jp = f"{RAWJ}/{c}_1m_jul.parquet"
        if os.path.exists(jp): parts.append(pd.read_parquet(jp, columns=["timestamp_ms","high","low","close"]))
        df = pd.concat(parts).drop_duplicates("timestamp_ms").sort_values("timestamp_ms")
        px[c] = (df["timestamp_ms"].astype("int64").values, df["high"].values.astype(float),
                 df["low"].values.astype(float), df["close"].values.astype(float))
    return px


if __name__ == "__main__":
    ent = pd.read_csv("run1r3r_result_trades.csv"); ent["entry_time"] = pd.to_datetime(ent["entry_time"], utc=True)
    g = apply_to_entries(ent, _load_px())
    R = g["R"].values; w = R[R > 0]; l = R[R < 0]
    g.to_csv("v5_trades.csv", index=False, encoding="utf-8-sig")
    print(f"[v5 = BT15·3] 거래 {len(g)} | 합R {R.sum():.1f} | PF {w.sum()/-l.sum():.2f} | 승률 {(R>0).mean()*100:.1f}% | expR {R.mean():.3f}")
    print("saved -> v5_trades.csv")
