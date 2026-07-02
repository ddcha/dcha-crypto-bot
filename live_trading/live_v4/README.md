# live_v4 — 확정 baseline 라이브 소액 테스트

★ 기존 live(Stage 4K, **룩어헤드 결함으로 폐기**)를 대체. **smc_stage4d(룩어헤드 free) 백테스트 엔진** 기반으로 재구축.
확정 전략 = **v4 42규칙 + 만기컷(48h) + 24·25제거 + 전역 risk×1.2 + killer 3.5%캡** (backtest 68.69억/MDD−17.68%).

## 검증됨 ✅
`test_offline.py` — 알려진 v4 거래 4건을 **캔들만으로(API X) 재검출**: side·setup·risk 전부 일치 (룩어헤드 0).

## 구조
| 파일 | 역할 |
|---|---|
| `main_live.py` | 라이브 루프 (H4 마감마다 신호→사이징→주문→SL). ★안전장치 다수 |
| `strategy_live.py` | ★룩어헤드 free 신호생성 — smc_stage4d gen + v4 게이트. flat 더미봉 패딩으로 현재봉 신호 방출(진입판정은 실데이터만=룩어헤드X) |
| `config_live.py` | 확정 파라미터 + ★안전장치(DRY_RUN·소액상한·하드캡·킬스위치) + API키(env) |
| `exchange_bybit.py` | Bybit 래퍼(pybit) — 기존 인프라 재사용 |
| `combo_risk_table.json` | 조합별 risk (역산×g1.2, 24·25=0, killer≤3.5%) |
| `setups_btc_triple_a3v4.json` | v4 42규칙 |
| `smc_stage4d/` | 백테스트 엔진(동일) |
| `test_offline.py` | 오프라인 신호 검증 |

## 안전장치 (config_live.py)
- **`DRY_RUN=True`** — 기본 주문 안 냄(신호·사이징만 로그). 실주문은 명시적 False.
- **`USE_DEMO=True`** — Bybit demo 계좌.
- **`TEST_FIXED_NOTIONAL_USDT=12`** — 1포지션 명목가 상한(소액).
- **`HARD_MAX_RISK_PCT=2.0`** — 소표본 120% risk 방지 clamp.
- `MAX_OPEN_POSITIONS=2`, `MAX_DAILY_ORDERS=20`, `MIN_BALANCE_USDT=30`.
- **`KILL` 파일** 생성 시 즉시 신규진입 중단.

## 실행
```powershell
pip install pybit pandas numpy pyarrow
$env:BYBIT_DEMO_API_KEY="..."; $env:BYBIT_DEMO_API_SECRET="..."; $env:PYTHONUTF8="1"
python test_offline.py     # 1) 오프라인 신호 검증 (API 불필요, data_cache 필요)
python main_live.py        # 2) DRY_RUN 라이브 (신호 로그만, 주문X)
# 3) 소액 실주문: config_live.py DRY_RUN=False (DEMO 유지 권장) 후 재실행
```

## 라이브 신호 원리 (룩어헤드 free 보장)
백테스트 candidate 생성은 진입 후 미래봉으로 시뮬해야 후보를 방출 → 라이브 현재봉은 미래봉 없음.
→ 캔들 뒤에 **flat 더미봉(마지막 close 반복) 패딩**으로 시뮬만 완료시켜 현재봉 후보 방출.
**진입 판정(side/entry/sl/원자/zone)은 실데이터(≤현재봉)만 사용** → 룩어헤드 없음. 더미봉은 무시되는 시뮬에만 영향.
원자 태그는 신호봉(entry_idx−1, HONEST_STAGE=5)에서 캐시 → v4 규칙 attribution → risk 조회.

## ⚠️ 실계좌 전 체크
- 반드시 DRY_RUN → DEMO 소액 → 실계좌 소액 순서.
- 청산(exit) 관리: 현재는 진입+SL만. TP분할/트레일링/러너 등 백테스트 exit plan은 추가 구현 필요(다음 단계).
- 라이브 체결은 봉마감 감지 후 시장가 → 백테스트 봉내 체결 대비 약간의 슬리피지 있음.
