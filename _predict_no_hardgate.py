"""
Hard gate (trend 반대 차단) 제거 시 결과 예측

[데이터 기반 추론]
  main(EMA) trades 중 a_trend_align=False (= trend 안 맞음) 524건 분석
  → 이들이 "trend mismatch 인데 들어간 trade" 의 표본
  → 만약 v3 에서도 hard gate 없애면 이런 trade들이 추가됨
  → 그 PF/Win% 가 어떨지가 핵심

[한계]
  main 의 EMA neutral != H1 CHoCH 반대. 완전 정확하지 않음.
  단, 일반적으로 trend 안 맞는 entry가 어떤 성과인지 표본 측정 가능.
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
import numpy as np

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return float(g/max(l,1e-9))

main = pd.read_csv('D:/smc_bot/stage4l_redist_outputs_main_20260513/stage4l_boost25_out_skip_trades.csv')
print('='*100)
print('[A] main(EMA) BOOST25 — a_trend_align=True vs False 비교')
print('='*100)
print(f'\ntotal entered = {len(main)}')

for align in [True, False]:
    sub = main[main['a_trend_align']==align]
    if len(sub)==0: continue
    w = (sub.net_pnl>0).mean()*100
    print(f'\n  a_trend_align={align}: n={len(sub)} ({len(sub)/len(main)*100:.1f}%)')
    print(f'    Win%   : {w:.2f}%')
    print(f'    PF     : {pf(sub.net_pnl):.3f}')
    print(f'    avg_R  : {sub.r_multiple.mean():.3f}')
    print(f'    pnl    : ${sub.net_pnl.sum():,.0f}')
    print(f'    avg pnl: ${sub.net_pnl.mean():,.0f}')

# 가설 검증: align=False 가 align=True 보다 약함?
align_t = main[main['a_trend_align']==True]
align_f = main[main['a_trend_align']==False]
print(f'\n[비교]')
print(f'  PF ratio (False/True): {pf(align_f.net_pnl)/pf(align_t.net_pnl):.3f}')
print(f'  align=False 가 align=True 의 PF 의 {pf(align_f.net_pnl)/pf(align_t.net_pnl)*100:.0f}%')

# Tier 별 align=False 의 PF
print('\n[A2] main(EMA) BOOST25 — align=False trade 의 tier 별 PF')
print(f'{"tier":<18}{"n":>6}{"win%":>8}{"PF":>8}{"pnl":>14}')
for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
    sub = align_f[align_f.tier==tier]
    if len(sub)==0: continue
    w = (sub.net_pnl>0).mean()*100
    print(f'{tier:<18}{len(sub):>6d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

# side 별
print('\n[A3] main(EMA) BOOST25 — align=False 의 side 별')
print(f'{"side":<10}{"n":>6}{"win%":>8}{"PF":>8}{"pnl":>14}')
for s in ['long','short']:
    sub = align_f[align_f.side==s]
    if len(sub)==0: continue
    w = (sub.net_pnl>0).mean()*100
    print(f'{s:<10}{len(sub):>6d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

# Total pnl 기여도
total_pnl = main.net_pnl.sum()
print(f'\n[A4] PnL 기여도')
print(f'  align=True  pnl: ${align_t.net_pnl.sum():>12,.0f}  ({align_t.net_pnl.sum()/total_pnl*100:.1f}% of total)')
print(f'  align=False pnl: ${align_f.net_pnl.sum():>12,.0f}  ({align_f.net_pnl.sum()/total_pnl*100:.1f}% of total)')

# 만약 align=False 제거 (= hard gate 강화) 시 효과
print(f'\n[A5] 만약 main 에서 align=False trade 모두 제거 시 (= hard gate가 완벽히 작동)')
only_align = align_t.copy()
print(f'  trades : {len(main)} → {len(only_align)} (-{len(align_f)})')
print(f'  PF     : {pf(main.net_pnl):.3f} → {pf(only_align.net_pnl):.3f}  (Δ {pf(only_align.net_pnl)-pf(main.net_pnl):+.3f})')
print(f'  pnl    : ${total_pnl:,.0f} → ${only_align.net_pnl.sum():,.0f}  (Δ ${only_align.net_pnl.sum()-total_pnl:,.0f})')
print(f'  → 만약 align=False pnl 이 양수면 hard gate 제거가 좋음')
print(f'  → 만약 align=False pnl 이 음수면 hard gate 유지가 좋음')

print('\n' + '='*100)
print('[B] v3 의 모든 entered trade 가 align=True 이므로, hard gate 제거 시 효과 직접 추정 불가')
print('='*100)
print('  v3 는 H1 CHoCH trend + hard gate 로 100% align trade 만 진입.')
print('  Hard gate 제거하면 trend 반대인 trade 도 진입 가능.')
print('  새 trade 의 PF 는 알 수 없음 (시뮬 안 해봤음).')
print()
print('  하지만 다음 가설은 합리적:')
print('  - 반대 trend 진입 trade 는 일반적으로 PF < 1 (역추세 거래)')
print('  - SMC 시스템은 trend 추종형 → 역추세는 알파 약함')
print('  - 추가 trade 의 PF 가 1.0 이하라면 전체 PF 떨어짐')
print('  - 단, 추가 trade 가 작은 risk (a_trend_align=F → tier 강등) 로 들어가서 영향 작을 수도')
