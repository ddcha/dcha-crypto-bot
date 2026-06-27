# BTC 3중게이트 v4 — 최종 채택 마일스톤

브랜치: `feat/atom-tier-engulf-atr13`. 원자 재구성 → BTC레짐 3중게이트 → 가지치기 → **3종 검증으로 v4(42규칙) 최종 채택**까지의 결과·검증.

## 최종 채택: `setups_btc_triple_a3v4.json` (42규칙)
각 규칙 = `{atoms[...], btc_zone, side}` 3중 조건. 진입 = (atoms 전부 AND) AND btc_zone 일치 AND side 일치 규칙이 1개+ 매칭.

## 영구반영된 엔진 변경 (2건)
1. **room swing60** (`filters.py` + 원본 `smc_crypto_stage4d_atom_gate (1).py`): a_room 타겟을 `pd_high/low`(1620봉 극값, RR1~5 9%로 변별불가 결함) → **최근 60봉 swing high/low**(RR1~5 69%, 변별력 +0.54). 룩어헤드 0(entry_idx 이하 60봉).
2. **`_combo_union_match` 음극지원** (`simulation.py` 모듈): `~a_fvg`/`~a_trend_align` 음극 atom을 NOT으로 매칭(정극 오매칭 방지). ※ 원본엔 COMBO_UNION 자체가 없음(모듈 직접추가分) — [[project_extract_sync_landmine]] 참조.

## baseline
OB_MODE=engulf / DISP_ATR_MULT=1.3 / USE_H1_REFINE=1 / HONEST_STAGE=5 / room=swing60 / bb_squeeze 제외.
확정 임계: REG_VOL_PCTL=0.85(vol_expansion 조임), BROAD_FVG_SIZE_ATR=0(→~a_fvg=FVG 순수 없음).
BTC레짐: BTCUSDT_h4.csv ma10/ma30 → btc_dist, entry이전(strict<) 매칭. <−1=down/−1~1=range/>1=up.
자본시뮬(4L 이식, BOOST/tier/phase/excess 제외): KRW_PER_USDT=1540, 시드500만, 월250만×5, RISK 1%, fee 0.00055편도, max_notional 3배. total_assets MDD%, 룩어헤드테스트.

## 원자 재구성 결론 (실측 solo 기준)
- 확정 알파: **a_score_ge13(≥10) · ~a_fvg(없음) · a_volume(1.5) · a_room(swing60) · a_ob(존재) · a_vol_expansion(0.85)**
- 폐기: wick·bb_squeeze·pre_total·sweep_count·sweep·mss·efficiency조임·trend_h1choch(룩어헤드0이나 이점없음)
- 비대칭: **OB는 "있음"이 알파, FVG는 "없음"이 알파.**
- 핵심교훈: 사후 변별력은 실측서 반전 빈번(efficiency·~wick·~bb·pt≥3·sweep_count) → **실측이 최종판정.**

## a3 vs v4 가지치기 (음수규칙 제거)
114(원자≥1) → 63(a3, 원자≥3 양수) → 49(v2) → 44(v3) → **42(v4)**. v2~v4는 IS/OOS 괴리(과적합 의심)였으나 **검증에서 v4 우위 확인.**

## ★ 3종 검증 — v4가 전부 통과 (a3 대비)
| 검증 | a3(63) | **v4(42)** |
|---|---|---|
| 2022 순수OOS PF (규칙 미학습 대약세장) | 1.20 | **1.49** |
| Walk-forward 평균 검증창 PF | 1.35 | **1.58** |
| Walk-forward PF≥1 비율 | 79% | **86%** |
| 15m MTF 체결 PF (낙관편향) | 1.48 | **1.74** |
| 15m OOS | 1.27 | **1.61** |
| 최종자본(2022시드, 총1750만 납입) | 1.44억 | **2.28억** |
| MDD% (total_assets) | −26.1 | **−11.1** |
| 전체 매년삶 | ✅ | ✗(2026 0.98 경계, WF선 무시가능) |

→ **8지표 중 7개 v4 우위. v4 최종 채택.** 2022 대약세장(순수 OOS)·walk-forward·15m 실전체결 모두 통과 = 과적합 아님, robust.

## 핵심 스크립트
- 본게이트: `run_btc_triple_a3.py`(63) / `run_btc_triple_a3v4.py`(42) — 3중게이트(토큰 주입) + 음극 + 자본시뮬.
- 검증: `build_prepared_2022.py`(LOOKBACK_YEARS=5 2022캐시) → `run_2022_validate.py`(2022확장) → `run_walkforward.py`(롤링) → `run_15m_mtf.py`(15m 체결, H4 atr 스케일·entry i+1 수정본).
- 원자분석: `run_solo10_par.py`(병렬 solo+태깅), `run_alpha2_A/B.py`(전방향 변별·실측), `run_atom_alpha_A/B.py`.
- 자본엔진: 4L `make_deposit_schedule/apply_pending_deposits/calc_position_size` + 이벤트루프 KRW 이식(BOOST/tier/phase 제외).

## 산출물 (결과 CSV는 .gitignore 제외, v4·검증은 git add -f 포함)
- `btc_triple_a3v4_result/` — v4 trades.csv(+matched_rule·9원자·btc_dist·btc_zone·side·rule_natoms), rule_breakdown, equity_curve, monthly.
- `walkforward_result/` — trades_a3/v4, wf_a3/v4.
- `mtf15_result/` — 15m 재체결 trades.
- 캐시 `prepared_cache*.pkl`(143MB) 미커밋 — `build_prepared_2022.py`로 재생성.

## 미해결/다음
- 2026 borderline(v4 단일 구간) — 데이터 누적되며 모니터.
- 음수규칙 추가제거는 과적합(v2/v3에서 IS↑ OOS↓ 확인) → **v4에서 멈춤.**
