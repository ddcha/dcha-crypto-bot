from __future__ import annotations
"""어댑터 검증 — generate_entry_signal 이 알려진 v4 거래를 재현하고 payload 계약을 채우는지."""
import pandas as pd
import strategy_engine as SE

DATA = "../../data_cache"
TESTS = [
    ("BTCUSDT", "2026-06-22 20:00:00", "Sell", "a_room+a_score_ge13+a_volume"),
    ("SOLUSDT", "2026-06-27 20:00:00", "Buy", "a_fvg_absent+a_ob+a_room+a_score_ge13"),
]


def load(sym, tf):
    d = pd.read_parquet(f"{DATA}/{sym}_{tf}.parquet"); d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True)


def main():
    btc = load("BTCUSDT", "4h")
    need = ["should_enter", "side", "position_side", "entry", "sl", "qty", "risk_per_unit", "tp_plan", "tp_plan_name",
            "timestamp", "risk_pct_base", "risk_pct_tier_adjusted", "tier", "tier_mult", "sentiment_mult", "grade", "score"]
    ok = 0
    for sym, et, exp_side, exp_setup in TESTS:
        ets = pd.Timestamp(et, tz="UTC")
        SE.set_btc_regime(btc[btc["timestamp"] <= ets])
        h4 = load(sym, "4h"); h1 = load(sym, "1h")
        h4c = h4[h4["timestamp"] <= ets].tail(1600).reset_index(drop=True)
        h1c = h1[h1["timestamp"] <= ets + pd.Timedelta(hours=3, minutes=59)].tail(6400).reset_index(drop=True)
        sig = SE.generate_entry_signal(h4c, h1c, balance=10000.0, risk_pct=1.0, fee_rate=0.00055, max_notional_mult=3.0, symbol=sym)
        det = sig.get("should_enter", False)
        miss = [k for k in need if k not in sig] if det else []
        side_ok = det and sig.get("side") == exp_side
        setup_ok = det and str(sig.get("setup", "")).startswith(exp_setup[:20])
        print(f"[{sym}] 검출={det} side={sig.get('side')} setup={sig.get('setup','-')[:35]} "
              f"risk={sig.get('risk_pct_tier_adjusted','-')} qty={sig.get('qty','-')} tp={sig.get('tp_plan_name','-')} "
              f"{'✅' if (det and side_ok and setup_ok and not miss) else '❌ '+ (sig.get('reason','') or ('누락:'+str(miss)))}")
        if det and side_ok and setup_ok and not miss:
            ok += 1
    print(f"\n검증: {ok}/{len(TESTS)}  {'✅ 어댑터 정상 (payload 계약 충족)' if ok==len(TESTS) else '⚠️ 확인필요'}")


if __name__ == "__main__":
    main()
