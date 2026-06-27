#!/usr/bin/env python3
# 2022 확장 prepared 캐시 빌드 (LOOKBACK_YEARS=5 → 2022-01부터). 병렬 indicators. room=swing60 영구.
import os, time, pickle
import multiprocessing as mp
OUT = "prepared_cache_2022.pkl"


def _setup():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    import smc_stage4d.data as D
    D.LOOKBACK_YEARS = 5   # 2022-01 포함 (cutoff 2021-06)


def _build_one(sym):
    _setup()
    from smc_stage4d.data import download_symbol_data
    from smc_stage4d.structures import apply_indicators_and_build
    return sym, apply_indicators_and_build(download_symbol_data(sym))


def main():
    from smc_stage4d.config import SCENARIO_MULTI
    SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
    ncore = max(1, min(mp.cpu_count() - 1, len(SYMBOLS)))
    print(f"[2022 캐시빌드] LOOKBACK_YEARS=5, {len(SYMBOLS)}코인 병렬({ncore}코어)")
    t0 = time.time()
    with mp.Pool(ncore) as pool:
        res = pool.map(_build_one, SYMBOLS)
    prepared = {s: p for s, p in res}
    for s, p in prepared.items():
        df = p["df_struct"]
        print(f"  {s}: H4 {len(df)}봉 {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    with open(OUT, "wb") as f:
        pickle.dump(prepared, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[완료] {time.time()-t0:.0f}s → {OUT} ({os.path.getsize(OUT)//1024//1024} MB)")


if __name__ == "__main__":
    mp.freeze_support(); main()
