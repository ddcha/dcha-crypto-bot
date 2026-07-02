from __future__ import annotations
"""
라이브 소액 테스트 루프 — 확정 v4 baseline(룩어헤드 free) + Bybit demo.
안전: DRY_RUN(기본 주문X), TEST 소액 명목가 상한, 하드 risk캡, 최대 포지션/일일주문, 킬스위치, 최소잔고.
사용:
  $env:BYBIT_DEMO_API_KEY="..."; $env:BYBIT_DEMO_API_SECRET="..."
  python main_live.py            # DRY_RUN(config_live.DRY_RUN=True) — 신호·사이징만 로그, 주문 없음
  # 실제 소액주문: config_live.py 에서 DRY_RUN=False 로 명시 전환 (DEMO 유지 권장)
"""
import os, time, json, datetime as dt
import pandas as pd
import config_live as C
import strategy_live as S
from exchange_bybit import BybitExchange

_acted = {}          # symbol -> last acted signal_time (중복 진입 방지)
_daily = {"date": None, "count": 0}


def log(msg: str):
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat()} | {msg}"
    print(line, flush=True)
    try:
        with open(C.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def kill_active() -> bool:
    return os.path.exists(C.KILL_SWITCH_FILE)


def daily_reset():
    today = dt.date.today().isoformat()
    if _daily["date"] != today:
        _daily["date"] = today; _daily["count"] = 0


def get_balance(ex) -> float:
    try:
        resp = ex.get_wallet_balance(); accts = resp.get("result", {}).get("list", [])
        for a in accts:
            for c in a.get("coin", []):
                if c.get("coin") == "USDT":
                    return float(c.get("walletBalance") or c.get("equity") or 0.0)
    except Exception as e:
        log(f"balance error: {e}")
    return 0.0


def open_symbols(ex) -> set:
    out = set()
    try:
        resp = ex.get_positions(category=C.CATEGORY); items = resp.get("result", {}).get("list", [])
        for it in items:
            if float(it.get("size", "0") or 0) > 0:
                out.add(it.get("symbol"))
    except Exception as e:
        log(f"positions error: {e}")
    return out


def compute_qty(ex, symbol: str, price: float, balance: float, risk_pct: float, entry: float, sl: float):
    risk_amt = balance * risk_pct / 100.0; rpu = abs(entry - sl)
    qty = risk_amt / rpu if rpu > 0 else 0.0
    notional = qty * price
    cap_notional = balance * C.MAX_NOTIONAL_MULT
    if C.TEST_MODE:
        cap_notional = min(cap_notional, C.TEST_FIXED_NOTIONAL_USDT)   # ★소액 상한
    if notional > cap_notional:
        qty = cap_notional / price
    info = ex.get_instrument_info(C.CATEGORY, symbol)
    step = info["qty_step"]; qty = round(qty / step) * step
    qty = round(qty, info["qty_decimals"])
    return qty, info


def try_enter(ex, sig: dict, balance: float):
    symbol = sig["symbol"]; side = "Buy" if sig["side"] == "long" else "Sell"
    price = ex.get_last_price(C.CATEGORY, symbol)
    qty, info = compute_qty(ex, symbol, price, balance, sig["risk_pct"], sig["entry"], sig["sl"])
    if qty < info["min_qty"] or qty <= 0:
        log(f"[SKIP] {symbol} qty {qty} < min {info['min_qty']} (명목가 너무 작음)"); return False
    plan = f"{symbol} {side} qty={qty} px~{price:.6f} SL={sig['sl']:.6f} risk={sig['risk_pct']:.2f}% setup={sig['setup']} zone={sig['btc_zone']}"
    if C.DRY_RUN:
        log(f"[DRY_RUN 진입예정] {plan}"); return True
    # 실주문
    res = ex.place_market_order_and_wait(category=C.CATEGORY, symbol=symbol, side=side, qty=qty)
    log(f"[ORDER] {plan} → {res.get('avg_price')}")
    fill = ex.wait_for_position_fill_info(category=C.CATEGORY, symbol=symbol, expected_side=side, min_qty=qty * 0.5)
    if fill:
        sl_res = ex.set_stop_loss_only(category=C.CATEGORY, symbol=symbol, stop_loss=round(sig["sl"], 6))
        log(f"[SL] {symbol} SL={sig['sl']:.6f} set → {sl_res.get('retMsg', 'ok')}")
    return True


def loop_once(ex):
    daily_reset()
    if kill_active():
        log("KILL 스위치 활성 — 신규진입 중단"); return
    bal = get_balance(ex)
    if bal < C.MIN_BALANCE_USDT:
        log(f"잔고 {bal:.2f} < {C.MIN_BALANCE_USDT} — 신규진입 중단"); return
    if _daily["count"] >= C.MAX_DAILY_ORDERS:
        log(f"일일 주문한도 {C.MAX_DAILY_ORDERS} 도달"); return
    # BTC 레짐
    btc = ex.get_recent_klines_df(C.CATEGORY, C.BTC_SYMBOL, C.H4_INTERVAL, C.H4_LIMIT)
    S.set_btc_regime(btc)
    opened = open_symbols(ex)
    if len(opened) >= C.MAX_OPEN_POSITIONS:
        log(f"최대 포지션 {C.MAX_OPEN_POSITIONS} 도달 ({opened})"); return
    for sym in C.SYMBOLS:
        if sym in opened:
            continue
        try:
            h4 = ex.get_recent_klines_df(C.CATEGORY, sym, C.H4_INTERVAL, C.H4_LIMIT)
            h1 = ex.get_recent_klines_df(C.CATEGORY, sym, C.H1_INTERVAL, C.H1_LIMIT)
            sig = S.get_live_signal(sym, h4, h1, C)
            if not sig.get("should_enter"):
                continue
            if _acted.get(sym) == sig["signal_time"]:
                continue   # 이미 처리한 신호
            log(f"[SIGNAL] {sym} {sig['side']} setup={sig['setup']} zone={sig['btc_zone']} risk={sig['risk_pct']:.2f}% t={sig['signal_time']}")
            if try_enter(ex, sig, bal):
                _acted[sym] = sig["signal_time"]; _daily["count"] += 1
                if len(open_symbols(ex)) >= C.MAX_OPEN_POSITIONS and not C.DRY_RUN:
                    break
        except Exception as e:
            log(f"[{sym}] error: {e}")


def main():
    k, s = C.resolve_api_credentials()
    mode = "DEMO" if C.USE_DEMO else ("TESTNET" if C.USE_TESTNET else "LIVE")
    log(f"=== live_v4 시작 | {mode} | DRY_RUN={C.DRY_RUN} TEST_MODE={C.TEST_MODE} 소액상한={C.TEST_FIXED_NOTIONAL_USDT}USDT ===")
    if not k or not s:
        log("❌ API 키 없음 (BYBIT_DEMO_API_KEY/SECRET 환경변수 설정 필요) — 종료"); return
    ex = BybitExchange(api_key=k, api_secret=s, use_testnet=C.USE_TESTNET, use_demo=C.USE_DEMO)
    S.init(C)
    log(f"엔진 초기화 완료 | 심볼 {len(C.SYMBOLS)} | 규칙 {len(S._RULES)} | risk테이블 {len(S._RISK)}조합")
    log(f"잔고: {get_balance(ex):.2f} USDT")
    while True:
        try:
            loop_once(ex)
        except Exception as e:
            log(f"loop error: {e}")
        time.sleep(C.LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
