"""
================================================================
한투 KIS Open API - Exchange Layer
================================================================
Bybit 의 BybitExchange 와 동일 인터페이스 (드롭인 교체)
- 토큰 발급 / 갱신
- 잔고 조회
- 포지션 조회
- 캔들 (klines) 조회
- 시장가 주문 (체결 대기)
- 지정가 주문 (TP1)
- 주문 취소
- Stop loss (KIS 는 별도 stop order, 또는 수동 모니터링)

[중요 - KIS 해외선물 API endpoint]
- 모의투자 base: https://openapivts.koreainvestment.com:29443
- 실전 base:    https://openapi.koreainvestment.com:9443
- 인증: AppKey + AppSecret → access_token (24h)

[참고]
- 공식 샘플: github.com/koreainvestment/open-trading-api
- python-kis (Soju06) 는 해외선물 지원 약함 → REST 직접 호출

⚠️ KIS 정확한 tr_id / endpoint 는 KIS Developers 포털 docs 에서 확인 필수
   (이 파일의 endpoint / tr_id 는 일반적 추정값, 실제 호출 전 검증)
================================================================
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List

import requests
import pandas as pd

from config_kis import (
    KIS_DEMO_BASE_URL,
    KIS_LIVE_BASE_URL,
    READ_API_MAX_RETRIES,
    READ_API_RETRY_SLEEP_SECONDS,
)

from kis_assets import (
    ASSET_META,
    get_kis_symbol,
    get_kis_exchange,
    get_pt_value_usd,
    get_currency,
    DEFAULT_FX_TO_USD,
)


# ============================================================
# 토큰 캐시 (24h 유효)
# ============================================================
TOKEN_CACHE_FILE = Path("kis_token_cache.json")


class KisExchange:
    """KIS Open API wrapper (해외선물옵션)
    
    Bybit 의 BybitExchange 와 동일 인터페이스 제공:
        get_server_time, get_wallet_balance, get_positions,
        get_kline, get_last_price, place_market_order,
        wait_for_position_fill_info, set_stop_loss_only, ...
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,            # 8자리 (예: "00225351")
        product_code: str = "08",   # 해외선물옵션 = 08
        use_demo: bool = True,
        hts_id: Optional[str] = None,
    ):
        self.app_key = str(app_key).strip()
        self.app_secret = str(app_secret).strip()
        self.account_no = str(account_no).strip()
        self.product_code = str(product_code).strip()
        self.use_demo = bool(use_demo)
        self.hts_id = hts_id
        
        self.base_url = KIS_DEMO_BASE_URL if self.use_demo else KIS_LIVE_BASE_URL
        
        # 토큰 캐시
        self._access_token: Optional[str] = None
        self._token_expire_at: Optional[datetime] = None
        self._load_token_from_cache()

    # ============================================================
    # 토큰 관리
    # ============================================================
    def _load_token_from_cache(self) -> None:
        """디스크 캐시에서 토큰 로드 (서버 재시작 시 재발급 방지)"""
        if not TOKEN_CACHE_FILE.exists():
            return
        try:
            data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
            cache_key = self._token_cache_key()
            entry = data.get(cache_key)
            if not entry:
                return
            expire_at = datetime.fromisoformat(entry["expire_at"])
            if expire_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                self._access_token = entry["access_token"]
                self._token_expire_at = expire_at
        except Exception:
            pass

    def _save_token_to_cache(self) -> None:
        """토큰 캐시 저장"""
        try:
            data = {}
            if TOKEN_CACHE_FILE.exists():
                data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
            cache_key = self._token_cache_key()
            data[cache_key] = {
                "access_token": self._access_token,
                "expire_at": self._token_expire_at.isoformat() if self._token_expire_at else None,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            TOKEN_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[KIS] 토큰 캐시 저장 실패: {e}")

    def _token_cache_key(self) -> str:
        """토큰 캐시 키 = (mode + appkey 앞 8자리)"""
        mode = "demo" if self.use_demo else "live"
        return f"{mode}_{self.app_key[:8]}"

    def _ensure_token(self) -> str:
        """토큰 유효성 체크 + 필요시 갱신"""
        if self._access_token and self._token_expire_at:
            if self._token_expire_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                return self._access_token
        
        # 토큰 발급
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        try:
            resp = requests.post(url, json=body, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            # KIS 는 expire_in 초 단위 반환
            expire_seconds = int(data.get("expires_in", 86400))
            self._token_expire_at = datetime.now(timezone.utc) + timedelta(seconds=expire_seconds)
            self._save_token_to_cache()
            return self._access_token
        except Exception as e:
            raise RuntimeError(f"KIS 토큰 발급 실패: {e}")

    def _headers(self, tr_id: str, custtype: str = "P") -> Dict[str, str]:
        """REST 헤더 표준"""
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": custtype,
        }

    def _call_with_retry(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """재시도 wrapper"""
        last_error = None
        for attempt in range(1, READ_API_MAX_RETRIES + 1):
            try:
                resp = requests.request(method, url, timeout=15, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                if attempt >= READ_API_MAX_RETRIES:
                    raise
                time.sleep(READ_API_RETRY_SLEEP_SECONDS)
        raise last_error

    # ============================================================
    # 시간/잔고 조회
    # ============================================================
    def get_server_time(self) -> Dict[str, Any]:
        """서버 시각 (placeholder - KIS 별도 endpoint X, 토큰 검증으로 대체)"""
        try:
            self._ensure_token()
            return {
                "rt_cd": "0",
                "msg_cd": "OK",
                "msg1": "토큰 정상",
                "current_utc": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e)}

    def get_wallet_balance(self) -> Dict[str, Any]:
        """
        해외선물옵션 예수금현황 조회 (KIS 공식 docs 기준).
        
        - URL: /uapi/overseas-futureoption/v1/trading/inquire-deposit
        - TR_ID: OTFM1411R (실전 only — 모의투자 미지원)
        - Method: GET
        - Required: CANO, ACNT_PRDT_CD, CRCY_CD, INQR_DT
        
        CRCY_CD 값:
          TUS = TOT_USD (USD 환산 총액) ← 우리가 사용
          TKR = TOT_KRW (KRW 환산 총액)
          KRW/USD/EUR/HKD/CNY/JPY/VND
        """
        # 모의에서는 미지원 - 명확한 메시지 반환
        if self.use_demo:
            return {
                "rt_cd": "ERR",
                "msg_cd": "DEMO_UNSUPPORTED",
                "msg1": "해외선물옵션 예수금현황은 모의투자 미지원 (KIS 정책). settings.manual_balance_usd 사용",
                "output": {},
                "_demo_unsupported": True,
            }
        
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-deposit"
        tr_id = "OTFM1411R"
        params = {
            "CANO":         self.account_no,
            "ACNT_PRDT_CD": self.product_code,
            "CRCY_CD":      "TUS",  # USD 환산 총액
            "INQR_DT":      datetime.now().strftime("%Y%m%d"),
        }
        try:
            data = self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
            return data
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e), "output": {}}

    def get_balance_usd(self, fallback_manual_balance: float = 0.0) -> float:
        """
        USD 환산 총자산평가금액 추출.
        
        주요 필드:
          fm_tot_asst_evlu_amt  : 총자산평가금액 ⭐ (가장 의미있음)
          fm_dnca_rmnd          : 예수금잔액
          fm_ord_psbl_amt       : 주문가능금액
          fm_drwg_psbl_amt      : 출금가능금액
        
        Args:
            fallback_manual_balance: 모의 미지원 또는 API 실패 시 사용할 수동 입력 값
        """
        resp = self.get_wallet_balance()
        
        # 모의 미지원이거나 에러 → fallback
        if resp.get("_demo_unsupported") or resp.get("rt_cd") == "ERR":
            return float(fallback_manual_balance) if fallback_manual_balance > 0 else 0.0
        
        try:
            output = resp.get("output", {}) or {}
            # 우선순위: 총자산평가 > 예수금잔액 > 주문가능
            for key in ("fm_tot_asst_evlu_amt", "fm_dnca_rmnd", "fm_ord_psbl_amt"):
                val = output.get(key)
                if val:
                    try:
                        f = float(val)
                        if f > 0:
                            return f
                    except Exception:
                        pass
            # API 응답은 왔지만 0 인 경우 fallback 도 시도
            return float(fallback_manual_balance) if fallback_manual_balance > 0 else 0.0
        except Exception:
            return float(fallback_manual_balance) if fallback_manual_balance > 0 else 0.0

    # ============================================================
    # 포지션 조회 (해외선물옵션 미결제내역조회)
    # ============================================================
    def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        해외선물옵션 미결제내역조회(잔고) — 보유 포지션.
        
        - URL: /uapi/overseas-futureoption/v1/trading/inquire-unpd
        - TR_ID: OTFM1412R (실전 only — 모의투자 미지원)
        - Method: GET
        - Required: CANO, ACNT_PRDT_CD, FUOP_DVSN, CTX_AREA_FK100, CTX_AREA_NK100
        
        FUOP_DVSN: 00=전체 / 01=선물 / 02=옵션
        
        응답 (output 배열):
          ovrs_futr_fx_pdno: 종목번호 (예: "6AZ22", "NQH26")
          sll_buy_dvsn_cd:   매도매수구분 ("01"=매도, "02"=매수)
          fm_ustl_qty:       미결제수량
          fm_ccld_avg_pric:  체결평균가격 (entry price)
          fm_now_pric:       현재가격
          fm_evlu_pfls_amt:  평가손익금액
          fm_lqd_psbl_qty:   청산가능수량
          crcy_cd:           통화코드
        """
        if self.use_demo:
            return {
                "rt_cd": "ERR",
                "msg_cd": "DEMO_UNSUPPORTED",
                "msg1": "해외선물옵션 미결제내역조회는 모의투자 미지원",
                "output": [],
                "_demo_unsupported": True,
            }
        
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-unpd"
        tr_id = "OTFM1412R"
        params = {
            "CANO":             self.account_no,
            "ACNT_PRDT_CD":     self.product_code,
            "FUOP_DVSN":        "01",   # 01=선물 (인덱스 봇은 선물만)
            "CTX_AREA_FK100":   "",
            "CTX_AREA_NK100":   "",
        }
        try:
            data = self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
            return data
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e), "output": []}

    def get_position_by_symbol(self, symbol: str) -> Dict[str, Any]:
        """특정 자산 포지션 조회 — output 배열에서 ovrs_futr_fx_pdno 매칭"""
        all_pos = self.get_positions()
        if all_pos.get("rt_cd") != "0":
            return {"found": False, "raw": all_pos}
        
        kis_sym = get_kis_symbol(symbol)
        for item in all_pos.get("output", []):
            pdno = str(item.get("ovrs_futr_fx_pdno", "")).strip()
            # 종목번호는 월물 코드 (예: NQH26) 가 붙어서 단순 매칭 어려움
            # 우선 prefix 매칭 (NQ → NQH26, NQM26 등)
            if pdno.startswith(kis_sym):
                qty = float(item.get("fm_ustl_qty", 0) or 0)
                if qty > 0:
                    side_code = str(item.get("sll_buy_dvsn_cd", ""))
                    return {
                        "found": True,
                        "symbol": symbol,
                        "kis_pdno": pdno,
                        "side": "Buy" if side_code == "02" else "Sell",
                        "qty": qty,
                        "avg_price": float(item.get("fm_ccld_avg_pric", 0) or 0),
                        "now_price": float(item.get("fm_now_pric", 0) or 0),
                        "pnl": float(item.get("fm_evlu_pfls_amt", 0) or 0),
                        "raw": item,
                    }
        return {"found": False, "raw": all_pos}

    # ============================================================
    # 캔들 (klines) 조회
    # ============================================================
    def get_kline(
        self,
        symbol: str,
        interval: str,    # "120" = 2h, "60" = 1h
        limit: int = 200,
    ) -> Dict[str, Any]:
        """
        해외선물 분봉/시간봉 차트 조회.
        TR_ID: 'HHDFC55020100' (해외선물 시간별체결가)
        Endpoint: /uapi/overseas-futureoption/v1/quotations/inquire-time-fuopchartprice
        ⚠️ 정확한 endpoint/tr_id 는 KIS docs 확인
        
        Args:
            symbol: 백테 키 (NQ/ES/YM 등)
            interval: "60"(1h), "120"(2h)
            limit: 캔들 개수
        """
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/quotations/inquire-time-fuopchartprice"
        tr_id = "HHDFC55020100"
        kis_sym = get_kis_symbol(symbol)
        kis_exch = get_kis_exchange(symbol)
        
        params = {
            "EXCD":              kis_exch,
            "SRS_CD":            kis_sym,
            "EXCH_CD":           kis_exch,
            "FID_PERIOD_DIV_CODE": "M",   # M=분봉
            "FID_INPUT_HOUR_1":  interval,
            "FID_PW_DATA_INCU_YN": "N",
        }
        try:
            data = self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
            return data
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e), "output2": []}

    def get_recent_klines_df(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> pd.DataFrame:
        """캔들 → DataFrame 변환 (Bybit 의 get_recent_klines_df 와 동일 인터페이스)"""
        resp = self.get_kline(symbol=symbol, interval=interval, limit=limit)
        
        # KIS 응답 형식: output2 에 list of dict
        items = resp.get("output2", []) or []
        if not items:
            raise ValueError(f"No kline data returned for {symbol} {interval}: {resp.get('msg1', '')}")
        
        rows = []
        for item in items:
            # KIS 응답 필드명 추정 (실제 응답 받아보고 보정)
            # stck_bsop_date(YYYYMMDD) + stck_cntg_hour(HHMMSS) → timestamp
            # 또는 dt + tm 
            try:
                date_str = item.get("stck_bsop_date") or item.get("xymd") or item.get("date")
                time_str = item.get("stck_cntg_hour") or item.get("xhms") or item.get("time", "000000")
                ts_str = f"{date_str}{time_str}"
                ts = pd.to_datetime(ts_str, format="%Y%m%d%H%M%S", utc=True)
                
                rows.append({
                    "timestamp": ts,
                    "open":   float(item.get("open") or item.get("stck_oprc") or 0),
                    "high":   float(item.get("high") or item.get("stck_hgpr") or 0),
                    "low":    float(item.get("low")  or item.get("stck_lwpr") or 0),
                    "close":  float(item.get("close") or item.get("stck_prpr") or 0),
                    "volume": float(item.get("volume") or item.get("cntg_vol") or 0),
                })
            except Exception:
                continue
        
        if not rows:
            raise ValueError(f"All kline rows failed to parse for {symbol}")
        
        df = pd.DataFrame(rows).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        return df

    def get_last_price(self, symbol: str) -> float:
        """현재가 조회 - 호가 endpoint 또는 시세 endpoint 호출"""
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/quotations/inquire-price"
        tr_id = "HHDFC55010100"
        kis_sym = get_kis_symbol(symbol)
        kis_exch = get_kis_exchange(symbol)
        
        params = {
            "EXCD":    kis_exch,
            "SRS_CD":  kis_sym,
            "EXCH_CD": kis_exch,
        }
        try:
            data = self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
            output = data.get("output", {}) or {}
            # 가능한 필드: last, stck_prpr, prpr
            for key in ("last", "stck_prpr", "prpr", "trade_price"):
                val = output.get(key)
                if val:
                    return float(val)
            return 0.0
        except Exception as e:
            print(f"[KIS] get_last_price({symbol}) 실패: {e}")
            return 0.0

    # ============================================================
    # 주문
    # ============================================================
    def place_market_order(
        self,
        symbol: str,
        side: str,          # "Buy" / "Sell" (Bybit 호환)
        qty: int,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """
        해외선물 시장가 주문.
        TR_ID: 모의 'VTTO1101U' (해외선물 매수/매도)
              실전 'OTFM3001U'
        Endpoint: /uapi/overseas-futureoption/v1/trading/order
        ⚠️ 정확한 tr_id 는 KIS docs 확인
        """
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/order"
        tr_id = "VTTO1101U" if self.use_demo else "OTFM3001U"
        kis_sym = get_kis_symbol(symbol)
        kis_exch = get_kis_exchange(symbol)
        
        # KIS 의 매수/매도 코드: 02=매수, 01=매도 (해외선물)
        sll_buy_code = "02" if str(side) == "Buy" else "01"
        
        body = {
            "CANO":          self.account_no,
            "ACNT_PRDT_CD":  self.product_code,
            "OVRS_FUTR_FX_PDNO": kis_sym,
            "SLL_BUY_DVSN_CD": sll_buy_code,
            "FM_LQD_LMT_DVSN_CD": "1",   # 1=신규, 2=청산
            "FM_LMT_ORD_PRIC":  "0",     # 시장가 = 0
            "FM_MKPR_CVSN_YN":  "Y",     # 시장가 변환 여부
            "FM_ORD_QTY":       str(int(qty)),
            "FM_ORD_DVSN_CD":   "01",    # 01=시장가, 02=지정가
            "FM_PDGR_CD":       "01",
            "ECIS_RSVN_ORD_YN": "N",
        }
        try:
            data = self._call_with_retry(
                "POST", url, headers=self._headers(tr_id), json=body,
            )
            return {"response": data, "raw": data}
        except Exception as e:
            return {"response": {"rt_cd": "ERR", "msg1": str(e)}, "raw": {}}

    def place_market_order_and_wait(
        self,
        symbol: str,
        side: str,
        qty: int,
        reduce_only: bool = False,
        retries: int = 10,
        sleep_seconds: float = 0.7,
    ) -> Dict[str, Any]:
        """시장가 주문 + 체결가 polling (Bybit 호환)"""
        order_resp = self.place_market_order(symbol, side, qty, reduce_only)
        order_id = self._extract_order_id(order_resp.get("response", {}))
        
        avg_price = None
        if order_id:
            for _ in range(retries):
                try:
                    status = self.get_order_fill_status(symbol, order_id)
                    if status.get("is_filled") and status.get("avg_price", 0) > 0:
                        avg_price = float(status["avg_price"])
                        return {
                            "response": order_resp.get("response", {}),
                            "avg_price": avg_price,
                            "raw": status.get("raw", {}),
                        }
                except Exception:
                    pass
                time.sleep(sleep_seconds)
        
        return {
            "response": order_resp.get("response", {}),
            "avg_price": avg_price,
            "raw": {},
        }

    def _extract_order_id(self, response: Dict[str, Any]) -> str:
        """주문 응답에서 orderId 추출"""
        output = response.get("output", {}) or {}
        # 가능한 필드: ODNO (주문번호), KRX_FWDG_ORD_ORGNO, ORD_GNO_BRNO 등
        for key in ("ODNO", "odno", "ord_no", "order_id"):
            val = output.get(key)
            if val:
                return str(val)
        return ""

    def get_order_fill_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        주문 체결 상태 조회.
        TR_ID: 'OTFM3122R' / 'VTOF3122R' (모의)
        Endpoint: /uapi/overseas-futureoption/v1/trading/inquire-ccnl
        """
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-ccnl"
        tr_id = "VTOF3122R" if self.use_demo else "OTFM3122R"
        params = {
            "CANO":          self.account_no,
            "ACNT_PRDT_CD":  self.product_code,
            "ORD_DT":        datetime.now().strftime("%Y%m%d"),
            "ODNO":          str(order_id),
            "INQR_DVSN_CD":  "00",
            "INQR_DVSN_3":   "00",
        }
        try:
            data = self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
            output_list = data.get("output1", []) or []
            if output_list:
                raw = output_list[0]
                return {
                    "found":         True,
                    "is_filled":     str(raw.get("ORD_STAT_CD", "")) == "31",  # 31=체결
                    "cum_exec_qty":  float(raw.get("CCLD_QTY", 0) or 0),
                    "leaves_qty":    float(raw.get("RMN_QTY", 0) or 0),
                    "avg_price":     float(raw.get("CCLD_PRC", 0) or raw.get("ORD_PRIC", 0) or 0),
                    "status":        str(raw.get("ORD_STAT_CD", "")),
                    "raw": raw,
                }
            return {"found": False, "is_filled": False, "cum_exec_qty": 0, "leaves_qty": 0, "avg_price": 0, "status": "", "raw": {}}
        except Exception as e:
            return {"found": False, "is_filled": False, "cum_exec_qty": 0, "leaves_qty": 0, "avg_price": 0, "status": "ERR", "raw": {"error": str(e)}}

    def place_reduce_only_limit_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        """청산 지정가 주문 (TP1 용)"""
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/order"
        tr_id = "VTTO1101U" if self.use_demo else "OTFM3001U"
        kis_sym = get_kis_symbol(symbol)
        sll_buy_code = "02" if str(side) == "Buy" else "01"
        
        body = {
            "CANO":          self.account_no,
            "ACNT_PRDT_CD":  self.product_code,
            "OVRS_FUTR_FX_PDNO": kis_sym,
            "SLL_BUY_DVSN_CD": sll_buy_code,
            "FM_LQD_LMT_DVSN_CD": "2",   # 2=청산
            "FM_LMT_ORD_PRIC":  str(price),
            "FM_MKPR_CVSN_YN":  "N",
            "FM_ORD_QTY":       str(int(qty)),
            "FM_ORD_DVSN_CD":   "02",    # 02=지정가
            "FM_PDGR_CD":       "01",
            "ECIS_RSVN_ORD_YN": "N",
        }
        try:
            data = self._call_with_retry(
                "POST", url, headers=self._headers(tr_id), json=body,
            )
            return data
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e)}

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """주문 취소"""
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/order-rvsecncl"
        tr_id = "VTTO1103U" if self.use_demo else "OTFM3003U"
        body = {
            "CANO":          self.account_no,
            "ACNT_PRDT_CD":  self.product_code,
            "ODNO":          str(order_id),
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "FM_ORD_QTY":    "0",
            "FM_LMT_ORD_PRIC":"0",
            "FM_MKPR_CVSN_YN":"N",
            "RMN_QTY_YN":    "Y",
        }
        try:
            return self._call_with_retry(
                "POST", url, headers=self._headers(tr_id), json=body,
            )
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e)}

    def get_open_orders(self, symbol: Optional[str] = None, order_id: Optional[str] = None) -> Dict[str, Any]:
        """미체결 주문 조회"""
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-unccnl"
        tr_id = "VTOF3018R" if self.use_demo else "OTFM3018R"
        params = {
            "CANO":          self.account_no,
            "ACNT_PRDT_CD":  self.product_code,
            "OVRS_FUTR_FX_PDNO": get_kis_symbol(symbol) if symbol else "",
            "INQR_DVSN_3":   "00",
        }
        try:
            return self._call_with_retry(
                "GET", url, headers=self._headers(tr_id), params=params,
            )
        except Exception as e:
            return {"rt_cd": "ERR", "msg1": str(e), "output": []}

    # ============================================================
    # Stop loss (KIS 는 별도 stop order 지원 - 또는 수동 모니터링)
    # ============================================================
    def set_stop_loss_only(
        self,
        symbol: str,
        stop_loss: float,
        side: str,
        qty: int,
    ) -> Dict[str, Any]:
        """
        Stop loss 주문 등록.
        KIS 해외선물에 stop order 지원하는 endpoint 가 있으면 사용,
        없으면 main loop 에서 수동 모니터링 후 시장가 청산.
        
        ⚠️ 일단 placeholder. 실제 운용 시:
           1) KIS docs 에서 stop order endpoint 확인
           2) 없으면 main_idx.py 에서 가격 모니터링 → 시장가 청산
        """
        # Placeholder: 실제 KIS API 확인 후 구현
        # 현재는 manage_open_positions 에서 수동 모니터링하는 방식
        return {
            "rt_cd": "0",
            "msg1": "stop loss는 main_idx.py 에서 수동 모니터링 (KIS stop order 미구현)",
            "stop_loss": stop_loss,
            "managed_in_main": True,
        }

    def close_position_market(self, symbol: str, side: str, qty: int) -> Dict[str, Any]:
        """포지션 시장가 청산"""
        close_side = "Sell" if side == "Buy" else "Buy"
        return self.place_market_order_and_wait(
            symbol=symbol, side=close_side, qty=qty, reduce_only=True,
        )

    def wait_for_position_fill_info(
        self,
        symbol: str,
        expected_side: str,
        retries: int = 10,
        sleep_seconds: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        """
        포지션 체결 후 entry price polling.
        
        KIS 미결제내역 응답 필드 (모두 소문자):
          ovrs_futr_fx_pdno: 종목번호 (예: "NQH26")
          sll_buy_dvsn_cd:   "01"=매도, "02"=매수
          fm_ustl_qty:       미결제수량
          fm_ccld_avg_pric:  체결평균가격 (entry price)
        """
        kis_sym = get_kis_symbol(symbol)
        
        for _ in range(retries):
            resp = self.get_positions(symbol=symbol)
            
            # 모의 미지원 시 즉시 종료 (polling 무의미)
            if resp.get("_demo_unsupported"):
                return None
            
            output = resp.get("output", []) or []
            if isinstance(output, list):
                for item in output:
                    pdno = str(item.get("ovrs_futr_fx_pdno", "")).strip()
                    # 종목번호 prefix 매칭 (NQ → NQH26 등 월물 코드)
                    if pdno.startswith(kis_sym):
                        side_code = str(item.get("sll_buy_dvsn_cd", ""))
                        item_side = "Buy" if side_code == "02" else "Sell"
                        item_qty = float(item.get("fm_ustl_qty", 0) or 0)
                        if item_qty <= 0:
                            continue
                        if expected_side and item_side != expected_side:
                            continue
                        avg_price = float(item.get("fm_ccld_avg_pric", 0) or 0)
                        return {
                            "symbol": symbol,
                            "kis_pdno": pdno,
                            "side": item_side,
                            "qty": item_qty,
                            "avg_price": avg_price,
                            "raw": item,
                            "response": resp,
                        }
            time.sleep(sleep_seconds)
        return None


# ============================================================
# 자기 검증
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("KisExchange 인터페이스 검증 (실제 API 호출 X)")
    print("=" * 80)
    
    # mock 인스턴스 생성 (실제 키 없이)
    ex = KisExchange(
        app_key="MOCK_APP_KEY_12345",
        app_secret="MOCK_APP_SECRET",
        account_no="00225351",
        product_code="08",
        use_demo=True,
    )
    
    print(f"base_url: {ex.base_url}")
    print(f"account: {ex.account_no}-{ex.product_code}")
    print(f"use_demo: {ex.use_demo}")
    
    # 메서드 시그니처 확인
    methods = [
        "get_server_time",
        "get_wallet_balance",
        "get_balance_usd",
        "get_positions",
        "get_position_by_symbol",
        "get_kline",
        "get_recent_klines_df",
        "get_last_price",
        "place_market_order",
        "place_market_order_and_wait",
        "get_order_fill_status",
        "place_reduce_only_limit_order",
        "cancel_order",
        "get_open_orders",
        "set_stop_loss_only",
        "close_position_market",
        "wait_for_position_fill_info",
    ]
    print(f"\n구현 메서드: {len(methods)}")
    for m in methods:
        has = hasattr(ex, m)
        print(f"  {'✓' if has else '✗'} {m}")
    
    print()
    print("⚠️ 실제 API 호출 검증은 KIS AppKey 발급 후 진행")
    print("⚠️ tr_id / endpoint 는 KIS Developers 포털 docs 확인 필수")
