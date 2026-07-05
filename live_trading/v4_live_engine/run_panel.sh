#!/usr/bin/env bash
# ★컨트롤패널 싱글턴 런처 (Linux/mac) — 이미 8501 떠있으면 중복 기동 안 함(누적 방지).
#   streamlit 은 포트가 바쁘면 조용히 8502...로 옮겨 떠서 인스턴스가 쌓인다 → 포트 리스닝 체크로 차단.
cd "$(dirname "$0")"
export PYTHONUTF8=1
PORT=8501

if command -v ss >/dev/null 2>&1; then
  LISTEN=$(ss -ltn 2>/dev/null | grep -c ":$PORT ")
elif command -v lsof >/dev/null 2>&1; then
  LISTEN=$(lsof -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | wc -l)
elif command -v netstat >/dev/null 2>&1; then
  # Windows(git-bash) 폴백: ss/lsof 없음 → netstat LISTENING 라인 수
  LISTEN=$(netstat -ano 2>/dev/null | grep ":$PORT " | grep -ic listen)
else
  LISTEN=0
fi

if [ "$LISTEN" -gt 0 ]; then
  echo "[panel] 이미 실행 중 - http://localhost:$PORT . 중복 기동 안 함."
  exit 0
fi

echo "[panel] 컨트롤패널 기동 - http://localhost:$PORT"
exec python -m streamlit run control_panel.py --server.headless true --server.port "$PORT"
