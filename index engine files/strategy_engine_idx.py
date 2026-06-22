"""
================================================================
한투 KIS 인덱스 자동매매 - Strategy Engine (v29.5 baseline)
================================================================
v29.5 baseline 의 진입 신호 로직을 실시간 호출 가능하게 추출.
코인 v2.2 의 build_structures / evaluate_zones / generate_entry_signal 패턴 따름.

[코인 vs 인덱스 차이]
- 코인: classify_tier_stage4h (ALPHA_MAX/HIGH/MED, SWEEP_GEM 등) + Stage 4K Sentiment
- 인덱스: classify_v25idx (S++/S/A+/A/XB) — v29.5 baseline 통계로 검증

[주요 import]
- yahoo_index_v29_5.py 의 핵심 함수들:
  prepare_h2_dataframe, prepare_h1_dataframe (timeframe 변경)
  build_structures, evaluate_zones_at_current_time
  compute_pre_entry_confluence, compute_wick_ratio_5
  compute_trade_tags, classify_tier_stage4h (4h tier)
  classify_tier_v19b_rp_boost (v19b S/A/B/C/D)
  apply_basic_indicators, apply_mss/displacement/fvg/ob/pd/pivots/structure_bias/choch
  apply_h4_market_state, apply_sweep_flags

[핵심 차이 from coin]
1. 코인 classify_tier_stage4h 결과 → 무시 X (atoms 계산용)
2. v25idx 분류 추가:
   - 시나리오 B 12종 차단 (XB)
   - v29.4 추가 음수 RULE 3종 차단
   - S++/S+/S/A+/A/A-/OTHER subtier
3. mult: rule × asset
4. risk_pct = base × combined_mult × global_risk_multiplier
================================================================
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import pandas as pd
import numpy as np

from config_kis import (
    # v29.5 mults
    V29_1_RULE_MULT,
    V29_2_ASSET_MULT,
    PHASE_A_RISK,
    PHASE_B_RISK,
    USE_V29_1_PATCH,
    USE_V29_2_PATCH,
    USE_V29_4_PATCH,
    # Risk
    FEE_RATE,
    MAX_NOTIONAL_PCT_OF_BALANCE,
    RISK_MULTIPLIER_DEFAULT,
    # v1.9b
    WICK_RATIO_5_Q1_THRESHOLD,
    PRE_ENTRY_LOOKBACK_LTF_BARS,
    WICK_LOOKBACK_BARS,
    SWEEP_LOOKBACK_BARS,
    USE_TIER_PRIORITY_SORT,
    EXCLUDE_RECENT_H1_FOR_TIER,
)

from kis_assets import (
    ASSET_META,
    get_pt_value_usd,
    get_multiplier,
    get_currency,
    DEFAULT_FX_TO_USD,
)

from risk_manager_idx import calc_qty_with_price


# ============================================================
# v29.5 백테 코드의 core 함수 import
# v29.5 백테 파일 (yahoo_index_v29_5.py) 이 같은 폴더에 있어야 함
# 실전 운용 시: kis_index_bot/yahoo_index_v29_5.py 로 복사
# ============================================================
# 핵심 함수만 발췌 import (전체 백테 함수는 안 가져옴)
# 백테 파일이 sys.path 에 있으면 직접 import 가능

# 백테 코드를 같은 폴더에 두는 게 가장 깔끔. 일단 sys.path 추가:
_v29_5_path = Path(__file__).parent / "yahoo_index_v29_5.py"
if not _v29_5_path.exists():
    # 개발/테스트 시 outputs 폴더에서 찾기
    _v29_5_path = Path(__file__).parent.parent / "yahoo_index_v29_5.py"

# ============================================================
# 상수 (v29.5 백테 동일)
# ============================================================
TIMEZONE = "America/New_York"
MIN_SCORE = 8.5
FRESHNESS_MAX_BONUS = 1.0
RELAX_MIN_SCORE = MIN_SCORE - FRESHNESS_MAX_BONUS  # 7.5

# Zone expiration (HTF 봉 단위)
ZONE_EXPIRE_BARS = 24

# ============================================================
# DataFrame 준비 (timeframe: HTF=2h, LTF=1h)
# ============================================================
def _basic_clean(df: pd.DataFrame) -> pd.DataFrame:
    """순수 데이터 cleanup (indicator 미적용)"""
    df = df.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df["high"]  = pd.to_numeric(df["high"],  errors="coerce")
    df["low"]   = pd.to_numeric(df["low"],   errors="coerce")
    df["open"]  = pd.to_numeric(df["open"],  errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"]= pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
    df = df.dropna(subset=["high", "low", "open", "close"]).reset_index(drop=True)
    return df


def prepare_htf_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """HTF (2h) 데이터 + 모든 indicator 적용 (코인의 prepare_h4 와 동일 패턴)"""
    df = _basic_clean(df)
    core = get_v29_5_core()
    if core is None:
        return df  # core 없으면 cleaning 만
    
    df = core["apply_basic_indicators"](df)
    df = core["apply_mss"](df, mss_lookback=80)
    df = core["apply_displacement"](df)
    df = core["apply_fvg"](df)
    df = core["apply_ob"](df, ob_lookback=15)
    df = core["apply_pd"](df, pd_lookback=1620)
    df = core["apply_pivots"](df, swing_len=30)
    df = core["apply_structure_bias"](df)
    df = core["apply_choch"](df, break_atr_mult=0.18)
    df = core["apply_h4_market_state"](df, transition_bars=360)
    return df


def prepare_ltf_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """LTF (1h) 데이터 + indicator (코인의 prepare_h1 와 동일 패턴)"""
    df = _basic_clean(df)
    core = get_v29_5_core()
    if core is None:
        return df
    
    df = core["apply_basic_indicators"](df)
    df = core["apply_mss"](df)
    df = core["apply_displacement"](df)
    df = core["apply_fvg"](df)
    df = core["apply_ob"](df)
    df = core["apply_pd"](df, pd_lookback=40)
    df = core["apply_pivots"](df, swing_len=3)
    df = core["apply_structure_bias"](df)
    df = core["apply_choch"](df, break_atr_mult=0.12)
    df = core["apply_sweep_flags"](df, recent_sweep_n=10)
    return df


# ============================================================
# 지표 / 구조 계산 (v29.5 함수 재사용)
# ============================================================
# 아래 함수들은 yahoo_index_v29_5.py 에서 import 시도
# 실패하면 ImportError 발생 → 운용 시 v29_5.py 가 같은 폴더에 있어야 함
def _try_import_v29_5_core():
    """v29_5 백테 코드에서 핵심 함수들 import.
    
    주의: v29.5 백테 코드는 zone 평가를 simulate_portfolio 안에서 인라인으로 처리함
    → evaluate_zones_at_current_time 은 백테에 없고, strategy_engine_idx 자체 구현 필요.
    """
    try:
        # 같은 폴더에 yahoo_index_v29_5.py 가 있다고 가정
        from yahoo_index_v29_5 import (
            apply_basic_indicators,
            apply_mss,
            apply_displacement,
            apply_fvg,
            apply_ob,
            apply_pd,
            apply_pivots,
            apply_structure_bias,
            apply_choch,
            apply_h4_market_state,
            apply_sweep_flags,
            build_structures as _build_structures_v29,
            compute_pre_entry_confluence as _compute_pre,
            compute_wick_ratio_5 as _compute_wick,
            compute_trade_tags as _compute_atoms,
            classify_tier_stage4h as _classify_4h,
            classify_tier_v19b_rp_boost as _classify_v19b,
            get_run_potential as _get_rp,
            calc_min_stop_distance as _calc_min_stop,
            clamp_stop_for_long, clamp_stop_for_short,
            get_tp_plan as _get_tp_plan,
            calc_position_size as _calc_pos_size,
            evaluate_freshness_at_entry as _eval_freshness,
            is_zone_fresh_at_entry as _is_zone_fresh,
        )
        return {
            "apply_basic_indicators": apply_basic_indicators,
            "apply_mss": apply_mss,
            "apply_displacement": apply_displacement,
            "apply_fvg": apply_fvg,
            "apply_ob": apply_ob,
            "apply_pd": apply_pd,
            "apply_pivots": apply_pivots,
            "apply_structure_bias": apply_structure_bias,
            "apply_choch": apply_choch,
            "apply_h4_market_state": apply_h4_market_state,
            "apply_sweep_flags": apply_sweep_flags,
            "build_structures": _build_structures_v29,
            "compute_pre_entry_confluence": _compute_pre,
            "compute_wick_ratio_5": _compute_wick,
            "compute_trade_tags": _compute_atoms,
            "classify_tier_stage4h": _classify_4h,
            "classify_tier_v19b_rp_boost": _classify_v19b,
            "get_run_potential": _get_rp,
            "calc_min_stop_distance": _calc_min_stop,
            "clamp_stop_for_long": clamp_stop_for_long,
            "clamp_stop_for_short": clamp_stop_for_short,
            "get_tp_plan": _get_tp_plan,
            "calc_position_size": _calc_pos_size,
            "evaluate_freshness_at_entry": _eval_freshness,
            "is_zone_fresh_at_entry": _is_zone_fresh,
        }
    except ImportError as e:
        print(f"[strategy_engine_idx] v29_5 core import 실패: {e}")
        print("  → yahoo_index_v29_5.py 가 같은 폴더에 있어야 함")
        return None


_V29_5_CORE = None  # lazy load


def get_v29_5_core():
    """v29_5 core 함수들 lazy load"""
    global _V29_5_CORE
    if _V29_5_CORE is None:
        _V29_5_CORE = _try_import_v29_5_core()
    return _V29_5_CORE


# ============================================================
# v29.5 RULE 분류 (XB 차단 + S++/S+/S/A+/A/A-/OTHER)
# ============================================================
def classify_v25idx(
    atoms_dict: Dict[str, Any],
    tier_4h_label: str,
    tier_v19b_label: str,
    pre_total_v: int,
    sweep_v: int,
    score_v: float,
    rp_v: int,
    side: str,
    symbol_key: str,
) -> Tuple[str, str, float, float]:
    """
    v29.5 의 RULE 분류 + XB 차단 + mult 계산.
    
    Returns:
        (v25idx_rule, v25idx_subtier, rule_mult, asset_mult)
    """
    # ----- atoms_dict 에서 변수 추출 -----
    _score_ge13 = bool(atoms_dict.get('a_score_ge13', False))
    _fvg        = bool(atoms_dict.get('a_fvg', False))
    _wick_q1    = bool(atoms_dict.get('a_wick_le_q1', False))
    _pre_ge4    = bool(atoms_dict.get('a_pre_total_ge4', False))
    _overlap    = bool(atoms_dict.get('a_overlap', False))
    _mss        = bool(atoms_dict.get('a_mss', False))
    _sweep_count_2_4 = bool(atoms_dict.get('a_sweep_count_2_4', False))
    
    _v19b_match_S = (tier_v19b_label == "S")
    _v19b_match_C = (tier_v19b_label == "C")
    _v19b_match_D = (tier_v19b_label == "D")
    _d_cond     = ((pre_total_v >= 4) or (2 <= sweep_v <= 4) or (score_v >= 13))
    _rp = int(rp_v)
    
    _t4h_max_score_pre   = (tier_4h_label == "ALPHA_MAX")
    _t4h_sweep_room_fvg  = (tier_4h_label == "SWEEP_ROOM_FVG")
    _t4h_sweep_room_only = (tier_4h_label == "SWEEP_ROOM_ONLY")
    _t4h_high_sweep_vol  = (tier_4h_label in ("ALPHA_HIGH", "ALPHA_MAX")) and _sweep_count_2_4
    _t4h_alpha_high      = (tier_4h_label == "ALPHA_HIGH")
    _t4h_alpha_med       = (tier_4h_label == "ALPHA_MED")
    _t4h_complete_out    = (tier_4h_label == "COMPLETE_OUT")
    
    v25idx_rule = "OTHER"
    v25idx_subtier = "OTHER"
    
    # ----- 1) X-BLOCK: 약한 조합 -----
    if _rp <= 1:
        v25idx_rule = "XB_RP01"; v25idx_subtier = "XB"
    elif _t4h_alpha_med and (not _v19b_match_S):
        v25idx_rule = "XB_MED"; v25idx_subtier = "XB"
    elif _v19b_match_C and _rp <= 1:
        v25idx_rule = "XB_C_RP"; v25idx_subtier = "XB"
    elif _v19b_match_D:
        v25idx_rule = "XB_D"; v25idx_subtier = "XB"
    
    # ----- 2) S++ 매우 강함 -----
    elif _mss and _overlap:
        v25idx_rule = "S++_MSS_OVL"; v25idx_subtier = "S++"
    elif _sweep_count_2_4 and _wick_q1 and _t4h_sweep_room_fvg:
        v25idx_rule = "S++_SC24_WICK_RFVG"; v25idx_subtier = "S++"
    elif _sweep_count_2_4 and _fvg and _wick_q1:
        v25idx_rule = "S++_SC24_FVG_WICK"; v25idx_subtier = "S++"
    elif _sweep_count_2_4 and _score_ge13 and _wick_q1:
        v25idx_rule = "S++_SC24_SCORE_WICK"; v25idx_subtier = "S++"
    
    # ----- 3) S+ 강함 -----
    elif _t4h_max_score_pre and _t4h_sweep_room_fvg and _v19b_match_S:
        v25idx_rule = "S+_MAX_RFVG_S"; v25idx_subtier = "S+"
    elif _t4h_max_score_pre and _t4h_sweep_room_fvg and _wick_q1:
        v25idx_rule = "S+_MAX_RFVG_WICK"; v25idx_subtier = "S+"
    elif _score_ge13 and _t4h_sweep_room_fvg and _v19b_match_S:
        v25idx_rule = "S+_SCORE_RFVG_S"; v25idx_subtier = "S+"
    elif _t4h_max_score_pre and _t4h_high_sweep_vol and _v19b_match_S:
        v25idx_rule = "S+_MAX_HSV_S"; v25idx_subtier = "S+"
    elif _fvg and _t4h_high_sweep_vol and _v19b_match_S:
        v25idx_rule = "S+_FVG_HSV_S"; v25idx_subtier = "S+"
    
    # ----- 4) S 견고 -----
    elif _pre_ge4 and _wick_q1 and _t4h_max_score_pre:
        v25idx_rule = "S_PRE4_WICK_MAX"; v25idx_subtier = "S"
    elif _fvg and _t4h_max_score_pre and _v19b_match_S:
        v25idx_rule = "S_FVG_MAX_S"; v25idx_subtier = "S"
    elif _score_ge13 and _t4h_max_score_pre and _wick_q1:
        v25idx_rule = "S_SCORE_MAX_WICK"; v25idx_subtier = "S"
    elif _score_ge13 and _v19b_match_S:
        v25idx_rule = "S_SCORE_S"; v25idx_subtier = "S"
    elif _pre_ge4 and _score_ge13:
        v25idx_rule = "S_PRE4_SCORE"; v25idx_subtier = "S"
    
    # ----- 5) A+ 보통 -----
    elif _score_ge13 and _fvg:
        v25idx_rule = "A+_SCORE_FVG"; v25idx_subtier = "A+"
    elif _t4h_max_score_pre:
        v25idx_rule = "A+_MAX"; v25idx_subtier = "A+"
    elif _rp == 4:
        v25idx_rule = "A+_RP4"; v25idx_subtier = "A+"
    elif _fvg and _d_cond and _rp == 3:
        v25idx_rule = "A+_FVG_D_RP3"; v25idx_subtier = "A+"
    
    # ----- 6) A 보통 -----
    elif _t4h_alpha_high:
        v25idx_rule = "A_HIGH"; v25idx_subtier = "A"
    elif _rp == 3:
        v25idx_rule = "A_RP3"; v25idx_subtier = "A"
    elif _rp == 2:
        v25idx_rule = "A_RP2"; v25idx_subtier = "A"
    
    # ----- 7) A- 약함 -----
    elif _t4h_sweep_room_only:
        v25idx_rule = "A-_ROOM_ONLY"; v25idx_subtier = "A-"
    elif _t4h_complete_out:
        v25idx_rule = "A-_OUT"; v25idx_subtier = "A-"
    else:
        v25idx_rule = "OTHER"; v25idx_subtier = "OTHER"
    
    # ============================================================
    # v29.1 시나리오 B 추가 차단 (음수 패턴 12종)
    # ============================================================
    if USE_V29_1_PATCH and v25idx_subtier != "XB":
        if v25idx_rule == "A_HIGH":
            if side == "short" and symbol_key == "YM":
                v25idx_rule = "XB_AH_SHORT_YM"; v25idx_subtier = "XB"
            elif side == "long" and tier_v19b_label == "S":
                v25idx_rule = "XB_AH_LONG_S"; v25idx_subtier = "XB"
            elif side == "short" and tier_v19b_label == "C":
                v25idx_rule = "XB_AH_SHORT_C"; v25idx_subtier = "XB"
            elif side == "long" and symbol_key == "ES":
                v25idx_rule = "XB_AH_LONG_ES"; v25idx_subtier = "XB"
            elif side == "short" and tier_v19b_label == "A":
                v25idx_rule = "XB_AH_SHORT_A"; v25idx_subtier = "XB"
            elif side == "long" and symbol_key == "NQ":
                v25idx_rule = "XB_AH_LONG_NQ"; v25idx_subtier = "XB"
            # SSE/SZSE 는 v29.5 baseline 에서 제거됐으므로 매칭 없음
        elif v25idx_rule == "A_RP3":
            if tier_4h_label == "ALPHA_MED":
                v25idx_rule = "XB_AR3_MED"; v25idx_subtier = "XB"
            elif tier_4h_label == "SKIP_MSS":
                v25idx_rule = "XB_AR3_SKIP"; v25idx_subtier = "XB"
        elif v25idx_rule == "S_SCORE_S":
            if _rp in (2, 4):
                v25idx_rule = "XB_SSS_RP24"; v25idx_subtier = "XB"
        elif v25idx_rule == "A+_RP4":
            v25idx_rule = "XB_AR4_ALL"; v25idx_subtier = "XB"
    
    # ============================================================
    # v29.4 추가 음수 RULE 3종 차단
    # ============================================================
    if USE_V29_4_PATCH and v25idx_subtier != "XB":
        if v25idx_rule == "A+_MAX":
            v25idx_rule = "XB_APMAX_ALL"; v25idx_subtier = "XB"
        elif v25idx_rule == "S_SCORE_MAX_WICK":
            v25idx_rule = "XB_SSMW_ALL"; v25idx_subtier = "XB"
        elif v25idx_rule == "A_RP3":
            v25idx_rule = "XB_AR3_ALL"; v25idx_subtier = "XB"
    
    # ============================================================
    # mult 계산
    # ============================================================
    if v25idx_subtier != "XB":
        rule_mult = V29_1_RULE_MULT.get(v25idx_rule, 1.0)
        asset_mult = V29_2_ASSET_MULT.get(symbol_key, 1.0)
    else:
        rule_mult = 0.0   # XB 차단 = 진입 X
        asset_mult = 1.0
    
    return v25idx_rule, v25idx_subtier, rule_mult, asset_mult


# ============================================================
# 메인 진입 신호 함수 (코인 v2.2 의 generate_entry_signal 와 동일 인터페이스)
# ============================================================
def generate_entry_signal_idx(
    df_htf_raw: pd.DataFrame,
    df_ltf_raw: pd.DataFrame,
    balance_usd: float,
    base_risk_pct: float,
    fee_rate: float,
    current_price: Optional[float] = None,
    last_exit_time_iso: Optional[str] = None,
    last_exit_side: Optional[str] = None,
    risk_multiplier: float = 1.0,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """
    인덱스 자산용 진입 신호 생성 (v29.5 baseline 사용).
    
    코인 봇의 generate_entry_signal 과 동일 인터페이스, 내부는 v29.5 baseline.
    
    Args:
        df_htf_raw: HTF (2h) raw 데이터, columns=[timestamp, open, high, low, close, volume]
        df_ltf_raw: LTF (1h) raw 데이터
        balance_usd: 잔고 (USD 환산)
        base_risk_pct: 기본 risk % (예: 0.01 = 1%)
        fee_rate: 수수료
        current_price: 현재가 (zone touch 판정용)
        last_exit_time_iso, last_exit_side: 청산 직후 재진입 쿨다운
        risk_multiplier: 패널 runtime 조절
        symbol: 자산 키 (NQ/ES 등)
    
    Returns:
        dict with should_enter, side, entry_price, sl, tp1, tp2, qty, ...
    """
    if symbol is None:
        return {"should_enter": False, "reason": "symbol_not_provided"}
    
    if len(df_htf_raw) < 250 or len(df_ltf_raw) < 400:
        return {
            "should_enter": False,
            "reason": "not_enough_data",
            "htf_rows": len(df_htf_raw),
            "ltf_rows": len(df_ltf_raw),
        }
    
    # v29.5 core 함수 lazy load
    core = get_v29_5_core()
    if core is None:
        return {
            "should_enter": False,
            "reason": "v29_5_core_not_available",
            "hint": "yahoo_index_v29_5.py 를 같은 폴더에 복사",
        }
    
    # ----- 1) Risk multiplier 적용 -----
    try:
        _rm = float(risk_multiplier) if risk_multiplier is not None else 1.0
    except Exception:
        _rm = 1.0
    if _rm <= 0.0:
        _rm = 1.0
    
    # ----- 2) DataFrame 준비 -----
    df_htf = prepare_htf_dataframe(df_htf_raw.copy())
    df_ltf = prepare_ltf_dataframe(df_ltf_raw.copy())
    
    # ----- 3) HTF 구조 분석 -----
    df_struct, structures, _ = core["build_structures"](df_htf.copy())
    
    if len(df_struct) < 220:
        return {
            "should_enter": False,
            "reason": "not_enough_struct_bars",
            "struct_rows": len(df_struct),
        }
    
    # 마지막 closed bar 의 인덱스 (실시간이면 마지막 bar 는 진행중일 수 있음)
    # 코인 봇 패턴: i = len(df_struct) - 2 (직전 closed bar)
    i = len(df_struct) - 2
    
    if i < 0:
        return {"should_enter": False, "reason": "insufficient_bars"}
    
    row_now = df_struct.iloc[i]
    
    # ----- 4) Zone evaluation (current price 기반) -----
    # 코인 v2.2 패턴: current_price 가 zone 안에 있을 때만 active
    # v29.5 의 evaluate_zones_at_current_time 사용
    if current_price is None:
        current_price = float(row_now["close"])
    
    # active zones 추출
    active_structures = [
        s for s in structures
        if s["zone_created_idx"] <= i <= s["expire_idx"]
        and s.get("score", 0) >= RELAX_MIN_SCORE
    ]
    
    if not active_structures:
        return {"should_enter": False, "reason": "no_active_zones"}
    
    # current_price 가 zone 안 또는 매우 가까운 자산 찾기
    touched_zones = []
    for s in active_structures:
        zone_low = s["zone_low"]
        zone_high = s["zone_high"]
        if zone_low <= current_price <= zone_high:
            touched_zones.append(s)
    
    if not touched_zones:
        return {
            "should_enter": False,
            "reason": "no_touched_zone",
            "current_price": current_price,
            "n_active_zones": len(active_structures),
        }
    
    # ----- 5) 최고 score zone 우선 (또는 USE_TIER_PRIORITY_SORT 따라 tier 우선) -----
    # 일단 score 우선 (백테 기본)
    touched_zones.sort(key=lambda s: -s.get("score", 0))
    
    # ----- 6) 각 touched zone 평가 → 최고 tier 선택 -----
    best_signal = None
    best_combined_mult = 0.0
    
    for structure in touched_zones:
        side = structure["type"]  # "long" or "short"
        zone_low = structure["zone_low"]
        zone_high = structure["zone_high"]
        zone_created_idx = structure["zone_created_idx"]
        score = structure.get("score", 0.0)
        
        # 진입 가격: 코인 봇 패턴 = current_price (현재가)
        entry_price = float(current_price)
        
        # ATR 기반 SL 거리 계산 (백테 코드와 동일)
        atr_val = float(row_now.get("atr", 0)) if "atr" in row_now else 0.0
        if atr_val <= 0:
            atr_val = abs(zone_high - zone_low) * 1.5
        
        if side == "long":
            raw_sl = zone_low - atr_val * 0.08  # SL_BUFFER_MULT
            raw_sl = core["clamp_stop_for_long"](entry_price, raw_sl, atr_val)
        else:
            raw_sl = zone_high + atr_val * 0.08
            raw_sl = core["clamp_stop_for_short"](entry_price, raw_sl, atr_val)
        
        sl_distance = abs(entry_price - raw_sl)
        if sl_distance <= 0:
            continue
        
        # ----- atoms 계산 -----
        # compute_pre_entry_confluence (returns: pre_sweep, pre_fvg, pre_ob, pre_total)
        try:
            pre_sweep, pre_fvg, pre_ob, pre_total = core["compute_pre_entry_confluence"](
                df_htf=df_struct,
                df_ltf=df_ltf,
                htf_entry_idx=i,
                zone_low=zone_low,
                zone_high=zone_high,
                lookback_ltf_bars=PRE_ENTRY_LOOKBACK_LTF_BARS,
            )
        except Exception:
            pre_sweep, pre_fvg, pre_ob, pre_total = 0, 0, 0, 0
        
        # wick_ratio_5
        try:
            wick_ratio_5 = core["compute_wick_ratio_5"](
                df_htf=df_struct,
                df_ltf=df_ltf,
                htf_entry_idx=i,
                side=side,
                lookback_n=WICK_LOOKBACK_BARS,
            )
            if wick_ratio_5 is None:
                wick_ratio_5 = 0.5
        except Exception:
            wick_ratio_5 = 0.5
        
        # compute_trade_tags 호출 (atomic 12 컨디션)
        try:
            atoms = core["compute_trade_tags"](
                df_struct=df_struct,
                entry_idx=i,
                zone_created_idx=zone_created_idx,
                zone_low=zone_low,
                zone_high=zone_high,
                side=side,
                pre_total=int(pre_total),
                sweep_count=int(pre_sweep),
                score=score,
                wick_ratio_5=wick_ratio_5,
                structure_reasons=structure.get("reasons", ""),
                atr_val=atr_val,
            )
        except Exception:
            atoms = {}
        
        # sweep_count = pre_sweep (compute_pre_entry_confluence 가 반환한 값 사용)
        sweep_count = int(pre_sweep)
        
        # ----- run_potential -----
        try:
            _rp_result = core["get_run_potential"](df_struct, i, structure); run_potential = _rp_result[0] if isinstance(_rp_result, tuple) else _rp_result
        except Exception:
            run_potential = 2
        
        # ----- tier_4h (코인의 ALPHA_MAX/HIGH/MED 등) -----
        try:
            tier_4h_label = core["classify_tier_stage4h"](atoms, side=side)
        except Exception:
            tier_4h_label = "OTHER"
        
        # ----- tier_v19b (S/A/B/C/D) -----
        try:
            tier_v19b_label = core["classify_tier_v19b_rp_boost"](
                pre_total=pre_total,
                sweep_count=sweep_count,
                score=score,
                wick_ratio_5=wick_ratio_5,
                run_potential=run_potential,
            )
        except Exception:
            tier_v19b_label = "C"
        
        # ----- v25idx 분류 (메인 차단/mult) -----
        v25idx_rule, v25idx_subtier, rule_mult, asset_mult = classify_v25idx(
            atoms_dict=atoms,
            tier_4h_label=tier_4h_label,
            tier_v19b_label=tier_v19b_label,
            pre_total_v=pre_total,
            sweep_v=sweep_count,
            score_v=score,
            rp_v=run_potential,
            side=side,
            symbol_key=symbol,
        )
        
        # XB 차단된 zone 은 skip
        if v25idx_subtier == "XB":
            continue
        
        combined_mult = rule_mult * asset_mult
        
        # 최고 mult zone 선택
        if combined_mult > best_combined_mult:
            best_combined_mult = combined_mult
            
            # SL/TP 계산
            tp_plan = core["get_tp_plan"](expansion_state=False)
            tp1_rr = tp_plan.get("tp1_rr", 1.5)
            tp2_rr = tp_plan.get("tp2_rr", 3.0)
            
            if side == "long":
                tp1 = entry_price + sl_distance * tp1_rr
                tp2 = entry_price + sl_distance * tp2_rr
            else:
                tp1 = entry_price - sl_distance * tp1_rr
                tp2 = entry_price - sl_distance * tp2_rr
            
            # qty 계산 (정수 계약)
            qty_result = calc_qty_with_price(
                symbol=symbol,
                balance_usd=balance_usd,
                base_risk_pct=base_risk_pct,
                rule_mult=rule_mult,
                asset_mult=asset_mult,
                global_risk_multiplier=_rm,
                entry_price=entry_price,
                sl_price=raw_sl,
                max_notional_pct_of_balance=MAX_NOTIONAL_PCT_OF_BALANCE,
            )
            
            best_signal = {
                "should_enter": True,
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "sl": raw_sl,
                "tp1": tp1,
                "tp2": tp2,
                "qty": qty_result["qty"],
                "risk_amount_usd": qty_result["risk_amount_usd"],
                "risk_per_contract_usd": qty_result["risk_per_contract_usd"],
                "notional_usd": qty_result["notional_usd"],
                "notional_pct_of_balance": qty_result["notional_pct_of_balance"],
                # v29.5 분류
                "v25idx_rule": v25idx_rule,
                "v25idx_subtier": v25idx_subtier,
                "rule_mult": rule_mult,
                "asset_mult": asset_mult,
                "combined_mult": combined_mult,
                # 코인 호환 tier
                "tier_4h": tier_4h_label,
                "tier_v19b": tier_v19b_label,
                # atoms / signal 정보
                "score": score,
                "pre_total": pre_total,
                "sweep_count": sweep_count,
                "wick_ratio_5": wick_ratio_5,
                "run_potential": run_potential,
                "atoms": atoms,
                # zone 정보
                "zone_low": zone_low,
                "zone_high": zone_high,
                "zone_created_idx": zone_created_idx,
                # tp_plan
                "tp_plan": tp_plan,
                "atr_val": atr_val,
                "sl_distance": sl_distance,
                # qty 메타
                "qty_was_forced": qty_result.get("qty_was_forced", False),
                "qty_reason": qty_result.get("reason", ""),
                # signal_ts
                "signal_ts": str(row_now["timestamp"]),
            }
    
    if best_signal is None:
        return {
            "should_enter": False,
            "reason": "all_touched_zones_xb_blocked",
            "n_touched_zones": len(touched_zones),
        }
    
    return best_signal


# ============================================================
# Helper: 잔고 USD 환산 (KIS 잔고 응답 → USD)
# ============================================================
def get_balance_usd_from_kis_response(balance_response: Dict[str, Any]) -> float:
    """
    KIS API 잔고 응답에서 TOT_USD 추출.
    
    [2710] 화면의 'TOT_USD' 가 USD 환산 총액.
    실제 KIS API 응답 형식은 docs 확인 필요.
    """
    # 임시 placeholder. 실제 KIS API 응답 형식에 맞게 수정 필요.
    try:
        result = balance_response.get("output", {})
        # 일반적인 KIS 해외선물 잔고 필드 추정
        tot_usd = float(result.get("dnca_tot_amt", 0))  # 예탁금
        return tot_usd
    except Exception:
        return 0.0


# ============================================================
# 모듈 레벨 wrapper 함수 (main_idx.py 호환 — 코인 봇과 동일 시그니처)
# ============================================================
def build_structures(df: pd.DataFrame):
    """v29_5 의 build_structures wrapper (zone cache build 용)"""
    core = get_v29_5_core()
    if core is None:
        raise RuntimeError("v29_5 core not loaded - yahoo_index_v29_5.py 가 같은 폴더에 있어야 함")
    return core["build_structures"](df)


def evaluate_zones_at_current_time(
    df_h4: pd.DataFrame,
    df_h1: pd.DataFrame,
    active_structures: List[Dict],
    i: int,
    exclude_recent_h1: int = 0,
    symbol: Optional[str] = None,
) -> List[Dict]:
    """
    현재 HTF index 기준으로 active zone 들을 일괄 평가 (인덱스 v29.5 baseline).
    
    코인 봇의 evaluate_zones_at_current_time 와 동일 인터페이스. 
    내부는 v29.5 baseline classify_v25idx 사용 (코인 tier 시스템 X).
    
    Returns: list of evaluated zone dicts (entry/sl 미포함 - main loop 에서 계산)
    """
    core = get_v29_5_core()
    if core is None:
        return []
    
    if i < 0 or i >= len(df_h4):
        return []
    
    evaluated = []
    
    for s in active_structures:
        # Freshness 평가
        try:
            fresh_bonus, fresh_reasons = core["evaluate_freshness_at_entry"](df_h4, s, i)
        except Exception:
            fresh_bonus = 0.0
            fresh_reasons = ""
        eff_score = float(s.get("score", 0)) + fresh_bonus
        if eff_score < MIN_SCORE:
            continue
        
        side_zone = str(s.get("type", ""))
        zone_low = float(s.get("zone_low", 0))
        zone_high = float(s.get("zone_high", 0))
        zone_created_idx = int(s.get("zone_created_idx", 0))
        structure_reasons = str(s.get("reasons", ""))
        
        # v29.5 atomic 계산 (v29.5 백테는 exclude_recent_h1 파라미터 없음)
        try:
            pre_sweep, pre_fvg, pre_ob, pre_total = core["compute_pre_entry_confluence"](
                df_htf=df_h4,
                df_ltf=df_h1,
                htf_entry_idx=i,
                zone_low=zone_low,
                zone_high=zone_high,
                lookback_ltf_bars=PRE_ENTRY_LOOKBACK_LTF_BARS,
            )
        except Exception:
            pre_sweep, pre_fvg, pre_ob, pre_total = 0, 0, 0, 0
        
        try:
            wick_r5 = core["compute_wick_ratio_5"](
                df_htf=df_h4,
                df_ltf=df_h1,
                htf_entry_idx=i,
                side=side_zone,
                lookback_n=WICK_LOOKBACK_BARS,
            )
        except Exception:
            wick_r5 = 0.5
        
        atr_val = float(df_h4.loc[i, "atr"]) if "atr" in df_h4.columns and pd.notna(df_h4.loc[i, "atr"]) else 0.0
        
        # atomic 12 컨디션
        try:
            atoms_dict = core["compute_trade_tags"](
                df_struct=df_h4,
                entry_idx=i,
                zone_created_idx=zone_created_idx,
                zone_low=zone_low,
                zone_high=zone_high,
                side=side_zone,
                pre_total=int(pre_total),
                sweep_count=int(pre_sweep),
                score=float(eff_score),
                wick_ratio_5=float(wick_r5) if wick_r5 is not None else 0.5,
                structure_reasons=structure_reasons,
                atr_val=atr_val,
            )
        except Exception:
            atoms_dict = {}
        
        # tier_4h
        try:
            tier_4h = core["classify_tier_stage4h"](atoms_dict, side=side_zone)
        except Exception:
            tier_4h = "OTHER"
        
        # run_potential
        try:
            _rp_result = core["get_run_potential"](df_h4, i, s); run_potential = _rp_result[0] if isinstance(_rp_result, tuple) else _rp_result
        except Exception:
            run_potential = 2
        
        # tier_v19b
        try:
            tier_v19b = core["classify_tier_v19b_rp_boost"](
                pre_total=int(pre_total),
                sweep_count=int(pre_sweep),
                score=float(eff_score),
                wick_ratio_5=float(wick_r5) if wick_r5 is not None else 0.5,
                run_potential=run_potential,
            )
        except Exception:
            tier_v19b = "C"
        
        # v25idx 분류 + mult (인덱스 baseline)
        v25idx_rule, v25idx_subtier, rule_mult, asset_mult = classify_v25idx(
            atoms_dict=atoms_dict,
            tier_4h_label=tier_4h,
            tier_v19b_label=tier_v19b,
            pre_total_v=int(pre_total),
            sweep_v=int(pre_sweep),
            score_v=float(eff_score),
            rp_v=int(run_potential),
            side=side_zone,
            symbol_key=symbol or "",
        )
        
        combined_mult = rule_mult * asset_mult
        
        # XB 차단 zone 은 evaluated 에서 제외 (또는 mult=0 으로 표시)
        evaluated.append({
            **s,  # 기존 zone 필드 모두 보존
            "fresh_bonus":         fresh_bonus,
            "fresh_reasons":       fresh_reasons,
            "eff_score":           eff_score,
            "pre_total":           int(pre_total),
            "pre_sweep":           int(pre_sweep),
            "wick_ratio_5":        float(wick_r5) if wick_r5 is not None else None,
            "atoms":               atoms_dict,
            "tier_4h":             tier_4h,
            "tier_v19b":           tier_v19b,
            "run_potential":       int(run_potential),
            "v25idx_rule":         v25idx_rule,
            "v25idx_subtier":      v25idx_subtier,
            "rule_mult":           rule_mult,
            "asset_mult":          asset_mult,
            "tier_mult_final":     combined_mult,
            "is_blocked":          v25idx_subtier == "XB",
        })
    
    return evaluated


# 코인 인터페이스 호환 alias
prepare_h4_dataframe = prepare_htf_dataframe
prepare_h1_dataframe = prepare_ltf_dataframe
generate_entry_signal = generate_entry_signal_idx


def get_latest_balance_usdt(wallet_response: Dict[str, Any]) -> float:
    """코인 인터페이스 호환 (wallet response → USD)"""
    return get_balance_usd_from_kis_response(wallet_response)


# ============================================================
# 자기 검증
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("strategy_engine_idx.py 자기 검증")
    print("=" * 80)
    
    # 1) classify_v25idx 단위 테스트
    print("\n[1] classify_v25idx 테스트")
    test_cases = [
        # (atoms, tier_4h, tier_v19b, pre, sweep, score, rp, side, symbol, expected_subtier)
        ({"a_mss": True, "a_overlap": True}, "ALPHA_HIGH", "S", 4, 2, 14, 3, "long", "ES", "S++"),
        # XB 패턴들
        ({}, "ALPHA_HIGH", "S", 0, 0, 10, 1, "long", "ES", "XB"),  # rp <= 1
        ({}, "ALPHA_MED", "C", 4, 2, 13, 3, "long", "NQ", "XB"),    # alpha_med + not S
        # A_HIGH ES long → XB 차단 (시나리오 B)
        ({}, "ALPHA_HIGH", "A", 0, 0, 10, 3, "long", "ES", "XB"),
    ]
    
    for atoms, t4h, tv19b, pre, sw, sc, rp, side, sym, expected in test_cases:
        rule, subtier, rm, am = classify_v25idx(atoms, t4h, tv19b, pre, sw, sc, rp, side, sym)
        flag = "✅" if subtier == expected else "❌"
        print(f"  {flag} {sym} {side} t4h={t4h} v19b={tv19b} rp={rp} → {subtier} ({rule}) mult={rm}×{am}")
    
    # 2) v29.5 mult 테이블 검증
    print("\n[2] V29_1_RULE_MULT 검증")
    for k in ["S++_MSS_OVL", "S_PRE4_WICK_MAX", "A_HIGH"]:
        print(f"  {k}: {V29_1_RULE_MULT.get(k)}x")
    
    print("\n[3] V29_2_ASSET_MULT 검증")
    for k in ["ES", "NQ", "TPX"]:
        print(f"  {k}: {V29_2_ASSET_MULT.get(k)}x")
    
    print("\n[4] generate_entry_signal_idx (mock 데이터)")
    print("  → 실제 구동은 main_idx.py 에서 KIS klines 데이터로 호출")
    print("  → 단위 테스트는 v29_5 백테 코드와 통합 후 수행")
