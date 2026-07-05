"""legacy zone패널 경로 numpy 리팩토링 안전망.
  capture: prepare_h4_dataframe / prepare_h1_dataframe / build_structures 출력 pickle.
  verify : 리팩토링 후 비트단위 동일 검증 + 함수별 타이밍.
사용: python _golden_legacy.py capture | verify
"""
import os, sys, time, pickle
import numpy as np, pandas as pd
import strategy_engine_legacy as L

DATA = "../../data_cache"; SYMS = ["BTCUSDT", "SOLUSDT"]; REF = "_golden_legacy.pkl"


def load(sym, tf, n):
    d = pd.read_parquet(f"{DATA}/{sym}_{tf}.parquet")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True).tail(n).reset_index(drop=True)


def run_one(sym):
    h4 = load(sym, "4h", 1600); h1 = load(sym, "1h", 6400)
    t0 = time.perf_counter(); h4p = L.prepare_h4_dataframe(h4.copy()); t1 = time.perf_counter()
    h1p = L.prepare_h1_dataframe(h1.copy()); t2 = time.perf_counter()
    ds, structs, _ = L.build_structures(h4p.copy()); t3 = time.perf_counter()
    return {"h4p": h4p, "h1p": h1p, "ds": ds, "n_struct": len(structs), "structs": structs,
            "t_h4": t1 - t0, "t_h1": t2 - t1, "t_bs": t3 - t2}


def capture():
    ref = {}
    for s in SYMS:
        r = run_one(s); ref[s] = r
        print(f"[capture] {s}: struct={r['n_struct']} | h4={r['t_h4']*1000:.0f}ms h1={r['t_h1']*1000:.0f}ms bs={r['t_bs']*1000:.0f}ms")
    with open(REF, "wb") as f:
        pickle.dump({s: {"h4p": r["h4p"], "h1p": r["h1p"], "ds": r["ds"],
                         "n_struct": r["n_struct"], "structs": r["structs"]} for s, r in ref.items()}, f)
    print(f"[capture] saved → {REF}")


def _fi(a, b):
    if list(a.columns) != list(b.columns):
        return "columns order/set diff"
    if a.shape != b.shape:
        return f"shape {a.shape} vs {b.shape}"
    for c in a.columns:
        x, y = a[c], b[c]
        if x.dtype != y.dtype:
            return f"{c} dtype {x.dtype}/{y.dtype}"
        if pd.api.types.is_float_dtype(x):
            if not np.array_equal(x.values, y.values, equal_nan=True):
                return f"{c} float mismatch"
        else:
            if not x.equals(y):
                return f"{c} mismatch"
    return None


def verify():
    ref = pickle.load(open(REF, "rb")); allok = True
    for s in SYMS:
        r = run_one(s); g = ref[s]
        m4 = _fi(g["h4p"], r["h4p"]); m1 = _fi(g["h1p"], r["h1p"]); mb = _fi(g["ds"], r["ds"])
        sok = (g["n_struct"] == r["n_struct"]) and (g["structs"] == r["structs"])
        ok = all(m is None for m in (m4, m1, mb)) and sok; allok &= ok
        print(f"[verify] {s}: h4p={m4 or 'OK'} | h1p={m1 or 'OK'} | bs={mb or 'OK'} | struct={sok} "
              f"| t h4={r['t_h4']*1000:.0f} h1={r['t_h1']*1000:.0f} bs={r['t_bs']*1000:.0f}ms  {'✅' if ok else '❌'}")
    print("\n" + ("✅ legacy 전 출력 비트단위 동일" if allok else "❌ 불일치"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    (capture if (len(sys.argv) > 1 and sys.argv[1] == "capture") else verify)()
