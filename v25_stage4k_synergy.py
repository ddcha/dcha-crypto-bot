# =========================================================
# v25 stage 4K — SYNERGY ANALYSIS (Atomic Decomposition)
#
# v25 지수 백테 결과 (trades.csv + all_candidates.csv) 에서
# 12 atom 의 시너지를 분해 → 콘솔 1차 출력 + CSV 저장.
#
# [정의]
#   PF_baseline    : 전체 거래 PF
#   PF_atom_i      : atom_i 단독 PASS 거래 PF
#   expected_PF    : (Π PF_atom_i) / PF_baseline^(n-1)         ← 독립 가정
#   actual_PF      : combo (AND) PASS 거래 PF
#   synergy_ratio  : actual_PF / expected_PF
#                      > 1 시너지 (서로 강화)
#                      = 1 독립 (단순 중첩)
#                      < 1 반시너지 (서로 방해)
#   synergy_lift   : actual_PF − max(individual atom PFs)
#                      > 0 가장 강한 atom 보다 추가 alpha
#   freq_lift      : actual_count / (N × Π P(atom_i))
#                      > 1 atom 들이 같이 자주 등장
#
# [산출물 → OUTDIR/]
#   v25_stage4k_pairwise_synergy.csv      ← 모든 atom-pair AND 시너지
#   v25_stage4k_triple_synergy.csv        ← 3-way AND 시너지 (top 50)
#   v25_stage4k_conditional_alpha.csv     ← A given B 조건부 alpha
#   v25_stage4k_anti_synergy.csv          ← 시너지 ratio < 1.0 조합
#   v25_stage4k_synergy_ranked_combos.csv ← synergy_ratio top combos (size 2-5)
#
# [실행]  D:\smc_bot> python v25_stage4k_synergy.py
# =========================================================
import os
import time
from itertools import combinations
from multiprocessing import Pool, cpu_count

import numpy as np
import pandas as pd


# =========================================================
# 사용자 환경 — 자기 폴더에 맞게 수정
# =========================================================
OUTDIR = "v25_stage4k_outputs"        # 백테 결과 폴더 (이 폴더에 trades.csv + all_candidates.csv 있어야 함)
PREFIX = "v25_stage4k"                 # 백테 파일 prefix

TRADES_CSV     = f"{OUTDIR}/{PREFIX}_trades.csv"
CANDIDATES_CSV = f"{OUTDIR}/{PREFIX}_all_candidates.csv"

N_WORKERS = max(1, cpu_count() - 1)

# 표본 size 컷
MIN_TRADES_PAIR   = 30
MIN_TRADES_TRIPLE = 25
MIN_TRADES_COMBO  = 25
MIN_TRADES_COND   = 30

PF_INF_CAP = 50.0   # PF=g_loss=0 일 때 cap (시너지 ratio 폭주 방지)


# =========================================================
# 12 atom (크립토 4D / 지수 v25 동일)
# =========================================================
ATOMS_ALL_12 = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
# a_room 은 v25 에서 100% PASS (no-op) → 분석 대상에서 제외
ATOMS_SYN = [a for a in ATOMS_ALL_12 if a != "a_room"]   # 11 atoms


# =========================================================
# ProcessPool worker 글로벌
# =========================================================
_WORKER_DATA = {}


def _init_worker(atom_matrix, net_pnl, r_multiple,
                 atom_pf, atom_count, baseline_pf, baseline_n):
    _WORKER_DATA["atoms"]       = atom_matrix
    _WORKER_DATA["net_pnl"]     = net_pnl
    _WORKER_DATA["r_multiple"]  = r_multiple
    _WORKER_DATA["atom_pf"]     = atom_pf
    _WORKER_DATA["atom_count"]  = atom_count
    _WORKER_DATA["baseline_pf"] = baseline_pf
    _WORKER_DATA["baseline_n"]  = baseline_n


def _stats_from_mask(mask):
    n = int(mask.sum())
    if n == 0:
        return None
    pnl = _WORKER_DATA["net_pnl"][mask]
    rmul = _WORKER_DATA["r_multiple"][mask]
    g_p = float(pnl[pnl > 0].sum())
    g_l = float(abs(pnl[pnl < 0].sum()))
    pf = g_p / max(g_l, 1e-9) if g_l > 0 else (PF_INF_CAP if g_p > 0 else 0.0)
    return {
        "trades":  n,
        "win_pct": float((pnl > 0).mean() * 100.0),
        "avg_R":   float(rmul.mean()),
        "PF":      float(min(pf, PF_INF_CAP)),
        "total_pnl": float(pnl.sum()),
    }


def _synergy_metrics(atom_indices, st):
    atom_pf = _WORKER_DATA["atom_pf"]
    atom_cnt = _WORKER_DATA["atom_count"]
    base_pf = _WORKER_DATA["baseline_pf"]
    base_n  = _WORKER_DATA["baseline_n"]

    individual_pfs  = [float(atom_pf[i]) for i in atom_indices]
    individual_cnts = [int(atom_cnt[i]) for i in atom_indices]

    n = len(atom_indices)
    if base_pf > 0:
        prod_pf = 1.0
        for pf in individual_pfs:
            prod_pf *= pf
        expected_pf = prod_pf / (base_pf ** (n - 1))
    else:
        expected_pf = 0.0

    actual_pf = st["PF"]
    synergy_ratio = actual_pf / expected_pf if expected_pf > 0 else 0.0
    synergy_lift  = actual_pf - max(individual_pfs)

    if base_n > 0:
        prob_prod = 1.0
        for c in individual_cnts:
            prob_prod *= (c / base_n)
        expected_count = base_n * prob_prod
    else:
        expected_count = 0.0
    actual_count = st["trades"]
    freq_lift = actual_count / expected_count if expected_count > 0 else 0.0

    return {
        "actual_PF":     actual_pf,
        "expected_PF":   expected_pf,
        "synergy_ratio": synergy_ratio,
        "synergy_lift":  synergy_lift,
        "max_atom_PF":   max(individual_pfs),
        "min_atom_PF":   min(individual_pfs),
        "actual_count":  actual_count,
        "expected_count": expected_count,
        "freq_lift":     freq_lift,
        "indiv_PFs":     ",".join(f"{p:.2f}" for p in individual_pfs),
    }


def worker_synergy_combo(args):
    size, atom_indices, atom_names, min_trades = args
    atoms = _WORKER_DATA["atoms"]
    mask = np.ones(atoms.shape[0], dtype=bool)
    for idx in atom_indices:
        mask = mask & atoms[:, idx]
    if int(mask.sum()) < min_trades:
        return None
    st = _stats_from_mask(mask)
    if st is None:
        return None
    syn = _synergy_metrics(atom_indices, st)
    return {
        "size": size,
        "combo": "+".join(atom_names),
        **st,
        **syn,
    }


def worker_conditional_alpha(args):
    a_idx, b_idx, a_name, b_name, min_trades = args
    atoms = _WORKER_DATA["atoms"]

    b_mask = atoms[:, b_idx]
    b_st = _stats_from_mask(b_mask)
    ab_mask = atoms[:, a_idx] & atoms[:, b_idx]

    if b_st is None or int(ab_mask.sum()) < min_trades:
        return {
            "A_atom": a_name, "given_B": b_name,
            "B_only_trades": b_st["trades"] if b_st else 0,
            "B_only_PF": b_st["PF"] if b_st else 0.0,
            "B_only_winpct": b_st["win_pct"] if b_st else 0.0,
            "AB_trades": int(ab_mask.sum()),
            "AB_PF": 0.0, "AB_winpct": 0.0,
            "cond_alpha_PF": 0.0, "cond_alpha_winpct": 0.0,
            "valid": False,
        }

    ab_st = _stats_from_mask(ab_mask)
    if ab_st is None:
        ab_st = {"PF": 0, "win_pct": 0, "trades": 0}

    return {
        "A_atom": a_name, "given_B": b_name,
        "B_only_trades": b_st["trades"],
        "B_only_PF":     b_st["PF"],
        "B_only_winpct": b_st["win_pct"],
        "AB_trades": ab_st["trades"],
        "AB_PF":     ab_st["PF"],
        "AB_winpct": ab_st["win_pct"],
        "cond_alpha_PF":     ab_st["PF"] - b_st["PF"],
        "cond_alpha_winpct": ab_st["win_pct"] - b_st["win_pct"],
        "valid": True,
    }


# =========================================================
# Helper
# =========================================================
def _to_bool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def stats_dict(sub):
    if len(sub) == 0:
        return {"trades":0, "win_pct":0.0, "avg_R":0.0, "PF":0.0,
                "total_pnl":0.0}
    pnl = sub["net_pnl"].values
    rmul = sub["r_multiple"].values
    g_p = float(pnl[pnl > 0].sum())
    g_l = float(abs(pnl[pnl < 0].sum()))
    pf = g_p / max(g_l, 1e-9) if g_l > 0 else (PF_INF_CAP if g_p > 0 else 0.0)
    return {
        "trades":  len(sub),
        "win_pct": float((pnl > 0).mean() * 100.0),
        "avg_R":   float(rmul.mean()),
        "PF":      float(min(pf, PF_INF_CAP)),
        "total_pnl": float(pnl.sum()),
    }


# =========================================================
# Main
# =========================================================
if __name__ == "__main__":
    print("=" * 95)
    print("# v25 Stage 4K — SYNERGY ANALYSIS (Atomic Decomposition)")
    print("=" * 95)
    print(f"#   trades CSV     : {TRADES_CSV}")
    print(f"#   candidates CSV : {CANDIDATES_CSV}")
    print(f"#   OUTDIR         : {OUTDIR}")
    print(f"#   N_WORKERS      : {N_WORKERS} / cpu_count = {cpu_count()}")
    print()

    if not os.path.exists(TRADES_CSV):
        print(f"[ERROR] trades 파일 없음: {TRADES_CSV}")
        print(f"        스크립트 상단 OUTDIR 변수를 자기 백테 결과 폴더로 수정하세요")
        raise SystemExit(1)
    if not os.path.exists(CANDIDATES_CSV):
        print(f"[ERROR] candidates 파일 없음: {CANDIDATES_CSV}")
        raise SystemExit(1)

    os.makedirs(OUTDIR, exist_ok=True)
    t_start = time.time()

    # ─────────────────────────────────────────────────
    # 1. 데이터 로드 + atom join
    # ─────────────────────────────────────────────────
    trades = pd.read_csv(TRADES_CSV)
    candidates = pd.read_csv(CANDIDATES_CSV)

    atoms_cols_in = [f"atoms_{a}" for a in ATOMS_ALL_12]
    for c in atoms_cols_in:
        if c not in candidates.columns:
            print(f"[ERROR] candidates 컬럼 누락: {c}")
            raise SystemExit(1)
        candidates[c] = _to_bool(candidates[c])

    candidates = candidates.rename(columns={f"atoms_{a}": a for a in ATOMS_ALL_12})

    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    candidates["entry_time"] = pd.to_datetime(candidates["entry_time"])

    cols_t = ["trade_id", "symbol_key", "entry_time", "side",
              "tier_label", "r_multiple", "net_pnl", "run_potential"]
    cols_c = ["symbol_key", "entry_time", "side"] + ATOMS_ALL_12

    tdf = pd.merge(
        trades[cols_t], candidates[cols_c],
        on=["symbol_key", "entry_time", "side"], how="left",
    )
    for c in ATOMS_ALL_12:
        tdf[c] = tdf[c].fillna(False).astype(bool)

    print(f"[LOAD] trades={len(trades)} | candidates={len(candidates)} | joined={len(tdf)}")

    # ─────────────────────────────────────────────────
    # 2. baseline + 개별 atom PFs
    # ─────────────────────────────────────────────────
    atom_matrix = tdf[ATOMS_ALL_12].values.astype(bool)
    net_pnl_arr = tdf["net_pnl"].values.astype(float)
    r_mul_arr   = tdf["r_multiple"].values.astype(float)
    atom_idx    = {a: ATOMS_ALL_12.index(a) for a in ATOMS_ALL_12}

    base_st = stats_dict(tdf)
    baseline_pf = base_st["PF"]
    baseline_n  = base_st["trades"]

    n_atoms = atom_matrix.shape[1]
    atom_pf_arr     = np.zeros(n_atoms)
    atom_cnt_arr    = np.zeros(n_atoms, dtype=int)
    atom_winpct_arr = np.zeros(n_atoms)
    for i, atom_name in enumerate(ATOMS_ALL_12):
        m = atom_matrix[:, i]
        sub = tdf[m]
        st = stats_dict(sub)
        atom_pf_arr[i]     = st["PF"]
        atom_cnt_arr[i]    = st["trades"]
        atom_winpct_arr[i] = st["win_pct"]

    print()
    print(f"[BASELINE] Trades {baseline_n} | Win {base_st['win_pct']:.2f}% | "
          f"PF {baseline_pf:.3f} | avg_R {base_st['avg_R']:.3f}")
    print()
    print("[INDIVIDUAL ATOM PFs]")
    print(f"  {'atom':<22} {'trades':>7} {'PF':>7} {'win%':>7}")
    print("  " + "-" * 50)
    for i, a in enumerate(ATOMS_ALL_12):
        marker = " (excl.)" if a == "a_room" else ""
        print(f"  {a:<22} {atom_cnt_arr[i]:>7} {atom_pf_arr[i]:>7.3f} "
              f"{atom_winpct_arr[i]:>6.2f}%{marker}")

    pool_kwargs = dict(
        processes=N_WORKERS,
        initializer=_init_worker,
        initargs=(atom_matrix, net_pnl_arr, r_mul_arr,
                  atom_pf_arr, atom_cnt_arr, baseline_pf, baseline_n),
    )

    # ─────────────────────────────────────────────────
    # (1) PAIRWISE SYNERGY
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[1] PAIRWISE SYNERGY — 모든 atom-pair AND 의 시너지")
    print("=" * 95)

    pair_jobs = [(2, (atom_idx[a1], atom_idx[a2]), (a1, a2), MIN_TRADES_PAIR)
                 for a1, a2 in combinations(ATOMS_SYN, 2)]
    print(f"  jobs: {len(pair_jobs)} | min_trades: {MIN_TRADES_PAIR}")

    t0 = time.time()
    with Pool(**pool_kwargs) as pool:
        pair_results = pool.map(worker_synergy_combo, pair_jobs)
    pair_results = [r for r in pair_results if r is not None]
    print(f"  완료: {len(pair_results)} valid pairs ({time.time()-t0:.1f}s)")

    pair_df = pd.DataFrame(pair_results)
    if len(pair_df) > 0:
        pair_df = pair_df.sort_values("synergy_ratio", ascending=False).reset_index(drop=True)
        pair_df = pair_df.round({"win_pct":2, "avg_R":3, "PF":3, "total_pnl":2,
                                  "actual_PF":3, "expected_PF":3,
                                  "synergy_ratio":3, "synergy_lift":3,
                                  "max_atom_PF":3, "min_atom_PF":3,
                                  "expected_count":2, "freq_lift":3})
        out_path = f"{OUTDIR}/{PREFIX}_pairwise_synergy.csv"
        pair_df.to_csv(out_path, index=False)
        print(f"  [SAVE] {out_path}")

        print()
        print(f"  {'#':<3} {'pair':<50} {'tr':>5} {'PF':>6} {'expPF':>6} "
              f"{'synR':>6} {'synLift':>8}")
        print("  " + "-" * 95)
        for i, r in pair_df.head(15).iterrows():
            print(f"  {i+1:<3} {r['combo']:<50} {int(r['trades']):>5} "
                  f"{r['actual_PF']:>6.2f} {r['expected_PF']:>6.2f} "
                  f"{r['synergy_ratio']:>6.2f} {r['synergy_lift']:>+8.3f}")

    # ─────────────────────────────────────────────────
    # (2) TRIPLE SYNERGY
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[2] TRIPLE SYNERGY — 3-way AND 시너지")
    print("=" * 95)

    triple_jobs = [(3, tuple(atom_idx[a] for a in trio), trio, MIN_TRADES_TRIPLE)
                   for trio in combinations(ATOMS_SYN, 3)]
    print(f"  jobs: {len(triple_jobs)} | min_trades: {MIN_TRADES_TRIPLE}")

    t0 = time.time()
    with Pool(**pool_kwargs) as pool:
        triple_results = pool.map(worker_synergy_combo, triple_jobs, chunksize=32)
    triple_results = [r for r in triple_results if r is not None]
    print(f"  완료: {len(triple_results)} valid triples ({time.time()-t0:.1f}s)")

    triple_df = pd.DataFrame(triple_results)
    if len(triple_df) > 0:
        triple_df = triple_df.sort_values("synergy_ratio", ascending=False).reset_index(drop=True)
        triple_df = triple_df.round({"win_pct":2, "avg_R":3, "PF":3, "total_pnl":2,
                                      "actual_PF":3, "expected_PF":3,
                                      "synergy_ratio":3, "synergy_lift":3,
                                      "max_atom_PF":3, "min_atom_PF":3,
                                      "expected_count":2, "freq_lift":3})
        out_path = f"{OUTDIR}/{PREFIX}_triple_synergy.csv"
        triple_df.head(50).to_csv(out_path, index=False)
        print(f"  [SAVE] {out_path}")

        print()
        print(f"  {'#':<3} {'triple':<60} {'tr':>5} {'PF':>6} {'expPF':>6} "
              f"{'synR':>6} {'synLift':>8}")
        print("  " + "-" * 105)
        for i, r in triple_df.head(15).iterrows():
            cstr = r['combo'][:58]
            print(f"  {i+1:<3} {cstr:<60} {int(r['trades']):>5} "
                  f"{r['actual_PF']:>6.2f} {r['expected_PF']:>6.2f} "
                  f"{r['synergy_ratio']:>6.2f} {r['synergy_lift']:>+8.3f}")

    # ─────────────────────────────────────────────────
    # (3) CONDITIONAL ALPHA
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[3] CONDITIONAL ALPHA — B PASS 거래에서 A 추가 시 alpha")
    print("=" * 95)

    cond_jobs = [(atom_idx[a], atom_idx[b], a, b, MIN_TRADES_COND)
                 for a in ATOMS_SYN for b in ATOMS_SYN if a != b]
    print(f"  jobs: {len(cond_jobs)} | min_trades: {MIN_TRADES_COND}")

    t0 = time.time()
    with Pool(**pool_kwargs) as pool:
        cond_results = pool.map(worker_conditional_alpha, cond_jobs, chunksize=32)
    print(f"  완료 ({time.time()-t0:.1f}s)")

    cond_df = pd.DataFrame(cond_results)
    cond_df_valid = cond_df[cond_df["valid"]].drop(columns=["valid"]).copy()
    cond_df_valid = cond_df_valid.round({"B_only_PF":3, "B_only_winpct":2,
                                          "AB_PF":3, "AB_winpct":2,
                                          "cond_alpha_PF":3, "cond_alpha_winpct":2})
    out_path = f"{OUTDIR}/{PREFIX}_conditional_alpha.csv"
    cond_df_valid.to_csv(out_path, index=False)
    print(f"  [SAVE] {out_path}")

    print()
    print("  [TOP 15 cond_alpha_PF]")
    cond_top = cond_df_valid.sort_values("cond_alpha_PF", ascending=False).head(15)
    print(f"  {'#':<3} {'A given B':<55} {'B_only':>7} {'A∧B':>7} "
          f"{'AB_tr':>7} {'cond_α':>9}")
    print("  " + "-" * 100)
    for i, r in cond_top.reset_index(drop=True).iterrows():
        s = f"{r['A_atom']} | {r['given_B']}"
        print(f"  {i+1:<3} {s:<55} {r['B_only_PF']:>7.3f} {r['AB_PF']:>7.3f} "
              f"{int(r['AB_trades']):>7} {r['cond_alpha_PF']:>+9.3f}")

    print()
    print("  [BOTTOM 10 cond_alpha_PF] (B 통과인데 A 추가하면 PF 하락)")
    cond_bot = cond_df_valid.sort_values("cond_alpha_PF").head(10)
    for i, r in cond_bot.reset_index(drop=True).iterrows():
        s = f"{r['A_atom']} | {r['given_B']}"
        print(f"  {i+1:<3} {s:<55} {r['B_only_PF']:>7.3f} {r['AB_PF']:>7.3f} "
              f"{int(r['AB_trades']):>7} {r['cond_alpha_PF']:>+9.3f}")

    # ─────────────────────────────────────────────────
    # (4) ANTI-SYNERGY
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[4] ANTI-SYNERGY — synergy_ratio < 1.0 (서로 방해)")
    print("=" * 95)

    anti_pair = pair_df[pair_df["synergy_ratio"] < 1.0].copy() if len(pair_df) > 0 else pd.DataFrame()
    anti_triple = triple_df[triple_df["synergy_ratio"] < 1.0].copy() if len(triple_df) > 0 else pd.DataFrame()
    if len(anti_pair) > 0:
        anti_pair["combo_size"] = 2
    if len(anti_triple) > 0:
        anti_triple["combo_size"] = 3

    anti_df = pd.concat([anti_pair, anti_triple], ignore_index=True) if (len(anti_pair) or len(anti_triple)) else pd.DataFrame()

    if len(anti_df) > 0:
        anti_df = anti_df.sort_values("synergy_ratio").reset_index(drop=True)
        out_path = f"{OUTDIR}/{PREFIX}_anti_synergy.csv"
        anti_df.to_csv(out_path, index=False)
        print(f"  [SAVE] {out_path}  ({len(anti_df)} 개)")

        print()
        print(f"  {'#':<3} {'size':<5} {'combo':<55} {'tr':>5} "
              f"{'PF':>6} {'expPF':>6} {'synR':>6}")
        print("  " + "-" * 100)
        for i, r in anti_df.head(15).iterrows():
            cstr = r["combo"][:53]
            print(f"  {i+1:<3} {int(r['combo_size']):<5} {cstr:<55} "
                  f"{int(r['trades']):>5} {r['actual_PF']:>6.2f} "
                  f"{r['expected_PF']:>6.2f} {r['synergy_ratio']:>6.3f}")
    else:
        print("  반시너지 조합 없음")

    # ─────────────────────────────────────────────────
    # (5) SYNERGY-RANKED COMBOS (size 2-5)
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[5] SYNERGY-RANKED COMBOS — size 2-5 통합 랭킹")
    print("=" * 95)

    combo_jobs = []
    for size in (2, 3, 4, 5):
        for combo in combinations(ATOMS_SYN, size):
            idx_t = tuple(atom_idx[a] for a in combo)
            combo_jobs.append((size, idx_t, combo, MIN_TRADES_COMBO))
    print(f"  jobs: {len(combo_jobs):,} | min_trades: {MIN_TRADES_COMBO}")

    t0 = time.time()
    with Pool(**pool_kwargs) as pool:
        combo_results = pool.map(worker_synergy_combo, combo_jobs, chunksize=64)
    combo_results = [r for r in combo_results if r is not None]
    print(f"  완료: {len(combo_results):,} valid combos ({time.time()-t0:.1f}s)")

    combo_df = pd.DataFrame(combo_results)
    if len(combo_df) > 0:
        combo_top = combo_df.sort_values("synergy_ratio", ascending=False).head(50)
        combo_top = combo_top.round({"win_pct":2, "avg_R":3, "PF":3, "total_pnl":2,
                                      "actual_PF":3, "expected_PF":3,
                                      "synergy_ratio":3, "synergy_lift":3,
                                      "max_atom_PF":3, "min_atom_PF":3,
                                      "expected_count":2, "freq_lift":3})
        out_path = f"{OUTDIR}/{PREFIX}_synergy_ranked_combos.csv"
        combo_top.to_csv(out_path, index=False)
        print(f"  [SAVE] {out_path}")

        print()
        print("  [TOP 20 synergy_ratio (모든 size)]")
        print(f"  {'#':<3} {'size':<5} {'combo':<60} {'tr':>5} {'PF':>6} "
              f"{'expPF':>6} {'synR':>6} {'lift':>7}")
        print("  " + "-" * 110)
        for i, r in combo_top.head(20).reset_index(drop=True).iterrows():
            cstr = r['combo'][:58]
            print(f"  {i+1:<3} {int(r['size']):<5} {cstr:<60} "
                  f"{int(r['trades']):>5} {r['actual_PF']:>6.2f} "
                  f"{r['expected_PF']:>6.2f} {r['synergy_ratio']:>6.2f} "
                  f"{r['synergy_lift']:>+7.3f}")

    # ─────────────────────────────────────────────────
    # 요약
    # ─────────────────────────────────────────────────
    print()
    print("=" * 95)
    print(f"[DONE] {time.time() - t_start:.1f}s | 산출물 → {OUTDIR}/")
    print("=" * 95)
    for f in [f"{PREFIX}_pairwise_synergy.csv",
              f"{PREFIX}_triple_synergy.csv",
              f"{PREFIX}_conditional_alpha.csv",
              f"{PREFIX}_anti_synergy.csv",
              f"{PREFIX}_synergy_ranked_combos.csv"]:
        print(f"  - {f}")
