# 🚀 KIS 인덱스 자동매매 봇 - 배포 가이드

**v29.5 baseline (PF 4.03, MDD -17.28%, 9자산)** 을 한투 KIS Open API 로 실전 매매.

---

## 📋 시스템 구조

```
kis_index_bot/
├── 핵심 코드
│   ├── config_kis.py              ← 모든 설정 (v29.5 mult 포함)
│   ├── kis_assets.py              ← 9자산 메타데이터
│   ├── market_hours.py            ← 자산별 거래시간 체크 (UTC)
│   ├── risk_manager_idx.py        ← 정수 계약 sizing + max_open=8
│   ├── strategy_engine_idx.py     ← v29.5 baseline 진입 로직
│   ├── exchange_kis.py            ← KIS REST API wrapper
│   ├── main_idx.py                ← 메인 loop (zone-proximity)
│   └── yahoo_index_v29_5.py       ← 백테 코드 (lazy load)
├── UI / 인프라 (코인 봇 재사용)
│   ├── control_panel_idx.py       ← Streamlit UI
│   ├── settings_store.py          ← live_settings_idx.json
│   ├── state_store.py             ← runtime_state.json
│   ├── log_store.py               ← logs/
│   ├── telegram_utils.py          ← TG 알림
│   └── engine_watchdog.py         ← main_idx 자동 재시작
└── runtime
    ├── live_settings_idx.json     ← API 키 + 자산 설정
    ├── runtime_state.json         ← 봇 상태
    ├── kis_token_cache.json       ← KIS 토큰 캐시
    └── logs/                      ← trade_log, system_log 등
```

---

## ⚙️ 1. KIS Developers 사전 준비

### 1-1. AppKey 발급 (이미 완료)
- 한투 홈페이지 → 트레이딩 → Open API → KIS Developers
- 모의계좌: 00225351-08 (해외선물옵션)

### 1-2. 모의투자 신청 (이미 완료)
- 트레이딩 → 모의투자 → 해외선물옵션 모의투자 신청

---

## 📦 2. 서버 배포 (Vultr Tokyo, Ubuntu 22.04)

### 2-1. 폴더 생성 + 파일 업로드

로컬 (PC) 에서:
```bash
scp -r kis_index_bot linuxuser@158.247.231.108:/home/linuxuser/
```

### 2-2. Python 환경 설정

서버에서:
```bash
ssh linuxuser@158.247.231.108

cd /home/linuxuser/kis_index_bot

# 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install pandas numpy requests pybit python-dotenv streamlit
```

### 2-3. 검증 실행

```bash
cd /home/linuxuser/kis_index_bot
source venv/bin/activate

# 모든 모듈 import 테스트
python3 -c "
import config_kis, kis_assets, market_hours, risk_manager_idx
import strategy_engine_idx, exchange_kis
import settings_store, state_store, log_store, telegram_utils, engine_watchdog
print('✓ 모든 모듈 import 성공')
"

# v29.5 core 로드 테스트
python3 -c "
import strategy_engine_idx as se
core = se.get_v29_5_core()
print(f'✓ v29_5 core 로드: {core is not None}')
"

# market hours 테스트
python3 market_hours.py
```

### 2-4. systemd service 설정

`/etc/systemd/system/kis-index-bot.service`:
```ini
[Unit]
Description=KIS Index Trading Bot
After=network.target

[Service]
Type=simple
User=linuxuser
WorkingDirectory=/home/linuxuser/kis_index_bot
ExecStart=/home/linuxuser/kis_index_bot/venv/bin/python3 main_idx.py
Restart=on-failure
RestartSec=15
CPUQuota=80%
StandardOutput=append:/home/linuxuser/kis_index_bot/logs/main_stdout.log
StandardError=append:/home/linuxuser/kis_index_bot/logs/main_stderr.log

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/kis-index-panel.service`:
```ini
[Unit]
Description=KIS Index Control Panel
After=network.target

[Service]
Type=simple
User=linuxuser
WorkingDirectory=/home/linuxuser/kis_index_bot
ExecStart=/home/linuxuser/kis_index_bot/venv/bin/streamlit run control_panel_idx.py --server.port 8502 --server.address 0.0.0.0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kis-index-panel.service
sudo systemctl start kis-index-panel.service
```

### 2-5. 패널 접속 + API 입력

```
http://158.247.231.108:8502
```

- **Demo App Key**: KIS Developers 에서 받은 모의 appkey
- **Demo App Secret**: 모의 appsecret
- **Demo 계좌번호**: `00225351` (둠챠 계좌)
- → "Demo API 적용" 버튼

### 2-6. 시스템 체크 ALL GREEN 확인

패널에서 system check 가 모두 ✓ 이면 START 가능.

---

## 🟢 3. 봇 시작

### 3-1. 자동 시작 (watchdog 사용 권장)
```bash
sudo systemctl enable kis-index-bot.service
sudo systemctl start kis-index-bot.service
```

또는 watchdog 으로:
```bash
nohup python3 engine_watchdog.py > logs/watchdog.log 2>&1 &
```

### 3-2. 로그 모니터링

```bash
# 메인 로그
tail -f logs/main_stdout.log

# trade log
tail -f logs/trade_log.csv

# system 로그
tail -f logs/system_log.csv
```

---

## 🔍 4. 운용 점검

### 4-1. 봇 상태 확인
```bash
sudo systemctl status kis-index-bot.service
ps aux | grep main_idx
```

### 4-2. 자산 시장 시간 확인
```bash
cd /home/linuxuser/kis_index_bot
source venv/bin/activate
python3 market_hours.py
```

### 4-3. 잔고 확인 (KIS API 호출 테스트)
```bash
python3 -c "
import json
from pathlib import Path
from settings_store import load_live_settings, get_kis_credentials
from exchange_kis import KisExchange

s = load_live_settings()
creds = get_kis_credentials(s)
ex = KisExchange(
    app_key=creds['app_key'],
    app_secret=creds['app_secret'],
    account_no=creds['account_no'],
    product_code=creds['product_code'],
    use_demo=creds['use_demo'],
)
print('서버 시간:', ex.get_server_time())
print('잔고:', ex.get_wallet_balance())
print('USD 환산:', ex.get_balance_usd())
"
```

---

## 🛑 5. 중지 / 재시작

```bash
# 안전 중지 (control_panel 의 STOP 버튼 권장)
sudo systemctl stop kis-index-bot.service

# 강제 재시작
sudo systemctl restart kis-index-bot.service

# 패널만 재시작
sudo systemctl restart kis-index-panel.service
```

---

## ⚠️ 6. 주의사항 / 알려진 이슈

### 6-1. KIS API tr_id 검증 필요
`exchange_kis.py` 의 tr_id / endpoint 는 일반 추정값. **첫 실행 전 KIS Developers 포털 docs 와 대조 필수**:
- https://apiportal.koreainvestment.com/apiservice
- 특히: 잔고조회, 주문, 시세 (해외선물옵션)

### 6-2. KIS 응답 필드명 fine-tune
`exchange_kis.py` 의 `get_balance_usd`, `get_recent_klines_df`, `get_last_price` 등은 KIS 응답 필드명을 추정해서 파싱. 실제 응답 받아본 후 정확한 필드명으로 수정 필요.

### 6-3. Stop loss 수동 모니터링
KIS 해외선물의 stop order endpoint 가 명확하지 않아 `set_stop_loss_only` 는 placeholder. main loop 의 `manage_open_positions` 가 SL 조건 체크 후 시장가 청산하는 방식으로 동작. (코인 봇과 동일)

### 6-4. 시장 시간
- 자산별 시장 closed 시간엔 진입 신호 발생 X (정상)
- HSI/TPX 휴장일 (일본/홍콩 공휴일) 은 별도 처리 X — 봇이 자동 skip (가격 0 반환 시 fail)

### 6-5. 환율 fix
`kis_assets.py` 의 `DEFAULT_FX_TO_USD` 는 2026-04 기준 정적값. 정확한 USD 환산은 매일 갱신 권장 (한투 환율 endpoint 또는 yahoo finance 환율 API).

---

## 📊 7. v29.5 baseline 성과 (참고)

- **거래 수**: 216
- **Win%**: 63.0%
- **PF**: 4.03
- **NetPnL**: +$112,089
- **Return**: +4,929%
- **MDD**: -17.28%
- **Avg R**: +0.510

---

## 🔄 8. 롤백 (문제 발생 시)

```bash
# 봇 중지
sudo systemctl stop kis-index-bot.service

# 백업 폴더로 복원
cd /home/linuxuser/
mv kis_index_bot kis_index_bot_broken
cp -r kis_index_bot_backup_<DATE> kis_index_bot

# 봇 재시작
sudo systemctl start kis-index-bot.service
```

---

## 💡 9. 진행 단계 권장

1. **Stage 1**: 모의계좌에서 `get_wallet_balance` 만 호출 → KIS API 응답 형식 확인 + 필드 보정
2. **Stage 2**: `get_kline` 호출 → 시세 데이터 받기 + 응답 보정
3. **Stage 3**: 봇 ENGINE 띄우되 `trading_enabled=False` (시그널만 로깅)
4. **Stage 4**: 1자산만 (`enabled=True`) 활성화, 시그널 → 진입 검증
5. **Stage 5**: 9자산 모두 활성화, 모의 운영
6. **Stage 6**: 실전 전환 (mode="live")

---

## 📞 문의 / 디버그

- 로그: `logs/` 폴더의 csv / log 파일
- 패널: `http://158.247.231.108:8502`
- TG 알림: `.env` 의 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
