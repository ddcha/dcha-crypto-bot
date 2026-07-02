# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.tiers
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403



# =========================================================
# ★★★ Stage 1 신규: classify_tier_v19b_rp_boost ★★★
# =========================================================
def classify_tier_v19b_rp_boost(pre_total, sweep_count, score, wick_ratio_5, run_potential):
    """
    v1.9b TIER + RP_BOOST 통합 분류.
    
    Returns:
        (tier_label, final_tier_mult, rp_action)
        - tier_label: "S", "A", "B", "C", "D"
        - final_tier_mult: base_tier_mult × RP_TIER_MULT_TABLE[run_potential]
                            (0.0 이면 skip)
        - rp_action: "rp_boost_rpN_xM.M" | "rp_pass_rpN" | "rp_skip_rpN" | "tier_d_skip"
    """
    # RP 테이블 밖 (RP 6+) → skip
    if run_potential not in RP_TIER_MULT_TABLE:
        return "D", 0.0, f"rp_skip_rp{run_potential}"
    
    rp_mult = RP_TIER_MULT_TABLE[run_potential]
    rp_action = (
        f"rp_boost_rp{run_potential}_x{rp_mult}" if rp_mult > 1.0
        else f"rp_pass_rp{run_potential}"
    )
    
    # 기존 v1.9b 티어 판정
    in_d = (pre_total >= 4) or (2 <= sweep_count <= 4) or (score >= 13)
    in_wick = (wick_ratio_5 is not None) and (not pd.isna(wick_ratio_5)) and (wick_ratio_5 <= WICK_RATIO_5_Q1_THRESHOLD)
    
    if in_d and in_wick:
        tier = "S"
        base_mult = TIER_RISK_S
    elif in_d and not in_wick:
        tier = "A"
        base_mult = TIER_RISK_A
    elif not in_d and in_wick:
        tier = "B"
        base_mult = TIER_RISK_B
    elif pre_total >= 1:
        tier = "C"
        base_mult = TIER_RISK_C
    else:
        # pre_total == 0 → Tier D → skip
        return "D", 0.0, "tier_d_skip"
    
    final_mult = base_mult * rp_mult
    return tier, final_mult, rp_action
