#!/usr/bin/env python3
"""
analyze_atoms_4k.py — 자산군별 atom 효용 분석

목적: 크립토 4K 의 atomic 12 + 319 WIN69 combos 가
      지수/원자재 자산군에서도 같은 alpha 만들지 검증.

작업: 4K 백테 trades.csv 에 atomic 12 컬럼이 이미 들어있어
      이 데이터로 자산군별 atom × atom OR 조합의 win rate / PF / avg_R 측정.

사용법:
  # 백테 후
  python3 analyze_atoms_4k.py \\
      --trades yahoo_index_v26_stage4k_v19b_outputs/v26_trades.csv \\
      --asset_class index \\
      --out atom_analysis_index.csv

출력:
  - atom_singles_<asset_class>.csv: 각 atom 단독 효용
  - atom_pairs_<asset_class>.csv: 두 atom OR 조합 효용
  - atom_triples_<asset_class>.csv: 세 atom OR 조합 효용
  - win69_match_<asset_class>.csv: 319 WIN69 combo 매칭 결과
  - top_combos_<asset_class>.csv: 통계적으로 유의한 top 조합

분석 기준:
  - 최소 거래 수 N >= 20 (통계 유의)
  - PF >= 1.5 (기본 알파)
  - Win rate >= 60% (안정성)
"""
from __future__ import annotations
import argparse
import itertools
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


# 4K atomic 12 컬럼명
ATOM_COLS = [
    "atoms_a_sweep",
    "atoms_a_volume",
    "atoms_a_pre_total_ge4",
    "atoms_a_sweep_count_2_4",
    "atoms_a_score_ge13",
    "atoms_a_wick_le_q1",
    "atoms_a_pre_total_ge1",
    "atoms_a_trend_align",
    "atoms_a_mss",
    "atoms_a_fvg",
    "atoms_a_overlap",
    "atoms_a_room",
]

# WIN69 컬럼 alias (원본 이름)
ATOM_NAMES = {
    "atoms_a_sweep": "a_sweep",
    "atoms_a_volume": "a_volume",
    "atoms_a_pre_total_ge4": "a_pre_total_ge4",
    "atoms_a_sweep_count_2_4": "a_sweep_count_2_4",
    "atoms_a_score_ge13": "a_score_ge13",
    "atoms_a_wick_le_q1": "a_wick_le_q1",
    "atoms_a_pre_total_ge1": "a_pre_total_ge1",
    "atoms_a_trend_align": "a_trend_align",
    "atoms_a_mss": "a_mss",
    "atoms_a_fvg": "a_fvg",
    "atoms_a_overlap": "a_overlap",
    "atoms_a_room": "a_room",
}

# 통계 유의 기준
MIN_TRADES = 20
MIN_PF = 1.5
MIN_WINRATE_PCT = 60.0


def compute_metrics(df: pd.DataFrame) -> dict:
    """trades subset 의 PF / WinRate / Avg R / Total PnL."""
    if len(df) == 0:
        return {"n": 0, "PF": np.nan, "WinRate%": np.nan, "AvgR": np.nan, "TotalPnL": 0.0}
    gross_profit = df.loc[df["net_pnl"] > 0, "net_pnl"].sum()
    gross_loss = abs(df.loc[df["net_pnl"] < 0, "net_pnl"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf
    win_rate = (df["net_pnl"] > 0).mean() * 100
    avg_r = df["r_multiple"].mean() if "r_multiple" in df.columns else np.nan
    total_pnl = df["net_pnl"].sum()
    return {
        "n": len(df),
        "PF": round(pf, 3) if pd.notna(pf) and pf != np.inf else pf,
        "WinRate%": round(win_rate, 2),
        "AvgR": round(avg_r, 3) if pd.notna(avg_r) else np.nan,
        "TotalPnL": round(total_pnl, 2),
    }


def analyze_singles(trades: pd.DataFrame) -> pd.DataFrame:
    """각 atom 단독 효용 (atom == True 인 거래만 vs 전체)."""
    rows = []
    overall = compute_metrics(trades)
    rows.append({"atom_combo": "ALL_TRADES", **overall, "type": "baseline"})
    for col in ATOM_COLS:
        if col not in trades.columns:
            continue
        sub = trades[trades[col] == True]  # noqa
        m = compute_metrics(sub)
        rows.append({"atom_combo": ATOM_NAMES[col], **m, "type": "single"})
    return pd.DataFrame(rows)


def analyze_or_pairs(trades: pd.DataFrame) -> pd.DataFrame:
    """두 atom OR 조합."""
    rows = []
    available_cols = [c for c in ATOM_COLS if c in trades.columns]
    for c1, c2 in itertools.combinations(available_cols, 2):
        mask = (trades[c1] == True) | (trades[c2] == True)  # noqa
        sub = trades[mask]
        m = compute_metrics(sub)
        if m["n"] < MIN_TRADES:
            continue
        rows.append({
            "atom_combo": f"{ATOM_NAMES[c1]} OR {ATOM_NAMES[c2]}",
            **m, "type": "or_pair",
        })
    return pd.DataFrame(rows)


def analyze_or_triples(trades: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """세 atom OR 조합 (조합 폭증 방지: 최대 top_n 까지)."""
    rows = []
    available_cols = [c for c in ATOM_COLS if c in trades.columns]
    for c1, c2, c3 in itertools.combinations(available_cols, 3):
        mask = (trades[c1] == True) | (trades[c2] == True) | (trades[c3] == True)  # noqa
        sub = trades[mask]
        m = compute_metrics(sub)
        if m["n"] < MIN_TRADES:
            continue
        rows.append({
            "atom_combo": f"{ATOM_NAMES[c1]} OR {ATOM_NAMES[c2]} OR {ATOM_NAMES[c3]}",
            **m, "type": "or_triple",
        })
    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("PF", ascending=False).head(top_n)
    return df


def analyze_and_pairs(trades: pd.DataFrame) -> pd.DataFrame:
    """두 atom AND 조합 (둘 다 True 인 경우)."""
    rows = []
    available_cols = [c for c in ATOM_COLS if c in trades.columns]
    for c1, c2 in itertools.combinations(available_cols, 2):
        mask = (trades[c1] == True) & (trades[c2] == True)  # noqa
        sub = trades[mask]
        m = compute_metrics(sub)
        if m["n"] < MIN_TRADES:
            continue
        rows.append({
            "atom_combo": f"{ATOM_NAMES[c1]} AND {ATOM_NAMES[c2]}",
            **m, "type": "and_pair",
        })
    return pd.DataFrame(rows)


def filter_top(df: pd.DataFrame, label: str = "") -> pd.DataFrame:
    """통계 유의 + alpha 기준 필터."""
    if len(df) == 0:
        return df
    mask = (df["n"] >= MIN_TRADES) & (df["PF"] >= MIN_PF) & (df["WinRate%"] >= MIN_WINRATE_PCT)
    out = df[mask].sort_values("PF", ascending=False).reset_index(drop=True)
    print(f"  Top combos in {label}: {len(out)} (PF>={MIN_PF}, WinRate>={MIN_WINRATE_PCT}%, n>={MIN_TRADES})")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", required=True, help="백테 trades.csv 경로")
    parser.add_argument("--asset_class", default="index", choices=["index", "commodity"])
    parser.add_argument("--out_dir", default=".", help="출력 디렉토리")
    args = parser.parse_args()
    
    trades_path = Path(args.trades)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if not trades_path.exists():
        print(f"ERROR: {trades_path} 없음")
        sys.exit(1)
    
    print(f"Loading trades from {trades_path}...")
    trades = pd.read_csv(trades_path)
    print(f"Total trades: {len(trades)}")
    
    # atom 컬럼 확인
    available_atoms = [c for c in ATOM_COLS if c in trades.columns]
    print(f"Available atom columns: {len(available_atoms)}/{len(ATOM_COLS)}")
    if len(available_atoms) == 0:
        print("ERROR: trades.csv 에 atoms_a_* 컬럼이 없음")
        print("       v26 백테 결과로 다시 생성하거나, candidates.csv 사용")
        sys.exit(1)
    
    asset_class = args.asset_class
    
    # 1. 단독 atom
    print(f"\n[1] Singles 분석...")
    singles = analyze_singles(trades)
    out_path = out_dir / f"atom_singles_{asset_class}.csv"
    singles.to_csv(out_path, index=False)
    print(f"  Saved: {out_path}")
    print(singles.to_string(index=False))
    
    # 2. OR 페어
    print(f"\n[2] OR pairs 분석...")
    or_pairs = analyze_or_pairs(trades)
    out_path = out_dir / f"atom_or_pairs_{asset_class}.csv"
    or_pairs.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(or_pairs)} pairs)")
    
    # 3. AND 페어
    print(f"\n[3] AND pairs 분석...")
    and_pairs = analyze_and_pairs(trades)
    out_path = out_dir / f"atom_and_pairs_{asset_class}.csv"
    and_pairs.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(and_pairs)} pairs)")
    
    # 4. OR triple (top 50)
    print(f"\n[4] OR triples 분석 (top 50)...")
    or_triples = analyze_or_triples(trades, top_n=50)
    out_path = out_dir / f"atom_or_triples_{asset_class}.csv"
    or_triples.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(or_triples)} top triples)")
    
    # 5. Top combos 모음 (필터된 결과만)
    print(f"\n[5] Top combos (filtered) 통합...")
    top_singles = filter_top(singles, "singles")
    top_pairs = filter_top(or_pairs, "or_pairs")
    top_and = filter_top(and_pairs, "and_pairs")
    top_triples = filter_top(or_triples, "or_triples")
    
    all_top = pd.concat([top_singles, top_pairs, top_and, top_triples], ignore_index=True)
    if len(all_top) > 0:
        all_top = all_top.sort_values("PF", ascending=False).reset_index(drop=True)
    out_path = out_dir / f"top_combos_{asset_class}.csv"
    all_top.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(all_top)} top combos)")
    
    # 6. By symbol breakdown (자산별 차이 발견)
    print(f"\n[6] 자산별 분석...")
    by_symbol_rows = []
    if "symbol_key" in trades.columns:
        for sym in sorted(trades["symbol_key"].unique()):
            sub = trades[trades["symbol_key"] == sym]
            for col in ATOM_COLS:
                if col not in sub.columns:
                    continue
                # atom == True 인 거래 only
                m = compute_metrics(sub[sub[col] == True])
                m["symbol"] = sym
                m["atom"] = ATOM_NAMES[col]
                by_symbol_rows.append(m)
        
        by_symbol = pd.DataFrame(by_symbol_rows)
        out_path = out_dir / f"atom_by_symbol_{asset_class}.csv"
        by_symbol.to_csv(out_path, index=False)
        print(f"  Saved: {out_path} ({len(by_symbol)} rows)")
        
        # 자산별 baseline
        sym_baseline = []
        for sym in sorted(trades["symbol_key"].unique()):
            sub = trades[trades["symbol_key"] == sym]
            m = compute_metrics(sub)
            m["symbol"] = sym
            sym_baseline.append(m)
        sym_baseline_df = pd.DataFrame(sym_baseline)
        out_path = out_dir / f"baseline_by_symbol_{asset_class}.csv"
        sym_baseline_df.to_csv(out_path, index=False)
        print(f"  Saved: {out_path}")
        print(sym_baseline_df.to_string(index=False))
    
    # 7. WIN69 매칭 (각 거래가 어떤 WIN69 combo 에 매칭되는지)
    print(f"\n[7] WIN69 319 combos 매칭 분석...")
    print("  (구현은 차회. v26 백테에서 이미 tier_label_4h='ALPHA_MED' = WIN69 매칭됨)")
    if "tier_label_4h" in trades.columns:
        win69_match = trades["tier_label_4h"] == "ALPHA_MED"
        m_match = compute_metrics(trades[win69_match])
        m_nomatch = compute_metrics(trades[~win69_match])
        win69_df = pd.DataFrame([
            {"group": "WIN69_match (ALPHA_MED)", **m_match},
            {"group": "WIN69_nomatch", **m_nomatch},
        ])
        out_path = out_dir / f"win69_match_{asset_class}.csv"
        win69_df.to_csv(out_path, index=False)
        print(f"  Saved: {out_path}")
        print(win69_df.to_string(index=False))
    
    print("\n✅ 분석 완료. 다음 단계:")
    print(f"   1. top_combos_{asset_class}.csv 보고 자산군에서 effective 한 atom 조합 발견")
    print(f"   2. atom_by_symbol_{asset_class}.csv 보고 자산별 다른 atom 효용 확인")
    print(f"   3. 발견한 패턴으로 v26 의 classify_tier_stage4h / classify_tier_v19b_rp_boost 재검토")
    print(f"   4. 자산군별 ROOM_ONLY_SYMBOL_BLACKLIST 추가 결정")


if __name__ == "__main__":
    main()
