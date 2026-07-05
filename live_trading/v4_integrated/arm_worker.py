#!/usr/bin/env python3
"""★배경 무장존 워커 — H4 마감마다 1회 실행. 심볼별 full-히스토리(2022~)로 무장존 계산 → armed_cache.json.
   메인 루프는 이 캐시를 읽어 존 경계에 지정가 거치(main 배선). 계산 155s/심볼 × 9 = ~23분/H4(4h 여유).
   히스토리 소스: 기본 data_cache(로컬 parquet, 라이브서버에 동봉). 라이브 증분은 exchange fetch 로 append(옵션).
   실행: python arm_worker.py            (1회 계산 후 종료)
         python arm_worker.py --loop     (H4 경계 감지해 반복)
"""
import os, sys, json, time
for _k, _v in {"OB_MODE": "engulf", "DISP_ATR_MULT": "1.3", "USE_H1_REFINE": "1", "HONEST_STAGE": "5", "MIN_SCORE": "7.5"}.items():
    os.environ.setdefault(_k, _v)
os.environ.setdefault("ATOM_AND_LIST", ""); os.environ.setdefault("ATOM_OR_LIST", "")
import pandas as pd
import strategy_engine as SE

SYMBOLS = ["ADAUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT"]
DATA = os.environ.get("STAGE4D_DLCACHE", "../../data_cache")
BALANCE = float(os.environ.get("ARM_BALANCE", "10000"))     # 라이브: 실잔고 주입
RISK_PCT, FEE, MAXN = 1.0, 0.00055, 3.0
OUT = os.environ.get("ARMED_CACHE", "armed_cache.json")
H1_RECENT = 6400                                            # 현재봉 refine 엔 최근이면 충분(검증됨)


def _load(sym, tf, data_dir=DATA):
    d = pd.read_parquet(f"{data_dir}/{sym}_{tf}.parquet"); d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True)


def compute(symbols=SYMBOLS, data_dir=DATA, balance=BALANCE, loader=_load):
    """심볼별 무장존 계산. loader(sym,tf,data_dir)->DataFrame (라이브는 exchange 증분 loader 주입 가능)."""
    SE._init()
    SE.set_btc_regime(loader("BTCUSDT", "4h", data_dir))   # btc 레짐 (COMBO_UNION __zone)
    cache = {}
    for sym in symbols:
        t0 = time.time()
        try:
            h4 = loader(sym, "4h", data_dir)
            h1 = loader(sym, "1h", data_dir).tail(H1_RECENT).reset_index(drop=True)
            r = SE.get_armed_zones(h4, h1, balance, RISK_PCT, FEE, MAXN, symbol=sym)
            cache[sym] = {"timestamp": r.get("timestamp"), "hours_to_expiry": r.get("hours_to_expiry"),
                          "btc_zone": r.get("btc_zone"), "n_raw": r.get("n_raw", 0),
                          "armed": r.get("armed", []), "reason": r.get("reason"),
                          "h4_last": str(h4["timestamp"].iloc[-1]), "sec": round(time.time() - t0, 1)}
            print(f"[arm] {sym}: 무장 {len(cache[sym]['armed'])}개 (raw {cache[sym]['n_raw']}) {cache[sym]['sec']}s")
        except Exception as e:
            cache[sym] = {"error": str(e), "armed": []}
            print(f"[arm] {sym} ERROR: {e}")
    return cache


def write_cache(cache, out=OUT):
    payload = {"computed_at": pd.Timestamp.now("UTC").isoformat(), "config": "cap15_36h_backtrail_15mfill", "symbols": cache}
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, ensure_ascii=False, indent=1)
    os.replace(tmp, out)   # 원자적 교체 (메인이 읽는 중 깨짐 방지)


def main():
    syms = SYMBOLS
    if "--syms" in sys.argv:
        syms = sys.argv[sys.argv.index("--syms") + 1].split(",")
    t0 = time.time()
    cache = compute(syms)
    write_cache(cache)
    tot = sum(len(v.get("armed", [])) for v in cache.values())
    print(f"[arm] 완료: {len(syms)}심볼 무장 총 {tot}개 → {OUT} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
