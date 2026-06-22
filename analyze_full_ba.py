"""FINAL.py before/after(PATCH1) 풀백테스트 결과 대조 분석.
산출물: 헤드라인 PF, tier 분해, 월/연 시간분포, 후보레벨 R-PF, LEAK-1."""
import sys, io, glob, re, os
import pandas as pd
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BEF, AFT = "full_before", "full_after"

def g1(d, pat):
    hits = glob.glob(os.path.join(d, pat))
    return hits[0] if hits else None

def load(d, pat):
    fp = g1(d, pat)
    return pd.read_csv(fp) if fp else None

line = "=" * 78
print(line); print("FINAL.py  풀백테스트  BEFORE(원본) vs AFTER(PATCH1=off-by-one 제거)"); print(line)

# ── [1] 헤드라인 (overall_summary) ──
ob = load(BEF, "*_overall_summary.csv")
oa = load(AFT, "*_overall_summary.csv")
print("\n[1] 시나리오 종합 (BOOST15)")
if ob is not None and oa is not None:
    cols = [c for c in ["trades","win%","PF","avg_R","MDD%","Return_%"] if c in ob.columns]
    rb, ra = ob.iloc[0], oa.iloc[0]
    print(f"  {'metric':<12}{'BEFORE':>16}{'AFTER':>16}{'Δ':>16}")
    for c in cols:
        try:
            vb, va = float(rb[c]), float(ra[c])
            print(f"  {c:<12}{vb:>16.3f}{va:>16.3f}{va-vb:>16.3f}")
        except Exception:
            print(f"  {c:<12}{str(rb[c]):>16}{str(ra[c]):>16}")
else:
    print("  ! overall_summary 누락 — 런 미완료/실패 가능")

# ── [2] tier 분해 ──
tb = load(BEF, "tier_*_distribution.csv")
ta = load(AFT, "tier_*_distribution.csv")
print("\n[2] TIER 분해 (PF / trades / total_pnl)  ★ 룩어헤드 수익이 어느 tier에 몰렸나")
if tb is not None and ta is not None:
    m = tb.merge(ta, on="tier", how="outer", suffixes=("_b","_a")).fillna(0)
    print(f"  {'tier':<16}{'PF_b':>8}{'PF_a':>8}{'n_b':>7}{'n_a':>7}{'pnl_b':>13}{'pnl_a':>13}{'Δpnl':>13}")
    for _, r in m.iterrows():
        print(f"  {str(r['tier']):<16}{r.get('PF_b',0):>8.2f}{r.get('PF_a',0):>8.2f}"
              f"{int(r.get('trades_b',0)):>7}{int(r.get('trades_a',0)):>7}"
              f"{r.get('total_pnl_b',0):>13.0f}{r.get('total_pnl_a',0):>13.0f}"
              f"{r.get('total_pnl_a',0)-r.get('total_pnl_b',0):>13.0f}")
else:
    print("  ! tier_distribution 누락")

# ── [3] 시간 분포 (monthly → 연도 집계) ──
mb = load(BEF, "*_monthly.csv")
ma = load(AFT, "*_monthly.csv")
print("\n[3] 시간분포 — 연도별 net_pnl (월별 합산)")
def year_agg(df):
    if df is None: return None
    c_month = next((c for c in df.columns if c.lower() in ("month","ym","period")), None)
    c_pnl = next((c for c in df.columns if "pnl" in c.lower() and "krw" not in c.lower()), None)
    if c_pnl is None:
        c_pnl = next((c for c in df.columns if "pnl" in c.lower()), None)
    if c_month is None or c_pnl is None: return None
    s = df[[c_month, c_pnl]].copy()
    s["year"] = s[c_month].astype(str).str[:4]
    return s.groupby("year")[c_pnl].sum()
yb, ya = year_agg(mb), year_agg(ma)
if yb is not None and ya is not None:
    yrs = sorted(set(yb.index) | set(ya.index))
    print(f"  {'year':<8}{'BEFORE':>16}{'AFTER':>16}{'Δ':>16}")
    for y in yrs:
        vb, va = float(yb.get(y,0)), float(ya.get(y,0))
        print(f"  {y:<8}{vb:>16.0f}{va:>16.0f}{va-vb:>16.0f}")
    print(f"  {'TOTAL':<8}{yb.sum():>16.0f}{ya.sum():>16.0f}{ya.sum()-yb.sum():>16.0f}")
else:
    print("  ! monthly 컬럼 자동탐지 실패 — 컬럼:", None if mb is None else list(mb.columns))

# ── [4] 후보레벨 R-PF (diag parquet) ──
print("\n[4] 후보레벨 R-PF (필터 전 raw, 시뮬 전 단계)")
def rmet(fp):
    if not os.path.exists(fp): return None
    d = pd.read_parquet(fp)
    rp = d.loc[d.r_multiple>0,"r_multiple"].sum(); rn = d.loc[d.r_multiple<0,"r_multiple"].sum()
    return len(d), (rp/abs(rn) if rn else float('inf')), 100*(d.r_multiple>0).mean(), d.r_multiple.sum()
for tag, fp in [("BEFORE","diag_candidates_full_before.parquet"),("AFTER","diag_candidates_full_after.parquet")]:
    r = rmet(fp)
    if r: print(f"  {tag:<7} n={r[0]:>5}  R-PF={r[1]:>6.3f}  win={r[2]:>5.1f}%  sumR={r[3]:>7.1f}")
    else: print(f"  {tag:<7} (parquet 없음)")

# ── [5] LEAK-1 (로그 파싱) ──
print("\n[5] LEAK-1 same-bar entry (로그)")
for tag, lg in [("BEFORE","full_before.log"),("AFTER","full_after.log")]:
    if os.path.exists(lg):
        txt = open(lg, encoding='utf-8', errors='replace').read()
        m = re.search(r"\[LEAK-1\][^\n]*", txt)
        pf = re.search(r"PF\s*:\s*([\d.]+)", txt)
        print(f"  {tag:<7} {m.group(0) if m else '(LEAK-1 라인 없음)'}")
print(line)
