import numpy as np, pandas as pd
d = pd.read_csv("stage1_passrate_result/trades_old.csv")
w = pd.to_numeric(d["wick_ratio_5"], errors="coerce").dropna()
print(f"wick_ratio_5 유효 {len(w)}/{len(d)}건")
print("백분위:", {p: round(float(np.percentile(w, p)), 4) for p in (5,10,15,20,25,30,50)})
for thr in (0.15, 0.18, 0.20, 0.23, 0.35):
    print(f"  wick<= {thr}: {float((w<=thr).mean()*100):.1f}% pass")
# 20% 통과 임계 = 20th pct
print(f"→ a_wick 20% 목표 권장 임계 ≈ {float(np.percentile(w,20)):.3f} (현재 0.20→30.7%는 NaN제외분모 차이/표본)")
