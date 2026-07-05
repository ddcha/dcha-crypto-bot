# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.utils
# =========================================================================
from .config import *  # noqa: F401,F403


# =========================================================
# DATE / DEPOSIT HELPERS
# =========================================================
def month_range(start_year=2022, start_month=1):
    now = datetime.now(timezone.utc)
    months = []
    y, m = start_year, start_month
    while (y < now.year) or (y == now.year and m <= now.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


# =========================================================
# STRUCTURE HELPERS
# =========================================================

def overlap_size(a_low, a_high, b_low, b_high):
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def is_zone_fresh_at_entry(h_arr, l_arr, zone_created_idx, entry_idx, zone_low, zone_high):
    # ⭐ numpy 벡터화: 기존 .loc 봉단위 루프 → C레벨 슬라이스(결과 불변, 단위검증 4000/4000 일치)
    #   h_arr/l_arr = df_struct["high"/"low"].values (위치기반, reset_index 전제와 동일)
    start = zone_created_idx + 1
    end = entry_idx - 1
    if start < 0:
        start = 0
    if end >= len(h_arr):
        end = len(h_arr) - 1
    if start > end:
        return True
    seg_h = h_arr[start:end + 1]
    seg_l = l_arr[start:end + 1]
    touched = (seg_h >= zone_low) & (seg_l <= zone_high)   # 터치 = 윅 진입(high≥zlo and low≤zhi)
    return int(touched.sum()) <= 1                          # ≤1터치 = fresh (NaN 존 경계도 동일)


# =========================================================
# RISK / ENTRY HELPERS
# =========================================================
def calc_min_stop_distance(entry, atr_val):
    pct_floor = entry * 0.003
    atr_floor = atr_val * 0.25 if pd.notna(atr_val) and atr_val > 0 else 0.0
    return max(pct_floor, atr_floor)


def clamp_stop_for_long(entry, raw_sl, atr_val):
    min_dist = calc_min_stop_distance(entry, atr_val)
    max_sl = entry - min_dist
    return min(raw_sl, max_sl)


def clamp_stop_for_short(entry, raw_sl, atr_val):
    min_dist = calc_min_stop_distance(entry, atr_val)
    min_sl = entry + min_dist
    return max(raw_sl, min_sl)


def calc_position_size(balance, risk_pct, entry, sl, fee_rate, max_notional_mult=3.0):
    risk_amount = balance * risk_pct
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return None, None, None

    qty = risk_amount / risk_per_unit
    notional = abs(entry * qty)

    max_notional = balance * max_notional_mult
    if notional > max_notional:
        qty = max_notional / abs(entry)
        notional = abs(entry * qty)

    est_roundtrip_fee = notional * fee_rate * 2
    if est_roundtrip_fee > risk_amount * 0.35:
        return None, None, None

    return qty, risk_per_unit, notional


def parse_reason_set(reason_str):
    if pd.isna(reason_str) or str(reason_str).strip() == "":
        return set()
    return set([x.strip() for x in str(reason_str).split(",") if x.strip()])


def classify_grade(entry_score, run_potential):
    if run_potential >= 3 and entry_score >= 10.0:
        return "S"
    elif run_potential == 2 and entry_score >= 10.0:
        return "A"
    return "B"


def get_expansion_state(market_state, h1_choch_confirm):
    return bool(h1_choch_confirm and market_state in ["up", "down"])


# =========================================================
# TRADE SIMULATOR (v1.9b 와 동일)
# =========================================================
def calc_bar_favorable_rr(side, entry, risk_per_unit, bar_high, bar_low):
    if risk_per_unit <= 0:
        return np.nan
    if side == "long":
        return (bar_high - entry) / risk_per_unit
    return (entry - bar_low) / risk_per_unit


# =========================================================
# PHASE HELPERS
# =========================================================
def get_current_phase(balance_usdt):
    return "B" if balance_usdt >= TARGET_BALANCE_USDT else "A"


def get_phase_risk_pct(phase, symbol):
    if phase == "B":
        return PHASE_B_RISK.get(symbol, PHASE_A_RISK.get(symbol, 0.01))
    return PHASE_A_RISK.get(symbol, 0.01)


def cap_and_extract_excess(balance_usdt):
    if balance_usdt <= TARGET_BALANCE_USDT:
        return balance_usdt, 0.0
    excess = balance_usdt - TARGET_BALANCE_USDT
    return TARGET_BALANCE_USDT, excess
