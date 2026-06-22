# v1.9_REALISTIC 실전 배포 가이드

**이식 기반:** 백테스트 v1.9_BASELINE_REALISTIC 검증 결과
- Return 38,694% | PF 8.723 | MDD -4.90% | Win 75.62% | Trades 640
- v1.9_BASELINE (원본 40,776%) 대비 -5% Return, MDD 개선

**적용된 변경 3가지:**
1. Tier 우선 정렬 (tier_mult_final 내림차순)
2. Tier 일괄 계산 (evaluate_zones_at_current_time 함수 신규)
3. compute_pre_entry_confluence / compute_wick_ratio_5 에 exclude_recent_h1 파라미터 추가

**실전 엔진에서 변경 없는 것:**
- v1.9b 티어 시스템 (S/A/B/C/D × 3.0/1.5/0.8/0.7/skip)
- v1.9g RP Boost 테이블
- S/A cap free (999.0)
- Phase A/B 자동 전환
- Global risk multiplier (패널 조절)
- Refine 코드 (실전은 current_price 사용하므로 죽은 코드로 남음)

---

## 📦 변경된 파일

| 파일 | 변경 내용 |
|---|---|
| `config.py` | `USE_TIER_PRIORITY_SORT=True`, `EXCLUDE_RECENT_H1_FOR_TIER=0` 추가 |
| `strategy_engine.py` | evaluate_zones_at_current_time 신규 함수, generate_entry_signal 리팩토링 |

**나머지 파일 변경 없음:** main.py, control_panel.py, settings_store.py, state_store.py, exchange_bybit.py, log_store.py

---

## 🚀 배포 순서

### Step 1: 서버 접속 + 현재 상태 백업

```bash
# SSH 접속
ssh linuxuser@158.247.231.108

cd /home/linuxuser/bybit_bot

# 현재 상태 백업 (타임스탬프 포함)
TS=$(date +%Y%m%d_%H%M%S)
tar -czf ~/backup_before_v19realistic_${TS}.tar.gz \
    --exclude='venv' --exclude='__pycache__' --exclude='*.log' \
    /home/linuxuser/bybit_bot/

ls -la ~/backup_before_v19realistic_${TS}.tar.gz
```

### Step 2: 서비스 중지

```bash
sudo systemctl stop bybit-bot.service
sudo systemctl stop control-panel.service

# 프로세스 완전 종료 확인
sleep 2
ps aux | grep -E "bybit_bot|streamlit" | grep -v grep
```

### Step 3: 파일 업로드

로컬에서:
```bash
scp -r server_patch_v19realistic linuxuser@158.247.231.108:/tmp/
```

서버에서:
```bash
cd /home/linuxuser/bybit_bot

# 파일 교체
cp /tmp/server_patch_v19realistic/config.py ./config.py
cp /tmp/server_patch_v19realistic/strategy_engine.py ./strategy_engine.py
cp /tmp/server_patch_v19realistic/verify_v19realistic.sh ./verify_v19realistic.sh

# __pycache__ 정리 (이전 컴파일 결과 제거)
rm -rf __pycache__
```

### Step 4: 검증 스크립트 실행

```bash
cd /home/linuxuser/bybit_bot
bash verify_v19realistic.sh
```

**예상 출력:**
```
[1/5] 문법 검증...
  [OK] config.py: 132 lines
  [OK] strategy_engine.py: 1773 lines

[2/5] Config 값 확인...
  [OK] USE_TIER_PRIORITY_SORT = True
  [OK] EXCLUDE_RECENT_H1_FOR_TIER = 0
  [OK] RP_TIER_MULT_TABLE, MAX_NOTIONAL_MULT_SA_FREE, RISK_MULTIPLIER_DEFAULT 정상

[3/5] 주요 함수 import 체크...
  [OK] evaluate_zones_at_current_time 함수 존재
  [OK] exclude_recent_h1 파라미터 모두 존재

[4/5] Notional cap 동작 확인...
  [OK] S/A tier = 999.0 (cap free)
  [OK] B/C tier = 3.0

[5/5] Settings store 읽기 테스트...
  [OK] risk_multiplier = 1.0

✅ ALL CHECKS PASSED
```

**모든 단계 [OK] 통과해야 다음 진행. 하나라도 [ERR] 있으면 중단.**

### Step 5: 서비스 재시작

```bash
sudo systemctl start bybit-bot.service
sudo systemctl start control-panel.service

# 상태 확인
sleep 3
sudo systemctl status bybit-bot.service --no-pager -l | head -20
sudo systemctl status control-panel.service --no-pager -l | head -10
```

### Step 6: 로그 모니터링

```bash
# 초기 로그 5분 정도 관찰
sudo journalctl -u bybit-bot -f --since "1 minute ago"
```

**확인할 것:**
- Engine 정상 시작 ("Engine started" 또는 유사 메시지)
- 에러/예외 없음
- 첫 루프 완료 (60초 내)
- 심볼별 데이터 수집 정상 (BTC/ETH/SOL/XRP/DOGE/AVAX/LINK)

### Step 7: 패널 접속 확인

```
http://158.247.231.108:8501
```

확인 항목:
- 패널 정상 렌더링
- Active Zones 표시
- Global Risk Multiplier 표시 (기본 1.0)
- Effective Risk Sum 카드 정상

---

## 🔍 배포 후 관찰 포인트 (1~2주)

### 1. Tier 분포
- 실전 진입 로그에서 `tier` 필드 수집
- S/A 비율 확인 (백테스트는 S 20.6%, A 30.8% 였음)

### 2. Entry 위치
- Current_price 체결가가 zone 어느 위치인지
- Zone 하단/중간/상단 분포 확인
- 백테스트 fill_entry 와 비교

### 3. Tier 우선 정렬 효과
- 여러 zone 동시 touched 되는 케이스 로그 추적
- 실제로 tier S/A 가 우선 선택되는지 확인

### 4. 예상 Return
- 백테스트 REALISTIC = 38,694% (3년, risk×1.0)
- 실전 기대치 = 이보다 약간 낮을 것 (slippage, 놓치는 진입)
- Balance 추이 관찰

---

## 🚨 롤백 시나리오

### 경우 1: 검증 스크립트 실패

```bash
# 백업에서 복원
cd /home/linuxuser/bybit_bot
tar -xzf ~/backup_before_v19realistic_${TS}.tar.gz -C / --strip-components=0

# 서비스 재시작
sudo systemctl start bybit-bot.service
sudo systemctl start control-panel.service
```

### 경우 2: 배포 후 심각한 에러

```bash
# 서비스 중지
sudo systemctl stop bybit-bot.service

# 이전 파일로 복원
cd /home/linuxuser/bybit_bot
cp /tmp/server_patch_v19baseline/config.py ./  # 또는 백업에서
cp /tmp/server_patch_v19baseline/strategy_engine.py ./
rm -rf __pycache__

# 서비스 재시작
sudo systemctl start bybit-bot.service
```

### 경우 3: 원하는 동작 아님 (성능 저하 등)

config.py 에서 스위치 하나만 끄고 부드럽게 되돌리기 가능:

```python
# 기존 eff_score 우선 정렬로 복귀
USE_TIER_PRIORITY_SORT = False
```

또는:
```python
# 백테스트와 동일 조건 (보수적)
EXCLUDE_RECENT_H1_FOR_TIER = 1
```

---

## 📊 실전 vs 백테스트 REALISTIC 차이

| 항목 | 백테스트 | 실전 |
|---|---|---|
| EXCLUDE_RECENT_H1 | 1 (보수) | 0 (최신 정보 활용) |
| Touch 판정 | row.high/low | current_price |
| 체결가 | open clamp | current_price |
| Fill rate | 100% | ~100% (체결 실패 드묾) |

**→ 실전은 백테스트보다 약간 유리할 수 있음 (최신 H1 정보 활용).**

---

## 💡 참고: 배포 후 체크리스트

- [ ] 백업 생성 완료
- [ ] 서비스 중지 완료
- [ ] 파일 업로드 완료 (config.py, strategy_engine.py)
- [ ] __pycache__ 삭제 완료
- [ ] verify_v19realistic.sh 모두 [OK]
- [ ] 서비스 재시작 완료
- [ ] 초기 로그 확인 (에러 없음)
- [ ] 패널 접속 정상
- [ ] 첫 Zone Touched 확인
- [ ] 첫 실전 진입 관찰

---

**배포 완료 후 1주 관찰 결과를 바탕으로:**
- Tier 분포 분석
- 실전 Return 측정
- 필요 시 파라미터 튜닝

Good luck! 🚀
