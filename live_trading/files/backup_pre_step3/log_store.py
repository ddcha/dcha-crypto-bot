from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

RUNTIME_LOG_FILE = LOG_DIR / "main_runtime.log"
SYSTEM_LOG_CSV = LOG_DIR / "system_log.csv"
TRADE_LOG_CSV = LOG_DIR / "trade_log.csv"
TRADE_JOURNAL_CSV = LOG_DIR / "trade_journal.csv"


# trade_log.csv 에 남길 핵심 거래 이벤트만 허용
ALLOWED_TRADE_EVENTS = {
    "order_submitted",
    "order_filled",
    "order_fill_sync_pending",
    "fill_sync_completed",
    "initial_sl_attached",
    "tp1_limit_submitted",
    "tp1_exchange_filled",
    "tp1_fallback_be_moved",
    "tp1_exchange_order_recovered",
    "tp1_limit_cancelled",
    "be_moved",
    "tp1_closed",
    "tp2_closed",
    "runner_candidate_2of3",
    "runner_post_filter_ok",
    "runner_protected",
    "runner_active",
    "runner_trailing_stop_updated",
    "position_time_exit",
    "managed_position_removed",
    "managed_position_recovered",
    "managed_position_recovery_failed",
    "tier_classified",
    "tier_skipped_d",
    "emergency_close_submitted",
    "emergency_close_all_completed",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return value


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _normalize_value(v) for k, v in row.items()}


def _monthly_path(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}_{current_month_key()}{base_path.suffix}")


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader]
    except Exception:
        return []


def _write_csv_rows(path: Path, rows: List[Dict[str, Any]]) -> None:
    rows = [_normalize_row(r) for r in rows]

    all_keys: List[str] = []
    seen = set()

    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                all_keys.append(key)

    if not all_keys:
        all_keys = ["ts"]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=all_keys,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _append_csv_row(path: Path, row: Dict[str, Any]) -> None:
    try:
        row = _normalize_row(row)
        for target in (path, _monthly_path(path)):
            existing_rows = _read_csv_rows(target)
            existing_rows.append(row)
            _write_csv_rows(target, existing_rows)
    except Exception as e:
        # 로그 실패로 엔진이 멈추지 않게 방어
        print(f"LOG WRITE ERROR [{path.name}]: {e}")


def log_runtime_event(message: str) -> None:
    try:
        line = f"[{utc_now_iso()}] {message}\n"
        with RUNTIME_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"RUNTIME LOG WRITE ERROR: {e}")


def log_system_event(
    event_type: str,
    symbol: str | None = None,
    message: str | None = None,
    extra: Dict[str, Any] | None = None,
) -> None:
    row: Dict[str, Any] = {
        "ts": utc_now_iso(),
        "event_type": event_type,
        "symbol": symbol or "",
        "message": message or "",
    }
    if extra:
        row.update(extra)

    _append_csv_row(SYSTEM_LOG_CSV, row)
    log_runtime_event(f"SYSTEM {event_type} symbol={symbol or ''} message={message or ''}")


def log_trade_event(
    event_type: str,
    symbol: str,
    side: str | None = None,
    qty: float | str | None = None,
    price: float | str | None = None,
    signal_ts: str | None = None,
    reason: str | None = None,
    extra: Dict[str, Any] | None = None,
) -> None:
    # 거래 복기에 의미 없는 이벤트는 trade_log.csv 에 기록하지 않음
    if event_type not in ALLOWED_TRADE_EVENTS:
        return

    row: Dict[str, Any] = {
        "ts": utc_now_iso(),
        "event_type": event_type,
        "symbol": symbol,
        "side": side or "",
        "qty": qty if qty is not None else "",
        "price": price if price is not None else "",
        "signal_ts": signal_ts or "",
        "reason": reason or "",
    }
    if extra:
        row.update(extra)

    _append_csv_row(TRADE_LOG_CSV, row)
    log_runtime_event(f"TRADE {event_type} {symbol} side={side or ''} qty={qty if qty is not None else ''} price={price if price is not None else ''} reason={reason or ''}")


def _journal_key(symbol: str, signal_ts: str) -> str:
    return f"{symbol}__{signal_ts}"


def upsert_trade_journal(symbol: str, signal_ts: str, fields: Dict[str, Any]) -> None:
    rows = _read_csv_rows(TRADE_JOURNAL_CSV)
    key = _journal_key(symbol, signal_ts)

    target_index = None
    for i, row in enumerate(rows):
        if row.get("_journal_key", "") == key:
            target_index = i
            break

    base_row: Dict[str, Any] = {
        "_journal_key": key,
        "symbol": symbol,
        "signal_ts": signal_ts,
        "opened_at": utc_now_iso(),
        "closed_at": "",
        "status": "open",
    }
    base_row.update(_normalize_row(fields))

    if target_index is None:
        rows.append(base_row)
    else:
        opened_at = rows[target_index].get("opened_at", "") or base_row["opened_at"]
        rows[target_index].update(base_row)
        rows[target_index]["opened_at"] = opened_at

    _write_csv_rows(TRADE_JOURNAL_CSV, rows)
    _write_csv_rows(_monthly_path(TRADE_JOURNAL_CSV), rows)


def close_trade_journal(symbol: str, signal_ts: str, fields: Dict[str, Any]) -> None:
    rows = _read_csv_rows(TRADE_JOURNAL_CSV)
    key = _journal_key(symbol, signal_ts)

    target_index = None
    for i, row in enumerate(rows):
        if row.get("_journal_key", "") == key:
            target_index = i
            break

    close_fields = _normalize_row(fields)

    if target_index is None:
        row: Dict[str, Any] = {
            "_journal_key": key,
            "symbol": symbol,
            "signal_ts": signal_ts,
            "opened_at": utc_now_iso(),
            "closed_at": utc_now_iso(),
            "status": "closed",
        }
        row.update(close_fields)
        rows.append(row)
    else:
        rows[target_index].update(close_fields)
        rows[target_index]["status"] = "closed"
        rows[target_index]["closed_at"] = utc_now_iso()

    _write_csv_rows(TRADE_JOURNAL_CSV, rows)
    _write_csv_rows(_monthly_path(TRADE_JOURNAL_CSV), rows)


def load_trade_journal_rows(limit: int = 300) -> List[Dict[str, Any]]:
    rows = _read_csv_rows(TRADE_JOURNAL_CSV)
    if not rows:
        return []

    def sort_key(r: Dict[str, Any]) -> str:
        return str(r.get("opened_at", "") or "")

    rows = sorted(rows, key=sort_key, reverse=True)
    return rows[:limit]
