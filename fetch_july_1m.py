#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-07 1m 캔들 다운로드(Binance Vision 일별) → raw_1m_july/{COIN}_1m_jul.parquet. 기존 raw_1m 안건드림."""
import os, io, zipfile, datetime as dt, socket, urllib.request, urllib.error
import pandas as pd
socket.setdefaulttimeout(180)
OUT = r"D:/smc_bot/v3 engine/data/raw_1m_july"; os.makedirs(OUT, exist_ok=True)
BASE_D = "https://data.binance.vision/data/futures/um/daily/klines"
BASE_M = "https://data.binance.vision/data/futures/um/monthly/klines"
COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","BNBUSDT"]
KCOLS = ["open_time","open","high","low","close","volume","close_time","quote_volume","count","tbv","tbqv","ignore"]

def dl(url):
    try:
        with urllib.request.urlopen(url) as r: return r.read()
    except urllib.error.HTTPError as e: return None if e.code == 404 else "ERR"
    except Exception: return "ERR"

def read_zip(b):
    z = zipfile.ZipFile(io.BytesIO(b)); n = z.namelist()[0]
    head = z.open(n).read(64).split(b"\n")[0].split(b",")[0]
    hh = not head.replace(b".", b"").replace(b"-", b"").isdigit()
    return pd.read_csv(z.open(n), header=(0 if hh else None), names=(None if hh else KCOLS))

today = dt.datetime.now(dt.timezone.utc).date()
for coin in COINS:
    outp = os.path.join(OUT, f"{coin}_1m_jul.parquet")
    frames = []
    # 월별 우선(7월 완료시), 없으면 일별
    b = dl(f"{BASE_M}/{coin}/1m/{coin}-1m-2026-07.zip")
    if b not in (None, "ERR"):
        frames.append(read_zip(b))
    else:
        for d in range(1, 32):
            day = dt.date(2026, 7, d)
            if day >= today: break
            bd = dl(f"{BASE_D}/{coin}/1m/{coin}-1m-{day.isoformat()}.zip")
            if bd not in (None, "ERR"): frames.append(read_zip(bd))
    if not frames:
        print(f"{coin}: NO JULY DATA"); continue
    d = pd.concat(frames, ignore_index=True); d.columns = [str(c) for c in d.columns]
    if "open_time" not in d.columns: d.columns = KCOLS[:len(d.columns)]
    d = d.rename(columns={"open_time": "timestamp_ms"})[["timestamp_ms", "open", "high", "low", "close"]]
    d["timestamp_ms"] = pd.to_numeric(d["timestamp_ms"], errors="coerce").astype("int64")
    for c in ["open", "high", "low", "close"]: d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["timestamp_ms"]).drop_duplicates("timestamp_ms").sort_values("timestamp_ms").reset_index(drop=True)
    d.to_parquet(outp, index=False)
    mx = pd.Timestamp(int(d["timestamp_ms"].max()), unit="ms", tz="UTC")
    print(f"{coin}: {len(d)} rows -> ...{mx}")
print("DONE july 1m.")
