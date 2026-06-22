# PR: Stage 4D 단일 파일 → `smc_stage4d/` 패키지 모듈화 (동작 100% 동일)

## 무엇을 / 왜

`smc_crypto_stage4d_atom_gate (1).py` (4,159줄, 단일 파일, 노트북 추출본)을
**라인범위 verbatim 추출**로 `smc_stage4d/` 패키지(10개 모듈)로 분리했다.
목표는 **로직 0 변경 + 동작(출력 CSV) 바이트 동일**. 가독성·유지보수성만 개선한다.

`allowme.md` 표준 플레이북(STEP 1~6) 그대로 진행했다.

## 범위 (사용자 확정)
- **모듈 분리만** (최대 안전, 라인범위 verbatim)
- 검증: **실행 CSV 바이트 동일성**
- 전달: **git init + 브랜치 + PR**

## 구조도

의존 방향(순환 없음, 호출그래프 DAG 로 검증):
`config → utils → data → indicators → tiers → structures → filters → simulation → reporting → __main__`

| 모듈 | 줄수 | 책임 |
|------|-----:|------|
| `config.py` | 404 | 모든 상수·테이블 단일 소스 (+ 재정의 상수 최종값 통합) |
| `utils.py` | 131 | 순수 헬퍼 (스톱·RR·overlap·포지션·페이즈) |
| `data.py` | 114 | Binance Vision 수집·캐시 + D1 추세 + 입금 스케줄 |
| `indicators.py` | 373 | MSS/FVG/OB/PD/Pivot/CHoCH/H4 state/sweep |
| `tiers.py` | 48 | Tier 분류 (`classify_tier_v19b_rp_boost`) |
| `structures.py` | 534 | 존·신선도·run potential·지표 파이프라인 |
| `filters.py` | 383 | 진입 필터 + 12원자 태그 |
| `simulation.py` | 1371 | 체결·시뮬레이션 엔진 |
| `reporting.py` | 212 | 월별 손익·은퇴월·요약 |
| `__main__.py` | 589 | 실행 오케스트레이션 (병렬) |

**합계 4,159줄 = 원본과 1:1** (모든 라인이 정확히 한 모듈로 배정됨, 추출기가 검증).

## 검증 결과 (동일성 증명)

같은 `data_cache` parquet 캐시로 원본(골든)과 모듈판을 각각 1회 완주 후 비교.

| 산출물 | diff -q | md5 |
|--------|:------:|:---:|
| stage4d_trades.csv (1.75MB) | ✅ | ✅ |
| stage4d_equity.csv | ✅ | ✅ |
| stage4d_monthly / skipped / overall_summary | ✅ | ✅ |
| atom_solo_effect / sweep_vol_pivot / tier_decomposition | ✅ | ✅ |
| rp_decomposition / rp_level_analysis / side_x_atom | ✅ | ✅ |
| top_combo_analysis / tier_original_vs_atoms | ✅ | ✅ |

→ **13 / 13 CSV 바이트 동일.** (py_compile + import 그래프 사전 점검도 통과)

## 핵심 보존 처리

1. **중간 재정의 상수 14개** (`H4_PIVOT_SWING_LEN` 3→30 등, `USE_VOLUME_FILTER` True→False 등):
   재정의 라인을 원본 순서대로 `config.py` 끝에 모아 **최종 실효값이 단일 소스로 승리** →
   함수가 `from .config import *` 로 항상 최종값을 본다. multiprocessing 워커 전파 문제까지 해결.
2. **순환 없는 레이어링**: 함수 67개를 호출그래프 DAG 레이어에 맞춰 배치, 각 모듈은
   **엄격히 하위 레이어에서만 `import *`** → 모듈 레벨 순환 불가능.
3. **주석 verbatim**: 추출은 "노드 앞 주석 동반" 라인범위 단위 → ◆ 해설/한국어 주석 보존.

## 버그/주의

- 원본의 `if __name__` 가드 부재 → 패키지는 실행부를 `__main__.py` 로 이동, `python -m smc_stage4d` 구동.
  loky 워커는 `config` 만 re-import 하여 `[ATOM GATE]` 배너가 stdout 에 중복 출력되나 **CSV 영향 없음**.

## 재현 / 재생성

```bash
python tools/extract_modules.py --write          # 패키지 재생성 (결정론적)
STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=out python -m smc_stage4d   # 실행
```

## 리뷰 포인트
- `tools/extract_modules.py` 의 `FUNC_MODULE` 배치와 `REDEF_NAMES` 통합 규칙
- `config.py` 끝의 재정의 상수 최종값 블록
- 레이어 순서가 호출 방향과 일치하는지

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
