# feature/gate-tighten — sweep/displacement/MSS 엄밀화 파라미터 스윕

> **목표**: 존 생성의 *전제 관문*(sweep·displacement·MSS)을 **env로 조절**해
> "관문을 엄밀히 하면 더 좋은 존을 고르나, 표본만 깎나"를 측정. 모든 변경은 **H4 게이트에만**.
> **기본값=현행 → baseline 보존(회귀 0 확인됨).** `GATE_TIGHTEN_SPEC.md` 구현.

> ⚠️ 이 브랜치도 패키지를 직접 편집한다(자동추출본 아님). **`extract_modules.py --write` 금지.**
> `feature/h1-refine-zone` 에서 분기 → refine 코드 포함, `USE_H1_REFINE=1` 고정으로 스윕.

---

## 🔧 변경 (H4 게이트 전용, H1 보조계산 불변)

| 관문 | env (기본=현행) | 배선 위치 |
|------|----------------|-----------|
| sweep 봉수 | `SWEEP_RECENT_N=10` | `structures.py` build_structures `recent_sweep_n` (H1 apply_sweep_flags 10 유지) |
| displacement ATR | `DISP_ATR_MULT=0.90` | `structures.py` H4 `apply_displacement(...)` (H1 호출 기본값 유지) |
| displacement body | `DISP_BODY_RATIO=0.45` | 〃 |
| MSS 모드 | `MSS_MODE=legacy` | `structures.py` apply_choch 직후 `choch`면 bull/bear_mss ← bull/bear_choch |

`config.py` 에 env 4개 추가. `simulation.py` trade row 에 `sweep_recent_n/disp_atr_mult/disp_body_ratio/mss_mode` 자기문서화 컬럼.

---

## 🧪 룩어헤드 검증

- **sweep/displacement**: `rolling(N).max().shift(1)`·봉 자체 값만 → 안전(윈도/임계값만 변경).
- **MSS=choch**: `apply_choch`는 `last_pivot_high/low`(apply_pivots)에 의존. 분석상 `last_pivot`은
  `lookup_bar=i-swing_len`만 보므로 미래봉 무관(causal). **변조-불변 테스트로 실증**:
  `tests/test_choch_mss_no_lookahead.py` — 800회 / entry봉 이후 OHLC 전부 변조 / 불일치 **0건** → 룩어헤드 0. ✅

---

## 🚀 실험 설계 (OB(strict/engulf) × 한 축씩, rest-6 CI 판정)

- **OB 살림**: strict·engulf **양쪽**에서 같은 스윕 → OB 정의에 무관하게 먹히는 축만 채택.
- **고정**: `USE_H1_REFINE=1`(이미 +효과) + 캐시 공유.
- **금지**: 풀그리드(과적합). OB별로 **한 축만** 바꾸고 나머지는 그 OB baseline 고정.

| 축 | baseline | 테스트값 |
|----|----------|----------|
| sweep | 10 | 30, 50 |
| disp ATR | 0.90 | 1.3, 1.5, 1.7 |
| disp body | 0.45 | 0.6, 0.75 |
| MSS | legacy | choch |

OB당 (base 1 + 변형 8)=9런 × 2 OB = **총 18런** → `gate_sweep_runs/{ob}_{variant}/`.

```bash
bash tools/run18 (스크립트 참조)   # USE_H1_REFINE=1 STAGE4D_DLCACHE=data_cache 고정
python tools/compare_gate.py        # OB별, 각 변형 vs base, 전체9+나머지6 avgR 95% CI
```

### 판정 규칙
- 실현(close_at_end 제외) **avgR + 95% 부트스트랩 CI**. in-sample PF 로 승자 금지.
- **strict·engulf 둘 다에서 같은 방향으로 개선**되는 축만 채택.
- 나머지6(코어3 제외) 관점 병행 — 대형코인 dominance 배제.

---

## 📊 측정 결과 (실현기준, avgR 95% 부트스트랩 CI, 각 변형 vs 같은 OB의 base)

### 핵심: displacement ATR 문턱 상향이 유일한 일관 개선 축 ✅

**전체 9코인 avgR (base → 변형)**
| 변형 | strict | engulf |
|------|--------|--------|
| **base** | 0.070 | −0.001 |
| sweep30 / 50 | 0.048 / 0.055 ↓ | 0.016 / 0.019 ~ |
| **atr 1.3** | **0.090** ↑ | **0.115** ↑ CI분리[+0.052,+0.181] |
| **atr 1.5** | **0.079** ↑ | **0.113** ↑ |
| atr 1.7 | 0.085 ↑ | 0.088 ↑ |
| body 0.6 / 0.75 | 0.053 / 0.043 ↓ | 0.074 / 0.047 ↑ (불일치) |
| MSS choch | 0.058 ↓ | 0.016 ~ |

**나머지6(코어3 제외)에서도 동일 패턴**: atr 1.3/1.5 가 strict(0.124/0.131) · engulf(0.152 CI분리 / 0.156) 모두 base 대비 상향. PF 도 동반 상승(engulf atr 1.3: 0.944→1.146).

### 판정 (합의 규칙: strict·engulf 둘 다 같은 방향만 채택)
- ✅ **`DISP_ATR_MULT` 상향(1.3~1.5)이 유일한 채택 후보** — strict·engulf, 전체9·나머지6 **네 관점 모두에서 avgR↑·PF↑**, engulf 에선 **95% CI가 base 위로 분리**(우연 아님 단서 강함). "displacement = 진짜 임펄스 확인" 가설 **지지**. 표본도 충분(atr13: 1500~1700건).
- ❌ **sweep 봉수**: strict 에선 오히려 ↓, 표본만 깎음 → 기각.
- ❌ **disp body**: strict↓ / engulf↑ 방향 불일치 → 기각.
- ❌ **MSS choch**: 방향 불일치·미미 → 기각.
- ⚠️ atr 1.7 은 개선폭이 1.3/1.5 와 비슷하나 표본을 더 깎아(933/1029) CI 넓음 → **1.3~1.5 가 sweet spot**.

> **결론**: 게이트 엄밀화 중 **displacement ATR 문턱(0.9→1.3~1.5)** 만이 "더 좋은 존을 고른다"가 확인됨(나머지는 표본만 깎음). **다음 단계 = atr 1.3/1.5 OOS/walk-forward 재확인**, 그 후 채택.

---

## ✅ 검증 / 한계
- **회귀 0**: env 없이(전부 기본값) = 기존 baseline 과 기존 컬럼 **바이트 동일**(완전 no-op). 확인됨.
- 선재 비결정성(원본, BNBUSDT 2023-08-01 ~1트레이드)은 on/off 동일세션 비교로 상쇄.
- **백테스트·연구 전용**, 투자 조언 아님. in-sample 결과 → 채택 축은 OOS 재확인 필요.
