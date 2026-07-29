# -*- coding: utf-8 -*-
"""[파리티 전기간 스윕] 라이브 기동일~오늘 전 구간을 한 번의 후보생성으로 양방향 대조.

   verify_today.py 는 하루당 gen 을 통째로 재실행해 24일이면 2시간이 걸린다.
   이 도구는 심볼별 gen 을 1회만(병렬) 돌리고 전 기간을 평가한다.

   - 데이터: 시드 + 거래소 페이지네이션 = **갭 없음** (fix/live-h1-gap 이후 라이브와 동일 조립)
   - 진입프레임: 42룰 union + 만기36h컷 + 0%combo차단 (v6.1 확정 = 라이브 오버레이)
   - 원자귀속: compute_trade_tags 캡처, 조회 key = entry_idx-1 (후보=터치봉, 태그=신호봉)
   - 양방향: 라이브⊄백테(유령진입) / 백테⊄라이브(미진입) 를 모두 보고

   실행: python verify_range.py [--start 2026-07-05] [--end 2026-07-29]
"""
import os, sys, json, csv, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT", "ADAUSDT"]
EXPH = 36.0
URL = "https://api.bybit.com/v5/market/kline"
IMAP = {"4h": "240", "1h": "60"}


def _env():
    os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
    os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    for k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
        os.environ.pop(k, None)


_env()
import numpy as np
import pandas as pd

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
    for a in range(5):
        try:
            return _sess().get(URL, params=p, timeout=25).json().get("result", {}).get("list", [])
        except Exception:
            time.sleep(1.0 + a)
    return []


def build(sym, tf):
    """★갭 없는 조립: 시드 끝(since)까지 페이지네이션 (수정된 make_live_loader 와 동일)."""
    seed = pd.read_parquet(os.path.join(HERE, "data_cache", f"{sym}_{tf}.parquet"))
    seed["timestamp"] = pd.to_datetime(seed["timestamp"], utc=True)
    since = int(pd.Timestamp(seed["timestamp"].max()).value // 10 ** 6)
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
    rec = pd.DataFrame([{"timestamp": pd.to_datetime(int(x[0]), unit="ms", utc=True),
                         "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                         "close": float(x[4]), "volume": float(x[5])}
                        for x in items if int(x[0]) >= since])
    out = pd.concat([seed, rec], ignore_index=True).drop_duplicates("timestamp", keep="first") \
            .sort_values("timestamp").reset_index(drop=True)
    return out


def _monthly_expiries():
    days = pd.date_range("2022-01-01", "2028-12-31", freq="D", tz="UTC")
    last = {}
    for d in days:
        if d.weekday() == 4:
            last[(d.year, d.month)] = d
    return pd.DatetimeIndex(sorted(v.replace(hour=8) for v in last.values())).tz_localize(None).values


_MEXP = _monthly_expiries()


def hours_to_expiry(ts):
    et = np.datetime64(pd.Timestamp(ts).tz_convert("UTC").tz_localize(None))
    nxt = _MEXP[min(int(np.searchsorted(_MEXP, et, "left")), len(_MEXP) - 1)]
    return float((nxt - et) / np.timedelta64(1, "h"))


def _worker(payload):
    """심볼 1개: 데이터조립 → prepared → gen → 오버레이 귀속. (spawn 워커에서 실행)"""
    sym, day_start, day_end = payload
    _env()
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    from smc_stage4d.structures import apply_indicators_and_build
    Fm.REG_VOL_PCTL = 0.85; Fm.BROAD_FVG_SIZE_ATR = 0.0

    btc = build("BTCUSDT", "4h")
    BTS = btc["timestamp"].values
    BDIST = ((btc["close"].rolling(10).mean() - btc["close"].rolling(30).mean())
             / btc["close"].rolling(30).mean() * 100.0).values

    def zone(ts):
        p = int(np.searchsorted(BTS, ts, "left")) - 1
        if p < 0 or np.isnan(BDIST[p]):
            return None
        bd = BDIST[p]
        return "down" if bd < -1 else ("range" if bd <= 1 else "up")

    rules = json.load(open(os.path.join(HERE, "setups_btc_triple_a3v4.json"), encoding="utf-8"))
    ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in rules]
    RISK = json.load(open(os.path.join(HERE, "combo_risk_table.json"), encoding="utf-8"))["combos"]
    TAGS = {}
    ORIG = Fm.compute_trade_tags

    def wrap(*a, **kw):
        tags = ORIG(*a, **kw)
        try:
            df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
            z = zone(df["timestamp"].values[min(ei + 1, len(df) - 1)])
            if z is not None:
                tags["__zone_" + z] = True
            tags["__side_" + side] = True
            TAGS[(ei, side)] = dict(tags)
        except Exception:
            pass
        return tags

    Fm.compute_trade_tags = wrap; sim.compute_trade_tags = wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = ATOMSETS

    prep = apply_indicators_and_build({"symbol": sym, "df_raw": build(sym, "4h"), "df_h1_raw": build(sym, "1h")})
    cand = sim.generate_candidates_from_prepared(prep)["candidates"]
    if cand is None or len(cand) == 0:
        return sym, []
    cand = cand.copy(); cand["entry_time"] = pd.to_datetime(cand["entry_time"], utc=True)
    day = cand[(cand["entry_time"] >= day_start) & (cand["entry_time"] < day_end)]

    def amatch(g, a):
        return (not bool(g(a[1:]))) if a.startswith("~") else bool(g(a))

    out = []
    for _, r in day.iterrows():
        side = str(r["side"])
        tags = TAGS.get((int(r["entry_idx"]) - 1, side), {})
        z = next((k[len("__zone_"):] for k in ("__zone_up", "__zone_range", "__zone_down") if tags.get(k)), None)
        m = [(i, ru["key"], len(ru["atoms"])) for i, ru in enumerate(rules)
             if ru["btc_zone"] == z and ru["side"] == side
             and all(amatch(lambda a: bool(tags.get(a, False)), at) for at in ru["atoms"])]
        setup = sorted(m, key=lambda x: (-x[2], x[0]))[0][1].split("||")[0] if m else ""
        hrs = hours_to_expiry(r["entry_time"])
        blk = ""
        if hrs <= EXPH:
            blk = f"만기컷({hrs:.1f}h)"
        elif not setup:
            blk = "규칙미매칭"
        elif float(RISK.get(setup, {}).get("applied_risk_pct", 0.0)) <= 0:
            blk = f"0%차단({setup})"
        out.append({"symbol": sym, "ts": str(r["entry_time"]), "side": side,
                    "entry": round(float(r["entry"]), 8), "sl": round(float(r["sl"]), 8),
                    "setup": setup, "block": blk,
                    "r": round(float(r.get("r_multiple", 0)), 2),
                    "exit": str(r.get("exit_reason", ""))})
    return sym, out


def load_live(day_start, day_end):
    live = []
    try:
        for x in csv.DictReader(open(os.path.join(HERE, "logs", "trade_journal.csv"), encoding="utf-8-sig")):
            ts = x.get("signal_ts", "")
            if not ts:
                continue
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            if day_start <= t < day_end:
                live.append({"symbol": x["symbol"], "ts": str(t), "side": x.get("side_raw", x.get("side")),
                             "entry": float(x["entry_price"]) if x.get("entry_price") else 0.0,
                             "status": x.get("status", "")})
    except Exception as e:
        print(f"[warn] 저널 로드 실패: {e}")
    return live


def _sd(s):
    return "long" if str(s).lower() in ("buy", "long") else "short"


def match(rec, pool):
    """존 기준: 심볼+방향+진입가 ±0.3%."""
    e = float(rec["entry"])
    if e <= 0:
        return None
    for t in pool:
        if t["symbol"] == rec["symbol"] and _sd(t["side"]) == _sd(rec["side"]) \
           and abs(float(t["entry"]) - e) / e < 0.003:
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-05")
    ap.add_argument("--end", default=None, help="미포함 상한 (기본: 내일)")
    a = ap.parse_args()
    ds = pd.Timestamp(a.start, tz="UTC")
    de = pd.Timestamp(a.end, tz="UTC") if a.end else (pd.Timestamp.utcnow().normalize().tz_localize(None).tz_localize("UTC") + pd.Timedelta(days=1))

    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(pyw):
        try:
            ctx.set_executable(pyw)
        except Exception:
            pass
    t0 = time.time()
    print(f"=== 파리티 전기간 스윕 {ds.date()} ~ {(de - pd.Timedelta(days=1)).date()} (9심볼, 갭없는 조립) ===", flush=True)
    bt = []
    with ctx.Pool(processes=min(9, max(1, (os.cpu_count() or 2)))) as pool:
        for sym, rows in pool.imap_unordered(_worker, [(s, ds, de) for s in SYMBOLS]):
            bt.extend(rows)
            print(f"  {sym}: 후보 {len(rows)}건 ({time.time()-t0:.0f}s)", flush=True)

    live = load_live(ds, de)
    passed = [t for t in bt if not t["block"]]
    blocked = [t for t in bt if t["block"]]

    print(f"\n{'='*96}")
    print(f"백테 진입 {len(passed)}건 (오버레이 차단 {len(blocked)}건 별도) | 라이브 진입 {len(live)}건")
    print("=" * 96)

    print(f"\n=== ① 백테 진입 → 라이브 대조 (미진입 = 놓친 거래) ===")
    miss = []
    for t in sorted(passed, key=lambda x: x["ts"]):
        lm = match(t, live)
        mk = "✅라이브진입" if lm else "❌라이브미진입"
        if not lm:
            miss.append(t)
        print(f"  {t['ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']:<12} sl={t['sl']:<12} R={t['r']:>6}  → {mk}")

    print(f"\n=== ② 라이브 진입 → 백테 대조 (유령 = 백테에 없는 진입) ===")
    ghost = []
    for lv in sorted(live, key=lambda x: x["ts"]):
        bm = match(lv, passed)
        if bm:
            print(f"  {lv['ts'][:16]} {lv['symbol']:9} {lv['side']:5} entry={lv['entry']:<12}  → ✅백테존 {bm['entry']}")
        else:
            bb = match(lv, blocked)
            tag = f"❌백테에없음" + (f" (오버레이차단후보와 일치: {bb['block']})" if bb else "")
            ghost.append(lv)
            print(f"  {lv['ts'][:16]} {lv['symbol']:9} {lv['side']:5} entry={lv['entry']:<12}  → {tag}")

    if blocked:
        print(f"\n=== ③ 오버레이 차단 후보 {len(blocked)}건 (양쪽 미진입이 정상) ===")
        for t in sorted(blocked, key=lambda x: x["ts"]):
            print(f"  {t['ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']:<12} → 🚫{t['block']}")

    print(f"\n{'='*96}\n=== 판정 ===")
    print(f"  백테 진입 {len(passed)} / 라이브 진입 {len(live)}")
    print(f"  ❌ 미진입(백테O 라이브X): {len(miss)}건")
    for t in miss:
        print(f"       {t['ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']} R={t['r']}")
    print(f"  ❌ 유령(라이브O 백테X): {len(ghost)}건")
    for t in ghost:
        print(f"       {t['ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']}")
    if not miss and not ghost:
        print("\n  ✅ 완전일치 — 백테와 라이브 진입이 전 구간 동일")
    print(f"\n소요 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    main()
