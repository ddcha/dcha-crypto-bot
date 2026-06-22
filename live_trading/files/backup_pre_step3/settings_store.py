from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

SETTINGS_FILE = Path("live_settings.json")


def _default_settings() -> Dict[str, Any]:
    return {
        "mode": "demo",
        "api": {
            "demo_api_key": "",
            "demo_api_secret": "",
            "live_api_key": "",
            "live_api_secret": "",
        },
        "portfolio": {"max_open_positions": 7, "risk_multiplier": 1.0},
        "execution": {"orderbook_limit": 50, "poll_fill_timeout_sec": 8},
        "protection": {
            "position_management_enabled": True,
            "move_be_at_1r": True,
            "runner_trailing_enabled": True,
            "runner_trail_start_lock_rr": 1.0,
            "runner_trail_step_rr": 1.0,
            "runner_trail_lock_increment_rr": 0.5,
            "runner_lifecycle_enabled": True,
            "runner_fast_2r_bars_max": 3,
            "runner_above_2r_bars_min": 3,
            "runner_max_rr_after_2r_min": 3.0,
            "runner_candidate_min_conds": 2,
            "runner_post_filter_enabled": True,
            "runner_post_filter_max_rr_after_2r": 1.5,
            "runner_protect_locked_r": 0.30,
            "runner_protect_only_if_be_moved": True,
            "disable_time_exit_for_runner": True,
        },
        "assets": {
            "BTCUSDT":  {"enabled": True, "risk_pct": 0.022, "qty_step": 0.001, "min_order_qty": 0.001, "qty_decimals": 3, "allow_long": True, "allow_short": True},
            "ETHUSDT":  {"enabled": True, "risk_pct": 0.015, "qty_step": 0.01,  "min_order_qty": 0.01,  "qty_decimals": 2, "allow_long": True, "allow_short": True},
            "SOLUSDT":  {"enabled": True, "risk_pct": 0.010, "qty_step": 0.1,   "min_order_qty": 0.1,   "qty_decimals": 1, "allow_long": True, "allow_short": True},
            "XRPUSDT":  {"enabled": True, "risk_pct": 0.008, "qty_step": 1,     "min_order_qty": 1,     "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "DOGEUSDT": {"enabled": True, "risk_pct": 0.008, "qty_step": 1,     "min_order_qty": 1,     "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "AVAXUSDT": {"enabled": True, "risk_pct": 0.009, "qty_step": 0.1,   "min_order_qty": 0.1,   "qty_decimals": 1, "allow_long": True, "allow_short": True},
            "LINKUSDT": {"enabled": True, "risk_pct": 0.008, "qty_step": 0.1,   "min_order_qty": 0.1,   "qty_decimals": 1, "allow_long": True, "allow_short": True},
        },
    }


def _merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in src.items():
        if k not in dst:
            dst[k] = v
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
    return dst


def load_live_settings() -> Dict[str, Any]:
    defaults = _default_settings()
    if not SETTINGS_FILE.exists():
        save_live_settings(defaults)
        return defaults
    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = defaults
        _merge(settings, defaults)
        return settings
    except Exception:
        save_live_settings(defaults)
        return defaults


def save_live_settings(settings: Dict[str, Any]) -> None:
    _merge(settings, _default_settings())
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def get_assets(settings: Dict[str, Any]) -> Dict[str, Any]:
    return settings.get("assets", {})


def get_portfolio_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return settings.get("portfolio", {})


def get_protection_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return settings.get("protection", {})


def get_execution_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return settings.get("execution", {})


def get_api_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return settings.get("api", {})


def get_mode(settings: Dict[str, Any]) -> str:
    return str(settings.get("mode", "demo")).strip().lower()
