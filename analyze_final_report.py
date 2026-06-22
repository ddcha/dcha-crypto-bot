"""
최종 종합 리포트 — 사용자 요청 대응
  A) 시나리오 메트릭 표 (BOOST15/25/35 × baseline/A/A+B)
     - total_assets_end / peak / MDD% / MDD$ / retirement_month / retirement_months
     - PF / Win% / Return% / trades
  B) Wave 파악 효과
     - 전체 wave_state 분포 (D1/H4/H1) + unclear 비율
     - 처방 정의 정리 (WEAK_SETUPS 21개 + WAVE PATTERNS 6개)
     - 처방 적용된 trade 분포
     - wave 인식 → 효과 측정
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np
from pathlib import Path

BASE  = Path("stage4l_redist_outputs_wave_baseline")
OPTA  = Path("stage4l_redist_outputs_optionA")
OPTAB = Path("stage4l_redist_outputs")
SCEN  = ["boost15", "boost25", "boost35"]
STAGE_LABEL = {"baseline": BASE, "optionA": OPTA, "optionAB": OPTAB}

KRW_PER_USDT = 1350.0

def fmt_pf(sub):
    if len(sub) == 0: return 0.0
    g = sub[sub["net_pnl"]>0]["net_pnl"].sum()
    l = abs(sub[sub["net_pnl"]<0]["net_pnl"].sum())
    return g / max(l, 1e-9)

def banner(s, ch="="):
    print(); print(ch*100); print(s); print(ch*100)

def calc_mdd_dollar(eq):
    eq = eq.copy()
    eq["dd_dollar"] = eq["total_assets"] - eq["cummax"]
    return float(eq["dd_dollar"].min())

# ─────────────────────────────────────────────────────────
# A) 시나리오 메트릭 표
# ─────────────────────────────────────────────────────────
banner("[ A ] 시나리오 종합 메트릭 (3 시나리오 × 3 단계)", "█")

# 단계별 한 번에 표시
for sc in SCEN:
    banner(f"BOOST{sc[5:]}", "=")
    print(f"\n  {'단계':<10} {'PF':>6} {'Win%':>6} {'MDD%':>6} {'MDD$':>14} "
          f"{'Return%':>10} {'total_end$':>14} {'total_peak$':>14} "
          f"{'retire_m':>9} {'retire':>10}")
    print("  " + "-" * 110)
    for stage_name, stage_path in STAGE_LABEL.items():
        s = pd.read_csv(stage_path / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
        eq = pd.read_csv(stage_path / f"stage4l_{sc}_out_skip_equity.csv")
        mdd_dollar = calc_mdd_dollar(eq)
        # KRW 단위 total_assets 인 듯 (overall_summary 의 단위 확인 필요)
        # overall summary csv 의 total_assets_end 단위가 KRW
        end_krw = float(s["total_assets_end"])
        peak_krw = float(s["total_assets_peak"])
        ret = str(s["retirement"])
        ret_m = s["retirement_months"]
        print(f"  {stage_name:<10} {s['PF']:>6.3f} {s['win%']:>5.2f}% {s['MDD%']:>5.2f}% "
              f"${mdd_dollar:>+13,.0f} "
              f"{s['Return_%']:>9.0f}% {end_krw:>14,.0f} {peak_krw:>14,.0f} "
              f"{str(ret_m):>9} {ret:>10}")

# 한눈에 보기: optionAB 만 비교
banner("[ A 요약 ] optionAB 최종 (3 시나리오 비교)", "=")
print(f"\n  {'시나리오':<10} {'PF':>6} {'Win%':>6} {'MDD%':>6} {'MDD$':>14} "
      f"{'Return%':>10} {'total_end$':>14} {'retire_m':>9}")
print("  " + "-" * 90)
for sc in SCEN:
    s  = pd.read_csv(OPTAB / f"stage4l_{sc}_out_skip_overall_summary.csv").iloc[0]
    eq = pd.read_csv(OPTAB / f"stage4l_{sc}_out_skip_equity.csv")
    mdd_dollar = calc_mdd_dollar(eq)
    print(f"  BOOST{sc[5:]:<5} {s['PF']:>6.3f} {s['win%']:>5.2f}% {s['MDD%']:>5.2f}% "
          f"${mdd_dollar:>+13,.0f} "
          f"{s['Return_%']:>9.0f}% {float(s['total_assets_end']):>14,.0f} "
          f"{str(s['retirement_months']):>9}")

# ─────────────────────────────────────────────────────────
# B) Wave 파악 효과
# ─────────────────────────────────────────────────────────
banner("[ B ] Wave 파악 효과 + 처방 적용 분포", "█")

# B1: 처방 정의 정리
banner("[ B-1 ] 적용된 처방 종류 + 정의", "=")
print("""
  [옵션 A] Weak Setup Blacklist — 명시적 (d1, h4, h1, side) 21개 조합 risk × 0.3
    근거: backtest 분석에서 PF < 0.7 × baseline (≈ 1.87) 조합
    — n=291 (22.1%) trade 적용

  [옵션 B] Wave Pattern Rules — 6개 일반 패턴
    WEAK (risk 축소):
      1) D1 ≠ H4 (opposite trends)         × 0.5
      2) H1 = expansion + side = SHORT    × 0.5
      3) D1 = impulse_up + H4 = correction + side = LONG  × 0.7
    STRONG (risk boost):
      4) D1 = expansion AND H4 = expansion × 1.5
      5) H1 = compression + side = SHORT   × 1.3
      6) H1 = compression + side = LONG    × 1.2
    — n=627 (47.5%) trade 적용

  [기존 PD-aware filter]
    discount + side = SHORT  × 0.5
    — n=376 (28.5%) trade 적용
""")

# B2: wave_state 분포 (D1, H4, H1)
banner("[ B-2 ] Wave State 분포 — 데이터 인식률", "=")
t = pd.read_csv(OPTAB / "stage4l_boost25_out_skip_trades.csv")
n_total = len(t)
print(f"\n전체 {n_total} trades (BOOST25, A+B 적용 기준)")

for col in ["d1_wave_state", "h4_wave_state", "h1_wave_state"]:
    print(f"\n  [{col}]")
    vc = t[col].value_counts()
    for ws, cnt in vc.items():
        print(f"    {str(ws):<15} {cnt:>5} ({cnt/n_total*100:>5.1f}%)")
    n_unclear = (t[col] == "unclear").sum()
    print(f"    → 인식률: {(n_total - n_unclear)/n_total*100:.1f}% (unclear {n_unclear/n_total*100:.1f}%)")

# B3: combined mult 분포 (각 trade가 어느 처방을 받았는가)
banner("[ B-3 ] 처방 적용 분포 — 어떤 trade에 어느 처방이 적용됐는가", "=")
t["combined_mult"] = t.get("pd_aware_mult",1.0) * t.get("weak_setup_mult",1.0) * t.get("wave_pattern_mult",1.0)
print(f"\n  combined mult 분포 (전체 {n_total})")
print(f"  {'mult bin':<13} {'n':>5} {'%':>7} {'win%':>7} {'PF':>7} {'pnl':>14}")
for lo, hi, label in [
    (0,    0.30, "0.0-0.3 (강한 reduce)"),
    (0.30, 0.50, "0.3-0.5 (중간 reduce)"),
    (0.50, 0.80, "0.5-0.8 (약한 reduce)"),
    (0.80, 1.05, "0.8-1.05 (변경 없음)"),
    (1.05, 1.50, "1.05-1.5 (boost)"),
    (1.50, 3.00, "1.5+ (강한 boost)"),
]:
    sub = t[(t["combined_mult"] >= lo) & (t["combined_mult"] < hi)]
    if len(sub) == 0: continue
    print(f"  {label:<22} {len(sub):>5} {len(sub)/n_total*100:>5.1f}% "
          f"{(sub['net_pnl']>0).mean()*100:>6.2f}% {fmt_pf(sub):>7.2f} {sub['net_pnl'].sum():>+14,.0f}")

# 처방 받은 trade vs 안 받은 trade
n_modified = (t["combined_mult"] != 1.0).sum()
print(f"\n  → 처방 영향 받은 trade: {n_modified} ({n_modified/n_total*100:.1f}%)")
print(f"  → 처방 영향 없는 trade: {n_total - n_modified} ({(n_total-n_modified)/n_total*100:.1f}%)")

# B4: Wave 파악 효과 측정 — baseline 대비 처방으로 회수한 손실
banner("[ B-4 ] Wave 처방으로 회수한 효과 (BOOST25)", "=")
b_t = pd.read_csv(BASE / "stage4l_boost25_out_skip_trades.csv")
ab_t = t

print(f"\n  baseline trades (n={len(b_t)})")
print(f"    PF={fmt_pf(b_t):.3f}  win%={(b_t['net_pnl']>0).mean()*100:.2f}%  "
      f"net=$ {b_t['net_pnl'].sum():+,.0f}")
print(f"\n  optionAB trades (n={len(ab_t)})")
print(f"    PF={fmt_pf(ab_t):.3f}  win%={(ab_t['net_pnl']>0).mean()*100:.2f}%  "
      f"net=$ {ab_t['net_pnl'].sum():+,.0f}")
diff = ab_t["net_pnl"].sum() - b_t["net_pnl"].sum()
print(f"\n  net_pnl 차이: ${diff:+,.0f}")

# 12월 구간 회복
print(f"\n  [12월 손실 구간 (2025-12-15~31) 회복]")
b_t["entry_time"] = pd.to_datetime(b_t["entry_time"], utc=True)
ab_t["entry_time"] = pd.to_datetime(ab_t["entry_time"], utc=True)
b_dec = b_t[(b_t["entry_time"]>="2025-12-15") & (b_t["entry_time"]<="2025-12-31")]
ab_dec = ab_t[(ab_t["entry_time"]>="2025-12-15") & (ab_t["entry_time"]<="2025-12-31")]
print(f"    baseline 12월: PF={fmt_pf(b_dec):.2f} pnl=${b_dec['net_pnl'].sum():+,.0f}")
print(f"    optionAB 12월: PF={fmt_pf(ab_dec):.2f} pnl=${ab_dec['net_pnl'].sum():+,.0f}")
print(f"    회수 금액: ${ab_dec['net_pnl'].sum() - b_dec['net_pnl'].sum():+,.0f}")
