# feat/atom-tier-engulf-atr13 — 12조합 UNION 게이트 (단일 런 조합별 성과)

> **한 번의 백테스트**에서 12개 원자조합이 **모두 매매 가능**하게 한다(어느 조합이든 AND 만족 시 진입).
> 진입한 트레이드에 **매칭 조합 태그(`combos_matched`)** 를 박아, 단일 런 안에서 조합별 성과를 분해한다.
> baseline = **engulf + DISP_ATR_MULT=1.3 + USE_H1_REFINE=1** (고정).
> (※ 13개 따로 돌리는 게 아니라 단일 런 — 단일 포지션 시퀀싱 공유로 현실적·빠름.)

> ⚠️ 패키지 직접 편집 브랜치. `extract_modules.py --write` 금지.

---

## 🔧 변경

- **config.py**: `COMBOS` 12개 dict + `USE_COMBO_UNION` 플래그.
  (`COMBO_KEY` 단일선택 모드도 남겨둠 — 단발 검증용.)
- **simulation.py**:
  - `_combo_union_match(tags)` = 12조합 중 만족(AND)하는 키 리스트.
  - 진입 게이트(SHORT/LONG): `USE_COMBO_UNION` 시 _gtags(정직봉 i-1)로 조합 평가,
    **하나라도 만족하면 진입**, 아니면 skip. 매칭 조합을 `_combos_matched` 에 기록.
  - trade row 에 `combos_matched`("c08|c12" 형태) 컬럼.
- **tools/combo_union_analyze.py**: 단일 union trades.csv → 조합별 subset 성과
  (실현 PF/IS/OOS/avgR/Sharpe/sumR + 자본시뮬 시드500+250×5 + 나머지6) + 룩어헤드 검증.

## 🧪 룩어헤드
- 게이트: 실값 원자를 **정직봉(i-1, HONEST_STAGE=5)** 에서 계산 → 진입 룩어헤드 0.
- 자본엔진: 이벤트 순(진입<입금<청산), 사이징=그 시점 실현자본만. `test_capital_no_lookahead` 통과 강제.

## 🚀 실행 (단일 런)
```bash
OB_MODE=engulf DISP_ATR_MULT=1.3 USE_H1_REFINE=1 USE_COMBO_UNION=1 \
  STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=combo_union_run python -m smc_stage4d
python tools/combo_union_analyze.py combo_union_run
```

## 📊 결과 — 단일 union 런(1,194거래) 조합별 (실현기준, 정렬 OOS_PF)

| combo | n | win% | PF | IS_PF | **OOS_PF** | avgR | sumR | 자본배수 | MDD% | 나머지6 PF |
|-------|--:|----:|----:|----:|-----:|-----:|----:|----:|----:|----:|
| **c02 score+vol+volume+room** | 155 | 58.1 | 1.940 | 1.801 | **2.132** | +0.318 | 49.2 | 1.62× | −4.9 | 2.483 |
| **c09 score+vol** | 236 | 55.1 | 1.587 | 1.416 | **1.793** | +0.252 | 59.6 | 1.71× | −8.9 | 1.894 |
| **c01 score+fvg+vol** | 142 | 54.9 | 1.425 | 1.515 | **1.325** | +0.263 | 37.3 | 1.39× | −4.9 | 1.970 |
| c04 eff+fvg+vol+volume+room | 420 | 51.0 | 1.011 | 1.057 | 0.960 | +0.058 | 24.5 | 1.18× | −19.7 | 1.276 |
| **ALL_union** | 1194 | 51.7 | 1.023 | 1.173 | 0.897 | +0.076 | 91.0 | 2.00× | −26.2 | 1.118 |
| c08★ eff+fvg+vol+volume | 504 | 52.8 | 1.032 | 1.201 | 0.883 | +0.109 | 54.9 | 1.56× | −19.6 | 1.292 |
| c07 eff+fvg+vol+room | 497 | 50.5 | 0.990 | 1.106 | 0.870 | +0.053 | 26.4 | 1.20× | −21.0 | 1.242 |
| c10 eff+fvg+vol | 589 | 52.1 | 1.009 | 1.204 | 0.841 | +0.096 | 56.4 | 1.59× | −21.0 | 1.258 |
| c03 eff+fvg+vol+volume+wick+room | 348 | 50.3 | 0.954 | 1.078 | 0.833 | +0.042 | 14.7 | 1.07× | −23.0 | 1.196 |
| c12 fvg+vol | 1100 | 51.4 | 0.975 | 1.152 | 0.830 | +0.063 | 68.8 | 1.65× | −33.1 | 1.077 |
| c11 fvg+vol+wick | 898 | 51.0 | 0.943 | 1.106 | 0.812 | +0.059 | 53.2 | 1.42× | −38.3 | 1.050 |
| c06 eff+fvg+vol+wick | 489 | 51.7 | 0.989 | 1.217 | 0.794 | +0.094 | 45.9 | 1.44× | −23.9 | 1.221 |
| c05 eff+fvg+vol+volume+wick | 421 | 52.3 | 0.974 | 1.250 | 0.752 | +0.097 | 40.8 | 1.37× | −23.3 | 1.219 |

룩어헤드: ALL_union 136,750건 검증 / **0불일치 통과** ✅.

### ⚠️ 핵심 발견 — 사후분할 ↔ 실제 게이트 정반대 (과적합 폭로)
- 스펙이 **최강이라던 eff/fvg/vol 계열(c08★/c10/c03/c05/c06/c11/c12)** — 사후분할 OOS_PF 2.0~2.7 → **실제 게이트선 OOS_PF 0.75~0.96 으로 붕괴**. 사후 수치는 과적합 환상이었음.
- **유일 생존 = score13 기반 (c02/c09/c01)**: c02(score+vol_exp+volume+room)가 **OOS_PF 2.13, 나머지6 2.48, MDD −4.9%** 로 최강. c09·c01도 OOS>1.3.
- **union 전체(OOS 0.897)는 engulf+atr1.3 baseline(OOS≈, PF 1.146)보다 나쁨** — eff/fvg/vol 다수가 희석. 즉 "12개 다 켜기"는 손해.
- 표본 주의: score 계열은 n 작음(142~236). modest 엣지지만 **OOS·나머지6가 함께 살아남은 건 c02/c09/c01 뿐**.

### 판정
- ✅ **채택 후보: c02 (그다음 c09)** — 실제 게이트 후에도 OOS_PF≥1.8 & 나머지6≥1.9 & MDD 양호.
- 🚫 eff/fvg/vol 계열·union 전체: 실제 게이트 OOS<1 → **컷**.
- 다음: c02/c09 단독 게이트로 walk-forward(연도별) + 데모 forward 확인 후 확정.

## 🔬 판정
- 조합 subset = `combos_matched` 에 그 키 포함된 트레이드. 조합들은 중첩(예: c08⊂c12).
- 정렬 OOS_PF→sumR. 사후분할 대비 OOS 유지율로 채택/컷.
- 단일 역사구간 in-sample — 데모 forward 전 확정 아님. **투자 조언 아님.**

---

## 🔁 COMBO_UNION_FIX 검증 + atom-tier 자본시뮬 (후처리, `tools/combo_tier_capital.py`)

수정 스펙 4개 진단 검증:
- **#1 refine: 오인** — refine 이미 ON(`h1_refined` 463/1204=**38.5%**). 스펙이 본 `entry_refined`(0)은 옛 삭제된 refine 의 죽은 컬럼.
- #2/#3/#4(atom-tier S1/S2/A · mult 2.0/1.3/1.0 · 시드500+250×5)는 **trade set/R 을 안 바꾸는 자본 후처리** → 엔진 재실행 없이 적용. §6 체크리스트 7개 전부 OK(h1_refined·atom_tier·mult·balance≈500·phase·combos·룩어헤드0).

**atom-tier 결과 (assign_tier = fvg/vol/eff/volume):**
| tier | mult | n | OOS_PF | avgR |
|------|----:|--:|-----:|-----:|
| S1 (fvg+vol+eff+volume) | 2.0× | 504 | **0.883** | +0.109 |
| S2 (fvg+vol+eff) | 1.3× | 85 | 0.723 | +0.017 |
| A (fvg+vol⊕eff) | 1.0× | 511 | 0.805 | +0.024 |
| **BASE (비fvg=score조합; 스펙은 제외)** | 1.0× | 94 | **2.090** | **+0.237** |

### ⚠️ 핵심 — 티어 철학이 거꾸로
- spec 이 **2.0× 로 키우라는 S1(fvg+vol+eff+volume) 이 OOS_PF 0.883(손실)**. fvg 기반 전 티어 OOS<1.
- spec 이 **제외**하는 비-fvg(score조합 c02/c09)가 **OOS_PF 2.09 로 유일한 엣지** — 버려짐.
- 티어 적용(literal): $4097(2.34×)·CAGR 35% 지만 **손실 티어를 2배 베팅 → MDD −42%**.
- 결론: **edge 축은 fvg 가 아니라 score13.** 자본/티어 모델은 edge 순위를 못 바꾼다(R-기반 동일).
- 권고: assign_tier 를 **score 기반**으로 재정의하거나, **c02/c09 단독 게이트** 로 진행.
