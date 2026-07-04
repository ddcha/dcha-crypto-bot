from __future__ import annotations

import os
import json
import math
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
import pandas as pd

from config import (
    CATEGORY,
    H4_INTERVAL,
    H1_INTERVAL,
    H4_LIMIT,
    H1_LIMIT,
    MAX_NOTIONAL_MULT,
    FEE_RATE,
    LOOP_SLEEP_SECONDS,
    EXIT_COOLDOWN_HOURS,
    TRAIL_MODE,
    # v2.2: Zone-Proximity Trigger
    USE_ZONE_PROXIMITY_TRIGGER,
    LIGHT_LOOP_SLEEP_SECONDS,
    ZONE_PROXIMITY_PCT,
    ZONE_CACHE_REFRESH_SECONDS,
)
from exchange_bybit import BybitExchange
from strategy_engine import generate_entry_signal, get_latest_balance_usdt, set_btc_regime as _v4_set_btc_regime
# v2.2: zone cache 빌드용
from strategy_engine import (
    prepare_h4_dataframe as _prepare_h4_for_zone,
    prepare_h1_dataframe as _prepare_h1_for_zone,
    build_structures as _build_structures_for_zone,
    evaluate_zones_at_current_time as _evaluate_zones_for_zone,
    RELAX_MIN_SCORE as _RELAX_MIN_SCORE_FOR_ZONE,
)
import pickle as _pickle_for_zone
from config import EXCLUDE_RECENT_H1_FOR_TIER as _EXCLUDE_RECENT_H1_FOR_ZONE
from state_store import (
    load_state,
    save_state,
    ensure_symbol_state,
    ensure_system_state,
    ensure_managed_positions,
    ensure_latest_open_positions,
    ensure_exchange_positions,
    ensure_engine_positions_view,
)
from settings_store import (
    load_live_settings,
    get_assets,
    get_portfolio_settings,
    get_protection_settings,
    get_execution_settings,
    get_api_settings,
    get_mode,
)
from log_store import log_system_event, log_trade_event, upsert_trade_journal
from telegram_utils import send_telegram_message


# ★ [PATCHED 2026-06-04] recovery_failed 알림 스로틀.
# trade_log 에 진입(order_filled) 기록이 없는 orphan 포지션은 매 루프 복구 실패하므로,
# 그대로 두면 rebuild 가 매 루프(2회) 1523행 recovery_failed 로그 + 텔레그램을 도배함
# (DOGE/BNB 가 5/31부터 초당 스팸 → trade_log.csv 초당 전체 재기록 → SIGKILL 시 잘림 유발).
# 같은 심볼은 INTERVAL 당 1회만 알림/로그 한다. 포지션 자체 처리(exchange_recovered_only 유지)는 그대로.
_RECOVERY_FAILED_NOTIFY_INTERVAL_SEC = 3600.0  # 심볼당 최대 1시간에 1번만 알림
_recovery_failed_last_notified: dict[str, float] = {}


def _should_notify_recovery_failed(symbol: str) -> bool:
    """같은 심볼의 recovery_failed 를 INTERVAL 안에서는 1회만 알리도록 게이트."""
    now = time.time()
    last = _recovery_failed_last_notified.get(symbol, 0.0)
    if now - last >= _RECOVERY_FAILED_NOTIFY_INTERVAL_SEC:
        _recovery_failed_last_notified[symbol] = now
        return True
    return False


def _clear_recovery_failed_notify(symbol: str) -> None:
    """포지션이 정상 복구/청산되면 스로틀 상태를 초기화해 다음 실패 시 즉시 알리도록."""
    _recovery_failed_last_notified.pop(symbol, None)


def print_title(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def pretty_print_json(title: str, data) -> None:
    print_title(title)
    try:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    except Exception:
        print(data)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None"):
            return default
        return float(value)
    except Exception:
        return default


def safe_api_call(func, label: str = "", retries: int = 3, delay_seconds: float = 2.0):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            print_title(f"API RETRY - {label or 'unknown'}")
            print(f"attempt={attempt}/{retries}")
            print(str(e))
            if attempt < retries:
                time.sleep(delay_seconds)
    raise last_error


def sanitize_secret_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip().strip('"').strip("'")
    if "=" in value:
        value = value.split("=", 1)[1].strip()
    return value


def resolve_api_credentials(settings: dict) -> tuple[str, str, bool, bool]:
    api_cfg = get_api_settings(settings)
    mode = get_mode(settings)

    demo_key = sanitize_secret_value(api_cfg.get("demo_api_key", ""))
    demo_secret = sanitize_secret_value(api_cfg.get("demo_api_secret", ""))
    live_key = sanitize_secret_value(api_cfg.get("live_api_key", ""))
    live_secret = sanitize_secret_value(api_cfg.get("live_api_secret", ""))

    env_key = sanitize_secret_value(os.getenv("BYBIT_API_KEY", ""))
    env_secret = sanitize_secret_value(os.getenv("BYBIT_API_SECRET", ""))

    env_demo_key = sanitize_secret_value(os.getenv("BYBIT_DEMO_API_KEY", ""))
    env_demo_secret = sanitize_secret_value(os.getenv("BYBIT_DEMO_API_SECRET", ""))
    env_live_key = sanitize_secret_value(os.getenv("BYBIT_LIVE_API_KEY", ""))
    env_live_secret = sanitize_secret_value(os.getenv("BYBIT_LIVE_API_SECRET", ""))

    if mode == "live":
        api_key = live_key or env_live_key or env_key
        api_secret = live_secret or env_live_secret or env_secret
        use_demo = False
        use_testnet = False
    else:
        api_key = demo_key or env_demo_key or env_key
        api_secret = demo_secret or env_demo_secret or env_secret
        use_demo = True
        use_testnet = False

    return api_key, api_secret, use_testnet, use_demo


def extract_open_positions_map(positions_response) -> dict:
    result = {}

    try:
        items = positions_response.get("result", {}).get("list", [])
        for item in items:
            symbol = item.get("symbol")
            if not symbol:
                continue

            size_val = safe_float(item.get("size", "0"), 0.0)
            side = str(item.get("side", ""))

            if size_val > 0:
                result[symbol] = {
                    "has_position": True,
                    "side": side,
                    "qty": size_val,
                    "raw": item,
                }
    except Exception:
        pass

    return result


def normalize_qty(qty: float, qty_step: float, min_order_qty: float, qty_decimals: int) -> float:
    if qty <= 0:
        return 0.0

    stepped = math.floor(qty / qty_step) * qty_step
    rounded = round(stepped, qty_decimals)

    if rounded < min_order_qty:
        return 0.0

    return rounded


def calc_total_open_risk_pct(open_positions_map: dict, assets: dict) -> float:
    total = 0.0
    for symbol, pos in open_positions_map.items():
        if not pos.get("has_position"):
            continue

        asset_cfg = assets.get(symbol)
        if not asset_cfg:
            continue

        total += float(asset_cfg.get("risk_pct", 0.0))
    return total


def count_open_positions(open_positions_map: dict) -> int:
    return sum(1 for _, pos in open_positions_map.items() if pos.get("has_position"))


def is_duplicate_signal(symbol_state: dict, signal_ts: str, signal_side: str) -> bool:
    return (
        symbol_state.get("last_order_signal_timestamp") == signal_ts
        and symbol_state.get("last_order_side") == signal_side
    )


def is_side_allowed(signal_side: str, asset_cfg: dict) -> bool:
    if signal_side == "Buy" and not asset_cfg.get("allow_long", True):
        return False
    if signal_side == "Sell" and not asset_cfg.get("allow_short", True):
        return False
    return True


def can_open_new_position(
    symbol: str,
    asset_cfg: dict,
    open_positions_map: dict,
    trading_enabled: bool,
    kill_switch: bool,
    assets: dict,
    max_open_positions: int,
) -> tuple[bool, str]:
    """
    합산 리스크 제한 제거됨 (사용자 결정 2026-04-22).
    이유: v1.9b 티어 매핑이 기본 risk × mult 로 들어가는 구조에서,
    합산 리스크 cap 이 걸리면 S 티어가 들어간 뒤 다른 포지션이 막힘.
    리스크 관리는 개별 자산 risk_pct 와 max_open_positions 로만.
    """
    if kill_switch:
        return False, "kill_switch_active"

    if not trading_enabled:
        return False, "trading_disabled"

    if not asset_cfg.get("enabled", False):
        return False, "asset_disabled"

    if symbol in open_positions_map and open_positions_map[symbol].get("has_position"):
        return False, "position_already_exists"

    current_open_positions = count_open_positions(open_positions_map)
    if current_open_positions >= max_open_positions:
        return False, "max_open_positions_reached"

    return True, "ok"


def handle_emergency_close_all(
    exchange: BybitExchange,
    category: str,
    open_positions_map: dict,
    system_state: dict,
    managed_positions: dict,
) -> None:
    if not system_state.get("emergency_close_all", False):
        return

    if not open_positions_map:
        print_title("EMERGENCY CLOSE ALL")
        print("열린 포지션 없음. emergency_close_all 플래그를 해제합니다.")
        log_system_event(
            event_type="emergency_close_all_no_positions",
            message="열린 포지션이 없어 close all 없이 종료",
        )
        system_state["last_emergency_close_all_at"] = utc_now_iso()
        system_state["emergency_close_all"] = False
        managed_positions.clear()
        return

    print_title("EMERGENCY CLOSE ALL")
    print("보유 포지션 전체 시장가 청산 시도")

    for symbol, pos in open_positions_map.items():
        if not pos.get("has_position"):
            continue

        side = pos.get("side", "")
        qty = float(pos.get("qty", 0.0))

        try:
            resp = exchange.close_position_market(
                category=category,
                symbol=symbol,
                side=side,
                qty=qty,
            )

            pretty_print_json(f"EMERGENCY CLOSE RESPONSE - {symbol}", resp)

            log_trade_event(
                event_type="emergency_close_submitted",
                symbol=symbol,
                side=side,
                qty=qty,
                reason="emergency_close_all",
                extra={"response": resp},
            )
            send_telegram_message(
                f"🚨 EMERGENCY CLOSE SUBMITTED\n"
                f"Symbol: {symbol}\n"
                f"Side: {side}\n"
                f"Qty: {qty}"
            )
        except Exception as e:
            log_system_event(
                event_type="emergency_close_error",
                symbol=symbol,
                message=str(e),
            )
            raise

    system_state["last_emergency_close_all_at"] = utc_now_iso()
    system_state["emergency_close_all"] = False
    managed_positions.clear()

    log_trade_event(
        event_type="emergency_close_all_completed",
        symbol="ALL",
        reason="emergency_close_all_completed",
    )
    send_telegram_message("🚨 EMERGENCY CLOSE ALL COMPLETED")


def calc_rr(side: str, entry_price: float, risk_per_unit: float, current_price: float) -> float:
    if risk_per_unit <= 0:
        return 0.0
    if side == "Buy":
        return (current_price - entry_price) / risk_per_unit
    return (entry_price - current_price) / risk_per_unit


def calc_risk_per_unit(side: str, entry_price: float | None, sl_price: float | None) -> float:
    if entry_price is None or sl_price is None:
        return 0.0
    if side == "Buy":
        return max(0.0, float(entry_price) - float(sl_price))
    return max(0.0, float(sl_price) - float(entry_price))


def calc_slippage_pct(side: str, expected_price: float | None, filled_price: float | None) -> float | None:
    if expected_price is None or filled_price is None:
        return None
    expected_price = float(expected_price)
    filled_price = float(filled_price)
    if expected_price <= 0:
        return None

    if side == "Buy":
        return ((filled_price - expected_price) / expected_price) * 100.0
    return ((expected_price - filled_price) / expected_price) * 100.0


def extract_avg_entry_price(raw: dict) -> float | None:
    if not raw:
        return None

    for key in ("avgPrice", "avgEntryPrice", "markPrice"):
        value = safe_float(raw.get(key), 0.0)
        if value > 0:
            return value
    return None


def get_signal_payload_for_symbol(state: dict, symbol: str) -> dict | None:
    symbols = state.get("symbols", {})
    sym = symbols.get(symbol, {})
    payload = sym.get("last_signal_payload")
    if isinstance(payload, dict):
        return payload
    return None


def recover_signal_plan_from_trade_log(
    symbol: str,
    actual_side: str,
    actual_entry: float,
    max_slippage_pct: float = 0.005,
) -> dict | None:
    """
    logs/trade_log.csv 에서 현재 포지션과 매칭되는 최근 order_filled 이벤트를 찾아
    signal_payload 형태로 재구성해 반환. 매칭 실패 시 None.

    매칭 조건 (AND):
      - symbol 동일
      - event_type == "order_filled"
      - side 동일
      - abs(entry_price 차이) / entry_price < max_slippage_pct
    """
    import csv as _csv
    from pathlib import Path as _Path
    import ast as _ast

    trade_log_path = _Path("logs") / "trade_log.csv"
    if not trade_log_path.exists():
        return None
    if actual_entry is None or float(actual_entry) <= 0:
        return None

    try:
        with trade_log_path.open("r", encoding="utf-8-sig", newline="") as f:
            all_rows = list(_csv.DictReader(f))
    except Exception:
        return None

    # 최근 이벤트부터 거꾸로 탐색해서 매칭되는 order_filled 찾기
    candidate_signal_ts = None
    candidate_entry = None
    for r in reversed(all_rows):
        if r.get("symbol") != symbol:
            continue
        if r.get("event_type") != "order_filled":
            continue
        if r.get("side") != actual_side:
            continue
        try:
            je = float(r.get("price") or 0)
        except Exception:
            continue
        if je <= 0:
            continue
        if abs(je - float(actual_entry)) / je > float(max_slippage_pct):
            continue

        candidate_signal_ts = str(r.get("signal_ts", "") or "")
        candidate_entry = je
        break

    if not candidate_signal_ts:
        return None

    # 동일 signal_ts 의 모든 이벤트를 모아 tp_plan / actual_sl 복구
    same_signal_events = [
        r for r in all_rows
        if r.get("symbol") == symbol and str(r.get("signal_ts", "") or "") == candidate_signal_ts
    ]

    tp_plan_raw = None
    tp_plan_name_raw = None
    actual_sl_value = None
    risk_per_unit_value = None

    for r in same_signal_events:
        if tp_plan_raw is None:
            cand_tp = r.get("tp_plan")
            if cand_tp:
                tp_plan_raw = cand_tp
        if tp_plan_name_raw is None:
            cand_name = r.get("tp_plan_name")
            if cand_name:
                tp_plan_name_raw = cand_name
        if actual_sl_value is None:
            cand_sl = r.get("actual_sl")
            if cand_sl not in (None, "", "None"):
                try:
                    actual_sl_value = float(cand_sl)
                except Exception:
                    pass
        if risk_per_unit_value is None:
            cand_risk = r.get("signal_risk_per_unit")
            if cand_risk not in (None, "", "None"):
                try:
                    risk_per_unit_value = float(cand_risk)
                except Exception:
                    pass

    tp_plan = {}
    tp_plan_name = str(tp_plan_name_raw or "base")
    if tp_plan_raw:
        try:
            if isinstance(tp_plan_raw, str):
                tp_plan = _ast.literal_eval(tp_plan_raw)
            elif isinstance(tp_plan_raw, dict):
                tp_plan = tp_plan_raw
        except Exception:
            tp_plan = {}

    # risk_per_unit 우선순위: 직접 저장값 > sl 과 entry 로 역산
    risk = 0.0
    if risk_per_unit_value is not None and float(risk_per_unit_value) > 0:
        risk = float(risk_per_unit_value)
    elif actual_sl_value is not None and candidate_entry is not None:
        risk = abs(float(candidate_entry) - float(actual_sl_value))

    if actual_sl_value is None and risk > 0 and candidate_entry is not None:
        if actual_side == "Buy":
            actual_sl_value = float(candidate_entry) - risk
        else:
            actual_sl_value = float(candidate_entry) + risk

    return {
        "should_enter": True,
        "side": actual_side,
        "entry": float(candidate_entry) if candidate_entry is not None else None,
        "sl": float(actual_sl_value) if actual_sl_value is not None else None,
        "risk_per_unit": float(risk) if risk > 0 else 0.0,
        "timestamp": candidate_signal_ts,
        "tp_plan": tp_plan if isinstance(tp_plan, dict) else {},
        "tp_plan_name": tp_plan_name,
        "_recovered_from": "trade_log",
    }


def recover_tp1_order_from_exchange_open_orders(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    position_side: str,
) -> dict | None:
    """
    거래소의 현재 open orders 중 reduceOnly 이고 Limit 인 주문을 찾아
    TP1 주문으로 간주하고 상세정보 반환.

    매칭 조건:
      - reduceOnly == True
      - orderType == "Limit"
      - side == (position_side 의 반대: Buy→Sell, Sell→Buy)

    여러 개면 가장 작은 qty 의 주문 선택 (= 가장 먼저 걸린 TP1 로 가정).
    """
    try:
        resp = exchange.get_open_orders(category=category, symbol=symbol)
    except Exception:
        return None

    orders = resp.get("result", {}).get("list", []) or []
    close_side = "Sell" if position_side == "Buy" else "Buy"

    candidates = []
    for o in orders:
        try:
            reduce_only = str(o.get("reduceOnly", "")).lower() == "true"
            order_type = str(o.get("orderType", ""))
            side = str(o.get("side", ""))
            order_id = str(o.get("orderId", ""))
            price = float(o.get("price", 0) or 0)
            qty = float(o.get("qty", 0) or 0)
        except Exception:
            continue

        if not reduce_only:
            continue
        if order_type != "Limit":
            continue
        if side != close_side:
            continue
        if not order_id or price <= 0 or qty <= 0:
            continue

        candidates.append({
            "order_id": order_id,
            "price": price,
            "qty": qty,
        })

    if not candidates:
        return None

    # 여러 orphan 이 있을 가능성 → qty 작은 것 (가장 먼저 걸렸을 확률 높음)
    candidates.sort(key=lambda x: x["qty"])
    return candidates[0]


def get_signal_risk_per_unit(signal_payload: dict | None) -> float:
    if not isinstance(signal_payload, dict):
        return 0.0

    risk = safe_float(signal_payload.get("risk_per_unit"), 0.0)
    if risk > 0:
        return risk

    entry = safe_float(signal_payload.get("entry"), 0.0)
    sl = safe_float(signal_payload.get("sl"), 0.0)
    if entry > 0 and sl > 0:
        return abs(entry - sl)

    return 0.0


def calc_actual_stop_from_fill(side: str, filled_price: float, signal_risk_per_unit: float) -> float | None:
    if filled_price <= 0 or signal_risk_per_unit <= 0:
        return None
    if side == "Buy":
        return filled_price - signal_risk_per_unit
    return filled_price + signal_risk_per_unit




def get_tp_target_price(entry_price: float, risk_per_unit: float, side: str, target_rr: float) -> float:
    if side == "Buy":
        return float(entry_price) + float(risk_per_unit) * float(target_rr)
    return float(entry_price) - float(risk_per_unit) * float(target_rr)


def get_tp_close_side(position_side: str) -> str:
    return "Sell" if position_side == "Buy" else "Buy"


def attach_tp1_limit_order(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    managed_pos: dict,
    asset_cfg: dict,
) -> dict | None:
    tp_targets = managed_pos.get("tp_targets") or []
    if not tp_targets:
        return None

    # --- Orphan 방지: 기존 tp1_exchange_order_id 가 남아있으면 취소 먼저 ---
    # [배경] attach_tp1_limit_order 가 두 번 호출되면 (중복 진입, tranche 추가 등)
    # 이전 order_id 가 덮어씌워져 orphan 이 됨. 거래소에선 살아있지만 엔진은 추적 불가.
    existing_order_id = str(managed_pos.get("tp1_exchange_order_id", "") or "")
    if existing_order_id:
        try:
            cancel_resp = exchange.cancel_order(category=category, symbol=symbol, order_id=existing_order_id)
            log_trade_event(
                event_type="tp1_limit_cancelled",
                symbol=symbol,
                side=str(managed_pos.get("side", "")),
                signal_ts=str(managed_pos.get("signal_ts", "")),
                reason="replaced_by_new_tp1_order_before_attach",
                extra={"response": cancel_resp, "cancelled_order_id": existing_order_id},
            )
        except Exception:
            # 이미 체결/취소된 주문이면 실패 가능 — 무시하고 새 주문 진행
            pass
        managed_pos["tp1_exchange_order_id"] = ""
        managed_pos["tp1_exchange_armed"] = False

    first_target = tp_targets[0]
    target_rr = float(first_target.get("rr", 0.0))
    target_frac = float(first_target.get("frac", 0.0))
    entry_price = safe_float(managed_pos.get("entry_price"), 0.0)
    risk_per_unit = safe_float(managed_pos.get("risk_per_unit"), 0.0)

    if entry_price <= 0 or risk_per_unit <= 0 or target_rr <= 0 or target_frac <= 0:
        return None

    original_qty = float(managed_pos.get("original_qty", 0.0))
    tp_qty_abs = original_qty * target_frac
    tp_qty = normalize_qty(
        qty=float(tp_qty_abs),
        qty_step=float(asset_cfg["qty_step"]),
        min_order_qty=float(asset_cfg["min_order_qty"]),
        qty_decimals=int(asset_cfg["qty_decimals"]),
    )
    if tp_qty <= 0:
        return None

    tp_price = get_tp_target_price(
        entry_price=entry_price,
        risk_per_unit=risk_per_unit,
        side=str(managed_pos.get("side", "")),
        target_rr=target_rr,
    )
    close_side = get_tp_close_side(str(managed_pos.get("side", "")))

    resp = exchange.place_reduce_only_limit_order(
        category=category,
        symbol=symbol,
        side=close_side,
        qty=tp_qty,
        price=tp_price,
    )
    order_id = str(resp.get("result", {}).get("orderId", ""))

    managed_pos["tp1_exchange_order_id"] = order_id
    managed_pos["tp1_exchange_price"] = float(tp_price)
    managed_pos["tp1_exchange_qty"] = float(tp_qty)
    managed_pos["tp1_exchange_armed"] = bool(order_id)
    managed_pos["tp1_exchange_done"] = False
    managed_pos["last_sync_at"] = utc_now_iso()
    return resp


def cancel_tp1_limit_order(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    managed_pos: dict,
) -> dict | None:
    order_id = str(managed_pos.get("tp1_exchange_order_id", "") or "")
    if not order_id:
        return None

    try:
        resp = exchange.cancel_order(category=category, symbol=symbol, order_id=order_id)
    except Exception:
        return None

    managed_pos["tp1_exchange_armed"] = False
    managed_pos["last_sync_at"] = utc_now_iso()
    return resp


def handle_tp1_exchange_fill(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    mp: dict,
    current_qty: float,
) -> None:
    if mp.get("tp1_done", False):
        return

    # --- Fallback 1: order_id 없거나 추적 실패 시 qty 변화로 TP1 감지 ---
    # [배경] orphan order (attach_tp1_limit_order 중복 호출로 id 덮어쓰기) 나
    # 재시작 후 order_id 복구 실패 시에도 실제 TP1 체결은 발생할 수 있음.
    # 이 fallback 이 없으면 BE 이동이 영구 누락됨.
    order_id = str(mp.get("tp1_exchange_order_id", "") or "")
    original_qty = safe_float(mp.get("original_qty"), 0.0)
    tp_targets = mp.get("tp_targets", []) or []
    first_target = tp_targets[0] if tp_targets else None
    tp1_frac = safe_float(first_target.get("frac"), 0.25) if isinstance(first_target, dict) else 0.25

    qty_fallback_triggered = False
    if original_qty > 0 and current_qty >= 0 and tp1_frac > 0:
        qty_reduced = original_qty - float(current_qty)
        # TP1 분량의 90% 이상 감소했으면 TP1 체결로 간주
        # (수수료/rounding 때문에 딱 frac 만큼 줄지 않을 수 있음)
        expected_tp1_qty = original_qty * tp1_frac
        if qty_reduced >= expected_tp1_qty * 0.9:
            qty_fallback_triggered = True

    if (not order_id) and (not qty_fallback_triggered):
        return

    # --- 기존 로직: order_id 기반 체결 확인 ---
    status = None
    if order_id:
        try:
            status = exchange.get_order_fill_status(category=category, symbol=symbol, order_id=order_id)
        except Exception:
            status = None

    order_confirmed_filled = False
    if isinstance(status, dict):
        if status.get("found", False) and not status.get("is_open", False) and status.get("is_filled", False):
            order_confirmed_filled = True

    # order_id 체결 확인되지도 않았고, qty fallback 도 아닌 경우 종료
    if (not order_confirmed_filled) and (not qty_fallback_triggered):
        return

    if not tp_targets:
        return

    first_target["done"] = True
    mp["tp1_done"] = True
    mp["tp1_exchange_done"] = True
    mp["tp1_exchange_armed"] = False

    if isinstance(status, dict):
        tp1_exec_qty = float(status.get("cum_exec_qty", 0.0) or 0.0)
        tp1_exec_price = float(status.get("avg_price", 0.0) or 0.0)
        order_status_str = str(status.get("status", ""))
    else:
        # qty fallback 경로: 체결 수량/가격은 추정치
        tp1_exec_qty = float(original_qty - float(current_qty))
        tp1_exec_price = 0.0
        order_status_str = "qty_fallback_inferred"

    mp["remaining_qty_est"] = max(0.0, float(current_qty))

    entry_price = safe_float(mp.get("entry_price"), 0.0)
    be_resp = None
    if entry_price > 0:
        try:
            be_resp = exchange.set_stop_loss_only(
                category=category,
                symbol=symbol,
                stop_loss=entry_price,
                position_idx=0,
                sl_trigger_by="LastPrice",
            )
            mp["be_moved"] = True
            mp["current_stop"] = entry_price
            mp["stop_type_last"] = "be"
        except Exception as be_err:
            log_system_event(
                event_type="be_move_failed",
                symbol=symbol,
                message=str(be_err),
                extra={"entry_price": entry_price},
            )

    mp["last_sync_at"] = utc_now_iso()

    event_type = "tp1_fallback_be_moved" if qty_fallback_triggered and not order_confirmed_filled else "tp1_exchange_filled"

    log_trade_event(
        event_type=event_type,
        symbol=symbol,
        side=str(mp.get("side", "")),
        qty=tp1_exec_qty,
        price=tp1_exec_price,
        signal_ts=str(mp.get("signal_ts", "")),
        reason=event_type,
        extra={
            "order_status": order_status_str,
            "be_response": be_resp,
            "qty_fallback_triggered": qty_fallback_triggered,
            "order_confirmed_filled": order_confirmed_filled,
            "original_qty": original_qty,
            "current_qty": float(current_qty),
        },
    )

    be_price_str = f"{entry_price}" if entry_price > 0 else "N/A"
    fallback_note = " (qty fallback)" if qty_fallback_triggered and not order_confirmed_filled else ""
    send_telegram_message(
        f"🟠 TP1 FILLED{fallback_note}\n"
        f"Symbol: {symbol}\n"
        f"Side: {mp.get('side', '')}\n"
        f"Qty: {tp1_exec_qty}\n"
        f"Price: {tp1_exec_price}\n"
        f"SL -> BE: {be_price_str}"
    )

def build_tp_targets(tp_plan: dict | None) -> list[dict]:
    if not isinstance(tp_plan, dict):
        return []

    targets = tp_plan.get("targets", [])
    out = []
    for idx, item in enumerate(targets):
        try:
            rr = float(item[0])
            frac = float(item[1])
        except Exception:
            continue

        out.append(
            {
                "name": f"tp{idx + 1}",
                "rr": rr,
                "frac": frac,
                "done": False,
            }
        )
    return out


def close_absolute_qty(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    actual_side: str,
    target_qty: float,
    asset_cfg: dict,
) -> tuple[float, dict | None]:
    close_qty = normalize_qty(
        qty=float(target_qty),
        qty_step=float(asset_cfg["qty_step"]),
        min_order_qty=float(asset_cfg["min_order_qty"]),
        qty_decimals=int(asset_cfg["qty_decimals"]),
    )

    if close_qty <= 0:
        return 0.0, None

    resp = exchange.close_position_market(
        category=category,
        symbol=symbol,
        side=actual_side,
        qty=close_qty,
    )
    return close_qty, resp


def calc_trailing_stop_price(
    side: str,
    entry_price: float,
    risk_per_unit: float,
    rr: float,
    protection: dict,
    trail_activate_rr: float,
) -> float | None:
    runner_trailing_enabled = bool(protection.get("runner_trailing_enabled", True))
    runner_trail_start_lock_rr = float(protection.get("runner_trail_start_lock_rr", 1.0))
    runner_trail_step_rr = float(protection.get("runner_trail_step_rr", 1.0))
    runner_trail_lock_increment_rr = float(protection.get("runner_trail_lock_increment_rr", 0.5))

    if not runner_trailing_enabled:
        return None
    if rr < trail_activate_rr:
        return None
    if risk_per_unit <= 0:
        return None

    extra_rr = max(0.0, rr - trail_activate_rr)
    passed_steps = int(extra_rr // runner_trail_step_rr)
    lock_rr = runner_trail_start_lock_rr + passed_steps * runner_trail_lock_increment_rr

    if side == "Buy":
        return entry_price + risk_per_unit * lock_rr
    return entry_price - risk_per_unit * lock_rr


def calc_backtest_trail_stop(
    side: str,
    entry_price: float,
    prev_high: float,
    prev_low: float,
    atr_val: float,
) -> float | None:
    """★백테 엔진 트레일 이식 (smc_stage4d.simulation.update_trailing_stop 동일 공식).
    직전 마감 H4봉의 range 중점 ∓ 0.10×H4ATR, entry 로 클램프(BE 이하로 안 내려감).
    단조성(현 stop 대비 유리할 때만)은 호출부 _meaningful_improve 가 처리.
    """
    if prev_high is None or prev_low is None or atr_val is None:
        return None
    prev_range = float(prev_high) - float(prev_low)
    a = float(atr_val) if atr_val == atr_val else 0.0   # NaN 방어
    if side == "Buy":
        candidate = float(prev_low) + prev_range * 0.50 - a * 0.10
        return max(candidate, float(entry_price))
    candidate = float(prev_high) - prev_range * 0.50 + a * 0.10
    return min(candidate, float(entry_price))


def _last_closed_h4_for_trail(exchange, category: str, symbol: str):
    """트레일용 직전 마감 H4봉 (high, low, ATR14). 신호경로와 동일하게 fetch 마지막 봉=마감봉으로 취급."""
    df = exchange.get_recent_klines_df(category=category, symbol=symbol, interval=H4_INTERVAL, limit=H4_LIMIT)
    h = df["high"].astype(float); l = df["low"].astype(float); c = df["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    return float(h.iloc[-1]), float(l.iloc[-1]), float(atr)


def parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def ensure_runner_lifecycle_fields(mp: dict) -> None:
    mp.setdefault("rr_bars_to_2r", None)
    mp.setdefault("rr_bars_spent_above_2r", 0)
    mp.setdefault("rr_max_rr_after_2r", 0.0)
    mp.setdefault("rr_cond_count_final", 0)
    mp.setdefault("runner_candidate_2of3", False)
    mp.setdefault("post_2of3_apply_ok", False)
    mp.setdefault("runner_protected", False)
    mp.setdefault("runner_stats_last_h4_ts", None)
    mp.setdefault("runner_stats_last_rr", 0.0)
    mp.setdefault("runner_state_badge", "IDLE")
    mp.setdefault("time_exit_disabled_for_runner", False)


def get_runner_state_badge(mp: dict) -> str:
    if bool(mp.get("runner_active", False)):
        return "TRAILING"
    if bool(mp.get("runner_protected", False)):
        return "PROTECTED"
    if bool(mp.get("post_2of3_apply_ok", False)):
        return "QUALIFIED"
    if bool(mp.get("runner_candidate_2of3", False)):
        return "CANDIDATE"
    return "IDLE"


def get_latest_closed_h4_bar(exchange: BybitExchange, category: str, symbol: str) -> dict | None:
    try:
        df_h4 = exchange.get_recent_klines_df(
            category=category,
            symbol=symbol,
            interval=H4_INTERVAL,
            limit=3,
        )
    except Exception:
        return None

    if len(df_h4) < 2:
        return None

    bar = df_h4.iloc[-2]
    return {
        "timestamp": bar["timestamp"],
        "open": float(bar["open"]),
        "high": float(bar["high"]),
        "low": float(bar["low"]),
        "close": float(bar["close"]),
    }


def register_runner_lifecycle_from_latest_h4_bar(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    mp: dict,
    protection: dict,
) -> None:
    ensure_runner_lifecycle_fields(mp)

    if not bool(protection.get("runner_lifecycle_enabled", True)):
        mp["runner_state_badge"] = get_runner_state_badge(mp)
        return

    entry_price = safe_float(mp.get("entry_price"), 0.0)
    risk_per_unit = safe_float(mp.get("risk_per_unit"), 0.0)
    side = str(mp.get("side", ""))

    if entry_price <= 0 or risk_per_unit <= 0 or side not in ("Buy", "Sell"):
        mp["runner_state_badge"] = get_runner_state_badge(mp)
        return

    bar = get_latest_closed_h4_bar(exchange=exchange, category=category, symbol=symbol)
    if not bar:
        mp["runner_state_badge"] = get_runner_state_badge(mp)
        return

    bar_ts = str(bar["timestamp"])
    if bar_ts == str(mp.get("runner_stats_last_h4_ts")):
        mp["runner_state_badge"] = get_runner_state_badge(mp)
        return

    if side == "Buy":
        favorable_rr = (float(bar["high"]) - entry_price) / risk_per_unit
    else:
        favorable_rr = (entry_price - float(bar["low"])) / risk_per_unit

    favorable_rr = float(favorable_rr)
    mp["runner_stats_last_rr"] = favorable_rr
    mp["runner_stats_last_h4_ts"] = bar_ts

    signal_ts_dt = parse_iso_utc(str(mp.get("signal_ts", "")))
    bar_dt = parse_iso_utc(bar_ts)
    if signal_ts_dt is not None and bar_dt is not None:
        hold_bars = max(1, int((bar_dt - signal_ts_dt).total_seconds() // (4 * 3600)))
    else:
        prev = mp.get("rr_bars_to_2r")
        hold_bars = int(prev) + 1 if prev not in (None, "") else 1

    if favorable_rr >= 2.0:
        mp["rr_bars_spent_above_2r"] = int(mp.get("rr_bars_spent_above_2r", 0)) + 1

        if mp.get("rr_bars_to_2r") in (None, ""):
            mp["rr_bars_to_2r"] = hold_bars

        extra_expand = max(0.0, favorable_rr - 2.0)
        mp["rr_max_rr_after_2r"] = max(float(mp.get("rr_max_rr_after_2r", 0.0)), extra_expand)

    fast_2r_bars_max = int(protection.get("runner_fast_2r_bars_max", 3))
    above_2r_bars_min = int(protection.get("runner_above_2r_bars_min", 3))
    max_rr_after_2r_min = float(protection.get("runner_max_rr_after_2r_min", 3.0))
    runner_candidate_min_conds = int(protection.get("runner_candidate_min_conds", 2))

    cond_fast_2r = mp.get("rr_bars_to_2r") not in (None, "") and int(mp.get("rr_bars_to_2r")) <= fast_2r_bars_max
    cond_hold_above_2r = int(mp.get("rr_bars_spent_above_2r", 0)) >= above_2r_bars_min
    cond_extra_expand = float(mp.get("rr_max_rr_after_2r", 0.0)) >= max_rr_after_2r_min
    cond_count_final = int(cond_fast_2r) + int(cond_hold_above_2r) + int(cond_extra_expand)
    mp["rr_cond_count_final"] = cond_count_final

    if cond_count_final >= runner_candidate_min_conds and not bool(mp.get("runner_candidate_2of3", False)):
        mp["runner_candidate_2of3"] = True
        log_trade_event(
            event_type="runner_candidate_2of3",
            symbol=symbol,
            side=side,
            signal_ts=str(mp.get("signal_ts", "")),
            reason="runner_candidate_2of3",
            extra={
                "rr_bars_to_2r": mp.get("rr_bars_to_2r"),
                "rr_bars_spent_above_2r": mp.get("rr_bars_spent_above_2r"),
                "rr_max_rr_after_2r": mp.get("rr_max_rr_after_2r"),
                "rr_cond_count_final": cond_count_final,
            },
        )

    if bool(mp.get("runner_candidate_2of3", False)) and not bool(mp.get("post_2of3_apply_ok", False)):
        post_filter_enabled = bool(protection.get("runner_post_filter_enabled", True))
        post_filter_threshold = float(protection.get("runner_post_filter_max_rr_after_2r", 1.5))
        if (not post_filter_enabled) or float(mp.get("rr_max_rr_after_2r", 0.0)) >= post_filter_threshold:
            mp["post_2of3_apply_ok"] = True
            log_trade_event(
                event_type="runner_post_filter_ok",
                symbol=symbol,
                side=side,
                signal_ts=str(mp.get("signal_ts", "")),
                reason="runner_post_filter_ok",
                extra={"rr_max_rr_after_2r": mp.get("rr_max_rr_after_2r"), "post_filter_threshold": post_filter_threshold},
            )

    if bool(mp.get("post_2of3_apply_ok", False)) and not bool(mp.get("runner_protected", False)):
        require_be = bool(protection.get("runner_protect_only_if_be_moved", True))
        if (not require_be) or bool(mp.get("be_moved", False)):
            protect_locked_r = float(protection.get("runner_protect_locked_r", 0.30))
            if side == "Buy":
                protected_stop = entry_price + risk_per_unit * protect_locked_r
                should_update = mp.get("current_stop") is None or float(protected_stop) > float(mp.get("current_stop"))
            else:
                protected_stop = entry_price - risk_per_unit * protect_locked_r
                should_update = mp.get("current_stop") is None or float(protected_stop) < float(mp.get("current_stop"))

            resp = None
            if should_update:
                resp = exchange.set_stop_loss_only(
                    category=category,
                    symbol=symbol,
                    stop_loss=float(protected_stop),
                    position_idx=0,
                    sl_trigger_by="LastPrice",
                )
                mp["current_stop"] = float(protected_stop)

            mp["runner_protected"] = True
            mp["time_exit_disabled_for_runner"] = bool(protection.get("disable_time_exit_for_runner", True))

            log_trade_event(
                event_type="runner_protected",
                symbol=symbol,
                side=side,
                signal_ts=str(mp.get("signal_ts", "")),
                reason="runner_protected",
                extra={"protected_stop": mp.get("current_stop"), "response": resp},
            )

    mp["runner_state_badge"] = get_runner_state_badge(mp)


def build_managed_position(
    symbol: str,
    signal_side: str,
    order_qty: float,
    signal_ts: str,
    filled_price: float | None,
    expected_price: float | None,
    slippage_pct: float | None,
    actual_sl: float | None,
    signal_payload: dict | None,
    management_enabled: bool,
    recovered: bool = False,
    awaiting_fill_sync: bool = False,
    entry_source: str = "",
) -> dict:
    signal_risk_per_unit = get_signal_risk_per_unit(signal_payload)
    tp_plan = signal_payload.get("tp_plan", {}) if isinstance(signal_payload, dict) else {}
    tp_plan_name = signal_payload.get("tp_plan_name", "") if isinstance(signal_payload, dict) else ""
    tp_targets = build_tp_targets(tp_plan)

    # v1.9b TIER 정보 추출 (없으면 기본값)
    if isinstance(signal_payload, dict):
        tier_label = str(signal_payload.get("tier", "") or "")
        tier_mult_val = signal_payload.get("tier_mult")
        tier_pre_total_val = signal_payload.get("tier_pre_total")
        tier_sweep_count_val = signal_payload.get("tier_sweep_count")
        tier_wick_ratio_5_val = signal_payload.get("tier_wick_ratio_5")
        risk_pct_base_val = signal_payload.get("risk_pct_base")
        risk_pct_tier_adjusted_val = signal_payload.get("risk_pct_tier_adjusted")
        # ⭐ Stage 4K 신규 ⭐
        run_potential_val = signal_payload.get("run_potential")
        rp_action_val = signal_payload.get("rp_action")
        stage4j_mult_val = signal_payload.get("stage4j_mult")
        stage4j_label_val = signal_payload.get("stage4j_label")
        sentiment_mult_val = signal_payload.get("sentiment_mult")
        sentiment_label_val = signal_payload.get("sentiment_label")
    else:
        tier_label = ""
        tier_mult_val = None
        tier_pre_total_val = None
        tier_sweep_count_val = None
        tier_wick_ratio_5_val = None
        risk_pct_base_val = None
        risk_pct_tier_adjusted_val = None
        run_potential_val = None
        rp_action_val = None
        stage4j_mult_val = None
        stage4j_label_val = None
        sentiment_mult_val = None
        sentiment_label_val = None

    mp = {
        "symbol": symbol,
        "side": signal_side,
        "entry_price": float(filled_price) if filled_price is not None else None,
        "expected_entry_price": float(expected_price) if expected_price is not None else None,
        "slippage_pct": float(slippage_pct) if slippage_pct is not None else None,
        "initial_sl": float(actual_sl) if actual_sl is not None else None,
        "current_stop": float(actual_sl) if actual_sl is not None else None,
        "risk_per_unit": float(signal_risk_per_unit) if signal_risk_per_unit > 0 else 0.0,
        "original_qty": float(order_qty),
        "remaining_qty_est": float(order_qty),
        "signal_ts": str(signal_ts),
        "tp_plan_name": tp_plan_name,
        "tp_plan": tp_plan,
        "tp_targets": tp_targets,
        "tp1_done": False,
        "tp2_done": False,
        "tp3_done": False,
        "be_moved": False,
        "runner_active": False,
        "runner_announced": False,
        "tp1_exchange_order_id": "",
        "tp1_exchange_price": None,
        "tp1_exchange_qty": 0.0,
        "tp1_exchange_armed": False,
        "tp1_exchange_done": False,
        "recovered": recovered,
        "management_enabled": management_enabled,
        "awaiting_fill_sync": awaiting_fill_sync,
        "entry_source": entry_source,
        "last_sync_at": utc_now_iso(),
        # v1.9b TIER fields
        "tier": tier_label,
        "tier_mult": float(tier_mult_val) if tier_mult_val is not None else None,
        "tier_pre_total": int(tier_pre_total_val) if tier_pre_total_val is not None else None,
        "tier_sweep_count": int(tier_sweep_count_val) if tier_sweep_count_val is not None else None,
        "tier_wick_ratio_5": float(tier_wick_ratio_5_val) if tier_wick_ratio_5_val is not None else None,
        "risk_pct_base": float(risk_pct_base_val) if risk_pct_base_val is not None else None,
        "risk_pct_tier_adjusted": float(risk_pct_tier_adjusted_val) if risk_pct_tier_adjusted_val is not None else None,
        # ⭐⭐ Stage 4K 신규 fields (sentiment lookback 핵심 데이터) ⭐⭐
        "run_potential": int(run_potential_val) if run_potential_val is not None else None,
        "rp_action": str(rp_action_val) if rp_action_val is not None else "",
        "stage4j_mult": float(stage4j_mult_val) if stage4j_mult_val is not None else 1.0,
        "stage4j_label": str(stage4j_label_val) if stage4j_label_val is not None else "DEFAULT",
        "sentiment_mult": float(sentiment_mult_val) if sentiment_mult_val is not None else 1.0,
        "sentiment_label": str(sentiment_label_val) if sentiment_label_val is not None else "no_data",
    }
    ensure_runner_lifecycle_fields(mp)
    return mp


def attach_initial_stop_loss(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    managed_pos: dict,
) -> dict | None:
    sl_price = managed_pos.get("current_stop")
    if sl_price is None:
        return None

    return exchange.set_stop_loss_only(
        category=category,
        symbol=symbol,
        stop_loss=float(sl_price),
        position_idx=0,
        sl_trigger_by="LastPrice",
    )


def sync_existing_managed_position_with_exchange(mp: dict, actual: dict, signal_payload: dict | None) -> None:
    ensure_runner_lifecycle_fields(mp)
    raw = actual.get("raw", {}) or {}
    actual_qty = float(actual.get("qty", 0.0))
    actual_entry = extract_avg_entry_price(raw)
    side = str(mp.get("side", ""))

    mp["remaining_qty_est"] = actual_qty
    mp["last_sync_at"] = utc_now_iso()

    if "tp_targets" not in mp or not isinstance(mp.get("tp_targets"), list):
        tp_plan = signal_payload.get("tp_plan", {}) if isinstance(signal_payload, dict) else {}
        mp["tp_plan"] = tp_plan
        mp["tp_plan_name"] = signal_payload.get("tp_plan_name", "") if isinstance(signal_payload, dict) else ""
        mp["tp_targets"] = build_tp_targets(tp_plan)

    mp.setdefault("tp1_exchange_order_id", "")
    mp.setdefault("tp1_exchange_price", None)
    mp.setdefault("tp1_exchange_qty", 0.0)
    mp.setdefault("tp1_exchange_armed", False)
    mp.setdefault("tp1_exchange_done", False)

    if actual_entry is not None and actual_entry > 0:
        signal_risk_per_unit = get_signal_risk_per_unit(signal_payload)

        if signal_risk_per_unit > 0:
            old_initial_sl = mp.get("initial_sl")
            old_current_stop = mp.get("current_stop")
            new_initial_sl = calc_actual_stop_from_fill(side, actual_entry, signal_risk_per_unit)

            mp["entry_price"] = float(actual_entry)
            mp["risk_per_unit"] = float(signal_risk_per_unit)
            mp["initial_sl"] = float(new_initial_sl) if new_initial_sl is not None else None

            if old_current_stop is None:
                mp["current_stop"] = mp["initial_sl"]
            elif old_initial_sl is not None and abs(float(old_current_stop) - float(old_initial_sl)) < 1e-9:
                mp["current_stop"] = mp["initial_sl"]

        elif mp.get("entry_price") is None:
            mp["entry_price"] = float(actual_entry)

    if mp.get("awaiting_fill_sync", False) and actual_entry is not None:
        mp["awaiting_fill_sync"] = False
        mp["management_enabled"] = mp.get("risk_per_unit", 0.0) > 0
        mp["entry_source"] = "exchange_sync_after_order"

        log_trade_event(
            event_type="fill_sync_completed",
            symbol=str(mp.get("symbol", "")),
            side=str(mp.get("side", "")),
            qty=float(actual.get("qty", 0.0)),
            price=float(actual_entry),
            signal_ts=str(mp.get("signal_ts", "")),
            reason="fill_sync_completed",
            extra={"raw": raw},
        )


def rebuild_managed_positions_from_exchange(
    state: dict,
    managed_positions: dict,
    open_positions_map: dict,
    exchange: BybitExchange | None = None,
    category: str | None = None,
) -> None:
    for symbol, mp in list(managed_positions.items()):
        actual = open_positions_map.get(symbol)
        if not actual or not actual.get("has_position"):
            # 포지션 청산 감지
            from datetime import datetime, timezone as tz
            # ★ [PATCHED 2026-06-04] 쿨다운 키 불일치 수정 + SL 전용(TP1 미체결) 조건.
            #   (1) 기존엔 state["symbol_states"] 에 썼는데, 쿨다운 체크(2454행)는
            #       ensure_symbol_state = state["symbols"] 를 읽음 → 서로 다른 키라 8h 쿨다운이
            #       전혀 작동 안 했음(LINK 3시간 재진입 사고). → 동일하게 ensure_symbol_state 사용.
            #   (2) "TP1 도 못 치고 SL 로 청산"된 경우에만 쿨다운. TP1 이미 친 포지션 청산은
            #       부분익절 성공 거래이므로 쿨다운 걸지 않음(재진입 즉시 허용).
            sym_state = ensure_symbol_state(state, symbol)
            tp1_hit = bool(mp.get("tp1_done", False) or mp.get("tp1_exchange_done", False))
            if not tp1_hit:
                sym_state["last_exit_time"] = datetime.now(tz.utc).isoformat()
                sym_state["last_exit_side"] = mp.get("side", "")
                sym_state["last_exit_reason"] = "closed_pre_tp1"
                print(f"[COOLDOWN] {symbol} closed BEFORE TP1 -> {EXIT_COOLDOWN_HOURS}h cooldown armed")
            else:
                # TP1 친 뒤 청산 → 쿨다운 미적용. 직전 stale 쿨다운이 있으면 해제.
                sym_state["last_exit_time"] = None
                sym_state["last_exit_side"] = mp.get("side", "")
                sym_state["last_exit_reason"] = "closed_after_tp1_no_cooldown"
                print(f"[COOLDOWN] {symbol} closed AFTER TP1 -> no cooldown (re-entry allowed)")
            managed_positions.pop(symbol, None)
            _clear_recovery_failed_notify(symbol)  # ★ [PATCHED 2026-06-04] 청산 시 스로틀 초기화
            continue

        signal_payload = get_signal_payload_for_symbol(state, symbol)
        sync_existing_managed_position_with_exchange(mp, actual, signal_payload)

        # ★★★ [PATCHED May 20 — Manual Position] ★★★
        # manual_position=True 인 포지션은 사용자가 직접 관리.
        # 봇은 복구 재시도 X, recovery_failed 알림 X, SL/TP 안 건드림.
        # (청산 감지는 위 라인 1285 에서 처리되므로 닫히면 자동 제거됨)
        if mp.get("manual_position", False):
            continue

        # --- 기존 managed_position 도 관리 비활성 상태면 복구 시도 ---
        # [배경] 이전 재시작에서 exchange_recovered_only 로 저장된 포지션도
        # 이번엔 trade_log.csv + open orders 로 복구될 수 있음.
        if not mp.get("management_enabled", False):
            actual_side = str(actual.get("side", ""))
            actual_entry = extract_avg_entry_price(actual.get("raw", {}) or {})
            actual_qty = float(actual.get("qty", 0.0))
            recovered_plan = recover_signal_plan_from_trade_log(
                symbol=symbol,
                actual_side=actual_side,
                actual_entry=actual_entry if actual_entry is not None else 0.0,
            )
            if isinstance(recovered_plan, dict):
                recovered_risk = get_signal_risk_per_unit(recovered_plan)
                recovered_sl = recovered_plan.get("sl")
                recovered_sl_f = safe_float(recovered_sl, 0.0)
                if recovered_risk > 0 and actual_entry is not None:
                    # managed_position 필드 직접 업데이트 (mp 객체 유지)
                    tp_plan = recovered_plan.get("tp_plan", {}) or {}
                    tp_targets = build_tp_targets(tp_plan)
                    mp["entry_price"] = float(actual_entry)
                    mp["risk_per_unit"] = float(recovered_risk)
                    mp["initial_sl"] = float(recovered_sl_f) if recovered_sl_f > 0 else mp.get("initial_sl")
                    mp["current_stop"] = mp.get("current_stop") or (float(recovered_sl_f) if recovered_sl_f > 0 else None)
                    mp["tp_plan"] = tp_plan if isinstance(tp_plan, dict) else {}
                    mp["tp_plan_name"] = str(recovered_plan.get("tp_plan_name", "") or "base")
                    mp["tp_targets"] = tp_targets
                    mp["signal_ts"] = str(recovered_plan.get("timestamp", "") or mp.get("signal_ts", ""))
                    mp["original_qty"] = float(mp.get("original_qty") or actual_qty or 0.0)
                    mp["remaining_qty_est"] = float(actual_qty)
                    mp["management_enabled"] = True
                    mp["recovered"] = True
                    mp["entry_source"] = "recovered_from_trade_log"
                    mp["last_sync_at"] = utc_now_iso()
                    log_trade_event(
                        event_type="managed_position_recovered",
                        symbol=symbol,
                        side=actual_side,
                        qty=actual_qty,
                        price=float(actual_entry),
                        signal_ts=str(mp.get("signal_ts", "")),
                        reason="recovered_from_trade_log",
                        extra={
                            "risk_per_unit": recovered_risk,
                            "tp_plan_name": mp["tp_plan_name"],
                        },
                    )
                    send_telegram_message(
                        f"🔄 POSITION RECOVERED\n"
                        f"Symbol: {symbol}\n"
                        f"Side: {actual_side}\n"
                        f"Entry: {actual_entry}\n"
                        f"Risk/unit: {recovered_risk}\n"
                        f"Plan: {mp['tp_plan_name']}\n"
                        f"Source: trade_log"
                    )

        # --- TP1 exchange order 복구: 엔진에 order_id 없지만 거래소엔 있을 수 있음 ---
        # [배경] 재시작 시 tp1_exchange_order_id 가 빈 값으로 초기화되지만
        # 거래소엔 reduceOnly Limit 주문이 그대로 살아있을 수 있음.
        if (
            exchange is not None
            and category
            and mp.get("management_enabled", False)
            and not mp.get("tp1_done", False)
            and not mp.get("tp1_exchange_order_id", "")
        ):
            recovered_tp1 = recover_tp1_order_from_exchange_open_orders(
                exchange=exchange,
                category=category,
                symbol=symbol,
                position_side=str(mp.get("side", "")),
            )
            if isinstance(recovered_tp1, dict):
                mp["tp1_exchange_order_id"] = str(recovered_tp1.get("order_id", ""))
                mp["tp1_exchange_price"] = float(recovered_tp1.get("price", 0.0) or 0.0)
                mp["tp1_exchange_qty"] = float(recovered_tp1.get("qty", 0.0) or 0.0)
                mp["tp1_exchange_armed"] = True
                mp["tp1_exchange_done"] = False
                mp["last_sync_at"] = utc_now_iso()
                log_trade_event(
                    event_type="tp1_exchange_order_recovered",
                    symbol=symbol,
                    side=str(mp.get("side", "")),
                    qty=float(mp["tp1_exchange_qty"]),
                    price=float(mp["tp1_exchange_price"]),
                    signal_ts=str(mp.get("signal_ts", "")),
                    reason="tp1_exchange_order_recovered_from_open_orders",
                    extra={"order_id": mp["tp1_exchange_order_id"]},
                )

    # --- 거래소에만 있고 엔진엔 없는 새 포지션 처리 ---
    for symbol, actual in open_positions_map.items():
        if not actual.get("has_position"):
            continue
        if symbol in managed_positions:
            continue

        signal_payload = get_signal_payload_for_symbol(state, symbol)
        actual_side = str(actual.get("side", ""))
        actual_qty = float(actual.get("qty", 0.0))
        actual_entry = extract_avg_entry_price(actual.get("raw", {}) or {})

        if isinstance(signal_payload, dict):
            signal_side = str(signal_payload.get("side", ""))
            if signal_side == actual_side:
                signal_risk_per_unit = get_signal_risk_per_unit(signal_payload)
                actual_sl = calc_actual_stop_from_fill(actual_side, actual_entry, signal_risk_per_unit) if actual_entry else None

                managed_positions[symbol] = build_managed_position(
                    symbol=symbol,
                    signal_side=actual_side,
                    order_qty=actual_qty,
                    signal_ts=str(signal_payload.get("timestamp", "recovered")),
                    filled_price=actual_entry,
                    expected_price=safe_float(signal_payload.get("entry"), 0.0) or None,
                    slippage_pct=calc_slippage_pct(
                        actual_side,
                        safe_float(signal_payload.get("entry"), 0.0) or None,
                        actual_entry,
                    ),
                    actual_sl=actual_sl,
                    signal_payload=signal_payload,
                    management_enabled=(signal_risk_per_unit > 0 and actual_sl is not None),
                    recovered=True,
                    awaiting_fill_sync=False,
                    entry_source="exchange_recovered_with_signal_plan",
                )
                # tp1 order 복구 시도
                if exchange is not None and category:
                    _try_recover_tp1_order_for_symbol(exchange, category, symbol, managed_positions[symbol])
                continue

        # signal_payload 없거나 매칭 실패 → trade_log.csv 에서 복구 시도
        recovered_plan = recover_signal_plan_from_trade_log(
            symbol=symbol,
            actual_side=actual_side,
            actual_entry=actual_entry if actual_entry is not None else 0.0,
        )
        if isinstance(recovered_plan, dict):
            recovered_risk = get_signal_risk_per_unit(recovered_plan)
            recovered_sl = recovered_plan.get("sl")
            if recovered_risk > 0 and actual_entry is not None:
                managed_positions[symbol] = build_managed_position(
                    symbol=symbol,
                    signal_side=actual_side,
                    order_qty=actual_qty,
                    signal_ts=str(recovered_plan.get("timestamp", "recovered")),
                    filled_price=actual_entry,
                    expected_price=safe_float(recovered_plan.get("entry"), 0.0) or None,
                    slippage_pct=None,
                    actual_sl=float(recovered_sl) if recovered_sl is not None else None,
                    signal_payload=recovered_plan,
                    management_enabled=True,
                    recovered=True,
                    awaiting_fill_sync=False,
                    entry_source="recovered_from_trade_log",
                )
                log_trade_event(
                    event_type="managed_position_recovered",
                    symbol=symbol,
                    side=actual_side,
                    qty=actual_qty,
                    price=float(actual_entry),
                    signal_ts=str(recovered_plan.get("timestamp", "")),
                    reason="recovered_from_trade_log_new_position",
                    extra={
                        "risk_per_unit": recovered_risk,
                        "tp_plan_name": managed_positions[symbol].get("tp_plan_name", ""),
                    },
                )
                send_telegram_message(
                    f"🔄 POSITION RECOVERED (new entry)\n"
                    f"Symbol: {symbol}\n"
                    f"Side: {actual_side}\n"
                    f"Entry: {actual_entry}\n"
                    f"Plan: {managed_positions[symbol].get('tp_plan_name', '')}"
                )
                if exchange is not None and category:
                    _try_recover_tp1_order_for_symbol(exchange, category, symbol, managed_positions[symbol])
                continue

        # 최후 fallback: 모든 복구 실패 → 예전처럼 exchange_recovered_only
        managed_positions[symbol] = {
            "symbol": symbol,
            "side": actual_side,
            "entry_price": float(actual_entry) if actual_entry is not None else None,
            "expected_entry_price": None,
            "slippage_pct": None,
            "initial_sl": None,
            "current_stop": None,
            "risk_per_unit": 0.0,
            "original_qty": actual_qty,
            "remaining_qty_est": actual_qty,
            "signal_ts": "recovered",
            "tp_plan_name": "",
            "tp_plan": {},
            "tp_targets": [],
            "tp1_done": False,
            "tp2_done": False,
            "tp3_done": False,
            "be_moved": False,
            "runner_active": False,
            "runner_announced": False,
            "tp1_exchange_order_id": "",
            "tp1_exchange_price": None,
            "tp1_exchange_qty": 0.0,
            "tp1_exchange_armed": False,
            "tp1_exchange_done": False,
            "recovered": True,
            "management_enabled": False,
            "manual_position": False,
            "awaiting_fill_sync": False,
            "entry_source": "exchange_recovered_only",
            "last_sync_at": utc_now_iso(),
        }
        ensure_runner_lifecycle_fields(managed_positions[symbol])
        # ★ [PATCHED 2026-06-04] orphan 포지션의 recovery_failed 매 루프 도배 방지.
        # 포지션은 그대로 exchange_recovered_only(management_enabled=False)로 유지되어
        # manage_open_positions 에서 SL/TP 를 건드리지 않음(안전). 단지 로그/텔레그램만
        # 심볼당 1시간 1회로 스로틀해서 trade_log.csv 초당 재기록 폭주를 끊는다.
        if _should_notify_recovery_failed(symbol):
            log_trade_event(
                event_type="managed_position_recovery_failed",
                symbol=symbol,
                side=actual_side,
                qty=actual_qty,
                signal_ts="recovered",
                reason="no_signal_payload_or_trade_log_match",
            )
            send_telegram_message(
                f"⚠️ POSITION RECOVERY FAILED\n"
                f"Symbol: {symbol}\n"
                f"Side: {actual_side}\n"
                f"Qty: {actual_qty}\n"
                f"Action: manual management required\n"
                f"(이후 1시간 동안 이 심볼 반복 알림 생략)"
            )


def _try_recover_tp1_order_for_symbol(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    mp: dict,
) -> None:
    """신규 복구된 managed_position 에 대해 거래소 open orders 로 TP1 order_id 복구."""
    try:
        recovered_tp1 = recover_tp1_order_from_exchange_open_orders(
            exchange=exchange,
            category=category,
            symbol=symbol,
            position_side=str(mp.get("side", "")),
        )
    except Exception:
        recovered_tp1 = None
    if isinstance(recovered_tp1, dict):
        mp["tp1_exchange_order_id"] = str(recovered_tp1.get("order_id", ""))
        mp["tp1_exchange_price"] = float(recovered_tp1.get("price", 0.0) or 0.0)
        mp["tp1_exchange_qty"] = float(recovered_tp1.get("qty", 0.0) or 0.0)
        mp["tp1_exchange_armed"] = True
        mp["tp1_exchange_done"] = False
        log_trade_event(
            event_type="tp1_exchange_order_recovered",
            symbol=symbol,
            side=str(mp.get("side", "")),
            qty=float(mp["tp1_exchange_qty"]),
            price=float(mp["tp1_exchange_price"]),
            signal_ts=str(mp.get("signal_ts", "")),
            reason="tp1_exchange_order_recovered_from_open_orders",
            extra={"order_id": mp["tp1_exchange_order_id"]},
        )


def update_exchange_positions_snapshot(state: dict, open_positions_map: dict) -> None:
    exchange_positions = ensure_exchange_positions(state)
    exchange_positions.clear()

    for symbol, pos in open_positions_map.items():
        if not pos.get("has_position"):
            continue

        raw = pos.get("raw", {}) or {}
        exchange_positions[symbol] = {
            "side": pos.get("side", ""),
            "qty": float(pos.get("qty", 0.0)),
            "avg_entry_price": extract_avg_entry_price(raw),
            "mark_price": safe_float(raw.get("markPrice"), None),
            "liq_price": safe_float(raw.get("liqPrice"), None),
            "position_value": safe_float(raw.get("positionValue"), None),
            "unrealised_pnl": safe_float(raw.get("unrealisedPnl"), None),
            "updated_at": utc_now_iso(),
        }

    latest = ensure_latest_open_positions(state)
    latest.clear()
    latest.update(exchange_positions)


def update_engine_positions_view_snapshot(state: dict, managed_positions: dict) -> None:
    engine_view = ensure_engine_positions_view(state)
    engine_view.clear()

    for symbol, mp in managed_positions.items():
        engine_view[symbol] = {
            "side": mp.get("side", ""),
            "entry_price": mp.get("entry_price"),
            "expected_entry_price": mp.get("expected_entry_price"),
            "slippage_pct": mp.get("slippage_pct"),
            "initial_sl": mp.get("initial_sl"),
            "current_stop": mp.get("current_stop"),
            "risk_per_unit": mp.get("risk_per_unit"),
            "original_qty": mp.get("original_qty"),
            "remaining_qty_est": mp.get("remaining_qty_est"),
            "tp_plan_name": mp.get("tp_plan_name"),
            "tp_targets": mp.get("tp_targets"),
            "tp1_done": mp.get("tp1_done"),
            "tp2_done": mp.get("tp2_done"),
            "tp3_done": mp.get("tp3_done"),
            "be_moved": mp.get("be_moved"),
            "runner_active": mp.get("runner_active"),
            "runner_candidate_2of3": mp.get("runner_candidate_2of3"),
            "post_2of3_apply_ok": mp.get("post_2of3_apply_ok"),
            "runner_protected": mp.get("runner_protected"),
            "runner_state_badge": mp.get("runner_state_badge"),
            "rr_bars_to_2r": mp.get("rr_bars_to_2r"),
            "rr_bars_spent_above_2r": mp.get("rr_bars_spent_above_2r"),
            "rr_max_rr_after_2r": mp.get("rr_max_rr_after_2r"),
            "rr_cond_count_final": mp.get("rr_cond_count_final"),
            "time_exit_disabled_for_runner": mp.get("time_exit_disabled_for_runner"),
            "tp1_exchange_order_id": mp.get("tp1_exchange_order_id"),
            "tp1_exchange_price": mp.get("tp1_exchange_price"),
            "tp1_exchange_qty": mp.get("tp1_exchange_qty"),
            "tp1_exchange_armed": mp.get("tp1_exchange_armed"),
            "tp1_exchange_done": mp.get("tp1_exchange_done"),
            "recovered": mp.get("recovered"),
            "management_enabled": mp.get("management_enabled"),
            "manual_position": mp.get("manual_position", False),
            "awaiting_fill_sync": mp.get("awaiting_fill_sync"),
            "entry_source": mp.get("entry_source"),
            "signal_ts": mp.get("signal_ts"),
            "last_sync_at": mp.get("last_sync_at"),
        }


def refresh_runtime_snapshots(state: dict, open_positions_map: dict, managed_positions: dict) -> None:
    update_exchange_positions_snapshot(state=state, open_positions_map=open_positions_map)
    update_engine_positions_view_snapshot(state=state, managed_positions=managed_positions)


def manage_open_positions(
    exchange: BybitExchange,
    category: str,
    open_positions_map: dict,
    managed_positions: dict,
    assets: dict,
    protection: dict,
) -> None:
    if not bool(protection.get("position_management_enabled", True)):
        return

    symbols_to_remove = []

    for symbol, mp in managed_positions.items():
        ensure_runner_lifecycle_fields(mp)

        actual = open_positions_map.get(symbol)
        if not actual or not actual.get("has_position"):
            if mp.get("tp1_exchange_armed", False):
                cancel_resp = cancel_tp1_limit_order(
                    exchange=exchange,
                    category=category,
                    symbol=symbol,
                    managed_pos=mp,
                )
                if cancel_resp is not None:
                    log_trade_event(
                        event_type="tp1_limit_cancelled",
                        symbol=symbol,
                        side=str(mp.get("side", "")),
                        signal_ts=str(mp.get("signal_ts", "")),
                        reason="position_not_found_on_exchange",
                        extra={"response": cancel_resp},
                    )

            log_trade_event(
                event_type="managed_position_removed",
                symbol=symbol,
                reason="position_not_found_on_exchange",
            )
            send_telegram_message(
                f"⚪ POSITION CLOSED DETECTED\n"
                f"Symbol: {symbol}\n"
                f"Side: {mp.get('side', '')}\n"
                f"Signal TS: {mp.get('signal_ts', '')}\n"
                f"Reason: position_not_found_on_exchange"
            )
            symbols_to_remove.append(symbol)
            continue

        if not mp.get("management_enabled", True):
            log_trade_event(
                event_type="recovered_position_unmanaged",
                symbol=symbol,
                side=str(mp.get("side", "")),
                qty=float(actual.get("qty", 0.0)),
                reason="recovered_or_unsynced_position_waiting_manual_or_sync",
            )
            continue

        side = str(mp.get("side", ""))
        entry_price = mp.get("entry_price")
        risk_per_unit = safe_float(mp.get("risk_per_unit"), 0.0)
        asset_cfg = assets.get(symbol)

        if not asset_cfg:
            continue
        if entry_price is None or risk_per_unit <= 0:
            continue

        entry_price = float(entry_price)
        current_qty = float(actual.get("qty", 0.0))
        original_qty = float(mp.get("original_qty", current_qty))

        if bool(mp.get("tp1_exchange_armed", False)) and not bool(mp.get("tp1_done", False)):
            handle_tp1_exchange_fill(
                exchange=exchange,
                category=category,
                symbol=symbol,
                mp=mp,
                current_qty=current_qty,
            )

        current_price = exchange.get_last_price(category=category, symbol=symbol)
        rr = calc_rr(side=side, entry_price=entry_price, risk_per_unit=risk_per_unit, current_price=current_price)

        tp_plan = mp.get("tp_plan", {}) or {}
        tp_targets = mp.get("tp_targets", []) or []
        be_after_rr = float(tp_plan.get("be_after_rr", 1.0))
        trail_activate_rr = float(tp_plan.get("trail_activate_rr", 3.0))
        max_hold_bars = int(tp_plan.get("max_hold_bars", 12))

        print_title(f"POSITION MANAGEMENT - {symbol}")
        print(f"side={side}")
        print(f"current_price={current_price}")
        print(f"entry_price={entry_price}")
        print(f"risk_per_unit={risk_per_unit}")
        print(f"rr={rr:.4f}")
        print(f"current_qty={current_qty}")
        print(f"tp_plan_name={mp.get('tp_plan_name')}")
        print(f"runner_state={mp.get('runner_state_badge')}")

        register_runner_lifecycle_from_latest_h4_bar(
            exchange=exchange,
            category=category,
            symbol=symbol,
            mp=mp,
            protection=protection,
        )

        log_trade_event(
            event_type="position_management_check",
            symbol=symbol,
            side=side,
            qty=current_qty,
            price=current_price,
            signal_ts=str(mp.get("signal_ts", "")),
            reason="position_management_check",
            extra={"rr": rr, "tp_plan_name": mp.get("tp_plan_name"), "runner_state_badge": mp.get("runner_state_badge")},
        )

        signal_ts_raw = str(mp.get("signal_ts", ""))
        if signal_ts_raw not in ("", "recovered"):
            try:
                signal_ts = datetime.fromisoformat(signal_ts_raw.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - signal_ts).total_seconds() / 3600.0
                max_hold_hours = max_hold_bars * 4.0
                disable_time_exit_for_runner = bool(protection.get("disable_time_exit_for_runner", True))
                is_runner = bool(mp.get("runner_active", False) or mp.get("runner_protected", False))

                if age_hours >= max_hold_hours and current_qty > 0 and not (disable_time_exit_for_runner and is_runner):
                    resp = exchange.close_position_market(
                        category=category,
                        symbol=symbol,
                        side=side,
                        qty=current_qty,
                    )
                    pretty_print_json(f"TIME EXIT RESPONSE - {symbol}", resp)
                    log_trade_event(
                        event_type="position_time_exit",
                        symbol=symbol,
                        side=side,
                        qty=current_qty,
                        price=current_price,
                        signal_ts=signal_ts_raw,
                        reason="time_exit_max_hold_bars",
                        extra={"response": resp, "age_hours": age_hours, "max_hold_hours": max_hold_hours},
                    )
                    send_telegram_message(
                        f"🔵 TIME EXIT\n"
                        f"Symbol: {symbol}\n"
                        f"Side: {side}\n"
                        f"Qty: {current_qty}\n"
                        f"Price: {current_price}\n"
                        f"RR: {rr:.2f}\n"
                        f"Reason: time_exit_max_hold_bars"
                    )
                    symbols_to_remove.append(symbol)
                    continue
            except Exception:
                pass

        if (not mp.get("be_moved", False)) and rr >= be_after_rr:
            resp = exchange.set_stop_loss_only(
                category=category,
                symbol=symbol,
                stop_loss=entry_price,
                position_idx=0,
                sl_trigger_by="LastPrice",
            )
            mp["be_moved"] = True
            mp["current_stop"] = entry_price
            mp["last_sync_at"] = utc_now_iso()

            pretty_print_json(f"BE MOVE RESPONSE - {symbol}", resp)
            log_trade_event(
                event_type="be_moved",
                symbol=symbol,
                side=side,
                qty=current_qty,
                price=current_price,
                signal_ts=str(mp.get("signal_ts", "")),
                reason=f"be_moved_at_{be_after_rr}r",
                extra={"response": resp, "rr": rr},
            )
            send_telegram_message(
                f"🟡 BE MOVED\n"
                f"Symbol: {symbol}\n"
                f"Side: {side}\n"
                f"Price: {current_price}\n"
                f"RR: {rr:.2f}\n"
                f"Stop -> Entry: {entry_price}"
            )

            # BE 이후 보호 조건이 이미 충족된 경우 즉시 runner_protected 적용 가능하도록 재평가
            register_runner_lifecycle_from_latest_h4_bar(
                exchange=exchange,
                category=category,
                symbol=symbol,
                mp=mp,
                protection=protection,
            )

        for idx, target in enumerate(tp_targets):
            if target.get("done", False):
                continue
            if idx == 0 and bool(mp.get("tp1_exchange_armed", False)):
                continue

            target_rr = float(target.get("rr", 0.0))
            target_frac = float(target.get("frac", 0.0))

            if rr < target_rr:
                continue

            target_qty_abs = original_qty * target_frac
            close_qty, resp = close_absolute_qty(
                exchange=exchange,
                category=category,
                symbol=symbol,
                actual_side=side,
                target_qty=min(target_qty_abs, current_qty),
                asset_cfg=asset_cfg,
            )

            target["done"] = True
            if idx == 0:
                mp["tp1_done"] = True
            elif idx == 1:
                mp["tp2_done"] = True
            elif idx == 2:
                mp["tp3_done"] = True

            if resp is not None and close_qty > 0:
                pretty_print_json(f"{target['name'].upper()} CLOSE RESPONSE - {symbol}", resp)
                event_name = f"{target['name']}_closed"
                if event_name not in {"tp1_closed", "tp2_closed"}:
                    event_name = "tp2_closed"

                log_trade_event(
                    event_type=event_name,
                    symbol=symbol,
                    side=side,
                    qty=close_qty,
                    price=current_price,
                    signal_ts=str(mp.get("signal_ts", "")),
                    reason=target["name"],
                    extra={"response": resp, "rr": rr, "target_rr": target_rr, "target_frac": target_frac},
                )
                send_telegram_message(
                    f"🟠 PARTIAL EXIT\n"
                    f"Symbol: {symbol}\n"
                    f"Side: {side}\n"
                    f"Target: {target['name'].upper()}\n"
                    f"Qty: {close_qty}\n"
                    f"Price: {current_price}\n"
                    f"RR: {rr:.2f}"
                )
                current_qty = max(0.0, current_qty - close_qty)
                mp["remaining_qty_est"] = current_qty
                mp["last_sync_at"] = utc_now_iso()
            else:
                skip_event = "tp1_skip_qty_zero" if idx == 0 else "tp2_skip_qty_zero"
                log_trade_event(
                    event_type=skip_event,
                    symbol=symbol,
                    side=side,
                    qty=current_qty,
                    price=current_price,
                    signal_ts=str(mp.get("signal_ts", "")),
                    reason=f"{target['name']}_qty_zero_after_normalization",
                    extra={"rr": rr, "target_rr": target_rr, "target_frac": target_frac},
                )

        remaining_after_targets = float(mp.get("remaining_qty_est", current_qty))

        if remaining_after_targets > 0 and rr >= trail_activate_rr and not mp.get("runner_announced", False):
            mp["runner_active"] = True
            mp["runner_announced"] = True
            mp["runner_state_badge"] = get_runner_state_badge(mp)
            mp["time_exit_disabled_for_runner"] = bool(protection.get("disable_time_exit_for_runner", True))
            mp["last_sync_at"] = utc_now_iso()
            log_trade_event(
                event_type="runner_active",
                symbol=symbol,
                side=side,
                qty=remaining_after_targets,
                price=current_price,
                signal_ts=str(mp.get("signal_ts", "")),
                reason="runner_trigger_reached",
                extra={"rr": rr, "trail_activate_rr": trail_activate_rr},
            )
            send_telegram_message(
                f"🟣 RUNNER ACTIVE\n"
                f"Symbol: {symbol}\n"
                f"Side: {side}\n"
                f"Qty: {remaining_after_targets}\n"
                f"Price: {current_price}\n"
                f"RR: {rr:.2f}"
            )

        if mp.get("runner_active", False):
            # ★기준조건(2026-07-04): 트레일링 = 백테 엔진 트레일(직전봉 range중점−0.10×H4ATR).
            #   TRAIL_MODE="rratchet" 로 두면 구 R래칫 사용(롤백용).
            if TRAIL_MODE == "backtest":
                try:
                    _ph, _pl, _atr = _last_closed_h4_for_trail(exchange, category, symbol)
                    trailing_stop = calc_backtest_trail_stop(side, entry_price, _ph, _pl, _atr)
                except Exception as _te:
                    trailing_stop = None
                    print(f"[trail/backtest] {symbol} H4 fetch/calc fail: {_te}")
            else:
                trailing_stop = calc_trailing_stop_price(
                    side=side,
                    entry_price=entry_price,
                    risk_per_unit=risk_per_unit,
                    rr=rr,
                    protection=protection,
                    trail_activate_rr=trail_activate_rr,
                )

            if trailing_stop is not None:
                current_stop = mp.get("current_stop")
                # ★ [PATCHED 2026-06-02] 부동소수점 미세차로 인한 SL 재설정 무한루프 방지.
                # BNB 같은 고가 코인은 trailing 계산값(705.8035714...)과 거래소 반올림값(705.80)이
                # 사실상 같은데도 매 루프 "더 유리" 판정 → set_trading_stop → 34040 폭주.
                # 현재 SL 대비 0.05% 이상 유리해질 때만 실제 업데이트한다.
                def _meaningful_improve(new_stop, old_stop, pos_side):
                    try:
                        old_v = float(old_stop); new_v = float(new_stop)
                    except Exception:
                        return True
                    if old_v <= 0:
                        return True
                    rel = abs(new_v - old_v) / old_v
                    if rel < 0.0005:  # 0.05% 미만 차이는 무시 (tick 반올림 노이즈)
                        return False
                    if pos_side == "Buy":
                        return new_v > old_v
                    else:
                        return new_v < old_v
                should_update = False

                if current_stop is None:
                    should_update = True
                else:
                    should_update = _meaningful_improve(trailing_stop, current_stop, side)

                if should_update:
                    resp = exchange.set_stop_loss_only(
                        category=category,
                        symbol=symbol,
                        stop_loss=float(trailing_stop),
                        position_idx=0,
                        sl_trigger_by="LastPrice",
                    )
                    mp["current_stop"] = float(trailing_stop)
                    mp["last_sync_at"] = utc_now_iso()
                    mp["runner_state_badge"] = get_runner_state_badge(mp)

                    pretty_print_json(f"RUNNER TRAIL RESPONSE - {symbol}", resp)
                    log_trade_event(
                        event_type="runner_trailing_stop_updated",
                        symbol=symbol,
                        side=side,
                        qty=remaining_after_targets,
                        price=current_price,
                        signal_ts=str(mp.get("signal_ts", "")),
                        reason="runner_trailing_stop_updated",
                        extra={"response": resp, "rr": rr, "new_stop": trailing_stop},
                    )

    for symbol in symbols_to_remove:
        managed_positions.pop(symbol, None)


def try_sync_fill_after_order(
    exchange: BybitExchange,
    category: str,
    symbol: str,
    expected_side: str,
    min_qty: float = 0.0,
    retries: int = 10,
    sleep_seconds: float = 0.7,
) -> dict | None:
    return exchange.wait_for_position_fill_info(
        category=category,
        symbol=symbol,
        expected_side=expected_side,
        min_qty=min_qty,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )


# ============================================================
# v2.2: Zone-Proximity Trigger Helpers
# ============================================================
def _build_zone_cache_for_symbol(exchange, symbol: str) -> list:
    """
    한 symbol 의 active zone 들을 fetch + 평가해서 light cache 형태로 반환.
    무거운 작업이지만 1시간에 1번만 실행.
    """
    df_h4 = exchange.get_recent_klines_df(
        category=CATEGORY, symbol=symbol, interval=H4_INTERVAL, limit=H4_LIMIT
    )
    df_h1_raw = exchange.get_recent_klines_df(
        category=CATEGORY, symbol=symbol, interval=H1_INTERVAL, limit=H1_LIMIT
    )
    df_h1_p = _prepare_h1_for_zone(df_h1_raw.copy())
    df_struct, structures, _ = _build_structures_for_zone(_prepare_h4_for_zone(df_h4.copy()))
    i = len(df_struct) - 2
    active_structures = [
        s for s in structures
        if s["zone_created_idx"] <= i <= s["expire_idx"]
        and s["score"] >= _RELAX_MIN_SCORE_FOR_ZONE
    ]
    evaluated_zones = _evaluate_zones_for_zone(
        df_h4=df_struct,
        df_h1=df_h1_p,
        active_structures=active_structures,
        i=i,
        exclude_recent_h1=_EXCLUDE_RECENT_H1_FOR_ZONE,
        symbol=symbol,
    )
    # Light cache: zone_low/high + 메타만 (가격 비교에 필요한 정보)
    light_zones = []
    for z in evaluated_zones:
        light_zones.append({
            "zone_low": float(z["zone_low"]),
            "zone_high": float(z["zone_high"]),
            "type": z.get("type", ""),
            "tier": z.get("tier", ""),
            "tier_passable": bool(z.get("tier_passable", False)),
        })
    # 또한 control_panel 표시용 풀 zone 정보도 같이 cache (pickle 저장)
    return {
        "light_zones": light_zones,
        "full_evaluated_zones": evaluated_zones,
        "active_structures": active_structures,
        "h4_trend": str(df_struct.iloc[i].get("trend", "?")) if len(df_struct) > i else "?",
        "h4_idx": int(i),
    }


def _save_zone_cache_to_pickle(zone_cache_full: dict, current_prices: dict) -> None:
    """control_panel 이 read 할 pickle 파일 저장 (atomic)."""
    try:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "zones_cache.pkl")
        cache_tmp = cache_path + ".tmp"
        # control_panel 이 기대하는 구조로 변환
        snapshot = {}
        for symbol, full in zone_cache_full.items():
            snapshot[symbol] = {
                "computed_at": utc_now_iso(),
                "current_close": float(current_prices.get(symbol, 0.0)),
                "h4_trend": full.get("h4_trend", "?"),
                "h4_idx": full.get("h4_idx", -1),
                "active_structures": full.get("active_structures", []),
                "evaluated_zones": full.get("full_evaluated_zones", []),
                "df_1m_recent_tail5": [],  # light loop 에선 1m fetch 안 함 (cache 재생성 시점에만)
                "has_position": False,
                "position_side": "",
                "position_qty": 0.0,
            }
        with open(cache_tmp, "wb") as f:
            _pickle_for_zone.dump({
                "_meta": {
                    "saved_at": utc_now_iso(),
                    "n_symbols": len(snapshot),
                    "ttl_seconds": ZONE_CACHE_REFRESH_SECONDS + 600,
                },
                "snapshot": snapshot,
            }, f)
        os.replace(cache_tmp, cache_path)
    except Exception as e:
        print(f"[zone cache] save failed: {e}")


def _is_price_near_any_zone(price: float, light_zones: list, proximity_pct: float) -> tuple:
    """
    가격이 light_zones 중 하나라도 ±proximity_pct% 이내면 (True, zone) 반환.
    """
    margin = proximity_pct / 100.0
    for z in light_zones:
        zlo = z["zone_low"] * (1 - margin)
        zhi = z["zone_high"] * (1 + margin)
        if zlo <= price <= zhi:
            return True, z
    return False, None


def main() -> None:
    print("프로그램 시작 - 기준 엔진 반영 실거래 실행 버전")

    load_dotenv()

    settings = load_live_settings()
    api_key, api_secret, use_testnet, use_demo = resolve_api_credentials(settings)

    if not api_key or not api_secret:
        msg = "ERROR: live_settings.json 또는 .env에 API 키/시크릿이 없습니다."
        print(msg)
        send_telegram_message(f"🚨 ENGINE ERROR\n{msg}")
        return

    exchange = BybitExchange(
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
        use_demo=use_demo,
    )

    state = load_state()
    ensure_system_state(state)
    managed_positions = ensure_managed_positions(state)

    # 패널 상태 동기화
    system_state = ensure_system_state(state)
    system_state["engine_running"] = True
    system_state["engine_pid"] = os.getpid()
    system_state["engine_started_at"] = system_state.get("engine_started_at") or utc_now_iso()
    system_state["engine_stopped_at"] = None
    system_state["last_action"] = "MAIN STARTED"
    system_state.setdefault("watchdog_enabled", True)
    system_state.setdefault("watchdog_running", False)
    system_state.setdefault("watchdog_pid", None)
    system_state.setdefault("watchdog_last_check", None)
    save_state(state)

    # v2.2: Zone-Proximity Trigger 상태 변수
    zone_cache_full = {}  # {symbol: {light_zones, full_evaluated_zones, active_structures, h4_trend, h4_idx}}
    last_zone_refresh = 0.0
    if USE_ZONE_PROXIMITY_TRIGGER:
        print(f"★ v2.2 USE_ZONE_PROXIMITY_TRIGGER: True")
        print(f"   - Light loop sleep: {LIGHT_LOOP_SLEEP_SECONDS}s")
        print(f"   - Zone proximity: ±{ZONE_PROXIMITY_PCT}%")
        print(f"   - Zone cache refresh: {ZONE_CACHE_REFRESH_SECONDS}s ({ZONE_CACHE_REFRESH_SECONDS/3600:.1f}h)")
    else:
        print(f"★ v2.2 USE_ZONE_PROXIMITY_TRIGGER: False (legacy mode - 매 LOOP 풀 분석)")

    while True:
        try:
            # 패널에서 stop 요청했는지 최신 state 다시 읽음
            state = load_state()
            system_state = ensure_system_state(state)
            managed_positions = ensure_managed_positions(state)

            if bool(system_state.get("stop_requested", False)):
                system_state["engine_running"] = False
                system_state["engine_stopped_at"] = utc_now_iso()
                system_state["last_action"] = "STOP REQUESTED"
                save_state(state)
                print_title("STOP REQUESTED")
                print("control_panel 에서 stop 요청 -> main 종료")
                return

            settings = load_live_settings()
            assets = get_assets(settings)
            portfolio = get_portfolio_settings(settings)
            protection = get_protection_settings(settings)
            execution = get_execution_settings(settings)

            max_open_positions = int(portfolio.get("max_open_positions", 3))
            orderbook_limit = int(execution.get("orderbook_limit", 50))
            poll_fill_timeout_sec = int(execution.get("poll_fill_timeout_sec", 8))

            trading_enabled = bool(system_state.get("trading_enabled", True))
            kill_switch = bool(system_state.get("kill_switch", False))
            emergency_close_all = bool(system_state.get("emergency_close_all", False))

            system_state["last_loop_time"] = utc_now_iso()
            system_state["last_error"] = None
            system_state["last_action"] = "LOOP START"
            save_state(state)

            print_title("LOOP START")

            system_state["last_action"] = "SERVER TIME"
            save_state(state)
            server_time = safe_api_call(lambda: exchange.get_server_time(), label="get_server_time")
            pretty_print_json("Bybit Server Time", server_time)

            system_state["last_action"] = "WALLET SYNC"
            save_state(state)
            wallet = safe_api_call(lambda: exchange.get_wallet_balance(account_type="UNIFIED", coin="USDT"), label="get_wallet_balance")
            balance = get_latest_balance_usdt(wallet)
            pretty_print_json("Wallet Balance", wallet)

            system_state["last_action"] = "POSITIONS SYNC"
            save_state(state)
            all_positions = safe_api_call(lambda: exchange.get_positions(category=CATEGORY, symbol=None), label="get_positions_initial")
            pretty_print_json("All Current Positions", all_positions)

            open_positions_map = extract_open_positions_map(all_positions)

            rebuild_managed_positions_from_exchange(
                state=state,
                managed_positions=managed_positions,
                open_positions_map=open_positions_map,
                exchange=exchange,
                category=CATEGORY,
            )
            refresh_runtime_snapshots(
                state=state,
                open_positions_map=open_positions_map,
                managed_positions=managed_positions,
            )

            print_title("PORTFOLIO STATUS")
            print(f"mode={get_mode(settings)}")
            print(f"use_demo={use_demo}")
            print(f"use_testnet={use_testnet}")
            print(f"open_positions={count_open_positions(open_positions_map)}")
            print(f"current_total_open_risk_pct={calc_total_open_risk_pct(open_positions_map, assets):.4f}  (info-only, no cap)")
            print(f"max_open_positions={max_open_positions}")
            print(f"trading_enabled={trading_enabled}")
            print(f"kill_switch={kill_switch}")
            print(f"emergency_close_all={emergency_close_all}")
            print(f"position_management_enabled={bool(protection.get('position_management_enabled', True))}")

            if emergency_close_all:
                system_state["last_action"] = "EMERGENCY CLOSE ALL"
                save_state(state)
                handle_emergency_close_all(
                    exchange=exchange,
                    category=CATEGORY,
                    open_positions_map=open_positions_map,
                    system_state=system_state,
                    managed_positions=managed_positions,
                )
                refresh_runtime_snapshots(
                    state=state,
                    open_positions_map={},
                    managed_positions=managed_positions,
                )
                save_state(state)
                time.sleep(LOOP_SLEEP_SECONDS)
                continue

            system_state["last_action"] = "MANAGE OPEN POSITIONS"
            save_state(state)
            manage_open_positions(
                exchange=exchange,
                category=CATEGORY,
                open_positions_map=open_positions_map,
                managed_positions=managed_positions,
                assets=assets,
                protection=protection,
            )

            system_state["last_action"] = "REFRESH POSITIONS"
            save_state(state)
            refreshed_positions = safe_api_call(lambda: exchange.get_positions(category=CATEGORY, symbol=None), label="get_positions_refresh")
            open_positions_map = extract_open_positions_map(refreshed_positions)

            rebuild_managed_positions_from_exchange(
                state=state,
                managed_positions=managed_positions,
                open_positions_map=open_positions_map,
                exchange=exchange,
                category=CATEGORY,
            )
            refresh_runtime_snapshots(
                state=state,
                open_positions_map=open_positions_map,
                managed_positions=managed_positions,
            )
            save_state(state)

            # ============================================================
            # v2.2 Zone-Proximity Trigger
            # ============================================================
            if USE_ZONE_PROXIMITY_TRIGGER:
                # === [Step 1] Zone cache 갱신 (1시간마다 또는 시작 시 비어있으면) ===
                _now = time.time()
                if (_now - last_zone_refresh) > ZONE_CACHE_REFRESH_SECONDS or not zone_cache_full:
                    print_title("ZONE CACHE REFRESH")
                    system_state["last_action"] = "ZONE CACHE REFRESH"
                    save_state(state)
                    _refresh_started = _now
                    _failed_symbols = []
                    for _sym, _cfg in assets.items():
                        if not _cfg.get("enabled", False):
                            continue
                        try:
                            zone_cache_full[_sym] = _build_zone_cache_for_symbol(exchange, _sym)
                            _n = len(zone_cache_full[_sym]["light_zones"])
                            print(f"  [zone cache] {_sym}: {_n} zones")
                        except Exception as _ze:
                            _failed_symbols.append(_sym)
                            print(f"  [zone cache] {_sym}: failed - {_ze}")
                    last_zone_refresh = _now
                    _refresh_dur = time.time() - _refresh_started
                    print(f"[zone cache] refresh done in {_refresh_dur:.1f}s, failed={len(_failed_symbols)}")

                # === [Step 2] Light loop: 가격 polling 으로 hot symbols 식별 ===
                _hot_symbols = []
                _current_prices = {}
                for _sym, _cfg in assets.items():
                    if not _cfg.get("enabled", False):
                        continue
                    # 포지션 있으면 진입 분석은 skip (포지션 관리는 따로)
                    _pos = open_positions_map.get(_sym, {"has_position": False})
                    if _pos.get("has_position"):
                        continue
                    try:
                        _price = exchange.get_last_price(category=CATEGORY, symbol=_sym)
                        _current_prices[_sym] = float(_price)
                    except Exception as _pe:
                        print(f"  [price] {_sym}: failed - {_pe}")
                        continue
                    _light_zones = zone_cache_full.get(_sym, {}).get("light_zones", [])
                    if not _light_zones:
                        continue
                    _is_hot, _matched_zone = _is_price_near_any_zone(_price, _light_zones, ZONE_PROXIMITY_PCT)
                    if _is_hot:
                        _hot_symbols.append(_sym)
                        print(f"  [HOT] {_sym} price={_price} near zone {_matched_zone['zone_low']:.4f}~{_matched_zone['zone_high']:.4f} ({_matched_zone['type']})")

                # === [Step 3] Pickle cache 저장 (control_panel read 용) ===
                _save_zone_cache_to_pickle(zone_cache_full, _current_prices)

                if not _hot_symbols:
                    print(f"[light loop] no hot symbols (all {len(_current_prices)} symbols far from zones) -> SLEEP {LIGHT_LOOP_SLEEP_SECONDS}s")
                    system_state["last_action"] = f"LIGHT SLEEP - {LIGHT_LOOP_SLEEP_SECONDS}s"
                    save_state(state)
                    time.sleep(LIGHT_LOOP_SLEEP_SECONDS)
                    continue  # 다음 main loop iteration

                print(f"[light loop] {len(_hot_symbols)} hot symbols: {_hot_symbols}")
            else:
                _hot_symbols = list(assets.keys())  # legacy mode: 모두 처리

            # ============================================================
            # SYMBOL_LOOP - hot_symbols 만 풀 분석 (또는 legacy mode 면 전체)
            # ============================================================

            # ★ v4: BTC 레짐(btc_zone) 갱신 — 심볼 루프 전 1회 (v4 3중게이트용)
            try:
                _v4_btc_h4 = exchange.get_recent_klines_df(category=CATEGORY, symbol="BTCUSDT", interval=H4_INTERVAL, limit=H4_LIMIT)
                _v4_set_btc_regime(_v4_btc_h4)
            except Exception as _v4_e:
                print(f"[v4] BTC regime update failed: {_v4_e}")

            for symbol, asset_cfg in assets.items():
                try:
                    state = load_state()
                    system_state = ensure_system_state(state)
                    managed_positions = ensure_managed_positions(state)
                    symbol_state = ensure_symbol_state(state, symbol)

                    system_state["last_loop_time"] = utc_now_iso()
                    system_state["last_action"] = f"SIGNAL SCAN - {symbol}"
                    save_state(state)

                    print_title(f"SYMBOL LOOP - {symbol}")

                    if not asset_cfg.get("enabled", False):
                        print(f"{symbol}: disabled -> skip")
                        continue

                    # v2.2: hot symbols 가 아니면 진입 분석 skip (포지션 관리는 아래서 수행)
                    if USE_ZONE_PROXIMITY_TRIGGER and symbol not in _hot_symbols:
                        # zone 근처 아님 -> 풀 분석 skip
                        # 그러나 포지션 있으면 management 는 진행해야 하니 아래 logic 으로 분기
                        pos_info = open_positions_map.get(symbol, {
                            "has_position": False, "side": "", "qty": 0.0, "raw": None,
                        })
                        if not pos_info["has_position"]:
                            # 포지션 없고 hot 도 아니면 완전 skip
                            continue
                        # 포지션 있으면 아래로 흘려보내서 management 만 처리되도록
                        # (기존 코드: `if pos_info["has_position"]: continue` 가 있어서 자연스럽게 처리됨)

                    pos_info = open_positions_map.get(symbol, {
                        "has_position": False,
                        "side": "",
                        "qty": 0.0,
                        "raw": None,
                    })

                    if pos_info["has_position"]:
                        print(f"{symbol}: position exists -> side={pos_info['side']}, qty={pos_info['qty']}")
                        continue

                    # 청산 후 재진입 쿨다운 체크
                    from datetime import datetime, timezone as tz
                    _last_exit = symbol_state.get("last_exit_time")
                    if _last_exit:
                        try:
                            _exit_dt = datetime.fromisoformat(_last_exit)
                            _elapsed_hours = (datetime.now(tz.utc) - _exit_dt).total_seconds() / 3600
                            if _elapsed_hours < EXIT_COOLDOWN_HOURS:
                                _remain = EXIT_COOLDOWN_HOURS - _elapsed_hours
                                print(f"{symbol}: cooldown active ({_elapsed_hours:.1f}h elapsed, {_remain:.1f}h remaining)")
                                continue
                        except Exception:
                            pass

                    df_h4 = safe_api_call(
                        lambda: exchange.get_recent_klines_df(
                            category=CATEGORY,
                            symbol=symbol,
                            interval=H4_INTERVAL,
                            limit=H4_LIMIT,
                        ),
                        label=f"get_recent_klines_df_h4_{symbol}",
                    )
                    df_h1 = safe_api_call(
                        lambda: exchange.get_recent_klines_df(
                            category=CATEGORY,
                            symbol=symbol,
                            interval=H1_INTERVAL,
                            limit=H1_LIMIT,
                        ),
                        label=f"get_recent_klines_df_h1_{symbol}",
                    )
                    # ⭐ v2.0_WICK: 1분봉 fetch (wick touch 감지용)
                    # 최근 10 개 1분봉만 필요 (lookback 5 + margin)
                    df_1m = None
                    try:
                        df_1m = safe_api_call(
                            lambda: exchange.get_recent_klines_df(
                                category=CATEGORY,
                                symbol=symbol,
                                interval="1",
                                limit=10,
                            ),
                            label=f"get_recent_klines_df_1m_{symbol}",
                        )
                    except Exception as e:
                        print(f"{symbol} 1m fetch failed (wick touch 비활성): {e}")
                        df_1m = None

                    print(f"{symbol} H4 rows: {len(df_h4)}")
                    print(f"{symbol} H1 rows: {len(df_h1)}")
                    print(f"{symbol} H4 latest: {df_h4['timestamp'].iloc[-1]}")
                    print(f"{symbol} H1 latest: {df_h1['timestamp'].iloc[-1]}")
                    if df_1m is not None and len(df_1m) > 0:
                        print(f"{symbol} 1m rows: {len(df_1m)}, latest: {df_1m['timestamp'].iloc[-1]}")
                    print(f"USDT balance: {balance}")

                    # 실시간 zone touch 감지를 위해 현재가 조회
                    current_price = safe_api_call(
                        lambda: exchange.get_last_price(category=CATEGORY, symbol=symbol),
                        label=f"get_last_price_{symbol}",
                    )
                    print(f"{symbol} current price: {current_price}")

                    entry_signal = generate_entry_signal(
                        df_h4_raw=df_h4,
                        df_h1_raw=df_h1,
                        balance=balance,
                        risk_pct=float(asset_cfg["risk_pct"]),
                        fee_rate=FEE_RATE,
                        max_notional_mult=MAX_NOTIONAL_MULT,
                        current_price=current_price,
                        last_exit_time_iso=symbol_state.get("last_exit_time"),
                        last_exit_side=symbol_state.get("last_exit_side"),
                        risk_multiplier=float(portfolio.get("risk_multiplier", 1.0)),
                        df_1m_raw=df_1m,
                        symbol=symbol,
                    )

                    pretty_print_json(f"LIVE SIGNAL RESULT - {symbol}", entry_signal)

                    symbol_state["last_signal_timestamp"] = entry_signal.get("timestamp")
                    symbol_state["last_signal_side"] = entry_signal.get("side")
                    symbol_state["last_signal_payload"] = entry_signal
                    save_state(state)

                    log_trade_event(
                        event_type="signal_checked",
                        symbol=symbol,
                        side=str(entry_signal.get("side", "")),
                        signal_ts=str(entry_signal.get("timestamp", "")),
                        reason=str(entry_signal.get("reason", "")),
                        extra={"signal": entry_signal},
                    )

                    if not entry_signal.get("should_enter"):
                        print(f"{symbol}: no signal")
                        continue

                    signal_ts = str(entry_signal.get("timestamp"))
                    signal_side = str(entry_signal.get("side"))

                    # v1.9b TIER 로그 (진입 확정 시 티어 정보 기록)
                    if entry_signal.get("tier"):
                        log_trade_event(
                            event_type="tier_classified",
                            symbol=symbol,
                            side=signal_side,
                            signal_ts=signal_ts,
                            reason=f"tier_{entry_signal.get('tier')}",
                            extra={
                                "tier": entry_signal.get("tier"),
                                "tier_mult": entry_signal.get("tier_mult"),
                                "pre_total": entry_signal.get("tier_pre_total"),
                                "sweep_count": entry_signal.get("tier_sweep_count"),
                                "fvg_count": entry_signal.get("tier_fvg_count"),
                                "ob_count": entry_signal.get("tier_ob_count"),
                                "wick_ratio_5": entry_signal.get("tier_wick_ratio_5"),
                                "score": entry_signal.get("score"),
                                "risk_pct_base": entry_signal.get("risk_pct_base"),
                                "risk_pct_adjusted": entry_signal.get("risk_pct_tier_adjusted"),
                            },
                        )

                    if not is_side_allowed(signal_side, asset_cfg):
                        print(f"{symbol}: side not allowed -> {signal_side}")
                        continue

                    if is_duplicate_signal(symbol_state, signal_ts, signal_side):
                        print(f"{symbol}: duplicate signal -> skipped")
                        continue

                    can_enter, reject_reason = can_open_new_position(
                        symbol=symbol,
                        asset_cfg=asset_cfg,
                        open_positions_map=open_positions_map,
                        trading_enabled=trading_enabled,
                        kill_switch=kill_switch,
                        assets=assets,
                        max_open_positions=max_open_positions,
                    )

                    print_title(f"RISK CHECK - {symbol}")
                    print(f"can_enter={can_enter}")
                    print(f"reason={reject_reason}")

                    if not can_enter:
                        log_trade_event(
                            event_type="risk_check_rejected",
                            symbol=symbol,
                            side=signal_side,
                            signal_ts=signal_ts,
                            reason=reject_reason,
                        )
                        continue

                    raw_qty = float(entry_signal.get("qty", 0.0))
                    order_qty = normalize_qty(
                        qty=raw_qty,
                        qty_step=float(asset_cfg["qty_step"]),
                        min_order_qty=float(asset_cfg["min_order_qty"]),
                        qty_decimals=int(asset_cfg["qty_decimals"]),
                    )

                    print_title(f"ORDER CHECK - {symbol}")
                    print(f"raw_qty={raw_qty}")
                    print(f"normalized_qty={order_qty}")
                    print(f"risk_pct={asset_cfg['risk_pct']}")

                    if order_qty <= 0:
                        print(f"{symbol}: normalized qty <= 0 -> skip")
                        continue

                    expected_signal_entry = safe_float(entry_signal.get("entry"), 0.0)
                    signal_risk_per_unit = get_signal_risk_per_unit(entry_signal)

                    system_state["last_action"] = f"ORDERBOOK ESTIMATE - {symbol}"
                    save_state(state)
                    expected_orderbook_price = safe_api_call(
                        lambda: exchange.estimate_market_fill_price(
                            category=CATEGORY,
                            symbol=symbol,
                            side=signal_side,
                            qty=order_qty,
                            limit=orderbook_limit,
                        ),
                        label=f"estimate_market_fill_price_{symbol}",
                    )

                    system_state["last_action"] = f"ORDER SUBMIT - {symbol}"
                    save_state(state)
                    order_resp = safe_api_call(
                        lambda: exchange.place_market_order(
                            category=CATEGORY,
                            symbol=symbol,
                            side=signal_side,
                            qty=order_qty,
                        ),
                        label=f"place_market_order_{symbol}",
                    )

                    pretty_print_json(f"ORDER RESPONSE - {symbol}", order_resp)

                    symbol_state["last_order_signal_timestamp"] = signal_ts
                    symbol_state["last_order_side"] = signal_side
                    symbol_state["last_order_response"] = order_resp

                    log_trade_event(
                        event_type="order_submitted",
                        symbol=symbol,
                        side=signal_side,
                        qty=order_qty,
                        signal_ts=signal_ts,
                        reason="order_submitted",
                        extra={
                            "response": order_resp,
                            "expected_signal_entry": expected_signal_entry,
                            "expected_orderbook_price": expected_orderbook_price,
                            "tp_plan_name": entry_signal.get("tp_plan_name"),
                            "tp_plan": entry_signal.get("tp_plan"),
                        },
                    )

                    system_state["last_action"] = f"FILL SYNC - {symbol}"
                    save_state(state)
                    fill_info = try_sync_fill_after_order(
                        exchange=exchange,
                        category=CATEGORY,
                        symbol=symbol,
                        expected_side=signal_side,
                        min_qty=order_qty,
                        retries=max(8, poll_fill_timeout_sec),
                        sleep_seconds=0.7,
                    )

                    managed_pos = None

                    if fill_info is not None:
                        filled_qty = float(fill_info.get("qty", order_qty))
                        filled_price = safe_float(fill_info.get("avg_price"), 0.0) or expected_orderbook_price
                        slippage_pct = calc_slippage_pct(
                            side=signal_side,
                            expected_price=expected_orderbook_price,
                            filled_price=filled_price,
                        )

                        actual_sl = calc_actual_stop_from_fill(
                            side=signal_side,
                            filled_price=filled_price,
                            signal_risk_per_unit=signal_risk_per_unit,
                        )

                        managed_pos = build_managed_position(
                            symbol=symbol,
                            signal_side=signal_side,
                            order_qty=filled_qty,
                            signal_ts=signal_ts,
                            filled_price=filled_price,
                            expected_price=expected_orderbook_price,
                            slippage_pct=slippage_pct,
                            actual_sl=actual_sl,
                            signal_payload=entry_signal,
                            management_enabled=(actual_sl is not None and signal_risk_per_unit > 0),
                            recovered=False,
                            awaiting_fill_sync=False,
                            entry_source="exchange_avg_price_after_order",
                        )
                        managed_positions[symbol] = managed_pos

                        symbol_state["last_fill_snapshot"] = fill_info

                        log_trade_event(
                            event_type="order_filled",
                            symbol=symbol,
                            side=signal_side,
                            qty=filled_qty,
                            price=filled_price,
                            signal_ts=signal_ts,
                            reason="order_filled_from_exchange_position",
                            extra={
                                "expected_signal_entry": expected_signal_entry,
                                "expected_orderbook_price": expected_orderbook_price,
                                "filled_price": filled_price,
                                "slippage_pct": slippage_pct,
                                "actual_sl": actual_sl,
                                "signal_risk_per_unit": signal_risk_per_unit,
                                "fill_sync_source": "exchange_position_avg_price",
                                "order_response": order_resp,
                                "fill_info": fill_info,
                                "tp_plan_name": entry_signal.get("tp_plan_name"),
                                "tp_plan": entry_signal.get("tp_plan"),
                            },
                        )
                        # ⭐⭐ Stage 4K: trade_journal 에 진입 기록 (sentiment lookback 데이터 소스) ⭐⭐
                        try:
                            upsert_trade_journal(
                                symbol=symbol,
                                signal_ts=signal_ts,
                                fields={
                                    "side": "long" if signal_side == "Buy" else "short",
                                    "side_raw": signal_side,
                                    "entry_price": float(filled_price) if filled_price is not None else None,
                                    "qty": float(filled_qty),
                                    "sl": float(actual_sl) if actual_sl is not None else None,
                                    # 4K sentiment 측정 핵심 필드
                                    "run_potential": int(entry_signal.get("run_potential")) if entry_signal.get("run_potential") is not None else None,
                                    "tier": str(entry_signal.get("tier", "") or ""),
                                    "tier_mult": float(entry_signal.get("tier_mult")) if entry_signal.get("tier_mult") is not None else None,
                                    "rp_action": str(entry_signal.get("rp_action", "") or ""),
                                    "stage4j_mult": float(entry_signal.get("stage4j_mult", 1.0)),
                                    "stage4j_label": str(entry_signal.get("stage4j_label", "DEFAULT")),
                                    "sentiment_mult": float(entry_signal.get("sentiment_mult", 1.0)),
                                    "sentiment_label": str(entry_signal.get("sentiment_label", "no_data")),
                                    "tp_plan_name": str(entry_signal.get("tp_plan_name", "")),
                                    "score": float(entry_signal.get("score", 0.0)),
                                    "grade": str(entry_signal.get("grade", "")),
                                },
                            )
                        except Exception as e:
                            print(f"trade_journal upsert error: {e}")
                        send_telegram_message(
                            f"🟢 ENTRY FILLED\n"
                            f"Symbol: {symbol}\n"
                            f"Side: {signal_side}\n"
                            f"Qty: {filled_qty}\n"
                            f"Expected: {expected_orderbook_price}\n"
                            f"Filled: {filled_price}\n"
                            f"Slippage: {slippage_pct if slippage_pct is not None else 'N/A'}%\n"
                            f"SL: {actual_sl if actual_sl is not None else 'N/A'}\n"
                            f"Plan: {entry_signal.get('tp_plan_name', '')}"
                        )

                        open_positions_map[symbol] = {
                            "has_position": True,
                            "side": signal_side,
                            "qty": filled_qty,
                            "raw": fill_info.get("raw", {}),
                        }
                    else:
                        managed_pos = build_managed_position(
                            symbol=symbol,
                            signal_side=signal_side,
                            order_qty=order_qty,
                            signal_ts=signal_ts,
                            filled_price=None,
                            expected_price=expected_orderbook_price,
                            slippage_pct=None,
                            actual_sl=None,
                            signal_payload=entry_signal,
                            management_enabled=False,
                            recovered=False,
                            awaiting_fill_sync=True,
                            entry_source="awaiting_exchange_fill_sync",
                        )
                        managed_positions[symbol] = managed_pos

                        log_trade_event(
                            event_type="order_fill_sync_pending",
                            symbol=symbol,
                            side=signal_side,
                            qty=order_qty,
                            signal_ts=signal_ts,
                            reason="order_submitted_but_fill_not_synced_yet",
                            extra={
                                "expected_signal_entry": expected_signal_entry,
                                "expected_orderbook_price": expected_orderbook_price,
                                "signal_risk_per_unit": signal_risk_per_unit,
                                "order_response": order_resp,
                                "tp_plan_name": entry_signal.get("tp_plan_name"),
                                "tp_plan": entry_signal.get("tp_plan"),
                            },
                        )
                        send_telegram_message(
                            f"🟡 ORDER SUBMITTED / FILL PENDING\n"
                            f"Symbol: {symbol}\n"
                            f"Side: {signal_side}\n"
                            f"Qty: {order_qty}\n"
                            f"Expected: {expected_orderbook_price}"
                        )

                        position_resp = safe_api_call(
                            lambda: exchange.get_position_by_symbol(category=CATEGORY, symbol=symbol),
                            label=f"get_position_by_symbol_{symbol}",
                        )
                        synced_map = extract_open_positions_map(position_resp)
                        if symbol in synced_map:
                            open_positions_map[symbol] = synced_map[symbol]
                        else:
                            open_positions_map[symbol] = {
                                "has_position": True,
                                "side": signal_side,
                                "qty": order_qty,
                                "raw": {
                                    "symbol": symbol,
                                    "side": signal_side,
                                    "size": order_qty,
                                    "source": "local_post_order_pending_sync",
                                },
                            }

                    if managed_pos is not None and managed_pos.get("current_stop") is not None:
                        system_state["last_action"] = f"INITIAL SL - {symbol}"
                        save_state(state)
                        initial_sl_resp = attach_initial_stop_loss(
                            exchange=exchange,
                            category=CATEGORY,
                            symbol=symbol,
                            managed_pos=managed_pos,
                        )
                        if initial_sl_resp is not None:
                            pretty_print_json(f"INITIAL SL RESPONSE - {symbol}", initial_sl_resp)
                            log_trade_event(
                                event_type="initial_sl_attached",
                                symbol=symbol,
                                side=signal_side,
                                qty=order_qty,
                                signal_ts=signal_ts,
                                reason="initial_stop_loss_attached",
                                extra={"response": initial_sl_resp, "actual_sl": managed_pos.get("current_stop")},
                            )

                    if managed_pos is not None and managed_pos.get("management_enabled", False):
                        system_state["last_action"] = f"TP1 LIMIT - {symbol}"
                        save_state(state)
                        tp1_resp = attach_tp1_limit_order(
                            exchange=exchange,
                            category=CATEGORY,
                            symbol=symbol,
                            managed_pos=managed_pos,
                            asset_cfg=asset_cfg,
                        )
                        if tp1_resp is not None:
                            pretty_print_json(f"TP1 LIMIT RESPONSE - {symbol}", tp1_resp)
                            symbol_state["last_tp1_order_response"] = tp1_resp
                            log_trade_event(
                                event_type="tp1_limit_submitted",
                                symbol=symbol,
                                side=signal_side,
                                qty=managed_pos.get("tp1_exchange_qty"),
                                price=managed_pos.get("tp1_exchange_price"),
                                signal_ts=signal_ts,
                                reason="tp1_limit_submitted",
                                extra={"response": tp1_resp, "order_id": managed_pos.get("tp1_exchange_order_id", "")},
                            )

                    save_state(state)

                    refresh_runtime_snapshots(
                        state=state,
                        open_positions_map=open_positions_map,
                        managed_positions=managed_positions,
                    )
                    save_state(state)

                    system_state["last_action"] = f"ORDER COMPLETE - {symbol}"
                    save_state(state)

                    print_title(f"ORDER SUBMITTED - {symbol}")
                    print("자동 진입 주문 완료")

                except Exception as symbol_error:
                    system_state["last_error"] = f"{symbol}: {str(symbol_error)}"
                    system_state["last_action"] = f"SYMBOL ERROR - {symbol}"
                    save_state(state)

                    log_system_event(
                        event_type="symbol_error",
                        symbol=symbol,
                        message=str(symbol_error),
                    )
                    send_telegram_message(
                        f"🚨 SYMBOL ERROR\n"
                        f"Symbol: {symbol}\n"
                        f"Error: {str(symbol_error)}"
                    )

                    print_title(f"SYMBOL ERROR - {symbol}")
                    print(str(symbol_error))
                    continue

            # v2.2: zone proximity mode 면 light sleep, legacy 면 기존 sleep
            _sleep_secs = LIGHT_LOOP_SLEEP_SECONDS if USE_ZONE_PROXIMITY_TRIGGER else LOOP_SLEEP_SECONDS
            system_state["last_action"] = f"SLEEP - {_sleep_secs}s"
            system_state["last_loop_time"] = utc_now_iso()
            save_state(state)
            time.sleep(_sleep_secs)

        except Exception as e:
            system_state = ensure_system_state(state)
            system_state["last_error"] = str(e)
            system_state["last_action"] = "ERROR"
            save_state(state)

            log_system_event(
                event_type="main_loop_error",
                message=str(e),
            )
            send_telegram_message(f"🚨 MAIN LOOP ERROR\n{str(e)}")

            print_title("ERROR")
            print(str(e))
            _err_sleep = LIGHT_LOOP_SLEEP_SECONDS if USE_ZONE_PROXIMITY_TRIGGER else LOOP_SLEEP_SECONDS
            time.sleep(_err_sleep)


if __name__ == "__main__":
    main()