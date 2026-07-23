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


def is_watchdog_process(pid: Any) -> bool:
    """
    [PATCHED May 19]
    PID가 살아있고 + 실제 engine_watchdog.py 실행 중인지 검증.
    PID 재사용 / stale PID 케이스 방지.
    runtime_state.json 의 watchdog_pid 가 옛 PID라서
    다른 무관한 프로세스 PID와 우연히 같을 때 "watchdog alive" 오판하는 것을 막음.
    """
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        p = psutil.Process(pid_int)
        cmdline = " ".join(p.cmdline() or [])
        return "engine_watchdog.py" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return False


def is_main_engine_process(pid: Any) -> bool:
    """
    [PATCHED May 19]
    PID가 살아있고 + 실제 main.py 실행 중인지 검증. is_watchdog_process 와 동일 원리.
    """
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        p = psutil.Process(pid_int)
        cmdline = " ".join(p.cmdline() or [])
        return "main.py" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
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
        system["last_error"] = ""   # ★성공 시 이전 에러(stale 401 등) clear — 안 지우면 영구표시됨

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
        # ★v4 무장존 기준 — 수치 파라미터는 코드/기본값 고정(패널 변경 불가). 조작은 토글/자산 on-off 만.
        st.info("**v4 기준 고정** — 리스크캡 15%·만기컷 36h·트레일=백테엔진·리스크=조합테이블. "
                "아래 수치들은 백테와 동일하게 코드 고정이라 패널에서 변경하지 않습니다.")
        with st.expander("v4 고정 수치 (읽기전용)", expanded=False):
            st.caption(f"Max Open {int(portfolio.get('max_open_positions', 9))} · RiskMult {float(portfolio.get('risk_multiplier', 1.0))} · "
                       f"Orderbook {int(execution.get('orderbook_limit', 50))} · FillRetries {int(execution.get('poll_fill_timeout_sec', 8))}")
            st.caption(f"Runner: fast2r {int(protection.get('runner_fast_2r_bars_max', 3))} · above2r {int(protection.get('runner_above_2r_bars_min', 3))} · "
                       f"minConds {int(protection.get('runner_candidate_min_conds', 2))} · protectLockR {float(protection.get('runner_protect_locked_r', 0.30))}")
        # 값 = 저장된 설정/기본값 그대로 (위젯 없음 = 변경 불가)
        max_open_positions = int(portfolio.get("max_open_positions", 9))
        risk_multiplier = float(portfolio.get("risk_multiplier", 1.0))
        orderbook_limit = int(execution.get("orderbook_limit", 50))
        poll_fill_timeout_sec = int(execution.get("poll_fill_timeout_sec", 8))
        # ★v6 균일 리스크 선택 (2/1.5/1%, 기본 2%). >0 이면 combo_risk_table 무시하고 균일 적용.
        _risk_opts = [2.0, 1.5, 1.0]
        _cur_uniform = float(portfolio.get("uniform_risk_pct", 2.0))
        _idx = _risk_opts.index(_cur_uniform) if _cur_uniform in _risk_opts else 0
        uniform_risk_pct = st.selectbox(
            "리스크 % (균일, 기본 2%)", _risk_opts, index=_idx,
            format_func=lambda x: f"{x:.1f}%",
            help="v6 균일 리스크. combo_risk_table 무시하고 모든 진입에 이 리스크% 적용. 소액테스트 2%, 시드 성장 시 1%로 축소 권장.",
        )
        position_management_enabled = st.toggle(
            "Position Management Enabled",
            value=bool(protection.get("position_management_enabled", True)),
        )
        runner_lifecycle_enabled = bool(protection.get("runner_lifecycle_enabled", True))
        disable_time_exit_for_runner = bool(protection.get("disable_time_exit_for_runner", True))
        runner_fast_2r_bars_max = int(protection.get("runner_fast_2r_bars_max", 3))
        runner_above_2r_bars_min = int(protection.get("runner_above_2r_bars_min", 3))
        runner_max_rr_after_2r_min = float(protection.get("runner_max_rr_after_2r_min", 3.0))
        runner_candidate_min_conds = int(protection.get("runner_candidate_min_conds", 2))
        runner_post_filter_enabled = bool(protection.get("runner_post_filter_enabled", True))
        runner_post_filter_max_rr_after_2r = float(protection.get("runner_post_filter_max_rr_after_2r", 1.5))
        runner_protect_locked_r = float(protection.get("runner_protect_locked_r", 0.30))
        runner_protect_only_if_be_moved = bool(protection.get("runner_protect_only_if_be_moved", True))

    with top_right:
        st.markdown("### 자산별 설정")
        for symbol, cfg in assets.items():
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    cfg["enabled"] = st.toggle(f"{symbol} Enabled", value=bool(cfg.get("enabled", True)), key=f"{symbol}_enabled")
                with c2:
                    # ★risk_pct 는 v4 미사용(combo_risk_table 사용). qty 규격은 거래소 고정 → 읽기전용.
                    st.caption(f"qty_step {cfg.get('qty_step')} · min {cfg.get('min_order_qty')} · dec {cfg.get('qty_decimals')}  (risk=조합테이블·15%캡)")
                # 값 유지 (변경 위젯 없음 = 코드/거래소 고정)
                cfg["risk_pct"] = float(cfg.get("risk_pct", 0.0))
                cfg["qty_step"] = float(cfg.get("qty_step", 0.0))
                cfg["min_order_qty"] = float(cfg.get("min_order_qty", 0.0))
                cfg["qty_decimals"] = int(cfg.get("qty_decimals", 3))

                c6, c7 = st.columns(2)
                with c6:
                    cfg["allow_long"] = st.toggle(f"{symbol} Allow Long", value=bool(cfg.get("allow_long", True)), key=f"{symbol}_long")
                with c7:
                    cfg["allow_short"] = st.toggle(f"{symbol} Allow Short", value=bool(cfg.get("allow_short", True)), key=f"{symbol}_short")

    system["trading_enabled"] = trading_enabled
    portfolio["max_open_positions"] = int(max_open_positions)
    portfolio["risk_multiplier"] = float(risk_multiplier)  # ⭐ v1.9_BASELINE
    portfolio["uniform_risk_pct"] = float(uniform_risk_pct)  # ★v6 균일 리스크% (2/1.5/1)
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

            # ★ [PATCHED May 19 — C 패치]
            # 강화된 검증: cmdline 까지 확인해서 PID 재사용/stale PID 케이스 방지
            engine_really_alive = is_main_engine_process(engine_pid)
            watchdog_really_alive = is_watchdog_process(watchdog_pid)

            # ★ 추가 안전: 시스템 전역에서 다른 watchdog 인스턴스 검색
            #    (runtime_state.json 에 기록 안 된 watchdog 도 발견)
            all_watchdog_pids: List[int] = []
            try:
                for p in psutil.process_iter(["pid", "cmdline"]):
                    try:
                        cl = " ".join(p.info.get("cmdline") or [])
                        if "engine_watchdog.py" in cl:
                            all_watchdog_pids.append(p.info["pid"])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                pass

            if engine_really_alive:
                st.warning(f"이미 main.py가 실행 중입니다. (PID: {engine_pid})")
            elif all_watchdog_pids:
                # 시스템에 watchdog 가 1개 이상 있음
                if len(all_watchdog_pids) > 1:
                    st.error(
                        f"⚠️ watchdog 가 {len(all_watchdog_pids)}개 실행 중! "
                        f"PIDs: {all_watchdog_pids}. 수동 정리 필요 (서버에서 pkill 권장)."
                    )
                else:
                    # 정확히 1개 — 재활성화 경로
                    actual_pid = all_watchdog_pids[0]
                    system["stop_requested"] = False
                    system["watchdog_enabled"] = True
                    system["watchdog_pid"] = actual_pid  # 실제 PID 로 갱신
                    system["watchdog_running"] = True
                    system["last_action"] = "watchdog_re_enabled_from_control_panel"
                    save_runtime_state(runtime_state)
                    st.success(f"watchdog.py 재활성화 완료 (PID: {actual_pid})")
                    st.rerun()
            elif watchdog_really_alive:
                # 위 process_iter 검사로 이미 잡혔어야 함. 안전망.
                system["stop_requested"] = False
                system["watchdog_enabled"] = True
                system["last_action"] = "watchdog_re_enabled_from_control_panel"
                save_runtime_state(runtime_state)
                st.success(f"watchdog.py 재활성화 완료 (PID: {watchdog_pid})")
                st.rerun()
            else:
                # 정말로 watchdog 없음 — 새 spawn
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

                # ★ spawn 후 즉시 한 번 더 확인 (race condition 최소화)
                import time as _time
                _time.sleep(0.3)

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

            # ★ [PATCHED May 19 — C 패치]
            # 시스템 전역에서 watchdog / main.py 잔존 프로세스 모두 정리.
            # 좀비 누적 사고 같은 케이스 방지.
            killed_extra: List[int] = []
            try:
                for p in psutil.process_iter(["pid", "cmdline"]):
                    try:
                        cl = " ".join(p.info.get("cmdline") or [])
                        if "engine_watchdog.py" in cl or "main.py" in cl:
                            pid_x = p.info["pid"]
                            # 본인 (streamlit) 제외
                            if pid_x in (system.get("engine_pid"), system.get("watchdog_pid")):
                                continue
                            try:
                                psutil.Process(pid_x).kill()
                                killed_extra.append(pid_x)
                            except Exception:
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                pass

            system["engine_running"] = False
            system["watchdog_running"] = False
            system["engine_pid"] = None
            system["watchdog_pid"] = None
            system["engine_stopped_at"] = datetime.now(timezone.utc).isoformat()
            save_runtime_state(runtime_state)
            if killed_extra:
                st.warning(f"main.py / watchdog.py 종료 + 잔존 프로세스 {len(killed_extra)}개 정리 ({killed_extra})")
            else:
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
                "manual": "✋ MANUAL" if pos.get("manual_position", False) else "",
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

    # ★★★ [PATCHED May 20 — Manual Position] ★★★
    # 사용자가 직접 진입한 포지션을 Manual 로 표시.
    # Manual 표시 시: 봇은 복구 재시도 X, recovery_failed 알림 X, SL/TP 안 건드림.
    #                 단, 신규 진입 차단은 유지 (one-way 모드 포지션 섞임 방지).
    #                 포지션 닫히면 자동으로 목록에서 사라짐.
    if engine_positions_view:
        st.markdown("### ✋ Manual 포지션 관리")
        st.caption(
            "직접 진입한 포지션을 Manual 로 체크하면 봇이 복구/관리/알림을 하지 않습니다. "
            "(신규 진입 차단은 유지되어 포지션 섞임을 방지합니다. 포지션 종료 시 자동 해제)"
        )
        mp_cols = st.columns(min(len(engine_positions_view), 4) or 1)
        for idx, (symbol, pos) in enumerate(engine_positions_view.items()):
            col = mp_cols[idx % len(mp_cols)]
            with col:
                cur_manual = bool(pos.get("manual_position", False))
                side = pos.get("side", "?")
                entry = pos.get("entry_price", "?")
                new_manual = st.checkbox(
                    f"{symbol} ({side} @ {entry})",
                    value=cur_manual,
                    key=f"manual_chk_{symbol}",
                )
                if new_manual != cur_manual:
                    # runtime_state.json 의 managed_positions 직접 갱신
                    rs = load_runtime_state()
                    mp_all = rs.get("managed_positions", {})
                    if symbol in mp_all:
                        mp_all[symbol]["manual_position"] = bool(new_manual)
                        # Manual 로 전환 시 봇 관리 비활성 (충돌 방지)
                        if new_manual:
                            mp_all[symbol]["management_enabled"] = False
                        # engine_positions_view 도 즉시 갱신 (화면 반영)
                        epv = rs.get("engine_positions_view", {})
                        if symbol in epv:
                            epv[symbol]["manual_position"] = bool(new_manual)
                        save_runtime_state(rs)
                        st.success(
                            f"{symbol} manual_position = {new_manual} "
                            f"{'(봇 관리 해제)' if new_manual else '(봇 관리 가능)'}"
                        )
                        st.rerun()
                    else:
                        st.warning(f"{symbol} 가 managed_positions 에 아직 없습니다. 잠시 후 다시 시도.")

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
    """★v4 무장존 모니터 — 터치 시 진입되는 진짜 후보(현재가 근처 무장존)만 표시.
       배경워커(arm_worker) 가 H4마다 계산한 armed_cache.json 을 읽음. (옛 tier zone_cache 폐기)"""
    import json as _json, os as _os, time as _t
    st.subheader("무장존 모니터 (v4 — 터치 시 진입 후보)")

    api_key, api_secret, mode = get_active_api_credentials(live_settings)

    col1, col2 = st.columns([2, 2])
    with col1:
        only_near = st.radio("표시", ["진입 임박(근처)", "전체 무장존"], horizontal=True, key="armed_view",
                             help="진입 임박: 현재가 근처(터치 임박) 후보만. 전체: 대기 중인 모든 무장존(디버깅).")
    with col2:
        near_pct = st.slider("근처 기준 (%) — 현재가↔진입가 거리", 0.1, 3.0, 1.0, 0.1, key="armed_near_pct")

    cache_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "armed_cache.json")
    if not _os.path.exists(cache_path):
        st.error("⚠ armed_cache.json 없음. arm_worker(--loop --live) 첫 계산(~15분) 완료 후 표시됩니다.")
        return
    age = _t.time() - _os.path.getmtime(cache_path)
    try:
        d = _json.load(open(cache_path, encoding="utf-8"))
    except Exception as e:
        st.error(f"캐시 읽기 실패: {e}")
        return
    st.caption(f"📦 armed_cache: {str(d.get('computed_at', '?'))[:19]} | age {int(age/60)}분 | {d.get('config', '?')}")
    if age > 3 * 3600 + 900:
        st.warning(f"⚠ 캐시가 {int(age/60)}분 전 — 워커(arm_worker --loop --live) 가동 확인.")

    ex = None
    if api_key and api_secret:
        try:
            ex = BybitExchange(api_key, api_secret, use_testnet=False, use_demo=(mode == "demo"))
        except Exception:
            ex = None

    active_symbols = [s for s, c in live_settings["assets"].items() if c.get("enabled", False)]
    syms = d.get("symbols", {})
    total_near = 0
    for symbol in active_symbols:
        v = syms.get(symbol)
        if not v:
            continue
        armed = v.get("armed", [])
        if v.get("reason"):
            st.info(f"{symbol}: {v['reason']} (무장 0)")
            continue
        price = None
        if ex is not None:
            try:
                price = float(ex.get_last_price(category="linear", symbol=symbol))
            except Exception:
                price = None
        rows = []
        near_cnt = 0
        for a in armed:
            ent = float(a["entry"])
            dist = (abs(price - ent) / ent * 100.0) if price else None
            near = (dist is not None and dist <= near_pct)
            imminent = (dist is not None and dist <= 0.4)
            if near:
                near_cnt += 1
            if only_near.startswith("진입") and not near:
                continue
            rows.append({
                "우선": a.get("priority"),
                "방향": a["side"],
                "setup": str(a.get("setup", ""))[:28],
                "진입가": round(ent, 6),
                "SL": round(float(a["sl"]), 6),
                "risk%": a.get("risk_pct_tier_adjusted"),
                "거리%": (round(dist, 2) if dist is not None else None),
                "상태": "🔴터치임박" if imminent else ("🟡근처" if near else "대기"),
                "zone": f"[{a['zone_low']:.6g}, {a['zone_high']:.6g}]",
            })
        total_near += near_cnt
        header = f"**{symbol}** — 무장 {len(armed)}개"
        if price:
            header += f" · 현재가 {price:g}"
        header += f" · 근처 {near_cnt}개"
        st.markdown(header)
        if rows:
            import pandas as _pd
            rows.sort(key=lambda r: (r["거리%"] if isinstance(r["거리%"], (int, float)) else 1e9, r["우선"] if r["우선"] is not None else 999))
            st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True)
        elif only_near.startswith("진입"):
            st.caption("  진입 임박 존 없음 (현재가 근처에 무장존 없음)")
    if only_near.startswith("진입"):
        st.info(f"🎯 진입 임박(근처 {near_pct}%) 총 {total_near}개 — 🔴는 엣지 ±0.4%(터치 시 즉시 진입). "
                "무장존 총수가 많아도 실제 진입은 현재가 근처(터치)만 됩니다.")

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
