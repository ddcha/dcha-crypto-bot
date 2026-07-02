from __future__ import annotations
"""
룩어헤드 free 라이브 신호 생성기 — smc_stage4d 엔진(백테스트와 동일) + v4 3중게이트.
각 심볼의 최근 H4/H1 캔들을 받아, ★막 마감된 봉(최신)에서 v4 진입이 트리거되는지 판정.
백테스트 candidate 생성은 진입 후 시뮬까지 하는데, 최신봉 후보는 미래봉이 없어 close_at_end 로 나옴 →
그 후보(entry_idx==마지막봉)를 '지금 진입 신호'로 해석. 게이트/원자/risk는 백테스트와 동일 규칙.
"""
import os, json
import numpy as np, pandas as pd

_RULES = None; _ATOMSETS = None; _RISK = None; _BTS = None; _BDIST = None; _ORIG = None; _READY = False
_LAST_TAGS = {}   # entry_idx -> 원자 tags (attribution 용, gate가 후보에 원자 안 저장하므로 캐시)


def _setup(cfg):
    for k, v in cfg.ENGINE_ENV.items():
        os.environ.setdefault(k, v)
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    import smc_stage4d.filters as F
    F.REG_VOL_PCTL = 0.85; F.BROAD_FVG_SIZE_ATR = 0.0


def _amatch(getter, a):
    return (not bool(getter(a[1:]))) if a.startswith("~") else bool(getter(a))


def attribute_setup(getter, zone, side):
    """진입 원자 tags + btc_zone + side 로 매칭되는 v4 규칙의 setup(키 앞부분) 반환."""
    matched = [(i, ru["key"], len(ru["atoms"])) for i, ru in enumerate(_RULES)
               if ru["btc_zone"] == zone and ru["side"] == side and all(_amatch(getter, at) for at in ru["atoms"])]
    if not matched:
        return None
    key = sorted(matched, key=lambda x: (-x[2], x[0]))[0][1]
    return key.split("||")[0]


def _btc_zone(ts):
    p = int(np.searchsorted(_BTS, ts, side="left")) - 1
    if p < 0 or np.isnan(_BDIST[p]):
        return None
    bd = _BDIST[p]
    return "down" if bd < -1 else ("range" if bd <= 1 else "up")


def _wrap(*a, **kw):
    tags = _ORIG(*a, **kw)
    try:
        df = kw["df_struct"]; ei = int(kw["entry_idx"]); side = kw["side"]
        ts = df["timestamp"].values[min(ei + 1, len(df) - 1)]
        z = _btc_zone(ts)
        if z is not None:
            tags["__zone_" + z] = True
        tags["__side_" + side] = True
        _LAST_TAGS[(ei, side)] = dict(tags)   # ★attribution 용 태그 캐시
    except Exception:
        pass
    return tags


def init(cfg):
    """1회 초기화 — 규칙/risk테이블 로드 + 게이트 wrapper 설치."""
    global _RULES, _ATOMSETS, _RISK, _ORIG, _READY
    _setup(cfg)
    _RULES = json.load(open(cfg.RULES_JSON, encoding="utf-8"))
    _ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in _RULES]
    _RISK = json.load(open(cfg.COMBO_RISK_TABLE, encoding="utf-8"))["combos"]
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    _ORIG = Fm.compute_trade_tags
    Fm.compute_trade_tags = _wrap; sim.compute_trade_tags = _wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    _READY = True


def set_btc_regime(btc_h4: pd.DataFrame):
    """BTC h4 로 btc_zone 배열 갱신 (ma10/ma30). 매 루프 최신화."""
    global _BTS, _BDIST
    b = btc_h4.sort_values("timestamp").reset_index(drop=True)
    ma10 = b["close"].rolling(10).mean(); ma30 = b["close"].rolling(30).mean()
    _BTS = b["timestamp"].values; _BDIST = ((ma10 - ma30) / ma30 * 100.0).values


def _pad_forward(df, n, step_h):
    """flat 더미봉 패딩 — 마지막 close 반복, 미래시각. gen 시뮬 완료용(진입판정은 실데이터만 씀=룩어헤드X)."""
    last = df.iloc[-1]; rows = []
    for k in range(1, n + 1):
        rows.append({"timestamp": last["timestamp"] + pd.Timedelta(hours=step_h * k),
                     "open": last["close"], "high": last["close"], "low": last["close"], "close": last["close"], "volume": 0.0})
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def get_live_signal(symbol: str, df_h4: pd.DataFrame, df_h1: pd.DataFrame, cfg) -> dict:
    """★막 마감된 최신봉에서 v4 진입신호 판정. 반환: should_enter/side/entry/sl/setup/btc_zone/risk_pct/signal_time.
    구현: 캔들 뒤에 flat 더미봉 패딩 → gen 이 현재봉 후보 방출 → entry_time==실제마지막봉 인 후보가 지금 신호."""
    if not _READY:
        return {"should_enter": False, "reason": "not_initialized"}
    if len(df_h4) < 260 or len(df_h1) < 420:
        return {"should_enter": False, "reason": "not_enough_data", "h4": len(df_h4), "h1": len(df_h1)}
    import smc_stage4d.simulation as sim
    from smc_stage4d.structures import apply_indicators_and_build
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    real_last_ts = pd.Timestamp(df_h4["timestamp"].iloc[-1])       # 실제 마지막(막 마감된) 봉
    h4p = _pad_forward(df_h4.copy(), 30, 4); h1p = _pad_forward(df_h1.copy(), 120, 1)
    _LAST_TAGS.clear()
    prepared = apply_indicators_and_build({"symbol": symbol, "df_raw": h4p, "df_h1_raw": h1p})
    cand = sim.generate_candidates_from_prepared(prepared)["candidates"]
    if cand is None or len(cand) == 0:
        return {"should_enter": False, "reason": "no_candidate"}
    cand = cand.copy(); cand["entry_time"] = pd.to_datetime(cand["entry_time"], utc=True)
    fresh = cand[cand["entry_time"] == real_last_ts]               # ★막 마감봉에서 트리거된 진입만
    if len(fresh) == 0:
        return {"should_enter": False, "reason": "no_fresh_signal", "last_bar": str(real_last_ts)}
    row = fresh.iloc[-1]
    side = str(row["side"]); ent = float(row["entry"]); sl = float(row["sl"])
    # btc_zone: gate가 쓴 것과 동일 규칙(entry봉+1의 직전 BTC봉, strict<). BTC배열은 실데이터까지만.
    ts = np.datetime64((real_last_ts + pd.Timedelta(hours=4)).tz_convert("UTC").tz_localize(None))
    zone = _btc_zone(ts)
    ei = int(row["entry_idx"])   # 원자는 신호봉(ei-1)에서 계산됨(HONEST_STAGE=5)
    tags = _LAST_TAGS.get((ei - 1, side)) or _LAST_TAGS.get((ei, side)) or {}
    getter = lambda a: bool(tags.get(a, False))
    setup = attribute_setup(getter, zone, side)
    if setup is None:
        return {"should_enter": False, "reason": "no_rule_match", "zone": zone, "side": side}
    info = _RISK.get(setup, {"applied_risk_pct": 0.0})
    risk_pct = float(info.get("applied_risk_pct", 0.0))
    if risk_pct <= 0:
        return {"should_enter": False, "reason": "combo_risk_zero_or_removed", "setup": setup}
    risk_pct = min(risk_pct, cfg.HARD_MAX_RISK_PCT)   # ★소표본 120% 방지 하드캡
    return {"should_enter": True, "symbol": symbol, "side": side, "entry": ent, "sl": sl,
            "setup": setup, "btc_zone": zone, "risk_pct": risk_pct,
            "signal_time": pd.Timestamp(row["entry_time"]).isoformat(), "entry_idx": int(row["entry_idx"])}
