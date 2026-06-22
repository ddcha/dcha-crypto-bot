"""
================================================================
TPX (TOPIX) 단독 다운로드 스크립트
================================================================
- TPX 만 따로 받음 (다른 자산은 이미 받았으니 건너뜀)
- 여러 심볼 시도하면서 성공할 때까지 진행
- N_BARS = 10000

실행:
  python download_topix.py
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

OUTPUT_KEY = "TPX"
INTERVAL = Interval.in_1_hour
N_BARS = 10000

# 시도 순서 — 위에서부터 차례로 시도, 성공하면 stop
CANDIDATES = [
    # (symbol, exchange, 설명)
    ('TOPIX1!',  'OSE',     'TOPIX Futures (정식 - 가장 가능성 높음)'),
    ('TOPIXM1!', 'OSE',     'TOPIX Mini Futures (백업)'),
    ('TPX',      'TVC',      'TVC TOPIX 인덱스'),
    ('TOPIX',    'TSE',      'TSE TOPIX 인덱스 (현물)'),
    ('JP100',    'CAPITALCOM','CFD 인덱스 (대안)'),
]

# ============================================================
# 메인
# ============================================================
def main():
    print("=" * 70)
    print(f"TPX (TOPIX) 단독 다운로드")
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
        # 다른 자산 함께 검증
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
        print("  1) TradingView 웹에서 직접 'TOPIX' 검색")
        print("     https://www.tradingview.com/symbols/OSE-TOPIX1!/  (선물)")
        print("     https://www.tradingview.com/symbols/TSE-TOPIX/    (인덱스)")
        print("  2) URL 에서 정확한 EXCHANGE-SYMBOL 형식 확인")
        print("  3) 또는 익명 모드 한계일 수 있음 → TV 계정 로그인 시도")
    print("=" * 70)


if __name__ == "__main__":
    main()
