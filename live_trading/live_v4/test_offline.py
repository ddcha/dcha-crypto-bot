from __future__ import annotations
"""오프라인 검증 — API 없이, 캐시 캔들로 get_live_signal 이 알려진 v4 거래를 재검출하는지 확인."""
import os, sys
import pandas as pd
import config_live as C
import strategy_live as S

DATA = os.path.join("..", "..", "data_cache")   # 리포 루트 data_cache
TESTS = [   # (symbol, entry_time_utc, expected_side, expected_setup_prefix)
    ("BTCUSDT", "2026-06-22 20:00:00", "short", "a_room+a_score_ge13+a_volume"),
    ("XRPUSDT", "2026-06-15 16:00:00", "short", "a_fvg_absent+a_ob+a_room+a_trend_counter"),
    ("DOGEUSDT", "2026-06-17 08:00:00", "long", "a_fvg_absent+a_ob+a_room+a_trend_counter"),
    ("SOLUSDT", "2026-06-27 20:00:00", "long", "a_fvg_absent+a_ob+a_room+a_score_ge13"),
]


def load(sym, tf):
    d = pd.read_parquet(os.path.join(DATA, f"{sym}_{tf}.parquet"))
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True)


def main():
    S.init(C)
    btc_all = load("BTCUSDT", "4h")
    ok = 0
    print(f"{'symbol':9}{'검출':>6}{'side':>7}{'setup 일치':>10}  risk%  판정")
    for sym, et, exp_side, exp_setup in TESTS:
        ets = pd.Timestamp(et, tz="UTC")
        h4 = load(sym, "4h"); h1 = load(sym, "1h")
        h4c = h4[h4["timestamp"] <= ets].tail(1600).reset_index(drop=True)
        h1c = h1[h1["timestamp"] <= ets + pd.Timedelta(hours=3, minutes=59)].tail(6400).reset_index(drop=True)
        S.set_btc_regime(btc_all[btc_all["timestamp"] <= ets])
        sig = S.get_live_signal(sym, h4c, h1c, C)
        det = sig.get("should_enter", False)
        side_ok = det and sig.get("side") == exp_side
        setup_ok = det and sig.get("setup", "").startswith(exp_setup[:20])
        verdict = "✅" if (det and side_ok and setup_ok) else ("⚠️신호X:" + sig.get("reason", "") if not det else "❌불일치")
        rp = f"{sig.get('risk_pct',0):.2f}" if det else "-"
        print(f"{sym:9}{'O' if det else 'X':>6}{sig.get('side','-'):>7}{'O' if setup_ok else 'X':>10}  {rp:>5}  {verdict}")
        if det and side_ok and setup_ok:
            ok += 1
    print(f"\n검출 성공: {ok}/{len(TESTS)}  {'✅ 라이브 신호 파이프라인 정상' if ok==len(TESTS) else '⚠️ 일부 미검출 — 확인필요'}")


if __name__ == "__main__":
    main()
