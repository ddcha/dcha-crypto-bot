"""
Active Zone 확인 스크립트
엔진 폴더에서 실행: python check_zones.py
"""
import json
from pathlib import Path
from strategy_engine import *
from exchange_bybit import BybitExchange

# live_settings.json 에서 API 키 로딩
settings_file = Path("live_settings.json")
if not settings_file.exists():
    print("live_settings.json 파일을 찾을 수 없습니다.")
    exit(1)

settings = json.loads(settings_file.read_text(encoding="utf-8"))
mode = str(settings.get("mode", "demo")).strip().lower()
api_cfg = settings.get("api", {})

if mode == "live":
    api_key = api_cfg.get("live_api_key", "")
    api_secret = api_cfg.get("live_api_secret", "")
else:
    api_key = api_cfg.get("demo_api_key", "")
    api_secret = api_cfg.get("demo_api_secret", "")

if not api_key or not api_secret:
    print(f"API 키가 설정되지 않았습니다. (mode={mode})")
    exit(1)

exchange = BybitExchange(
    api_key=api_key,
    api_secret=api_secret,
    use_testnet=(mode == "demo"),
    use_demo=(mode == "demo"),
)

print(f"[{mode.upper()} 모드] API 연결 완료\n")

# enabled 된 심볼 전체 스캔
active_symbols = [sym for sym, cfg in settings.get("assets", {}).items() if cfg.get("enabled", False)]
print(f"스캔 대상: {active_symbols}\n")

for symbol in active_symbols:
    try:
        df_h4 = exchange.get_recent_klines_df(
            category="linear", symbol=symbol, interval="240", limit=2000
        )

        df_struct, structures, _ = build_structures(prepare_h4_dataframe(df_h4.copy()))
        i = len(df_struct) - 2
        row = df_struct.iloc[i]
        current_close = float(row["close"])

        # 가격대에 맞춘 포맷
        if current_close < 1:
            pfmt = ",.4f"
        elif current_close < 100:
            pfmt = ",.3f"
        else:
            pfmt = ",.2f"

        active = [
            s for s in structures
            if s["zone_created_idx"] <= i <= s["expire_idx"]
            and s["score"] >= MIN_SCORE
        ]

        print(f"{'='*70}")
        print(f"{symbol}  |  현재가 ~{format(current_close, pfmt)}  |  H4 bars: {len(df_struct)}  |  active zones: {len(active)}")
        print(f"{'='*70}")

        if not active:
            print("  active zone 없음\n")
            continue

        for s in sorted(active, key=lambda x: -x["score"]):
            if s["type"] == "long":
                diff_pct = (current_close - s["zone_high"]) / current_close * 100
                dist = f"현재가 대비 {diff_pct:+.2f}%"
            else:
                diff_pct = (s["zone_low"] - current_close) / current_close * 100
                dist = f"현재가 대비 {diff_pct:+.2f}%"

            touch = "◀ TOUCH!" if s["zone_low"] <= current_close <= s["zone_high"] else ""

            zl = format(s["zone_low"], pfmt)
            zh = format(s["zone_high"], pfmt)
            print(f"  {s['type']:5s} | {zl:>14s} ~ {zh:>14s} | score={s['score']:5.1f} | {dist} {touch}")

        print()

    except Exception as e:
        print(f"\n{symbol}: 에러 - {e}\n")
