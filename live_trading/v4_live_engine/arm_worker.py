#!/usr/bin/env python3
"""★배경 무장존 워커 — H4 마감마다 1회 실행. 심볼별 full-히스토리(2022~)로 무장존 계산 → armed_cache.json.
   메인 루프는 이 캐시를 읽어 존 경계에 지정가 거치(main 배선).
   계산: 9심볼 병렬(compute_parallel, spawn Pool) ~4.6분/H4. (구 순차 ~18분 → 4배, 파리티 비트동일.)
   경계 직후 이 시간만큼 신규존 미가용 = 재무장 블라인드 창. 병렬화로 18분→4.6분 축소.
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
            cache[sym] = _build_entry(sym, r, h4, t0)
            print(f"[arm] {sym}: 무장 {len(cache[sym]['armed'])}개 (raw {cache[sym]['n_raw']}) {cache[sym]['sec']}s")
        except Exception as e:
            cache[sym] = {"error": str(e), "armed": []}
            print(f"[arm] {sym} ERROR: {e}")
    return cache


def _build_entry(sym, r, h4, t0):
    return {"timestamp": r.get("timestamp"), "hours_to_expiry": r.get("hours_to_expiry"),
            "btc_zone": r.get("btc_zone"), "n_raw": r.get("n_raw", 0),
            "armed": r.get("armed", []), "reason": r.get("reason"),
            "h4_last": str(h4["timestamp"].iloc[-1]), "sec": round(time.time() - t0, 1)}


# ── 병렬 무장 계산 (심볼 독립·결정론적 → armed_cache 비트동일, 벽시계만 단축) ──
# set_btc_regime 은 전역상태라 워커별 1회 init. 데이터 로드(네트워크/IO)는 메인에서 수행 후
# CPU 무거운 get_armed_zones 만 워커로 넘긴다(live loader=exchange객체 는 pickle 불가하므로).
_WORKER_BTC_H4 = None


def _pool_init(btc_h4):
    global _WORKER_BTC_H4
    import strategy_engine as _SE
    _SE._init()
    _SE.set_btc_regime(btc_h4)
    _WORKER_BTC_H4 = btc_h4


def _arm_task(payload):
    sym, h4, h1, balance = payload
    import strategy_engine as _SE
    t0 = time.time()
    try:
        r = _SE.get_armed_zones(h4, h1, balance, RISK_PCT, FEE, MAXN, symbol=sym)
        return sym, _build_entry(sym, r, h4, t0)
    except Exception as e:
        return sym, {"error": str(e), "armed": []}


def compute_parallel(symbols=SYMBOLS, data_dir=DATA, balance=BALANCE, loader=_load, workers=None):
    """compute() 의 병렬판. 결과는 순차와 동일(심볼 독립). 워커는 CPU계산만, 데이터로드는 메인."""
    import multiprocessing as mp
    btc_h4 = loader("BTCUSDT", "4h", data_dir)   # 레짐용 + 워커 init 시드
    payloads = []
    for sym in symbols:                          # 로드는 메인(라이브 loader=exchange 는 여기서만 사용)
        h4 = loader(sym, "4h", data_dir)
        h1 = loader(sym, "1h", data_dir).tail(H1_RECENT).reset_index(drop=True)
        payloads.append((sym, h4, h1, balance))
    if workers is None:
        workers = int(os.environ.get("ARM_WORKERS", "0")) or min(len(symbols), max(1, (os.cpu_count() or 2)))
    cache = {}
    ctx = mp.get_context("spawn")               # Windows/파리티 일관 (fork 상속 부작용 배제)
    _pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")   # 워커 콘솔창 안뜨게(pythonw)
    if os.path.exists(_pyw):
        try: ctx.set_executable(_pyw)
        except Exception: pass
    with ctx.Pool(processes=workers, initializer=_pool_init, initargs=(btc_h4,)) as pool:
        for sym, entry in pool.imap_unordered(_arm_task, payloads):
            cache[sym] = entry
            if "error" in entry:
                print(f"[arm] {sym} ERROR: {entry['error']}")
            else:
                print(f"[arm] {sym}: 무장 {len(entry['armed'])}개 (raw {entry['n_raw']}) {entry['sec']}s [par]")
    return {s: cache[s] for s in symbols if s in cache}   # SYMBOLS 순서로 정렬(JSON 안정)


def write_cache(cache, out=OUT):
    payload = {"computed_at": pd.Timestamp.now("UTC").isoformat(), "config": "cap15_36h_backtrail_15mfill", "symbols": cache}
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, ensure_ascii=False, indent=1)
    os.replace(tmp, out)   # 원자적 교체 (메인이 읽는 중 깨짐 방지)


def make_live_loader(exchange, category):
    """★라이브 로더: data_cache(full 히스토리 시드) + 거래소 최신봉 merge → 항상 최신 full.

    ★2026-07-29 갭수정: 기존엔 limit=200 고정이라 1h 에서 8.3일치만 받아, 시드(data_cache)가
      낡을수록 시드끝~거래소최古 사이에 구멍이 생겼다(발견 시점 07-01~07-20, 19일 20시간).
      4h 는 200봉=33일이라 무증상이었다. 시드 끝을 since_ms 로 넘겨 페이지네이션으로 이어받아
      갭이 원천적으로 생기지 않게 한다(시드가 아무리 낡아도 자가치유). 1h 1000봉=41일 → 통상 1페이지.
    """
    from config import H4_INTERVAL, H1_INTERVAL
    imap = {"4h": H4_INTERVAL, "1h": H1_INTERVAL, "15m": "15", "1m": "1"}
    _step_h = {"4h": 4.0, "1h": 1.0, "15m": 0.25, "1m": 1.0 / 60.0}

    def loader(sym, tf, data_dir=DATA):
        base = _load(sym, tf, data_dir)
        iv = imap.get(tf, tf)
        recent = None
        try:
            since = int(pd.Timestamp(base["timestamp"].iloc[-1]).value // 10 ** 6) if len(base) else 0
            recent = exchange.get_full_klines_df(category=category, symbol=sym, interval=iv,
                                                 since_ms=since, max_pages=6)
        except Exception as e:
            print(f"[arm] {sym} {tf} 시드연결 fetch 실패, 최근200봉으로 폴백: {e}")
            try:
                recent = exchange.get_recent_klines_df(category=category, symbol=sym, interval=iv, limit=200)
            except Exception as e2:
                print(f"[arm] {sym} {tf} 최신봉 fetch 실패, data_cache 만 사용: {e2}")
                return base
        out = pd.concat([base, recent], ignore_index=True).drop_duplicates("timestamp") \
                .sort_values("timestamp").reset_index(drop=True)
        st = _step_h.get(tf)
        if st:                                                  # 갭 잔존 시 조용히 넘어가지 않고 경고
            d = out["timestamp"].diff()
            n = int((d > pd.Timedelta(hours=st * 1.5)).sum())
            if n:
                i = d.idxmax()
                print(f"[arm] ⚠️ {sym} {tf} 갭 {n}개 잔존 (최대 {out['timestamp'][i-1]} → {out['timestamp'][i]})")
        return out
    return loader


def _sleep_to_next_h4(margin_sec=90):
    """다음 H4 경계(00/04/08/12/16/20 UTC) + margin 까지 대기 (거래소 확정봉 반영 여유)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    nb = now.replace(minute=0, second=0, microsecond=0) + _dt.timedelta(hours=(4 - now.hour % 4))
    wait = (nb - now).total_seconds() + margin_sec
    print(f"[arm] 다음 H4 경계까지 {wait/60:.1f}분 대기 (다음 {nb.isoformat()})")
    time.sleep(max(30, wait))


def _run_once(syms, loader):
    t0 = time.time()
    _parallel = os.environ.get("ARM_PARALLEL", "1") != "0"
    if _parallel:
        try:
            cache = compute_parallel(syms, loader=loader)
        except Exception as e:
            import traceback; print(f"[arm] 병렬 실패, 순차 폴백: {e}\n{traceback.format_exc()}")
            cache = compute(syms, loader=loader)
    else:
        cache = compute(syms, loader=loader)
    write_cache(cache)
    tot = sum(len(v.get("armed", [])) for v in cache.values())
    took = time.time() - t0
    print(f"[arm] 완료: {len(syms)}심볼 무장 총 {tot}개 → {OUT} ({took:.0f}s)")
    # ★텔레그램 요약 (기존 telegram_utils, env 토큰 있을 때만)
    try:
        from telegram_utils import send_telegram_message, telegram_enabled
        if telegram_enabled():
            lines = [f"🎯 무장존 갱신 ({len(syms)}심볼, {took:.0f}s)"]
            for s in syms:
                v = cache.get(s, {}); arm = v.get("armed", [])
                if arm:
                    t = arm[0]
                    lines.append(f"• {s}: {len(arm)}개 | p0 {t['side']} {t['setup'][:22]} @{t['entry']:g} r{t['risk_pct_tier_adjusted']}%")
                elif v.get("reason"):
                    lines.append(f"• {s}: 0 ({v['reason']})")
                else:
                    lines.append(f"• {s}: 0")
            send_telegram_message("\n".join(lines))
    except Exception as _te:
        print(f"[arm] 텔레그램 알림 실패(무시): {_te}")


def _apply_panel_risk_settings():
    """컨트롤패널(live_settings/runtime_state)의 uniform_risk_pct·exit_scheme 을 env로 주입.
       strategy_engine 이 _UNIFORM_RISK_PCT·_EXIT_SCHEME 로 읽음. 없으면 기본(2%·v4청산)."""
    try:
        from settings_store import load_live_settings
        st = load_live_settings()
        pf = st.get("portfolio", {}) if isinstance(st, dict) else {}
        urp = pf.get("uniform_risk_pct")
        if urp is not None and float(urp) > 0:
            os.environ["UNIFORM_RISK_PCT"] = str(float(urp))
        es = pf.get("exit_scheme")
        if es:
            os.environ["EXIT_SCHEME"] = str(es).lower()
        print(f"[arm] 리스크설정: UNIFORM_RISK_PCT={os.environ.get('UNIFORM_RISK_PCT','(combo)')} EXIT_SCHEME={os.environ.get('EXIT_SCHEME','v4')}")
    except Exception as e:
        print(f"[arm] 패널 리스크설정 로드 실패(기본 사용): {e}")


def main():
    syms = SYMBOLS
    if "--syms" in sys.argv:
        syms = sys.argv[sys.argv.index("--syms") + 1].split(",")
    _apply_panel_risk_settings()
    loader = _load
    if "--live" in sys.argv:   # 거래소 최신봉 merge (data_cache 시드). klines=공개데이터.
        from config import CATEGORY
        from exchange_bybit import BybitExchange
        # ★main 과 동일 소스: 컨트롤패널(live_settings.json) 우선 → env 폴백. 모드(live/demo)도 패널 따름.
        from settings_store import load_live_settings, get_api_settings, get_mode
        _st = load_live_settings(); _api = get_api_settings(_st); _mode = get_mode(_st)

        def _sv(x):
            return (x or "").strip()
        if _mode == "live":
            key = _sv(_api.get("live_api_key")) or _sv(os.getenv("BYBIT_LIVE_API_KEY")) or _sv(os.getenv("BYBIT_API_KEY"))
            sec = _sv(_api.get("live_api_secret")) or _sv(os.getenv("BYBIT_LIVE_API_SECRET")) or _sv(os.getenv("BYBIT_API_SECRET"))
            use_demo = False
        else:
            key = _sv(_api.get("demo_api_key")) or _sv(os.getenv("BYBIT_DEMO_API_KEY")) or _sv(os.getenv("BYBIT_API_KEY"))
            sec = _sv(_api.get("demo_api_secret")) or _sv(os.getenv("BYBIT_DEMO_API_SECRET")) or _sv(os.getenv("BYBIT_API_SECRET"))
            use_demo = True
        if not key or not sec:
            print("[arm] API 키 없음(컨트롤패널 live_settings.json 또는 env) — data_cache 만으로 계산")
            loader = _load
        else:
            print(f"[arm] --live: {'DEMO' if use_demo else 'LIVE'} 모드 (컨트롤패널 설정 따름)")
            ex = BybitExchange(key, sec, use_demo=use_demo)
            loader = make_live_loader(ex, CATEGORY)
    if "--loop" in sys.argv:
        print("[arm] --loop: H4 경계마다 무장존 재계산")
        while True:
            try:
                _run_once(syms, loader)
            except Exception as e:
                import traceback; print(f"[arm] 사이클 오류: {e}\n{traceback.format_exc()}")
            _sleep_to_next_h4()
    else:
        _run_once(syms, loader)


if __name__ == "__main__":
    main()
