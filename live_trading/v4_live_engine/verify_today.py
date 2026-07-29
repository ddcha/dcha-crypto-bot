"""오늘(기본 07-06) 9코인 백테 거래 전체를 뽑아 라이브 거래와 대조(양방향 파리티).
   - prepared(구조체) pickle 캐시 → 재실행 시 구조빌드 스킵(gen 만 재실행).
   - 워커규약(keep='first', limit=200) 데이터 조립.
   - 백테 오늘거래 ↔ 라이브 오늘거래(trade_journal + managed_positions) 대조.
   사용: python verify_today.py [YYYY-MM-DD] [--rebuild]
"""
import os, sys, json, pickle, csv
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
    os.environ.pop(_k, None)
import urllib.request
import numpy as np
import pandas as pd
import smc_stage4d.filters as Fm
import smc_stage4d.simulation as sim
from smc_stage4d.structures import apply_indicators_and_build
Fm.REG_VOL_PCTL = 0.85; Fm.BROAD_FVG_SIZE_ATR = 0.0

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT", "ADAUSDT"]
DAY = sys.argv[1] if (len(sys.argv) > 1 and sys.argv[1].startswith("2026")) else "2026-07-06"
REBUILD = "--rebuild" in sys.argv
PREP_CACHE = "prepared_cache_today.pkl"


def bybit_klines(symbol, interval, limit=200):
    u = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
    d = json.load(urllib.request.urlopen(u, timeout=20))["result"]["list"]
    return pd.DataFrame([{"timestamp": pd.to_datetime(int(r[0]), unit="ms", utc=True), "open": float(r[1]),
        "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in d]).sort_values("timestamp").reset_index(drop=True)


def build(sym, tf, iv):   # ★워커 규약: keep='first', limit=200
    seed = pd.read_parquet(f"data_cache/{sym}_{tf}.parquet"); seed["timestamp"] = pd.to_datetime(seed["timestamp"], utc=True)
    rec = bybit_klines(sym, iv, 200)
    return pd.concat([seed, rec]).drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True)


# BTC zone arrays
btc = build("BTCUSDT", "4h", "240")
_BTS = btc["timestamp"].values
_BDIST = ((btc["close"].rolling(10).mean() - btc["close"].rolling(30).mean()) / btc["close"].rolling(30).mean() * 100.0).values


def _zone(ts):
    p = int(np.searchsorted(_BTS, ts, side="left")) - 1
    if p < 0 or np.isnan(_BDIST[p]):
        return None
    bd = _BDIST[p]
    return "down" if bd < -1 else ("range" if bd <= 1 else "up")


rules = json.load(open("setups_btc_triple_a3v4.json", encoding="utf-8"))
_ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in rules]

# ── ★라이브 오버레이 (v6.1 확정 프레임) ──
# v6.1_backtest_package/README.md: "진입 = v4 42룰 + 만기 36h 컷 + 0% combo 차단 (라이브 진입 프레임)"
# 이 두 게이트가 없으면 verify 가 라이브보다 permissive 해져 false '라이브미진입' 경고를 낸다.
EXPH = 36.0                                                  # 라이브 _EXPIRY_BLOCK_HOURS
_RISK_TABLE = json.load(open("combo_risk_table.json", encoding="utf-8"))["combos"]


def combo_active(setup_key):
    """0%combo 차단 (라이브 strategy_engine.get_armed_zones 와 동일 판정)."""
    info = _RISK_TABLE.get(setup_key)
    return info is not None and float(info.get("applied_risk_pct", 0.0)) > 0


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


def _amatch(g, a):
    return (not bool(g(a[1:]))) if a.startswith("~") else bool(g(a))


def attribute_setup(tags, z, side):
    """42규칙 귀속 (라이브 _attribute_setup 동일: 원자수 많은 규칙 우선)."""
    m = [(i, ru["key"], len(ru["atoms"])) for i, ru in enumerate(rules)
         if ru["btc_zone"] == z and ru["side"] == side
         and all(_amatch(lambda a: bool(tags.get(a, False)), at) for at in ru["atoms"])]
    return sorted(m, key=lambda x: (-x[2], x[0]))[0][1].split("||")[0] if m else ""


# ★원자 태그는 후보 DataFrame 에 없다(컬럼 부재) — compute_trade_tags 호출 시점에 캡처해야 한다.
#   키 = (신호봉 idx, side). 후보의 entry_idx 는 터치봉(=신호봉+1) 이므로 조회 시 -1 (off-by-one 주의).
#   심볼 간 idx 충돌 방지를 위해 심볼별 gen 직전에 clear() 한다.
_TAGS = {}
_ORIG = Fm.compute_trade_tags
def _wrap(*a, **kw):
    tags = _ORIG(*a, **kw)
    try:
        df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
        z = _zone(df["timestamp"].values[min(ei + 1, len(df) - 1)])
        if z is not None:
            tags["__zone_" + z] = True
        tags["__side_" + side] = True
        _TAGS[(ei, side)] = dict(tags)
    except Exception:
        pass
    return tags
Fm.compute_trade_tags = _wrap; sim.compute_trade_tags = _wrap
sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS

# prepared 캐시 (구조빌드 스킵용)
prepared_all = {}
if os.path.exists(PREP_CACHE) and not REBUILD:
    prepared_all = pickle.load(open(PREP_CACHE, "rb"))
    print(f"[cache] prepared 캐시 로드 ({len(prepared_all)}심볼)")

DAY_START = pd.Timestamp(DAY, tz="UTC"); DAY_END = DAY_START + pd.Timedelta(days=1)

# Phase 1: prepared(구조체) 빌드/로드 — 증분 pickle 저장(크래시 내성)
for sym in SYMBOLS:
    if sym not in prepared_all:
        h4 = build(sym, "4h", "240"); h1 = build(sym, "1h", "60")
        prepared_all[sym] = apply_indicators_and_build({"symbol": sym, "df_raw": h4, "df_h1_raw": h1})
        pickle.dump(prepared_all, open(PREP_CACHE, "wb"))   # ★증분 저장
        print(f"[cache] {sym} prepared 빌드·저장")

# Phase 2: gen + 오늘 필터 + ★라이브 오버레이(만기36h컷·0%차단)
bt = []; blocked = []
for sym in SYMBOLS:
    _TAGS.clear()                                            # ★심볼별 idx 충돌 방지
    cand = sim.generate_candidates_from_prepared(prepared_all[sym])["candidates"]
    if cand is None or len(cand) == 0:
        continue
    cand = cand.copy(); cand["entry_time"] = pd.to_datetime(cand["entry_time"], utc=True)
    day = cand[(cand["entry_time"] >= DAY_START) & (cand["entry_time"] < DAY_END)].copy()
    for _, row in day.iterrows():
        side = str(row["side"])
        tags = _TAGS.get((int(row["entry_idx"]) - 1, side), {})   # ★-1 = 신호봉
        z = next((k[len("__zone_"):] for k in ("__zone_up", "__zone_range", "__zone_down") if tags.get(k)), None)
        setup = attribute_setup(tags, z, side)
        rec = {"symbol": sym, "signal_ts": str(row["entry_time"]), "side": side,
               "entry": round(float(row["entry"]), 6), "sl": round(float(row["sl"]), 6),
               "exit_reason": row.get("exit_reason", ""), "r": round(float(row.get("r_multiple", 0)), 2),
               "setup": setup, "btc_zone": z}
        hrs = hours_to_expiry(row["entry_time"])
        if hrs <= EXPH:
            rec["block"] = f"만기컷({hrs:.1f}h<={EXPH:.0f})"; blocked.append(rec); continue
        if not setup:
            rec["block"] = "규칙미매칭"; blocked.append(rec); continue
        if not combo_active(setup):
            rec["block"] = f"0%차단({setup})"; blocked.append(rec); continue
        bt.append(rec)

# 라이브 오늘 거래 (저널 + 열린포지션)
live = {}
try:
    for x in csv.DictReader(open("logs/trade_journal.csv", encoding="utf-8-sig")):
        ts = x.get("signal_ts", "")
        if ts.startswith(DAY):
            live[(x["symbol"], ts[:16])] = {"side": x.get("side_raw", x.get("side")), "entry": x.get("entry_price"), "status": x.get("status")}
except Exception:
    pass

def _match(sym, side, entry, cand_list):
    """★존 기준 매칭 (타임스탬프 아닌 심볼+방향+진입가±0.3%). 라이브 signal_ts(형성봉)와
       백테 entry_time(터치봉)이 달라도 같은 존이면 매칭."""
    side_l = "long" if str(side).lower() in ("buy", "long") else "short"
    try:
        e = float(entry)
    except (TypeError, ValueError):
        return None
    for t in cand_list:
        t_side = "long" if str(t["side"]).lower() in ("buy", "long") else "short"
        if t["symbol"] == sym and t_side == side_l and abs(t["entry"] - e) / e < 0.003:
            return t
    return None


live_list = [{"symbol": s, "signal_ts": ts, "side": v["side"], "entry": v["entry"], "status": v["status"]}
             for (s, ts), v in live.items()]

print(f"\n{'='*80}\n=== {DAY} 백테 거래 (9코인, 워커규약 keep=first, ★라이브 오버레이 적용) : {len(bt)}건 ===")
for t in sorted(bt, key=lambda x: x["signal_ts"]):
    lm = _match(t["symbol"], t["side"], t["entry"], [dict(x, entry=float(x["entry"]) if x["entry"] else 0) for x in live_list])
    live_has = "✅라이브도잡음" if lm else "⚠️라이브미진입(엔진기동전/미터치)"
    print(f"  {t['signal_ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']} sl={t['sl']} exit={t['exit_reason']} R={t['r']}  → {live_has}")

if blocked:
    print(f"\n=== 오버레이로 차단된 후보 (백테·라이브 양쪽 미진입이 정상) : {len(blocked)}건 ===")
    for t in sorted(blocked, key=lambda x: x["signal_ts"]):
        print(f"  {t['signal_ts'][:16]} {t['symbol']:9} {t['side']:5} entry={t['entry']} sl={t['sl']}  → 🚫{t['block']}")

print(f"\n=== 라이브 {DAY} 거래 : {len(live_list)}건 ===")
missing = []
for lv in sorted(live_list, key=lambda x: x["signal_ts"]):
    bm = _match(lv["symbol"], lv["side"], lv["entry"], bt)
    if bm:
        print(f"  {lv['signal_ts'][:16]} {lv['symbol']:9} {lv['side']} entry={lv['entry']}  → ✅백테도있음(백테존 entry={bm['entry']} @ {bm['signal_ts'][:16]})")
    else:
        print(f"  {lv['signal_ts'][:16]} {lv['symbol']:9} {lv['side']} entry={lv['entry']}  → ❌백테에없음(조사필요!)")
        missing.append((lv["symbol"], lv["signal_ts"]))

print(f"\n=== 판정 (존 기준 매칭) ===")
if missing:
    print(f"  ❌ 라이브에 있는데 백테에 없는 거래: {missing} — 파리티 위반, 조사 필요")
else:
    print(f"  ✅ 라이브 오늘거래 {len(live_list)}건 전부 백테에 동일 존으로 존재 (라이브 ⊆ 백테)")
