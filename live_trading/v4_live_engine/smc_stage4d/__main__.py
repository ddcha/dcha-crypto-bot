# =========================================================================
# ⚠️  AUTO-EXTRACTED — 직접 수정 금지.
#     원본: smc_crypto_stage4d_atom_gate (1).py 를 고친 뒤
#     python tools/extract_modules.py --write 로 재생성하세요.
#     (라인범위 verbatim 추출 — 주석/서식/로직 100% 보존)
#     module: smc_stage4d.__main__
# =========================================================================
from .config import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403
from .tiers import *  # noqa: F401,F403
from .structures import *  # noqa: F401,F403
from .filters import *  # noqa: F401,F403
from .simulation import *  # noqa: F401,F403
from .reporting import *  # noqa: F401,F403



print("Stage 1 Part 1/3 loaded: config + indicators + tier helpers (with RP_BOOST)")


print("Stage 1 Part 2/3 loaded: structures + trade simulator + phase helpers")


print("Stage 1 Part 2.5/3 loaded: candidate generation (REFINE 제거) + execution")


print("Stage 1 Part 3/3 loaded: simulation + report")


# =========================================================
# ★★★ 셀 1: 데이터 다운로드 (병렬 처리) ★★★
# =========================================================
SYMBOLS_TO_PREPARE = sorted(list(SCENARIO_MULTI["assets"].keys()))

# =========================================================
# 🔍 실행 환경 체크
# =========================================================
import os as _os_env
try:
    import psutil as _psutil
    _ram_gb = _psutil.virtual_memory().total / 1e9
except ImportError:
    _ram_gb = None

_cpu_count = _os_env.cpu_count() or 2
_in_colab = "COLAB_GPU" in _os_env.environ or "google.colab" in str(_os_env.environ.get("PATH", ""))

print("=" * 75)
print("🔍 실행 환경 (Stage 2: v19b_norefine_rpboost / 9코인)")
print("=" * 75)
print(f"  환경: {'Google Colab' if _in_colab else 'Local'}")
print(f"  CPU 코어: {_cpu_count}")
if _ram_gb:
    print(f"  RAM: {_ram_gb:.1f} GB")
print("=" * 75)
print()

# =========================================================
# 병렬 처리 유틸리티
# =========================================================
import time as _time_module

def _parallel_map(func, items, n_workers=None, task_name="task", io_bound=False):
    """
    joblib(loky) → ProcessPoolExecutor → ThreadPool → 순차 fallback
    io_bound=True: Thread (네트워크 I/O 용)
    io_bound=False: Process (CPU 연산용)
    """
    n = len(items)
    if n_workers is None:
        if io_bound:
            n_workers = min(n, 9)
        else:
            n_workers = min(n, _os_env.cpu_count() or 2)
    else:
        if not io_bound:
            n_workers = min(n_workers, _os_env.cpu_count() or 2)

    t0 = _time_module.time()
    results = None
    errors = []

    if io_bound:
        try:
            from concurrent.futures import ThreadPoolExecutor
            print(f"  🔀 ThreadPool I/O 병렬 ({n_workers} threads, {n} {task_name})")
            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e:
            print(f"  ⚠️ Thread 실패, 순차 처리")
            results = [func(item) for item in items]
        elapsed = _time_module.time() - t0
        print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
        return results

    # CPU bound
    try:
        from joblib import Parallel, delayed
        print(f"  🔀 joblib(loky) CPU 병렬 ({n_workers} workers, {n} {task_name})")
        results = Parallel(n_jobs=n_workers, backend="loky", verbose=0)(
            delayed(func)(item) for item in items
        )
    except Exception as e_joblib:
        errors.append(("joblib", e_joblib))
        try:
            from concurrent.futures import ProcessPoolExecutor
            print(f"  🔀 ProcessPoolExecutor fallback ({n_workers} workers)")
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(func, items))
        except Exception as e_pool:
            errors.append(("ProcessPool", e_pool))
            print(f"  ⚠️ 병렬 모두 실패, 순차 처리")
            for name, e in errors:
                print(f"     - {name}: {type(e).__name__}: {str(e)[:100]}")
            results = [func(item) for item in items]

    elapsed = _time_module.time() - t0
    print(f"  ⏱  {task_name} 완료: {elapsed:.1f}초")
    return results


# 데이터 다운로드 (병렬)
print("=" * 75)
print(f"📥 데이터 다운로드 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

raw_results = _parallel_map(
    download_symbol_data, SYMBOLS_TO_PREPARE,
    task_name="심볼 다운로드", io_bound=True,
)
raw_data = dict(zip(SYMBOLS_TO_PREPARE, raw_results))

print("\n✅ 데이터 다운로드 완료.")

print("=" * 75)
print(f"🔧 indicators + 구조물 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

def _apply_indicators_single(sym):
    return sym, apply_indicators_and_build(raw_data[sym])

try:
    prepared_results = _parallel_map(
        _apply_indicators_single, SYMBOLS_TO_PREPARE,
        task_name="indicators", io_bound=False,
    )
    prepared_data = dict(prepared_results)
except Exception as e:
    print(f"  ⚠️ indicators 병렬 실패: {e}, 순차 처리")
    prepared_data = {}
    for sym in SYMBOLS_TO_PREPARE:
        prepared_data[sym] = apply_indicators_and_build(raw_data[sym])

print()
print("=" * 75)
print(f"🎯 candidates 생성 ({len(SYMBOLS_TO_PREPARE)} 심볼)")
print("=" * 75)

def _generate_candidates_single(sym):
    return sym, generate_candidates_from_prepared(prepared_data[sym])


# =========================================================
# ★★★ Stage 4D: candidates 생성 (atomic decomposition 실험) ★★★
# =========================================================
print()
print("=" * 75)
print("[Stage 4D] candidates 생성 — Atomic Decomposition (모든 risk mult 1.0)")
print("=" * 75)
print("  진입 조건 = MIN_SCORE 7.5 만 (모든 게이트 해제)")
print("  Tier / RP 계산은 유지, 단 risk 에 전혀 미반영")
print("  12 atomic 태그 전부 로그")

try:
    candidates_results_stage4d = _parallel_map(
        _generate_candidates_single, SYMBOLS_TO_PREPARE,
        task_name="candidates Stage 4D", io_bound=False,
    )
    candidates_dict_stage4d = dict(candidates_results_stage4d)
except Exception as e:
    print(f"  candidates 병렬 실패: {e}, 순차 처리")
    candidates_dict_stage4d = {}
    for sym in SYMBOLS_TO_PREPARE:
        candidates_dict_stage4d[sym] = generate_candidates_from_prepared(prepared_data[sym])

total_stage4d = sum(len(candidates_dict_stage4d[s]["candidates"]) for s in SYMBOLS_TO_PREPARE)
print(f"\n  TOTAL candidates (Stage 4D): {total_stage4d}")
print("\n[OK] candidates 생성 완료 (Stage 4D). risk 는 simulate 단계에서 전부 1.0 고정.")



# =========================================================
# ★★★ 셀 3: 단일 시나리오 백테스트 실행 (Stage 4D) ★★★
# =========================================================
import os
OUTDIR = os.environ.get("STAGE4D_OUTDIR", "stage4d_outputs")
os.makedirs(OUTDIR, exist_ok=True)
print(f"\n[OUTDIR] {os.path.abspath(OUTDIR)}")

STAGE4D_CASE = {
    "name":  "stage4d",
    "label": "Stage 4D: Atomic Decomposition (all risk mult = 1.0)",
    "risk_mult": 1.0,
    "candidates": candidates_dict_stage4d,
}

print()
print("#" * 75)
print(f"# Stage 4D 백테스트 시작: {STAGE4D_CASE['label']}")
print("#" * 75)

res = simulate_scenario_v19b_rpboost(
    scenario=SCENARIO_MULTI,
    candidates_dict=STAGE4D_CASE["candidates"],
    risk_multiplier=STAGE4D_CASE["risk_mult"],
)

monthly_report = print_scenario_summary(res)

prefix = "stage4d"
res["trades"].to_csv(f"{OUTDIR}/{prefix}_trades.csv", index=False)
res["equity"].to_csv(f"{OUTDIR}/{prefix}_equity.csv", index=False)
res["skipped"].to_csv(f"{OUTDIR}/{prefix}_skipped.csv", index=False)
monthly_report.to_csv(f"{OUTDIR}/{prefix}_monthly.csv", index=False)

# ─── 기본 summary ───
trades = res["trades"]
eq = res["equity"]
gp = trades[trades['net_pnl']>0]['net_pnl'].sum() if len(trades)>0 else 0
gl = abs(trades[trades['net_pnl']<0]['net_pnl'].sum()) if len(trades)>0 else 0
pf_overall = gp / max(gl, 1e-9)
wr_overall = (trades['net_pnl']>0).mean() * 100 if len(trades)>0 else 0
avgr_overall = trades['r_multiple'].mean() if len(trades)>0 else 0
mdd_overall = eq['dd_pct'].min() if len(eq)>0 else 0

final_total_krw   = res["final_total_assets_krw"]
deposit_krw = (INITIAL_BALANCE_USDT + MONTHLY_DEPOSIT_USDT * NUM_MONTHLY_DEPOSITS) * KRW_PER_USDT
return_pct = (final_total_krw - deposit_krw) / deposit_krw * 100
qualified = monthly_report[monthly_report['rolling_3m_avg_krw'] >= RETIREMENT_MONTHLY_TARGET_KRW]
retirement_month = qualified.iloc[0]['month'] if len(qualified)>0 else "mi-dalseong"
months_taken = monthly_report[monthly_report['month'] == retirement_month].index[0] + 1 if len(qualified)>0 else None

summary_df = pd.DataFrame([{
    "scenario":  STAGE4D_CASE["name"],
    "label":     STAGE4D_CASE["label"],
    "trades":    len(trades),
    "win%":      wr_overall,
    "PF":        pf_overall,
    "avg_R":     avgr_overall,
    "MDD%":      mdd_overall,
    "Return_%":  return_pct,
    "retirement":      retirement_month,
    "retirement_months": months_taken if months_taken else "X",
}])
summary_df.to_csv(f"{OUTDIR}/stage4d_overall_summary.csv", index=False)

print()
print("=" * 75)
print("[Stage 4D] 전체 성과")
print("=" * 75)
print(f"  Trades   : {len(trades)}")
print(f"  Win%     : {wr_overall:.2f}%")
print(f"  PF       : {pf_overall:.3f}")
print(f"  avg_R    : {avgr_overall:.3f}")
print(f"  MDD%     : {mdd_overall:.2f}%")
print(f"  Return%  : {return_pct:.1f}%")
print(f"  retirement : {retirement_month} ({months_taken if months_taken else 'X'}m)")


# =========================================================
# ★★★ Stage 4D: ATOMIC DECOMPOSITION 심층 분석 (8개 산출물) ★★★
# =========================================================
print()
print("#" * 75)
print("# Stage 4D Atomic Decomposition 분석")
print("#" * 75)

tdf = res["trades"].copy()

# 12 atomic 컬럼
ATOMS_ALL = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
ATOMS_TIER = ["a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
              "a_wick_le_q1", "a_pre_total_ge1"]
ATOMS_RP   = ["a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
ATOMS_SIG  = ["a_sweep", "a_volume"]

if len(tdf) == 0:
    print("[WARN] 거래 0건 — 분석 불가")
else:
    for c in ATOMS_ALL + ["tier", "run_potential"]:
        if c not in tdf.columns:
            tdf[c] = False if c.startswith("a_") else ""

    def _pf_of(sub):
        if len(sub) == 0:
            return 0.0
        g_p = sub[sub["net_pnl"] > 0]["net_pnl"].sum()
        g_l = abs(sub[sub["net_pnl"] < 0]["net_pnl"].sum())
        return g_p / max(g_l, 1e-9)

    def _stats(sub):
        if len(sub) == 0:
            return {"trades":0, "win_pct":0.0, "avg_R":0.0, "PF":0.0,
                    "total_pnl":0.0, "pnl_per_trade":0.0}
        return {
            "trades":    len(sub),
            "win_pct":   (sub["net_pnl"] > 0).mean() * 100.0,
            "avg_R":     sub["r_multiple"].mean(),
            "PF":        _pf_of(sub),
            "total_pnl":     sub["net_pnl"].sum(),
            "pnl_per_trade": sub["net_pnl"].mean(),
        }

    # ──────────────────────────────────────────────────────
    # (1) atom_solo_effect.csv — 각 원자 PASS vs FAIL
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[1] atom_solo_effect — 12 atomic PASS vs FAIL (Delta PF = 원자의 alpha)")
    print("=" * 95)
    print(f"{'atom':<22} {'status':<6} {'trades':>7} {'win%':>7} {'avg_R':>7} "
          f"{'PF':>7} {'total $':>14}")
    print("-" * 95)

    solo_rows = []
    for c in ATOMS_ALL:
        st_pass = _stats(tdf[tdf[c] == True])
        st_fail = _stats(tdf[tdf[c] == False])
        delta_pf = st_pass["PF"] - st_fail["PF"]
        solo_rows.append({"atom": c, "status": "PASS", "delta_PF": delta_pf, **st_pass})
        solo_rows.append({"atom": c, "status": "FAIL", "delta_PF": delta_pf, **st_fail})
        print(f"{c:<22} {'PASS':<6} {st_pass['trades']:>7} "
              f"{st_pass['win_pct']:>6.2f}% {st_pass['avg_R']:>7.3f} "
              f"{st_pass['PF']:>7.3f} {st_pass['total_pnl']:>14,.0f}")
        print(f"{c:<22} {'FAIL':<6} {st_fail['trades']:>7} "
              f"{st_fail['win_pct']:>6.2f}% {st_fail['avg_R']:>7.3f} "
              f"{st_fail['PF']:>7.3f} {st_fail['total_pnl']:>14,.0f}")
        print(f"{'  -> delta_PF':<22} {delta_pf:>+7.3f}")

    solo_df = pd.DataFrame(solo_rows).round(4)
    solo_df.to_csv(f"{OUTDIR}/atom_solo_effect.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (2) sweep_vol_pivot.csv — SWEEP+VOL 기준 나머지 atomic 추가 시 PF 변화
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[2] sweep_vol_pivot — SWEEP+VOLUME 기준 나머지 10 atomic 추가 시 효과")
    print("=" * 95)
    sv_base = tdf[(tdf["a_sweep"] == True) & (tdf["a_volume"] == True)]
    base_st = _stats(sv_base)
    print(f"  [BASE] SWEEP+VOLUME 통과: {base_st['trades']}t, "
          f"Win {base_st['win_pct']:.2f}%, PF {base_st['PF']:.3f}, "
          f"total ${base_st['total_pnl']:,.0f}")
    print("-" * 95)
    print(f"{'add_atom':<22} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'PF_delta':>9} {'total $':>14}")
    print("-" * 95)

    pivot_rows = [{"add_atom": "BASE_SV_ONLY", **base_st, "PF_delta": 0.0}]
    for c in ATOMS_ALL:
        if c in ATOMS_SIG:
            continue
        sub = sv_base[sv_base[c] == True]
        st = _stats(sub)
        delta = st["PF"] - base_st["PF"]
        pivot_rows.append({"add_atom": c, **st, "PF_delta": delta})
        print(f"{c:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {delta:>+9.3f} {st['total_pnl']:>14,.0f}")

    pivot_df = pd.DataFrame(pivot_rows).round(4)
    pivot_df.to_csv(f"{OUTDIR}/sweep_vol_pivot.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (3) tier_decomposition.csv — Tier 구성 5 atomic + 원본 Tier 판정 비교
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[3] tier_decomposition — Tier 구성 5 atomic 기여도 + 원본 Tier 판정")
    print("=" * 95)
    print(f"{'group':<22} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>14}")
    print("-" * 95)

    td_rows = []
    # Tier 구성 원자별
    for c in ATOMS_TIER:
        sub = tdf[tdf[c] == True]
        st = _stats(sub)
        td_rows.append({"group_type": "atomic_PASS", "group": c, **st})
        print(f"{c:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    # 원본 Tier 판정
    print("-" * 95)
    for t in ["S", "A", "B", "C", "D"]:
        sub = tdf[tdf["tier"] == t]
        st = _stats(sub)
        td_rows.append({"group_type": "original_tier", "group": t, **st})
        print(f"{'tier='+t:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
              f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

    td_df = pd.DataFrame(td_rows).round(4)
    td_df.to_csv(f"{OUTDIR}/tier_decomposition.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (4) rp_decomposition.csv — RP 구성 5 atomic 기여도 + side 분리
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[4] rp_decomposition — RP 구성 5 atomic (LONG / SHORT / ALL)")
    print("=" * 95)
    print(f"{'side':<6} {'atom':<18} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'total $':>14}")
    print("-" * 95)

    rpd_rows = []
    for side_val in ("ALL", "long", "short"):
        side_sub = tdf if side_val == "ALL" else tdf[tdf["side"] == side_val]
        for c in ATOMS_RP:
            sub = side_sub[side_sub[c] == True]
            st = _stats(sub)
            rpd_rows.append({"side": side_val, "atom": c, **st})
            print(f"{side_val:<6} {c:<18} {st['trades']:>7} "
                  f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
                  f"{st['total_pnl']:>14,.0f}")

    rpd_df = pd.DataFrame(rpd_rows).round(4)
    rpd_df.to_csv(f"{OUTDIR}/rp_decomposition.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (5) rp_level_analysis.csv — RP0 vs RP1 vs RP2+ 세분
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[5] rp_level_analysis — RP0 / RP1 / RP2+ 세분 (side 별)")
    print("=" * 95)

    rpl_rows = []
    rp_buckets = [
        ("RP0",   lambda r: r == 0),
        ("RP1",   lambda r: r == 1),
        ("RP2",   lambda r: r == 2),
        ("RP3",   lambda r: r == 3),
        ("RP4+",  lambda r: r >= 4),
        ("RP_0_only",  lambda r: r == 0),
        ("RP_0_or_1",  lambda r: r in (0, 1)),
        ("RP_ge_2",    lambda r: r >= 2),
    ]
    print(f"{'side':<6} {'bucket':<14} {'trades':>7} {'win%':>7} {'PF':>7} "
          f"{'avg_R':>7} {'total $':>14}")
    print("-" * 95)
    for side_val in ("ALL", "long", "short"):
        side_sub = tdf if side_val == "ALL" else tdf[tdf["side"] == side_val]
        for bname, cond in rp_buckets:
            sub = side_sub[side_sub["run_potential"].apply(cond)]
            st = _stats(sub)
            rpl_rows.append({"side": side_val, "bucket": bname, **st})
            print(f"{side_val:<6} {bname:<14} {st['trades']:>7} "
                  f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
                  f"{st['avg_R']:>7.3f} {st['total_pnl']:>14,.0f}")

    rpl_df = pd.DataFrame(rpl_rows).round(4)
    rpl_df.to_csv(f"{OUTDIR}/rp_level_analysis.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (6) side_x_atom.csv — LONG/SHORT × 12 atomic
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[6] side_x_atom — LONG / SHORT 에서 각 원자의 PASS 효과")
    print("=" * 95)
    print(f"{'side':<6} {'atom':<22} {'trades_PASS':>11} {'win% PASS':>10} "
          f"{'PF PASS':>8} {'PF FAIL':>8} {'delta_PF':>9}")
    print("-" * 95)

    sxa_rows = []
    for side_val in ("long", "short"):
        side_sub = tdf[tdf["side"] == side_val]
        for c in ATOMS_ALL:
            st_p = _stats(side_sub[side_sub[c] == True])
            st_f = _stats(side_sub[side_sub[c] == False])
            delta = st_p["PF"] - st_f["PF"]
            sxa_rows.append({
                "side": side_val, "atom": c,
                "trades_PASS": st_p["trades"], "win_pct_PASS": st_p["win_pct"],
                "PF_PASS": st_p["PF"], "total_pnl_PASS": st_p["total_pnl"],
                "trades_FAIL": st_f["trades"], "PF_FAIL": st_f["PF"],
                "delta_PF": delta,
            })
            print(f"{side_val:<6} {c:<22} {st_p['trades']:>11} "
                  f"{st_p['win_pct']:>9.2f}% {st_p['PF']:>8.3f} "
                  f"{st_f['PF']:>8.3f} {delta:>+9.3f}")

    sxa_df = pd.DataFrame(sxa_rows).round(4)
    sxa_df.to_csv(f"{OUTDIR}/side_x_atom.csv", index=False)

    # ──────────────────────────────────────────────────────
    # (7) top_combo_analysis.csv — 2개 & 3개 atomic 조합 brute-force 탐색 상위 30
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[7] top_combo_analysis — 2-3 atomic 조합 brute-force 탐색 (PF 상위 30)")
    print("=" * 95)

    from itertools import combinations
    MIN_TRADES_COMBO = 30   # 표본 신뢰를 위해 최소 30건 이상 조합만

    combo_rows = []
    for size in (2, 3):
        for atoms_sub in combinations(ATOMS_ALL, size):
            mask = pd.Series(True, index=tdf.index)
            for a in atoms_sub:
                mask = mask & (tdf[a] == True)
            sub = tdf[mask]
            if len(sub) < MIN_TRADES_COMBO:
                continue
            st = _stats(sub)
            combo_rows.append({
                "size": size,
                "combo": "+".join(atoms_sub),
                **st,
            })

    combo_df = pd.DataFrame(combo_rows)
    if len(combo_df) > 0:
        combo_df = combo_df.sort_values("PF", ascending=False).head(30).reset_index(drop=True)
        combo_df = combo_df.round({"win_pct":2, "avg_R":3, "total_pnl":2,
                                    "pnl_per_trade":2, "PF":3})
        combo_df.to_csv(f"{OUTDIR}/top_combo_analysis.csv", index=False)

        print(f"{'#':<3} {'size':<5} {'combo':<55} {'trades':>7} "
              f"{'win%':>7} {'PF':>7}")
        print("-" * 95)
        for i, r in combo_df.iterrows():
            cstr = r["combo"][:53] if len(r["combo"]) > 53 else r["combo"]
            print(f"{i+1:<3} {int(r['size']):<5} {cstr:<55} "
                  f"{int(r['trades']):>7} {r['win_pct']:>6.2f}% {r['PF']:>7.3f}")
    else:
        print("  (min_trades 조건 만족 조합 없음)")

    # ──────────────────────────────────────────────────────
    # (8) tier_original_vs_atoms.csv — 원본 Tier S/A/B/C/D 가 어떤 atomic 으로 구성되는지
    # ──────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[8] tier_original_vs_atoms — 원본 Tier 등급 × atomic 통과율")
    print("=" * 95)

    tov_rows = []
    header = f"{'tier':<6} {'trades':>7}"
    for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
        header += f"  {a[:11]:>11}"
    print(header)
    print("-" * max(len(header), 95))

    for t in ["S", "A", "B", "C", "D"]:
        sub = tdf[tdf["tier"] == t]
        if len(sub) == 0:
            continue
        row_data = {"tier": t, "trades": len(sub)}
        line = f"{t:<6} {len(sub):>7}"
        for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
            pct = (sub[a] == True).mean() * 100
            row_data[a + "_pct"] = round(pct, 2)
            line += f"  {pct:>10.1f}%"
        tov_rows.append(row_data)
        print(line)

    tov_df = pd.DataFrame(tov_rows)
    tov_df.to_csv(f"{OUTDIR}/tier_original_vs_atoms.csv", index=False)


print()
print("=" * 75)
print("[SAVED] Stage 4D 분석 산출물 (8개 + 기본 5개)")
print("=" * 75)
print(f"  {OUTDIR}/stage4d_trades.csv")
print(f"  {OUTDIR}/stage4d_equity.csv")
print(f"  {OUTDIR}/stage4d_skipped.csv")
print(f"  {OUTDIR}/stage4d_monthly.csv")
print(f"  {OUTDIR}/stage4d_overall_summary.csv")
print(f"  {OUTDIR}/atom_solo_effect.csv           [1] 각 원자 PASS vs FAIL")
print(f"  {OUTDIR}/sweep_vol_pivot.csv            [2] SWEEP+VOL 기준 원자 추가 효과")
print(f"  {OUTDIR}/tier_decomposition.csv         [3] Tier 5 원자 기여도")
print(f"  {OUTDIR}/rp_decomposition.csv           [4] RP 5 원자 기여도")
print(f"  {OUTDIR}/rp_level_analysis.csv          [5] RP0/RP1/RP2+ 세분")
print(f"  {OUTDIR}/side_x_atom.csv                [6] LONG/SHORT x 12 원자")
print(f"  {OUTDIR}/top_combo_analysis.csv         [7] 2-3 원자 조합 PF 상위 30")
print(f"  {OUTDIR}/tier_original_vs_atoms.csv     [8] 원본 Tier vs 원자 통과율")

print()
print("=" * 75)
print("[Stage 4D] 실험 완료")
print("=" * 75)
print("  설정: MIN_SCORE 7.5 만 게이트, 모든 risk mult = 1.0")
print("        Tier / RP 계산 유지(태깅 목적), risk 미반영")
print("        12 atomic 전부 독립 측정")
print("  핵심 산출물: sweep_vol_pivot.csv + top_combo_analysis.csv")

