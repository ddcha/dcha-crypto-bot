"""
v3 (conservative) vs h1choch vs v2 — 4-way 비교
  - 시나리오별 PF/Return/MDD
  - OOS PF decay 추이
  - ALPHA_MED SHORT 개선 효과 (핵심)
  - CUT_ShortStable_L / T2 패턴별 효과 검증
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
from pathlib import Path

PATHS = {
    'h1choch': Path('D:/smc_bot/stage4l_redist_outputs_h1choch_20260513'),
    'v2'    : Path('D:/smc_bot/stage4l_redist_outputs_v2_overfit_fix'),
    'v3'    : Path('D:/smc_bot/stage4l_redist_outputs_v3_conservative'),
}
CUTOFF = '2025-01-01'

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return g/max(l,1e-9)

# ─────────────────────────────────────────────────────────
# A. 시나리오 비교 (3-way)
# ─────────────────────────────────────────────────────────
print('='*110)
print('[A] 시나리오 비교 — h1choch / v2 / v3')
print('='*110)
summaries = {ver: pd.read_csv(p / 'stage4l_comparison_summary.csv') for ver, p in PATHS.items()}

print(f'{"scenario":<10}{"ver":<10}{"trades":>8}{"win%":>7}{"PF":>8}{"MDD%":>8}{"Return%":>10}{"retire":>10}{"final$":>14}')
for sc in ['BOOST15','BOOST25','BOOST35']:
    base_pf = None
    for ver in ['h1choch','v2','v3']:
        df = summaries[ver]
        r = df[df.scenario==sc].iloc[0]
        marker = ''
        if base_pf is None:
            base_pf = r.PF
        else:
            d = (r.PF - base_pf)/base_pf*100
            marker = f'  ({d:+.1f}% vs h1choch)'
        print(f'{sc:<10}{ver:<10}{int(r.trades):>8d}{r["win%"]:>7.2f}{r.PF:>8.3f}{r["MDD%"]:>8.2f}{r["Return_%"]:>10.0f}{r.retirement:>10}${r.total_assets_end:>13,.0f}{marker}')
    print()

# ─────────────────────────────────────────────────────────
# B. OOS PF decay (BOOST25)
# ─────────────────────────────────────────────────────────
print('='*110)
print('[B] OOS decay 추이 (BOOST25): IS PF / OOS PF')
print('='*110)
def split(path):
    d = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
    d['entry_time'] = pd.to_datetime(d['entry_time'], utc=True)
    return d[d.entry_time<CUTOFF], d[d.entry_time>=CUTOFF]

print(f'{"version":<12}{"n_IS":>7}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}{"OOS_pnl":>16}{"OOS_avg":>10}')
results = {}
for ver, p in PATHS.items():
    is_, oos = split(p)
    pf_is = pf(is_.net_pnl); pf_oos = pf(oos.net_pnl)
    decay = (pf_oos - pf_is)/pf_is*100
    avg = oos.net_pnl.mean()
    print(f'{ver:<12}{len(is_):>7d}{pf_is:>9.3f}{len(oos):>7d}{pf_oos:>9.3f}{decay:>9.1f}%${oos.net_pnl.sum():>15,.0f}${avg:>9,.0f}')
    results[ver] = (pf_is, pf_oos, decay)

print('\n  decay 추이:')
print(f'    h1choch: {results["h1choch"][2]:.1f}%  (baseline)')
print(f'    v2     : {results["v2"][2]:.1f}%  ({results["v2"][2]-results["h1choch"][2]:+.1f}%p)')
print(f'    v3     : {results["v3"][2]:.1f}%  ({results["v3"][2]-results["h1choch"][2]:+.1f}%p)')

# ─────────────────────────────────────────────────────────
# C. ALPHA_MED SHORT — v3 패치 효과
# ─────────────────────────────────────────────────────────
print('\n' + '='*110)
print('[C] ALPHA_MED SHORT — v3 핵심 패치 (risk × 0.3) 효과')
print('='*110)
def amed_short(path):
    d = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
    d['entry_time'] = pd.to_datetime(d['entry_time'], utc=True)
    return d[(d.tier=='ALPHA_MED') & (d.side=='short')]

print(f'{"":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for ver, p in PATHS.items():
    a = amed_short(p)
    if len(a):
        w = (a.net_pnl>0).mean()*100
        print(f'{ver:<12}{len(a):>5d}{w:>8.1f}{pf(a.net_pnl):>8.3f}${a.net_pnl.sum():>13,.0f}${a.net_pnl.mean():>9,.0f}')

print('\n  IS/OOS 분리 (v3):')
a_v3 = amed_short(PATHS['v3'])
for label, d in [('IS', a_v3[a_v3.entry_time<CUTOFF]), ('OOS', a_v3[a_v3.entry_time>=CUTOFF])]:
    if len(d):
        w = (d.net_pnl>0).mean()*100
        print(f'    {label}: n={len(d):>3d}  Win={w:5.1f}%  PF={pf(d.net_pnl):.3f}  pnl=${d.net_pnl.sum():>10,.0f}')

# ─────────────────────────────────────────────────────────
# D. ALPHA_MED LONG — 같이 안 망가졌는지 sanity check
# ─────────────────────────────────────────────────────────
print('\n' + '='*110)
print('[D] ALPHA_MED LONG — 패치 부작용 없는지 확인 (변화 없어야 정상)')
print('='*110)
def amed_long(path):
    d = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
    return d[(d.tier=='ALPHA_MED') & (d.side=='long')]

print(f'{"":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for ver, p in PATHS.items():
    a = amed_long(p)
    if len(a):
        w = (a.net_pnl>0).mean()*100
        print(f'{ver:<12}{len(a):>5d}{w:>8.1f}{pf(a.net_pnl):>8.3f}${a.net_pnl.sum():>13,.0f}${a.net_pnl.mean():>9,.0f}')

# ─────────────────────────────────────────────────────────
# E. 패턴별 검증 — CUT_ShortStable_L / T2
# ─────────────────────────────────────────────────────────
print('\n' + '='*110)
print('[E] 패치 패턴별 직접 검증')
print('='*110)
print('\n[E1] CUT_ShortStable_L (h1choch=cut 0.5×, v2/v3=DISABLED)')
print(f'{"":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}')
for ver, p in PATHS.items():
    d = pd.read_csv(p / 'stage4l_boost25_out_skip_trades.csv')
    label_match = 'CUT_ShortStable_L_DISABLED' if ver != 'h1choch' else 'CUT_ShortStable_L'
    sub = d[d.sentiment_label==label_match]
    if len(sub):
        w = (sub.net_pnl>0).mean()*100
        print(f'{ver:<12}{len(sub):>5d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

print('\n[E2] strong_T2aligned_h1comp_short (h1choch=1.5, v2=1.0, v3=1.5 복원)')
print(f'{"":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}')
for ver, p in PATHS.items():
    d = pd.read_csv(p / 'stage4l_boost25_out_skip_trades.csv')
    sub = d[(d.d1_wave_state=='impulse_down') & (d.h4_wave_state=='impulse_down') & (d.h1_wave_state=='compression') & (d.side=='short')]
    if len(sub):
        w = (sub.net_pnl>0).mean()*100
        print(f'{ver:<12}{len(sub):>5d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

# ─────────────────────────────────────────────────────────
# F. Tier 별 OOS PF — 모든 tier 확인
# ─────────────────────────────────────────────────────────
print('\n' + '='*110)
print('[F] Tier 별 OOS PF — h1choch / v2 / v3')
print('='*110)
oos_dict = {ver: split(p)[1] for ver, p in PATHS.items()}
print(f'{"tier":<18}{"h1ch_OOS":>10}{"v2_OOS":>10}{"v3_OOS":>10}{"v3-v_h":>12}')
for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
    pfs = {}
    for ver in ['h1choch','v2','v3']:
        sub = oos_dict[ver][oos_dict[ver].tier==tier]
        pfs[ver] = pf(sub.net_pnl) if len(sub) else 0
    diff = pfs['v3'] - pfs['h1choch']
    print(f'{tier:<18}{pfs["h1choch"]:>10.3f}{pfs["v2"]:>10.3f}{pfs["v3"]:>10.3f}{diff:>+12.3f}')

# ─────────────────────────────────────────────────────────
# G. 전체 평가
# ─────────────────────────────────────────────────────────
print('\n' + '='*110)
print('[G] 종합 평가 (BOOST25 기준)')
print('='*110)
b25 = {ver: summaries[ver][summaries[ver].scenario=='BOOST25'].iloc[0] for ver in ['h1choch','v2','v3']}
print(f'{"metric":<22}{"h1choch":>14}{"v2":>14}{"v3":>14}{"v3 vs h1ch":>14}')
for metric, fmt in [('PF', '.3f'), ('win%', '.2f'), ('MDD%', '.2f'), ('Return_%', '.0f'), ('total_assets_end', ',.0f')]:
    h = b25['h1choch'][metric]; v2v = b25['v2'][metric]; v3v = b25['v3'][metric]
    diff = (v3v - h) / h * 100 if h != 0 else 0
    print(f'{metric:<22}{format(h, fmt):>14}{format(v2v, fmt):>14}{format(v3v, fmt):>14}{diff:>+13.2f}%')

print(f'\n{"OOS_PF_BOOST25":<22}{results["h1choch"][1]:>14.3f}{results["v2"][1]:>14.3f}{results["v3"][1]:>14.3f}{(results["v3"][1]-results["h1choch"][1])/results["h1choch"][1]*100:>+13.2f}%')
print(f'{"OOS_decay":<22}{results["h1choch"][2]:>13.1f}%{results["v2"][2]:>13.1f}%{results["v3"][2]:>13.1f}%{results["v3"][2]-results["h1choch"][2]:>+13.1f}%p')
