import json, numpy as np, pandas as pd

def pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else float('inf')

base = "combo_files_result"
runs = ["pf10", "pf12", "pf13", "pf14"]
T = {r: pd.read_csv(f"{base}/trades_{r}.csv") for r in runs}
for r in runs:
    T[r]["exit_reason"] = T[r]["exit_reason"].astype(str)
    T[r] = T[r][~T[r]["exit_reason"].str.contains("close_at_end", case=False, na=False)].copy()
    T[r]["key"] = T[r]["symbol"].astype(str) + "|" + T[r]["entry_time"].astype(str)

# 1) 셋업 중첩(부분집합)
S = {}
for r in runs:
    d = json.load(open(f"combination backtest/setups_{r}.json", encoding="utf-8"))
    S[r] = set(s["key"] for s in d)
print("=== 1) 셋업 부분집합(중첩) 확인 ===")
for a, b in [("pf14", "pf13"), ("pf13", "pf12"), ("pf12", "pf10")]:
    print(f"  {a}({len(S[a])}) subset of {b}({len(S[b])}) ? {S[a].issubset(S[b])} | {a}-only={sorted(S[a]-S[b])}")

# 2) 거래 키 겹침
print("\n=== 2) 거래(symbol|entry_time) 겹침 ===")
for r in runs:
    print(f"  {r}: 거래 {len(T[r])}")
p10keys = set(T["pf10"]["key"])
for a in ["pf12", "pf13", "pf14"]:
    inter = T[a]["key"].isin(p10keys).sum()
    print(f"  {a} ∩ pf10 = {inter} / {len(T[a])}  ({inter/len(T[a])*100:.1f}% 가 pf10에도 동일거래)")

# 3) 공통거래 r_multiple 동일성 (버그 점검)
print("\n=== 3) 공통거래 r_multiple 동일성 (pf14 ∩ pf10) ===")
m = T["pf14"].merge(T["pf10"][["key", "r_multiple"]], on="key", suffixes=("_14", "_10"))
if len(m):
    diff = (m["r_multiple_14"] - m["r_multiple_10"]).abs()
    print(f"  공통 {len(m)}건 | r_multiple 최대차={diff.max():.4f} | 불일치(>1e-6)={int((diff>1e-6).sum())}")
else:
    print("  공통 거래 0건")

# 4) 런별 PF & pf14 신규 vs 공통
print("\n=== 4) 런별 PF & pf14 신규거래(=pf10에 없던) PF ===")
for r in runs:
    print(f"  {r}: PF={pf(T[r]['net_pnl']):.4f}  avgR={T[r]['r_multiple'].mean():.4f}")
only14 = T["pf14"][~T["pf14"]["key"].isin(p10keys)]
shared14 = T["pf14"][T["pf14"]["key"].isin(p10keys)]
print(f"  pf14 신규거래 {len(only14)}건: PF={pf(only14['net_pnl']):.4f} avgR={only14['r_multiple'].mean():.4f} 승률={(only14['net_pnl']>0).mean()*100:.1f}%")
print(f"  pf14 공통거래 {len(shared14)}건: PF={pf(shared14['net_pnl']):.4f} avgR={shared14['r_multiple'].mean():.4f} 승률={(shared14['net_pnl']>0).mean()*100:.1f}%")

# 5) matched_setup 분포: pf14에서 실제로 어떤 셋업으로 귀속됐나 (상위)
print("\n=== 5) pf14 matched_setup 분포(상위10, 셋업 setup_pf 와 대조) ===")
vc = T["pf14"]["matched_setup"].value_counts()
for k, c in vc.head(10).items():
    g = T["pf14"][T["pf14"]["matched_setup"] == k]
    print(f"  {c:4d}건 PF={pf(g['net_pnl']):6.3f}  {k}")
