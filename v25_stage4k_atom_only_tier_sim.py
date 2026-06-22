# =========================================================
# v25 stage 4K — ATOM-ONLY TIER REDESIGN (시뮬레이션)
# =========================================================
# 기존 tier (ALPHA_MED/HIGH/MAX, SWEEP_ROOM_*) 완전 무시.
# atom 패턴만으로 새 tier 재구성 + atom 1+ OR 진입 게이트.
#
# [진입 게이트]
#   모든 atom OR — 11 atom (a_room 제외) 중 1+ PASS
#
# [차단 — 실제 손실 분석 기반]
#   K = 0           → SKIP (atom 부재)
#   K ≤ 3           → SKIP (22 trades, PF 0.55, -$1.9K — 진짜 손실 그룹)
#   CORE = 0        → SKIP (CORE 부재 setup, 손실률 53.5%)
#   * 단, overlap_solo 는 예외 (단독 PF 4.19, 27건)
#
# [Tier 분류 — atom 카운트 기반]
#   TIER_S       :  K ≥ 7  AND  CORE ≥ 1     (PF 3.0+ 추정)
#   TIER_A       :  K = 5~6  AND  CORE ≥ 2   (PF 2.0+ 추정)
#   TIER_B       :  K = 5~6  AND  CORE = 1   (PF 1.5 추정)
#   TIER_C       :  K = 4    AND  CORE ≥ 1   (마진 ~ PF 1.0)
#   TIER_OVERLAP :  overlap_solo 예외        (PF 4.19, 표본 27)
#
#   K = atom PASS 갯수 (a_room 제외)
#   CORE = score_ge13 / fvg / pre_total_ge4 / wick_le_q1 중 PASS 갯수
#
# [출력 → OUTDIR/]
#   v25_stage4k_atomtier_summary.csv     ← BEFORE vs AFTER
#   v25_stage4k_atomtier_TAKE.csv        ← 진입 거래
#   v25_stage4k_atomtier_SKIP.csv        ← 차단 거래
#   v25_stage4k_atomtier_tier_grp.csv    ← TAKE tier 분해
#   v25_stage4k_atomtier_skip_grp.csv    ← SKIP reason 분해
#   v25_stage4k_atomtier_asset.csv       ← 자산별 BEFORE/AFTER
#
# [실행] python v25_stage4k_atom_only_tier_sim.py
# =========================================================
import os
from pathlib import Path
import pandas as pd
import numpy as np


# === 환경 ===
OUTDIR = Path("yahoo_index_v25_stage4k_outputs")
PREFIX = "v25_stage4k"
TRADES_CSV     = OUTDIR / f"{PREFIX}_trades.csv"
CANDIDATES_CSV = OUTDIR / f"{PREFIX}_all_candidates.csv"

# === Atom 정의 ===
ATOMS_ALL_12 = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
ATOMS_SYN = [a for a in ATOMS_ALL_12 if a != "a_room"]   # 11 atoms
CORE4 = ["a_score_ge13", "a_fvg", "a_pre_total_ge4", "a_wick_le_q1"]
NON_OVERLAP_ATOMS = [a for a in ATOMS_SYN if a != "a_overlap"]

PF_INF_CAP = 50.0
INITIAL_USD = 2222.22


# =========================================================
# ★ atom-only 진입 룰 + tier 함수 (백테 본체 import 가능) ★
# =========================================================
def evaluate_atomic_filter(atoms: dict) -> tuple:
    """
    Atom 패턴만으로 진입/차단/tier 결정.
    
    Args:
        atoms: {'a_score_ge13': True, 'a_fvg': False, ...}  (a_room 무시됨)
    Returns:
        (decision, label):
          decision: 'TAKE' or 'SKIP'
          label: TIER_S / TIER_A / TIER_B / TIER_C / TIER_OVERLAP   (TAKE)
                 no_atom_pass / K_le_3 / K{K}_no_core               (SKIP)
    """
    # K = atom PASS 갯수 (a_room 제외)
    K = sum(1 for a in ATOMS_SYN if atoms.get(a, False))
    # CORE 카운트 (CORE 4 중 PASS 갯수)
    core_count = sum(1 for a in CORE4 if atoms.get(a, False))
    # overlap solo 판정
    overlap = atoms.get("a_overlap", False)
    others_excl_overlap = any(atoms.get(a, False) for a in NON_OVERLAP_ATOMS)
    overlap_solo = overlap and not others_excl_overlap

    # ── 진입 게이트 ──
    if K == 0:
        return ("SKIP", "no_atom_pass")

    # ── overlap solo 예외 ──
    if overlap_solo:
        return ("TAKE", "TIER_OVERLAP")

    # ── 차단 (손실 분석 기반) ──
    if K <= 3:
        return ("SKIP", "K_le_3")
    if core_count == 0:
        return ("SKIP", f"K{K}_no_core")

    # ── Tier 분류 (CORE ≥ 1 보장) ──
    if K >= 7:
        return ("TAKE", "TIER_S")
    if K >= 5:
        if core_count >= 2:
            return ("TAKE", "TIER_A")
        else:
            return ("TAKE", "TIER_B")
    # K == 4
    return ("TAKE", "TIER_C")


# =========================================================
# Helpers
# =========================================================
def _to_bool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def stats(net_pnl, r):
    n = len(net_pnl)
    if n == 0:
        return {"trades": 0, "win_pct": 0.0, "avg_R": 0.0, "median_R": 0.0,
                "PF": 0.0, "total_pnl": 0.0}
    g_p = float(net_pnl[net_pnl > 0].sum())
    g_l = float(abs(net_pnl[net_pnl < 0].sum()))
    pf = g_p / max(g_l, 1e-9) if g_l > 0 else (PF_INF_CAP if g_p > 0 else 0.0)
    return {
        "trades":   n,
        "win_pct":  float((net_pnl > 0).mean() * 100),
        "avg_R":    float(r.mean()),
        "median_R": float(np.median(r)),
        "PF":       float(min(pf, PF_INF_CAP)),
        "total_pnl": float(net_pnl.sum()),
    }


def equity_dd_usd(arr, initial=INITIAL_USD):
    if len(arr) == 0:
        return {"final_usd": initial, "max_dd_abs": 0.0, "max_dd_pct": 0.0,
                "return_pct": 0.0}
    cum = arr.cumsum() + initial
    rmax = np.maximum.accumulate(cum)
    dd = cum - rmax
    return {
        "final_usd":  float(cum[-1]),
        "max_dd_abs": float(dd.min()),
        "max_dd_pct": float((dd / rmax * 100).min()),
        "return_pct": float((cum[-1] - initial) / initial * 100),
    }


def equity_dd_R(arr):
    if len(arr) == 0:
        return {"final_R": 0.0, "max_dd_R": 0.0}
    cumR = arr.cumsum()
    rmax = np.maximum.accumulate(cumR)
    return {
        "final_R":  float(cumR[-1]),
        "max_dd_R": float((cumR - rmax).min()),
    }


# =========================================================
# Main
# =========================================================
if __name__ == "__main__":
    print("=" * 100)
    print("# v25 Stage 4K — ATOM-ONLY TIER REDESIGN (기존 tier 완전 무시)")
    print("=" * 100)
    print(f"#   trades CSV     : {TRADES_CSV}")
    print(f"#   candidates CSV : {CANDIDATES_CSV}")
    print()

    if not TRADES_CSV.exists() or not CANDIDATES_CSV.exists():
        print(f"[ERROR] 입력 파일 없음 in {OUTDIR}/")
        raise SystemExit(1)

    trades = pd.read_csv(TRADES_CSV)
    candidates = pd.read_csv(CANDIDATES_CSV)

    for c in [f"atoms_{a}" for a in ATOMS_ALL_12]:
        candidates[c] = _to_bool(candidates[c])
    candidates = candidates.rename(columns={f"atoms_{a}": a for a in ATOMS_ALL_12})

    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    candidates["entry_time"] = pd.to_datetime(candidates["entry_time"])

    cols_t = ["trade_id", "symbol_key", "entry_time", "side", "tier_label",
              "r_multiple", "net_pnl", "run_potential"]
    cols_c = ["symbol_key", "entry_time", "side"] + ATOMS_ALL_12
    tdf = pd.merge(trades[cols_t], candidates[cols_c],
                   on=["symbol_key", "entry_time", "side"], how="left")
    for c in ATOMS_ALL_12:
        tdf[c] = tdf[c].fillna(False).astype(bool)
    tdf = tdf.sort_values("entry_time").reset_index(drop=True)
    print(f"[LOAD] joined trades = {len(tdf)}")

    # ── 새 룰 적용 ──
    decisions, labels = [], []
    K_list, core_list = [], []
    for _, row in tdf.iterrows():
        atoms = {a: bool(row[a]) for a in ATOMS_ALL_12}
        d, lbl = evaluate_atomic_filter(atoms)
        decisions.append(d)
        labels.append(lbl)
        K_list.append(sum(1 for a in ATOMS_SYN if atoms.get(a, False)))
        core_list.append(sum(1 for a in CORE4 if atoms.get(a, False)))
    tdf["decision"] = decisions
    tdf["new_tier"] = labels
    tdf["K_pass"] = K_list
    tdf["CORE_pass"] = core_list

    take_df = tdf[tdf["decision"] == "TAKE"].copy().reset_index(drop=True)
    skip_df = tdf[tdf["decision"] == "SKIP"].copy().reset_index(drop=True)

    # ── BEFORE vs AFTER ──
    base_st = stats(tdf["net_pnl"].values, tdf["r_multiple"].values)
    take_st = stats(take_df["net_pnl"].values, take_df["r_multiple"].values)
    skip_st = stats(skip_df["net_pnl"].values, skip_df["r_multiple"].values)

    base_eq = equity_dd_usd(tdf["net_pnl"].values)
    take_eq = equity_dd_usd(take_df["net_pnl"].values)
    base_R = equity_dd_R(tdf["r_multiple"].values)
    take_R = equity_dd_R(take_df["r_multiple"].values)

    print()
    print("=" * 100)
    print("[BEFORE vs AFTER]")
    print("=" * 100)
    print(f"{'Metric':<22} {'BEFORE':>20} {'AFTER (TAKE)':>20} {'SKIP (제거)':>20}")
    print("-" * 100)
    rows = [
        ("trades",       base_st['trades'],   take_st['trades'],   skip_st['trades'], 'd'),
        ("win_pct (%)",  base_st['win_pct'],  take_st['win_pct'],  skip_st['win_pct'], '.2f'),
        ("avg_R",        base_st['avg_R'],    take_st['avg_R'],    skip_st['avg_R'], '.3f'),
        ("median_R",     base_st['median_R'], take_st['median_R'], skip_st['median_R'], '.3f'),
        ("PF",           base_st['PF'],       take_st['PF'],       skip_st['PF'], '.3f'),
        ("total_pnl USD", base_st['total_pnl'], take_st['total_pnl'], skip_st['total_pnl'], ',.2f'),
    ]
    for name, b, t, s, fmt in rows:
        if fmt == 'd':
            print(f"{name:<22} {b:>20} {t:>20} {s:>20}")
        else:
            print(f"{name:<22} {b:>20{fmt}} {t:>20{fmt}} {s:>20{fmt}}")
    print(f"{'final_usd':<22} {base_eq['final_usd']:>20,.2f} {take_eq['final_usd']:>20,.2f} {'—':>20}")
    print(f"{'return_pct':<22} {base_eq['return_pct']:>20.2f} {take_eq['return_pct']:>20.2f} {'—':>20}")
    print(f"{'max_dd_pct':<22} {base_eq['max_dd_pct']:>20.2f} {take_eq['max_dd_pct']:>20.2f} {'—':>20}")
    print(f"{'cum_R':<22} {base_R['final_R']:>20.2f} {take_R['final_R']:>20.2f} {'—':>20}")
    print(f"{'max_dd_R':<22} {base_R['max_dd_R']:>20.2f} {take_R['max_dd_R']:>20.2f} {'—':>20}")

    # ── TAKE Tier 분포 ──
    print()
    print("=" * 100)
    print("[TAKE Tier 분포] — 새 atom-only tier")
    print("=" * 100)
    tier_rows = []
    for t in ["TIER_S", "TIER_A", "TIER_B", "TIER_C", "TIER_OVERLAP"]:
        sub = take_df[take_df["new_tier"] == t]
        if len(sub) == 0:
            continue
        st = stats(sub["net_pnl"].values, sub["r_multiple"].values)
        st["tier"] = t
        st["pct_of_take"] = round(st["trades"] / len(take_df) * 100, 2) if len(take_df) > 0 else 0
        tier_rows.append(st)
    tier_df = pd.DataFrame(tier_rows)
    print(tier_df[["tier", "trades", "pct_of_take", "win_pct", "avg_R", "median_R", "PF", "total_pnl"]].round(3).to_string(index=False))

    # ── SKIP reason 분포 ──
    print()
    print("=" * 100)
    print("[SKIP reason 분포]")
    print("=" * 100)
    skip_rows = []
    for r in skip_df["new_tier"].unique():
        sub = skip_df[skip_df["new_tier"] == r]
        st = stats(sub["net_pnl"].values, sub["r_multiple"].values)
        st["reason"] = r
        st["pct_of_skip"] = round(st["trades"] / len(skip_df) * 100, 2) if len(skip_df) > 0 else 0
        skip_rows.append(st)
    skip_grp_df = pd.DataFrame(skip_rows).sort_values("trades", ascending=False)
    print(skip_grp_df[["reason", "trades", "pct_of_skip", "win_pct", "PF", "total_pnl"]].round(3).to_string(index=False))

    # ── 자산별 BEFORE/AFTER ──
    print()
    print("=" * 100)
    print("[자산별 BEFORE vs AFTER]")
    print("=" * 100)
    asset_rows = []
    for sym in sorted(tdf["symbol_key"].unique()):
        b = tdf[tdf["symbol_key"] == sym]
        t = take_df[take_df["symbol_key"] == sym]
        b_st = stats(b["net_pnl"].values, b["r_multiple"].values)
        t_st = stats(t["net_pnl"].values, t["r_multiple"].values)
        asset_rows.append({
            "symbol":         sym,
            "before_trades":  b_st["trades"],
            "after_trades":   t_st["trades"],
            "kept_pct":       round(t_st["trades"] / b_st["trades"] * 100, 1) if b_st["trades"] > 0 else 0,
            "before_PF":      round(b_st["PF"], 3),
            "after_PF":       round(t_st["PF"], 3),
            "before_pnl":     round(b_st["total_pnl"], 2),
            "after_pnl":      round(t_st["total_pnl"], 2),
            "pnl_delta":      round(t_st["total_pnl"] - b_st["total_pnl"], 2),
        })
    asset_df = pd.DataFrame(asset_rows)
    print(asset_df.to_string(index=False))

    # ── Side ──
    print()
    print("=" * 100)
    print("[Side 별 BEFORE vs AFTER]")
    print("=" * 100)
    print(f"{'side':<8} {'before_tr':>10} {'after_tr':>10} {'kept%':>7} "
          f"{'before_PF':>11} {'after_PF':>10} {'before_pnl':>13} {'after_pnl':>13}")
    print("-" * 100)
    for side in ("long", "short"):
        b = tdf[tdf["side"] == side]
        t = take_df[take_df["side"] == side]
        b_st = stats(b["net_pnl"].values, b["r_multiple"].values)
        t_st = stats(t["net_pnl"].values, t["r_multiple"].values)
        kept = round(t_st["trades"] / b_st["trades"] * 100, 1) if b_st["trades"] > 0 else 0
        print(f"{side:<8} {b_st['trades']:>10} {t_st['trades']:>10} {kept:>7.1f} "
              f"{b_st['PF']:>11.3f} {t_st['PF']:>10.3f} "
              f"{b_st['total_pnl']:>13,.2f} {t_st['total_pnl']:>13,.2f}")

    # ── K x CORE 결합 분포 ──
    print()
    print("=" * 100)
    print("[K x CORE 결합 분포] — 진단용 (어디로 분류 가는지)")
    print("=" * 100)
    grp = tdf.groupby(["K_pass", "CORE_pass"]).apply(
        lambda g: pd.Series({
            'n': len(g),
            'PF': round(stats(g['net_pnl'].values, g['r_multiple'].values)['PF'], 3),
            'total_pnl': round(g['net_pnl'].sum(), 2),
            'tier_majority': g['new_tier'].mode().iloc[0] if len(g) > 0 else '',
        })
    ).reset_index()
    print(grp.to_string(index=False))

    # ── CSV 저장 ──
    take_df.to_csv(OUTDIR / f"{PREFIX}_atomtier_TAKE.csv", index=False)
    skip_df.to_csv(OUTDIR / f"{PREFIX}_atomtier_SKIP.csv", index=False)
    summary_rows = [
        {"scenario": "BEFORE", **base_st, **base_eq, **base_R},
        {"scenario": "AFTER (TAKE)", **take_st, **take_eq, **take_R},
        {"scenario": "SKIP (제거)", **skip_st,
         "final_usd": None, "max_dd_abs": None, "max_dd_pct": None,
         "return_pct": None, "final_R": None, "max_dd_R": None},
    ]
    pd.DataFrame(summary_rows).to_csv(OUTDIR / f"{PREFIX}_atomtier_summary.csv", index=False)
    if len(tier_df) > 0:
        tier_df.to_csv(OUTDIR / f"{PREFIX}_atomtier_tier_grp.csv", index=False)
    if len(skip_grp_df) > 0:
        skip_grp_df.to_csv(OUTDIR / f"{PREFIX}_atomtier_skip_grp.csv", index=False)
    asset_df.to_csv(OUTDIR / f"{PREFIX}_atomtier_asset.csv", index=False)
    grp.to_csv(OUTDIR / f"{PREFIX}_atomtier_K_x_CORE.csv", index=False)

    print()
    print("=" * 100)
    print(f"[SAVE] 산출물 → {OUTDIR}/")
    print("=" * 100)
    for f in [f"{PREFIX}_atomtier_summary.csv",
              f"{PREFIX}_atomtier_TAKE.csv",
              f"{PREFIX}_atomtier_SKIP.csv",
              f"{PREFIX}_atomtier_tier_grp.csv",
              f"{PREFIX}_atomtier_skip_grp.csv",
              f"{PREFIX}_atomtier_asset.csv",
              f"{PREFIX}_atomtier_K_x_CORE.csv"]:
        print(f"  - {f}")

    print()
    print("⚠️  시뮬레이션 (기존 trades 후처리). 정확한 결과는 백테 본체에")
    print("   evaluate_atomic_filter() 룰을 import 해서 다시 돌려야 함.")
