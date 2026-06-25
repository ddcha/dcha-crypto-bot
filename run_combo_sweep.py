#!/usr/bin/env python3
# =========================================================================
# run_combo_sweep.py — 원자 조합 "진짜 게이트" 스윕 + 시드500 자본 시뮬
#
#   각 조합 = 그 원자들이 전부 True 여야 진입하는 AND 게이트(ATOM_AND_LIST).
#   generate_candidates_from_prepared 내부(L423)서 per-call 로 ATOM_AND_LIST 를 읽어
#   _atom_and_pass 로 적용(슬롯 재배치 반영, post-hoc 아님). + r_multiple 기반 자본 시뮬.
#
# [사용법]  (repo 루트 D:\smc_bot 에서)
#   # HEAD=5 먼저 검증:
#   set STAGE4D_DLCACHE=data_cache & set HEAD=5 & python run_combo_sweep.py
#   # 전체:
#   set STAGE4D_DLCACHE=data_cache & set HEAD= & python run_combo_sweep.py
#   # 조합파일/결과파일 경로 override: COMBOS_JSON, RESULTS_CSV
#   # 중간 중단 후 재실행하면 RESULTS_CSV 완료분은 건너뜀(resume).
#
# [자본 시뮬] 시드500 + 월말250×5(다음달 1일 00:00 도착, 총납입1750), RISK_PCT=0.01 flat.
#   진입 사이징 = 그 시점 실현자본(완료 청산손익+도착 입금)만. 이벤트순 진입<입금<청산.
#   test_capital_no_lookahead: 6분할×50변조 불일치0 (스윕 시작 전 1회 통과 필수).
# =========================================================================
import os
import sys
import json
import time
import csv

# ── baseline env (config import 前 설정; 외부 env 우선) ──
os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "USE_COMBO_UNION", "COMBO_KEY", "ATOM_GATE_RULE"):
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd

from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
from smc_stage4d.simulation import (
    generate_candidates_from_prepared,
    simulate_scenario_v19b_rpboost,
)

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
COMBOS_JSON = os.environ.get("COMBOS_JSON", "combos_filtered.json")
RESULTS_CSV = os.environ.get("RESULTS_CSV", "combo_sweep_results.csv")
HEAD = int(os.environ.get("HEAD", "0"))
CHUNK_N = int(os.environ.get("CHUNK_N", "1"))   # 병렬: 전체를 CHUNK_N 등분
CHUNK_I = int(os.environ.get("CHUNK_I", "0"))   #       그 중 i번째만 처리(interleaved)
PROGRESS_EVERY = 20

REST6_EXCLUDE = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}   # 나머지6 = 이 3 제외
YEARS = [2022, 2023, 2024, 2025, 2026]
SEED, MONTHLY, NDEP, RISK_PCT = 500.0, 250.0, 5, 0.01
TOTAL_DEP = SEED + MONTHLY * NDEP   # 1750

FIELDS = (["key", "atoms", "k", "n", "win_pct", "PF", "IS_PF", "OOS_PF", "oosN",
           "avgR", "Sharpe", "r6_PF"]
          + [f"pf_{y}" for y in YEARS]
          + ["years_traded", "all_years_ge1",
             "final_cap", "mult_vs_dep", "CAGR_pct", "MDD_pct", "err"])


# ── 지표 ─────────────────────────────────────────────────────────────────
def _pf(pnl):
    pnl = np.asarray(pnl, float)
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def _realized(trades):
    if "exit_reason" in trades.columns:
        return trades[~trades["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return trades


# ── 자본 시뮬 (시드500 flat, 룩어헤드 안전) ──────────────────────────────
def run_equity(g, rvals, seed=SEED, monthly=MONTHLY, nd=NDEP, rp=RISK_PCT):
    """g: entry_time/exit_time(tz-aware UTC) 정렬불요. 반환 (eq_at_entry dict, final, mdd)."""
    ET = list(g["entry_time"]); XT = list(g["exit_time"])
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = start
    for _ in range(nd):
        m = m + pd.offsets.MonthBegin(1); deps.append((m, monthly))   # 다음달 1일 00:00 도착
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 0, i)); ev.append((XT[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]
    ev.sort(key=lambda x: (x[0], x[1]))                # 진입(0)<입금(1)<청산(2)
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * realized; eq[p] = realized    # 사이징 = 현재 실현자본
        elif pri == 1:
            realized += (-p)
        else:
            realized += rvals[p] * ra.get(p, 0.0)
            peak = max(peak, realized); mdd = min(mdd, (realized - peak) / peak)
    return eq, realized, mdd


def test_capital_no_lookahead(g):
    """진입(entry≤T)의 사이징자본이, T 이후 청산되는 거래 r 변조에 불변인지. 6분할×50, 불일치0."""
    ET = g["entry_time"]; XT = g["exit_time"]; r_base = g["r_multiple"].values.astype(float)
    eq0, _, _ = run_equity(g, r_base)
    rng = np.random.default_rng(7)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01",
                             "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (XT >= T).values
        past = g.index[ET <= T]
        for _ in range(50):
            r2 = r_base.copy()
            if fut.any():
                r2[fut] = rng.uniform(-5, 5, int(fut.sum()))
            eq1, _, _ = run_equity(g, r2)
            for i in past:
                checked += 1
                if abs(eq0.get(i, 0.0) - eq1.get(i, 0.0)) > 1e-9:
                    mism += 1
    return mism, checked


def compute_row(key, atoms, trades):
    row = {f: "" for f in FIELDS}
    row["key"] = key; row["atoms"] = "+".join(atoms); row["k"] = len(atoms)
    if trades is None or len(trades) == 0:
        row["n"] = 0; row["all_years_ge1"] = False
        return row
    d = _realized(trades).copy()
    if len(d) == 0:
        row["n"] = 0; row["all_years_ge1"] = False
        return row
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values
    rr = d["r_multiple"].astype(float).values
    n = len(d); k = int(n * 0.7)

    row["n"] = n
    row["win_pct"] = round(float((pnl > 0).mean() * 100), 2)
    row["PF"] = round(_pf(pnl), 4)
    row["IS_PF"] = round(_pf(pnl[:k]), 4) if k > 0 else ""
    row["OOS_PF"] = round(_pf(pnl[k:]), 4) if n - k > 0 else ""
    row["oosN"] = n - k
    row["avgR"] = round(float(rr.mean()), 4)
    row["Sharpe"] = round(float(rr.mean() / rr.std(ddof=1)), 4) if n > 1 and rr.std(ddof=1) > 0 else ""
    if "symbol" in d.columns:
        d6 = d[~d["symbol"].isin(REST6_EXCLUDE)]
        row["r6_PF"] = round(_pf(d6["net_pnl"].astype(float).values), 4) if len(d6) else ""

    yr = d["exit_time"].dt.year
    all_ge1 = True; any_year = False
    for y in YEARS:
        sub = d[yr == y]
        if len(sub) > 0:
            pfy = _pf(sub["net_pnl"].astype(float).values)
            row[f"pf_{y}"] = round(pfy, 4); any_year = True
            if not (pfy >= 1.0):
                all_ge1 = False
    row["years_traded"] = int((pd.Series([len(d[yr == y]) for y in YEARS]) > 0).sum())
    row["all_years_ge1"] = bool(all_ge1 and any_year)

    # ── 자본 시뮬 (시드500 flat) — entry_time 기준 정렬본으로 ──
    de = d.sort_values("entry_time").reset_index(drop=True)
    _, final, mdd = run_equity(de, de["r_multiple"].astype(float).values)
    yrs = max((de["exit_time"].max() - de["entry_time"].min()).days / 365.25, 1e-9)
    row["final_cap"] = round(final, 2)
    row["mult_vs_dep"] = round(final / TOTAL_DEP, 4)
    row["CAGR_pct"] = round(((final / TOTAL_DEP) ** (1 / yrs) - 1) * 100, 2) if final > 0 else ""
    row["MDD_pct"] = round(mdd * 100, 2)
    return row


def load_done(path):
    done = set()
    if os.path.exists(path):
        try:
            prev = pd.read_csv(path)
            if "key" in prev.columns:
                done = set(prev["key"].astype(str).tolist())
        except Exception as e:
            print(f"[warn] {path} 읽기 실패({e}) — resume 없이")
    return done


def append_row(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row); f.flush()


def gate_atoms_ok(atoms, trades):
    if trades is None or len(trades) == 0:
        return "no-trades"
    bad = [a for a in atoms if (a not in trades.columns) or (not bool(trades[a].astype(bool).all()))]
    return "OK" if not bad else "FAIL:" + ",".join(bad)


def run_combo(prepared, atoms):
    os.environ["ATOM_AND_LIST"] = ",".join(atoms)
    os.environ["ATOM_OR_LIST"] = ""
    cand = {sym: generate_candidates_from_prepared(prepared[sym]) for sym in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    return res["trades"]


def main():
    if not os.path.exists(COMBOS_JSON):
        print(f"[ERROR] 조합 파일 없음: {COMBOS_JSON}"); sys.exit(1)
    combos = json.load(open(COMBOS_JSON, encoding="utf-8"))
    if HEAD > 0:
        combos = combos[:HEAD]; print(f"[HEAD] 앞 {HEAD}개만")
    if CHUNK_N > 1:
        combos = [c for idx, c in enumerate(combos) if idx % CHUNK_N == CHUNK_I]
        print(f"[CHUNK] {CHUNK_I}/{CHUNK_N} → {len(combos)}개 처리")

    done = load_done(RESULTS_CSV)
    print(f"[INFO] 조합 {len(combos)} | 완료 {len(done)}(resume) | 심볼 {len(SYMBOLS)}개")
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} | risk_mult=1.0 | 자본 시드{SEED}+{MONTHLY}x{NDEP}")

    # STEP1: 데이터+지표 9심볼 1회
    print("\n[STEP1] 데이터 + apply_indicators_and_build (9심볼 1회)")
    t0 = time.time(); prepared = {}
    for sym in SYMBOLS:
        prepared[sym] = apply_indicators_and_build(download_symbol_data(sym))
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    # STEP2: 스윕
    todo = [c for c in combos if c["key"] not in done]
    print(f"\n[STEP2] 스윕 (총 {len(combos)}, 남은 {len(todo)})")
    t_start = time.time(); processed = 0; gate_checked = False; cap_tested = False
    for combo in combos:
        key, atoms = combo["key"], combo["atoms"]
        if key in done:
            continue
        try:
            trades = run_combo(prepared, atoms)
            # 게이트 적용 검증(첫 1회)
            if not gate_checked:
                print(f"  [gate-check] {key}: {gate_atoms_ok(atoms, trades)}")
                gate_checked = True
            # 자본 룩어헤드 테스트(스윕 시작 전 1회, 거래 있는 첫 조합)
            if not cap_tested and trades is not None and len(_realized(trades)) >= 10:
                dd = _realized(trades).copy()
                dd["entry_time"] = pd.to_datetime(dd["entry_time"], utc=True)
                dd["exit_time"] = pd.to_datetime(dd["exit_time"], utc=True)
                dd = dd.sort_values("entry_time").reset_index(drop=True)
                mism, checked = test_capital_no_lookahead(dd)
                print(f"  [capital-lookahead] {checked}건 검사 / 불일치 {mism}")
                if mism != 0:
                    print("  [ABORT] 자본 룩어헤드 누수 — 중단"); sys.exit(2)
                cap_tested = True
            row = compute_row(key, atoms, trades)
        except Exception as e:
            row = {f: "" for f in FIELDS}
            row["key"] = key; row["atoms"] = "+".join(atoms); row["k"] = len(atoms)
            row["err"] = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"  [ERR] {key}: {row['err']}")
        append_row(RESULTS_CSV, row)
        processed += 1
        if processed % PROGRESS_EVERY == 0:
            el = time.time() - t_start; rate = el / processed
            eta = (len(todo) - processed) * rate
            print(f"  [{processed}/{len(todo)}] {key} | n={row.get('n')} PF={row.get('PF')} "
                  f"OOS={row.get('OOS_PF')} cap={row.get('final_cap')} | {rate:.1f}s/조합 ETA {eta/60:.0f}분")

    print(f"\n[DONE] 처리 {processed} | 총 {time.time()-t_start:.0f}s | → {RESULTS_CSV}")


if __name__ == "__main__":
    main()
