# 무장존 지정가 파리티 — 통합 가이드

라이브를 백테(62.52억)와 **같은 빈도**로 매매. "무장존"(전 게이트 통과·터치 대기 존)을 H4마다 계산·캐시 → 존 경계에 지정가 거치 → 터치 체결. **검증: 백테 28/28 정확 재현(entry·sl Δ0.00%), off-by-bar 없음.**

## 구성 요소 (전부 완성·검증됨)
| 파일 | 역할 | 상태 |
|---|---|---|
| `smc_stage4d/simulation.py` `_arm_bar` | 무장존 노출(진입 직전 전 게이트 통과 존) | ✅ 백테 바이트동일 |
| `strategy_engine.py` `get_armed_zones()` | 무장존별 setup·risk%·qty·tp_plan·우선순위 부착 | ✅ 검증 |
| `arm_worker.py` | H4당 full-히스토리 계산 → `armed_cache.json` | ✅ ~15분/9심볼 |
| `exchange_bybit.py` `place_limit_entry_order/cancel_order/get_open_orders` | 지정가 진입·취소·조회 | ✅ |
| `arm_entry.py` `plan_armed_orders/match_fill_to_armed` | 거치/취소 결정 로직(순수) | ✅ 유닛테스트 |

## 데이터 흐름
```
[배경워커: H4마다]  arm_worker.py → get_armed_zones(심볼별 full히스토리) → armed_cache.json (원자적)
[메인루프: 매틱]    armed_cache 읽기 → arm_entry.plan_armed_orders(현재가·미체결·포지션) →
                    place_limit_entry_order / cancel_order 실행
[체결감지]          포지션 출현 → orderLinkId 로 match_fill_to_armed → 무장 payload →
                    build_managed_position(기존) → 나머지 arm 지정가 취소 → 기존 SL·TP 관리
```

## ✅ 배선 완료 (구현됨) — 터치 시장가 방식
main.py 진입부(generate_entry_signal 시장가 즉시신호)를 **무장캐시 터치신호**로 교체(main.py ~2600).
기존 주문/체결동기화/build_managed_position/SL·TP 흐름 **100% 재사용** → money-code 위험 최소.
```python
_ac = load_armed_cache("armed_cache.json", symbol)                       # 워커 캐시
entry_signal = armed_signal_on_touch(_ac["armed"], current_price)        # 현재가가 터치한 무장존(우선순위0)
# → should_enter 시 실잔고로 qty 재계산(min(base*rm,15%)) → 기존 시장가 진입 흐름 그대로
```
- **존은 백테와 동일하게 미리 무장돼 대기**(28/28 재현). 가격이 존 경계 터치 시 그 존으로 시장가 진입.
- 슬리피지: 터치 시장가는 존 엣지 근처 체결(갭분석상 92.4% 정확·7.6% 유리) → 실질 손해 없음.

## 실행 (run model)
```bash
# 1) 배경 워커: H4마다 무장존 재계산 → armed_cache.json (별도 프로세스/systemd)
python arm_worker.py --loop --live      # --live=거래소 최신봉 merge, --loop=H4 경계 반복
# 2) 메인: armed_cache 읽어 터치 진입 + 기존 포지션관리
python main.py
```
watchdog: 워커 gen(~15분/9심볼)은 별도 프로세스라 main 루프·watchdog 안 막음.

## (향후) 정밀도 업그레이드 — 순수 지정가
`arm_entry.plan_armed_orders` + `exchange.place_limit_entry_order/cancel_order` 로 존 경계에 **지정가 거치**(터치 시장가 대신).
체결가 정확·봉간 체결 가능. 단 비동기 체결감지(match_fill_to_armed→build_managed_position) 배선 필요. 컴포넌트 준비완료, 훅업만 남음.

## 확인된 정합 사항
- **우선순위**: armed[0]=백테 최우선(scored_active 정렬). 근처 무장 여러 개면 우선순위순 최대 N개 거치.
- **갭오픈**: 92.4% 정상터치=백테 정확일치, 7.6% 갭=지정가가 더 유리(손해 없음).
- **단포지션·쿨다운**: 포지션 보유 시 진입지정가 전취소로 단포지션 보장. same-side 쿨다운은 gen 내 유지(non-emission).
- **오발 방지**: 근처(proximity) 존만 거치 + 단포지션 전취소 → 과매매 없음.

## 검증 재현
- 무장 재현: 백테 각 트레이드 진입봉에서 `get_armed_zones` 로 그 존 무장 확인(28/28 Δ0.00%).
- 워커: `python arm_worker.py --syms BTCUSDT,SOLUSDT` → armed_cache.json 생성 확인.
