"""OR 진입게이트 실전 백테스트 스윕 — post-hoc 아님, 매 조합마다 전략 재실행(슬롯 재배치 반영).
각 조합 = ATOM_OR_LIST 리터럴들. HONEST_STAGE=5(정직봉) 고정, 다운로드 캐시 공유.
병렬: 동시 N개 백테스트(각 내부 joblib 멀티코어). 결과 overall_summary + 연도별 PF 수집.

사용:
  python run_or_sweep.py singles [workers]     # 24개 단일 리터럴(원자·음극) 각각 단독게이트
  python run_or_sweep.py pairs   [workers]     # 단일+페어
  python run_or_sweep.py file:combos.txt [workers]   # 한 줄당 콤마구분 리터럴
"""
import os, sys, subprocess, io
from itertools import combinations
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "smc_crypto_stage4d_atomic_decomposition.py")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
SWEEP = os.path.join(ROOT, "stage4d_honest", "or_sweep")
os.makedirs(SWEEP, exist_ok=True)

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
LITERALS = ATOMS + ["~" + a for a in ATOMS]

def lit_atom(l): return l[1:] if l.startswith("~") else l

def build_combos(spec):
    if spec == "singles":
        return [[l] for l in LITERALS]
    if spec == "pairs":
        out = [[l] for l in LITERALS]
        for a, b in combinations(LITERALS, 2):
            if lit_atom(a) == lit_atom(b):
                continue
            out.append([a, b])
        return out
    if spec.startswith("file:"):
        out = []
        with open(spec[5:], encoding="utf-8") as f:
            for line in f:
                lits = [x.strip() for x in line.strip().split(",") if x.strip()]
                if lits:
                    out.append(lits)
        return out
    raise SystemExit(f"unknown spec: {spec}")

def label(lits):
    return "__".join(l.replace("~", "n_").replace("a_", "") for l in lits)[:80]

def pf(s):
    s = np.asarray(s, float)
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)

def run_one(lits):
    lab = label(lits)
    outdir = os.path.join(SWEEP, lab)
    env = dict(os.environ)
    env.update(HONEST_STAGE="5", ATOM_OR_LIST=",".join(lits),
               STAGE4D_DLCACHE=DLC, STAGE4D_OUTDIR=outdir, PYTHONIOENCODING="utf-8")
    logf = os.path.join(SWEEP, lab + ".log")
    with open(logf, "w", encoding="utf-8") as lg:
        rc = subprocess.run([sys.executable, SCRIPT], env=env, stdout=lg, stderr=subprocess.STDOUT).returncode
    res = {"combo": " OR ".join(lits), "label": lab, "rc": rc,
           "trades": np.nan, "PF": np.nan, "Return_%": np.nan,
           "PF2023": np.nan, "PF2024": np.nan, "PF2025": np.nan, "PF2026": np.nan,
           "PF_train2324": np.nan, "PF_test2526": np.nan}
    sm = os.path.join(outdir, "stage4d_overall_summary.csv")
    tr = os.path.join(outdir, "stage4d_trades.csv")
    if os.path.exists(sm):
        r = pd.read_csv(sm).iloc[0]
        res["trades"] = int(r["trades"]); res["PF"] = float(r["PF"]); res["Return_%"] = float(r["Return_%"])
    if os.path.exists(tr):
        d = pd.read_csv(tr)
        if len(d):
            d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
            for y in (2023, 2024, 2025, 2026):
                res[f"PF{y}"] = round(pf(d.loc[d.year == y, "net_pnl"]), 3)
            res["PF_train2324"] = round(pf(d.loc[d.year.isin([2023, 2024]), "net_pnl"]), 3)
            res["PF_test2526"] = round(pf(d.loc[d.year.isin([2025, 2026]), "net_pnl"]), 3)
    print(f"  done [{res['rc']}] {lab:<40} tr={res['trades']} PF={res['PF']} test2526={res['PF_test2526']}", flush=True)
    return res

if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "singles"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    combos = build_combos(spec)
    print(f"실전 OR 스윕 | spec={spec} | {len(combos)}조합 | workers={workers} | HONEST_STAGE=5", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(run_one, combos))
    R = pd.DataFrame(rows).sort_values("PF", ascending=False)
    out_csv = os.path.join(SWEEP, f"sweep_{spec.replace(':','_')}.csv")
    R.to_csv(out_csv, index=False)
    print(f"\n결과 {len(R)}행 → {out_csv}")
    print(R.to_string(index=False))
