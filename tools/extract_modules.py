#!/usr/bin/env python3
# =========================================================================
# tools/extract_modules.py
#
# 결정론적 모듈 추출기 (allowme.md STEP 4)
#   단일 파일  smc_crypto_stage4d_atom_gate (1).py  를
#   smc_stage4d/  패키지(10개 모듈)로 라인범위 verbatim 추출한다.
#
#   - 주석(◆ 해설 포함)은 "노드 앞 주석 동반" 규칙으로 verbatim 보존.
#   - 14개 중간 재정의 상수는 원본 라인순서 그대로 config.py 로 모아
#     최종 실효값이 단일 소스로 승리하게 한다(multiprocessing 워커가
#     부모 변경 못 보는 문제까지 동시 해결).
#   - 모듈 import 는 "엄격히 하위 레이어에서만 *" → 순환 불가능.
#
# 재생성:   python tools/extract_modules.py --write
# 검증만:   python tools/extract_modules.py            (dry-run, 리포트만)
# =========================================================================
import ast, os, sys, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC  = os.path.join(ROOT, "smc_crypto_stage4d_atom_gate (1).py")
PKG  = os.path.join(ROOT, "smc_stage4d")

# ---- 레이어 순서 (import 방향: 위 index 가 아래 index 를 import) -------------
LAYERS = ["config", "utils", "data", "indicators", "tiers",
          "structures", "filters", "simulation", "reporting", "__main__"]

# ---- 함수 → 모듈 배치 (호출그래프 DAG 를 레이어에 맞춰 배치) ----------------
FUNC_MODULE = {
    # utils — 순수 헬퍼 (스톱·RR·overlap·포지션·페이즈)
    "month_range": "utils", "overlap_size": "utils",
    "calc_min_stop_distance": "utils", "clamp_stop_for_long": "utils",
    "clamp_stop_for_short": "utils", "calc_position_size": "utils",
    "parse_reason_set": "utils", "classify_grade": "utils",
    "get_expansion_state": "utils", "calc_bar_favorable_rr": "utils",
    "get_current_phase": "utils", "get_phase_risk_pct": "utils",
    "cap_and_extract_excess": "utils", "is_zone_fresh_at_entry": "utils",
    # data — 데이터 수집 + 입금 스케줄
    "download_data": "data", "download_symbol_data": "data",
    "build_d1_trend": "data", "get_d1_trend_at": "data",
    "make_deposit_schedule": "data", "apply_pending_deposits": "data",
    # indicators — 지표·구조물 1차
    "apply_basic_indicators": "indicators", "apply_mss": "indicators",
    "apply_displacement": "indicators", "apply_fvg": "indicators",
    "apply_ob": "indicators", "apply_pd": "indicators",
    "apply_pivots": "indicators", "apply_structure_bias": "indicators",
    "apply_choch": "indicators", "apply_h4_market_state": "indicators",
    "has_recent_h1_choch": "indicators", "apply_sweep_flags": "indicators",
    "compute_pre_entry_confluence": "indicators", "compute_wick_ratio_5": "indicators",
    # tiers — Tier 분류·리스크 배수
    "classify_tier_v19b_rp_boost": "tiers",
    # structures — 존·신선도·run potential·지표 파이프라인
    "evaluate_zone_lifespan": "structures", "advance_zone_lifespan": "structures",
    "add_liquidity_sweep_quality": "structures", "build_structures": "structures",
    "evaluate_freshness_at_entry": "structures", "get_run_potential": "structures",
    "apply_indicators_and_build": "structures",
    # filters — 진입 필터 + 거래 태그
    "passes_d1_filter": "filters", "passes_sweep_confirmation": "filters",
    "passes_volume_filter": "filters", "passes_pullback_depth": "filters",
    "passes_atr_filter": "filters", "evaluate_all_filters": "filters",
    "evaluate_filter_groups": "filters", "compute_trade_tags": "filters",
    "compute_sweep_vol_only": "filters",
    # simulation — 체결·시뮬레이션 엔진
    "get_tp_plan": "simulation", "update_trailing_stop": "simulation",
    "_simulate_trade_with_plan_core": "simulation",
    "simulate_trade_with_plan_original": "simulation",
    "simulate_trade_with_plan_runner_no_time_exit": "simulation",
    "apply_execution_model_to_trade": "simulation",
    "execute_and_resimulate_trade": "simulation",
    "generate_candidates_from_prepared": "simulation",
    "simulate_scenario_v19b_rpboost": "simulation",
    # reporting — 리포트·차트
    "build_monthly_pnl_krw": "reporting", "find_retirement_month": "reporting",
    "print_scenario_summary": "reporting", "plot_equity": "reporting",
    # __main__ — 실행 오케스트레이션 헬퍼
    "_parallel_map": "__main__", "_apply_indicators_single": "__main__",
    "_generate_candidates_single": "__main__",
}

# config 로 강제 라우팅할 "재정의 상수" 이름(실행부에서 재대입되는 14개)
REDEF_NAMES = {
    "H4_PIVOT_SWING_LEN", "H4_MSS_LOOKBACK", "H4_OB_LOOKBACK", "H4_PD_LOOKBACK",
    "H4_MARKET_STATE_BARS", "H4_ZONE_MAX_AGE", "LONG_BASE_ENTRY_FRAC",
    "SHORT_BASE_ENTRY_FRAC", "USE_D1_TREND_FILTER", "USE_LIQUIDITY_SWEEP_CONF",
    "USE_VOLUME_FILTER", "USE_PULLBACK_DEPTH", "USE_ATR_FILTER", "USE_FILTER_GROUPS",
}

# config 영역 라인 경계: 첫 함수 def 전(헤더+상수) 및 BROAD/REG 상수 블록
FIRST_FUNC_LINE = 339          # def month_range
BROAD_REG_RANGE = (664, 705)   # 필터 그룹 뒤 BROAD_*/REG_* 상수 (주석 포함)


def assign_targets(node):
    names = []
    if isinstance(node, ast.Assign):
        for t in node.targets:
            for y in ast.walk(t):
                if isinstance(y, ast.Name):
                    names.append(y.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def bucket_for(node):
    """top-level 노드를 모듈 bucket 으로 분류."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return FUNC_MODULE[node.name]
    # 재정의 상수(실행부) → config 로 끌어모음 (최종값 단일소스)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        tgts = set(assign_targets(node))
        if tgts and tgts <= REDEF_NAMES and node.lineno >= FIRST_FUNC_LINE:
            return "config"
    # 헤더/imports/상수/atom-gate (첫 함수 전체 전)
    if node.lineno < FIRST_FUNC_LINE:
        return "config"
    # BROAD_*/REG_* 상수 블록
    if BROAD_REG_RANGE[0] <= node.lineno <= BROAD_REG_RANGE[1]:
        return "config"
    # 그 외 모든 실행부 statement(프린트/오케스트레이션) → __main__
    return "__main__"


def build():
    src = open(SRC, encoding="utf-8").read()
    lines = src.split("\n")            # 1-indexed via lines[i-1]
    n = len(lines)
    tree = ast.parse(src)

    # 라인 → bucket (노드 앞 주석 동반: prev_end+1 .. end)
    line_bucket = {}
    prev_end = 0
    for node in tree.body:
        b = bucket_for(node)
        start = prev_end + 1
        end = node.end_lineno
        for ln in range(start, end + 1):
            line_bucket[ln] = b
        prev_end = end
    # 파일 끝 잔여 라인(있으면) → 마지막 노드 bucket
    for ln in range(prev_end + 1, n + 1):
        line_bucket.setdefault(ln, "__main__")

    # bucket 별 라인 모으기
    buckets = {m: [] for m in LAYERS}
    for ln in range(1, n + 1):
        b = line_bucket.get(ln)
        if b is None:
            continue
        buckets[b].append(ln)

    return lines, buckets


def header(mod):
    idx = LAYERS.index(mod)
    lowers = LAYERS[:idx]
    imp = []
    banner = (
        "# =========================================================================\n"
        "# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.\n"
        "#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤\n"
        "#     python tools/extract_modules.py --write 로 재생성하세요.\n"
        "#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)\n"
        f"#     module: smc_stage4d.{mod}\n"
        "# =========================================================================\n"
    )
    for m in lowers:
        nm = "config" if m == "config" else m
        imp.append(f"from .{nm} import *  # noqa: F401,F403")
    return banner + ("\n".join(imp) + "\n\n" if imp else "\n")


def emit(lines, buckets, write):
    report = []
    total = 0
    for mod in LAYERS:
        lns = buckets[mod]
        total += len(lns)
        body = "\n".join(lines[ln - 1] for ln in lns)
        if mod == "config":
            head = (
                "# =========================================================================\n"
                "# ⚠️  AUTO-EXTRACTED — 직접 수정 금지 (config: 모든 상수·테이블 단일 소스).\n"
                "#     14개 중간 재정의 상수는 원본 라인순서 그대로 모아 최종 실효값이 승리한다.\n"
                "#     재생성: python tools/extract_modules.py --write\n"
                "# =========================================================================\n"
            )
            out = head + body + "\n"
            fname = "config.py"
        else:
            out = header(mod) + body + "\n"
            fname = mod + ".py" if mod != "__main__" else "__main__.py"
        report.append((fname, len(lns)))
        if write:
            with open(os.path.join(PKG, fname), "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
    if write:
        with open(os.path.join(PKG, "__init__.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write('"""smc_stage4d — Stage 4D Atomic Decomposition 백테스트 패키지.\n'
                    '자동 추출본. python -m smc_stage4d 로 실행.\n"""\n')
    return report, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="실제로 패키지 파일 생성")
    args = ap.parse_args()

    lines, buckets = build()
    if args.write:
        os.makedirs(PKG, exist_ok=True)
    report, total = emit(lines, buckets, args.write)

    print(f"원본 라인 수: {len(lines)}")
    print(f"버킷 배정 라인 합계: {total}  (모든 라인이 정확히 한 모듈로)")
    print("-" * 50)
    for fname, cnt in report:
        print(f"  {fname:18} {cnt:5} lines")
    print("-" * 50)
    print("WROTE → " + PKG if args.write else "(dry-run; --write 로 생성)")


if __name__ == "__main__":
    main()
