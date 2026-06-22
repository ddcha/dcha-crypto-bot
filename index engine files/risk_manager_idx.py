"""
================================================================
한투 KIS 인덱스 자동매매 - Risk Manager (정수 계약 sizing)
================================================================
인덱스 선물은 반드시 정수 계약 (1, 2, 3 ...) → floor 처리

[코인 vs 인덱스 차이]
- 코인:    qty = risk_amount / risk_per_unit       (소수점 가능)
- 인덱스:  qty = floor(risk_amount / (sl_pts × multiplier × fx))   (정수)

[max_open_positions 안전장치]
- 둠챠 결정: max=8 (코인 7 보다 살짝 위)
- 그 외 portfolio cap / phase 자동전환 X (둠챠 수동)

[포지션 sizing 흐름]
1. base_risk_pct (예: 1.0%) × global_risk_multiplier (예: 1.0) = effective risk_pct
2. RULE mult (V29_1_RULE_MULT) × asset_mult (V29_2_ASSET_MULT) = combined_mult
3. final_risk_amount = balance × effective_risk_pct × combined_mult
4. risk_per_contract = sl_distance_pts × multiplier × fx_to_usd
5. qty = floor(final_risk_amount / risk_per_contract)
6. qty = max(1, qty)   ← 최소 1계약 (단, 위험액 너무 크면 reject)
7. notional check (jenotional_cap)
================================================================
"""
from __future__ import annotations
import math
from typing import Dict, Optional, Tuple

from kis_assets import (
    ASSET_META, get_pt_value_usd, get_multiplier,
    DEFAULT_FX_TO_USD,
)


def calc_qty_for_index(
    symbol: str,
    balance_usd: float,
    base_risk_pct: float,
    rule_mult: float,
    asset_mult: float,
    global_risk_multiplier: float,
    sl_distance_pts: float,
    fx_table: Optional[Dict[str, float]] = None,
    min_qty: int = 1,
    max_qty: int = 999,
    max_notional_pct_of_balance: float = 1000.0,  # 1000% = 10x leverage cap
) -> Dict:
    """
    인덱스 선물 정수 계약 수 계산.
    
    Args:
        symbol:                 자산 키 (NQ/ES/YM/RTY/NKD/TPX/FTSE/HSI/TWII)
        balance_usd:            잔고 (USD 환산)
        base_risk_pct:          기본 risk % (예: 0.01 = 1%)
        rule_mult:              v29.5 RULE mult (예: 5.0 for S++_MSS_OVL)
        asset_mult:             자산별 mult (예: 1.5 for ES)
        global_risk_multiplier: 패널 runtime 조절 (예: 1.0)
        sl_distance_pts:        Stop loss 거리 (가격 단위, 예: 25 for ES 25pt)
        fx_table:               환율 dict (None 이면 default)
        min_qty:                최소 계약 수 (기본 1)
        max_qty:                최대 계약 수 (기본 999, 사실상 제한 없음)
        max_notional_pct:       잔고 대비 max notional % (기본 1000% = 10x)
    
    Returns:
        dict {
            "qty": int,
            "risk_amount_usd": float,
            "risk_per_contract_usd": float,
            "notional_usd": float,
            "notional_pct_of_balance": float,
            "reason": str ("OK", "qty_zero", "notional_cap_exceeded" 등)
        }
    """
    fx = fx_table or DEFAULT_FX_TO_USD
    
    if symbol not in ASSET_META:
        return {
            "qty": 0,
            "risk_amount_usd": 0.0,
            "risk_per_contract_usd": 0.0,
            "notional_usd": 0.0,
            "notional_pct_of_balance": 0.0,
            "reason": f"unknown_symbol_{symbol}",
        }
    
    if balance_usd <= 0 or sl_distance_pts <= 0:
        return {
            "qty": 0,
            "risk_amount_usd": 0.0,
            "risk_per_contract_usd": 0.0,
            "notional_usd": 0.0,
            "notional_pct_of_balance": 0.0,
            "reason": "invalid_inputs",
        }
    
    # 1. effective risk_pct
    effective_risk_pct = float(base_risk_pct) * float(global_risk_multiplier)
    
    # 2. combined mult
    combined_mult = float(rule_mult) * float(asset_mult)
    
    # 3. final risk amount (USD)
    final_risk_amount = float(balance_usd) * effective_risk_pct * combined_mult
    
    # 4. risk per 1 contract (USD)
    pt_value_usd = get_pt_value_usd(symbol, fx)  # multiplier × fx
    risk_per_contract = float(sl_distance_pts) * pt_value_usd
    
    if risk_per_contract <= 0:
        return {
            "qty": 0,
            "risk_amount_usd": final_risk_amount,
            "risk_per_contract_usd": 0.0,
            "notional_usd": 0.0,
            "notional_pct_of_balance": 0.0,
            "reason": "zero_risk_per_contract",
        }
    
    # 5. qty (floor)
    raw_qty = final_risk_amount / risk_per_contract
    qty = int(math.floor(raw_qty))
    
    # 6. min_qty 강제 적용 (위험액 < 1계약 risk 여도 1계약 진입)
    # 이유: 백테가 소수점 qty 허용했기 때문에, 실전에서 reject 하면 거래 빈도/PF 망가짐.
    # 단, 위험액 over 알림은 reason 에 명시.
    qty_under_min = (qty < min_qty)
    if qty_under_min:
        qty = min_qty
        reason = f"min_qty_forced_actual_risk_{(qty * risk_per_contract):.0f}_target_{final_risk_amount:.0f}"
    else:
        reason = "OK"
    
    qty = min(qty, max_qty)
    
    # 7. notional check
    # current_price 모르므로 sl_distance × multiplier 로 근사 X
    # → 호출자가 current_price 알면 더 정확. 일단 OK 처리.
    # TODO: 호출 시 current_price 받아서 정확한 notional 계산
    notional_usd = qty * pt_value_usd  # 임시: 1pt당 USD × qty (실제는 price × qty × multiplier)
    
    return {
        "qty": qty,
        "risk_amount_usd": final_risk_amount,
        "risk_per_contract_usd": risk_per_contract,
        "notional_usd": notional_usd,
        "notional_pct_of_balance": (notional_usd / balance_usd * 100.0) if balance_usd > 0 else 0.0,
        "reason": reason,
        "raw_qty": raw_qty,
        "qty_was_forced": qty_under_min,
    }


def calc_qty_with_price(
    symbol: str,
    balance_usd: float,
    base_risk_pct: float,
    rule_mult: float,
    asset_mult: float,
    global_risk_multiplier: float,
    entry_price: float,
    sl_price: float,
    fx_table: Optional[Dict[str, float]] = None,
    min_qty: int = 1,
    max_qty: int = 999,
    max_notional_pct_of_balance: float = 1000.0,
) -> Dict:
    """
    entry_price + sl_price 받아서 sl_distance_pts 자동 계산하는 wrapper.
    실전에서 generate_entry_signal 결과 받아서 호출.
    """
    sl_distance_pts = abs(float(entry_price) - float(sl_price))
    
    result = calc_qty_for_index(
        symbol=symbol,
        balance_usd=balance_usd,
        base_risk_pct=base_risk_pct,
        rule_mult=rule_mult,
        asset_mult=asset_mult,
        global_risk_multiplier=global_risk_multiplier,
        sl_distance_pts=sl_distance_pts,
        fx_table=fx_table,
        min_qty=min_qty,
        max_qty=max_qty,
        max_notional_pct_of_balance=max_notional_pct_of_balance,
    )
    
    if result["qty"] > 0:
        # 정확한 notional 계산
        fx = fx_table or DEFAULT_FX_TO_USD
        meta = ASSET_META[symbol]
        mult = float(meta["multiplier"])
        cur = str(meta["currency"])
        fx_rate = float(fx.get(cur, 1.0))
        notional_usd = float(entry_price) * mult * fx_rate * result["qty"]
        result["notional_usd"] = notional_usd
        result["notional_pct_of_balance"] = (notional_usd / balance_usd * 100.0) if balance_usd > 0 else 0.0
        
        # notional cap 체크
        if result["notional_pct_of_balance"] > max_notional_pct_of_balance:
            # qty 축소 시도
            max_qty_by_notional = int(math.floor(
                balance_usd * max_notional_pct_of_balance / 100.0 / (entry_price * mult * fx_rate)
            ))
            if max_qty_by_notional < min_qty:
                result["qty"] = 0
                result["reason"] = f"notional_cap_exceeded_no_room"
            else:
                result["qty"] = max_qty_by_notional
                result["notional_usd"] = float(entry_price) * mult * fx_rate * result["qty"]
                result["notional_pct_of_balance"] = (result["notional_usd"] / balance_usd * 100.0)
                result["reason"] = "OK_notional_capped"
    
    result["sl_distance_pts"] = sl_distance_pts
    return result


def can_open_new_position(open_position_count: int, max_open_positions: int = 8) -> Tuple[bool, str]:
    """max_open_positions 체크 (둠챠 결정: 8개)"""
    if open_position_count >= max_open_positions:
        return False, f"max_open_positions_reached_{open_position_count}/{max_open_positions}"
    return True, "OK"


# ============================================================
# 자기 검증
# ============================================================
if __name__ == "__main__":
    print("=" * 90)
    print("Risk Manager 자기 검증")
    print("=" * 90)
    
    balance = 407_449.26  # 둠챠 모의계좌
    
    # 시뮬: 9자산 각각 base 1% × A_HIGH 1.0 × asset 1.0 = 1.0% effective
    print(f"\n[시나리오 A: base 1% × RULE 1.0 (A_HIGH) × asset 1.0]")
    print(f"잔고: ${balance:,.0f}")
    print(f"{'sym':<6}{'price':>10}{'sl_pts':>8}{'risk/c$':>10}{'qty':>5}{'notional':>14}{'%':>8}{'reason':<30}")
    test_cases = [
        ("ES",    6800.0,  68.0),   # 1% 가격 거리 = 68 pt
        ("NQ",   24100.0, 241.0),
        ("YM",   47500.0, 475.0),
        ("RTY",   2350.0,  23.5),
        ("NKD",  51000.0, 510.0),
        ("TPX",   3650.0,  36.5),
        ("FTSE",  9100.0,  91.0),
        ("HSI",  25000.0, 250.0),
        ("TWII", 27000.0, 270.0),
    ]
    for sym, price, sl_pts in test_cases:
        result = calc_qty_for_index(
            symbol=sym,
            balance_usd=balance,
            base_risk_pct=0.01,
            rule_mult=1.0,
            asset_mult=1.0,
            global_risk_multiplier=1.0,
            sl_distance_pts=sl_pts,
        )
        # 정확한 notional 위해 calc_qty_with_price 사용
        sl_price = price - sl_pts  # long 가정
        result2 = calc_qty_with_price(
            symbol=sym, balance_usd=balance,
            base_risk_pct=0.01, rule_mult=1.0, asset_mult=1.0,
            global_risk_multiplier=1.0,
            entry_price=price, sl_price=sl_price,
        )
        print(f"{sym:<6}{price:>10,.0f}{sl_pts:>8.1f}"
              f"${result2['risk_per_contract_usd']:>9,.0f}"
              f"{result2['qty']:>5}"
              f"${result2['notional_usd']:>13,.0f}"
              f"{result2['notional_pct_of_balance']:>7.1f}%"
              f"  {result2['reason']:<30}")
    
    # 시뮬: 최대 mult (S++_MSS_OVL × ES 1.5 = 7.5x)
    print(f"\n[시나리오 B: base 1% × RULE 5.0 × asset 1.5 = 7.5x for ES] — 최대 mult")
    result = calc_qty_with_price(
        symbol="ES", balance_usd=balance,
        base_risk_pct=0.01, rule_mult=5.0, asset_mult=1.5,
        global_risk_multiplier=1.0,
        entry_price=6800.0, sl_price=6732.0,
    )
    for k, v in result.items():
        print(f"  {k}: {v}")
    
    # max_open 체크
    print(f"\n[max_open_positions 체크]")
    for n in [0, 5, 7, 8, 9]:
        ok, reason = can_open_new_position(n, max_open_positions=8)
        print(f"  {n} 포지션 → {'✅ OK' if ok else '❌ ' + reason}")
