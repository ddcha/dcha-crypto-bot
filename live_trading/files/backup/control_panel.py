from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple

import pandas as pd
import psutil
import streamlit as st

from settings_store import load_live_settings, save_live_settings
from state_store import load_state, save_state, ensure_system_state
from log_store import load_trade_journal_rows
from exchange_bybit import BybitExchange
from config import LOOP_SLEEP_SECONDS

LIVE_SETTINGS_FILE = Path("live_settings.json")
RUNTIME_STATE_FILE = Path("runtime_state.json")


st.set_page_config(
    page_title="SMC 자동매매 컨트롤 패널",
    page_icon="📊",
    layout="wide",
)


def load_runtime_state() -> Dict[str, Any]:
    state = load_state()
    ensure_system_state(state)
    return state


def save_runtime_state(state: Dict[str, Any]) -> None:
    ensure_system_state(state)
    save_state(state)


def save_all_settings(live_settings: Dict[str, Any], runtime_state: Dict[str, Any]) -> None:
    save_live_settings(live_settings)
    save_runtime_state(runtime_state)


def risk_pct_to_ui(value: float) -> float:
    return round(float(value) * 100.0, 4)


def risk_pct_from_ui(value: float) -> float:
    return float(value) / 100.0


def sanitize_secret_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip().strip('"').strip("'")
    if "=" in value:
        value = value.split("=", 1)[1].strip()
    return value


def masked_value(value: str) -> str:
    value = sanitize_secret_value(value)
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def active_key_preview(live_settings: Dict[str, Any]) -> str:
    mode = str(live_settings.get("mode", "demo")).strip().lower()
    api_cfg = live_settings.get("api", {})
    key = sanitize_secret_value(api_cfg.get("demo_api_key" if mode == "demo" else "live_api_key", ""))
    if not key:
        return "없음"
    return masked_value(key)


def start_main_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "main.py"])


def start_watchdog_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "engine_watchdog.py"])


def stop_process_if_alive(pid: Any) -> None:
    try:
        pid_int = int(pid)
    except Exception:
        return
    if pid_int <= 0:
        return
    try:
        p = psutil.Process(pid_int)
        p.kill()
    except Exception:
        pass


def is_process_alive(pid: Any) -> bool:
    try:
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


def get_active_api_credentials(live_settings: Dict[str, Any]) -> Tuple[str, str, str]:
    mode = str(live_settings.get("mode", "demo")).strip().lower()
    api_cfg = live_settings.get("api", {})
    if mode == "live":
        return (
            sanitize_secret_value(api_cfg.get("live_api_key", "")),
            sanitize_secret_value(api_cfg.get("live_api_secret", "")),
            "live",
        )
    return (
        sanitize_secret_value(api_cfg.get("demo_api_key", "")),
        sanitize_secret_value(api_cfg.get("demo_api_secret", "")),
        "demo",
    )


def get_balance_metrics(live_settings: Dict[str, Any], runtime_state: Dict[str, Any]) -> Dict[str, Any]:
    system = runtime_state["system"]
    metrics = {
        "wallet_balance": None,
        "equity": None,
        "daily_return_pct": 0.0,
        "monthly_return_pct": 0.0,
        "yearly_return_pct": 0.0,
        "mode": str(live_settings.get("mode", "demo")).upper(),
    }

    api_key, api_secret, mode = get_active_api_credentials(live_settings)
    if not api_key or not api_secret:
        return metrics

    try:
        ex = BybitExchange(
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=False,
            use_demo=(mode == "demo"),
        )
        wallet = ex.get_wallet_balance(account_type="UNIFIED", coin="USDT")
        items = wallet.get("result", {}).get("list", [])
        wallet_balance = None
        equity = None
        for account in items:
            for coin in account.get("coin", []):
                if coin.get("coin") == "USDT":
                    wb = coin.get("walletBalance")
                    eq = coin.get("equity") or coin.get("walletBalance")
                    wallet_balance = float(wb) if wb not in (None, "") else None
                    equity = float(eq) if eq not in (None, "") else wallet_balance
                    break
            if wallet_balance is not None or equity is not None:
                break

        metrics["wallet_balance"] = wallet_balance
        metrics["equity"] = equity

        if equity is not None:
            today = datetime.now(timezone.utc).date()
            month_key = today.strftime("%Y-%m")
            year_key = today.strftime("%Y")
            perf = system.setdefault("performance_snapshots", {})
            daily = perf.setdefault("daily", {})
            monthly = perf.setdefault("monthly", {})
            yearly = perf.setdefault("yearly", {})

            daily.setdefault(str(today), equity)
            monthly.setdefault(month_key, equity)
            yearly.setdefault(year_key, equity)

            def pct(cur: float, base: float | None) -> float:
                if base in (None, 0):
                    return 0.0
                return ((cur - float(base)) / float(base)) * 100.0

            metrics["daily_return_pct"] = pct(equity, daily.get(str(today)))
            metrics["monthly_return_pct"] = pct(equity, monthly.get(month_key))
            metrics["yearly_return_pct"] = pct(equity, yearly.get(year_key))
            save_runtime_state(runtime_state)

    except Exception as e:
        system["last_error"] = f"balance_metrics_error: {e}"
        save_runtime_state(runtime_state)

    return metrics


def build_system_check(live_settings: Dict[str, Any]) -> Tuple[bool, List[Tuple[str, bool, str]]]:
    checks: List[Tuple[str, bool, str]] = []
    api_key, api_secret, mode = get_active_api_credentials(live_settings)

    checks.append(("api_present", bool(api_key and api_secret), f"{mode.upper()} API 입력"))
    try:
        import strategy_engine  # noqa: F401
        checks.append(("strategy_engine_import", True, "strategy_engine import ok"))
    except Exception as e:
        checks.append(("strategy_engine_import", False, str(e)))

    try:
        import main  # noqa: F401
        checks.append(("main_import", True, "main import ok"))
    except Exception as e:
        checks.append(("main_import", False, str(e)))

    if api_key and api_secret:
        try:
            ex = BybitExchange(
                api_key=api_key,
                api_secret=api_secret,
                use_testnet=False,
                use_demo=(mode == "demo"),
            )
            ex.get_server_time()
            checks.append(("server_time", True, "Bybit server time ok"))
            wallet = ex.get_wallet_balance(account_type="UNIFIED", coin="USDT")
            ok = wallet.get("retCode", 0) == 0
            checks.append(("wallet_balance", ok, "wallet balance ok" if ok else str(wallet)))
        except Exception as e:
            checks.append(("wallet_balance", False, str(e)))

    all_green = all(item[1] for item in checks)
    return all_green, checks


def render_header() -> None:
    st.title("SMC 자동매매 컨트롤 패널")
    st.caption("컨트롤 패널에서만 API 입력 / 시스템 체크 ALL GREEN 이후 Start")


def render_status_cards(runtime_state: Dict[str, Any], live_settings: Dict[str, Any]) -> None:
    system = runtime_state["system"]
    assets = live_settings["assets"]
    portfolio = live_settings.get("portfolio", {})
    enabled_assets = [sym for sym, cfg in assets.items() if cfg.get("enabled", False)]
    total_config_risk = sum(float(assets[s]["risk_pct"]) for s in enabled_assets)
    # ⭐ v1.9_BASELINE: multiplier 반영한 실효 risk sum 계산
    risk_multiplier = float(portfolio.get("risk_multiplier", 1.0))
    total_effective_risk = total_config_risk * risk_multiplier
    metrics = get_balance_metrics(live_settings, runtime_state)

    exchange_positions = runtime_state.get("exchange_positions", {})
    engine_positions_view = runtime_state.get("engine_positions_view", {})

    position_sync = True
    qty_diff_total = 0.0

    all_symbols = sorted(set(exchange_positions.keys()) | set(engine_positions_view.keys()))
    for symbol in all_symbols:
        ex_pos = exchange_positions.get(symbol, {})
        eng_pos = engine_positions_view.get(symbol, {})

        ex_qty = float(ex_pos.get("qty", 0.0) or 0.0)
        eng_qty = float(eng_pos.get("remaining_qty_est", 0.0) or 0.0)
        diff = abs(ex_qty - eng_qty)
        qty_diff_total += diff

        if diff > 1e-9:
            position_sync = False
            break

    position_sync_text = "SYNC OK" if position_sync else "MISMATCH"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Mode", metrics["mode"])
    c2.metric("Engine", "RUNNING" if system.get("engine_running", False) else "STOPPED")
    c3.metric("Current Balance", f"{metrics['wallet_balance']:,.2f} USDT" if metrics["wallet_balance"] is not None else "-")
    c4.metric("Current Equity", f"{metrics['equity']:,.2f} USDT" if metrics["equity"] is not None else "-")
    c5.metric("Daily Return", f"{metrics['daily_return_pct']:.2f}%")
    # ⭐ v1.9_BASELINE: Effective Risk Sum (base × multiplier)
    c6.metric(
        "Effective Risk Sum",
        f"{risk_pct_to_ui(total_effective_risk):.2f}%",
        delta=f"×{risk_multiplier:.2f}",
        help=f"Base {risk_pct_to_ui(total_config_risk):.2f}% × multiplier {risk_multiplier:.2f}",
    )

    c7, c8, c9, c10 = st.columns(4)
    c7.metric("Monthly Return", f"{metrics['monthly_return_pct']:.2f}%")
    c8.metric("Yearly Return", f"{metrics['yearly_return_pct']:.2f}%")
    c9.metric("활성 API", f"{str(live_settings.get('mode', 'demo')).upper()} ({active_key_preview(live_settings)})")
    c10.metric("Position Sync", position_sync_text)

    if not position_sync:
        st.warning(f"거래소/엔진 포지션 수량 불일치 감지됨. 총 차이: {qty_diff_total:.8f}")

    st.divider()


def render_engine_monitor(runtime_state: Dict[str, Any], loop_sleep_seconds: int = 30) -> None:
    st.subheader("Main 엔진 상태")
    system = runtime_state["system"]
    last_loop = system.get("last_loop_time")
    heartbeat_age = None
    status = "STOPPED"

    if system.get("engine_running", False):
        status = "RUNNING"
        if last_loop:
            try:
                dt = datetime.fromisoformat(str(last_loop).replace("Z", "+00:00"))
                heartbeat_age = (datetime.now(timezone.utc) - dt).total_seconds()
                if heartbeat_age > max(30, loop_sleep_seconds * 3):
                    status = "STALLED"
            except Exception:
                pass

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Status", status)
    c2.metric("PID", system.get("engine_pid") or "-")
    c3.metric("Started At", system.get("engine_started_at") or "-")
    c4.metric("Heartbeat", f"{heartbeat_age:.0f}s ago" if heartbeat_age is not None else "-")
    c5.metric("Watchdog", "RUNNING" if system.get("watchdog_running", False) else "STOPPED")
    c6.metric("Last Action", system.get("last_action") or "-")

    if system.get("last_error"):
        st.error(system.get("last_error"))

    if st.button("새로고침", use_container_width=True):
        st.rerun()

    st.divider()


def render_api_controls(live_settings: Dict[str, Any], runtime_state: Dict[str, Any]) -> None:
    st.subheader("API 설정")
    api_cfg = live_settings.setdefault("api", {})

    demo_col, live_col = st.columns(2)

    with demo_col:
        st.markdown("### Demo API")
        demo_key = st.text_input(
            "Demo API Key",
            value=str(api_cfg.get("demo_api_key", "")),
            type="password",
            key="demo_api_key_input",
        )
        demo_secret = st.text_input(
            "Demo API Secret",
            value=str(api_cfg.get("demo_api_secret", "")),
            type="password",
            key="demo_api_secret_input",
        )
        st.caption(f"저장된 Demo Key: {masked_value(api_cfg.get('demo_api_key', ''))}")

        if st.button("Demo API 적용", use_container_width=True):
            api_cfg["demo_api_key"] = sanitize_secret_value(demo_key)
            api_cfg["demo_api_secret"] = sanitize_secret_value(demo_secret)
            live_settings["mode"] = "demo"
            save_all_settings(live_settings, runtime_state)
            st.success("Demo API 저장 및 활성화 완료")
            st.rerun()

    with live_col:
        st.markdown("### Live API")
        live_key = st.text_input(
            "Live API Key",
            value=str(api_cfg.get("live_api_key", "")),
            type="password",
            key="live_api_key_input",
        )
        live_secret = st.text_input(
            "Live API Secret",
            value=str(api_cfg.get("live_api_secret", "")),
            type="password",
            key="live_api_secret_input",
        )
        st.caption(f"저장된 Live Key: {masked_value(api_cfg.get('live_api_key', ''))}")

        if st.button("Live API 적용", use_container_width=True):
            api_cfg["live_api_key"] = sanitize_secret_value(live_key)
            api_cfg["live_api_secret"] = sanitize_secret_value(live_secret)
            live_settings["mode"] = "live"
            save_all_settings(live_settings, runtime_state)
            st.success("Live API 저장 및 활성화 완료")
            st.rerun()

    st.info(f"현재 활성 API: {str(live_settings.get('mode', 'demo')).upper()} ({active_key_preview(live_settings)})")
    st.divider()


def render_main_controls(live_settings: Dict[str, Any], runtime_state: Dict[str, Any]) -> None:
    st.subheader("운용 설정")
    system = runtime_state["system"]
    portfolio = live_settings["portfolio"]
    protection = live_settings["protection"]
    assets = live_settings["assets"]
    execution = live_settings.setdefault("execution", {"orderbook_limit": 50, "poll_fill_timeout_sec": 8})

    top_left, top_right = st.columns([1.1, 2.1])

    with top_left:
        trading_enabled = st.toggle("Trading Enabled", value=bool(system.get("trading_enabled", True)))
        max_open_positions = st.number_input(
            "Max Open Positions",
            min_value=1,
            max_value=20,
            value=int(portfolio.get("max_open_positions", 3)),
            step=1,
        )
        # ⭐ v1.9_BASELINE: Global Risk Multiplier (runtime 조절)
        # 모든 진입의 risk_pct 에 곱해지는 전역 배수.
        # 권장: 저자본 공격 2.0 / 중자본 1.5 / 고자본 방어 0.5~1.0
        risk_multiplier = st.number_input(
            "Global Risk Multiplier",
            min_value=0.1,
            max_value=3.0,
            value=float(portfolio.get("risk_multiplier", 1.0)),
            step=0.1,
            format="%.2f",
            help="전역 risk 배수 (1.0=백테스트 기준). 저자본=2.0, 고자본=0.5~1.0 권장.",
        )
        orderbook_limit = st.number_input(
            "Orderbook Limit",
            min_value=1,
            max_value=500,
            value=int(execution.get("orderbook_limit", 50)),
            step=1,
        )
        poll_fill_timeout_sec = st.number_input(
            "Fill Sync Retries",
            min_value=1,
            max_value=60,
            value=int(execution.get("poll_fill_timeout_sec", 8)),
            step=1,
        )
        position_management_enabled = st.toggle(
            "Position Management Enabled",
            value=bool(protection.get("position_management_enabled", True)),
        )
        runner_lifecycle_enabled = st.toggle(
            "Runner Lifecycle Enabled",
            value=bool(protection.get("runner_lifecycle_enabled", True)),
        )
        disable_time_exit_for_runner = st.toggle(
            "Disable Time Exit For Runner",
            value=bool(protection.get("disable_time_exit_for_runner", True)),
        )
        runner_fast_2r_bars_max = st.number_input(
            "Runner Fast 2R Bars Max",
            min_value=1,
            max_value=20,
            value=int(protection.get("runner_fast_2r_bars_max", 3)),
            step=1,
        )
        runner_above_2r_bars_min = st.number_input(
            "Runner Above 2R Bars Min",
            min_value=1,
            max_value=20,
            value=int(protection.get("runner_above_2r_bars_min", 3)),
            step=1,
        )
        runner_max_rr_after_2r_min = st.number_input(
            "Runner Max RR After 2R Min",
            min_value=0.0,
            max_value=20.0,
            value=float(protection.get("runner_max_rr_after_2r_min", 3.0)),
            step=0.1,
            format="%.2f",
        )
        runner_candidate_min_conds = st.number_input(
            "Runner Candidate Min Conds",
            min_value=1,
            max_value=3,
            value=int(protection.get("runner_candidate_min_conds", 2)),
            step=1,
        )
        runner_post_filter_enabled = st.toggle(
            "Runner Post Filter Enabled",
            value=bool(protection.get("runner_post_filter_enabled", True)),
        )
        runner_post_filter_max_rr_after_2r = st.number_input(
            "Runner Post Filter Max RR After 2R",
            min_value=0.0,
            max_value=20.0,
            value=float(protection.get("runner_post_filter_max_rr_after_2r", 1.5)),
            step=0.1,
            format="%.2f",
        )
        runner_protect_locked_r = st.number_input(
            "Runner Protect Locked R",
            min_value=0.0,
            max_value=10.0,
            value=float(protection.get("runner_protect_locked_r", 0.30)),
            step=0.05,
            format="%.2f",
        )
        runner_protect_only_if_be_moved = st.toggle(
            "Runner Protect Only If BE Moved",
            value=bool(protection.get("runner_protect_only_if_be_moved", True)),
        )

    with top_right:
        st.markdown("### 자산별 설정")
        for symbol, cfg in assets.items():
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1:
                    cfg["enabled"] = st.toggle(f"{symbol} Enabled", value=bool(cfg.get("enabled", True)), key=f"{symbol}_enabled")
                with c2:
                    cfg["risk_pct"] = risk_pct_from_ui(
                        st.number_input(
                            f"{symbol} Risk (%)",
                            min_value=0.0,
                            max_value=100.0,
                            value=risk_pct_to_ui(cfg.get("risk_pct", 0.0)),
                            step=0.1,
                            format="%.3f",
                            key=f"{symbol}_risk",
                        )
                    )
                with c3:
                    cfg["qty_step"] = float(
                        st.number_input(
                            f"{symbol} Qty Step",
                            min_value=0.0,
                            value=float(cfg.get("qty_step", 0.0)),
                            step=0.001,
                            format="%.6f",
                            key=f"{symbol}_step",
                        )
                    )
                with c4:
                    cfg["min_order_qty"] = float(
                        st.number_input(
                            f"{symbol} Min Qty",
                            min_value=0.0,
                            value=float(cfg.get("min_order_qty", 0.0)),
                            step=0.001,
                            format="%.6f",
                            key=f"{symbol}_minqty",
                        )
                    )
                with c5:
                    cfg["qty_decimals"] = int(
                        st.number_input(
                            f"{symbol} Qty Decimals",
                            min_value=0,
                            max_value=10,
                            value=int(cfg.get("qty_decimals", 3)),
                            step=1,
                            key=f"{symbol}_dec",
                        )
                    )

                c6, c7 = st.columns(2)
                with c6:
                    cfg["allow_long"] = st.toggle(f"{symbol} Allow Long", value=bool(cfg.get("allow_long", True)), key=f"{symbol}_long")
                with c7:
                    cfg["allow_short"] = st.toggle(f"{symbol} Allow Short", value=bool(cfg.get("allow_short", True)), key=f"{symbol}_short")

    system["trading_enabled"] = trading_enabled
    portfolio["max_open_positions"] = int(max_open_positions)
    portfolio["risk_multiplier"] = float(risk_multiplier)  # ⭐ v1.9_BASELINE
    # 합산 리스크 제한 제거됨 (v1.9b 티어 매핑으로 인해)
    if "max_total_risk_pct" in portfolio:
        del portfolio["max_total_risk_pct"]
    execution["orderbook_limit"] = int(orderbook_limit)
    execution["poll_fill_timeout_sec"] = int(poll_fill_timeout_sec)
    protection["position_management_enabled"] = bool(position_management_enabled)
    protection["runner_lifecycle_enabled"] = bool(runner_lifecycle_enabled)
    protection["disable_time_exit_for_runner"] = bool(disable_time_exit_for_runner)
    protection["runner_fast_2r_bars_max"] = int(runner_fast_2r_bars_max)
    protection["runner_above_2r_bars_min"] = int(runner_above_2r_bars_min)
    protection["runner_max_rr_after_2r_min"] = float(runner_max_rr_after_2r_min)
    protection["runner_candidate_min_conds"] = int(runner_candidate_min_conds)
    protection["runner_post_filter_enabled"] = bool(runner_post_filter_enabled)
    protection["runner_post_filter_max_rr_after_2r"] = float(runner_post_filter_max_rr_after_2r)
    protection["runner_protect_locked_r"] = float(runner_protect_locked_r)
    protection["runner_protect_only_if_be_moved"] = bool(runner_protect_only_if_be_moved)

    if st.button("설정 저장", type="primary", use_container_width=True):
        save_all_settings(live_settings, runtime_state)
        st.success("저장 완료")
        st.rerun()


def render_system_check(live_settings: Dict[str, Any], runtime_state: Dict[str, Any]) -> None:
    st.subheader("시스템 체크")
    all_green, checks = build_system_check(live_settings)
    rows = [{"name": name, "ok": "✅" if ok else "❌", "detail": detail} for name, ok, detail in checks]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if all_green:
        st.success("ALL GREEN")
    else:
        st.error("ALL GREEN 아님")

    system = runtime_state["system"]
    system["last_system_check"] = {"ok": all_green, "checks": rows}
    save_runtime_state(runtime_state)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Start", disabled=not all_green, use_container_width=True):
            live_settings = load_live_settings()
            runtime_state = load_runtime_state()
            system = runtime_state["system"]

            engine_pid = system.get("engine_pid")
            watchdog_pid = system.get("watchdog_pid")

            if engine_pid and is_process_alive(engine_pid):
                st.warning(f"이미 main.py가 실행 중입니다. (PID: {engine_pid})")
            elif watchdog_pid and is_process_alive(watchdog_pid):
                system["stop_requested"] = False
                system["watchdog_enabled"] = True
                system["last_action"] = "watchdog_re_enabled_from_control_panel"
                save_runtime_state(runtime_state)
                st.success(f"watchdog.py 재활성화 완료 (PID: {watchdog_pid})")
                st.rerun()
            else:
                system["stop_requested"] = False
                system["watchdog_enabled"] = True
                system["engine_running"] = False
                system["engine_pid"] = None
                system["engine_started_at"] = None
                system["engine_stopped_at"] = None
                system["watchdog_running"] = False
                system["watchdog_pid"] = None
                system["last_action"] = "watchdog_start_requested"
                save_runtime_state(runtime_state)

                proc = start_watchdog_process()

                system["watchdog_running"] = True
                system["watchdog_pid"] = proc.pid
                system["last_action"] = "watchdog_started_from_control_panel"
                save_runtime_state(runtime_state)

                st.success(f"watchdog.py 시작 (PID: {proc.pid})")
                st.rerun()

    with c2:
        if st.button("Stop", use_container_width=True):
            runtime_state = load_runtime_state()
            system = runtime_state["system"]

            system["stop_requested"] = True
            system["watchdog_enabled"] = False
            system["last_action"] = "stop_requested_from_control_panel"
            save_runtime_state(runtime_state)

            stop_process_if_alive(system.get("engine_pid"))
            stop_process_if_alive(system.get("watchdog_pid"))

            system["engine_running"] = False
            system["watchdog_running"] = False
            system["engine_pid"] = None
            system["watchdog_pid"] = None
            system["engine_stopped_at"] = datetime.now(timezone.utc).isoformat()
            save_runtime_state(runtime_state)
            st.warning("main.py / watchdog.py 종료")
            st.rerun()

    st.divider()


def render_runtime_status(runtime_state: Dict[str, Any]) -> None:
    st.subheader("현재 포지션 / 관리 상태")
    exchange_positions = runtime_state.get("exchange_positions", {})
    engine_positions_view = runtime_state.get("engine_positions_view", {})

    exchange_rows = []
    for symbol, pos in exchange_positions.items():
        exchange_rows.append(
            {
                "symbol": symbol,
                "side": pos.get("side"),
                "qty": pos.get("qty"),
                "avg_entry_price": pos.get("avg_entry_price"),
                "mark_price": pos.get("mark_price"),
                "position_value": pos.get("position_value"),
                "unrealised_pnl": pos.get("unrealised_pnl"),
                "updated_at": pos.get("updated_at"),
            }
        )

    engine_rows = []
    for symbol, pos in engine_positions_view.items():
        exchange_qty = float(exchange_positions.get(symbol, {}).get("qty", 0.0) or 0.0)
        engine_qty = float(pos.get("remaining_qty_est", 0.0) or 0.0)
        engine_rows.append(
            {
                "symbol": symbol,
                "side": pos.get("side"),
                "entry_price": pos.get("entry_price"),
                "expected_entry_price": pos.get("expected_entry_price"),
                "slippage_pct": pos.get("slippage_pct"),
                "initial_sl": pos.get("initial_sl"),
                "current_stop": pos.get("current_stop"),
                "original_qty": pos.get("original_qty"),
                "remaining_qty_est": pos.get("remaining_qty_est"),
                "exchange_qty": exchange_qty,
                "qty_diff": round(abs(exchange_qty - engine_qty), 10),
                "tp_plan_name": pos.get("tp_plan_name"),
                "tp1_done": pos.get("tp1_done"),
                "tp2_done": pos.get("tp2_done"),
                "tp3_done": pos.get("tp3_done"),
                "runner_active": pos.get("runner_active"),
                "runner_state_badge": pos.get("runner_state_badge"),
                "runner_candidate_2of3": pos.get("runner_candidate_2of3"),
                "post_2of3_apply_ok": pos.get("post_2of3_apply_ok"),
                "runner_protected": pos.get("runner_protected"),
                "rr_bars_to_2r": pos.get("rr_bars_to_2r"),
                "rr_bars_spent_above_2r": pos.get("rr_bars_spent_above_2r"),
                "rr_max_rr_after_2r": pos.get("rr_max_rr_after_2r"),
                "rr_cond_count_final": pos.get("rr_cond_count_final"),
                "time_exit_disabled_for_runner": pos.get("time_exit_disabled_for_runner"),
                "entry_source": pos.get("entry_source"),
                "signal_ts": pos.get("signal_ts"),
            }
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 거래소 실제 포지션")
        if exchange_rows:
            st.dataframe(pd.DataFrame(exchange_rows), use_container_width=True, hide_index=True)
        else:
            st.info("거래소 실제 포지션 없음")

    with c2:
        st.markdown("### 엔진 관리 포지션")
        if engine_rows:
            st.dataframe(pd.DataFrame(engine_rows), use_container_width=True, hide_index=True)
        else:
            st.info("엔진 관리 포지션 없음")

    st.divider()


def render_trade_journal() -> None:
    st.subheader("거래 요약 로그")
    rows = load_trade_journal_rows(limit=300)
    if not rows:
        st.info("아직 거래 요약 로그가 없습니다.")
        return

    df = pd.DataFrame(rows)
    preferred = [
        "status", "symbol", "side", "tp_plan_name", "signal_ts",
        "expected_entry_price", "filled_entry_price", "slippage_pct",
        "initial_sl", "original_qty",
        "tp1_qty", "tp1_price",
        "tp2_qty", "tp2_price",
        "tp3_qty", "tp3_price",
        "final_exit_qty", "final_exit_price", "final_exit_reason",
        "remaining_qty_est",
        "be_moved", "runner_active", "current_stop",
        "opened_at", "closed_at",
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    if "opened_at" in df.columns:
        df = df.sort_values("opened_at", ascending=False)
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    st.divider()


def render_active_zones(live_settings: Dict[str, Any]) -> None:
    st.subheader("Active Zones 모니터")

    api_key, api_secret, mode = get_active_api_credentials(live_settings)
    if not api_key or not api_secret:
        st.warning("API 키가 설정되지 않았습니다.")
        return

    # ⭐ v2.0_WICK: 모드 토글 + 필터 옵션
    col_mode, col_tier = st.columns([2, 2])
    with col_mode:
        view_mode = st.radio(
            "표시 모드",
            ["진입 후보만", "전체 보기"],
            horizontal=True,
            key="zones_view_mode",
            help="진입 후보만: 실전 엔진이 진입 가능한 zone 만. 전체 보기: 모든 active zone (디버깅용)."
        )
    with col_tier:
        if view_mode == "진입 후보만":
            tier_filter_label = st.selectbox(
                "Tier 필터 (Stage 4K)",
                ["전체 진입가능 (ALPHA + SWEEP)", "ALPHA 만 (고품질, 999× cap)", "ALPHA_MAX 만 (최강)"],
                index=0,
                key="zones_tier_filter",
                help="실전 엔진의 진입가능 tier: ALPHA_MAX/HIGH/MED + SWEEP_GEM/ROOM_FVG/ROOM_ONLY (4I/4J 차단 통과한 것). ALPHA 만 선택시 SWEEP 제외 (notional cap 무제한)."
            )
            if "전체" in tier_filter_label:
                allowed_tiers = {"ALPHA_MAX", "ALPHA_HIGH", "ALPHA_MED",
                                  "SWEEP_GEM", "SWEEP_ROOM_FVG", "SWEEP_ROOM_ONLY"}
            elif "ALPHA 만" in tier_filter_label:
                allowed_tiers = {"ALPHA_MAX", "ALPHA_HIGH", "ALPHA_MED"}
            else:  # ALPHA_MAX 만
                allowed_tiers = {"ALPHA_MAX"}
        else:
            allowed_tiers = {"ALPHA_MAX", "ALPHA_HIGH", "ALPHA_MED",
                              "SWEEP_GEM", "SWEEP_ROOM_FVG", "SWEEP_ROOM_ONLY",
                              "COMPLETE_OUT", "SKIP_MSS"}

    # 거리 필터 (진입 후보 모드만): 0=닿은 것만, > 0 은 디버깅용
    if view_mode == "진입 후보만":
        col_dist, col_wick = st.columns([2, 1])
        with col_dist:
            max_distance_pct = st.slider(
                "최대 거리 (%) — 0 = 닿은 zone 만",
                min_value=0.0, max_value=10.0, value=0.0, step=0.1,
                key="zones_max_distance",
                help="0% = 현재가가 zone 안에 있거나 1m wick touch 한 zone 만 표시. > 0 은 디버깅용 (가까운 zone 표시)."
            )
        with col_wick:
            use_1m_wick_panel = st.checkbox(
                "1m wick touch",
                value=True,
                key="zones_use_1m_wick",
                help="현재가가 zone 밖이라도 직전 5분 1분봉 wick 이 zone touch + 이탈거리 30% 이내인 zone 도 표시"
            )
    else:
        max_distance_pct = 999.0
        use_1m_wick_panel = False

    if not st.button("Zone 조회", use_container_width=True, key="btn_check_zones"):
        return

    # ====================================================================
    # v2.2: main.py 가 cache/zones_cache.pkl 에 저장한 것을 read
    # main.py 가 1시간마다 zone cache refresh 하므로 control_panel 은 fetch X
    # CPU 0%, API 호출 0회 - 즉시 응답
    # ====================================================================
    import pickle
    import os
    import time as _time_for_cache

    try:
        from config import (
            EXCLUDE_RECENT_H1_FOR_TIER,
            USE_TIER_PRIORITY_SORT,
            USE_1M_WICK_TOUCH,
            WICK_TOUCH_LOOKBACK_BARS,
            WICK_TOUCH_MAX_EXIT_FRAC,
        )
    except Exception:
        EXCLUDE_RECENT_H1_FOR_TIER = 0
        USE_TIER_PRIORITY_SORT = True
        USE_1M_WICK_TOUCH = True
        WICK_TOUCH_LOOKBACK_BARS = 5
        WICK_TOUCH_MAX_EXIT_FRAC = 0.30

    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "zones_cache.pkl")

    if not os.path.exists(cache_path):
        st.error(
            "⚠ Zone cache 파일이 없습니다.\n"
            "main.py 가 첫 SYMBOL_LOOP 완료 후 (~수분) 다시 시도하세요.\n"
            f"기대 경로: {cache_path}"
        )
        return

    cache_age_sec = _time_for_cache.time() - os.path.getmtime(cache_path)
    if cache_age_sec > 3700:  # 1시간 + 100초
        st.warning(
            f"⚠ Zone cache 가 {int(cache_age_sec/60)}분 {int(cache_age_sec%60)}초 전 데이터입니다. "
            f"main.py 가 정상 가동 중인지 확인하세요."
        )
    elif cache_age_sec > 1800:  # 30분 이상
        st.info(f"ℹ Zone cache: {int(cache_age_sec/60)}분 전 데이터 (정상 - 1시간마다 갱신)")

    try:
        with open(cache_path, "rb") as f:
            cache_data = pickle.load(f)
        zone_snapshot = cache_data.get("snapshot", {})
        cache_meta = cache_data.get("_meta", {})
    except Exception as e:
        st.error(f"⚠ Zone cache 읽기 실패: {e}")
        return

    if not zone_snapshot:
        st.warning("Zone cache 가 비어있음. main.py 첫 SYMBOL_LOOP 완료 대기.")
        return

    try:
        # runtime_state 의 현재 포지션 정보 (보유 중 표시용)
        try:
            runtime_state_local = load_runtime_state()
            symbols_state = runtime_state_local.get("symbols", {})
        except Exception:
            symbols_state = {}

        # enabled 된 심볼 전체 스캔
        active_symbols = [sym for sym, cfg in live_settings["assets"].items() if cfg.get("enabled", False)]

        st.caption(f"📦 Cache: {cache_meta.get('saved_at', '?')} | symbols={cache_meta.get('n_symbols', '?')} | age={int(cache_age_sec)}s")

        for symbol in active_symbols:
            try:
                if symbol not in zone_snapshot:
                    st.info(f"{symbol}: cache 없음 (비활성 또는 zone cache refresh 미진행)")
                    continue

                cached = zone_snapshot[symbol]

                # 에러로 cache 된 경우
                if "error" in cached:
                    st.warning(f"{symbol}: cache 생성 시 에러 ({cached['error']})")
                    continue

                # cache 에서 데이터 추출 (기존 변수명 유지)
                evaluated_zones = cached.get("evaluated_zones", [])
                active_structures = cached.get("active_structures", [])
                current_close = float(cached.get("current_close") or 0.0)
                h4_trend = str(cached.get("h4_trend", "?"))

                # 1m wick touch 데이터 (cache 의 tail5)
                df_1m_recent = None
                if view_mode == "진입 후보만" and use_1m_wick_panel:
                    _df_1m_records = cached.get("df_1m_recent_tail5", [])
                    if _df_1m_records:
                        try:
                            import pandas as _pd
                            df_1m_recent = _pd.DataFrame(_df_1m_records)
                            if "timestamp" in df_1m_recent.columns:
                                df_1m_recent["timestamp"] = _pd.to_datetime(df_1m_recent["timestamp"], utc=True)
                        except Exception:
                            df_1m_recent = None

                # 가격 포맷을 코인 가격대에 맞춰 동적 조정
                if current_close < 1:
                    price_fmt = ",.4f"
                elif current_close < 100:
                    price_fmt = ",.3f"
                else:
                    price_fmt = ",.2f"

                # 포지션 정보 (cache 에서)
                position_info = ""
                if cached.get("has_position"):
                    pside = cached.get("position_side", "?")
                    pqty = cached.get("position_qty", 0.0)
                    position_info = f" | 📍 {pside} qty {pqty}"

                # v2.0_WICK: 필터링 수행 — strategy_engine 진입 로직과 매핑
                def _is_touched(z):
                    """현재가가 zone 안 OR 직전 5분 1m wick touch (이탈거리 ≤ 30%)."""
                    zlow = float(z["zone_low"])
                    zhigh = float(z["zone_high"])
                    # 1) zone 안에 현재가
                    touched_now = (zlow <= current_close <= zhigh)
                    if touched_now:
                        return True, "current_price_in_zone"
                    # 2) 1m wick touch (옵션)
                    if not use_1m_wick_panel or df_1m_recent is None or len(df_1m_recent) == 0:
                        return False, "not_touched"
                    try:
                        recent_1m = df_1m_recent.tail(int(WICK_TOUCH_LOOKBACK_BARS))
                        recent_high = float(recent_1m["high"].max())
                        recent_low = float(recent_1m["low"].min())
                        wick_touched = (recent_high >= zlow) and (recent_low <= zhigh)
                        if not wick_touched:
                            return False, "no_wick_touch"
                        zone_size = zhigh - zlow
                        if zone_size <= 0:
                            return False, "zero_zone_size"
                        if z["type"] == "long":
                            exit_distance = max(0.0, current_close - zhigh)
                        else:
                            exit_distance = max(0.0, zlow - current_close)
                        exit_frac = exit_distance / zone_size
                        if exit_frac <= WICK_TOUCH_MAX_EXIT_FRAC:
                            return True, f"wick_touch_exit{exit_frac:.0%}"
                        return False, f"wick_touch_too_late_exit{exit_frac:.0%}"
                    except Exception:
                        return False, "wick_check_error"

                def zone_passes_filter(z):
                    if view_mode == "전체 보기":
                        return True
                    # 진입 후보 모드
                    # 1) tier 필터
                    if z["tier"] not in allowed_tiers:
                        return False
                    # 2) tier passable (4I/4J 차단, RP skip 모두 포함)
                    if not z["tier_passable"]:
                        return False
                    # 3) trend 역행 제외
                    if z["type"] == "short" and h4_trend == "up":
                        return False
                    if z["type"] == "long" and h4_trend == "down":
                        return False
                    # 4) ⭐ touched 판정 (max_distance_pct == 0 이면 touched only) ⭐
                    if max_distance_pct <= 0.001:
                        # 진짜 닿은 것만 (zone 안 또는 1m wick touch)
                        touched, _reason = _is_touched(z)
                        return touched
                    # 5) max_distance_pct > 0: 거리 필터 (디버깅용)
                    if z["type"] == "long":
                        dist = (current_close - z["zone_high"]) / current_close * 100
                    else:
                        dist = (z["zone_low"] - current_close) / current_close * 100
                    # zone 안이면 dist <= 0 이므로 통과. zone 밖이면 max_distance_pct 이내만
                    if dist > max_distance_pct:
                        return False
                    return True

                filtered_zones = [z for z in evaluated_zones if zone_passes_filter(z)]

                # 중복 제거 (zone_low/high/type 같은 것, tier_mult_final 상위만)
                def dedupe(zones):
                    seen = {}
                    for z in zones:
                        key = (z["type"], round(z["zone_low"], 6), round(z["zone_high"], 6))
                        if key not in seen or z["tier_mult_final"] > seen[key]["tier_mult_final"]:
                            seen[key] = z
                    return list(seen.values())

                filtered_zones = dedupe(filtered_zones)

                # 정렬
                if USE_TIER_PRIORITY_SORT:
                    filtered_zones.sort(key=lambda z: (
                        -float(z["tier_mult_final"]),
                        -float(z["eff_score"]),
                        int(z["zone_created_idx"]),
                    ))
                else:
                    filtered_zones.sort(key=lambda z: (
                        -float(z["eff_score"]),
                        int(z["zone_created_idx"]),
                    ))

                # 헤더 정보
                st.markdown(
                    f"**{symbol}** | 현재가 `{format(current_close, price_fmt)}` "
                    f"| H4 trend: `{h4_trend}` | zones: {len(filtered_zones)}/{len(evaluated_zones)}"
                    f"{position_info}"
                )

                if not filtered_zones:
                    if view_mode == "진입 후보만":
                        # 왜 없는지 힌트
                        reason_hints = []
                        if h4_trend == "up":
                            reason_hints.append("H4 uptrend → SHORT 차단")
                        elif h4_trend == "down":
                            reason_hints.append("H4 downtrend → LONG 차단")
                        if not evaluated_zones:
                            reason_hints.append("Active zone 없음")
                        hint = ", ".join(reason_hints) if reason_hints else "거리 또는 Tier 필터 조건 미충족"
                        st.info(f"{symbol}: 진입 후보 없음 ({hint})")
                    else:
                        st.info(f"{symbol}: active zone 없음")
                    continue

                rows = []
                for z in filtered_zones:
                    in_zone = z["zone_low"] <= current_close <= z["zone_high"]
                    if z["type"] == "long":
                        diff_pct = (current_close - z["zone_high"]) / current_close * 100
                    else:
                        diff_pct = (z["zone_low"] - current_close) / current_close * 100

                    # 상태 표시
                    if not z["tier_passable"]:
                        status = "⚪ SKIP"
                    elif in_zone:
                        status = "🔴 TOUCH"
                    elif abs(diff_pct) <= 0.5:
                        status = "🟡 가까움"
                    elif (z["type"] == "short" and h4_trend == "up") or (z["type"] == "long" and h4_trend == "down"):
                        status = "⛔ 역행"
                    else:
                        status = "⚫ 대기"

                    rows.append({
                        "방향": z["type"].upper(),
                        "Tier": z["tier"],
                        "Mult": f"{z['tier_mult_final']:.2f}x",
                        "RP": int(z["run_potential"]),
                        "Zone Low": format(z["zone_low"], price_fmt),
                        "Zone High": format(z["zone_high"], price_fmt),
                        "Score": f"{z['eff_score']:.1f}",
                        "거리%": f"{diff_pct:+.2f}%",
                        "상태": status,
                    })

                st.dataframe(rows, use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"{symbol}: {e}")

    except Exception as e:
        st.error(f"Zone 표시 실패: {e}")

    st.divider()


def render_file_paths() -> None:
    with st.expander("파일 경로 확인"):
        st.code(
            "live_settings.json -> " + str(LIVE_SETTINGS_FILE.resolve()) + "\n"
            + "runtime_state.json -> " + str(RUNTIME_STATE_FILE.resolve()),
            language="text",
        )


def main() -> None:
    try:
        st_autorefresh = getattr(st, "autorefresh", None)
        if callable(st_autorefresh):
            st_autorefresh(interval=5000, key="control_panel_autorefresh")

        live_settings = load_live_settings()
        runtime_state = load_runtime_state()

        render_header()
        render_status_cards(runtime_state, live_settings)
        render_engine_monitor(runtime_state, LOOP_SLEEP_SECONDS)
        render_api_controls(live_settings, runtime_state)
        render_main_controls(live_settings, runtime_state)
        render_system_check(live_settings, runtime_state)
        render_runtime_status(runtime_state)
        render_trade_journal()
        render_active_zones(live_settings)
        render_file_paths()

    except Exception as e:
        import traceback
        st.error(f"control_panel main error: {e}")
        st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
