# ddcha-crypto-bot

> SMC(Smart Money Concepts) 기반 **9개 암호화폐 멀티-타임프레임 백테스트 엔진**
> — `conservative_mtf_fill_주석판.py` (공식 기준 코드, Stage 4L)

암호화폐 선물(USDT-M) 9종에 대해 **스마트 머니 컨셉(SMC)** 매매 규칙을 적용하고,
적립식 입금·리스크 배분·다단계 필터를 거쳐 장기 성과를 시뮬레이션하는 단일 파일 백테스터입니다.

---

## 📌 한눈에 보기

| 항목 | 내용 |
|------|------|
| **전략 계보** | Stage 4L (tier 재배분) + H1 CHoCH hard gate (v3) + MTF fill |
| **대상 코인 (9종)** | BTC · ETH · SOL · XRP · DOGE · AVAX · LINK · BNB · ADA |
| **타임프레임** | 구조 판정 = **H4**, 추세 = **H1 CHoCH**, 체결 = **MTF fill (15m / 1h / 4h)** |
| **데이터 소스** | [Binance Vision](https://data.binance.vision) 공개 월별 klines (futures/um) |
| **검증 성과 (15m fill)** | PF **2.666** · 1,310거래 · 승률 **61.8%** · MDD **-11.15%** |
| **기간** | 2022-01 ~ (LOOKBACK 3년), Luna/FTX 붕괴 포함 52개월 중 양수월 92.3% |

> ⚠️ H4 fill 기준 PF는 3.79까지 나오지만 이는 **낙관 편향 30~42%** 가 섞인 값입니다.
> **실전 기대값은 15m fill** 결과를 기준으로 보세요.

---

## 🧠 전략 개요

이 봇은 기관 매매 흔적(유동성 사냥·구조 전환·미체결 주문 영역)을 추종하는 SMC 철학을 코드화합니다.

### 1) 다단계 타임프레임 (MTF)
- **H4 (4시간)** — 시장 구조물 생성: MSS, CHoCH, FVG, Order Block, Premium/Discount
- **H1 (1시간)** — 추세 판정을 후행 EMA 정렬 대신 **CHoCH state(즉시 반응)** 로 결정
  (반대 방향 CHoCH가 나올 때까지 추세 유지 — SMC 정통 방식)
- **Fill TF (15m/1h/4h)** — 실제 진입/청산 체결을 더 정밀한 봉으로 시뮬레이션

### 2) 진입 시그널 구성
- 구조물 기반 **존(zone)** 진입 + 신선도(freshness) 검증
- **12개 atomic 태그** + **WIN69 union** 조건
- 필터 그룹: 거래량 스파이크 · ATR · 풀백 깊이 · (옵션) 유동성 sweep / D1 추세

### 3) 리스크 배분 (Tier 시스템)
거래마다 다음 곱셈식으로 리스크%를 산출합니다:

```
risk_pct = base × tier_mult × rp_mult × stage4j_mult × sentiment_mult × risk_multiplier
```

| Tier | 배수 | 비고 |
|------|------|------|
| `ALPHA_MAX` | 2.5× | 안전 검증된 최상위 |
| `ALPHA_HIGH` | 1.5× | 시스템 핵심 엔진 |
| `ALPHA_MED` | LONG 0.6× / SHORT 1.0× | 약점 구간 강등 |
| `SWEEP_GEM` | 4.0× | Edge Ratio 4.76, 매우 안전 |
| `SWEEP_ROOM_FVG / ROOM_ONLY` | 1.0× | + Stage 4J extra mult |
| `COMPLETE_OUT / SKIP_MSS` | skip / 0 | 진입 차단 |

### 4) Sentiment + Momentum 부스터 (미래참조 X)
직전 7일 LONG/SHORT RP 격차로 **시장 심리**를 측정하고, 7~14일 전 대비 변화로 **가속도**를 잡아 진입을 가감합니다.

- **BOOST 패턴 (4종)**: TopReversal · BottomReversal · TrendStart_L · TrendStart_S
- **CUT 패턴 (3종)**: NeutStable_S · NeutFalling_S · ShortStable_L (0.5×)

### 5) 청산 플랜
- 부분 익절 1R / 2R / 3R + **러너(runner)** 잔량 트레일링
- BE(본전) 이동 · 시퀀스 러너 보호 · expansion 국면 시 더 공격적 TP

---

## ⚙️ 시나리오

부스터 강도에 따라 3개 시나리오를 한 번에 백테스트합니다.

| 시나리오 | BOOST 배수 | CUT 배수 | 성향 |
|----------|-----------|----------|------|
| `BOOST15` | 1.5× | 0.5× | 가벼움 **(공식 baseline)** |
| `BOOST25` | 2.5× | 0.5× | 중간 |
| `BOOST35` | 3.5× | 0.5× | 공격적 |

---

## 🚀 실행 방법

### 요구 사항
```bash
pip install pandas numpy matplotlib requests
# (선택) 병렬 가속: pip install joblib
```
- Python 3.9+
- 첫 실행 시 Binance Vision에서 월별 klines를 다운로드합니다(네트워크 필요).

### 실행
```bash
# 기본 (FILL_TF=1h)
python conservative_mtf_fill_주석판.py

# 15m fill 권장 — 실전 기대값에 가장 근접
FILL_TF=15m python conservative_mtf_fill_주석판.py
```

### 환경변수
| 변수 | 기본값 | 설명 |
|------|--------|------|
| `FILL_TF` | `1h` | 체결 타임프레임 (`15m` / `1h` / `4h`) |
| `H1_FILL_TIE_BREAK` | `heuristic` | 동일봉 체결 우선순위 (`heuristic` / `pessimistic`) |
| `USE_H1_FILL` | `auto` | `0` 이면 H4 fill 강제 |

> ✅ **실행 전 체크리스트**
> 1. 콘솔 첫 줄 `[MTF-FILL] FILL_TF=...` 를 **육안 확인**
> 2. 결과 검증: `trades.csv` 의 `hold_bars` 중앙값 (H4≈9 / 15m≈수백)
> 3. ⚠️ 결과 CSV 파일명이 TF와 무관 → **TF 바꿔 재실행 시 이전 결과를 덮어씀** (미해결 이슈 #5)

---

## 📂 산출물

모든 결과는 `stage4l_redist_outputs_v3_conservative/` 폴더에 저장됩니다.

| 파일 | 내용 |
|------|------|
| `stage4l_boost{15,25,35}_out_*_trades.csv` | 개별 거래 로그 (+ SL 취약성 5개 컬럼) |
| `..._equity.csv` | 자산 곡선 (KRW 환산, drawdown 포함) |
| `..._monthly.csv` | 월별 손익 / 3개월 롤링 |
| `..._overall_summary.csv` | 시나리오별 종합 성과 |
| `sentiment_distribution_stage4l_*.csv` | sentiment cell 별 PF 분포 |
| `tier_stage4l_*_distribution.csv` | Tier 별 성과 분포 |
| `stage4l_comparison_summary.csv` | **3 시나리오 비교 요약** |

**`trades.csv` SL 분석 컬럼**: `sl_dist_pct`, `worst_low/high_during_hold`,
`max_adverse_excursion_pct`, `sl_proximity_pct` (100 = SL 도달)

---

## 💰 자본 모델

| 파라미터 | 값 |
|----------|-----|
| 초기 자본 | 300만 KRW |
| 월 적립 | 200만 KRW × 5개월 |
| 환율 | 1,350 KRW/USDT |
| 수수료 | 0.05% (편도) |
| 최대 명목 노출 | 자본의 3배 |
| "퇴사" 목표 | 3개월 롤링 월수익 1,000만 KRW |

---

## 🏗️ 코드 구조

원본은 **5,271줄 단일 파일**(`conservative_mtf_fill_주석판.py`)이며, 동일한 로직을
**`smc/` 패키지(10개 모듈)** 로 분리한 모듈판을 함께 제공합니다. 둘은 **동작이 100% 동일**합니다
(아래 *동작 동일성 검증* 참조).

### `smc/` 패키지 (권장)

```
smc/
├── config.py        모든 상수·테이블·튜닝값 (단일 소스)
├── utils.py         순수 헬퍼 (스톱·RR·overlap)
├── data.py          데이터 수집 + 입금 스케줄 (Binance Vision)
├── indicators.py    지표·구조물 1차 (MSS/FVG/OB/PD/CHoCH, H1 CHoCH 추세)
├── structures.py    존(zone)·신선도·run potential·지표 파이프라인
├── filters.py       진입 필터 + 거래 태그
├── tiers.py         Tier 분류·리스크 배수·Sentiment 부스터
├── simulation.py    체결·시뮬레이션 엔진 (핵심)
├── reporting.py     리포트·차트
└── __main__.py      실행 오케스트레이션 (BOOST15/25/35 루프)
```

의존 방향(순환 없음): `config → utils → {data, indicators} → structures → filters → tiers → simulation → reporting → __main__`

```bash
python -m smc              # 패키지로 실행 (기본 FILL_TF=1h)
FILL_TF=15m python -m smc  # 15m fill 권장
```

> ⚠️ `smc/` 모듈은 원본에서 **자동 추출**됩니다. 직접 수정하지 말고 원본(`conservative_mtf_fill_주석판.py`)을
> 고친 뒤 `python tools/extract_modules.py --write` 로 재생성하세요. 추출은 라인범위 단위라 **주석(◆ 해설)까지 그대로 보존**됩니다.

### 동작 동일성 검증
모듈판이 원본과 **바이트 단위로 동일한 결과**를 내는지 백테스트 출력으로 검증합니다
(BOOST15/25/35 × trades/equity/monthly/summary/skipped/tier/sentiment = **22개 CSV 전부 일치**).

> 📝 원본 상단의 `◆` 로 시작하는 블록은 로직 변경 없이 추가된 **해설 주석**입니다
> (2026-06-12 주석판). 모듈판도 이 주석을 그대로 가져갑니다.

---

## ⚠️ 주의 / 알려진 한계

- **백테스트 전용** — 실거래 주문 집행 기능 없음. 과거 데이터 기반 시뮬레이션입니다.
- H4 fill 성과는 낙관 편향이 큽니다. **15m fill 기준으로 판단**하세요.
- 결과 CSV가 `FILL_TF` 별로 분리 저장되지 않습니다 (이슈 #5). TF 바꿔 돌릴 땐 폴더 백업 권장.
- 과거 성과가 미래 수익을 보장하지 않습니다. **투자 조언이 아닙니다.**

---

## 📜 라이선스

별도 명시 전까지 **All rights reserved** (비공개 연구 코드).
