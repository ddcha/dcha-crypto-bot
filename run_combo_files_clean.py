#!/usr/bin/env python3
# =========================================================================
# run_combo_files.py — 4개 셋업파일 × "최대원자 귀속 union 게이트 + 자본시뮬" 비교
#
#   파일: setups_pf10/12/13/14.json  (PF컷 셋업 리스트, 각 [{key,atoms,setup_pf}])
#   게이트(진짜 게이트, 슬롯 재배치 반영): 그 파일 셋업 중 "전 원자 True 셋업이 1개라도 있으면" 진입.
#   귀속(라벨): 거래의 a_* 로 매칭 셋업집합 → matched_setup=원자최다(동률 시 리스트순서),
#               n_setups_matched=매칭개수. (진입은 매칭≥1, 귀속은 라벨링 전용)
#
#   indicators(prepared) 9심볼 1회만 생성·재사용. 파일마다 candidate(게이트) + simulate.
#   baseline: OB_MODE=engulf, DISP_ATR_MULT=1.3, USE_H1_REFINE=1, risk_multiplier=1.0
#   실행:  set STAGE4D_DLCACHE=data_cache & python run_combo_files.py
# =========================================================================
import os, json, time

os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""        # union 게이트만 — 다른 게이트 비활성
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
REST6_EXCLUDE = {"DOGEUSDT", "LINKUSDT", "XRPUSDT"}
YEARS = [2022, 2023, 2024, 2025, 2026]
SEED, MONTHLY, NDEP, RISK_PCT = 500.0, 250.0, 5, 0.01
TOTAL_DEP = SEED + MONTHLY * NDEP                       # 1750
INDIR = "combination backtest"
OUTDIR = "combo_files_clean_result"   # ⭐ 클린 재실행(패스마다 _ls_* 리셋)


def reset_prepared(prepared):
    # ⚠️ advance_zone_lifespan 이 structure dict 에 _ls_* 증분상태 캐시(structures.py:79-111).
    #    generate_candidates 리셋은 'used'만 → 같은 prepared 2번째+ 호출은 _ls_pos 가 끝까지 전진해
    #    모든 존이 '시리즈 끝 역할'로 판정(룩어헤드성 오염). 매 게이트 전 이 상태 제거 → 1패스 동등(클린).
    for sym in prepared:
        for s in prepared[sym]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                s.pop(k, None)
            s["used"] = False

# (라벨, 파일경로, 사후기대값 dict) — 사후값은 진짜 게이트 검증 비교용
REF = {
    "pf10": {"n": 1165, "PF": 1.51, "OOS": 1.52, "cap": 14911, "mult": 8.5, "mdd": -16.9},
    "pf12": {"n": 1088, "PF": 1.54, "OOS": 1.51, "cap": 14537, "mult": 8.3, "mdd": -14.9},
    "pf13": {"n": 783,  "PF": 1.65, "OOS": 1.51, "cap": 10563, "mult": 6.0, "mdd": -12.5},
    "pf14": {"n": 302,  "PF": 2.13, "OOS": 2.29, "cap": 5380,  "mult": 3.1, "mdd": -8.4},
}
RUNS = [("pf10", "setups_pf10.json"), ("pf12", "setups_pf12.json"),
        ("pf13", "setups_pf13.json"), ("pf14", "setups_pf14.json")]


def _pf(p):
    p = np.asarray(p, float); gp = p[p > 0].sum(); gl = -p[p < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def _realized(t):
    if "exit_reason" in t:
        return t[~t["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)]
    return t


def attribute(atom_getter, setups):
    matched = []
    for idx, su in enumerate(setups):
        if all(bool(atom_getter(a)) for a in su["atoms"]):
            matched.append((idx, su["key"], len(su["atoms"])))
    if not matched:
        return "", 0
    best = sorted(matched, key=lambda x: (-x[2], x[0]))[0]
    return best[1], len(matched)


# ── 자본 시뮬 (시드500 flat, 룩어헤드 안전, v19b 자본로직 아님) ──
def run_equity(g, rvals, seed=SEED, monthly=MONTHLY, nd=NDEP, rp=RISK_PCT):
    ET = list(g["entry_time"]); XT = list(g["exit_time"])
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1)
    deps = []; m = start
    for _ in range(nd):
        m = m + pd.offsets.MonthBegin(1); deps.append((m, monthly))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 0, i)); ev.append((XT[i], 2, i))
    ev += [(dt, 1, -amt) for dt, amt in deps]
    ev.sort(key=lambda x: (x[0], x[1]))                # 진입(0)<입금(1)<청산(2)
    realized = seed; ra = {}; eq = {}; peak = seed; mdd = 0.0
    for ts, pri, p in ev:
        if pri == 0:
            ra[p] = rp * realized; eq[p] = realized
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


def summarize(name, trades, nsetups, check_lookahead=False):
    d = _realized(trades).copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d = d.sort_values("exit_time").reset_index(drop=True)
    pnl = d["net_pnl"].astype(float).values; rr = d["r_multiple"].astype(float).values
    n = len(d); k = int(n * 0.7)
    row = {"file": name, "n_setups": nsetups, "n": n,
           "win_pct": round(float((pnl > 0).mean() * 100), 2),
           "PF": round(_pf(pnl), 4), "IS_PF": round(_pf(pnl[:k]), 4), "OOS_PF": round(_pf(pnl[k:]), 4),
           "avgR": round(float(rr.mean()), 4),
           "Sharpe": round(float(rr.mean() / rr.std(ddof=1)), 4) if rr.std(ddof=1) > 0 else float("nan")}
    d6 = d[~d["symbol"].isin(REST6_EXCLUDE)]
    row["r6_PF"] = round(_pf(d6["net_pnl"].astype(float).values), 4)
    yr = d["exit_time"].dt.year; all_ge1 = True; any_y = False
    for y in YEARS:
        s = d[yr == y]
        if len(s) > 0:
            pfy = _pf(s["net_pnl"].astype(float).values); row[f"pf_{y}"] = round(pfy, 4); any_y = True
            if pfy < 1.0:
                all_ge1 = False
    row["all_years_ge1"] = bool(all_ge1 and any_y)
    de = d.sort_values("entry_time").reset_index(drop=True)
    if check_lookahead:
        mism, checked = test_capital_no_lookahead(de)
        print(f"  [capital-lookahead] {checked}건 검사 / 불일치 {mism}")
        if mism != 0:
            raise SystemExit(f"[ABORT] 자본 룩어헤드 누수 — 불일치 {mism}/{checked}")
    _, final, mdd = run_equity(de, de["r_multiple"].astype(float).values)
    yrs = max((de["exit_time"].max() - de["entry_time"].min()).days / 365.25, 1e-9)
    row["final_cap"] = round(final, 2); row["mult_vs_dep"] = round(final / TOTAL_DEP, 4)
    row["CAGR_pct"] = round(((final / TOTAL_DEP) ** (1 / yrs) - 1) * 100, 2) if final > 0 else float("nan")
    row["MDD_pct"] = round(mdd * 100, 2)
    return row


def main():
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} HONEST_STAGE={os.environ['HONEST_STAGE']} | "
          f"risk_mult=1.0 | 자본 시드{SEED}+{MONTHLY}x{NDEP}(총{TOTAL_DEP})")

    setup_map = {}
    for name, jf in RUNS:
        path = os.path.join(INDIR, jf)
        if not os.path.exists(path):
            path = jf   # 루트 폴백
        setup_map[name] = json.load(open(path, encoding="utf-8"))
        print(f"  [{name}] {path} → {len(setup_map[name])}셋업")

    # STEP1: prepared 9심볼 1회 (재사용)
    print("\n[STEP1] 데이터 + apply_indicators_and_build (9심볼 1회)")
    t0 = time.time(); prepared = {sym: apply_indicators_and_build(download_symbol_data(sym)) for sym in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    sim.USE_COMBO_UNION = True
    os.makedirs(OUTDIR, exist_ok=True)
    rows = []
    for fi, (name, jf) in enumerate(RUNS):
        setups = setup_map[name]
        sim.COMBO_UNION_ATOMSETS = [list(s["atoms"]) for s in setups]   # 게이트 atomset 교체
        print(f"\n[RUN {name}] {len(setups)}셋업 union 게이트 — candidates + simulate (클린: _ls_* 리셋)")
        t1 = time.time()
        reset_prepared(prepared)   # ⭐ 패스마다 수명상태 리셋 → 오염 제거
        cand = {sym: generate_candidates_from_prepared(prepared[sym]) for sym in SYMBOLS}
        res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
        trades = res["trades"].copy()

        # 최대원자 귀속
        labels = trades.apply(lambda r: attribute(lambda a: r.get(a, False), setups), axis=1)
        trades["matched_setup"] = [x[0] for x in labels]
        trades["n_setups_matched"] = [x[1] for x in labels]
        zero = int((trades["n_setups_matched"] == 0).sum())
        if zero != 0:
            raise SystemExit(f"[ABORT] {name}: 진입했으나 post-hoc 매칭0 거래 {zero}건 — 게이트/귀속 불일치")

        # 첫 파일 self-check
        if fi == 0:
            print(f"  [SELF-CHECK {name}] 진입거래 {len(trades)} 전부 매칭≥1 (귀속실패 0) — 샘플 5건:")
            ALL_ATOMS = sorted({a for s in setups for a in s["atoms"]})
            for _, r in trades.head(5).iterrows():
                ta = [a for a in ALL_ATOMS if bool(r.get(a, False))]
                print(f"    {r['symbol']} {r['entry_time']} | true={ta} → matched={r['matched_setup']} (n={r['n_setups_matched']})")

        trades.to_csv(os.path.join(OUTDIR, f"trades_{name}.csv"), index=False)
        row = summarize(name, trades, len(setups), check_lookahead=(fi == 0))
        rows.append(row)
        print(f"  [{name}] 완료 {time.time()-t1:.0f}s | n={row['n']} PF={row['PF']} OOS={row['OOS_PF']} "
              f"자본=${row['final_cap']}({row['mult_vs_dep']}x) CAGR={row['CAGR_pct']}% MDD={row['MDD_pct']}% "
              f"매년삶={row['all_years_ge1']}")

    cmp = pd.DataFrame(rows)
    cmp.to_csv(os.path.join(OUTDIR, "comparison.csv"), index=False)

    # 비교표
    print("\n" + "=" * 110)
    print("=== 4개 파일 비교 (최대원자 귀속 union 게이트) ===")
    print("=" * 110)
    hdr = f"{'파일':<6}{'셋업':>5}{'거래':>6}{'승률':>7}{'PF':>8}{'IS_PF':>8}{'OOS_PF':>8}{'나머지6':>8}{'매년삶':>7}{'최종자본':>11}{'배수':>7}{'CAGR%':>8}{'MDD%':>8}"
    print(hdr)
    print("-" * 110)
    for r in rows:
        print(f"{r['file']:<6}{r['n_setups']:>5}{r['n']:>6}{r['win_pct']:>7}{r['PF']:>8}{r['IS_PF']:>8}"
              f"{r['OOS_PF']:>8}{r['r6_PF']:>8}{str(r['all_years_ge1']):>7}{r['final_cap']:>11}"
              f"{r['mult_vs_dep']:>7}{r['CAGR_pct']:>8}{r['MDD_pct']:>8}")

    # 사후 기대값 대비 검증
    print("\n=== 사후 기대값 대비 (진짜 게이트 vs post-hoc 기대) ===")
    print(f"{'파일':<6}{'거래(실/기대)':>18}{'PF(실/기대)':>18}{'OOS(실/기대)':>18}{'배수(실/기대)':>18}")
    for r in rows:
        ref = REF.get(r["file"], {})
        c_n = "{}/{}".format(r["n"], ref.get("n", "?"))
        c_pf = "{}/{}".format(r["PF"], ref.get("PF", "?"))
        c_oos = "{}/{}".format(r["OOS_PF"], ref.get("OOS", "?"))
        c_mult = "{}/{}".format(r["mult_vs_dep"], ref.get("mult", "?"))
        print(f"{r['file']:<6}{c_n:>18}{c_pf:>18}{c_oos:>18}{c_mult:>18}")
    # 괴리 플래그
    print("\n[괴리 점검]")
    for r in rows:
        ref = REF.get(r["file"], {})
        if not ref:
            continue
        dn = abs(r["n"] - ref["n"]) / max(ref["n"], 1) * 100
        dpf = abs(r["PF"] - ref["PF"]) / max(ref["PF"], 1e-9) * 100
        flag = "⚠️ 괴리" if (dn > 10 or dpf > 15) else "OK"
        print(f"  {r['file']}: 거래Δ={dn:.1f}% PF Δ={dpf:.1f}% → {flag}")

    print(f"\n[저장 완료] {OUTDIR}/ (trades_pf10~pf14.csv, comparison.csv)")


if __name__ == "__main__":
    main()
