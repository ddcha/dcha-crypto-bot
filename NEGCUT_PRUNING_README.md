# 손실셋업 가지치기(negcut) 실험 + 수확체감/두더지잡기 — 복귀점

브랜치: `feat/atom-tier-engulf-atr13`. pf12(19셋업)에서 총R<0 손실셋업을 단계적으로 제거하며 진짜 union 게이트로 재측정. **원자 재구성 작업 전 복귀점(checkpoint)** 으로 커밋.

전제: 클린 엔진(`_ls_*` 비멱등 픽스 적용, 커밋 a184611). 각 런은 독립 프로세스 1패스 + 멱등성 assert + 룩어헤드 통과.

## 게이트/baseline
USE_COMBO_UNION=1, COMBO_UNION_JSON=<셋업파일>, OR-of-ANDs(진짜 게이트). matched_setup/n_setups_matched는 사후 라벨.
OB_MODE=engulf, DISP_ATR_MULT=1.3, USE_H1_REFINE=1, HONEST_STAGE=5, risk_mult=1.0.
자본시뮬: 시드500+월250×5(총1750), RISK_PCT=0.01 flat, run_equity(v19b 자본로직 아님).

## 스크립트
- `run_negcut_union.py` — setups_pf12_negcut.json(14셋업) 단일 백테스트 + 자본시뮬 + 멱등 assert + R단위 MDD + 사후값비교.
- `run_negcut2_union.py` — setups_pf12_negcut2.json(12셋업). 전체+역추세(a_trend_align=False) 둘 다 지표 + 셋업별표(IS/MDD_R/총R) + 음수셋업 등장 플래그.
- `run_atom_rawdist.py` — (다음작업) 5원자 raw 분포 + 20%통과 임계 + room 타겟정의 결함진단. ※ 측정 도중 중단(결과 미생성).

## 결과 (진짜 게이트, 클린)
| 파일 | 셋업 | 거래 | PF | IS | OOS | 매년삶 | 자본배수 | MDD_cap |
|---|---|---|---|---|---|---|---|---|
| pf12 | 19 | 1391 | 1.31 | 1.28 | 1.34 | ✓ | 9.45x | −17% |
| **negcut** | 14 | 1368 | 1.31 | 1.24 | 1.37 | ✓ | **8.49x** | −18% |
| **negcut2** | 12 | 1359 | 1.30 | 1.21 | 1.39 | ✓ | **7.12x** | −20% |

negcut2 역추세(a_trend_align=False, 555건): **PF 1.45 / OOS 1.77 / 매년삶 ✓** — 전체보다 강함(엣지가 역추세에 실림).

## 핵심 결론
1. **12셋업도 pf14처럼 약화 안 됨**(OOS 1.39, 매년 생존). pf14(14셋업, OOS 0.90)의 약화는 "개수"가 아니라 "구성" 탓 — negcut은 pf12 손실만 정확히 제거해 견고성 유지.
2. **단, negcut→negcut2 추가 가지치기는 수확체감**: PF 1.31→1.30, **자본 8.49x→7.12x로 오히려 악화**. 순효과 없음.
3. **두더지잡기 변질 확인**: 손실셋업 제거 시 슬롯 재배치로 *다른* 셋업이 음수로 변질.
   - negcut: efficiency+ob+wick(사후 +13R) → −6.2R 변질
   - negcut2: bb_squeeze+ob+pre_total_ge1+pre_total_ge4+room+wick(−1.63R) 새로 음수화 (강도는 약화·수렴)
   - 원인: 셋업 PF는 비고유(경로의존). prune은 복리로 안 좋아지고 ~1.30에서 정체.
4. **권고**: 셋업 가지치기는 negcut(14)에서 멈추는 게 합리적. 다음 유망 방향 = 역추세(a_trend_align) 활용 + 원자 재구성(broad 임계 조정).

## 사후값 대비 (강제대체 점검)
- negcut: 거래 Δ15.3%(>15% 플래그) but PF Δ0.7%·OOS Δ1.3% → 양성 대체(품질 유지).
- negcut2: 거래 Δ15.1% but PF Δ4.2%·OOS Δ8.5%(PF/OOS는 사후값보다 좋음).
→ 거래수만 괴리, 품질은 사후 기대 이상. pf14식 붕괴 아님.

## 다음 작업 (이 복귀점 이후)
원자 재구성: 5원자(wick/volume/fvg/vol_expansion/room) raw 분포로 "20% 통과" 정확 임계 산출 + **room 타겟정의 결함 진단**(현행 pd_high/low=1620봉 극값이라 임계 1.5→2.8에도 81→79%로 거의 안 걸림 의심 → swing/last_pivot 대안과 분포 비교). `run_atom_rawdist.py`로 측정 예정.

(결과 CSV 는 보통 .gitignore 제외지만, 이 복귀점은 negcut/negcut2 trades·summary·breakdown 을 git add -f 로 포함했다.)
