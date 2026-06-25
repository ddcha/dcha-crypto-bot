#!/usr/bin/env python3
# =========================================================================
# run_setups368_union.py — setups_368.json "최대원자 귀속 union 게이트" 단일 백테스트 + 자본시뮬
#
#   진입 게이트(기존 USE_COMBO_UNION 엔진, post-hoc 아님 / 정직봉 i-1):
#     30셋업 중 "전 원자 True 인 셋업이 1개라도 있으면" 진입. (= OR of ANDs)
#   최대원자 귀속(라벨링 전용):
#     진입한 거래마다 그 거래의 a_* 원자플래그로 매칭 셋업 집합을 구하고,
#       matched_setup    = 매칭 셋업 중 원자 수 최대(동률이면 setups 리스트 순서 빠른 것)의 key
#       n_setups_matched = 매칭된 셋업 개수
#     (진입 여부는 매칭≥1 로 동일 — 귀속은 어느 셋업 거래인지 기록일 뿐)
#
#   candidate 태깅 9심볼 1회 → simulate 1회 (단일 백테스트). 그 후 귀속 라벨 부여.
#   baseline: OB_MODE=engulf, DISP_ATR_MULT=1.3, USE_H1_REFINE=1, risk_multiplier=1.0
#   실행:  set STAGE4D_DLCACHE=data_cache & python run_setups368_union.py
# =========================================================================
import os, json, time

# ── baseline env (config import 前; 외부 env 우선) ──
os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["USE_COMBO_UNION"] = "1"                 # union 게이트 ON
os.environ["COMBO_UNION_JSON"] = "setups_368.json"   # 30셋업 atomset 자동 로드(config L166)
os.environ["ATOM_AND_LIST"] = ""                    # 다른 게이트 비활성
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE"):
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6_EXCLUDE = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
YEARS = [2022, 2023, 2024, 2025, 2026]
SEED, MONTHLY, NDEP, RISK_PCT = 500.0, 250.0, 5, 0.01
TOTAL_DEP = SEED + MONTHLY * NDEP                   # 1750
SETUPS_JSON = "setups_368.json"
OUTDIR = "setups368_union_result"

# 30셋업 (key, atoms) — 귀속 라벨링 소스 (게이트와 동일 파일)
SETUPS = json.load(open(SETUPS_JSON, encoding="utf-8"))


# ── 지표 ──────────────────────────────────────────────────────────────────
def _pf(p):
    p = np.asarray(p, float); gp = p[p > 0].sum(); gl = -p[p < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def _realized(t):
    if "exit_reason" in t:
        return t[~t["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return t


# ── 최대원자 귀속 ─────────────────────────────────────────────────────────
def attribute(atom_getter):
    """atom_getter(a)->bool. 반환 (matched_setup_key, n_setups_matched).
       매칭 = 셋업의 모든 원자 True. matched_setup = 원자수 최대(동률 시 리스트 순서 빠른 것)."""
    matched = []
    for idx, su in enumerate(SETUPS):
        if all(bool(atom_getter(a)) for a in su["atoms"]):
            matched.append((idx, su["key"], len(su["atoms"])))
    if not matched:
        return "", 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]   # 원자수↓, idx↑
    return best[1], len(matched)


def selfcheck_attribution_logic():
    """게이트 매칭/귀속 로직만 합성 샘플로 검증 (전체 실행 전)."""
    print("\n[SELF-CHECK] 귀속 로직 합성샘플 검증")
    ok = True
    # 1) 한 셋업과 정확히 일치 → 그 key, n>=1
    s0 = SETUPS[0]; atoms0 = set(s0["atoms"])
    k, n = attribute(lambda a: a in atoms0)
    cond1 = (n >= 1 and k != "")
    print(f"  [1] 단일셋업 매칭: key={k!r} n={n}  → {'OK' if cond1 else 'FAIL'}")
    ok &= cond1
    # 2) 모든 원자 False → 스킵(빈 라벨, n=0)
    k, n = attribute(lambda a: False)
    cond2 = (k == "" and n == 0)
    print(f"  [2] 원자0개 매칭: key={k!r} n={n}  → {'OK(스킵)' if cond2 else 'FAIL'}")
    ok &= cond2
    # 3) 서브셋+슈퍼셋 동시 매칭 → 최대원자 셋업으로 귀속, n>=2
    #    리스트에서 한 셋업의 원자집합이 다른 셋업을 포함하는 쌍 탐색
    pair = None
    for i, a in enumerate(SETUPS):
        for j, b in enumerate(SETUPS):
            if i != j and set(b["atoms"]).issubset(set(a["atoms"])) and len(a["atoms"]) > len(b["atoms"]):
                pair = (a, b); break
        if pair: break
    if pair:
        big, small = pair
        big_atoms = set(big["atoms"])
        k, n = attribute(lambda a: a in big_atoms)
        cond3 = (k == big["key"] and n >= 2)
        print(f"  [3] 서브셋+슈퍼셋 동시매칭: 귀속 key={k!r}(원자{len(big['atoms'])}) n={n}  → {'OK' if cond3 else 'FAIL'}")
        ok &= cond3
    else:
        print("  [3] 포함관계 셋업쌍 없음 — 스킵")
    if not ok:
        raise SystemExit("[ABORT] 귀속 로직 self-check 실패")
    print("  → 귀속 로직 OK")


# ── 자본 시뮬 (시드500 flat, 룩어헤드 안전, v19b 자본로직 아님) ────────────
def run_equity(g, rvals, seed=SEED, monthly=MONTHLY, nd=NDEP, rp=RISK_PCT):
    ET = list(g["entry_time"]); XT = list(g["exit_time"])
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = start
    for _ in range(nd):
        m = m + pd.offsets.MonthBegin(1); deps.append((m, monthly))   # 다음달 1일 00:00 도착
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 0, i)); ev.append((XT[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]
    ev.sort(key=lambda x: (x[0], x[1]))             # 진입(0)<입금(1)<청산(2)
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * realized; eq[p] = realized  # 사이징 = 그 시점 실현자본
        elif pri == 1:
            realized += (-p)
        else:
            realized += rvals[p] * ra.get(p, 0.0)
            peak = max(peak, realized); mdd = min(mdd, (realized - peak) / peak)
    return eq, realized, mdd


def test_capital_no_lookahead(g):
    ET = g["entry_time"]; XT = g["exit_time"]; r_base = g["r_multiple"].values.astype(float)
    eq0, _, _ = run_equity(g, r_base); rng = np.random.default_rng(7)
    splits = pd.to_datetime(["2023-10-01", "2024-01-01", "2024-07-01",
                             "2025-01-01", "2025-07-01", "2026-01-01"], utc=True)
    mism = checked = 0
    for T in splits:
        fut = (XT >= T).values; past = g.index[ET <= T]
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


# ── 요약 지표 ─────────────────────────────────────────────────────────────
def summarize(name, trades):
    d = _realized(trades).copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values; rr = d["r_multiple"].astype(float).values
    n = len(d); k = int(n * 0.7)
    row = {"name": name, "n": n,
           "win_pct": round(float((pnl > 0).mean() * 100), 2),
           "PF": round(_pf(pnl), 4), "IS_PF": round(_pf(pnl[:k]), 4), "OOS_PF": round(_pf(pnl[k:]), 4),
           "oosN": n - k, "avgR": round(float(rr.mean()), 4),
           "Sharpe": round(float(rr.mean() / rr.std(ddof=1)), 4) if rr.std(ddof=1) > 0 else float("nan")}
    d6 = d[~d["symbol"].isin(REST6_EXCLUDE)]
    row["r6_PF"] = round(_pf(d6["net_pnl"].astype(float).values), 4)
    row["r6_n"] = int(len(d6))
    yr = d["exit_time"].dt.year; all_ge1 = True; any_y = False
    for y in YEARS:
        s = d[yr == y]
        if len(s) > 0:
            pfy = _pf(s["net_pnl"].astype(float).values); row[f"pf_{y}"] = round(pfy, 4)
            row[f"n_{y}"] = int(len(s)); any_y = True
            if pfy < 1.0:
                all_ge1 = False
    row["all_years_ge1"] = bool(all_ge1 and any_y)
    # 자본 시뮬 (entry 순)
    de = d.sort_values("entry_time").reset_index(drop=True)
    mism, checked = test_capital_no_lookahead(de)
    if mism != 0:
        raise SystemExit(f"[ABORT] 자본 룩어헤드 누수 — 불일치 {mism}/{checked}")
    _, final, mdd = run_equity(de, de["r_multiple"].astype(float).values)
    yrs = max((de["exit_time"].max() - de["entry_time"].min()).days / 365.25, 1e-9)
    row["final_cap"] = round(final, 2); row["mult_vs_dep"] = round(final / TOTAL_DEP, 4)
    row["CAGR_pct"] = round(((final / TOTAL_DEP) ** (1 / yrs) - 1) * 100, 2) if final > 0 else float("nan")
    row["MDD_pct"] = round(mdd * 100, 2)
    row["LA_mismatch"] = mism; row["LA_checked"] = checked
    row["refine_pct"] = round(float(d["entry_refined"].astype(bool).mean() * 100), 1) if "entry_refined" in d else float("nan")
    return row


def setup_breakdown(trades):
    """matched_setup 라벨별 거래수·PF·OOS_PF (realized 기준)."""
    d = _realized(trades).copy()
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    rows = []
    for key, grp in d.groupby("matched_setup"):
        g = grp.sort_values("exit_time").reset_index(drop=True)
        pnl = g["net_pnl"].astype(float).values; n = len(g); k = int(n * 0.7)
        rows.append({
            "matched_setup": key, "n": n,
            "win_pct": round(float((pnl > 0).mean() * 100), 2),
            "PF": round(_pf(pnl), 4),
            "OOS_PF": round(_pf(pnl[k:]), 4) if n - k > 0 else float("nan"),
            "oosN": n - k,
            "avgR": round(float(g["r_multiple"].astype(float).mean()), 4),
            "n_atoms": len(next((s["atoms"] for s in SETUPS if s["key"] == key), [])),
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def main():
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} HONEST_STAGE={os.environ['HONEST_STAGE']} | "
          f"risk_mult=1.0 | 자본 시드{SEED}+{MONTHLY}x{NDEP}(총{TOTAL_DEP}) | 셋업 {len(SETUPS)}개")

    # STEP0: 귀속 로직 self-check (전체 실행 전)
    selfcheck_attribution_logic()

    # STEP1: prepared 1회
    print("\n[STEP1] 데이터 + apply_indicators_and_build (9심볼 1회)")
    t0 = time.time(); prepared = {sym: apply_indicators_and_build(download_symbol_data(sym)) for sym in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    # STEP2: candidates(게이트 적용) + simulate 1회
    print(f"\n[STEP2] candidates(union 게이트 30셋업) + simulate 1회")
    t1 = time.time()
    cand = {sym: generate_candidates_from_prepared(prepared[sym]) for sym in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    trades = res["trades"].copy()
    print(f"[STEP2] 완료 {time.time()-t1:.0f}s | 진입 거래 {len(trades)}")

    # STEP3: 최대원자 귀속 라벨링 (거래별 a_* 플래그)
    print("\n[STEP3] 최대원자 귀속 라벨링")
    labels = trades.apply(lambda r: attribute(lambda a: r.get(a, False)), axis=1)
    trades["matched_setup"] = [x[0] for x in labels]
    trades["n_setups_matched"] = [x[1] for x in labels]

    # 진입 거래 자기검증: 전부 매칭≥1 이어야 함 (게이트와 귀속 일관성)
    zero = int((trades["n_setups_matched"] == 0).sum())
    print(f"  진입 거래 {len(trades)} 중 매칭0(귀속실패) = {zero}")
    if zero != 0:
        bad = trades[trades["n_setups_matched"] == 0].head(3)
        print(bad[["symbol", "entry_time", "n_combos_matched"]].to_string(index=False))
        raise SystemExit(f"[ABORT] 게이트로 진입했으나 post-hoc 매칭0 거래 {zero}건 — 게이트/귀속 불일치")
    print(f"  → 모든 진입 거래가 ≥1 셋업 매칭. n_setups_matched 분포: "
          f"min={int(trades['n_setups_matched'].min())} "
          f"median={int(trades['n_setups_matched'].median())} "
          f"max={int(trades['n_setups_matched'].max())}")
    # 샘플 3건 원자/귀속 표시
    print("  [샘플 3건]")
    ALL_ATOMS = sorted({a for s in SETUPS for a in s["atoms"]})
    for _, r in trades.head(3).iterrows():
        true_atoms = [a for a in ALL_ATOMS if bool(r.get(a, False))]
        print(f"    {r['symbol']} {r['entry_time']} | true_atoms={true_atoms} "
              f"→ matched={r['matched_setup']} (n={r['n_setups_matched']})")

    # 저장
    os.makedirs(OUTDIR, exist_ok=True)
    trades.to_csv(os.path.join(OUTDIR, "trades.csv"), index=False)
    print(f"\n[저장] {OUTDIR}/trades.csv ({len(trades)}행, +matched_setup +n_setups_matched)")

    # 지표 + 자본시뮬
    row = summarize("setups368_union", trades)
    pd.DataFrame([row]).to_csv(os.path.join(OUTDIR, "summary.csv"), index=False)

    # 셋업별 분해
    bd = setup_breakdown(trades)
    bd.to_csv(os.path.join(OUTDIR, "setup_breakdown.csv"), index=False)

    # 출력
    print("\n" + "=" * 70)
    print("=== 전체 결과 (setups368_union) ===")
    print("=" * 70)
    for k in ["n", "win_pct", "PF", "IS_PF", "OOS_PF", "oosN", "avgR", "Sharpe",
              "r6_PF", "r6_n", "all_years_ge1", "refine_pct"]:
        print(f"  {k:14s}: {row.get(k)}")
    print("  연도별 PF/거래수:")
    for y in YEARS:
        if f"pf_{y}" in row:
            print(f"    {y}: PF={row[f'pf_{y}']:<8} n={row.get(f'n_{y}')}")
    print("  자본 시뮬(시드500+250x5 flat, RISK 1%):")
    print(f"    final_cap={row['final_cap']}  mult_vs_dep={row['mult_vs_dep']}x  "
          f"CAGR={row['CAGR_pct']}%  MDD={row['MDD_pct']}%")
    print(f"    룩어헤드 LA_mismatch={row['LA_mismatch']}/{row['LA_checked']}")

    print("\n=== 셋업별 분해 (matched_setup) ===")
    print(bd.to_string(index=False))
    print(f"\n[저장 완료] {OUTDIR}/ (trades.csv, summary.csv, setup_breakdown.csv)")


if __name__ == "__main__":
    main()
