"""
v25 OR-Combination & K-of-N Atomic Search
==========================================
크립토 4D / v25 atomic decomposition 후속 분석.
AND 조합은 이미 검증됨 (top_combo_analysis). 이번에는 OR / K-of-N / Hybrid.

산출물:
  1) v25_or_combo_brute.csv      — OR 조합 brute-force (size 2-5) PF 상위 50
  2) v25_kofn_voting.csv         — K-of-N voting (K=3..11)
  3) v25_or_pair_alpha.csv       — OR-pair alpha (PASS PF - FAIL PF)
  4) v25_hybrid_and_of_or.csv    — Hybrid (그룹 내부 OR, 그룹 간 AND) brute-force

a_room 은 항상 True (no-op) → 분석에서 제외. 11 atoms 사용.
"""
import pandas as pd
import numpy as np
from itertools import combinations
import time

pd.set_option('display.width', 220)
pd.set_option('display.max_columns', 100)

# ============================================================
# Load
# ============================================================
trades = pd.read_csv('/home/claude/trades.csv')
candidates = pd.read_csv('/home/claude/candidates.csv')

ATOMS_COLS = [
    "atoms_a_sweep", "atoms_a_volume",
    "atoms_a_pre_total_ge4", "atoms_a_sweep_count_2_4", "atoms_a_score_ge13",
    "atoms_a_wick_le_q1", "atoms_a_pre_total_ge1",
    "atoms_a_trend_align", "atoms_a_mss", "atoms_a_fvg",
    "atoms_a_overlap", "atoms_a_room",
]

def to_bool(s):
    return s.astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])

for c in ATOMS_COLS:
    candidates[c] = to_bool(candidates[c])

candidates = candidates.rename(columns={c: c.replace('atoms_', '') for c in ATOMS_COLS})

ATOMS_ALL_12 = [
    "a_sweep", "a_volume",
    "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
    "a_wick_le_q1", "a_pre_total_ge1",
    "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room",
]
# a_room 은 100% PASS (no-op) → 제외
ATOMS_OR = [a for a in ATOMS_ALL_12 if a != "a_room"]  # 11 atoms

# trades + atoms join
trades['entry_time'] = pd.to_datetime(trades['entry_time'])
candidates['entry_time'] = pd.to_datetime(candidates['entry_time'])
tdf = pd.merge(
    trades[['trade_id', 'symbol_key', 'entry_time', 'side',
            'tier_label', 'r_multiple', 'net_pnl', 'run_potential']],
    candidates[['symbol_key', 'entry_time', 'side'] + ATOMS_ALL_12],
    on=['symbol_key', 'entry_time', 'side'], how='left'
)
for c in ATOMS_ALL_12:
    tdf[c] = tdf[c].fillna(False).astype(bool)

OUTDIR = '/home/claude'

print(f"[LOAD] trades={len(trades)} | joined={len(tdf)} | OR atoms={len(ATOMS_OR)}")

# ============================================================
# Helpers
# ============================================================
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

# ============================================================
# Baseline
# ============================================================
base_st = _stats(tdf)
print()
print("=" * 95)
print(f"[BASELINE] Trades {base_st['trades']} | Win {base_st['win_pct']:.2f}% | "
      f"PF {base_st['PF']:.3f} | avg_R {base_st['avg_R']:.3f} | "
      f"total ${base_st['total_pnl']:,.0f}")
print("=" * 95)

# ============================================================
# (1) Pure OR brute-force (size 2-5)
# ============================================================
print()
print("=" * 95)
print("[1] Pure OR brute-force — size 2-5 (a_room 제외 11 atoms)")
print("=" * 95)
print("OR rule: atom A OR B OR C ... 중 하나라도 PASS 면 trade 포함")
print()

MIN_TRADES_OR = 50
or_rows = []
t0 = time.time()
for size in (2, 3, 4, 5):
    for atoms_sub in combinations(ATOMS_OR, size):
        # OR mask
        mask = pd.Series(False, index=tdf.index)
        for a in atoms_sub:
            mask = mask | (tdf[a] == True)
        sub = tdf[mask]
        if len(sub) < MIN_TRADES_OR:
            continue
        st = _stats(sub)
        or_rows.append({
            "size": size,
            "combo": "|".join(atoms_sub),
            **st,
        })

or_df = pd.DataFrame(or_rows)
print(f"총 OR 조합 (min_trades>={MIN_TRADES_OR}): {len(or_df)} 개 ({time.time()-t0:.1f}s)")

if len(or_df) > 0:
    or_top = or_df.sort_values("PF", ascending=False).head(50).reset_index(drop=True)
    or_top = or_top.round({"win_pct":2, "avg_R":3, "total_pnl":2,
                            "pnl_per_trade":2, "PF":3})
    or_top.to_csv(f"{OUTDIR}/v25_or_combo_brute.csv", index=False)

    print()
    print(f"{'#':<3} {'size':<5} {'OR combo':<70} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>12}")
    print("-" * 120)
    for i, r in or_top.head(30).iterrows():
        cstr = r["combo"][:68] if len(r["combo"]) > 68 else r["combo"]
        print(f"{i+1:<3} {int(r['size']):<5} {cstr:<70} "
              f"{int(r['trades']):>7} {r['win_pct']:>6.2f}% "
              f"{r['PF']:>7.3f} {r['total_pnl']:>12,.0f}")

# ============================================================
# (2) K-of-N voting (K=3..11)
# ============================================================
print()
print("=" * 95)
print("[2] K-of-N voting — 11 atoms 중 K 이상 PASS")
print("=" * 95)

# 각 거래의 PASS 수
tdf['_pass_count'] = tdf[ATOMS_OR].sum(axis=1)
print(f"PASS count 분포:")
print(tdf['_pass_count'].value_counts().sort_index().to_string())

print()
print(f"{'K':<5} {'rule':<22} {'trades':>7} {'win%':>7} {'PF':>7} "
      f"{'avg_R':>7} {'total $':>14} {'vs_BASE_PF':>11}")
print("-" * 95)

kofn_rows = []
for k in range(3, 12):
    sub = tdf[tdf['_pass_count'] >= k]
    st = _stats(sub)
    delta = st['PF'] - base_st['PF']
    kofn_rows.append({
        "K": k,
        "rule": f">=  {k} of {len(ATOMS_OR)}",
        **st,
        "delta_vs_base": delta,
    })
    print(f"{k:<5} {'>= '+str(k)+' of '+str(len(ATOMS_OR)):<22} {st['trades']:>7} "
          f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
          f"{st['avg_R']:>7.3f} {st['total_pnl']:>14,.0f} {delta:>+11.3f}")

# K = 정확히 N
print("-" * 95)
print("정확히 K 만 PASS:")
for k in range(3, 12):
    sub = tdf[tdf['_pass_count'] == k]
    st = _stats(sub)
    if st['trades'] == 0:
        continue
    kofn_rows.append({
        "K": k,
        "rule": f"==  {k} of {len(ATOMS_OR)}",
        **st,
        "delta_vs_base": st['PF'] - base_st['PF'],
    })
    print(f"{k:<5} {'== '+str(k)+' of '+str(len(ATOMS_OR)):<22} {st['trades']:>7} "
          f"{st['win_pct']:>6.2f}% {st['PF']:>7.3f} "
          f"{st['avg_R']:>7.3f} {st['total_pnl']:>14,.0f}")

kofn_df = pd.DataFrame(kofn_rows).round(4)
kofn_df.to_csv(f"{OUTDIR}/v25_kofn_voting.csv", index=False)

# ============================================================
# (3) OR-pair alpha (PASS PF - FAIL PF)
# ============================================================
print()
print("=" * 95)
print("[3] OR-pair alpha — OR-pair PASS vs FAIL (delta_PF)")
print("=" * 95)
print("PASS = pair 중 1+ atom PASS / FAIL = 둘 다 FAIL")
print()
print(f"{'pair':<50} {'P_trades':>9} {'P_PF':>7} {'F_trades':>9} {'F_PF':>7} "
      f"{'delta_PF':>9} {'P_total $':>12}")
print("-" * 120)

pair_rows = []
for a1, a2 in combinations(ATOMS_OR, 2):
    pass_mask = (tdf[a1] == True) | (tdf[a2] == True)
    pass_sub = tdf[pass_mask]
    fail_sub = tdf[~pass_mask]
    st_p = _stats(pass_sub)
    st_f = _stats(fail_sub)
    delta = st_p["PF"] - st_f["PF"]
    pair_rows.append({
        "pair": f"{a1}|{a2}",
        "P_trades": st_p["trades"], "P_win_pct": st_p["win_pct"],
        "P_PF": st_p["PF"], "P_total": st_p["total_pnl"],
        "F_trades": st_f["trades"], "F_PF": st_f["PF"],
        "delta_PF": delta,
    })

pair_df = pd.DataFrame(pair_rows).round(4)
pair_df_sorted = pair_df.sort_values("delta_PF", ascending=False).reset_index(drop=True)
pair_df_sorted.to_csv(f"{OUTDIR}/v25_or_pair_alpha.csv", index=False)

# 상위 15
for _, r in pair_df_sorted.head(15).iterrows():
    print(f"{r['pair']:<50} {int(r['P_trades']):>9} {r['P_PF']:>7.3f} "
          f"{int(r['F_trades']):>9} {r['F_PF']:>7.3f} "
          f"{r['delta_PF']:>+9.3f} {r['P_total']:>12,.0f}")

# ============================================================
# (4) Hybrid AND-of-OR (그룹 내부 OR, 그룹 간 AND)
# ============================================================
print()
print("=" * 95)
print("[4] Hybrid AND-of-OR — 그룹 내부 OR / 그룹 간 AND brute-force")
print("=" * 95)
print("SIG  = (a_sweep, a_volume)                              ← signal")
print("TIER = (a_pre_total_ge4, a_sweep_count_2_4, a_score_ge13, a_wick_le_q1, a_pre_total_ge1)")
print("RP   = (a_trend_align, a_mss, a_fvg, a_overlap)         ← a_room 제외")
print()

GRP_SIG  = ["a_sweep", "a_volume"]
GRP_TIER = ["a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
            "a_wick_le_q1", "a_pre_total_ge1"]
GRP_RP   = ["a_trend_align", "a_mss", "a_fvg", "a_overlap"]

# 각 그룹에서 1+ atom OR subset 모두 탐색
def all_subsets(lst, min_size=1, max_size=None):
    n = len(lst)
    if max_size is None:
        max_size = n
    out = []
    for s in range(min_size, max_size + 1):
        for sub in combinations(lst, s):
            out.append(list(sub))
    return out

sig_subs = all_subsets(GRP_SIG)
tier_subs = all_subsets(GRP_TIER)
rp_subs = all_subsets(GRP_RP)
print(f"SIG subsets: {len(sig_subs)} | TIER subsets: {len(tier_subs)} | RP subsets: {len(rp_subs)}")
print(f"총 hybrid 조합: {len(sig_subs) * len(tier_subs) * len(rp_subs)}")

hybrid_rows = []
MIN_TRADES_HY = 50
t0 = time.time()
for sig in sig_subs:
    sig_mask = pd.Series(False, index=tdf.index)
    for a in sig:
        sig_mask = sig_mask | (tdf[a] == True)
    for tier in tier_subs:
        tier_mask = pd.Series(False, index=tdf.index)
        for a in tier:
            tier_mask = tier_mask | (tdf[a] == True)
        for rp in rp_subs:
            rp_mask = pd.Series(False, index=tdf.index)
            for a in rp:
                rp_mask = rp_mask | (tdf[a] == True)
            mask = sig_mask & tier_mask & rp_mask
            sub = tdf[mask]
            if len(sub) < MIN_TRADES_HY:
                continue
            st = _stats(sub)
            hybrid_rows.append({
                "SIG":  "|".join(sig),
                "TIER": "|".join(tier),
                "RP":   "|".join(rp),
                "n_atoms": len(sig) + len(tier) + len(rp),
                **st,
            })

hybrid_df = pd.DataFrame(hybrid_rows)
print(f"valid hybrid (>={MIN_TRADES_HY} trades): {len(hybrid_df)} 개 ({time.time()-t0:.1f}s)")

if len(hybrid_df) > 0:
    hybrid_top = hybrid_df.sort_values("PF", ascending=False).head(40).reset_index(drop=True)
    hybrid_top = hybrid_top.round({"win_pct":2, "avg_R":3, "total_pnl":2,
                                    "pnl_per_trade":2, "PF":3})
    hybrid_top.to_csv(f"{OUTDIR}/v25_hybrid_and_of_or.csv", index=False)

    print()
    print(f"{'#':<3} {'SIG':<18} {'TIER':<60} {'RP':<35} {'tr':>5} "
          f"{'win%':>6} {'PF':>6} {'total $':>10}")
    print("-" * 175)
    for i, r in hybrid_top.head(25).iterrows():
        sig_s = r["SIG"][:16]
        tier_s = r["TIER"][:58]
        rp_s = r["RP"][:33]
        print(f"{i+1:<3} {sig_s:<18} {tier_s:<60} {rp_s:<35} "
              f"{int(r['trades']):>5} {r['win_pct']:>5.2f}% "
              f"{r['PF']:>6.3f} {r['total_pnl']:>10,.0f}")

# ============================================================
# (5) [추가] Best Single OR-rule (size 2-5) per side
# ============================================================
print()
print("=" * 95)
print("[5] LONG / SHORT 별 OR brute-force PF 상위 10")
print("=" * 95)

side_top_rows = []
for side_val in ("long", "short"):
    side_sub = tdf[tdf["side"] == side_val]
    side_base = _stats(side_sub)
    rows_side = []
    for size in (2, 3, 4):
        for atoms_sub in combinations(ATOMS_OR, size):
            mask = pd.Series(False, index=side_sub.index)
            for a in atoms_sub:
                mask = mask | (side_sub[a] == True)
            sub = side_sub[mask]
            if len(sub) < 30:
                continue
            st = _stats(sub)
            rows_side.append({
                "side": side_val,
                "size": size,
                "combo": "|".join(atoms_sub),
                **st,
                "vs_side_base_PF": st['PF'] - side_base['PF'],
            })
    side_df = pd.DataFrame(rows_side)
    if len(side_df) > 0:
        top = side_df.sort_values("PF", ascending=False).head(10)
        side_top_rows.append(top)
        print()
        print(f"--- {side_val.upper()} (BASE: {side_base['trades']} trades, PF {side_base['PF']:.3f}) ---")
        print(f"{'#':<3} {'size':<5} {'OR combo':<60} {'trades':>7} {'win%':>7} {'PF':>7} {'delta_base':>11}")
        print("-" * 110)
        for i, r in top.reset_index(drop=True).iterrows():
            cstr = r["combo"][:58] if len(r["combo"]) > 58 else r["combo"]
            print(f"{i+1:<3} {int(r['size']):<5} {cstr:<60} "
                  f"{int(r['trades']):>7} {r['win_pct']:>6.2f}% "
                  f"{r['PF']:>7.3f} {r['vs_side_base_PF']:>+11.3f}")

if side_top_rows:
    side_combo_df = pd.concat(side_top_rows, ignore_index=True)
    side_combo_df = side_combo_df.round({"win_pct":2, "avg_R":3, "PF":3,
                                          "total_pnl":2, "pnl_per_trade":2,
                                          "vs_side_base_PF":3})
    side_combo_df.to_csv(f"{OUTDIR}/v25_or_combo_by_side.csv", index=False)

# ============================================================
# Summary
# ============================================================
print()
print("=" * 95)
print("[SAVED] OR / K-of-N / Hybrid 산출물")
print("=" * 95)
for f in ["v25_or_combo_brute.csv",
          "v25_kofn_voting.csv",
          "v25_or_pair_alpha.csv",
          "v25_hybrid_and_of_or.csv",
          "v25_or_combo_by_side.csv"]:
    print(f"  {OUTDIR}/{f}")
