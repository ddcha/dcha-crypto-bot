# 실전 실행 — 무장존 파리티 라이브 (이 폴더 하나로 자립)

라이브를 백테(**62.52억 / MDD −17.75%**, cap15·만기36h·백테트레일·15m fill)와 **같은 빈도**로 매매.
"무장존"(전 게이트 통과·터치 대기 존)을 H4마다 계산·캐시 → 가격 터치 시 진입. **백테 28/28 정확 재현 검증.**

## 이 폴더만 있으면 됨 (자립 구성)
| | |
|---|---|
| `main.py` | 메인 루프 (터치 진입 + 포지션관리 TP/BE/트레일/SL) |
| `arm_worker.py` | 배경 워커 (H4마다 full-히스토리 무장존 → `armed_cache.json`) |
| `strategy_engine.py` / `smc_stage4d/` | v4 전략엔진 (honest, cap15·만기36h·백테트레일) |
| `arm_entry.py` | 터치 진입 신호 로직 |
| `config.py` `exchange_bybit.py` 등 | 라이브 인프라 (주문·상태·watchdog) |
| `data_cache/` | 워커 full-히스토리 시드 (4h+1h, 9심볼 — 2022~) |
| `combo_risk_table.json` `setups_btc_triple_a3v4.json` | risk테이블·42규칙 |
| `run_live.sh` | ★런처 (워커+메인 함께 기동) |

## API 키 — 기존과 동일 (컨트롤패널)
**기존처럼 컨트롤패널로 키를 입력하면 그대로 됩니다.** 워커·메인 둘 다 `live_settings.json` 우선 → env 폴백,
모드(live/demo)도 패널 설정을 따릅니다(제가 credential 경로는 안 건드림).
```bash
python control_panel.py     # ← 기존처럼 여기서 API 키·모드(demo/live) 입력 → live_settings.json 저장
```
(env 로도 가능: `BYBIT_DEMO_API_KEY/SECRET` 또는 `BYBIT_LIVE_API_KEY/SECRET`)

## 실행
```bash
pip install pybit pandas numpy pyarrow python-dotenv
bash run_live.sh          # 워커(배경) + 메인 함께 기동 (키는 컨트롤패널 live_settings.json 에서 읽음)
```
- 워커 로그: `arm_worker.log`. 최초 full-gen ~15분(9심볼) 후 `armed_cache.json` 생성 → 그때부터 메인이 진입.
- 캐시 없으면 메인은 **진입 안 함**(안전). 워커는 H4 경계마다 자동 재계산.

## 개별 실행 (systemd 등)
```bash
STAGE4D_DLCACHE=./data_cache python arm_worker.py --loop --live   # 워커만 (별 프로세스)
python main.py                                                    # 메인만
```

## 안전 체크리스트 (실계좌 전)
1. **demo 소액**으로 먼저: 워커가 armed_cache 생성하는지, 메인이 터치 시 진입하는지, SL/TP 붙는지.
2. `config.py` 확인: `TRAIL_MODE="backtest"`(백테트레일), 리스크캡·만기 기본값, `MAX_NOTIONAL_MULT=3.0`.
3. 첫 진입 로그에서 side·risk%·qty·SL·tp_plan 정상인지.
4. 워치독: 워커는 별 프로세스라 메인 루프를 막지 않음.

## 진입 방식 (현재) 및 업그레이드
- **현재 = 터치 시장가**: 무장존 경계 터치 시 시장가 진입(기존 체결/포지션관리 재사용). 갭 92.4% 정확·7.6% 유리.
- **업그레이드 = 순수 지정가**(체결가 정확·봉간 체결): `arm_entry.plan_armed_orders` + `exchange.place_limit_entry_order` 준비완료, 비동기 체결감지 훅업만 남음. `ARMED_INTEGRATION.md` 참조.

## 데이터 갱신
`data_cache/` parquet 은 시드(2022~). 워커 `--live` 가 거래소 최신봉을 merge 하므로 실행 중 자동 최신화.
장기 운영 시 주기적으로 data_cache parquet 재생성 권장(드리프트 방지).
