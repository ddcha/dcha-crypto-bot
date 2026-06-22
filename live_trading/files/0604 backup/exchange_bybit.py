from __future__ import annotations

from typing import Any, Dict, Optional
import time
import pandas as pd
from pybit.unified_trading import HTTP

from config import READ_API_MAX_RETRIES, READ_API_RETRY_SLEEP_SECONDS


class BybitExchange:
    def __init__(self, api_key: str, api_secret: str, use_testnet: bool = False, use_demo: bool = True):
        self.use_testnet = bool(use_testnet)
        self.use_demo = bool(use_demo)
        self.session = HTTP(testnet=self.use_testnet, demo=self.use_demo, api_key=api_key, api_secret=api_secret)

    def _call_with_retry(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(1, READ_API_MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt >= READ_API_MAX_RETRIES:
                    raise
                time.sleep(READ_API_RETRY_SLEEP_SECONDS)
        raise last_error

    def get_server_time(self) -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_server_time)

    def get_wallet_balance(self, account_type: str = "UNIFIED", coin: str = "USDT") -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_wallet_balance, accountType=account_type, coin=coin)

    def get_positions(self, category: str = "linear", symbol: Optional[str] = None, settle_coin: Optional[str] = "USDT") -> Dict[str, Any]:
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        elif settle_coin:
            params["settleCoin"] = settle_coin
        return self._call_with_retry(self.session.get_positions, **params)

    def get_position_by_symbol(self, category: str, symbol: str) -> Dict[str, Any]:
        return self.get_positions(category=category, symbol=symbol, settle_coin=None)

    def get_kline(self, category: str = "linear", symbol: str = "BTCUSDT", interval: str = "60", limit: int = 200) -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_kline, category=category, symbol=symbol, interval=interval, limit=limit)

    def get_tickers(self, category: str = "linear", symbol: Optional[str] = None) -> Dict[str, Any]:
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._call_with_retry(self.session.get_tickers, **params)

    def get_last_price(self, category: str, symbol: str) -> float:
        resp = self.get_tickers(category=category, symbol=symbol)
        items = resp.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"No ticker data returned for {symbol}")
        return float(items[0]["lastPrice"])

    def get_orderbook(self, category: str, symbol: str, limit: int = 50) -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_orderbook, category=category, symbol=symbol, limit=limit)

    def estimate_market_fill_price(self, category: str, symbol: str, side: str, qty: float, limit: int = 50) -> float:
        resp = self.get_orderbook(category=category, symbol=symbol, limit=limit)
        result = resp.get("result", {})
        levels = result.get("a", []) if str(side) == "Buy" else result.get("b", [])
        remain = float(qty)
        notional_sum = 0.0
        filled_sum = 0.0
        for lv in levels:
            try:
                px = float(lv[0]); sz = float(lv[1])
            except Exception:
                continue
            if px <= 0 or sz <= 0:
                continue
            take = min(remain, sz)
            notional_sum += take * px
            filled_sum += take
            remain -= take
            if remain <= 1e-12:
                break
        if filled_sum <= 1e-12:
            return self.get_last_price(category=category, symbol=symbol)
        return notional_sum / filled_sum

    def place_market_order(self, category: str, symbol: str, side: str, qty: float, reduce_only: bool = False) -> Dict[str, Any]:
        return self.session.place_order(category=category, symbol=symbol, side=side, orderType="Market", qty=str(qty), timeInForce="IOC", reduceOnly=reduce_only)

    def place_reduce_only_limit_order(
        self,
        category: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        return self.session.place_order(
            category=category,
            symbol=symbol,
            side=side,
            orderType="Limit",
            qty=str(qty),
            price=str(price),
            timeInForce=time_in_force,
            reduceOnly=True,
            closeOnTrigger=False,
        )

    def _extract_order_id(self, response: Dict[str, Any]) -> str:
        return str(response.get("result", {}).get("orderId", ""))

    def get_order_history(self, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_order_history, category=category, symbol=symbol, orderId=order_id)

    def get_open_orders(self, category: str, symbol: str, order_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"category": category, "symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        return self._call_with_retry(self.session.get_open_orders, **params)

    def cancel_order(self, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
        return self._call_with_retry(self.session.cancel_order, category=category, symbol=symbol, orderId=order_id)

    def get_closed_pnl(self, category: str, symbol: str, limit: int = 50) -> Dict[str, Any]:
        return self._call_with_retry(self.session.get_closed_pnl, category=category, symbol=symbol, limit=limit)

    def place_market_order_and_wait(self, category: str, symbol: str, side: str, qty: float, reduce_only: bool = False, retries: int = 10, sleep_seconds: float = 0.7) -> Dict[str, Any]:
        resp = self.place_market_order(category=category, symbol=symbol, side=side, qty=qty, reduce_only=reduce_only)
        order_id = self._extract_order_id(resp)
        avg_price = None
        if order_id:
            for _ in range(retries):
                try:
                    hist = self.get_order_history(category=category, symbol=symbol, order_id=order_id)
                    items = hist.get("result", {}).get("list", [])
                    if items:
                        raw = items[0]
                        for key in ("avgPrice", "cumExecAvgPrice", "price"):
                            val = raw.get(key)
                            try:
                                if val not in (None, "") and float(val) > 0:
                                    avg_price = float(val)
                                    return {"response": resp, "avg_price": avg_price, "raw": raw}
                            except Exception:
                                pass
                except Exception:
                    pass
                time.sleep(sleep_seconds)
        return {"response": resp, "avg_price": avg_price, "raw": {}}

    def set_stop_loss_only(self, category: str, symbol: str, stop_loss: float, position_idx: int = 0, sl_trigger_by: str = "LastPrice") -> Dict[str, Any]:
        # ★ [PATCHED 2026-06-02] ErrCode 34040 "not modified" 정상 처리.
        # 거래소가 SL 을 tick 단위로 반올림 저장하는데(예: BNB 705.8035714 → 705.80),
        # 봇이 부동소수점 계산값으로 매 루프 재설정 시도 → 같은 값이라 34040 거부 →
        # main_loop_error 로그 폭주 → 엔진 불안정 → watchdog RUNAWAY 의 숨은 원인.
        # 34040 은 "이미 그 SL 이 걸려있다"는 뜻이므로 실패가 아니라 성공으로 간주한다.
        try:
            return self.session.set_trading_stop(
                category=category, symbol=symbol, tpslMode="Full",
                positionIdx=position_idx, stopLoss=str(stop_loss), slTriggerBy=sl_trigger_by,
            )
        except Exception as e:
            msg = str(e)
            if ("34040" in msg) or ("not modified" in msg.lower()):
                # 이미 동일 SL 설정됨 — 포지션은 보호되고 있으므로 성공 처리
                return {"retCode": 0, "retMsg": "not_modified_ok", "result": {}, "_sl_unchanged": True}
            raise

    def close_position_market(self, category: str, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        close_side = "Sell" if side == "Buy" else "Buy"
        return self.place_market_order_and_wait(category=category, symbol=symbol, side=close_side, qty=qty, reduce_only=True)

    def wait_for_position_fill_info(self, category: str, symbol: str, expected_side: str, min_qty: float = 0.0, retries: int = 10, sleep_seconds: float = 0.7) -> Dict[str, Any] | None:
        for _ in range(retries):
            resp = self.get_position_by_symbol(category=category, symbol=symbol)
            items = resp.get("result", {}).get("list", [])
            for item in items:
                try:
                    item_side = str(item.get("side", "")); item_qty = float(item.get("size", "0") or 0.0)
                except Exception:
                    item_side = ""; item_qty = 0.0
                if item_qty <= 0:
                    continue
                if expected_side and item_side != expected_side:
                    continue
                avg_price_raw = item.get("avgPrice") or item.get("avgEntryPrice") or item.get("markPrice") or "0"
                try:
                    avg_price = float(avg_price_raw or 0.0)
                except Exception:
                    avg_price = 0.0
                return {"symbol": symbol, "side": item_side, "qty": item_qty, "avg_price": avg_price, "raw": item, "response": resp}
            time.sleep(sleep_seconds)
        return None

    def get_order_fill_status(self, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
        """Return normalized status for a specific order id."""
        open_resp = self.get_open_orders(category=category, symbol=symbol, order_id=order_id)
        open_items = open_resp.get("result", {}).get("list", [])
        if open_items:
            raw = open_items[0]
            return {
                "found": True,
                "is_open": True,
                "is_filled": False,
                "cum_exec_qty": float(raw.get("cumExecQty") or 0.0),
                "leaves_qty": float(raw.get("leavesQty") or 0.0),
                "avg_price": float(raw.get("avgPrice") or raw.get("cumExecAvgPrice") or 0.0),
                "status": str(raw.get("orderStatus", "")),
                "raw": raw,
            }

        hist_resp = self.get_order_history(category=category, symbol=symbol, order_id=order_id)
        hist_items = hist_resp.get("result", {}).get("list", [])
        if hist_items:
            raw = hist_items[0]
            status = str(raw.get("orderStatus", ""))
            cum_exec_qty = float(raw.get("cumExecQty") or 0.0)
            return {
                "found": True,
                "is_open": False,
                "is_filled": status == "Filled" or cum_exec_qty > 0,
                "cum_exec_qty": cum_exec_qty,
                "leaves_qty": float(raw.get("leavesQty") or 0.0),
                "avg_price": float(raw.get("avgPrice") or raw.get("cumExecAvgPrice") or 0.0),
                "status": status,
                "raw": raw,
            }

        return {
            "found": False,
            "is_open": False,
            "is_filled": False,
            "cum_exec_qty": 0.0,
            "leaves_qty": 0.0,
            "avg_price": 0.0,
            "status": "",
            "raw": {},
        }

    def get_recent_klines_df(self, category: str, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        resp = self.get_kline(category=category, symbol=symbol, interval=interval, limit=limit)
        items = resp.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"No kline data returned for {symbol} {interval}")
        rows = []
        for item in items:
            rows.append({"timestamp": pd.to_datetime(int(item[0]), unit="ms", utc=True), "open": float(item[1]), "high": float(item[2]), "low": float(item[3]), "close": float(item[4]), "volume": float(item[5])})
        return pd.DataFrame(rows).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
