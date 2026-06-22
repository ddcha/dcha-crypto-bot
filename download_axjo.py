"""
================================================================
AXJO (호주 ASX SPI 200) 단독 다운로드 스크립트
================================================================
- AXJO 만 따로 받음 (다른 10자산은 이미 받았으니 건너뜀)
- 여러 심볼 시도하면서 성공할 때까지 진행
- N_BARS = 10000 (한계 테스트)

실행:
  python download_axjo.py
================================================================
"""

from pathlib import Path

try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    print("❌ tvDatafeed 가 설치되지 않았습니다.")
    print("   설치: pip install https://github.com/rongardF/tvdatafeed/archive/refs/heads/main.zip")
    raise SystemExit(1)

import pandas as pd

# ============================================================
# 설정
# ============================================================
DATA_DIR = Path("./tv_data")
DATA_DIR.mkdir(exist_ok=True)

OUTPUT_KEY = "AXJO"
INTERVAL = Interval.in_1_hour
N_BARS = 10000   # 한계 테스트 — 실제로는 받아지는 만큼만 옴

# 시도 순서 — 위에서부터 차례로 시도, 성공하면 stop
# (TradingView 에서 'ASX 200' 검색 시 나오는 모든 후보)
CANDIDATES = [
    # (symbol, exchange, 설명)
    ('AS51',   'INDEXASX',    'S&P/ASX 200 인덱스 (현물)'),
    ('AUS200', 'CAPITALCOM',  'CFD 인덱스 (CapitalCom)'),
    ('AS51',   'TVC',          'TVC 의 ASX 200'),
    ('AUS200', 'OANDA',       'OANDA CFD'),
    ('SPI',    'ASX',          'SPI 200 (다른 표기)'),
    ('AP',     'ASX',          'AP 단순 (continuous)'),
    ('AP1!',   'SNFE',         'SNFE 거래소 시도'),
    ('XJO',    'ASX',          'XJO 인덱스'),
]

# ============================================================
# 메인
# ============================================================
def main():
    print("=" * 70)
    print(f"AXJO 단독 다운로드")
    print(f"  N_BARS: {N_BARS}")
    print(f"  저장 경로: {DATA_DIR.absolute() / f'{OUTPUT_KEY}_1h.csv'}")
    print("=" * 70)

    print("\n[Tradingview 초기화 중...]")
    tv = TvDatafeed()
    print("  익명 모드")

    success = False
    for i, (symbol, exchange, desc) in enumerate(CANDIDATES, 1):
        print(f"\n[{i}/{len(CANDIDATES)}] {exchange}:{symbol:<10} ({desc})")
        try:
            df = tv.get_hist(
                symbol=symbol, exchange=exchange,
                interval=INTERVAL, n_bars=N_BARS
            )
            if df is None or len(df) == 0:
                print(f"    ✗ 빈 데이터 반환")
                continue

            # 컬럼 정리
            if 'symbol' in df.columns:
                df = df.drop(columns=['symbol'])
            df.columns = [c.capitalize() for c in df.columns]
            df.index.name = 'Datetime'

            # 저장
            out_path = DATA_DIR / f"{OUTPUT_KEY}_1h.csv"
            df.to_csv(out_path)

            print(f"    ✓ 성공! {len(df)} 캔들")
            print(f"      기간: {df.index[0]} ~ {df.index[-1]}")
            print(f"      저장: {out_path}")
            success = True
            break

        except Exception as e:
            print(f"    ✗ 실패: {e}")

    print("\n" + "=" * 70)
    if success:
        print(f"[완료] {OUTPUT_KEY} 데이터 저장됨")
        # 다른 자산 검증
        print("\n[전체 tv_data/ 폴더 검증]")
        for csv in sorted(DATA_DIR.glob("*_1h.csv")):
            try:
                df = pd.read_csv(csv, index_col=0)
                start = str(df.index[0])[:19]
                end   = str(df.index[-1])[:19]
                print(f"  {csv.stem:<10} {len(df):>6} rows  ({start} ~ {end})")
            except Exception as e:
                print(f"  {csv.stem:<10} ❌ 읽기 실패: {e}")
    else:
        print("❌ 모든 시도 실패")
        print()
        print("다음 단계:")
        print("  1) TradingView 웹에서 직접 'ASX 200' 검색")
        print("     https://www.tradingview.com/symbols/AS51/ (인덱스)")
        print("     https://www.tradingview.com/symbols/ASX-AP1!/ (선물)")
        print("  2) URL 에서 정확한 exchange:symbol 형식 확인")
        print("     예: tradingview.com/symbols/[EXCHANGE]-[SYMBOL]")
        print("  3) AXJO 빼고 10자산만으로 백테 진행해도 됨")
    print("=" * 70)


if __name__ == "__main__":
    main()
