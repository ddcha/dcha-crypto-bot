from __future__ import annotations
"""
★ v4 어댑터 전략엔진 — 기존 main.py drop-in 교체.
   기존 Stage4K(룩어헤드 결함) 진입로직을 폐기하고, smc_stage4d(honest) + v4 3중게이트로 generate_entry_signal 제공.
   포지션관리/실행(main.py, control_panel 등)은 그대로 재사용.
   확정 전략 = v4 42규칙 + 만기컷(48h) + 24·25제거 + 전역 risk×1.2 + killer 3.5%캡.

   인터페이스(기존과 동일):
     generate_entry_signal(df_h4_raw, df_h1_raw, balance, risk_pct, fee_rate, max_notional_mult, ...)
     get_latest_balance_usdt(wallet_response)
     prepare_h4_dataframe / prepare_h1_dataframe / build_structures / evaluate_zones_at_current_time / RELAX_MIN_SCORE  (zone패널용 — legacy 재수출)
   신규:
     set_btc_regime(btc_h4_df)  ← main 이 루프마다 1회 호출 (btc_zone 계산용)
"""
import os, json
import numpy as np, pandas as pd

# zone패널/헬퍼는 검증된 legacy 그대로 재수출 (진입 로직 아님 — 룩어헤드 무관 표시용)
from strategy_engine_legacy import (
    prepare_h4_dataframe, prepare_h1_dataframe, build_structures,
    evaluate_zones_at_current_time, RELAX_MIN_SCORE, get_latest_balance_usdt,
)

# ── 확정 v4 파라미터 ──
_ENGINE_ENV = {"OB_MODE": "engulf", "DISP_ATR_MULT": "1.3", "USE_H1_REFINE": "1", "HONEST_STAGE": "5", "MIN_SCORE": "7.5"}
_G = 1.2; _EXPIRY_BLOCK_HOURS = 48; _HARD_MAX_RISK_PCT = 2.0
_HERE = os.path.dirname(os.path.abspath(__file__))
_RULES = None; _ATOMSETS = None; _RISK = None; _ORIG = None; _READY = False
_BTS = None; _BDIST = None; _LAST_TAGS = {}


def _monthly_expiries():
    days = pd.date_range("2022-01-01", "2028-12-31", freq="D", tz="UTC"); fri = [d for d in days if d.weekday() == 4]
    last = {}
    for f in fri:
        last[(f.year, f.month)] = f
    return pd.DatetimeIndex(sorted(v.replace(hour=8) for v in last.values())).tz_localize(None).values


_MEXP = _monthly_expiries()


def _hours_to_monthly_expiry(entry_ts) -> float:
    et = np.datetime64(pd.Timestamp(entry_ts).tz_convert("UTC").tz_localize(None))
    nxt = _MEXP[min(int(np.searchsorted(_MEXP, et, side="left")), len(_MEXP) - 1)]
    return float((nxt - et) / np.timedelta64(1, "h"))


def _amatch(getter, a):
    return (not bool(getter(a[1:]))) if a.startswith("~") else bool(getter(a))


def _attribute_setup(getter, zone, side):
    matched = [(i, r["key"], len(r["atoms"])) for i, r in enumerate(_RULES)
               if r["btc_zone"] == zone and r["side"] == side and all(_amatch(getter, at) for at in r["atoms"])]
    if not matched:
        return None
    return sorted(matched, key=lambda x: (-x[2], x[0]))[0][1].split("||")[0]


def _btc_zone(ts):
    if _BTS is None:
        return None
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
        _LAST_TAGS[(ei, side)] = dict(tags)
    except Exception:
        pass
    return tags


def _init():
    global _RULES, _ATOMSETS, _RISK, _ORIG, _READY
    if _READY:
        return
    for k, v in _ENGINE_ENV.items():
        os.environ.setdefault(k, v)
    os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
    import smc_stage4d.filters as Fm, smc_stage4d.simulation as sim
    Fm.REG_VOL_PCTL = 0.85; Fm.BROAD_FVG_SIZE_ATR = 0.0
    _RULES = json.load(open(os.path.join(_HERE, "setups_btc_triple_a3v4.json"), encoding="utf-8"))
    _ATOMSETS = [r["atoms"] + ["__zone_" + r["btc_zone"], "__side_" + r["side"]] for r in _RULES]
    _RISK = json.load(open(os.path.join(_HERE, "combo_risk_table.json"), encoding="utf-8"))["combos"]
    _ORIG = Fm.compute_trade_tags
    Fm.compute_trade_tags = _wrap; sim.compute_trade_tags = _wrap
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS
    _READY = True


def set_btc_regime(btc_h4: pd.DataFrame):
    """main 이 루프마다 1회 호출 — btc_zone(ma10/ma30) 계산용 배열 갱신."""
    global _BTS, _BDIST
    b = btc_h4[["timestamp", "close"]].copy()
    b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
    b = b.sort_values("timestamp").reset_index(drop=True)
    ma10 = b["close"].rolling(10).mean(); ma30 = b["close"].rolling(30).mean()
    _BTS = b["timestamp"].dt.tz_localize(None).values.astype("datetime64[ns]")
    _BDIST = ((ma10 - ma30) / ma30 * 100.0).values


def _pad(df, n, step_h):
    last = df.iloc[-1]; rows = [{"timestamp": last["timestamp"] + pd.Timedelta(hours=step_h * k),
                                 "open": last["close"], "high": last["close"], "low": last["close"], "close": last["close"], "volume": 0.0} for k in range(1, n + 1)]
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def generate_entry_signal(df_h4_raw, df_h1_raw, balance, risk_pct, fee_rate, max_notional_mult,
                          current_price=None, last_exit_time_iso=None, last_exit_side=None,
                          risk_multiplier=1.0, df_1m_raw=None, symbol=None):
    """★v4 진입신호 (룩어헤드 free). 반환 payload는 기존 main 계약과 호환."""
    _init()
    import smc_stage4d.simulation as sim
    from smc_stage4d.structures import apply_indicators_and_build
    from smc_stage4d.simulation import calc_position_size
    if len(df_h4_raw) < 260 or len(df_h1_raw) < 420:
        return {"should_enter": False, "reason": "not_enough_data", "h4_rows": len(df_h4_raw), "h1_rows": len(df_h1_raw)}
    df_h4 = df_h4_raw.copy(); df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"], utc=True)
    df_h1 = df_h1_raw.copy(); df_h1["timestamp"] = pd.to_datetime(df_h1["timestamp"], utc=True)
    df_h4 = df_h4.sort_values("timestamp").reset_index(drop=True); df_h1 = df_h1.sort_values("timestamp").reset_index(drop=True)
    real_last_ts = pd.Timestamp(df_h4["timestamp"].iloc[-1])
    sim.USE_COMBO_UNION = True; sim.COMBO_UNION_ATOMSETS = _ATOMSETS; _LAST_TAGS.clear()
    prepared = apply_indicators_and_build({"symbol": symbol or "SYM", "df_raw": _pad(df_h4, 30, 4), "df_h1_raw": _pad(df_h1, 120, 1)})
    cand = sim.generate_candidates_from_prepared(prepared)["candidates"]
    if cand is None or len(cand) == 0:
        return {"should_enter": False, "reason": "no_candidate"}
    cand = cand.copy(); cand["entry_time"] = pd.to_datetime(cand["entry_time"], utc=True)
    fresh = cand[cand["entry_time"] == real_last_ts]
    if len(fresh) == 0:
        return {"should_enter": False, "reason": "no_fresh_signal", "last_bar": str(real_last_ts)}
    row = fresh.iloc[-1]
    side = str(row["side"]); ent = float(row["entry"]); sl = float(row["sl"])
    hrs = _hours_to_monthly_expiry(real_last_ts)
    if hrs <= _EXPIRY_BLOCK_HOURS:
        return {"should_enter": False, "reason": "expiry_block", "hours_to_expiry": round(hrs, 1), "setup": None}
    ts_zone = np.datetime64((real_last_ts + pd.Timedelta(hours=4)).tz_convert("UTC").tz_localize(None))
    zone = _btc_zone(ts_zone)
    ei = int(row["entry_idx"])
    tags = _LAST_TAGS.get((ei - 1, side)) or _LAST_TAGS.get((ei, side)) or {}
    setup = _attribute_setup(lambda a: bool(tags.get(a, False)), zone, side)
    if setup is None:
        return {"should_enter": False, "reason": "no_rule_match", "zone": zone, "side": side}
    info = _RISK.get(setup, {"applied_risk_pct": 0.0})
    base_risk = float(info.get("applied_risk_pct", 0.0))
    if base_risk <= 0:
        return {"should_enter": False, "reason": "combo_removed_or_zero", "setup": setup}
    rm = float(risk_multiplier) if risk_multiplier and float(risk_multiplier) > 0 else 1.0
    final_risk = min(base_risk, _HARD_MAX_RISK_PCT) * rm     # ★소표본 하드캡 + 패널 배수
    qty, notional, _ = calc_position_size(balance, final_risk, ent, sl, fee_rate, max_notional_mult)
    if qty is None or qty <= 0:
        return {"should_enter": False, "reason": "position_size_zero", "setup": setup, "risk_pct": final_risk}
    plan = dict(row.get("tp_plan")) if isinstance(row.get("tp_plan"), dict) else None
    from smc_stage4d.simulation import get_tp_plan
    if plan is None:
        plan = get_tp_plan(bool(row.get("expansion_state", False)))
    return {
        "should_enter": True,
        "timestamp": str(real_last_ts),
        "h4_closed_index": ei,
        "side": "Buy" if side == "long" else "Sell",
        "position_side": side,
        "entry": ent, "base_entry": float(row.get("base_entry", ent)),
        "entry_refined": bool(row.get("entry_refined", False)),
        "refined_entry_px": float(row["refined_entry_px"]) if pd.notna(row.get("refined_entry_px")) else None,
        "refine_tag": str(row.get("refine_tag", "")),
        "sl": sl, "qty": float(qty), "notional": float(notional), "risk_per_unit": abs(ent - sl),
        "score": float(row.get("score", 0.0)), "base_score": float(row.get("base_score", 0.0)),
        "grade": str(row.get("grade", "C")), "run_potential": int(row.get("run_potential", 0)), "run_tags": [],
        "tp_plan_name": plan.get("name", "base"), "tp_plan": plan,
        "expansion_state": bool(row.get("expansion_state", False)),
        "setup": setup, "btc_zone": zone,
        # ── 기존 main 계약 호환용 필드 (v4는 tier/sentiment 미사용 → 중립) ──
        "tier": "V4", "tier_mult": 1.0, "tier_mult_raw": 1.0, "rp_action": "v4",
        "stage4j_mult": 1.0, "stage4j_label": "v4", "sentiment_mult": 1.0, "sentiment_label": "v4",
        "tier_pre_total": 0, "tier_sweep_count": 0, "tier_fvg_count": 0, "tier_ob_count": 0, "tier_wick_ratio_5": None,
        "risk_pct_base": float(base_risk), "risk_pct_tier_adjusted": float(final_risk),
        "reasons": [setup], "atoms_dict": {k: bool(v) for k, v in tags.items() if k.startswith("a_")},
        "hours_to_expiry": round(hrs, 1),
    }
