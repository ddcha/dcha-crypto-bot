"""
세 가지 분석:
  [A] Neutral 비율 (entered trades 중 trend=neutral 비율)
  [B] Trend 차단으로 skip된 비율 (skipped.csv 분석)
  [C] EMA vs H1 CHoCH 비교 (main vs h1choch 결과)
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path('D:/smc_bot')
PATHS = {
    'main(EMA)':    ROOT / 'stage4l_redist_outputs_main_20260513',
    'h1choch':      ROOT / 'stage4l_redist_outputs_h1choch_20260513',
    'v3_conservative': ROOT / 'stage4l_redist_outputs_v3_conservative',
}
SCENARIOS = ['BOOST15', 'BOOST25', 'BOOST35']

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return float(g/max(l,1e-9))

# ─────────────────────────────────────────────────────────
# [A] Neutral 비율 — entered trades 의 trend 분포
# ─────────────────────────────────────────────────────────
print('='*100)
print('[A] 진입된 trades 의 H4 trend 분포 (v3 conservative 기준)')
print('='*100)

v3_dir = PATHS['v3_conservative']
all_v3_trades = {}
for sc in SCENARIOS:
    t = pd.read_csv(v3_dir / f'stage4l_{sc.lower()}_out_skip_trades.csv')
    all_v3_trades[sc] = t

print(f'\n각 시나리오 entered trades 의 a_trend_align + last_choch_direction:')
print(f'  - a_trend_align=True  → trend가 진입 방향과 일치')
print(f'  - a_trend_align=False → trend=neutral (반대였다면 hard gate에서 차단)')
print(f'  - last_choch_direction: bull/bear/none/tie')
print()

for sc, t in all_v3_trades.items():
    print(f'\n[{sc}] total {len(t)} entries')
    # a_trend_align
    tal_true = int(t['a_trend_align'].sum())
    tal_false = int(len(t) - tal_true)
    print(f'  a_trend_align=True  (trend 일치): {tal_true:>4d} ({tal_true/len(t)*100:5.1f}%)')
    print(f'  a_trend_align=False (trend neutral): {tal_false:>4d} ({tal_false/len(t)*100:5.1f}%)')

    # last_choch_direction (entry 시점 H4 trend 추적 컬럼)
    if 'last_choch_direction' in t.columns:
        print(f'\n  last_choch_direction 분포:')
        dist = t['last_choch_direction'].value_counts()
        for k, v in dist.items():
            print(f'    {str(k):<10}: {v:>5d} ({v/len(t)*100:5.1f}%)')

    # side × a_trend_align cross
    print(f'\n  side × a_trend_align cross:')
    ct = pd.crosstab(t['side'], t['a_trend_align'], margins=True)
    print(ct.to_string())

    # 가설 검증: a_trend_align=False trades의 last_choch_direction
    if 'last_choch_direction' in t.columns:
        false_subset = t[t['a_trend_align']==False]
        if len(false_subset) > 0:
            print(f'\n  a_trend_align=False trades 의 last_choch_direction:')
            for k, v in false_subset['last_choch_direction'].value_counts().items():
                print(f'    {str(k):<10}: {v:>5d}')

# ─────────────────────────────────────────────────────────
# [B] Trend 차단으로 skip된 비율 — skipped.csv 분석
# ─────────────────────────────────────────────────────────
print()
print('='*100)
print('[B] skipped.csv 분석 — skip 사유별 비율')
print('='*100)

# v3 BOOST25 기준으로 분석
sk_v3 = pd.read_csv(v3_dir / 'stage4l_boost25_out_skip_skipped.csv')
print(f'\n[v3 BOOST25] total skipped = {len(sk_v3)}')

reason_counts = sk_v3['reason'].value_counts()
print(f'\nskip 사유 Top 20:')
print(f'{"reason":<60}{"count":>8}{"%":>8}')
for reason, count in reason_counts.head(20).items():
    print(f'{str(reason)[:60]:<60}{count:>8d}{count/len(sk_v3)*100:>7.1f}%')

# trend 관련 사유 검색
print(f'\n--- trend / wave 관련 skip 사유 (substring match) ---')
trend_skips = sk_v3[sk_v3['reason'].str.contains('trend|wave|d1|choch', case=False, na=False)]
if len(trend_skips) > 0:
    trend_rc = trend_skips['reason'].value_counts()
    for r, c in trend_rc.items():
        print(f'  {r:<60}: {c:>5d} ({c/len(sk_v3)*100:5.1f}%)')
else:
    print('  (trend 관련 명시적 skip 사유 없음 — hard gate가 _track_skip 호출 안 함)')

# 추정: hard gate로 진입 안 한 트레이드 수
# 방법: main(EMA) vs h1choch 비교 → trend 알고리즘만 바꿨을 때 trade 수 차이
print(f'\n[B-추정] hard gate trend 차단 비율 추정 (간접):')
print(f'  v3 BOOST25: entered = {len(all_v3_trades["BOOST25"])} | skipped = {len(sk_v3)}')
print(f'  총 후보 = entered + skipped = {len(all_v3_trades["BOOST25"]) + len(sk_v3)}')
print(f'  진입율 = {len(all_v3_trades["BOOST25"]) / (len(all_v3_trades["BOOST25"]) + len(sk_v3)) * 100:.1f}%')
print(f'  ⚠ trend hard gate는 _track_skip 없이 continue → skipped.csv 에 안 잡힘.')
print(f'  ⚠ 따라서 진짜 trend skip 수는 위 숫자보다 더 클 수 있음.')

# ─────────────────────────────────────────────────────────
# [C] EMA vs H1 CHoCH 비교 — main vs h1choch
# ─────────────────────────────────────────────────────────
print()
print('='*100)
print('[C] EMA trend vs H1 CHoCH trend 비교')
print('='*100)
print('비교 베이스:')
print('  - main(EMA)  : stage4l_redist (h1choch 패치 X) — EMA 기반 H4 trend')
print('  - h1choch    : stage4l_redist_h1choch — H1 CHoCH 기반 trend + 기타 Step2/3 패치 모두')
print('  → 순수 trend 알고리즘 차이는 아니지만 h1choch 패치 전후 종합 효과 측정')
print()

print(f'{"scenario":<10}{"version":<12}{"trades":>8}{"win%":>7}{"PF":>8}{"MDD%":>8}{"Return%":>10}')
for sc in SCENARIOS:
    for ver, path in [('main(EMA)', PATHS['main(EMA)']), ('h1choch', PATHS['h1choch'])]:
        f = path / 'stage4l_comparison_summary.csv'
        if not f.exists(): continue
        s = pd.read_csv(f)
        row = s[s.scenario==sc]
        if len(row)==0: continue
        r = row.iloc[0]
        print(f'{sc:<10}{ver:<12}{int(r.trades):>8d}{r["win%"]:>7.2f}{r.PF:>8.3f}{r["MDD%"]:>8.2f}{r["Return_%"]:>10.0f}')
    print()

# [C2] entered trades 의 a_trend_align 비교 (main vs h1choch vs v3)
print()
print('='*100)
print('[C2] a_trend_align=True 비율 — trend 알고리즘이 얼마나 정확한지')
print('='*100)
print(f'{"version":<15}{"scenario":<10}{"trades":>8}{"align_true":>12}{"align_true_%":>14}')

for sc in SCENARIOS:
    for ver_name, ver_path in PATHS.items():
        f = ver_path / f'stage4l_{sc.lower()}_out_skip_trades.csv'
        if not f.exists():
            continue
        t = pd.read_csv(f)
        if 'a_trend_align' not in t.columns:
            print(f'{ver_name:<15}{sc:<10}{len(t):>8d}  (a_trend_align 컬럼 없음)')
            continue
        true_n = int(t['a_trend_align'].sum())
        pct = true_n/len(t)*100
        print(f'{ver_name:<15}{sc:<10}{len(t):>8d}{true_n:>12d}{pct:>13.1f}%')
    print()

# [C3] tier 분포 비교 (main vs h1choch)
print()
print('='*100)
print('[C3] Tier 분포 변화 (BOOST25 기준)')
print('='*100)
print('a_trend_align 이 tier 분류에 큰 영향을 주므로, tier 분포 변화로 trend 효과 가시화')
print(f'\n{"tier":<18}{"main(EMA)":>14}{"h1choch":>14}{"v3":>14}{"Δ(h1-main)":>14}')

tiers = ['ALPHA_MAX', 'ALPHA_HIGH', 'ALPHA_MED', 'SWEEP_GEM', 'SWEEP_ROOM_FVG', 'SWEEP_ROOM_ONLY']
tier_data = {}
for ver_name, ver_path in PATHS.items():
    f = ver_path / 'tier_stage4l_boost25_distribution.csv'
    if not f.exists():
        tier_data[ver_name] = None
        continue
    d = pd.read_csv(f)
    tier_data[ver_name] = {row.tier: row.trades for _, row in d.iterrows()}

for tier in tiers:
    main_n = tier_data.get('main(EMA)', {}).get(tier, 0) if tier_data.get('main(EMA)') else 0
    h1_n   = tier_data.get('h1choch',   {}).get(tier, 0) if tier_data.get('h1choch') else 0
    v3_n   = tier_data.get('v3_conservative', {}).get(tier, 0) if tier_data.get('v3_conservative') else 0
    diff = h1_n - main_n
    print(f'{tier:<18}{main_n:>14d}{h1_n:>14d}{v3_n:>14d}{diff:>+14d}')

# [C4] tier 별 PF 비교
print()
print('='*100)
print('[C4] Tier 별 PF 변화 (main vs h1choch)')
print('='*100)
print(f'\n{"tier":<18}{"main_PF":>12}{"h1choch_PF":>14}{"v3_PF":>10}{"Δ(h1-main)":>14}')

tier_pf = {}
for ver_name, ver_path in PATHS.items():
    f = ver_path / 'tier_stage4l_boost25_distribution.csv'
    if not f.exists():
        tier_pf[ver_name] = {}
        continue
    d = pd.read_csv(f)
    tier_pf[ver_name] = {row.tier: row.PF for _, row in d.iterrows()}

for tier in tiers:
    main_pf = tier_pf.get('main(EMA)', {}).get(tier, 0)
    h1_pf = tier_pf.get('h1choch', {}).get(tier, 0)
    v3_pf = tier_pf.get('v3_conservative', {}).get(tier, 0)
    diff = h1_pf - main_pf if main_pf else 0
    print(f'{tier:<18}{main_pf:>12.3f}{h1_pf:>14.3f}{v3_pf:>10.3f}{diff:>+14.3f}')

# [C5] 종합 — h1choch trend 알고리즘이 만든 net 효과
print()
print('='*100)
print('[C5] 종합: H1 CHoCH trend 패치의 net 효과 (BOOST25 기준)')
print('='*100)

main_sum = pd.read_csv(PATHS['main(EMA)'] / 'stage4l_comparison_summary.csv')
h1_sum   = pd.read_csv(PATHS['h1choch']   / 'stage4l_comparison_summary.csv')

main_b25 = main_sum[main_sum.scenario=='BOOST25'].iloc[0]
h1_b25   = h1_sum[h1_sum.scenario=='BOOST25'].iloc[0]

print(f'\n{"metric":<20}{"main(EMA)":>14}{"h1choch":>14}{"Δ":>14}{"Δ%":>10}')
metrics = [
    ('trades', '.0f'),
    ('win%', '.2f'),
    ('PF', '.3f'),
    ('MDD%', '.2f'),
    ('Return_%', '.0f'),
]
for m, fmt in metrics:
    mv = main_b25[m]
    hv = h1_b25[m]
    diff = hv - mv
    pct = (diff/mv*100) if mv != 0 else 0
    print(f'{m:<20}{format(mv, fmt):>14}{format(hv, fmt):>14}{format(diff, fmt):>14}{pct:>+9.1f}%')

print(f'\n  → trades: {int(h1_b25["trades"])-int(main_b25["trades"]):+d} 변화 (다른 패치 효과 포함)')
print(f'  → PF: {h1_b25["PF"]:.3f} = main 의 {h1_b25["PF"]/main_b25["PF"]*100:.0f}% (= +{(h1_b25["PF"]/main_b25["PF"]-1)*100:.0f}% 개선)')
print(f'  → Return: {(h1_b25["Return_%"]-main_b25["Return_%"])/main_b25["Return_%"]*100:+.0f}% 개선')
