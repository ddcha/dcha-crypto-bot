# feature/h1-refine-zone — H1×H4 존 정밀화(refine)

> **목표**: H4 FVG/OB 존이 H1 FVG/OB와 **가격범위가 겹치면** 진입 존을 **교집합으로 좁혀(refine)**
> 더 타이트한 진입가·손절로 R:R/체결정밀도를 높인다. 겹치지 않으면 H4 존 그대로.
> `H1_REFINE_SPEC.md` 구현. **룩어헤드 절대 0**, 기본 **off**(baseline 보존), 효과는 **CI로 측정**.

---

## ⚠️ 이 브랜치의 코드 출처 규칙 (중요)

`smc_stage4d/`는 원래 `smc_crypto_stage4d_atom_gate (1).py`의 **자동 추출본**이지만,
**이 feature 브랜치부터는 패키지를 1차 소스로 직접 편집**한다.
→ **이 브랜치에서 `python tools/extract_modules.py --write` 를 실행하지 말 것** (직접 편집분이 덮어써짐).
원본 단일 파일은 baseline 재현용으로만 보존한다.

---

## 📌 한눈에 보기

| 항목 | 내용 |
|------|------|
| **무엇** | H4 존을 H1 FVG/OB와의 가격겹침 교집합으로 좁혀 진입가·손절을 타이트화 |
| **토글** | 환경변수 `USE_H1_REFINE=1` (기본 `0`=off → baseline 보존) |
| **룩어헤드** | **0** — `df_h1["timestamp"] < entry_ts` (strict `<`)로 이미 닫힌 H1봉만 사용. 미래봉 변조 불변성 테스트 통과 |
| **격리 설계** | confluence·12원자 태그·run_potential은 **H4 원본 유지**, 오직 **진입가·손절(R 기하)** 에만 refined 적용 → CI 비교가 깨끗 |
| **OB 정의별 비교** | `OB_MODE=strict` / `engulf` 각각 on vs off (`apply_ob`가 H1에도 자동 전파) |

---

## 🔧 변경 사항

| 파일 | 변경 |
|------|------|
| `indicators.py` | `refine_zone_with_h1(df_h1, entry_h4_ts, z4_lo, z4_hi, lookback_h1_bars=12)` 함수 추가 |
| `config.py` | `USE_H1_REFINE` 토글 추가 (기본 off) |
| `simulation.py` | 진입 루프에 refine **계산**(touched 직후) + SHORT/LONG 분기에서 **존 교체**(진입가·손절만) + trade row 컬럼 |
| `tests/test_refine_no_lookahead.py` | 룩어헤드 0 회귀 테스트 (3000회 / 미래봉 변조 불일치 0) |

### refine 적용 위치 (수술적)
- `touched` 통과 직후 refine를 **계산만** 한다 (`_rlo_ref/_rhi_ref/_h1_refined/_h1_overlap_frac`).
- SHORT/LONG 분기에서 `if USE_H1_REFINE and _h1_refined:` 일 때만 `s`의 zone_low/high를 교집합으로 교체.
  - **SHORT**: 체결 = zone_low. refined zone_low(≥원본)로 진입가↑ → sweep_ref(위) 고정 → 손절거리↓
  - **LONG**: 체결 = zone_high. refined zone_high(≤원본)로 진입가↓ → sweep_ref(아래) 고정 → 손절거리↓
- `sweep_ref`는 건드리지 않는다 — 진입가 이동만으로 R 기하가 타이트해진다(스펙 §3 그대로).

### trade row 추가 컬럼
`h1_refined`(bool) · `h1_overlap_frac`(float) · `zone_low_pre` · `zone_high_pre`(refine 전 H4 존) · `ob_mode`

---

## 🚀 실행 (4런: strict/engulf × on/off)

```bash
# strict
OB_MODE=strict USE_H1_REFINE=0 STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=out_strict_base   python -m smc_stage4d
OB_MODE=strict USE_H1_REFINE=1 STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=out_strict_refine python -m smc_stage4d
# engulf
OB_MODE=engulf USE_H1_REFINE=0 STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=out_engulf_base   python -m smc_stage4d
OB_MODE=engulf USE_H1_REFINE=1 STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=out_engulf_refine python -m smc_stage4d
```

---

## 🔬 판정 규칙 (이번 세션 합의)

- **`close_at_end` 제외(실현 기준)** 로 평가.
- **avgR 부트스트랩 95% CI** 로 판단 — in-sample PF 한 끗 금지.
- strict/engulf **승자를 in-sample PF로 고르지 말 것**(선택 편향) — CI/OOS로.
- `refined=True` 거래만 따로 떼서 refine이 실제로 R을 개선했나 직접 비교.

`tools/compare_refine.py` 가 4개 `trades.csv`를 받아 위 비교표(실현 PF/avgR/CI, refined-only)를 출력한다.

---

## ✅ 검증

- **룩어헤드 0**: `tests/test_refine_no_lookahead.py` — 3000회 / 미래봉 OHLC·FVG·OB 변조 후 결과 불일치 **0건** / refine 발동 다수.
- **baseline 보존**: `USE_H1_REFINE=0` 은 **동일 조건 pre-edit 패키지와 기존 83컬럼 전부 바이트 동일** → refine OFF 는 완전한 no-op(추가 컬럼만 신규). 검증됨.

> ⚠️ **선재(先在) 비결정성 주의**: 원본 백테스트 자체가 run 조건에 따라 **BNBUSDT 2023-08-01 경계 타이**에서 1트레이드(~0.05%)가 흔들린다(loky/BLAS 부동소수점 추정). 골든=2166 / 현 세션=2165. **제 feature 코드와 무관**하며, on/off 비교는 **같은 세션·조건**에서 수행해 noise 를 상쇄했다. 완전 결정화하려면 `OMP_NUM_THREADS=1` 등 단일스레드 실행 필요(별도 과제).

## 📊 측정 결과 (실현 기준, avgR 부트스트랩 95% CI, B=10000)

| 런 | trades | win% | PF | avgR | avgR 95% CI |
|----|------:|-----:|----:|-----:|------------|
| strict **base**   | 2158 | 47.91 | 0.914 | **-0.011** | [-0.067, +0.046] |
| strict **refine** | 2161 | 50.25 | 1.029 | **+0.070** | [+0.012, +0.128] |
| engulf **base**   | 2462 | 47.03 | 0.823 | **-0.073** | [-0.121, -0.025] |
| engulf **refine** | 2458 | 49.55 | 0.944 | **-0.001** | [-0.050, +0.049] |

**refined=True 거래만**: strict avgR +0.024 CI[-0.053,+0.105] · engulf avgR -0.017 CI[-0.082,+0.052]

### 판정 (합의 규칙대로)
- ✅ **방향성**: refine 는 **두 OB모드 모두 avgR 을 끌어올린다** (strict −0.011→+0.070, engulf −0.073→−0.001; PF 도 동반 상승). 승률도 +2~3%p.
- ⚠️ **통계적 확증은 아직**: on/off 의 **95% CI 가 겹친다**(strict: base_hi +0.046 > refine_lo +0.012) → 우연 배제 못 함. **단서(lead)**이지 증명 아님.
- ⚠️ **refined=True 부분집합**의 CI 가 0 을 가로지름 → "refine 된 거래 자체가 +R" 이라고 단정 못 함. 효과는 존 품질 선별(진입 자체가 줄며 분포 개선)에 더 가까울 수 있음.
- 🚫 in-sample PF(strict_refine=1.029 최고)로 승자 선언 금지 — **OOS/walk-forward 로 확인 필요**(다음 단계).

> **결론**: H1 refine 은 strict·engulf 양쪽에서 **일관되게 우호적 방향**이나, in-sample 95% CI 로는 **확증 미달**. 다음 단계 = OOS 검증 + (효과 확인 시) 연속 가중치 v2.

---

## ⚠️ 한계 / 면책
- refine는 **의도된 동작 변경**(엔트리가 달라짐) — 골든 바이트동일 대상 아님. 효과는 CI로만 판단.
- v1은 이진(겹침 유/무) + 최대겹침 교집합만. 연속 가중치는 효과 확인 후.
- **백테스트·연구 전용**, 투자 조언 아님.
