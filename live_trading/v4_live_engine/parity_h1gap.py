# -*- coding: utf-8 -*-
"""[파리티] H1 갭수정 before/after — 9심볼 무장존을 구(limit=200)·신(시드연결 페이지네이션)
   로더로 각각 완전 재계산하고 무장존을 비트 비교한다.

   구 로더 = 수정 전 make_live_loader (data_cache 시드 + 최근 200봉)
   신 로더 = 수정 후 (시드 끝 since_ms 로 페이지네이션 → 갭 없음)

   klines 는 공개데이터라 API 키 불필요. 실행: python parity_h1gap.py
"""
import os, sys, json, time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arm_worker as AW

URL = "https://api.bybit.com/v5/market/kline"
IMAP = {"4h": "240", "1h": "60"}
_S = None


def _sess():
    global _S
    if _S is None:
        import requests
        _S = requests.Session()
    return _S


def _kl(sym, iv, limit, end=None):
    p = {"category": "linear", "symbol": sym, "interval": iv, "limit": limit}
    if end is not None:
        p["end"] = end
    for attempt in range(5):
        try:
            r = _sess().get(URL, params=p, timeout=25)
            return r.json().get("result", {}).get("list", [])
        except Exception:
            time.sleep(1.0 + attempt)
    return []


def _df(items):
    return pd.DataFrame([{"timestamp": pd.to_datetime(int(x[0]), unit="ms", utc=True),
                          "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                          "close": float(x[4]), "volume": float(x[5])} for x in items]) \
             .sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def loader_old(sym, tf, data_dir=AW.DATA):
    """수정 전: 최근 200봉 고정."""
    base = AW._load(sym, tf, data_dir)
    rec = _df(_kl(sym, IMAP[tf], 200))
    return pd.concat([base, rec], ignore_index=True).drop_duplicates("timestamp") \
             .sort_values("timestamp").reset_index(drop=True)


def loader_new(sym, tf, data_dir=AW.DATA):
    """수정 후: 시드 끝까지 페이지네이션(get_full_klines_df 와 동일 알고리즘)."""
    base = AW._load(sym, tf, data_dir)
    since = int(pd.Timestamp(base["timestamp"].iloc[-1]).value // 10 ** 6)
    items, end = [], None
    for _ in range(6):
        got = _kl(sym, IMAP[tf], 1000, end)
        if not got:
            break
        items.extend(got)
        oldest = min(int(x[0]) for x in got)
        if oldest <= since or len(got) < 1000:
            break
        end = oldest - 1
    rec = _df([x for x in items if int(x[0]) >= since])
    return pd.concat([base, rec], ignore_index=True).drop_duplicates("timestamp") \
             .sort_values("timestamp").reset_index(drop=True)


def gapcheck(loader, tag):
    print(f"\n--- 갭 점검 [{tag}] ---")
    tot = 0
    for sym in AW.SYMBOLS:
        for tf, st in (("4h", 4.0), ("1h", 1.0)):
            d = loader(sym, tf)["timestamp"].diff()
            n = int((d > pd.Timedelta(hours=st * 1.5)).sum())
            tot += n
            if n:
                i = d.idxmax()
                print(f"  {sym:9} {tf}: 갭 {n}개 (최대 {d.max()})")
    print(f"  → 총 갭 {tot}개")
    return tot


def key(z):
    return (z["side"], round(float(z["entry"]), 8), round(float(z["sl"]), 8))


def run(loader, tag):
    t = time.time()
    print(f"\n=== 무장 재계산 [{tag}] ===", flush=True)
    c = AW.compute_parallel(loader=loader)
    print(f"  ({time.time()-t:.0f}s)")
    return c


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    g_old = gapcheck(loader_old, "구(200봉)")
    g_new = gapcheck(loader_new, "신(시드연결)")

    old = run(loader_old, "구(200봉)")
    new = run(loader_new, "신(시드연결)")

    print("\n" + "=" * 78)
    print(f"{'심볼':>10}{'구무장':>8}{'신무장':>8}{'동일':>8}{'구only':>8}{'신only':>8}")
    tot_s = tot_o = tot_n = 0
    diffs = []
    for sym in AW.SYMBOLS:
        a = {key(z) for z in old.get(sym, {}).get("armed", [])}
        b = {key(z) for z in new.get(sym, {}).get("armed", [])}
        same, oo, nn = len(a & b), len(a - b), len(b - a)
        tot_s += same; tot_o += oo; tot_n += nn
        print(f"{sym:>10}{len(a):>8}{len(b):>8}{same:>8}{oo:>8}{nn:>8}")
        for z in sorted(a - b):
            diffs.append((sym, "구only", z))
        for z in sorted(b - a):
            diffs.append((sym, "신only", z))
    print("-" * 78)
    print(f"{'합계':>10}{tot_s+tot_o:>8}{tot_s+tot_n:>8}{tot_s:>8}{tot_o:>8}{tot_n:>8}")
    if diffs:
        print(f"\n=== 차이 {len(diffs)}건 ===")
        for sym, w, z in diffs:
            print(f"  {sym:9} {w:7} side={z[0]:5} entry={z[1]} sl={z[2]}")
    print(f"\n=== 판정 ===")
    print(f"  갭: 구 {g_old}개 → 신 {g_new}개")
    if not diffs:
        print("  ✅ 무장존 비트동일 — 갭수정이 진입판정을 바꾸지 않음 (안전 배포 가능)")
    else:
        print(f"  ⚠️ 무장존 차이 {len(diffs)}건 — 갭이 실제로 판정에 영향을 주고 있었음. 위 목록 검토 필요")
