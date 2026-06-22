"""가드레일3/4: HONEST_STAGE 0..5 단계별 결과 교차분석.
각 stage4d_honest/sN/ 에서 overall_summary + trades 읽어 단계별 PF/거래수/tier/연도 대조.
누적 토글이므로 인접단계 Δ = 그 원소그룹의 누수 기여도."""
import os, sys, io
import pandas as pd
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "stage4d_honest")
LABEL = {0: "원본(누수포함)", 1: "S0 zone당봉배제", 2: "+S1 rp/trend/atr",
         3: "+S2 confl/wick", 4: "+S3 mstate/h1choch", 5: "+S4 trade_tags"}
STAGES = [s for s in range(6) if os.path.exists(os.path.join(BASE, f"s{s}", "stage4d_overall_summary.csv"))]

def load_sum(s):
    fp = os.path.join(BASE, f"s{s}", "stage4d_overall_summary.csv")
    return pd.read_csv(fp).iloc[0] if os.path.exists(fp) else None

def load_trades(s):
    fp = os.path.join(BASE, f"s{s}", "stage4d_trades.csv")
    if not os.path.exists(fp):
        return None
    d = pd.read_csv(fp)
    if "entry_time" in d.columns:
        d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
    return d

L = "=" * 88
print(L); print("HONEST_STAGE 단계별 분리측정 (누적 토글 — 인접 Δ = 해당 원소그룹 누수기여)"); print(L)

# [1] 헤드라인 추이
print("\n[1] 헤드라인 단계별 추이")
print(f"  {'stage':<20}{'trades':>8}{'win%':>8}{'PF':>8}{'avg_R':>8}{'Return%':>10}{'ΔPF':>8}{'Δtr':>7}")
prev_pf, prev_tr = None, None
rows = []
for s in STAGES:
    r = load_sum(s)
    if r is None:
        continue
    pf = float(r["PF"]); tr = int(r["trades"])
    dpf = "" if prev_pf is None else f"{pf-prev_pf:+.3f}"
    dtr = "" if prev_tr is None else f"{tr-prev_tr:+d}"
    print(f"  {LABEL[s]:<20}{tr:>8}{float(r['win%']):>8.2f}{pf:>8.3f}"
          f"{float(r['avg_R']):>8.3f}{float(r['Return_%']):>10.1f}{dpf:>8}{dtr:>7}")
    rows.append((s, tr, pf))
    prev_pf, prev_tr = pf, tr

# [2] tier 분해 (단계별 PF / trades)
print("\n[2] TIER 분해 — 단계별 PF (괄호: trades)  ★ 누수수익이 몰린 tier 추적")
tier_pf = {}
all_tiers = set()
for s in STAGES:
    d = load_trades(s)
    if d is None or "tier" not in d.columns or len(d) == 0:
        continue
    g = {}
    for t, sub in d.groupby("tier"):
        gp = sub.loc[sub.net_pnl > 0, "net_pnl"].sum()
        gl = abs(sub.loc[sub.net_pnl < 0, "net_pnl"].sum())
        g[t] = (gp / max(gl, 1e-9), len(sub))
        all_tiers.add(t)
    tier_pf[s] = g
hdr = "  " + f"{'tier':<16}" + "".join(f"{LABEL[s][:11]:>14}" for s in STAGES if s in tier_pf)
print(hdr)
for t in sorted(all_tiers, key=str):
    cells = ""
    for s in STAGES:
        if s in tier_pf:
            v = tier_pf[s].get(t)
            cells += f"{(f'{v[0]:.2f}({v[1]})' if v else '-'):>14}"
    print(f"  {str(t):<16}{cells}")

# [3] 연도별 net_pnl
print("\n[3] 연도별 net_pnl (단계별)")
yr_pnl = {}
all_years = set()
for s in STAGES:
    d = load_trades(s)
    if d is None or "year" not in d.columns or len(d) == 0:
        continue
    g = d.groupby("year")["net_pnl"].sum()
    yr_pnl[s] = g
    all_years.update(g.index.dropna().tolist())
print("  " + f"{'year':<8}" + "".join(f"{LABEL[s][:11]:>14}" for s in STAGES if s in yr_pnl))
for y in sorted(all_years):
    cells = "".join(f"{yr_pnl[s].get(y, 0):>14.0f}" for s in STAGES if s in yr_pnl)
    print(f"  {int(y):<8}{cells}")
print("  " + f"{'TOTAL':<8}" + "".join(f"{yr_pnl[s].sum():>14.0f}" for s in STAGES if s in yr_pnl))

# [4] 누수기여 요약
print("\n[4] 단계별 누수기여 요약 (PF/거래수 ΔΔ)")
for i in range(1, len(rows)):
    ps, ptr, ppf = rows[i-1]
    cs, ctr, cpf = rows[i]
    print(f"  {LABEL[cs]:<20} ΔPF={cpf-ppf:+.3f}  Δtrades={ctr-ptr:+d}  (PF {ppf:.3f}→{cpf:.3f})")
if rows:
    print(f"\n  ▶ 원본 PF {rows[0][2]:.3f} → 최종정직 PF {rows[-1][2]:.3f}  "
          f"(거래 {rows[0][1]}→{rows[-1][1]})")
print(L)
