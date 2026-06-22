"""
================================================================
한투 KIS 인덱스 자동매매 - Settings Store
================================================================
코인 settings_store.py base + 인덱스용 패치:
  - SETTINGS_FILE: live_settings_idx.json
  - api: app_key + app_secret + account_no + product_code + hts_id
  - assets: 9 인덱스 자산 (NQ/ES/YM/RTY/NKD/TPX/FTSE/HSI/TWII)
  - portfolio.max_open_positions: 8 (둠챠 결정)
================================================================
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# 인덱스용 settings 파일 (코인과 분리)
SETTINGS_FILE = Path("live_settings_idx.json")


def _default_settings() -> Dict[str, Any]:
    return {
        "mode": "demo",
        "api": {
            # KIS Open API 인증
            "demo_app_key":     "",
            "demo_app_secret":  "",
            "live_app_key":     "",
            "live_app_secret":  "",
            "demo_account_no":  "",   # 8자리 (예: "00225351")
            "live_account_no":  "",
            "product_code":     "08", # 해외선물옵션 = 08
            "hts_id":           "",
        },
        "portfolio": {
            "max_open_positions": 8,
            "risk_multiplier":    1.0,
            # ⭐ 모의계좌 fallback: KIS 해외선물옵션 잔고조회가 모의 미지원이라
            #   여기 수동 입력값을 사용 (실전계좌 사용 시 0 또는 무시)
            "manual_balance_usd": 0.0,
        },
        "execution": {
            "orderbook_limit":     50,
            "poll_fill_timeout_sec": 8,
        },
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
            "NQ":   {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "ES":   {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "YM":   {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "RTY":  {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "NKD":  {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "TPX":  {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "FTSE": {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "HSI":  {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
            "TWII": {"enabled": True, "risk_pct": 0.010, "qty_step": 1, "min_order_qty": 1, "qty_decimals": 0, "allow_long": True, "allow_short": True},
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


# ============================================================
# Helper getters
# ============================================================
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


def get_kis_credentials(settings: Dict[str, Any]) -> Dict[str, Any]:
    """KIS credentials 추출 (mode 따라)"""
    api = get_api_settings(settings)
    mode = get_mode(settings)
    if mode == "live":
        return {
            "app_key":      api.get("live_app_key", ""),
            "app_secret":   api.get("live_app_secret", ""),
            "account_no":   api.get("live_account_no", ""),
            "product_code": api.get("product_code", "08"),
            "hts_id":       api.get("hts_id", ""),
            "use_demo":     False,
        }
    else:
        return {
            "app_key":      api.get("demo_app_key", ""),
            "app_secret":   api.get("demo_app_secret", ""),
            "account_no":   api.get("demo_account_no", ""),
            "product_code": api.get("product_code", "08"),
            "hts_id":       api.get("hts_id", ""),
            "use_demo":     True,
        }
