"""
Wave-aware setup 분석 — (D1, H4, H1) wave_state 조합별 성과

핵심 질문:
  Q1) wave_state 단독: 각 TF의 wave별 PF/win%
  Q2) D1 × side: D1 trend 방향과 진입 방향 매칭
  Q3) D1 × H4 setup 매트릭스: D1 안에서 H4가 어떤 phase일 때 가장 좋은가
  Q4) Full multi-fractal setup (D1 × H4 × H1 × side)
  Q5) 12월 손실 구간의 wave_state 분포
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("stage4l_redist_outputs")
SCEN = "boost25"

t = pd.read_csv(OUT / f"stage4l_{SCEN}_out_skip_trades.csv")
t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*95); print(s); print(ch*95)

banner(f"[{SCEN.upper()}] 전체: {len(t)} / win {(t['net_pnl']>0).mean()*100:.2f}% / PF {fmt_pf(t):.2f}")

# =========================================================
# Q1: 각 TF 단독 wave_state 분포
# =========================================================
banner("Q1: 각 TF wave_state 단독 성과")
for col in ["d1_wave_state", "h4_wave_state", "h1_wave_state"]:
    print(f"\n[{col}]")
    print(f"  분포: {t[col].value_counts().to_dict()}")
    print(f"  {'state':<15} {'n':>5} {'%':>6} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
    for ws in t[col].dropna().unique():
        sub = t[t[col] == ws]
        if len(sub) == 0: continue
        print(f"  {str(ws):<15} {len(sub):>5} {len(sub)/len(t)*100:>5.1f}% "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.2f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# =========================================================
# Q2: D1 wave × side
# =========================================================
banner("Q2: D1 wave × side — 큰 트렌드 방향 vs 진입 방향")
print(f"\n  {'d1_wave':<15} {'side':<7} {'n':>5} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
for d1ws in sorted(t["d1_wave_state"].dropna().unique()):
    for side in ["long", "short"]:
        sub = t[(t["d1_wave_state"] == d1ws) & (t["side"] == side)]
        if len(sub) < 5: continue
        print(f"  {str(d1ws):<15} {side:<7} {len(sub):>5} "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.2f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# =========================================================
# Q3: D1 × H4 매트릭스 (side 합계)
# =========================================================
banner("Q3: D1 × H4 wave 매트릭스 — D1 큰 트렌드 + H4 phase")
print(f"\n  {'d1_wave':<15} {'h4_wave':<15} {'n':>5} {'win%':>7} {'PF':>8} {'avg_R':>8} {'pnl':>14}")
combos = []
for d1ws in sorted(t["d1_wave_state"].dropna().unique()):
    for h4ws in sorted(t["h4_wave_state"].dropna().unique()):
        sub = t[(t["d1_wave_state"] == d1ws) & (t["h4_wave_state"] == h4ws)]
        if len(sub) < 10: continue
        combos.append((d1ws, h4ws, len(sub), fmt_pf(sub), sub["net_pnl"].sum()))
        print(f"  {str(d1ws):<15} {str(h4ws):<15} {len(sub):>5} "
              f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>8.2f} "
              f"{sub['r_multiple'].mean():>+8.3f} {sub['net_pnl'].sum():>+14,.0f}")

# Top/Bottom PF
combos.sort(key=lambda x: -x[3])
print("\n  [Top 5 PF setup (D1 × H4)]")
for i, (d, h, n, pf, p) in enumerate(combos[:5]):
    print(f"    {i+1}. D1={d:<14} H4={h:<14} n={n:>4} PF={pf:>5.2f} pnl=${p:>+12,.0f}")
print("\n  [Bottom 5 PF setup (D1 × H4)]")
for i, (d, h, n, pf, p) in enumerate(combos[-5:]):
    print(f"    {i+1}. D1={d:<14} H4={h:<14} n={n:>4} PF={pf:>5.2f} pnl=${p:>+12,.0f}")

# =========================================================
# Q4: Full setup (D1 × H4 × H1 × side)
# =========================================================
banner("Q4: Multi-fractal full setup (n>=10)")
combos4 = []
for d1ws in t["d1_wave_state"].dropna().unique():
    for h4ws in t["h4_wave_state"].dropna().unique():
        for h1ws in t["h1_wave_state"].dropna().unique():
            for side in ["long", "short"]:
                sub = t[(t["d1_wave_state"] == d1ws) & (t["h4_wave_state"] == h4ws) &
                        (t["h1_wave_state"] == h1ws) & (t["side"] == side)]
                if len(sub) < 10: continue
                combos4.append({
                    "d1": d1ws, "h4": h4ws, "h1": h1ws, "side": side,
                    "n": len(sub),
                    "win_pct": (sub["net_pnl"]>0).mean()*100,
                    "pf": fmt_pf(sub),
                    "avg_r": sub["r_multiple"].mean(),
                    "pnl": sub["net_pnl"].sum(),
                })

cdf = pd.DataFrame(combos4)
if len(cdf):
    print(f"\n  setup 후보: {len(cdf)}개 (n>=10)")
    print("\n  [Top 10 PF setup]")
    print(f"  {'d1':<14} {'h4':<14} {'h1':<14} {'side':<6} {'n':>4} {'win%':>7} {'PF':>7} {'pnl':>13}")
    for _, r in cdf.sort_values("pf", ascending=False).head(10).iterrows():
        print(f"  {str(r['d1']):<14} {str(r['h4']):<14} {str(r['h1']):<14} {str(r['side']):<6} "
              f"{int(r['n']):>4} {r['win_pct']:>6.2f}% {r['pf']:>7.2f} ${r['pnl']:>+12,.0f}")
    print("\n  [Bottom 10 PF setup]")
    for _, r in cdf.sort_values("pf").head(10).iterrows():
        print(f"  {str(r['d1']):<14} {str(r['h4']):<14} {str(r['h1']):<14} {str(r['side']):<6} "
              f"{int(r['n']):>4} {r['win_pct']:>6.2f}% {r['pf']:>7.2f} ${r['pnl']:>+12,.0f}")

# =========================================================
# Q5: 12월 손실 구간 wave_state
# =========================================================
banner("Q5: 12월 손실 구간 (2025-12-15~31) wave_state 분포")
dec = t[(t["entry_time"] >= "2025-12-15") & (t["entry_time"] <= "2025-12-31")]
print(f"\n  12월 후반 trade: {len(dec)}")
if len(dec):
    print(f"  net_pnl: ${dec['net_pnl'].sum():+,.0f}, win {(dec['net_pnl']>0).mean()*100:.1f}%, PF {fmt_pf(dec):.2f}")
    for col in ["d1_wave_state", "h4_wave_state", "h1_wave_state"]:
        print(f"\n  [{col}]")
        print(dec[col].value_counts().to_string())

    # 손실 trade만
    dec_loss = dec[dec["net_pnl"] < 0]
    print(f"\n  [12월 손실 trade {len(dec_loss)}건의 wave 조합]")
    g = dec_loss.groupby(["d1_wave_state", "h4_wave_state", "h1_wave_state", "side"]).size().sort_values(ascending=False)
    print(g.head(15).to_string())

# =========================================================
# 핵심 결론
# =========================================================
banner("종합 — 가장 강한 / 약한 setup")
if len(combos4):
    overall_pf = fmt_pf(t)
    strong = cdf[cdf["pf"] > overall_pf * 1.5].sort_values("pf", ascending=False)
    weak   = cdf[cdf["pf"] < overall_pf * 0.7].sort_values("pf")
    print(f"\n  전체 PF baseline: {overall_pf:.2f}")
    print(f"  강한 setup (PF > {overall_pf*1.5:.2f}): {len(strong)}개, total trade {strong['n'].sum() if len(strong) else 0}")
    print(f"  약한 setup (PF < {overall_pf*0.7:.2f}): {len(weak)}개, total trade {weak['n'].sum() if len(weak) else 0}")
    if len(weak):
        print(f"\n  약한 setup이 차지하는 trade 수: {weak['n'].sum()} / {len(t)} ({weak['n'].sum()/len(t)*100:.1f}%)")
        print(f"  약한 setup 차단 시 예상 trade 감소: -{weak['n'].sum()}")
        print(f"  약한 setup 총 손실: ${weak[weak['pnl']<0]['pnl'].sum():+,.0f}")

    # weak/strong setup csv export
    weak.to_csv(OUT / "weak_setups.csv", index=False)
    strong.to_csv(OUT / "strong_setups.csv", index=False)
    print(f"\n  → weak {len(weak)}개, strong {len(strong)}개 csv 저장: {OUT}/")

    # weak setup Python list 출력 (main 코드에 박을 용도)
    print("\n[weak setup Python list (PF < {:.2f})]".format(fmt_pf(t)*0.7))
    print("WEAK_SETUPS = [")
    for _, r in weak.sort_values("pf").iterrows():
        print(f'    ("{r["d1"]}", "{r["h4"]}", "{r["h1"]}", "{r["side"]}"),  # n={int(r["n"])} PF={r["pf"]:.2f} pnl=${r["pnl"]:+,.0f}')
    print("]")
