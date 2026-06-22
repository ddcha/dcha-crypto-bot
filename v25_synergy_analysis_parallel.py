"""
v25 Stage 4K — Synergy Analysis (Parallel)
=============================================================
"어떤 atom 조합이 1+1>2 의 시너지를 내는가" 정량 분석.

시너지 (synergy) 정의:
  PF_baseline    : 전체 거래 PF
  PF_atom_i      : atom_i PASS 거래의 PF
  expected_PF (독립 가정) = PF_baseline × Π(PF_atom_i / PF_baseline)
                         = (Π PF_atom_i) / PF_baseline^(n-1)
  actual_PF      : combo (모든 atom AND) PASS 거래의 PF
  
  synergy_ratio  = actual_PF / expected_PF
    > 1 : 시너지 (서로 강화)
    = 1 : 독립 (단순 중첩)
    < 1 : 반시너지 (서로 방해)
  
  synergy_lift   = actual_PF - max(PF_atom_i)
    > 0 : 가장 강한 atom 보다 추가 alpha 있음
    < 0 : 가장 강한 atom 단독이 더 좋음 (combo 무가치)

빈도 시너지 (frequency synergy):
  expected_count = N × Π P(atom_i) = N × Π (trades_atom_i / N)
  actual_count   = combo trades
  freq_lift      = actual_count / expected_count
    > 1 : atom 들이 같이 등장 (correlated)
    < 1 : atom 들이 따로 등장 (negatively correlated)

산출물 (output_dir):
  1) v25_pairwise_synergy.csv      — 모든 atom-pair AND 시너지 (66 pairs)
  2) v25_triple_synergy.csv        — 3-way AND 시너지 (165 triples)
  3) v25_conditional_alpha.csv     — A given B 조건부 alpha 매트릭스
  4) v25_anti_synergy.csv          — 반시너지 (서로 방해) 조합
  5) v25_synergy_ranked_combos.csv — synergy_ratio top combos (size 2-5)

사용법:
  python v25_synergy_analysis_parallel.py
  python v25_synergy_analysis_parallel.py --workers 8
  python v25_synergy_analysis_parallel.py \\
      --trades ./v25_stage4k_trades.csv \\
      --candidates ./v25_stage4k_all_candidates.csv \\
      --output-dir ./out
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from itertools import combinations
from multiprocessing import Pool, cpu_count

import numpy as np
import pandas as pd


# ============================================================
# 설정
# ============================================================
DEFAULT_TRADES_PATH = "v25_stage4k_trades.csv"
DEFAULT_CANDIDATES_PATH = "v25_stage4k_all_candidates.csv"
DEFAULT_OUTPUT_DIR = "."

ATOMS_ALL_12 = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
# a_room 은 v25 에서 100% PASS (no-op) → 분석에서 제외
ATOMS_SYN = [a for a in ATOMS_ALL_12 if a != "a_room"]  # 11 atoms

# 시너지 분석 최소 표본 (combo 표본이 너무 작으면 PF 신뢰도↓)
MIN_TRADES_PAIR   = 30
MIN_TRADES_TRIPLE = 25
MIN_TRADES_COMBO  = 25
MIN_TRADES_COND   = 30

PF_INF_CAP = 50.0  # PF=g_loss=0 일 때 cap (시너지 ratio 폭주 방지)


# ============================================================
# Worker 글로벌
# ============================================================
_WORKER_DATA: dict = {}


def _init_worker(atom_matrix: np.ndarray,
                 net_pnl: np.ndarray,
                 r_multiple: np.ndarray,
                 atom_pf: np.ndarray,
                 atom_count: np.ndarray,
                 baseline_pf: float,
                 baseline_n: int) -> None:
    """ProcessPool worker 초기화."""
    _WORKER_DATA["atoms"]       = atom_matrix
    _WORKER_DATA["net_pnl"]     = net_pnl
    _WORKER_DATA["r_multiple"]  = r_multiple
    _WORKER_DATA["atom_pf"]     = atom_pf       # individual atom PFs (size N_atoms)
    _WORKER_DATA["atom_count"]  = atom_count    # individual atom PASS counts
    _WORKER_DATA["baseline_pf"] = baseline_pf
    _WORKER_DATA["baseline_n"]  = baseline_n


def _stats_from_mask(mask: np.ndarray) -> dict | None:
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


def _synergy_metrics(atom_indices: tuple, mask: np.ndarray, st: dict) -> dict:
    """combo mask 와 stats 로 시너지 metric 계산."""
    atom_pf = _WORKER_DATA["atom_pf"]
    atom_cnt = _WORKER_DATA["atom_count"]
    base_pf = _WORKER_DATA["baseline_pf"]
    base_n  = _WORKER_DATA["baseline_n"]

    # 개별 atom PF 들
    individual_pfs = [float(atom_pf[i]) for i in atom_indices]
    individual_cnts = [int(atom_cnt[i]) for i in atom_indices]

    # expected PF (독립 가정): PF_b × Π (PF_i / PF_b) = Π PF_i / PF_b^(n-1)
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

    # frequency synergy
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


def worker_synergy_combo(args: tuple) -> dict | None:
    """combo (size n) AND mask 의 시너지 측정."""
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
    syn = _synergy_metrics(atom_indices, mask, st)
    return {
        "size": size,
        "combo": "+".join(atom_names),
        **st,
        **syn,
    }


def worker_conditional_alpha(args: tuple) -> dict:
    """A given B: B PASS subset 안에서 A 추가 시 효과."""
    a_idx, b_idx, a_name, b_name, min_trades = args
    atoms = _WORKER_DATA["atoms"]
    
    # B PASS subset
    b_mask = atoms[:, b_idx]
    b_st = _stats_from_mask(b_mask)
    
    # A AND B PASS subset
    ab_mask = atoms[:, a_idx] & atoms[:, b_idx]
    
    if b_st is None or int(ab_mask.sum()) < min_trades:
        return {
            "A_atom": a_name, "given_B": b_name,
            "B_only_trades": b_st["trades"] if b_st else 0,
            "B_only_PF": b_st["PF"] if b_st else 0.0,
            "AB_trades": int(ab_mask.sum()),
            "AB_PF": 0.0,
            "cond_alpha_PF": 0.0,
            "cond_alpha_winpct": 0.0,
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


# ============================================================
# Main 로직
# ============================================================
def _to_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def load_and_join(trades_path: str, candidates_path: str) -> pd.DataFrame:
    print(f"[LOAD] trades:     {trades_path}")
    print(f"[LOAD] candidates: {candidates_path}")
    
    trades = pd.read_csv(trades_path)
    candidates = pd.read_csv(candidates_path)
    
    atoms_cols_in = [f"atoms_{a}" for a in ATOMS_ALL_12]
    for c in atoms_cols_in:
        if c not in candidates.columns:
            raise ValueError(f"candidates 컬럼 누락: {c}")
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
    
    print(f"[JOIN] joined={len(tdf)}")
    return tdf


def stats_dict(sub: pd.DataFrame) -> dict:
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


def main(trades_path: str, candidates_path: str,
         output_dir: str, n_workers: int | None = None) -> None:
    os.makedirs(output_dir, exist_ok=True)
    if n_workers is None:
        n_workers = max(1, cpu_count() - 1)
    
    # 1. 데이터 로드
    tdf = load_and_join(trades_path, candidates_path)
    
    # 2. numpy 변환
    atom_matrix = tdf[ATOMS_ALL_12].values.astype(bool)
    net_pnl_arr = tdf["net_pnl"].values.astype(float)
    r_mul_arr   = tdf["r_multiple"].values.astype(float)
    atom_idx    = {a: ATOMS_ALL_12.index(a) for a in ATOMS_ALL_12}
    
    # 3. baseline + 개별 atom PF 사전계산
    base_st = stats_dict(tdf)
    baseline_pf = base_st["PF"]
    baseline_n = base_st["trades"]
    
    n_atoms = atom_matrix.shape[1]
    atom_pf_arr = np.zeros(n_atoms)
    atom_cnt_arr = np.zeros(n_atoms, dtype=int)
    atom_winpct_arr = np.zeros(n_atoms)
    for i, atom_name in enumerate(ATOMS_ALL_12):
        m = atom_matrix[:, i]
        sub = tdf[m]
        st = stats_dict(sub)
        atom_pf_arr[i] = st["PF"]
        atom_cnt_arr[i] = st["trades"]
        atom_winpct_arr[i] = st["win_pct"]
    
    print()
    print("=" * 95)
    print(f"[BASELINE] Trades {baseline_n} | Win {base_st['win_pct']:.2f}% | "
          f"PF {baseline_pf:.3f} | avg_R {base_st['avg_R']:.3f}")
    print(f"[PARALLEL] workers = {n_workers}")
    print()
    print("[INDIVIDUAL ATOM PFs] (시너지 expected_PF 계산용)")
    print(f"{'atom':<22} {'trades':>7} {'PF':>7} {'win%':>7}")
    print("-" * 50)
    for i, a in enumerate(ATOMS_ALL_12):
        marker = " (excl.)" if a == "a_room" else ""
        print(f"{a:<22} {atom_cnt_arr[i]:>7} {atom_pf_arr[i]:>7.3f} "
              f"{atom_winpct_arr[i]:>6.2f}%{marker}")
    print("=" * 95)
    
    pool_kwargs = dict(
        processes=n_workers,
        initializer=_init_worker,
        initargs=(atom_matrix, net_pnl_arr, r_mul_arr,
                  atom_pf_arr, atom_cnt_arr, baseline_pf, baseline_n),
    )
    
    # ========================================================
    # (1) Pairwise synergy (size 2)  ← 병렬
    # ========================================================
    print()
    print("=" * 95)
    print("[1] Pairwise synergy — 모든 atom-pair AND 의 시너지 측정")
    print("=" * 95)
    print(f"  metric: synergy_ratio = actual_PF / expected_PF (independent)")
    print(f"          synergy_lift  = actual_PF - max(atom PF)")
    
    pair_jobs = []
    for a1, a2 in combinations(ATOMS_SYN, 2):
        idx_t = (atom_idx[a1], atom_idx[a2])
        pair_jobs.append((2, idx_t, (a1, a2), MIN_TRADES_PAIR))
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
        pair_df.to_csv(f"{output_dir}/v25_pairwise_synergy.csv", index=False)
        
        print()
        print("[Top 15 synergy_ratio]")
        print(f"{'#':<3} {'pair':<50} {'tr':>5} {'PF':>6} {'expPF':>6} "
              f"{'synR':>6} {'synLift':>8} {'maxPF':>6}")
        print("-" * 110)
        for i, r in pair_df.head(15).iterrows():
            print(f"{i+1:<3} {r['combo']:<50} {int(r['trades']):>5} "
                  f"{r['actual_PF']:>6.2f} {r['expected_PF']:>6.2f} "
                  f"{r['synergy_ratio']:>6.2f} {r['synergy_lift']:>+8.3f} "
                  f"{r['max_atom_PF']:>6.2f}")
        
        print()
        print("[Top 10 synergy_lift] (가장 강한 atom 보다 추가 alpha)")
        lift_top = pair_df.sort_values("synergy_lift", ascending=False).head(10)
        for i, r in lift_top.reset_index(drop=True).iterrows():
            print(f"{i+1:<3} {r['combo']:<50} {int(r['trades']):>5} "
                  f"PF {r['actual_PF']:>5.2f} | maxAtom {r['max_atom_PF']:>5.2f} "
                  f"| lift {r['synergy_lift']:>+6.3f}")
    
    # ========================================================
    # (2) Triple synergy (size 3)  ← 병렬
    # ========================================================
    print()
    print("=" * 95)
    print("[2] Triple synergy — 3-way AND 시너지")
    print("=" * 95)
    
    triple_jobs = []
    for trio in combinations(ATOMS_SYN, 3):
        idx_t = tuple(atom_idx[a] for a in trio)
        triple_jobs.append((3, idx_t, trio, MIN_TRADES_TRIPLE))
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
        triple_df.head(50).to_csv(f"{output_dir}/v25_triple_synergy.csv", index=False)
        
        print()
        print("[Top 15 triple synergy_ratio]")
        print(f"{'#':<3} {'triple':<60} {'tr':>5} {'PF':>6} {'expPF':>6} "
              f"{'synR':>6} {'synLift':>8}")
        print("-" * 110)
        for i, r in triple_df.head(15).iterrows():
            cstr = r['combo'][:58]
            print(f"{i+1:<3} {cstr:<60} {int(r['trades']):>5} "
                  f"{r['actual_PF']:>6.2f} {r['expected_PF']:>6.2f} "
                  f"{r['synergy_ratio']:>6.2f} {r['synergy_lift']:>+8.3f}")
    
    # ========================================================
    # (3) Conditional alpha  ← 병렬
    # ========================================================
    print()
    print("=" * 95)
    print("[3] Conditional alpha — 'B PASS 거래 안에서 A 추가 시' alpha 측정")
    print("=" * 95)
    print("  cond_alpha_PF = PF(A∧B) - PF(B alone)")
    print("  → 양수이면 B 가 PASS 일 때 A 가 추가로 helpful")
    
    cond_jobs = []
    for a in ATOMS_SYN:
        for b in ATOMS_SYN:
            if a == b:
                continue
            cond_jobs.append((atom_idx[a], atom_idx[b], a, b, MIN_TRADES_COND))
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
    cond_df_valid.to_csv(f"{output_dir}/v25_conditional_alpha.csv", index=False)
    
    print()
    print("[Top 15 cond_alpha_PF] (B PASS 일 때 A 가 PF 가장 크게 향상)")
    cond_top = cond_df_valid.sort_values("cond_alpha_PF", ascending=False).head(15)
    print(f"{'#':<3} {'A given B':<55} {'B_only':>7} {'A∧B':>7} "
          f"{'AB_tr':>7} {'cond_α':>9}")
    print("-" * 100)
    for i, r in cond_top.reset_index(drop=True).iterrows():
        s = f"{r['A_atom']} | {r['given_B']}"
        print(f"{i+1:<3} {s:<55} {r['B_only_PF']:>7.3f} {r['AB_PF']:>7.3f} "
              f"{int(r['AB_trades']):>7} {r['cond_alpha_PF']:>+9.3f}")
    
    print()
    print("[Bottom 10 cond_alpha_PF] (B PASS 인데 A 추가하면 오히려 PF 하락)")
    cond_bot = cond_df_valid.sort_values("cond_alpha_PF").head(10)
    for i, r in cond_bot.reset_index(drop=True).iterrows():
        s = f"{r['A_atom']} | {r['given_B']}"
        print(f"{i+1:<3} {s:<55} {r['B_only_PF']:>7.3f} {r['AB_PF']:>7.3f} "
              f"{int(r['AB_trades']):>7} {r['cond_alpha_PF']:>+9.3f}")
    
    # ========================================================
    # (4) Anti-synergy  ← pair_df / triple_df 에서 추출
    # ========================================================
    print()
    print("=" * 95)
    print("[4] Anti-synergy — 시너지 ratio < 1.0 (서로 방해)")
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
        anti_df.to_csv(f"{output_dir}/v25_anti_synergy.csv", index=False)
        print(f"  반시너지 조합: {len(anti_df)} 개")
        print()
        print("[Worst 15 anti-synergy]")
        print(f"{'#':<3} {'size':<5} {'combo':<55} {'tr':>5} "
              f"{'PF':>6} {'expPF':>6} {'synR':>6}")
        print("-" * 100)
        for i, r in anti_df.head(15).iterrows():
            cstr = r["combo"][:53]
            print(f"{i+1:<3} {int(r['combo_size']):<5} {cstr:<55} "
                  f"{int(r['trades']):>5} {r['actual_PF']:>6.2f} "
                  f"{r['expected_PF']:>6.2f} {r['synergy_ratio']:>6.3f}")
    else:
        print("  반시너지 조합 없음")
    
    # ========================================================
    # (5) Synergy-ranked combos size 2-5  ← 병렬
    # ========================================================
    print()
    print("=" * 95)
    print("[5] Synergy-ranked combos — size 2-5, synergy_ratio 기준 랭킹")
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
        # synergy_ratio top 50
        combo_top_ratio = combo_df.sort_values("synergy_ratio", ascending=False).head(50)
        combo_top_ratio = combo_top_ratio.round({"win_pct":2, "avg_R":3, "PF":3,
                                                  "total_pnl":2, "actual_PF":3,
                                                  "expected_PF":3, "synergy_ratio":3,
                                                  "synergy_lift":3, "max_atom_PF":3,
                                                  "min_atom_PF":3, "expected_count":2,
                                                  "freq_lift":3})
        combo_top_ratio.to_csv(f"{output_dir}/v25_synergy_ranked_combos.csv", index=False)
        
        print()
        print("[Top 20 synergy_ratio (모든 size)]")
        print(f"{'#':<3} {'size':<5} {'combo':<60} {'tr':>5} {'PF':>6} "
              f"{'expPF':>6} {'synR':>6} {'lift':>7}")
        print("-" * 120)
        for i, r in combo_top_ratio.head(20).reset_index(drop=True).iterrows():
            cstr = r['combo'][:58]
            print(f"{i+1:<3} {int(r['size']):<5} {cstr:<60} "
                  f"{int(r['trades']):>5} {r['actual_PF']:>6.2f} "
                  f"{r['expected_PF']:>6.2f} {r['synergy_ratio']:>6.2f} "
                  f"{r['synergy_lift']:>+7.3f}")
        
        # synergy_lift 절대값 기준 top
        print()
        print("[Top 15 synergy_lift] (max atom PF 대비 추가 alpha 절대값)")
        lift_top = combo_df.sort_values("synergy_lift", ascending=False).head(15)
        for i, r in lift_top.reset_index(drop=True).iterrows():
            cstr = r['combo'][:58]
            print(f"{i+1:<3} {int(r['size']):<5} {cstr:<60} "
                  f"PF {r['actual_PF']:>5.2f} | maxAtom {r['max_atom_PF']:>5.2f} "
                  f"| lift {r['synergy_lift']:>+6.3f}")
    
    # ========================================================
    # 요약
    # ========================================================
    print()
    print("=" * 95)
    print(f"[SAVED] v25 Synergy 분석 산출물 → {output_dir}")
    print("=" * 95)
    for f in ["v25_pairwise_synergy.csv",
              "v25_triple_synergy.csv",
              "v25_conditional_alpha.csv",
              "v25_anti_synergy.csv",
              "v25_synergy_ranked_combos.csv"]:
        print(f"  {os.path.join(output_dir, f)}")
    print()
    print("핵심 활용:")
    print("  - pairwise_synergy:   2-atom 조합 시너지 정량화 (heatmap 후보)")
    print("  - triple_synergy:     3-atom 조합 시너지 (165 triples)")
    print("  - conditional_alpha:  'B 통과한 거래에서 A 가 helpful 한가' (110 pairs)")
    print("  - anti_synergy:       서로 방해하는 조합 = 동시 사용 금지 후보")
    print("  - synergy_ranked:     synergy_ratio 기준 통합 랭킹 (size 2-5)")
    print()
    print("해석:")
    print("  synergy_ratio > 1.5  → 강한 시너지 (1+1=3+)")
    print("  synergy_ratio 0.8-1.2 → 거의 독립 (1+1=2)")
    print("  synergy_ratio < 0.7  → 반시너지 (1+1<2, 같이 쓰면 손해)")
    print("  synergy_lift > 0     → max atom 보다 추가 alpha (true synergy)")
    print("  freq_lift > 1.5      → atom 들이 같이 자주 등장 (correlation)")


# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="v25 Stage 4K — Synergy Analysis (Parallel)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
시너지 정의:
  expected_PF (독립 가정) = (Π PF_atom_i) / PF_baseline^(n-1)
  synergy_ratio = actual_PF / expected_PF
  synergy_lift  = actual_PF - max(individual atom PFs)

예시:
  python v25_synergy_analysis_parallel.py
  python v25_synergy_analysis_parallel.py --workers 8
""")
    parser.add_argument("--trades", default=DEFAULT_TRADES_PATH)
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    
    print("=" * 95)
    print("v25 Stage 4K — Synergy Analysis (Parallel)")
    print("=" * 95)
    print(f"  trades       : {args.trades}")
    print(f"  candidates   : {args.candidates}")
    print(f"  output_dir   : {args.output_dir}")
    print(f"  workers      : {args.workers if args.workers else 'auto (cpu_count - 1)'}")
    print(f"  cpu_count    : {cpu_count()}")
    print()
    
    if not os.path.exists(args.trades):
        print(f"[ERROR] trades 파일 없음: {args.trades}")
        sys.exit(1)
    if not os.path.exists(args.candidates):
        print(f"[ERROR] candidates 파일 없음: {args.candidates}")
        sys.exit(1)
    
    t_start = time.time()
    main(args.trades, args.candidates, args.output_dir, args.workers)
    print()
    print(f"[TOTAL] {time.time() - t_start:.1f}s")
