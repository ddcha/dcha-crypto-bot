# 기준 백테스트 번들 (self-contained)

**이 폴더만 있으면** 확정 기준 백테스트를 실행할 수 있습니다. `python run_baseline.py` 한 줄.

## 실행
```bash
pip install numpy pandas          # 의존성 이것뿐 (smc_stage4d·data_cache 불필요)
python run_baseline.py            # → 62.52억 / MDD -17.75% / 은퇴 2024-01, result/ 저장
```

## 확정 기준 조건
| 축 | 값 |
|---|---|
| 체결 | **15m fill** (r15m — 15분봉 재체결, H4 낙관편향 제거) |
| 트레일링 | **백테 엔진 트레일** (직전봉 range중점−0.10×H4ATR) = r15m에 반영됨 |
| 리스크캡 | **15%** (min(risk,15%) — 120% 소표본 3조합만 실효 타깃) |
| 만기컷 | **36h** (월간만기 잔여 ≤36h 진입 스킵) |
| 쿨다운 | 8h 양방향 EXIT (TP1 전 청산만) |
| SL | 구조적 1.0x (sweep극값±ATR쿠션) |
| 자본 | reverse_risk×1.2 · 24·25제거 · killer 3.5%캡 · notional 3배 · 시드500만+월250만×5 |

## 결과 (기대값)
거래 960 · 승률 57.0% · PF 2.010 · **최종 62.52억 · MDD −17.75%(2023-03-14) · 은퇴 2024-01**

## 파일
| 파일 | 역할 |
|---|---|
| `run_baseline.py` | ★단일 실행 엔트리 — 확정 조건으로 자본시뮬 → result/ |
| `run_reconcile.py` | 코어: `load`(두 CSV 병합·reverse_risk·pretp1) + `equity`(봉단위 settled 자본시뮬) |
| `run_expiry_save.py` | 만기컷 30h·36h 변형 저장 (`python run_expiry_save.py`) |
| `walkforward_result/trades_v4.csv` | 입력① — v4 42규칙 3중게이트 H4 거래 (생성물) |
| `mtf15_result/trades_v4_15m.csv` | 입력② — 위 거래를 15분봉 재체결한 r15m |
| `result/` | 출력 — trades.csv · capital_curve.csv · monthly.csv |

## 왜 이 두 CSV만으로 되나
튜닝 축(캡·만기·트레일링·쿨다운·SL·자본)은 전부 **자본시뮬 단계**에서 trade log에 적용됩니다.
트레일링(백테 vs R래칫)은 이미 `r15m`(백테 트레일)로 재체결돼 CSV에 박혀 있어, 자본시뮬은 CSV만 읽으면 됩니다.

## (선택) 캔들부터 전체 재생성
입력 CSV 자체를 캔들에서 다시 만들려면 아래가 추가로 필요 (무거움, 이 번들엔 미포함):
1. `data_cache/` (9코인 4h+15m parquet, ~107MB) + `prepared_cache_2022.pkl` (~153MB)
2. `smc_stage4d/` 엔진 패키지 + `setups_btc_triple_a3v4.json`
3. 체인: `run_walkforward_v4only.py` (캔들→`walkforward_result/trades_v4.csv`) →
   `run_15m_mtf.py` (→`mtf15_result/trades_v4_15m.csv`) → `run_baseline.py`
   ※ 위 파일들은 리포 루트에 있음. `prepared_cache_2022.pkl`은 build 스크립트로 생성.

## 분석 도구 (리포 루트, 참고)
`run_mc_cap.py`(몬테카를로 파산확률) · `run_trail_compare.py`(트레일 비교) · `run_sl_test.py`(SL 배수) · `run_live_vs_bt.py`(라이브대조). 상세는 `../reconcile_result/README.md`.
