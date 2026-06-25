import numpy as np, pandas as pd
def pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else float('inf')
def load(d, r):
    t = pd.read_csv(f"{d}/trades_{r}.csv")
    t["exit_reason"] = t["exit_reason"].astype(str)
    t = t[~t["exit_reason"].str.contains("close_at_end", case=False, na=False)].copy()
    t["key"] = t["symbol"].astype(str) + "|" + pd.to_datetime(t["entry_time"], utc=True).astype(str)
    return t
runs = ["pf10", "pf12", "pf13", "pf14"]
OLD = {r: load("combo_files_result", r) for r in runs}
CLN = {r: load("combo_files_clean_result", r) for r in runs}

print("=== 클린 vs 오염(이전) — 거래수·PF ===")
print(f"{'파일':<6}{'오염 n/PF':>16}{'클린 n/PF':>16}")
for r in runs:
    print(f"{r:<6}{f'{len(OLD[r])}/{pf(OLD[r].net_pnl):.3f}':>16}{f'{len(CLN[r])}/{pf(CLN[r].net_pnl):.3f}':>16}")

print("\n=== 검증: pf10 클린==오염? (1패스라 동일해야) ===")
ka, kb = set(OLD['pf10'].key), set(CLN['pf10'].key)
print(f"  pf10 오염 {len(ka)} / 클린 {len(kb)} | 키 대칭차 {len(ka^kb)} (0이면 동일=리셋 안전·pf10 클린확인)")

print("\n=== 클린: pf12/13/14 거래가 pf10 거래의 부분집합? (가설B 재검) ===")
p10 = set(CLN['pf10'].key)
for r in ["pf12", "pf13", "pf14"]:
    k = set(CLN[r].key); inter = len(k & p10)
    print(f"  {r}: 거래 {len(k)} | ∩pf10 {inter} ({inter/len(k)*100:.1f}%) | ⊆pf10? {k.issubset(p10)}")

print("\n=== 클린 pf14: 신규(=pf10에 없던) vs 공통 거래 PF (가설A 재검) ===")
only = CLN['pf14'][~CLN['pf14'].key.isin(p10)]; shar = CLN['pf14'][CLN['pf14'].key.isin(p10)]
print(f"  공통 {len(shar)}건 PF={pf(shar.net_pnl):.3f} | 신규 {len(only)}건 PF={pf(only.net_pnl):.3f}")
