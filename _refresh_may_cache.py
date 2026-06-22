r"""
5월 데이터 캐시 갱신 (daily archive)
=====================================
Binance monthly archive는 2026-05 미공개. daily archive(일별 zip)는 사용 가능.
9 코인 × 3 interval (4h/1h/15m) × 31일 = 837 zip 병렬 다운로드 후
기존 data_cache/{SYMBOL}_{INTERVAL}.parquet 에 append + 중복 제거.

원본 캐시는 _backup_pre_may/ 로 백업.
"""
from __future__ import annotations
import io, sys, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import requests

ROOT  = Path(r"D:\smc_bot")
CACHE = ROOT / "data_cache"
BAK   = CACHE / "_backup_pre_may"
BAK.mkdir(exist_ok=True)

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT",
           "AVAXUSDT","LINKUSDT","BNBUSDT","ADAUSDT"]
INTERVALS = ["4h","1h","15m"]
DAYS = [f"2026-05-{d:02d}" for d in range(1, 32)]

BASE = "https://data.binance.vision/data/futures/um/daily/klines"
SESS = requests.Session()
SESS.headers["User-Agent"] = "smc-bot/cache-refresh"


def fetch_one(symbol: str, interval: str, day: str):
    url = f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{day}.zip"
    try:
        r = SESS.get(url, timeout=20)
        if r.status_code != 200:
            return (symbol, interval, day, None, f"HTTP {r.status_code}")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = pd.read_csv(z.open(z.namelist()[0]))
        if "open_time" in raw.columns:
            raw = raw.rename(columns={"open_time": "timestamp"})
            raw = raw[["timestamp","open","high","low","close","volume"]]
        else:
            raw = raw.iloc[:, :6].copy()
            raw.columns = ["timestamp","open","high","low","close","volume"]
        raw["timestamp"] = pd.to_numeric(raw["timestamp"], errors="coerce")
        raw = raw.dropna(subset=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], unit="ms", utc=True)
        for c in ["open","high","low","close","volume"]:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
        return (symbol, interval, day, raw, None)
    except Exception as e:
        return (symbol, interval, day, None, str(e))


def process_pair(symbol: str, interval: str):
    """심볼·인터벌 한 쌍에 대해 31일 daily archive 다운로드 → 캐시 append."""
    cache_fp = CACHE / f"{symbol}_{interval}.parquet"
    bak_fp   = BAK   / f"{symbol}_{interval}.parquet"
    if cache_fp.exists() and not bak_fp.exists():
        # 첫 실행 시 백업
        import shutil
        shutil.copy2(cache_fp, bak_fp)

    # 기존 캐시
    if cache_fp.exists():
        cur = pd.read_parquet(cache_fp)
        if cur["timestamp"].dt.tz is None:
            cur["timestamp"] = cur["timestamp"].dt.tz_localize("UTC")
        else:
            cur["timestamp"] = cur["timestamp"].dt.tz_convert("UTC")
    else:
        cur = pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])

    # 31일 병렬 다운로드
    new_frames = []
    fail = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch_one, symbol, interval, d) for d in DAYS]
        for f in as_completed(futs):
            s, iv, d, df, err = f.result()
            if df is not None:
                new_frames.append(df)
            else:
                fail.append((d, err))

    if not new_frames:
        return symbol, interval, len(cur), 0, fail, "no_new"

    new_df = pd.concat(new_frames, ignore_index=True)

    # append + 중복 제거 + 정렬
    merged = (pd.concat([cur, new_df], ignore_index=True)
                .drop_duplicates("timestamp")
                .sort_values("timestamp")
                .reset_index(drop=True))

    # 저장
    merged.to_parquet(cache_fp, index=False)

    n_added = len(merged) - len(cur)
    last_ts = merged["timestamp"].iloc[-1]
    return symbol, interval, len(cur), n_added, fail, str(last_ts)


print(f"[refresh] cache dir: {CACHE}")
print(f"[refresh] backup dir: {BAK}")
print(f"[refresh] {len(SYMBOLS)}×{len(INTERVALS)}×{len(DAYS)} = "
      f"{len(SYMBOLS)*len(INTERVALS)*len(DAYS)} zip files target\n")

pairs = [(s, iv) for s in SYMBOLS for iv in INTERVALS]
print(f"Processing {len(pairs)} (symbol, interval) pairs in parallel…\n")

# 9 × 3 = 27 pairs, 각 쌍 안에서 31일 병렬. 외부에서 9 pair만 동시 (즉 9*8=72 thread oversub 회피)
results = []
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(process_pair, s, iv): (s, iv) for s, iv in pairs}
    for f in as_completed(futs):
        s, iv = futs[f]
        try:
            sym, ivl, old_n, added, fail, info = f.result()
            ratio = f"+{added}" if added else "+0"
            print(f"  [{sym} {ivl:>3}] cache {old_n:>7} → +{added:<5}  last={info}  fail={len(fail)}")
            results.append({"symbol": sym, "interval": ivl, "old": old_n, "added": added,
                            "last": info, "fail_n": len(fail)})
        except Exception as e:
            print(f"  [{s} {iv}] FAIL: {e}")
            results.append({"symbol": s, "interval": iv, "old": -1, "added": -1,
                            "last": "ERROR", "fail_n": -1})

res_df = pd.DataFrame(results)
res_df.to_csv(ROOT / "sweep_analysis_outputs" / "08_may_cache_refresh.csv",
              index=False)

print("\n=== Summary ===")
print(res_df.to_string(index=False))
print(f"\nTotal new rows: {res_df['added'].sum()}")
print(f"Failed downloads: {res_df['fail_n'].sum()} (per pair, max {len(DAYS)} = full month miss)")
