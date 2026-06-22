"""
================================================================
한투 KIS 인덱스 자동매매 - 시장 거래 시간 체크
================================================================
각 자산의 거래소 개장 시간 (UTC 기준) 정의.
가격 polling 전 시장 closed 인 경우 skip.

[중요]
- 한국 시간(KST) = UTC + 9
- 거래소별 개장 시간이 다름 (24h 거래 X)
- KIS API 시세도 closed 시간엔 stale 반환 가능 → 진입 신호 무효

[표 (UTC 기준)]
거래소         | 시작     | 종료     | 비고
─────────────────────────────────────────────────────────────────
CME (NQ/ES/YM/RTY/NKD)  | 일 22:00 ~ 금 21:00 | 평일 거의 24h (60분 휴식 22:00~23:00)
CBOT (YM)               | CME 와 동일                                
OSE (TPX)               | 23:00 (월) ~ 06:00 (화) + 23:30 (화) ~ 06:00 (수) ...
                          KST: 08:45~15:15 + 16:30~05:55
ICE Europe (FTS, FTSE)  | 07:00 ~ 21:00 (월~금)   KST: 16:00~06:00
HKEX (HSI)              | 01:15~04:00, 05:00~08:00, 09:15~19:00 (월~금)
                          KST: 10:15~13:00 + 14:00~17:00 + 18:15~04:00
TAIFEX (TXF)            | 00:45 ~ 04:45 (T+1) Day session (KST 09:45~13:45)
                          14:00 ~ 04:00 (T+1) Night session (KST 23:00~13:00)
================================================================
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple


# ============================================================
# 거래소별 거래 시간 정의 (UTC 기준)
# ============================================================
# 형식: list of (start_utc_hour, end_utc_hour) 튜플
# 같은 day 내라 가정 (자정 넘는 경우는 처리 분기 추가)
# weekday: 0=Mon, 1=Tue, ..., 4=Fri, 5=Sat, 6=Sun
# ============================================================

# CME / CBOT 거래 시간 (월~금 거의 24h, 22:00~23:00 UTC 휴식)
CME_SESSION_HOURS = {
    # weekday 0(월)~4(금)
    # (start_utc, end_utc, crosses_midnight)
    "weekdays":   [(0, 22), (23, 24)],   # 0~22 + 23~24 (UTC)
    "sunday":     [(22, 24)],             # 일요일 22:00 UTC 부터 시작
    "saturday":   [],                     # 토요일 closed
}

# OSE (TPX) - 일본 시간대 (UTC+9)
# Day session:   09:00 ~ 15:15 JST = 00:00 ~ 06:15 UTC
# Night session: 16:30 ~ 06:00 JST (다음날) = 07:30 ~ 21:00 UTC
OSE_SESSION_HOURS = {
    "weekdays":   [(0, 6), (7, 21)],
    "sunday":     [],
    "saturday":   [],
}

# ICE Europe (FTSE 100) - 영국 시간대
# 거래시간: 08:00 ~ 21:00 GMT = 거의 동일 UTC (BST 일 때만 -1)
# 단순화를 위해 UTC 기준 07:00~21:00 (BST 시즌 보수적으로 시작 빠르게)
ICE_EU_SESSION_HOURS = {
    "weekdays":   [(7, 21)],
    "sunday":     [],
    "saturday":   [],
}

# HKEX (HSI)
# Pre-open: 09:00 (HKT)
# Morning: 09:30~12:00 HKT = 01:30~04:00 UTC
# Afternoon: 13:00~16:00 HKT = 05:00~08:00 UTC
# T+1 Night: 17:15~03:00 HKT = 09:15~19:00 UTC
HKEX_SESSION_HOURS = {
    "weekdays":   [(1, 4), (5, 8), (9, 19)],
    "sunday":     [],
    "saturday":   [],
}

# TAIFEX (TWII)
# Day:   08:45~13:45 TWT = 00:45~05:45 UTC
# Night: 15:00~05:00 (T+1) TWT = 07:00~21:00 UTC (T+1)
TAIFEX_SESSION_HOURS = {
    "weekdays":   [(0, 5), (7, 21)],
    "sunday":     [],
    "saturday":   [(0, 5)],   # 금요일 야간 → 토요일 새벽까지 이어짐
}


# ============================================================
# 거래소 → 세션 매핑
# ============================================================
EXCHANGE_HOURS = {
    "CME":     CME_SESSION_HOURS,
    "CBOT":    CME_SESSION_HOURS,    # CBOT 도 CME 와 동일
    "OSE":     OSE_SESSION_HOURS,
    "ICE_EU":  ICE_EU_SESSION_HOURS,
    "HKEX":    HKEX_SESSION_HOURS,
    "TAIFEX":  TAIFEX_SESSION_HOURS,
}


# ============================================================
# Helper 함수
# ============================================================
def _get_session_for_weekday(exchange: str, weekday: int) -> List[Tuple[int, int]]:
    """weekday 별 거래 시간 반환"""
    sessions = EXCHANGE_HOURS.get(exchange, {})
    if weekday >= 0 and weekday <= 4:
        return sessions.get("weekdays", [])
    elif weekday == 5:  # 토요일
        return sessions.get("saturday", [])
    elif weekday == 6:  # 일요일
        return sessions.get("sunday", [])
    return []


def is_market_open(exchange: str, dt_utc: datetime = None) -> bool:
    """
    특정 거래소가 현재 (또는 주어진 UTC 시각에) 개장 중인지 체크.
    
    Args:
        exchange: "CME" / "OSE" / "ICE_EU" / "HKEX" / "TAIFEX" 중 하나
        dt_utc: UTC datetime (None 이면 현재 시각 사용)
    
    Returns:
        bool: 개장 중이면 True
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    
    weekday = dt_utc.weekday()
    hour = dt_utc.hour
    
    sessions = _get_session_for_weekday(exchange, weekday)
    for start, end in sessions:
        if start <= hour < end:
            return True
    return False


def is_asset_market_open(symbol: str, dt_utc: datetime = None) -> bool:
    """자산이 현재 매매 가능한 시간인지"""
    from kis_assets import ASSET_META
    meta = ASSET_META.get(symbol)
    if not meta:
        return False
    exchange = meta.get("market", "CME")
    return is_market_open(exchange, dt_utc)


def get_market_open_assets(symbols: List[str], dt_utc: datetime = None) -> List[str]:
    """현재 개장 중인 자산만 필터"""
    return [s for s in symbols if is_asset_market_open(s, dt_utc)]


def get_market_status_dict(symbols: List[str], dt_utc: datetime = None) -> Dict[str, bool]:
    """모든 자산의 개장 상태 dict 반환"""
    return {s: is_asset_market_open(s, dt_utc) for s in symbols}


def utc_to_kst_str(dt_utc: datetime) -> str:
    """UTC → KST 문자열"""
    dt_kst = dt_utc.astimezone(timezone(timedelta(hours=9)))
    return dt_kst.strftime("%Y-%m-%d %H:%M:%S KST")


# ============================================================
# 자기 검증
# ============================================================
if __name__ == "__main__":
    from kis_assets import ASSET_META
    
    now_utc = datetime.now(timezone.utc)
    print(f"현재 시각: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} ({utc_to_kst_str(now_utc)})")
    print(f"weekday: {now_utc.weekday()} (0=Mon, 6=Sun)")
    print()
    print(f"{'symbol':<8}{'exchange':<10}{'is_open':<10}")
    print("-" * 40)
    for sym in ASSET_META:
        exch = ASSET_META[sym]["market"]
        is_open = is_market_open(exch, now_utc)
        flag = "✅ OPEN" if is_open else "❌ CLOSED"
        print(f"{sym:<8}{exch:<10}{flag}")
    
    print()
    print(f"개장 중 자산: {get_market_open_assets(list(ASSET_META.keys()))}")
    
    # 시간대별 시뮬
    print()
    print("[시간대별 개장 자산 시뮬 (UTC 기준)]")
    for h in range(0, 24, 2):
        sim_dt = now_utc.replace(hour=h, minute=30)
        opened = get_market_open_assets(list(ASSET_META.keys()), sim_dt)
        kst_h = (h + 9) % 24
        print(f"  UTC {h:02d}:30 (KST {kst_h:02d}:30) → {opened}")
