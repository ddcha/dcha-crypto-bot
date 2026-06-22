"""
================================================================
Tradingview 데이터 일괄 다운로드 스크립트 (v3 - 10000 캔들)
================================================================
- 한 번 실행해서 11개 자산 1H csv 저장
- 이후 v29.3 백테는 csv 만 읽음 → yfinance 의존 X
- 다운로드 시간: 자산당 약 10~20초 (총 약 3~5분)
- 저장 위치: ./tv_data/

[v2 → v3 변경:]
  - N_BARS 5500 → 10000 (둠챠가 5500 다 차있는 거 확인)
  - 받아지는 만큼만 받음 (실제 limit 자산별 다를 수 있음)

[v1 → v2 변경 (둠챠 지시):]
  - KS (KOSPI200) 제거
  - FTSE 100 (Z1! @ ICEEUR) 추가

설치:
  pip install https://github.com/rongardF/tvdatafeed/archive/refs/heads/main.zip
  
실행:
  python download_tv_data_v3.py
================================================================
"""

import time
from pathlib import Path

try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    print("❌ tvDatafeed 가 설치되지 않았습니다.")
    print("   설치: pip install tvDatafeed")
    print("   또는: pip install --upgrade --no-cache-dir git+https://github.com/rongardF/tvdatafeed.git")
    raise SystemExit(1)

import pandas as pd

# ============================================================
# 설정
# ============================================================
DATA_DIR = Path("./tv_data")
DATA_DIR.mkdir(exist_ok=True)

# 자산 매핑: 백테 키 → (TV 심볼, exchange)
# v2: 11자산 (KS 제거, FTSE 100 추가)
ASSETS = {
    # 🇺🇸 US 미국 4 (CME / CBOT)
    'NQ':    ('NQ1!',    'CME_MINI'),    # E-mini Nasdaq 100
    'ES':    ('ES1!',    'CME_MINI'),    # E-mini S&P 500
    'YM':    ('YM1!',    'CBOT_MINI'),   # E-mini Dow
    'RTY':   ('RTY1!',   'CME_MINI'),    # E-mini Russell 2000
    # 🇯🇵 JP 일본 1 (CME 닛케이 달러)
    'NKD':   ('NKD1!',   'CME'),         # Nikkei 225 (Dollar)
    # 🇩🇪 EU 유럽 3 (Eurex + ICE)
    'FDAX':  ('FDAX1!',  'EUREX'),       # DAX 선물
    'FESX':  ('FESX1!',  'EUREX'),       # Euro Stoxx 50
    'FTSE':  ('Z1!',     'ICEEUR'),      # ⭐ 신규: FTSE 100 (영국)
    # 🇭🇰 HK 홍콩 1
    'HSI':   ('HSI1!',   'HKEX'),        # Hang Seng Index
    # 🇹🇼 TW 대만 1
    'TWII':  ('TXF1!',   'TAIFEX'),      # 대만 가권 선물
    # 🇦🇺 AU 호주 1
    'AXJO':  ('AP1!',    'ASX'),         # SPI 200 (S&P/ASX 200)
}

INTERVAL = Interval.in_1_hour
N_BARS = 10000         # tvDatafeed 한계 테스트 (실제 한계는 ~10000~15000 추정)
                       # CME 자산 약 2년, EU 약 3년, HK/AU 약 6-8년 가능
RETRY = 3
SLEEP_BETWEEN = 2      # 초

# (옵션) Tradingview 로그인 — 익명으로 안 되면 사용
# 일부 자산 (특히 FTSE/HSI/TWII) 은 로그인 없이는 데이터 제한 가능
TV_USERNAME = None     # 'your_username'
TV_PASSWORD = None     # 'your_password'


# ============================================================
# 다운로드 함수
# ============================================================
def download_one(tv, key, symbol, exchange):
    """단일 자산 다운로드 + csv 저장"""
    for attempt in range(RETRY):
        try:
            print(f"  [{key:<5}] {exchange}:{symbol:<10} 다운로드 중... (try {attempt+1}/{RETRY})")
            df = tv.get_hist(
                symbol=symbol, exchange=exchange,
                interval=INTERVAL, n_bars=N_BARS
            )
            if df is None or len(df) == 0:
                raise ValueError("빈 데이터 반환됨")

            # 컬럼 정리: tvDatafeed 결과 컬럼 = ['symbol','open','high','low','close','volume']
            if 'symbol' in df.columns:
                df = df.drop(columns=['symbol'])

            # yfinance 와 호환되는 컬럼명으로 변환 (대문자 첫글자)
            df.columns = [c.capitalize() for c in df.columns]
            # 결과: ['Open','High','Low','Close','Volume']

            df.index.name = 'Datetime'

            # CSV 저장
            out_path = DATA_DIR / f"{key}_1h.csv"
            df.to_csv(out_path)

            print(f"    ✓ {len(df):>5} 캔들  ({df.index[0]} ~ {df.index[-1]})  저장: {out_path}")
            return True, len(df)

        except Exception as e:
            print(f"    ✗ 실패 ({attempt+1}/{RETRY}): {e}")
            if attempt < RETRY - 1:
                time.sleep(5)
    return False, 0


# ============================================================
# 메인
# ============================================================
def main():
    print("=" * 70)
    print("Tradingview 데이터 일괄 다운로드 v2")
    print(f"  자산 수: {len(ASSETS)}")
    print(f"  Interval: 1H")
    print(f"  N_BARS: {N_BARS} (약 730일 분량 — 거래시간만 카운트)")
    print(f"  저장 경로: {DATA_DIR.absolute()}")
    print(f"  변경: KS 제거, FTSE 100 (Z1!) 추가")
    print("=" * 70)

    # TvDatafeed 초기화
    print("\n[Tradingview 초기화 중...]")
    if TV_USERNAME and TV_PASSWORD:
        tv = TvDatafeed(username=TV_USERNAME, password=TV_PASSWORD)
        print("  로그인 모드")
    else:
        tv = TvDatafeed()
        print("  익명 모드 (FTSE/HSI/TWII 는 데이터 부족 가능)")
        print("  → 부족하면 위 TV_USERNAME/TV_PASSWORD 입력 후 재실행")

    success, fail = [], []
    counts = {}
    for i, (key, (symbol, exchange)) in enumerate(ASSETS.items(), 1):
        print(f"\n[{i}/{len(ASSETS)}] {key}")
        ok, n = download_one(tv, key, symbol, exchange)
        if ok:
            success.append(key)
            counts[key] = n
        else:
            fail.append(key)
        if i < len(ASSETS):
            time.sleep(SLEEP_BETWEEN)

    # 결과 요약
    print("\n" + "=" * 70)
    print(f"[결과] 성공: {len(success)}/{len(ASSETS)}  실패: {len(fail)}")
    print(f"  성공: {success}")
    if fail:
        print(f"  실패: {fail}")
        print()
        print("  실패 시 다음 사항 확인:")
        print("  1) 인터넷 연결")
        print("  2) Tradingview 로그인 — 위 TV_USERNAME/TV_PASSWORD 입력 후 재실행")
        print("  3) TV 심볼/exchange 정확성 — TV 웹에서 직접 검색해서 확인")
        print("     예시 대안:")
        print("       FTSE 100:    UKX (인덱스, FOREXCOM:UK100)")
        print("       ASX SPI 200: SPI=F, AS51 (인덱스)")
        print("       TWII:        TWII (TAIFEX:TX1!)")
        print("       HSI:         HSI (HKEX:HSI1!) 또는 인덱스 (HSIDIST:HSI)")
    print("=" * 70)

    # 검증: 모든 csv 파일 존재 + 행수 출력
    print("\n[저장 파일 검증]")
    print(f"{'key':<6} {'rows':>6} {'기간':<55} {'파일'}")
    print("-" * 90)
    for key in ASSETS:
        path = DATA_DIR / f"{key}_1h.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0)
            t_start = str(df.index[0])[:19]
            t_end   = str(df.index[-1])[:19]
            print(f"  {key:<5} {len(df):>5}  ({t_start} ~ {t_end})  {path.name}")
        else:
            print(f"  {key:<5}    --   ❌ 없음")

    # 자산별 권장 보완 (실패 시)
    if 'FTSE' in fail:
        print("\n  ⚠ FTSE 100 실패 시 대안 심볼:")
        print("     - ('Z1!', 'ICEEUR')      ← 표준선물")
        print("     - ('UKX', 'FOREXCOM')    ← 인덱스 (CFD 데이터)")
        print("     - ('UK100', 'CAPITALCOM')← CFD 인덱스")
    if 'AXJO' in fail:
        print("\n  ⚠ ASX SPI 200 실패 시 대안 심볼:")
        print("     - ('AP1!', 'ASX')        ← SPI 200 선물 (현재 설정)")
        print("     - ('AS51', 'INDEXASX')   ← S&P/ASX 200 인덱스")
        print("     - ('AUS200', 'CAPITALCOM') ← CFD 인덱스")


if __name__ == "__main__":
    main()
