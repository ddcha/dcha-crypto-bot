from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from config_kis import TRADING_ENABLED_DEFAULT, KILL_SWITCH_DEFAULT

STATE_FILE = Path("runtime_state.json")


def _default_symbol_state() -> Dict[str, Any]:
    return {
        "last_signal_timestamp": None,
        "last_signal_side": None,
        "last_signal_payload": None,
        "last_order_signal_timestamp": None,
        "last_order_side": None,
        "last_order_response": None,
        "last_fill_snapshot": None,
        "last_tp1_order_response": None,
        "last_tp1_fill_snapshot": None,
    }


def _default_system_state() -> Dict[str, Any]:
    return {
        "trading_enabled": TRADING_ENABLED_DEFAULT,
        "kill_switch": KILL_SWITCH_DEFAULT,
        "emergency_close_all": False,
        "last_emergency_close_all_at": None,
        "last_loop_time": None,
        "last_error": None,
        "engine_running": False,
        "engine_pid": None,
        "engine_started_at": None,
        "engine_stopped_at": None,
        "stop_requested": False,
        "last_action": None,
        "last_system_check": {},
    }


def _default_state() -> Dict[str, Any]:
    return {
        "system": _default_system_state(),
        "symbols": {},
        "managed_positions": {},
        "latest_open_positions": {},
        "exchange_positions": {},
        "engine_positions_view": {},
    }


def ensure_system_state(state: Dict[str, Any]) -> Dict[str, Any]:
    if "system" not in state or not isinstance(state["system"], dict):
        state["system"] = _default_system_state()
    defaults = _default_system_state()
    for k, v in defaults.items():
        state["system"].setdefault(k, v)
    return state["system"]


def ensure_symbol_state(state: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    ensure_system_state(state)
    if "symbols" not in state or not isinstance(state["symbols"], dict):
        state["symbols"] = {}
    if symbol not in state["symbols"] or not isinstance(state["symbols"][symbol], dict):
        state["symbols"][symbol] = _default_symbol_state()
    defaults = _default_symbol_state()
    for k, v in defaults.items():
        state["symbols"][symbol].setdefault(k, v)
    return state["symbols"][symbol]


def ensure_managed_positions(state: Dict[str, Any]) -> Dict[str, Any]:
    if "managed_positions" not in state or not isinstance(state["managed_positions"], dict):
        state["managed_positions"] = {}
    return state["managed_positions"]


def ensure_latest_open_positions(state: Dict[str, Any]) -> Dict[str, Any]:
    if "latest_open_positions" not in state or not isinstance(state["latest_open_positions"], dict):
        state["latest_open_positions"] = {}
    return state["latest_open_positions"]


def ensure_exchange_positions(state: Dict[str, Any]) -> Dict[str, Any]:
    if "exchange_positions" not in state or not isinstance(state["exchange_positions"], dict):
        state["exchange_positions"] = {}
    return state["exchange_positions"]


def ensure_engine_positions_view(state: Dict[str, Any]) -> Dict[str, Any]:
    if "engine_positions_view" not in state or not isinstance(state["engine_positions_view"], dict):
        state["engine_positions_view"] = {}
    return state["engine_positions_view"]


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        state = _default_state()
        save_state(state)
        return state
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = _default_state()
        ensure_system_state(state)
        if "symbols" not in state or not isinstance(state["symbols"], dict):
            state["symbols"] = {}
        ensure_managed_positions(state)
        ensure_latest_open_positions(state)
        ensure_exchange_positions(state)
        ensure_engine_positions_view(state)
        save_state(state)
        return state
    except Exception:
        state = _default_state()
        save_state(state)
        return state


def save_state(state: Dict[str, Any]) -> None:
    ensure_system_state(state)
    ensure_managed_positions(state)
    ensure_latest_open_positions(state)
    ensure_exchange_positions(state)
    ensure_engine_positions_view(state)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
