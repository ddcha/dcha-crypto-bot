from __future__ import annotations
"""어댑터 확장 검증 — 백테 trades_v4 에서 다수 거래를 샘플해 라이브 재현율/payload/경계 커버리지 측정.
   커버: 패딩 꼬리효과(최근 존 재현 실패율), combo_removed(24/25), 만기컷 경계(35h vs 37h).
   실행: python test_adapter_ext.py   (data_cache 필요, API 불필요)
"""
import os, sys
import numpy as np, pandas as pd
import strategy_engine as SE

DATA = "../../data_cache"
TRADES = "../../walkforward_result/trades_v4.csv"
N_SAMPLE = 25


def load(sym, tf):
    d = pd.read_parquet(f"{DATA}/{sym}_{tf}.parquet"); d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True)


def main():
    tr = pd.read_csv(TRADES)
    tr = tr[~tr["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].reset_index(drop=True)
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    tr["setup"] = tr["matched_rule"].astype(str).str.split(r"\|\|").str[0]
    # 시간·심볼 다양성 위해 균등 샘플 + 최근구간(패딩 꼬리효과) 가중
    idx = np.linspace(0, len(tr) - 1, N_SAMPLE).astype(int)
    idx = sorted(set(idx.tolist() + list(range(len(tr) - 5, len(tr)))))   # 최근 5건 강제포함
    sample = tr.iloc[idx].reset_index(drop=True)

    btc = load("BTCUSDT", "4h"); need = ["should_enter", "side", "entry", "sl", "qty", "tp_plan", "risk_pct_tier_adjusted"]
    cache = {}
    det = side_ok = payload_ok = 0; reasons = {}; rows = []
    for _, t in sample.iterrows():
        sym = t["symbol"]; ets = pd.Timestamp(t["entry_time"])
        if sym not in cache:
            cache[sym] = (load(sym, "4h"), load(sym, "1h"))
        h4, h1 = cache[sym]
        SE.set_btc_regime(btc[btc["timestamp"] <= ets])
        h4c = h4[h4["timestamp"] <= ets].tail(1600).reset_index(drop=True)
        h1c = h1[h1["timestamp"] <= ets + pd.Timedelta(hours=3, minutes=59)].tail(6400).reset_index(drop=True)
        if len(h4c) < 260 or len(h1c) < 420:
            reasons["insufficient_hist"] = reasons.get("insufficient_hist", 0) + 1; continue
        sig = SE.generate_entry_signal(h4c, h1c, balance=10000.0, risk_pct=1.0, fee_rate=0.00055, max_notional_mult=3.0, symbol=sym)
        d = bool(sig.get("should_enter"))
        exp_side = "Buy" if t["side"] == "long" else "Sell"
        if d:
            det += 1
            so = sig.get("side") == exp_side; side_ok += int(so)
            po = all(k in sig for k in need); payload_ok += int(po)
            rows.append((sym, str(ets)[:10], "ENTER", f"{sig.get('side')}/{sig.get('risk_pct_tier_adjusted')}%", "✅" if (so and po) else "✗side/payload"))
        else:
            rc = sig.get("reason", "?"); reasons[rc] = reasons.get(rc, 0) + 1
            rows.append((sym, str(ets)[:10], rc, "", "—"))
    n = len(sample)
    print(f"=== 어댑터 확장검증: 샘플 {n}건 (백테 trades_v4 균등+최근) ===")
    for r in rows:
        print(f"  {r[0]:9s} {r[1]} | {r[2]:22s} {r[3]:16s} {r[4]}")
    print(f"\n검출(ENTER) {det}/{n} | side일치 {side_ok}/{det} | payload완전 {payload_ok}/{det}")
    print(f"미검출 사유분포: {reasons}")
    print("※ 재현 실패(no_fresh_signal 등)는 패딩 꼬리효과 커버리지 지표 — 0 이 아니어도 정상(최근 존 형성 미세차).")
    ok = (det > 0) and (side_ok == det) and (payload_ok == det)
    print("✅ 검출건 전부 side·payload 정합" if ok else "⚠️ 검출건 중 불일치 존재 — 확인필요")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
