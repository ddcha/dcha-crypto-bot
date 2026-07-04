# v4_integrated — 기존 라이브 인프라 + v4 전략엔진 이식

기존 라이브 시스템(0703 백업)의 **포지션관리·실행·control_panel은 그대로 유지**하고,
**진입/전략엔진만** 룩어헤드 free 확정 baseline(smc_stage4d v4)으로 교체.

## 왜
- 기존 `strategy_engine.py`(Stage 4K)는 **룩어헤드 결함 있는 백테스트 기반** → 진입신호 신뢰 불가.
- 포지션관리(TP분할·트레일링·러너·BE·SL)·실행·패널은 **룩어헤드 무관**(열린 포지션을 현재가로 관리) → 그대로 재사용.

## 무엇이 바뀌었나
| 파일 | 변경 |
|---|---|
| **`strategy_engine.py`** | ★신규 어댑터 — `generate_entry_signal`을 smc_stage4d v4 3중게이트로 재구현. 기존과 동일 인터페이스+payload 계약. zone패널 함수(prepare/build_structures/evaluate_zones)·`get_latest_balance_usdt`는 `strategy_engine_legacy`에서 재수출 |
| `strategy_engine_legacy.py` | 구 엔진(zone패널 함수 재사용용, 진입로직은 안 씀) |
| **`main.py`** | ★1곳만 수정 — 심볼 루프 전 `set_btc_regime(BTC h4)` 호출 추가(v4 btc_zone 게이트용) + import 1줄 |
| `smc_stage4d/`, `setups_btc_triple_a3v4.json`, `combo_risk_table.json` | ★신규 — v4 엔진·규칙·risk테이블 |
| main 포지션관리/control_panel/exchange_bybit/state_store/... | **변경 없음(그대로 재사용)** |

## ★ 확정 기준 조건 (2026-07-04, 재조정 분석 완료)
v4 42규칙 3중게이트 + 다음 기준으로 확정 (`../../reconcile_result/` 참조):
- **트레일링 = 백테 엔진 트레일** (직전봉 range중점−0.10×H4ATR) — main.py `calc_backtest_trail_stop`, `config.TRAIL_MODE="backtest"`. 구 R래칫 대비 MDD −17.75% vs −27% 우위. (롤백: TRAIL_MODE="rratchet")
- **리스크캡 15%** (`_HARD_MAX_RISK_PCT=15.0`) — 120% 소표본 3조합만 실효 타깃. MC상 파산 0%.
- **만기컷 36h** (`_EXPIRY_BLOCK_HOURS=36`)
- 24·25제거 + 전역 risk×1.2 + killer 3.5%캡 + 8h 양방향 쿨다운 + 구조적 SL 1.0x + notional 3배 + 15m fill 검증
- **백테스트: 62.52억 / MDD −17.75% / PF 2.010 / 은퇴 2024-01** (`reconcile_result/cap15_expiry36h_v2/`)

### 이전값(참고): 만기 48h·캡 2%·R래칫 = 13.83억/−26.35% → 기준조건으로 4.5배 자본·8.6%p MDD 개선.

## 룩어헤드 free 보장
백테스트 candidate 생성은 진입 후 미래봉 시뮬 필요 → 라이브 현재봉은 미래봉 없음.
→ 캔들 뒤 **flat 더미봉 패딩**으로 시뮬만 완료시켜 현재봉 후보 방출. **진입판정(side/entry/sl/원자/zone)은 실데이터(≤현재봉)만 사용** = 룩어헤드 없음.

## 검증 ✅
`test_adapter.py` — 알려진 v4 거래 2/2 재현: side·setup·risk·qty·tp_plan 등 **payload 계약 완전 충족**.
```
[BTCUSDT] Sell a_room+score+volume risk=1.29% qty=0.463 tp=base ✅
[SOLUSDT] Buy  ~fvg+ob+room+score risk=2.0%(캡) qty=424 tp=base ✅
```

## payload 계약 (기존 main 호환)
- 트레이딩: `should_enter, side(Buy/Sell), position_side, entry, sl, qty, notional, risk_per_unit, tp_plan, tp_plan_name, timestamp`
- 표시/로그: `grade, score, tier, tier_mult, sentiment_mult, stage4j_mult, risk_pct_base, risk_pct_tier_adjusted, atoms_dict` — v4는 tier/sentiment 미사용이라 **중립값(1.0/"V4")**

## 실행
```powershell
pip install pybit pandas numpy pyarrow
python test_adapter.py     # 어댑터 검증 (data_cache 필요, API 불필요)
# 라이브: 기존 방식대로 main.py 실행 (config.py 의 API키·심볼·risk_pct 등 그대로)
python main.py
```

## ⚠️ 라이브 검증 체크리스트
- config.py 의 `USE_DEMO=True` 로 DEMO 먼저.
- 첫 신호 발생 시 payload(risk_pct_tier_adjusted, tp_plan, side)가 정상인지 로그 확인.
- 포지션관리(TP1 지정가·트레일링·SL)는 기존 로직 그대로 작동 — 별도 검증 권장.
- BTC 레짐 갱신 로그(`[v4] BTC regime`) 정상 확인.
