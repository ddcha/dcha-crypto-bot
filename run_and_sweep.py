"""AND 진입게이트 실전 백테스트 스윕 — post-hoc 아님, 매 조합마다 전략 재실행(슬롯 재배치 반영).
각 조합 = ATOM_AND_LIST 리터럴들(모두 True 여야 진입=교집합). HONEST_STAGE=5 고정, 다운로드 캐시 공유.
병렬: 동시 N개 백테스트(각 내부 joblib 멀티코어).

사용:
  python run_and_sweep.py curated [workers]        # 엣지원자 교집합 큐레이션(기본)
  python run_and_sweep.py file:and_combos.txt [workers]   # 한 줄당 콤마구분 리터럴(AND)
"""
import os, sys, subprocess, io
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "smc_crypto_stage4d_atomic_decomposition.py")
DLC = os.path.join(ROOT, "stage4d_honest", "_dlcache")
SWEEP = os.path.join(ROOT, "stage4d_honest", "and_sweep")
os.makedirs(SWEEP, exist_ok=True)

# train(23-24) PF>1.2 였던 '엣지원자' + 음극 함정후보 n_room
EDGE = ["a_volume", "a_fvg", "a_trend_align", "a_score_ge13"]
CURATED = [
    ["a_volume", "a_fvg"],
    ["a_volume", "a_trend_align"],
    ["a_fvg", "a_trend_align"],
    ["a_volume", "a_score_ge13"],
    ["a_fvg", "a_score_ge13"],
    ["a_trend_align", "a_score_ge13"],
    ["a_volume", "a_fvg", "a_trend_align"],
    ["a_volume", "a_fvg", "a_score_ge13"],
    ["a_volume", "a_trend_align", "a_score_ge13"],
    ["a_fvg", "a_trend_align", "a_score_ge13"],
    ["a_volume", "a_fvg", "a_trend_align", "a_score_ge13"],
    ["a_volume", "~a_room"],
    ["a_fvg", "~a_room"],
    ["a_trend_align", "~a_room"],
    ["a_volume", "a_fvg", "~a_room"],
    ["a_volume", "a_trend_align", "~a_room"],
    ["a_fvg", "a_trend_align", "~a_room"],
    ["a_volume", "a_fvg", "a_trend_align", "~a_room"],
]


def build_combos(spec):
    if spec == "curated":
        return CURATED
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
    return "AND__" + "__".join(l.replace("~", "n_").replace("a_", "") for l in lits)[:74]


def pf(s):
    s = np.asarray(s, float)
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def run_one(lits):
    lab = label(lits)
    outdir = os.path.join(SWEEP, lab)
    env = dict(os.environ)
    env.update(HONEST_STAGE="5", ATOM_AND_LIST=",".join(lits),
               STAGE4D_DLCACHE=DLC, STAGE4D_OUTDIR=outdir, PYTHONIOENCODING="utf-8")
    logf = os.path.join(SWEEP, lab + ".log")
    with open(logf, "w", encoding="utf-8") as lg:
        rc = subprocess.run([sys.executable, SCRIPT], env=env, stdout=lg, stderr=subprocess.STDOUT).returncode
    res = {"combo": " AND ".join(lits), "label": lab, "rc": rc,
           "trades": np.nan, "PF": np.nan, "Return_%": np.nan, "win_%": np.nan, "avgR": np.nan,
           "PF2023": np.nan, "PF2024": np.nan, "PF2025": np.nan, "PF2026": np.nan,
           "nte": 0, "PF_train2324": np.nan, "PF_test2526": np.nan}
    sm = os.path.join(outdir, "stage4d_overall_summary.csv")
    tr = os.path.join(outdir, "stage4d_trades.csv")
    if os.path.exists(sm):
        r = pd.read_csv(sm).iloc[0]
        res["trades"] = int(r["trades"]); res["PF"] = float(r["PF"]); res["Return_%"] = float(r["Return_%"])
    if os.path.exists(tr):
        d = pd.read_csv(tr)
        if len(d):
            pnl = d["net_pnl"].to_numpy(float)
            res["win_%"] = round(100 * (pnl > 0).mean(), 1)
            if "r_multiple" in d.columns:
                res["avgR"] = round(float(np.nanmean(d["r_multiple"].to_numpy(float))), 3)
            d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
            for y in (2023, 2024, 2025, 2026):
                res[f"PF{y}"] = round(pf(d.loc[d.year == y, "net_pnl"]), 3)
            te = d.year.isin([2025, 2026])
            res["nte"] = int(te.sum())
            res["PF_train2324"] = round(pf(d.loc[d.year.isin([2023, 2024]), "net_pnl"]), 3)
            res["PF_test2526"] = round(pf(d.loc[te, "net_pnl"]), 3)
    print(f"  done [{res['rc']}] {lab:<48} tr={res['trades']} PF={res['PF']} "
          f"tr2324={res['PF_train2324']} te2526={res['PF_test2526']} nte={res['nte']}", flush=True)
    return res


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "curated"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    combos = build_combos(spec)
    print(f"실전 AND 스윕 | spec={spec} | {len(combos)}조합 | workers={workers} | HONEST_STAGE=5", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(run_one, combos))
    R = pd.DataFrame(rows).sort_values("PF_test2526", ascending=False)
    out_csv = os.path.join(SWEEP, f"sweep_{spec.replace(':', '_')}.csv")
    R.to_csv(out_csv, index=False)
    cols = ["combo", "trades", "win_%", "PF", "avgR", "PF_train2324", "PF_test2526", "nte",
            "PF2023", "PF2024", "PF2025", "PF2026", "Return_%"]
    print(f"\n결과 {len(R)}행 (OOS test2526 PF 내림차순) → {out_csv}")
    print(R[cols].to_string(index=False))
