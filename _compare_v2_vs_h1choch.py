"""
v2 (overfit fix) vs h1choch 비교
  - 시나리오별 PF/Return/MDD
  - OOS PF decay 가 줄었는지 (overfit 완화 검증)
  - ALPHA_MED SHORT 부수 효과
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
from pathlib import Path

P_H = Path('D:/smc_bot/stage4l_redist_outputs_h1choch_20260513')
P_V = Path('D:/smc_bot/stage4l_redist_outputs_v2_overfit_fix')

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return g/max(l,1e-9)

# ─────────────────────────────────────────────────────────
# A. 시나리오별 비교
# ─────────────────────────────────────────────────────────
print('='*100)
print('[A] 시나리오 비교: h1choch vs v2 (overfit fix)')
print('='*100)
ch = pd.read_csv(P_H / 'stage4l_comparison_summary.csv')
v2 = pd.read_csv(P_V / 'stage4l_comparison_summary.csv')

print(f'{"scenario":<10}{"ver":<10}{"trades":>8}{"win%":>7}{"PF":>8}{"MDD%":>8}{"Return%":>10}{"retire":>10}{"final$":>14}')
for sc in ['BOOST15','BOOST25','BOOST35']:
    for label, df in [('h1choch', ch), ('v2', v2)]:
        r = df[df.scenario==sc].iloc[0]
        print(f'{sc:<10}{label:<10}{int(r.trades):>8d}{r["win%"]:>7.2f}{r.PF:>8.3f}{r["MDD%"]:>8.2f}{r["Return_%"]:>10.0f}{r.retirement:>10}${r.total_assets_end:>13,.0f}')
    rh = ch[ch.scenario==sc].iloc[0]; rv = v2[v2.scenario==sc].iloc[0]
    pf_d = (rv.PF - rh.PF) / rh.PF * 100
    ret_d = (rv['Return_%'] - rh['Return_%']) / rh['Return_%'] * 100
    print(f'{"":<10}{"Δ":<10}{"":<8}{"":<7}{pf_d:>+7.1f}%{"":>8}{ret_d:>+9.1f}%')
    print()

# ─────────────────────────────────────────────────────────
# B. OOS 검증 (BOOST25 기준) — overfit 감쇠
# ─────────────────────────────────────────────────────────
print('='*100)
print('[B] OOS 검증 (BOOST25): IS PF / OOS PF decay 가 v2 에서 줄었는가?')
print('='*100)
CUTOFF = '2025-01-01'
def oos_split(path):
    d = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
    d['entry_time'] = pd.to_datetime(d['entry_time'], utc=True)
    return d[d.entry_time < CUTOFF], d[d.entry_time >= CUTOFF]

is_h, oos_h = oos_split(P_H)
is_v, oos_v = oos_split(P_V)

def metrics(d): return (len(d), pf(d.net_pnl) if len(d) else 0, d.net_pnl.sum() if len(d) else 0)

n_is_h, pf_is_h, pnl_is_h = metrics(is_h); n_oos_h, pf_oos_h, pnl_oos_h = metrics(oos_h)
n_is_v, pf_is_v, pnl_is_v = metrics(is_v); n_oos_v, pf_oos_v, pnl_oos_v = metrics(oos_v)

dec_h = (pf_oos_h - pf_is_h) / pf_is_h * 100
dec_v = (pf_oos_v - pf_is_v) / pf_is_v * 100

print(f'{"":<12}{"n_IS":>7}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}{"OOS_pnl":>14}')
print(f'{"h1choch":<12}{n_is_h:>7d}{pf_is_h:>9.3f}{n_oos_h:>7d}{pf_oos_h:>9.3f}{dec_h:>9.1f}%${pnl_oos_h:>13,.0f}')
print(f'{"v2 fix":<12}{n_is_v:>7d}{pf_is_v:>9.3f}{n_oos_v:>7d}{pf_oos_v:>9.3f}{dec_v:>9.1f}%${pnl_oos_v:>13,.0f}')

print()
if abs(dec_v) < abs(dec_h):
    print(f'  ✓ overfit 완화: decay {dec_h:.1f}% → {dec_v:.1f}% ({abs(dec_h)-abs(dec_v):.1f}%p 개선)')
else:
    print(f'  ✗ overfit 개선 없음: decay {dec_h:.1f}% → {dec_v:.1f}%')
print(f'  OOS PF: {pf_oos_h:.3f} → {pf_oos_v:.3f}  ({(pf_oos_v-pf_oos_h)/pf_oos_h*100:+.1f}%)')

# ─────────────────────────────────────────────────────────
# C. ALPHA_MED SHORT 부수 효과
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[C] ALPHA_MED SHORT 변화 (h1choch 에서 PF 0.80 으로 망가졌던 부분)')
print('='*100)
def amed_short(path):
    d = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
    return d[(d.tier=='ALPHA_MED') & (d.side=='short')]

ams_h = amed_short(P_H); ams_v = amed_short(P_V)
print(f'{"":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for label, d in [('h1choch', ams_h), ('v2', ams_v)]:
    if len(d):
        w = (d.net_pnl>0).mean()*100
        print(f'{label:<12}{len(d):>5d}{w:>8.1f}{pf(d.net_pnl):>8.3f}${d.net_pnl.sum():>13,.0f}${d.net_pnl.mean():>9,.0f}')

# ─────────────────────────────────────────────────────────
# D. CUT_ShortStable_L (DISABLED 후 그 패턴 거래의 실제 결과)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[D] CUT_ShortStable_L 패턴 — DISABLED 후 (1.0× 적용)')
print('='*100)
d_h = pd.read_csv(P_H / 'stage4l_boost25_out_skip_trades.csv')
d_v = pd.read_csv(P_V / 'stage4l_boost25_out_skip_trades.csv')
csl_h = d_h[d_h.sentiment_label=='CUT_ShortStable_L']
csl_v = d_v[d_v.sentiment_label=='CUT_ShortStable_L_DISABLED']
print(f'{"version":<25}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for label, d in [('h1choch (CUT 0.5×)', csl_h), ('v2 (DISABLED 1.0×)', csl_v)]:
    if len(d):
        w = (d.net_pnl>0).mean()*100
        print(f'{label:<25}{len(d):>5d}{w:>8.1f}{pf(d.net_pnl):>8.3f}${d.net_pnl.sum():>13,.0f}${d.net_pnl.mean():>9,.0f}')

# ─────────────────────────────────────────────────────────
# E. strong_T2aligned_h1comp_short 패턴 — 1.5 → 1.0 효과
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[E] strong_T2aligned_h1comp_short 패턴 (D1=H4=down + H1=comp + SHORT) — 1.5→1.0 효과')
print('='*100)
def t2_pat(d):
    return d[(d.d1_wave_state=='impulse_down') & (d.h4_wave_state=='impulse_down') & (d.h1_wave_state=='compression') & (d.side=='short')]

t2_h = t2_pat(d_h); t2_v = t2_pat(d_v)
print(f'{"version":<12}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for label, d in [('h1choch', t2_h), ('v2', t2_v)]:
    if len(d):
        w = (d.net_pnl>0).mean()*100
        print(f'{label:<12}{len(d):>5d}{w:>8.1f}{pf(d.net_pnl):>8.3f}${d.net_pnl.sum():>13,.0f}${d.net_pnl.mean():>9,.0f}')

# ─────────────────────────────────────────────────────────
# F. Tier 별 OOS PF — 각 tier 의 overfit 정도 비교
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[F] Tier 별 OOS PF (h1choch vs v2)')
print('='*100)
print(f'{"tier":<18}{"v_h_OOS":>10}{"v_v_OOS":>10}{"diff":>10}')
for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
    th = oos_h[oos_h.tier==tier]; tv = oos_v[oos_v.tier==tier]
    pf_h = pf(th.net_pnl) if len(th) else 0
    pf_v = pf(tv.net_pnl) if len(tv) else 0
    diff = pf_v - pf_h
    print(f'{tier:<18}{pf_h:>10.3f}{pf_v:>10.3f}{diff:>+10.3f}')

# ─────────────────────────────────────────────────────────
# G. 최종 verdict
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[VERDICT]')
print('='*100)
print(f'• v2 BOOST25 PF: {ch[ch.scenario=="BOOST25"]["PF"].iloc[0]:.3f} → {v2[v2.scenario=="BOOST25"]["PF"].iloc[0]:.3f}')
print(f'• v2 BOOST25 Return: {ch[ch.scenario=="BOOST25"]["Return_%"].iloc[0]:.0f}% → {v2[v2.scenario=="BOOST25"]["Return_%"].iloc[0]:.0f}%')
print(f'• OOS PF decay: {dec_h:.1f}% → {dec_v:.1f}%')
print(f'• ALPHA_MED SHORT PF: {pf(ams_h.net_pnl):.3f} → {pf(ams_v.net_pnl):.3f}')
