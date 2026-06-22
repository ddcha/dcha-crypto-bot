import pandas as pd
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

m = pd.read_csv('D:/smc_bot/stage4l_redist_outputs_main_20260513/stage4l_boost25_out_skip_trades.csv')
h = pd.read_csv('D:/smc_bot/stage4l_redist_outputs_h1choch_20260513/stage4l_boost25_out_skip_trades.csv')

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return g/max(l,1e-9)

def stats(df, label):
    n = len(df)
    if n == 0: return f'  {label}: n=0'
    win = (df['net_pnl']>0).mean()*100
    pnl = df['net_pnl'].sum()
    avg = df['net_pnl'].mean()
    return f'  {label}: n={n:>4d}  Win={win:5.1f}%  PF={pf(df.net_pnl):5.2f}  pnl=${pnl:>12,.0f}  avg=${avg:>8,.0f}'

print('='*100)
print('ALPHA_MED — main vs h1choch (BOOST25)')
print('='*100)
for tag in ['LONG','SHORT','TOTAL']:
    print(f'\n[{tag}]')
    if tag == 'TOTAL':
        am = m[m.tier=='ALPHA_MED']; ah = h[h.tier=='ALPHA_MED']
    else:
        side = tag.lower()
        am = m[(m.tier=='ALPHA_MED') & (m.side==side)]
        ah = h[(h.tier=='ALPHA_MED') & (h.side==side)]
    print(stats(am, 'main   '))
    print(stats(ah, 'h1choch'))

print('\n' + '='*100)
print('ALPHA_MED h1choch — exit_reason 분포 (왜 지는지)')
print('='*100)
ah_med = h[h.tier=='ALPHA_MED']
am_med = m[m.tier=='ALPHA_MED']
print('\nmain ALPHA_MED:')
print(am_med.groupby('exit_reason').agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pnl=('net_pnl','sum')).round(2).to_string())
print('\nh1choch ALPHA_MED:')
print(ah_med.groupby('exit_reason').agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pnl=('net_pnl','sum')).round(2).to_string())

print('\n' + '='*100)
print('h1choch — wave_pattern_mult 효과 (ALPHA_MED only)')
print('='*100)
if 'wave_pattern_mult' in ah_med.columns:
    ah_med = ah_med.copy()
    ah_med['wp_bucket'] = pd.cut(ah_med['wave_pattern_mult'].fillna(1.0), bins=[0,0.4,0.8,1.1,1.5,3], labels=['<0.4','0.4-0.8','~1.0','1.0-1.5','>1.5'])
    print(ah_med.groupby('wp_bucket', observed=True).agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pf=('net_pnl', pf), pnl=('net_pnl','sum')).round(3).to_string())

print('\n' + '='*100)
print('h1choch — sentiment_label 별 ALPHA_MED 결과')
print('='*100)
if 'sentiment_label' in ah_med.columns:
    print(ah_med.groupby('sentiment_label').agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pf=('net_pnl', pf), pnl=('net_pnl','sum')).round(2).to_string())

print('\n' + '='*100)
print('전체 시스템에서 ALPHA_MED 제거 시 가상 수익 (단순 sum 차이 — 자본 효과 무시)')
print('='*100)
for ver, df in [('main', m), ('h1choch', h)]:
    total = df['net_pnl'].sum()
    med = df[df.tier=='ALPHA_MED']['net_pnl'].sum()
    no_med = total - med
    n_total = len(df); n_med = len(df[df.tier=='ALPHA_MED'])
    print(f'  {ver:>8}: total ${total:>14,.0f}  /  ALPHA_MED ${med:>10,.0f} ({n_med}t {n_med/n_total*100:.1f}%)  /  제거 시 ${no_med:>14,.0f} ({(no_med-total)/total*100:+.2f}%)')

print('\n  ⚠ 위 값은 ALPHA_MED 거래만 산술적으로 제거한 가상치 — 실제로는 자본 흐름/cooldown/risk_budget이 변해 결과가 달라질 수 있음')

print('\n' + '='*100)
print('ALPHA_MED LONG vs SHORT 별 제거 시뮬 (h1choch)')
print('='*100)
ah_long = h[(h.tier=='ALPHA_MED') & (h.side=='long')]
ah_short = h[(h.tier=='ALPHA_MED') & (h.side=='short')]
print(f'  LONG  pnl: ${ah_long.net_pnl.sum():>10,.0f}  PF {pf(ah_long.net_pnl):.2f}  n={len(ah_long)}')
print(f'  SHORT pnl: ${ah_short.net_pnl.sum():>10,.0f}  PF {pf(ah_short.net_pnl):.2f}  n={len(ah_short)}')
