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

## 남은 배선 (main.py 훅업) — 진입부(현재 시장가, ~2620-2760) 교체
1. **워커 상시 실행**: `python arm_worker.py --loop` 를 별도 프로세스/systemd 로 (26분 gen 이 메인 루프 안 막게). watchdog 은 워커 gen 유예.
2. **진입 루프 교체** (심볼별):
   ```python
   from arm_entry import load_armed_cache, plan_armed_orders, match_fill_to_armed
   ac = load_armed_cache("armed_cache.json", symbol)
   price = exchange.get_last_price(CATEGORY, symbol)
   open_arm = [o for o in exchange.get_open_orders(CATEGORY, symbol)... if orderLinkId.startswith("arm-")]
   has_pos = symbol in managed_positions or (open_positions_map.get(symbol) has_position)
   plan = plan_armed_orders(symbol, ac["armed"], price, ZONE_PROXIMITY_PCT, {existing link_ids}, has_pos, max_orders=3)
   for lid in plan["cancel"]: exchange.cancel_order(CATEGORY, symbol, order_link_id=lid)
   for p in plan["place"]:
       exchange.place_limit_entry_order(CATEGORY, symbol, p["side"], p["qty"], p["entry"], order_link_id=p["link_id"])
   ```
3. **체결 → 포지션관리**: 포지션 감지 시, 그 심볼 arm 주문 중 사라진(체결된) link_id 를 찾아 `match_fill_to_armed` →
   payload(entry/sl/qty/setup/tp_plan/risk)로 `build_managed_position(...)` 호출 후 managed_positions 등록 →
   나머지 arm 지정가 전취소. 이후 SL/TP/트레일링은 기존 `manage_open_positions` 그대로.
4. **잔고 주입**: 워커 `ARM_BALANCE` 또는 워커가 exchange 잔고 조회.

## 확인된 정합 사항
- **우선순위**: armed[0]=백테 최우선(scored_active 정렬). 근처 무장 여러 개면 우선순위순 최대 N개 거치.
- **갭오픈**: 92.4% 정상터치=백테 정확일치, 7.6% 갭=지정가가 더 유리(손해 없음).
- **단포지션·쿨다운**: 포지션 보유 시 진입지정가 전취소로 단포지션 보장. same-side 쿨다운은 gen 내 유지(non-emission).
- **오발 방지**: 근처(proximity) 존만 거치 + 단포지션 전취소 → 과매매 없음.

## 검증 재현
- 무장 재현: 백테 각 트레이드 진입봉에서 `get_armed_zones` 로 그 존 무장 확인(28/28 Δ0.00%).
- 워커: `python arm_worker.py --syms BTCUSDT,SOLUSDT` → armed_cache.json 생성 확인.
