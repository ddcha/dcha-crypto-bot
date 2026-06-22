"""
================================================================
한투 KIS 인덱스 자동매매 - 자산 메타데이터 (v29.5 baseline 9자산)
================================================================
v29.5 baseline 의 9자산 metadata 정의:
  - 한투 종목코드 (KIS API 주문 시 사용)
  - 거래소 코드 (한투 KIS 의 EXCH_CD)
  - Multiplier (1pt 변동 시 통화 손익)
  - Tick size (가격 호가 단위)
  - 통화 (USD/JPY/GBP/HKD/TWD)
  - 거래시간 (UTC 기준 — market_hours.py 와 연동)

[자산 키 = v29.5 백테 키 그대로 사용]
================================================================
"""
from __future__ import annotations
from typing import Dict, List, Optional


# ============================================================
# 9자산 메타데이터 (v29.5 baseline)
# ============================================================
# 주의:
#  - kis_symbol: 한투 KIS API 주문 시 사용하는 ovrs_excg_cd:종목코드
#    (둠챠가 한투 KIS 문서 / OpenAPI 받으면 정확한 형식 확인 필요. 일단 추정값)
#  - 정확한 한투 종목코드/거래소 코드는 KIS Developers AppKey 발급 후
#    실제 API 시세 조회로 검증
# ============================================================
ASSET_META: Dict[str, Dict] = {
    # ──────────────────────────────────────────────────
    # 🇺🇸 US 4 - CME (미국 시카고 상품거래소)
    # ──────────────────────────────────────────────────
    "NQ": {
        "name":        "E-mini Nasdaq 100",
        "kis_symbol":  "NQ",          # 한투 KIS 종목코드
        "kis_exchange":"CME",         # 한투 거래소 코드
        "multiplier":  20.0,          # 1pt = $20
        "tick":        0.25,          # 호가 단위
        "currency":    "USD",
        "market":      "CME",
        "tradable":    True,          # 한투 매매 가능
    },
    "ES": {
        "name":        "E-mini S&P 500",
        "kis_symbol":  "ES",
        "kis_exchange":"CME",
        "multiplier":  50.0,          # 1pt = $50
        "tick":        0.25,
        "currency":    "USD",
        "market":      "CME",
        "tradable":    True,
    },
    "YM": {
        "name":        "E-mini Dow",
        "kis_symbol":  "YM",
        "kis_exchange":"CBOT",
        "multiplier":  5.0,           # 1pt = $5
        "tick":        1.0,
        "currency":    "USD",
        "market":      "CBOT",
        "tradable":    True,
    },
    "RTY": {
        "name":        "E-mini Russell 2000",
        "kis_symbol":  "RTY",
        "kis_exchange":"CME",
        "multiplier":  50.0,          # 1pt = $50
        "tick":        0.10,
        "currency":    "USD",
        "market":      "CME",
        "tradable":    True,
    },

    # ──────────────────────────────────────────────────
    # 🇯🇵 JP 2 - CME / OSE
    # ──────────────────────────────────────────────────
    "NKD": {
        "name":        "Nikkei 225 ($)",
        "kis_symbol":  "NKD",
        "kis_exchange":"CME",
        "multiplier":  5.0,           # 1pt = $5 (USD 정산)
        "tick":        5.0,
        "currency":    "USD",
        "market":      "CME",
        "tradable":    True,
    },
    "TPX": {
        "name":        "TOPIX",
        "kis_symbol":  "TPX",         # 한투 OSE TPX
        "kis_exchange":"OSE",
        "multiplier":  10000.0,       # 1pt = ¥10,000
        "tick":        0.5,
        "currency":    "JPY",
        "market":      "OSE",
        "tradable":    True,
    },

    # ──────────────────────────────────────────────────
    # 🇬🇧 GB 1 - ICE Europe
    # ──────────────────────────────────────────────────
    "FTSE": {
        "name":        "FTSE 100",
        "kis_symbol":  "FTS",         # 한투 ICE 의 FTS
        "kis_exchange":"ICE_EU",
        "multiplier":  10.0,          # 1pt = £10
        "tick":        0.5,
        "currency":    "GBP",
        "market":      "ICE_EU",
        "tradable":    True,
    },

    # ──────────────────────────────────────────────────
    # 🇭🇰 HK 1 - HKEx
    # ──────────────────────────────────────────────────
    "HSI": {
        "name":        "Hang Seng",
        "kis_symbol":  "HSI",
        "kis_exchange":"HKEX",
        "multiplier":  50.0,          # 1pt = HK$50
        "tick":        1.0,
        "currency":    "HKD",
        "market":      "HKEX",
        "tradable":    True,
    },

    # ──────────────────────────────────────────────────
    # 🇹🇼 TW 1 - TAIFEX
    # ──────────────────────────────────────────────────
    # ⚠️ TWII (대만) 한투 매매 가능 여부 미확정 - 둠챠 한투 화면에서 검증 필요
    "TWII": {
        "name":        "TAIEX (TXF)",
        "kis_symbol":  "TXF",         # 한투 TAIFEX 코드 (확인 필요)
        "kis_exchange":"TAIFEX",
        "multiplier":  200.0,         # 1pt = NT$200
        "tick":        1.0,
        "currency":    "TWD",
        "market":      "TAIFEX",
        "tradable":    True,          # ⚠️ 한투 미확인 - 일단 활성화
    },
}


# ============================================================
# 환율 (USD 기준) — 실시간 갱신 필요. 일단 default 값 (2026-04 기준)
# ============================================================
# 실전에서는 KIS API 또는 별도 환율 API 로 매일 갱신 권장
# 백테 risk 계산 시 USD 환산을 위해 사용
DEFAULT_FX_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "JPY": 1.0 / 152.0,    # 1 JPY ≈ $0.00658
    "GBP": 1.27,           # 1 GBP ≈ $1.27
    "HKD": 0.128,          # 1 HKD ≈ $0.128
    "TWD": 0.030,          # 1 TWD ≈ $0.030
}


# ============================================================
# Helper 함수
# ============================================================
def get_asset_meta(symbol: str) -> Optional[Dict]:
    """자산 메타데이터 조회"""
    return ASSET_META.get(symbol)


def get_multiplier(symbol: str) -> float:
    """multiplier (1pt 변동 시 통화 손익)"""
    meta = ASSET_META.get(symbol, {})
    return float(meta.get("multiplier", 1.0))


def get_tick(symbol: str) -> float:
    """tick size (가격 호가 단위)"""
    meta = ASSET_META.get(symbol, {})
    return float(meta.get("tick", 0.01))


def get_currency(symbol: str) -> str:
    """통화 (USD/JPY/GBP/HKD/TWD)"""
    meta = ASSET_META.get(symbol, {})
    return str(meta.get("currency", "USD"))


def get_pt_value_usd(symbol: str, fx_table: Optional[Dict[str, float]] = None) -> float:
    """1pt 변동 시 USD 환산 손익"""
    fx = fx_table or DEFAULT_FX_TO_USD
    meta = ASSET_META.get(symbol)
    if not meta:
        return 1.0
    mult = float(meta.get("multiplier", 1.0))
    cur = str(meta.get("currency", "USD"))
    fx_rate = float(fx.get(cur, 1.0))
    return mult * fx_rate


def get_kis_symbol(symbol: str) -> str:
    """한투 KIS 종목코드"""
    meta = ASSET_META.get(symbol, {})
    return str(meta.get("kis_symbol", symbol))


def get_kis_exchange(symbol: str) -> str:
    """한투 거래소 코드"""
    meta = ASSET_META.get(symbol, {})
    return str(meta.get("kis_exchange", "CME"))


def round_to_tick(price: float, symbol: str) -> float:
    """가격을 tick size 단위로 반올림"""
    tick = get_tick(symbol)
    if tick <= 0:
        return float(price)
    return round(round(price / tick) * tick, 8)


def get_tradable_assets() -> List[str]:
    """매매 가능한 자산 키 목록"""
    return [s for s, m in ASSET_META.items() if m.get("tradable", False)]


def is_tradable(symbol: str) -> bool:
    """매매 가능 여부"""
    meta = ASSET_META.get(symbol, {})
    return bool(meta.get("tradable", False))


# ============================================================
# 자기 검증 (스크립트 직접 실행 시)
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("v29.5 baseline 9자산 메타데이터")
    print("=" * 80)
    print(f"{'sym':<6}{'name':<24}{'kis_sym':<8}{'exch':<8}{'mult':>10}{'tick':>8}{'cur':>5}{'pt_usd':>10}")
    print("-" * 80)
    for sym in ASSET_META:
        meta = ASSET_META[sym]
        pt_usd = get_pt_value_usd(sym)
        print(f"{sym:<6}{meta['name']:<24}{meta['kis_symbol']:<8}{meta['kis_exchange']:<8}"
              f"{meta['multiplier']:>10,.1f}{meta['tick']:>8}{meta['currency']:>5}"
              f"{pt_usd:>10.2f}")
    print()
    print(f"매매 가능 자산: {get_tradable_assets()}")
    print(f"총 자산 수: {len(ASSET_META)}")
