#!/usr/bin/env python3
"""★무장존 지정가 배치 로직 (순수함수, 테스트가능). main 이 호출만 하면 됨.
   armed_cache(워커산출) + 현재가 + 미체결주문 + 포지션여부 → 거치/취소 액션.
   설계:
   - 포지션 보유 심볼: 모든 진입지정가 취소(단포지션 = 백테와 동일).
   - 미보유: 현재가 proximity 내 무장존을 우선순위(백테 scored_active 순)로 최대 N개 지정가 거치.
     더 이상 근처 아님/스테일 주문은 취소. 캐시 갱신(H4)마다 재평가.
   - 체결 감지(포지션 출현) → orderLinkId 로 무장 payload 역참조 → 기존 build_managed_position/SL·TP.
"""
import json


def link_id(symbol: str, a: dict) -> str:
    """존/방향 결정론적 주문ID (체결 시 payload 역참조용). Bybit orderLinkId 는 심볼내 유일."""
    return f"arm-{symbol}-{a['side'][:1]}-{a['zone_low']:.8g}"


def load_armed_cache(path: str, symbol: str, max_age_sec: float = 5.0 * 3600) -> dict:
    """워커 캐시에서 심볼 무장목록 로드. 너무 오래된 캐시(H4 초과)는 무시."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {"armed": [], "stale": True}
    sym = d.get("symbols", {}).get(symbol, {})
    return {"armed": sym.get("armed", []), "computed_at": d.get("computed_at"),
            "timestamp": sym.get("timestamp"), "stale": False}


def plan_armed_orders(symbol: str, armed_list: list, current_price: float, proximity_pct: float,
                      existing_link_ids: set, has_position: bool, max_orders: int = 3) -> dict:
    """무장존+상태 → {place:[payload+link_id], cancel:[link_id]}. 순수함수."""
    existing_link_ids = set(existing_link_ids or [])
    if has_position:
        # ★단포지션: 진입 지정가 전부 취소 (하나 체결되면 나머지 무효)
        return {"place": [], "cancel": sorted(existing_link_ids)}
    if not current_price or current_price <= 0:
        return {"place": [], "cancel": []}
    near = []
    for a in armed_list:                                  # armed_list = 우선순위순(0=최우선)
        edge = float(a["entry"])                          # 지정가 = 존 엣지(백테 fill 가)
        if abs(edge - current_price) / current_price <= proximity_pct:
            near.append(a)
        if len(near) >= max_orders:
            break
    want = {}
    for a in near:
        want[link_id(symbol, a)] = a
    place = [dict(a, link_id=lid) for lid, a in want.items() if lid not in existing_link_ids]
    cancel = sorted(lid for lid in existing_link_ids if lid not in want)   # 근처 이탈/스테일 취소
    return {"place": place, "cancel": cancel}


def match_fill_to_armed(symbol: str, filled_link_id: str, armed_list: list) -> dict:
    """체결된 orderLinkId → 해당 무장 payload (build_managed_position 용 setup/sl/tp_plan/risk)."""
    for a in armed_list:
        if link_id(symbol, a) == filled_link_id:
            return a
    return None
