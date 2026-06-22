import pandas as pd
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

d = pd.read_csv('D:/smc_bot/stage4l_redist_outputs_h1choch_20260513/stage4l_boost25_out_skip_trades.csv')
d['entry_time'] = pd.to_datetime(d['entry_time'], utc=True)

am = d[(d.tier=='ALPHA_MED') & (d.side=='short')].copy()
def pf(s):
    g=s[s>0].sum(); l=abs(s[s<0].sum()); return g/max(l,1e-9)

print('='*80)
print('ALPHA_MED SHORT — 분기별 (h1choch BOOST25)')
print('='*80)
am['_q'] = am['entry_time'].dt.to_period('Q')
print(f'{"quarter":<10}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for q, sub in am.groupby('_q'):
    if len(sub)==0: continue
    w=(sub.net_pnl>0).mean()*100
    print(f'{str(q):<10}{len(sub):>5d}{w:>8.1f}{pf(sub.net_pnl):>8.2f}${sub.net_pnl.sum():>13,.0f}${sub.net_pnl.mean():>9,.0f}')

print('\n[ IS (~2024-12) vs OOS (2025+) ]')
is_ = am[am.entry_time < '2025-01-01']; oos = am[am.entry_time >= '2025-01-01']
for label, x in [('IS', is_), ('OOS', oos)]:
    if len(x)==0: continue
    w=(x.net_pnl>0).mean()*100
    print(f'  {label:<5}: n={len(x):>3d}  Win={w:5.1f}%  PF={pf(x.net_pnl):.3f}  pnl=${x.net_pnl.sum():>12,.0f}')

print('\n[ exit_reason 별 (전체) ]')
print(am.groupby('exit_reason').agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pf=('net_pnl', pf), pnl=('net_pnl','sum')).round(2).to_string())

print('\n[ exit_reason 별 (OOS만) ]')
print(oos.groupby('exit_reason').agg(n=('net_pnl','count'), win=('net_pnl', lambda x:(x>0).mean()*100), pf=('net_pnl', pf), pnl=('net_pnl','sum')).round(2).to_string())

# 만약 risk 축소 0.3 했다면 가상 효과
print('\n[ 가상 시뮬: ALPHA_MED SHORT risk × 0.3 적용했다면? ]')
for label, x in [('IS', is_), ('OOS', oos)]:
    if len(x)==0: continue
    sim_pnl = x.net_pnl * 0.3  # 단순 비례 (수수료 무시)
    print(f'  {label:<5}: pnl ${x.net_pnl.sum():>12,.0f} → ${sim_pnl.sum():>12,.0f}  (감소 ${x.net_pnl.sum()-sim_pnl.sum():>10,.0f})')

print('\n[ 가상 시뮬: ALPHA_MED SHORT 진입 차단 했다면? ]')
print(f'  전체 pnl 회복: +${-am.net_pnl.sum():>10,.0f}')
print(f'  OOS pnl 회복: +${-oos.net_pnl.sum():>10,.0f}')
