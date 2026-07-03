"""지표 numpy 리팩토링 정확성 안전망.
  capture: 현재(리팩토링 전) apply_indicators_and_build 출력을 pickle 로 저장.
  verify : 리팩토링 후 재실행 → 저장본과 비트단위 동일 검증.
사용: python _golden_indicators.py capture   /   python _golden_indicators.py verify
"""
import os, sys, time, pickle
import numpy as np, pandas as pd

# v4 확정 엔진 env (어댑터와 동일)
for k, v in {"OB_MODE": "engulf", "DISP_ATR_MULT": "1.3", "USE_H1_REFINE": "1",
             "HONEST_STAGE": "5", "MIN_SCORE": "7.5"}.items():
    os.environ.setdefault(k, v)
os.environ.setdefault("ATOM_AND_LIST", ""); os.environ.setdefault("ATOM_OR_LIST", "")

DATA = "../../data_cache"
SYMS = ["BTCUSDT", "SOLUSDT"]
REF = "_golden_indicators.pkl"


def load(sym, tf, n):
    d = pd.read_parquet(f"{DATA}/{sym}_{tf}.parquet")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.sort_values("timestamp").reset_index(drop=True).tail(n).reset_index(drop=True)


def run_one(sym):
    from smc_stage4d.structures import apply_indicators_and_build
    h4 = load(sym, "4h", 1600); h1 = load(sym, "1h", 6400)
    t0 = time.perf_counter()
    out = apply_indicators_and_build({"symbol": sym, "df_raw": h4, "df_h1_raw": h1})
    dt = time.perf_counter() - t0
    # 구조체 리스트는 dict → 정렬가능 튜플로 정규화(부동소수 그대로)
    structs = out["structures"]
    return {"df_struct": out["df_struct"], "df_h1": out["df_h1"],
            "n_struct": len(structs), "structs": structs, "dt": dt}


def capture():
    ref = {}
    for s in SYMS:
        r = run_one(s); ref[s] = r
        print(f"[capture] {s}: struct={r['n_struct']} cols_h4={r['df_struct'].shape} dt={r['dt']*1000:.0f}ms")
    with open(REF, "wb") as f:
        pickle.dump({s: {"df_struct": r["df_struct"], "df_h1": r["df_h1"],
                         "n_struct": r["n_struct"], "structs": r["structs"]} for s, r in ref.items()}, f)
    print(f"[capture] saved → {REF}")


def _frame_identical(a, b):
    if list(a.columns) != list(b.columns):
        return f"columns diff\n  a={list(a.columns)}\n  b={list(b.columns)}"
    if a.shape != b.shape:
        return f"shape {a.shape} vs {b.shape}"
    for c in a.columns:
        x, y = a[c], b[c]
        if x.dtype != y.dtype:
            return f"col {c} dtype {x.dtype} vs {y.dtype}"
        try:
            if pd.api.types.is_float_dtype(x):
                if not np.array_equal(x.values, y.values, equal_nan=True):
                    return f"col {c} float mismatch"
            else:
                if not x.equals(y):
                    return f"col {c} mismatch"
        except Exception as e:
            return f"col {c} err {e}"
    return None


def verify():
    with open(REF, "rb") as f:
        ref = pickle.load(f)
    allok = True
    for s in SYMS:
        r = run_one(s); g = ref[s]
        m1 = _frame_identical(g["df_struct"], r["df_struct"])
        m2 = _frame_identical(g["df_h1"], r["df_h1"])
        sok = (g["n_struct"] == r["n_struct"]) and (g["structs"] == r["structs"])
        ok = (m1 is None) and (m2 is None) and sok
        allok &= ok
        print(f"[verify] {s}: h4={'OK' if m1 is None else m1} | h1={'OK' if m2 is None else m2} | "
              f"struct={g['n_struct']}=={r['n_struct']}&eq={sok} | dt={r['dt']*1000:.0f}ms  {'✅' if ok else '❌'}")
    print("\n" + ("✅ 전 출력 비트단위 동일" if allok else "❌ 불일치 — 리팩토링 재검토"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    (capture if (len(sys.argv) > 1 and sys.argv[1] == "capture") else verify)()
