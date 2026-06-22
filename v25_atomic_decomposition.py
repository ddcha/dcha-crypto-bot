"""
v25 Stage 4K Atomic Decomposition (지수 엔진)
========================================================
크립토 smc_crypto_stage4d_atomic_decomposition.py 와 동일 frame 적용.
trades.csv (net_pnl) + all_candidates.csv (atoms_a_*) 를 join.

산출물:
  1) v25_atom_solo_effect.csv          — 12 atomic PASS vs FAIL (alpha)
  2) v25_sweep_vol_pivot.csv           — SWEEP+VOL 기준 + atomic PF 변화
  3) v25_tier_decomposition.csv        — Tier 5 atomic + 원본 tier_label
  4) v25_rp_decomposition.csv          — RP 5 atomic + side
  5) v25_rp_level_analysis.csv         — RP0/RP1/RP2+ (side 별)
  6) v25_side_x_atom.csv               — LONG/SHORT × 12 atomic
  7) v25_top_combo_analysis.csv        — 2-3 atomic 조합 brute-force 상위 30
  8) v25_tier_original_vs_atoms.csv    — tier_label × atomic 통과율
  [v25 특화]
  9) v25_symbol_x_atom.csv             — 8 indices × 12 atomic (자산별 atom alpha)
 10) v25_alpha_med_breakdown.csv       — ALPHA_MED 음수 원인 atom-level
 11) v25_overall_summary.csv           — 전체 baseline
"""
import pandas as pd
import numpy as np
from itertools import combinations

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 100)

# ============================================================
# Load & join
# ============================================================
trades = pd.read_csv('/home/claude/trades.csv')
candidates = pd.read_csv('/home/claude/candidates.csv')

# normalize boolean columns in candidates
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

# rename atoms_a_* → a_* (크립토 frame 일치)
rename_map = {c: c.replace('atoms_', '') for c in ATOMS_COLS}
candidates = candidates.rename(columns=rename_map)

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

# join: trades(net_pnl) + candidates(atoms)
trades_key = trades[['trade_id', 'symbol_key', 'entry_time', 'side',
                      'tier_label', 'r_multiple', 'net_pnl', 'run_potential',
                      'result', 'exit_reason']].copy()
cand_key = candidates[['symbol_key', 'entry_time', 'side'] + ATOMS_ALL].copy()

# entry_time 정규화
trades_key['entry_time'] = pd.to_datetime(trades_key['entry_time'])
cand_key['entry_time']  = pd.to_datetime(cand_key['entry_time'])

# merge on (symbol_key, entry_time, side)
tdf = pd.merge(trades_key, cand_key,
               on=['symbol_key', 'entry_time', 'side'],
               how='left')

print(f"Trades: {len(trades)} | Candidates: {len(candidates)} | Joined: {len(tdf)}")
print(f"Atoms join 실패: {tdf['a_sweep'].isna().sum()} 건")

# rename for compat
tdf = tdf.rename(columns={'tier_label': 'tier'})

# fill NaN atoms (혹시 join 실패한 것)
for c in ATOMS_ALL:
    tdf[c] = tdf[c].fillna(False).astype(bool)

OUTDIR = '/home/claude'

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
# Overall baseline
# ============================================================
overall = _stats(tdf)
print()
print("=" * 75)
print("[V25 Stage 4K] 전체 baseline")
print("=" * 75)
print(f"  Trades   : {overall['trades']}")
print(f"  Win%     : {overall['win_pct']:.2f}%")
print(f"  PF       : {overall['PF']:.3f}")
print(f"  avg_R    : {overall['avg_R']:.3f}")
print(f"  total $  : {overall['total_pnl']:,.2f}")

pd.DataFrame([overall]).to_csv(f"{OUTDIR}/v25_overall_summary.csv", index=False)

# ============================================================
# (1) atom_solo_effect
# ============================================================
print()
print("=" * 95)
print("[1] atom_solo_effect — 12 atomic PASS vs FAIL (delta_PF = atom alpha)")
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
solo_df.to_csv(f"{OUTDIR}/v25_atom_solo_effect.csv", index=False)

# ============================================================
# (2) sweep_vol_pivot
# ============================================================
print()
print("=" * 95)
print("[2] sweep_vol_pivot — SWEEP+VOLUME 기준 + atomic 추가 시 효과")
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
pivot_df.to_csv(f"{OUTDIR}/v25_sweep_vol_pivot.csv", index=False)

# ============================================================
# (3) tier_decomposition
# ============================================================
print()
print("=" * 95)
print("[3] tier_decomposition — Tier 5 atomic 기여도 + 원본 tier_label")
print("=" * 95)
print(f"{'group':<22} {'trades':>7} {'win%':>7} {'PF':>7} {'total $':>14}")
print("-" * 95)

td_rows = []
for c in ATOMS_TIER:
    sub = tdf[tdf[c] == True]
    st = _stats(sub)
    td_rows.append({"group_type": "atomic_PASS", "group": c, **st})
    print(f"{c:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
          f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

print("-" * 95)
TIERS_V25 = ["ALPHA_MAX", "ALPHA_HIGH", "ALPHA_MED",
             "SWEEP_ROOM_FVG", "SWEEP_ROOM_ONLY"]
for t in TIERS_V25:
    sub = tdf[tdf["tier"] == t]
    st = _stats(sub)
    td_rows.append({"group_type": "original_tier", "group": t, **st})
    print(f"{'tier='+t:<22} {st['trades']:>7} {st['win_pct']:>6.2f}% "
          f"{st['PF']:>7.3f} {st['total_pnl']:>14,.0f}")

td_df = pd.DataFrame(td_rows).round(4)
td_df.to_csv(f"{OUTDIR}/v25_tier_decomposition.csv", index=False)

# ============================================================
# (4) rp_decomposition
# ============================================================
print()
print("=" * 95)
print("[4] rp_decomposition — RP 5 atomic (LONG / SHORT / ALL)")
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
rpd_df.to_csv(f"{OUTDIR}/v25_rp_decomposition.csv", index=False)

# ============================================================
# (5) rp_level_analysis
# ============================================================
print()
print("=" * 95)
print("[5] rp_level_analysis — RP0 / RP1 / RP2+ 세분 (side 별)")
print("=" * 95)

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

rpl_rows = []
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
rpl_df.to_csv(f"{OUTDIR}/v25_rp_level_analysis.csv", index=False)

# ============================================================
# (6) side_x_atom
# ============================================================
print()
print("=" * 95)
print("[6] side_x_atom — LONG / SHORT 에서 각 atom 의 PASS 효과")
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
sxa_df.to_csv(f"{OUTDIR}/v25_side_x_atom.csv", index=False)

# ============================================================
# (7) top_combo_analysis
# ============================================================
print()
print("=" * 95)
print("[7] top_combo_analysis — 2-3 atomic 조합 brute-force (PF 상위 30)")
print("=" * 95)

MIN_TRADES_COMBO = 30
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
    combo_df.to_csv(f"{OUTDIR}/v25_top_combo_analysis.csv", index=False)

    print(f"{'#':<3} {'size':<5} {'combo':<55} {'trades':>7} "
          f"{'win%':>7} {'PF':>7}")
    print("-" * 95)
    for i, r in combo_df.iterrows():
        cstr = r["combo"][:53] if len(r["combo"]) > 53 else r["combo"]
        print(f"{i+1:<3} {int(r['size']):<5} {cstr:<55} "
              f"{int(r['trades']):>7} {r['win_pct']:>6.2f}% {r['PF']:>7.3f}")
else:
    print("  (min_trades 조건 만족 조합 없음)")

# ============================================================
# (8) tier_original_vs_atoms
# ============================================================
print()
print("=" * 95)
print("[8] tier_original_vs_atoms — 원본 tier_label × atomic 통과율")
print("=" * 95)

tov_rows = []
header = f"{'tier':<18} {'trades':>7}"
for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
    header += f"  {a[:11]:>11}"
print(header)
print("-" * max(len(header), 95))

for t in TIERS_V25:
    sub = tdf[tdf["tier"] == t]
    if len(sub) == 0:
        continue
    row_data = {"tier": t, "trades": len(sub)}
    line = f"{t:<18} {len(sub):>7}"
    for a in ATOMS_TIER + ATOMS_RP + ATOMS_SIG:
        pct = (sub[a] == True).mean() * 100
        row_data[a + "_pct"] = round(pct, 2)
        line += f"  {pct:>10.1f}%"
    tov_rows.append(row_data)
    print(line)

tov_df = pd.DataFrame(tov_rows)
tov_df.to_csv(f"{OUTDIR}/v25_tier_original_vs_atoms.csv", index=False)

# ============================================================
# (9) [V25 특화] symbol_x_atom — 8 indices × atom alpha
# ============================================================
print()
print("=" * 95)
print("[9] symbol_x_atom — 8 indices × 12 atom (자산별 atom alpha)")
print("=" * 95)
print(f"{'symbol':<8} {'atom':<22} {'trades_P':>9} {'win% P':>8} "
      f"{'PF_P':>7} {'PF_F':>7} {'delta_PF':>9} {'total $_P':>12}")
print("-" * 95)

symbol_atom_rows = []
for sym in sorted(tdf["symbol_key"].unique()):
    sym_sub = tdf[tdf["symbol_key"] == sym]
    for c in ATOMS_ALL:
        st_p = _stats(sym_sub[sym_sub[c] == True])
        st_f = _stats(sym_sub[sym_sub[c] == False])
        delta = st_p["PF"] - st_f["PF"]
        symbol_atom_rows.append({
            "symbol": sym, "atom": c,
            "trades_PASS": st_p["trades"], "win_pct_PASS": st_p["win_pct"],
            "PF_PASS": st_p["PF"], "total_pnl_PASS": st_p["total_pnl"],
            "trades_FAIL": st_f["trades"], "PF_FAIL": st_f["PF"],
            "delta_PF": delta,
        })
        print(f"{sym:<8} {c:<22} {st_p['trades']:>9} "
              f"{st_p['win_pct']:>7.2f}% {st_p['PF']:>7.3f} "
              f"{st_f['PF']:>7.3f} {delta:>+9.3f} {st_p['total_pnl']:>12,.0f}")
    print("-" * 95)

sxsx_df = pd.DataFrame(symbol_atom_rows).round(4)
sxsx_df.to_csv(f"{OUTDIR}/v25_symbol_x_atom.csv", index=False)

# ============================================================
# (10) [V25 특화] alpha_med_breakdown — ALPHA_MED 음수 원인
# ============================================================
print()
print("=" * 95)
print("[10] alpha_med_breakdown — ALPHA_MED 음수 원인 atom-level 분해")
print("=" * 95)
am_sub = tdf[tdf["tier"] == "ALPHA_MED"]
am_st = _stats(am_sub)
print(f"  [BASE] ALPHA_MED: {am_st['trades']}t, Win {am_st['win_pct']:.2f}%, "
      f"PF {am_st['PF']:.3f}, total ${am_st['total_pnl']:,.0f}")
print("-" * 95)
print(f"{'atom':<22} {'P_trades':>9} {'P_win%':>8} {'P_PF':>7} {'P_total':>12} "
      f"{'F_trades':>9} {'F_PF':>7} {'F_total':>12}")
print("-" * 95)

am_rows = [{"atom": "ALPHA_MED_BASE", "P_trades": am_st["trades"],
            "P_win_pct": am_st["win_pct"], "P_PF": am_st["PF"],
            "P_total": am_st["total_pnl"], "F_trades": 0, "F_PF": 0, "F_total": 0}]
for c in ATOMS_ALL:
    p = _stats(am_sub[am_sub[c] == True])
    f = _stats(am_sub[am_sub[c] == False])
    am_rows.append({
        "atom": c,
        "P_trades": p["trades"], "P_win_pct": p["win_pct"],
        "P_PF": p["PF"], "P_total": p["total_pnl"],
        "F_trades": f["trades"], "F_PF": f["PF"], "F_total": f["total_pnl"],
    })
    print(f"{c:<22} {p['trades']:>9} {p['win_pct']:>7.2f}% "
          f"{p['PF']:>7.3f} {p['total_pnl']:>12,.0f} "
          f"{f['trades']:>9} {f['PF']:>7.3f} {f['total_pnl']:>12,.0f}")

am_df = pd.DataFrame(am_rows).round(4)
am_df.to_csv(f"{OUTDIR}/v25_alpha_med_breakdown.csv", index=False)

# ============================================================
print()
print("=" * 75)
print("[SAVED] v25 Stage 4K Atomic Decomposition (10개 산출물)")
print("=" * 75)
for f in ["v25_overall_summary.csv",
          "v25_atom_solo_effect.csv",
          "v25_sweep_vol_pivot.csv",
          "v25_tier_decomposition.csv",
          "v25_rp_decomposition.csv",
          "v25_rp_level_analysis.csv",
          "v25_side_x_atom.csv",
          "v25_top_combo_analysis.csv",
          "v25_tier_original_vs_atoms.csv",
          "v25_symbol_x_atom.csv",
          "v25_alpha_med_breakdown.csv"]:
    print(f"  {OUTDIR}/{f}")
print()
print("핵심 산출물: sweep_vol_pivot + top_combo + symbol_x_atom + alpha_med_breakdown")
