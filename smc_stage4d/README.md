# smc_stage4d — Stage 4D Atomic Decomposition (모듈판)

> 단일 파일 `smc_crypto_stage4d_atom_gate (1).py` (4,159줄)을 **동작 100% 동일**하게
> `smc_stage4d/` 패키지(10개 모듈)로 분리한 결과물입니다.
> **출력 CSV 13개 전부 바이트 동일**(diff -q + md5)으로 검증되었습니다.

---

## 📌 한눈에 보기

| 항목 | 내용 |
|------|------|
| **목적** | Tier/RP 복합 변수를 **12개 atomic 태그**로 분해해 각 원자의 순수 기여도 측정 |
| **핵심 원칙** | 모든 risk multiplier = **1.0 고정** (순수 signal 품질만 비교), **MIN_SCORE 7.5** 만 유일 게이트 |
| **대상 코인 (9종)** | BTC · ETH · SOL · XRP · DOGE · AVAX · LINK · BNB · ADA |
| **데이터** | Binance Vision 월별 klines (futures/um), `STAGE4D_DLCACHE` 로컬 parquet 캐시 |
| **산출물** | 기본 5 + 분석 8 = **CSV 13개** |
| **검증** | 원본 골든 런과 13/13 CSV **바이트 동일** |

> ⚠️ 이 패키지는 **연구 실험용**입니다. Return 최적화가 아니라 **원자 기여도 매핑**이 목적입니다.

---

## 🧠 실험 개요 (원본 헤더 보존)

Stage 4C 에서 발견한 패턴 — *"Tier 엔진은 품질 필터가 아니라 risk scaler 였다 / tier 단독이 가장 약했다(PF 1.29) / RP0 이 숨은 최강(PF 6.22) / SWEEP+VOLUME 이 진짜 alpha"* —
을 검증하기 위해, 복합 변수를 원자 단위로 분해합니다.

**12 atomic 태그**
- Tier 구성 (5): `a_pre_total_ge4`, `a_sweep_count_2_4`, `a_score_ge13`, `a_wick_le_q1`, `a_pre_total_ge1`
- RP 구성 (5): `a_trend_align`, `a_mss`, `a_fvg`, `a_overlap`, `a_room`
- Entry signal (2): `a_sweep`, `a_volume`

**고정 설정** — `tier_mult=1.0`, `rp_mult` 곱 제거, `risk_multiplier=1.0`, cap=3.0 고정, Tier D skip 제거(모든 거래 수용), 게이트는 MIN_SCORE 7.5 만.

---

## 🚀 실행 방법

```bash
pip install pandas numpy matplotlib requests joblib psutil pyarrow

# 패키지로 실행 (data_cache 의 parquet 를 재사용해 오프라인 실행)
STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=stage4d_outputs python -m smc_stage4d
```

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `STAGE4D_DLCACHE` | (없음) | 지정 시 `{심볼}_{interval}.parquet` 캐시 사용/저장 → 네트워크 없이 결정론적 실행 |
| `STAGE4D_OUTDIR` | `stage4d_outputs` | CSV 출력 폴더 |
| `MIN_SCORE` | `7.5` | 진입 문턱 (env 로 6.0~9.0 스윕) |
| `HONEST_STAGE` | `5` | 정직봉 상속 (룩어헤드 0). config 로드 시 setdefault |

> ✅ 첫 줄 `[ATOM GATE] mode=OFF HONEST_STAGE=5` 를 육안 확인하세요.

---

## 📂 산출물 (13개 CSV)

| 파일 | 내용 |
|------|------|
| `stage4d_trades.csv` | 개별 거래 + 12 atomic 플래그 |
| `stage4d_equity.csv` / `_monthly.csv` / `_skipped.csv` | 자산곡선 / 월별 / 스킵 |
| `stage4d_overall_summary.csv` | 종합 성과 (PF·승률·MDD·Return) |
| `atom_solo_effect.csv` | [1] 각 원자 PASS vs FAIL 효과 |
| `sweep_vol_pivot.csv` | [2] **SWEEP+VOL 기준 원자 추가 효과 (핵심)** |
| `tier_decomposition.csv` | [3] Tier 5 원자 기여도 |
| `rp_decomposition.csv` | [4] RP 5 원자 기여도 + side |
| `rp_level_analysis.csv` | [5] RP0 / RP1 / RP2+ 세분 |
| `side_x_atom.csv` | [6] LONG/SHORT × 12 원자 |
| `top_combo_analysis.csv` | [7] **2-3 원자 조합 brute-force PF 상위 30 (핵심)** |
| `tier_original_vs_atoms.csv` | [8] 원본 Tier 판정의 원자 구성 |

---

## 🏗️ 코드 구조

의존 방향(순환 없음):
`config → utils → data → indicators → tiers → structures → filters → simulation → reporting → __main__`

```
smc_stage4d/
├── config.py        모든 상수·테이블 단일 소스 (404줄) ★
├── utils.py         순수 헬퍼 (스톱·RR·overlap·포지션·페이즈)
├── data.py          Binance Vision 수집 + D1 추세 + 입금 스케줄
├── indicators.py    MSS/FVG/OB/PD/Pivot/CHoCH/H4 market state/sweep flag
├── tiers.py         classify_tier_v19b_rp_boost
├── structures.py    존·신선도·run potential·지표 파이프라인
├── filters.py       진입 필터 + 12원자 태그 계산
├── simulation.py    체결·시뮬레이션 엔진 (generate_candidates / simulate_scenario) ★
├── reporting.py     월별 손익·은퇴월·요약 리포트
└── __main__.py      실행 오케스트레이션 (병렬 다운로드→지표→후보→백테스트→분석)
```

> ⚠️ **이 모듈들은 원본에서 자동 추출됩니다.** 직접 수정하지 말고 원본
> `smc_crypto_stage4d_atom_gate (1).py` 를 고친 뒤
> `python tools/extract_modules.py --write` 로 재생성하세요.
> 추출은 라인범위 단위라 **주석(◆ 해설)까지 verbatim 보존**됩니다.

---

## 🔬 동작 동일성 검증

```bash
# 골든(원본) — 같은 캐시로 1회
STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=_golden_out python "smc_crypto_stage4d_atom_gate (1).py"
# 모듈판 — 같은 캐시로 1회
STAGE4D_DLCACHE=data_cache STAGE4D_OUTDIR=_module_out python -m smc_stage4d
# 바이트 비교
for f in _golden_out/*.csv; do diff -q "$f" "_module_out/$(basename "$f")"; done
```
→ **13/13 CSV 바이트 동일** 확인.

---

## ⚠️ 핵심 보존 처리 (notebook 잔재 함정)

원본은 노트북에서 추출된 단일 파일이라 다음 함정이 있었고, 모듈화 시 정직하게 처리했습니다.

1. **중간 재정의 상수 14개** — `H4_PIVOT_SWING_LEN` 등 H4 구조 상수가 초기 블록(예: `3`)과
   실행부 셀(예: `30`)에서 **다르게 두 번 정의**됩니다. 함수는 셀 이후 호출되어 **최종값**을 봅니다.
   → 재정의 라인을 원본 순서 그대로 `config.py` 끝에 모아 **최종 실효값이 단일 소스로 승리**하게 했습니다
   (`USE_VOLUME_FILTER` 최종 `False`, H4 swing=30/mss=80/ob=15/pd=1620/state=360/zone=30 등).
   이로써 **multiprocessing 워커가 부모의 재정의를 못 보는 문제**도 동시에 해결됩니다.
2. **`if __name__` 가드 부재** — 원본은 전체가 top-level 실행. 패키지는 실행부를 `__main__.py` 로 옮겨
   `python -m smc_stage4d` 로 구동합니다 (loky 워커는 config 만 re-import → 배너만 중복 출력, CSV 영향 없음).
3. **노트북 매직** (`get_ipython()`, `%pip`) — `try/except NameError` 로 감싸져 일반 실행에서 무해. 보존.

---

## 📜 한계 / 면책

- **백테스트·연구 전용** — 실거래 주문 집행 없음.
- 과거 성과가 미래 수익을 보장하지 않습니다. **투자 조언이 아닙니다.**
