from __future__ import annotations
"""
라이브 트레이딩 설정 — 확정 baseline(v4 42규칙 + 만기컷 + 24·25제거 + 전역 risk×1.2, 15m체결).
★기존 live의 Stage 4K(룩어헤드)와 무관. smc_stage4d(룩어헤드 free) 엔진 기반.
★소액 라이브 테스트용 안전장치 다수 — 실계좌 투입 전 반드시 DRY_RUN·DEMO로 검증.
"""
import os

# ── 거래소 ──
CATEGORY = "linear"
USE_TESTNET = False
USE_DEMO = True                 # ★기본 demo. 실계좌는 False (신중히)
READ_API_MAX_RETRIES = 3
READ_API_RETRY_SLEEP_SECONDS = 0.8

# ── 캔들 ──
H4_INTERVAL = "240"; H1_INTERVAL = "60"
H4_LIMIT = 2000; H1_LIMIT = 1200
BTC_SYMBOL = "BTCUSDT"          # BTC 레짐(btc_zone) 계산용

# ── 대상 심볼 (백테스트 9코인) ──
SYMBOLS = ["ADAUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT"]

# ── 전략 baseline 파라미터 (확정) ──
FEE_RATE = 0.00055
MAX_NOTIONAL_MULT = 3.0
GLOBAL_RISK_MULT = 1.2          # 전역 g
EXPIRY_BLOCK_HOURS = 48         # 월간만기 ≤48h 진입 차단
KILLER_CAP_PCT = 3.5            # killer 2조합 캡
# 확정 게이트/엔진 env (백테스트와 동일)
ENGINE_ENV = {"OB_MODE": "engulf", "DISP_ATR_MULT": "1.3", "USE_H1_REFINE": "1", "HONEST_STAGE": "5", "MIN_SCORE": "7.5"}
RULES_JSON = "setups_btc_triple_a3v4.json"
COMBO_RISK_TABLE = "combo_risk_table.json"

# ── ★★ 안전장치 (소액 라이브 테스트) ★★ ──
DRY_RUN = True                  # ★True면 주문 안 냄(신호·사이징만 로그). 실주문은 False로 명시전환.
TEST_MODE = True                # ★True면 아래 소액 캡 강제
TEST_FIXED_NOTIONAL_USDT = 12.0 # ★테스트 1포지션 명목가 상한(USDT). risk 계산보다 이게 우선.
HARD_MAX_RISK_PCT = 2.0         # ★조합 risk가 이보다 크면 이 값으로 clamp (120% 소표본 방지)
MAX_OPEN_POSITIONS = 2          # 동시 최대 포지션
MAX_DAILY_ORDERS = 20           # 하루 최대 진입 수
MIN_BALANCE_USDT = 30.0         # 이 잔고 미만이면 신규진입 중단
KILL_SWITCH_FILE = "KILL"       # 이 파일 존재하면 즉시 신규진입 중단
LOOP_SLEEP_SECONDS = 30         # 루프 주기(H4 마감 감지)
LOG_FILE = "live_v4.log"

# ── API 키 (환경변수에서만 — 하드코딩 금지) ──
def resolve_api_credentials():
    if USE_DEMO:
        k = os.getenv("BYBIT_DEMO_API_KEY", "") or os.getenv("BYBIT_API_KEY", "")
        s = os.getenv("BYBIT_DEMO_API_SECRET", "") or os.getenv("BYBIT_API_SECRET", "")
    else:
        k = os.getenv("BYBIT_LIVE_API_KEY", "") or os.getenv("BYBIT_API_KEY", "")
        s = os.getenv("BYBIT_LIVE_API_SECRET", "") or os.getenv("BYBIT_API_SECRET", "")
    return k.strip(), s.strip()
