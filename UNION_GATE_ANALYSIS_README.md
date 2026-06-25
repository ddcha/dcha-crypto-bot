# 최대원자 귀속 union 게이트 실험 + 비멱등 누수 발견 (분석 노트)

브랜치: `feat/atom-tier-engulf-atr13`. smc_stage4d 백테스터로 셋업 리스트(JSON)를 "최대원자 귀속 union 게이트"로 돌린 실험과, 그 과정에서 발견한 엔진 비멱등(룩어헤드성) 문제 기록.

## 게이트 정의
각 거래 진입 시, 그 파일의 셋업 중 "원자가 전부 True 인" 셋업이 1개라도 있으면 진입(OR of ANDs, 진짜 게이트 — 슬롯 재배치 반영). 귀속(matched_setup)은 원자 최다 셋업으로 라벨링하는 **사후 분류**(진입엔 영향 없음). 엔진 경로: `simulation.py` `_combo_union_match` + `COMBO_UNION_ATOMSETS`(config: `COMBO_UNION_JSON` env 로드).

## baseline
OB_MODE=engulf, DISP_ATR_MULT=1.3, USE_H1_REFINE=1, HONEST_STAGE=5, MIN_SCORE=7.5, risk_multiplier=1.0.
자본시뮬: 시드500 + 월말250×5(총1750), RISK_PCT=0.01 flat, 이벤트순 진입<입금<청산, run_equity 신규(v19b 자본로직 아님). 룩어헤드 6분할×50변조 불일치0 통과.

## 스크립트
- `run_setups30_union.py` — setups_30(30) 단일 백테스트.
- `run_combo_files.py` — setups_pf10/12/13/14 4개 순차 비교 (⚠️ 아래 비멱등 오염 있음).
- `run_combo_files_clean.py` — **클린판**: 패스마다 `_ls_*` 리셋 → 오염 제거.
- `run_setups368_union.py` — setups_368(368, ≈무게이트) 단일.
- `run_stage1_passrate.py` — 원자 임계 OLD/NEW 통과율 측정(런타임 패치, 멱등성 검증 포함).
- `diag_*.py` — 슬롯/가설/클린-오염 비교/wick 분포 진단.

## ⚠️ 핵심 발견 — `generate_candidates_from_prepared` 비멱등 (잠재 누수)
- `advance_zone_lifespan`(structures.py:74)이 존 수명 상태를 structure dict에 증분 캐시(`_ls_role/_ls_broken/_ls_pos`, L79-111, 최초 1회만 init).
- `generate_candidates` 시작 리셋은 `s["used"]`만 → **같은 prepared에 2번째+ 호출 시 `_ls_pos`가 시리즈 끝까지 전진해 있어 모든 존이 "끝 시점 역할"로 판정**(증분 루프 빈 구간) = 룩어헤드성 오염.
- 증거: 게이트 OFF(원자=로그용, candidate에 영향0)인데 같은 prepared 1차 1702 → 2차 1768건.
- **영향**: `run_combo_files.py`가 prepared 1회 생성 후 pf10→pf12→pf13→pf14 순차 실행 → pf10(1패스)만 클린, **pf12/13/14 오염**. setups_30/pf10/setups_368(각 독립 1패스)은 클린.
- **우회(엔진 미수정)**: 하베스트에서 패스마다 `_ls_*`+`used` 제거(`reset_prepared`). 영구수정은 원본 `smc_crypto_stage4d_atom_gate (1).py`의 리셋 루프에 `_ls_*` 추가 후 re-extract 필요(**미적용, 승인 대기**).

## 정정된 결과 (클린, `run_combo_files_clean.py`)
| 파일 | 셋업 | 거래 | PF | OOS | 매년삶 | 자본배수 | MDD |
|---|---|---|---|---|---|---|---|
| pf10 | 22 | 1391 | 1.30 | 1.32 | ✓ | 9.25x | −16% |
| pf12 | 19 | 1391 | 1.31 | 1.34 | ✓ | 9.45x | −17% |
| pf13 | 17 | 1386 | 1.31 | 1.33 | ✓ | 9.09x | −19% |
| pf14 | 14 | 1255 | 1.06 | 0.90 | ✗ | 1.79x | −29% |

- 검증: 클린 pf10 == 오염 pf10(1391/1.30, 키 대칭차0) → 리셋 안전·pf10 원래 클린.
- pf12/13의 "붕괴(0.89/0.90, 자본0.6x)"는 **전부 비멱등 오염 아티팩트**. 클린에선 pf10~13 동등(~1.31), pf14만 진짜 약화.
- 이전 보고의 "역U자·전면 강제대체"는 오염 기반이라 **철회**. 강제대체는 pf14(14셋업)에서만 약하게 실재(공통 PF1.29 vs 신규 0.84).
- REF(사후 기대값)는 룩백 자기선택 통계 → forward와 무관, 폐기.

## Stage 1 통과율 (run_stage1_passrate.py, 게이트 OFF, base candidate 1702)
7개 config 상수만 런타임 조정(파일 무수정). a_pre_total_ge1은 filters.py:291 로직(상수 아님)이라 측정만.
- 목표 15~25% 적중: a_efficiency(22.6%), a_bb_squeeze(25.0%), pre_total **ge2(21.4%)**.
- 플래그: a_room 79.4%(임계 1.5→2.8에도 거의 안 걸림 — pd 1620봉 극값 문제), a_fvg 38.1%, a_wick 30.7%.
- 변별력(사후, 게이트 OFF)은 close_at_end 7건 포함/제외만으로 부호가 뒤집힐 만큼 불안정 → 결론 근거로 부적합. **게이트 ON solo로 판정 필요(미실행)**.

## 미해결 / 다음
1. 엔진 `_ls_*` 영구수정(원본 재추출) — 승인 대기.
2. a_pre_total_ge1 → ge2 (filters.py:291 로직 1줄) — 승인 대기.
3. Stage 2: 17 solo 게이트 OLD·NEW 비교(게이트 ON 변별 판정) — 보류 중.

(결과 CSV·trades는 .gitignore 제외. `combo_backtest_bundle/`은 엔진 중복이라 미커밋.)
