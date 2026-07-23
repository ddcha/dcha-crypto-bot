# v6.1 백테 패키지 — 현재 라이브 엔진과 완전 동일

**버전: v6.1** (fix 2026-07-24). 이 폴더만 다른 PC로 옮기면 **현재 라이브 v6 전략과 100% 동일한 백테**를 바로 실행. 자기완결(외부 의존 없음).
생성: 2026-07-23 · v6.1 고정: 2026-07-24.

실행: `python run_v6.1_backtest.py [--risk 2.0] [--regen]`

v6.1 = v6(청산 BT15·3 + 48h max_hold + 만기36h컷 + 0%차단 + 균일리스크)를 라이브 엔진과 전항목 대조 검증한 확정본.
라이브 대조: 11개 파라미터 전부 일치(리스크·exit_scheme·만기컷·BE@1.5·트레일 peak−1R·48h max_hold·부분익절없음·진입봉스킵 등).

## v6 = 무엇인가

| 축 | 내용 |
|---|---|
| **진입** | v4 42룰 + 만기 36h 컷 + 0% combo 차단 (라이브 진입 프레임) |
| **청산** | BT15·3 = 부분익절 없음(풀포지션) · BE@1.5R · 3R서 peak−1R 트레일 · 48h max_hold(러너 면제) |
| **리스크** | 균일 (기본 2%, 1.5%/1% 선택). combo_risk_table 무시 |
| **체결** | 1m 정직 (entry+4h 진입봉 스킵, 룩어헤드 없음) |

라이브 대비: 진입집합·오버레이·청산 로직 동일. 차이는 실행 슬리피지(백테는 슬리피지 0 가정)뿐.

## 환경

- Python 3.10+ , `pip install pandas numpy pyarrow`
- 네트워크 불필요 (모든 데이터 동봉)

## 실행

```
python run_v6_backtest.py                # 균일 2% (기본), 빠른경로
python run_v6_backtest.py --risk 1.5     # 균일 1.5%
python run_v6_backtest.py --risk 1.0     # 균일 1%
python run_v6_backtest.py --regen        # 진입 재생성(완전체, 원시→후보, ~20분)
```

- **빠른경로(기본)**: 동봉 `trades_v4.csv`(엔진 walkforward 진입셋)에 v6 프레임+청산 적용. 수초.
- **완전경로(--regen)**: `prepared_cache_2022.pkl`(동봉)로 엔진이 후보를 원시 4h/1h부터 **재생성** → v6 청산. 진입 판정까지 완전 재현. ~20분.
  - 빠른경로와 진입셋이 동일하면 파리티 확인(재생성 = trades_v4).

## 기대 결과 (빠른경로, in-sample 2022-2026)

| 리스크 | 진입 | PF | CAGR | 자본MDD | 최종 |
|---|--:|--:|--:|--:|--:|
| **2.0%** | 1016 | 2.63 | 951% | −20.8% | 5254억 |
| **1.5%** | 1016 | 2.63 | 596% | −16.2% | 863억 |
| **1.0%** | 1016 | 2.63 | 305% | −11.7% | 81억 |

*진입 1016건 = 1131 − 만기컷42 − 0%차단73. PF/승률/expR은 리스크 무관(청산 동일).*
*48h max_hold 적용 = 라이브 완전일치. (125h 미적용 대비 PF 2.52→2.63, MDD 개선)*

## 폴더 구조

```
run_v6_backtest.py                 메인 (자기완결)
smc_stage4d/                       엔진 코어 11모듈 (진입 재생성)
rules/
  setups_btc_triple_a3v4.json      v4 42룰 (라이브 동일)
  setups_btc_triple_a3.json        a3 룰 (참고)
  combo_risk_table.json            0%차단 판정용 (라이브 동일)
data/
  data_cache/                      4h/1h/15m parquet (27) — 지표/구조체
  raw_1m/                          9코인 1m (~380M) — 청산 정직체결
  raw_1m_july/                     7월 1m (~7/21) — 최신 확장
  prepared_cache_2022.pkl          구조체 캐시 (147M) — 완전경로 재생성용
  trades_v4.csv                    엔진 walkforward 진입셋 — 빠른경로/파리티
```

## 정직 경계

- **복리 아티팩트**: CAGR·최종금액은 복리+슬리피지0 가정으로 상방편향. **PF·자본MDD가 실질 신호.**
- **1m 정직체결**이나 same-min 피크-되돌림 미포착·트레일 슬리피지0 잔여 낙관.
- **in-sample 2022~2026(+7월 부분)**. walk-forward OOS 는 PF 2.30(BT15·3) 로 검증됨.
- 라이브 실수익은 스탑 슬리피지(v6는 청산 95%가 스탑/트레일)로 백테의 ~90-95% 예상.
- 리스크 2%: in-sample MDD −24%, 실전 −30%+ 각오. **소액 테스트용.** 시드 성장 시 1%로 축소 권장.

## 데이터 출처

- data_cache/raw_1m: Binance Vision 공개 선물 1m 덤프 (9코인, 2021-06~2026-07).
- trades_v4.csv: 엔진 walkforward (run_walkforward.py) 산출. 라이브와 동일 42룰.
- prepared_cache_2022.pkl: build_prepared_2022.py 산출 (LOOKBACK 5년).
