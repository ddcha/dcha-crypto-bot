# fix/verify-today-live-overlay — verify_today.py 파리티 판정 결함 수정

발견: 2026-07-29 (07-28 ETH·LINK "라이브미진입" 오탐 추적 중)

## 증상

07-28 12:00 봉에서 verify_today 가 3건을 "백테 거래"로 출력하고 ETH·LINK 를
`⚠️라이브미진입` 으로 표시했다. 실제로는 두 코인 모두 13:30 에 진입가를 **터치했는데도**
라이브가 진입하지 않았다 (AVAX 는 15:15 터치·15:26 진입 정상).

## 원인 — 라이브가 옳고 검증 도구가 틀렸다

라이브 `get_armed_zones` 를 07-28 12:00 시점으로 재현한 결과, ETH·LINK 후보 3건씩이
전부 동일 사유로 탈락했다.

| 심볼 | entry / sl | setup | base_risk | 판정 |
|---|---|---|--:|---|
| ETHUSDT | 1860.03 / 1770.2188 | `a_mss+a_score_ge13+a_vol_expansion` | **0.0** | 0%차단 |
| LINKUSDT | 8.197 / 7.839726 | `a_mss+a_score_ge13+a_vol_expansion` | **0.0** | 0%차단 |
| AVAXUSDT | 6.509 / 6.778331 | `a_fvg_absent+a_ob+a_room+a_trend_counter` | 1.0566 | ✅무장 |

`v6.1_backtest_package/README.md` 가 확정 프레임을 명시한다:

> 진입 = v4 42룰 + 만기 36h 컷 + **0% combo 차단** (라이브 진입 프레임)
> 진입 1016건 = 1131 − 만기컷42 − **0%차단73**

즉 0%차단은 CAGR 951%·MDD −20.8% 를 산출한 확정본의 일부다. **라이브 미진입이 정상**이고,
`verify_today.py` 가 42룰 union 만 걸어 확정 프레임보다 permissive 했던 것이 오탐의 원인.
(`combo_risk_table.json` 을 참조하는 파일이 `strategy_engine.py` 하나뿐이었던 것이 결정적 단서.)

## 수정 2건

### 1) 라이브 오버레이 이식 (`EXPH=36` · `combo_active`)
v6.1 `run_v6.1_backtest.py` 와 동일 로직. 차단된 후보는 버리지 않고
`🚫차단사유` 와 함께 **별도 섹션으로 출력**해 진단 정보를 보존한다.

### 2) 원자 귀속 복구 (★1번만 고치면 반대 방향 오판)
원자 태그는 후보 DataFrame 에 **컬럼으로 존재하지 않는다** — `compute_trade_tags`
호출 시점에만 만들어진다. v6.1 은 `simulate_scenario` 결과(원자 컬럼 보유)에 귀속시켰지만
verify_today 는 후보 단계라 그 경로가 없다.

- `_wrap` 에서 `_TAGS[(ei, side)]` 로 태그 캡처, 심볼별 gen 직전 `clear()` (idx 충돌 방지)
- **off-by-one**: 후보의 `entry_idx` 는 터치봉, 태그는 신호봉(=터치봉−1)에서 계산 → 조회 시 `-1`

1번만 적용한 첫 실행에서는 전 후보가 `규칙미매칭` 으로 떨어져 **AVAX 마저 차단**되는
반대 방향 오판이 났다. 2번 적용 후 귀속이 라이브와 일치:

```
tags@10016 = ['__side_short','__zone_range','a_efficiency','a_ob','a_room','a_wick_le_q1']
→ setup = a_fvg_absent+a_ob+a_room+a_trend_counter     # 라이브 diag 와 동일
```

## 수정 후 07-28 판정

```
=== 백테 거래 (★라이브 오버레이 적용) : 1건 ===
  AVAXUSDT short entry=6.509 sl=6.778331  → ✅라이브도잡음
=== 오버레이로 차단된 후보 (양쪽 미진입이 정상) : 2건 ===
  ETHUSDT  long entry=1860.03 → 🚫0%차단(a_mss+a_score_ge13+a_vol_expansion)
  LINKUSDT long entry=8.197   → 🚫0%차단(a_mss+a_score_ge13+a_vol_expansion)
=== 판정 === ✅ 라이브 오늘거래 1건 전부 백테에 동일 존으로 존재
```

## 영향 범위

- **라이브 엔진 무변경.** 검증 도구만 수정 — 라이브는 처음부터 옳게 동작하고 있었다
- `verify_live_trade.py` 는 `SE.get_armed_zones` 를 직접 호출하는 라이브 경로라 결함 없음
- 이전에 이 도구로 낸 `⚠️라이브미진입` 판정들은 **재검토 대상** (0%차단·만기컷 후보가
  오탐으로 섞였을 수 있음)

## 미해결 (별도 브랜치)

`arm_worker.make_live_loader` 의 H1 갭 — `data_cache` 시드(06-30 종료) + 거래소 200봉
(1h=8.3일) 조립이라 **07-01~07-20 H1 이 비어 있고 매일 커진다**. 4h 는 200봉=33일이라 무사.
현재 실피해는 미확인(H1 refine 이 최근 ±12봉만 봄, main.py:1046) 이나 잠재 위험.
→ `fix/live-h1-gap`
