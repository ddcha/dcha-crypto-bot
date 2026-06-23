"""feature/gate-tighten — MSS=choch 경로 룩어헤드 변조-불변 테스트.

MSS_MODE="choch" 는 H4 MSS 를 apply_choch 의 bull_choch/bear_choch 로 대체한다.
apply_choch 는 last_pivot_high/low(apply_pivots) + structure_bias + atr 에 의존하므로,
'진입봉(entry_idx) 이후 봉을 전부 쓰레기로 변조해도 entry_idx 시점의 choch 판정이 불변'
이면 = 미래를 안 읽은 것(룩어헤드 0). production 과 동일한 지표 체인/파라미터로 검증.
"""
import numpy as np, pandas as pd
from smc_stage4d.indicators import (
    apply_basic_indicators, apply_pivots, apply_structure_bias, apply_choch,
)
from smc_stage4d.config import H4_PIVOT_SWING_LEN, H4_CHOCH_BREAK_ATR_MULT


def _chain(df):
    df = apply_basic_indicators(df)
    df = apply_pivots(df, swing_len=H4_PIVOT_SWING_LEN)
    df = apply_structure_bias(df)
    df = apply_choch(df, break_atr_mult=H4_CHOCH_BREAK_ATR_MULT)
    return df


def _make_h4(n, rng):
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    o = close + rng.normal(0, 0.4, n)
    hi = np.maximum(o, close) + rng.uniform(0, 1.5, n)
    lo = np.minimum(o, close) - rng.uniform(0, 1.5, n)
    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC"),
        "open": o, "high": hi, "low": lo, "close": close,
    })


def test_choch_mss_no_lookahead():
    rng = np.random.default_rng(7)
    ocols = ["open", "high", "low", "close"]
    mism = 0
    fired = 0
    trials = 800
    for _ in range(trials):
        n = int(rng.integers(120, 360))
        df = _make_h4(n, rng)
        # 진입봉은 충분히 깊게(피벗 swing_len 확보) + 미래봉이 남도록
        ei = int(rng.integers(2 * H4_PIVOT_SWING_LEN + 20, n - 5))
        r1 = _chain(df)
        b1 = bool(r1.loc[ei, "bull_choch"]); s1 = bool(r1.loc[ei, "bear_choch"])

        dfc = df.copy()
        fut = (np.arange(n) > ei)               # ⭐ strict 미래봉만 변조(entry봉 자체 OHLC 는 보존)
        for c in ocols:
            col = dfc[c].values.copy()
            col[fut] = rng.uniform(-999, 999, fut.sum())
            dfc[c] = col
        r2 = _chain(dfc)
        b2 = bool(r2.loc[ei, "bull_choch"]); s2 = bool(r2.loc[ei, "bear_choch"])

        mism += int((b1 != b2) or (s1 != s2))
        fired += int(b1 or s1)

    assert mism == 0, f"CHoCH-MSS LOOKAHEAD LEAK: {mism}/{trials} mismatches"
    assert fired > 0, "test not exercising choch (fired=0)"
    print(f"PASS: choch-MSS 룩어헤드 0 ({trials}회 / 불일치 0 / choch 발동 {fired}회)")


if __name__ == "__main__":
    test_choch_mss_no_lookahead()
