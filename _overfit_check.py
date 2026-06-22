"""
과최적화 진단:
  IS  (In-Sample) : 2023-06 ~ 2024-12  (코드의 룰들이 만들어진 시기 가정)
  OOS (Out-of-Sample): 2025-01 ~ 2026-04  (룰 만든 후 새로 들어온 데이터)

진짜 알파라면 IS와 OOS의 PF가 비슷해야 한다.
PATTERN_MULTS 의 각 패턴이 OOS에서도 똑같이 작동하는지 직접 검증.
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
import numpy as np
from pathlib import Path

PATH = Path('D:/smc_bot/stage4l_redist_outputs_h1choch_20260513')
SCEN = 'boost25'
CUTOFF = '2025-01-01'

df = pd.read_csv(PATH / f'stage4l_{SCEN}_out_skip_trades.csv')
df['entry_time'] = pd.to_datetime(df['entry_time'], utc=True)
IS  = df[df.entry_time <  CUTOFF].copy()
OOS = df[df.entry_time >= CUTOFF].copy()

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return g/max(l,1e-9)

def stats(d):
    if len(d)==0: return (0, 0.0, 0.0, 0.0)
    return (len(d), (d['net_pnl']>0).mean()*100, pf(d['net_pnl']), d['net_pnl'].sum())

def fmt_row(label, d):
    n, w, p, pnl = stats(d)
    return f'  {label:<28} n={n:>4d}  Win={w:5.1f}%  PF={p:6.3f}  pnl=${pnl:>12,.0f}'

print('='*100)
print(f'[OVERFIT TEST] split at {CUTOFF}')
print(f'  IS  (2023-06 ~ 2024-12): n={len(IS):>4d}')
print(f'  OOS (2025-01 ~ 2026-04): n={len(OOS):>4d}')
print('='*100)

# ─────────────────────────────────────────────────────────
# A. 전체 시스템: IS vs OOS
# ─────────────────────────────────────────────────────────
print('\n[A] 전체 시스템 — IS vs OOS')
print(fmt_row('IS', IS))
print(fmt_row('OOS', OOS))
is_pf = pf(IS.net_pnl); oos_pf = pf(OOS.net_pnl)
decay = (oos_pf - is_pf) / is_pf * 100
print(f'\n  PF decay: {is_pf:.3f} -> {oos_pf:.3f}  ({decay:+.1f}%)')
print(f'  → 진단: ', end='')
if decay < -30: print(f'⚠⚠⚠ 심각한 과최적화 의심 ({decay:.0f}%)')
elif decay < -15: print(f'⚠ 과최적화 의심 ({decay:.0f}%)')
elif decay < 0: print(f'⚠ 약한 알파 감쇠 ({decay:.0f}%)')
else: print(f'✓ OOS에서 오히려 개선 — 강건한 알파 ({decay:+.0f}%)')

# ─────────────────────────────────────────────────────────
# B. Tier별 IS vs OOS
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[B] Tier 별 IS vs OOS')
print('='*100)
print(f'{"tier":<18}{"n_IS":>6}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}{"status":>10}')
for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
    is_t = IS[IS.tier==tier]; oos_t = OOS[OOS.tier==tier]
    n_is, _, pf_is, _ = stats(is_t); n_oos, _, pf_oos, _ = stats(oos_t)
    if n_is==0 or n_oos==0:
        print(f'{tier:<18}{n_is:>6d}{pf_is:>9.3f}{n_oos:>7d}{pf_oos:>9.3f}{"":>10}{"":>10}')
        continue
    d = (pf_oos - pf_is) / max(pf_is, 0.01) * 100
    sym = '⚠⚠' if d < -30 else ('⚠' if d < -15 else ('~' if d < 0 else '✓'))
    print(f'{tier:<18}{n_is:>6d}{pf_is:>9.3f}{n_oos:>7d}{pf_oos:>9.3f}{d:>9.0f}%{sym:>10}')

# ─────────────────────────────────────────────────────────
# C. PATTERN_MULTS — 룰별 IS vs OOS (코드의 wave_pattern_mult 컬럼 활용)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[C] PATTERN_MULTS — wave 패턴 룰의 IS vs OOS 안정성')
print('='*100)
print('  코드 정의된 mult 패턴이 OOS 에서도 같은 효과를 내는가?')

# wave_pattern_mult 의 bucket
def bucket(x):
    if pd.isna(x) or abs(x-1.0) < 0.01: return '1.0× (no rule)'
    if x < 0.4: return '<0.4× (weak T2 등 강력 cut)'
    if x < 0.8: return '0.4-0.8× (weak)'
    if x < 1.1: return '~1.0×'
    if x < 1.5: return '1.0-1.5× (strong)'
    return '≥1.5× (T2aligned 등 super-strong)'

if 'wave_pattern_mult' in df.columns:
    IS['_b'] = IS['wave_pattern_mult'].apply(bucket)
    OOS['_b'] = OOS['wave_pattern_mult'].apply(bucket)
    print(f'\n{"bucket":<38}{"n_IS":>6}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}')
    order = ['<0.4× (weak T2 등 강력 cut)','0.4-0.8× (weak)','~1.0×','1.0× (no rule)','1.0-1.5× (strong)','≥1.5× (T2aligned 등 super-strong)']
    for b in order:
        is_b = IS[IS._b==b]; oos_b = OOS[OOS._b==b]
        n_is, _, pf_is, _ = stats(is_b); n_oos, _, pf_oos, _ = stats(oos_b)
        if n_is==0 and n_oos==0: continue
        d_str = f'{(pf_oos-pf_is)/max(pf_is,0.01)*100:+.0f}%' if (n_is>0 and n_oos>0) else ''
        print(f'{b:<38}{n_is:>6d}{pf_is:>9.3f}{n_oos:>7d}{pf_oos:>9.3f}{d_str:>10}')
    print('  → weak 패턴 (< 1.0×): IS 에서 PF 낮아야 정의에 부합 / OOS 에서도 그래야 진짜 약점')
    print('  → strong 패턴 (≥ 1.0×): IS 에서 PF 높아야 정의에 부합 / OOS 에서도 그래야 진짜 강점')

# ─────────────────────────────────────────────────────────
# D. WEAK_SETUPS_SET 의 21개 조합 — IS vs OOS 별도 검증
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[D] WEAK_SETUPS_SET — 21개 (d1, h4, h1, side) 조합의 OOS 검증')
print('='*100)
print('  코드는 이 조합들을 PF<1.87 "약점" 으로 분류해 risk × 0.2 로 처벌함')
print('  OOS 에서도 PF<1.87 이어야 정당화됨')
WEAK_SETUPS_SET = [
    ("impulse_up","impulse_down","impulse_up","short",0.29),
    ("compression","compression","compression","short",0.31),
    ("impulse_down","impulse_down","expansion","short",0.35),
    ("impulse_down","impulse_down","impulse_down","short",0.38),
    ("expansion","impulse_up","impulse_down","long",0.44),
    ("impulse_up","compression","impulse_down","long",0.45),
    ("impulse_up","impulse_up","expansion","short",0.50),
    ("expansion","impulse_up","compression","long",0.53),
    ("impulse_up","expansion","compression","short",0.59),
    ("compression","impulse_up","impulse_down","long",0.63),
    ("expansion","impulse_up","impulse_up","long",0.63),
    ("compression","impulse_down","expansion","short",0.64),
    ("impulse_down","impulse_down","expansion","long",0.67),
    ("impulse_up","compression","expansion","long",0.73),
    ("impulse_down","expansion","impulse_up","short",0.95),
    ("impulse_down","compression","impulse_up","short",1.16),
    ("impulse_down","impulse_down","impulse_up","long",1.18),
    ("compression","compression","impulse_up","long",1.23),
    ("impulse_up","expansion","impulse_down","long",1.24),
    ("impulse_up","impulse_up","impulse_up","long",1.63),
    ("impulse_down","impulse_up","compression","long",1.73),
]
print(f'\n{"d1":<14}{"h4":<14}{"h1":<14}{"side":<7}{"PF_orig":>8}{"n_IS":>6}{"PF_IS":>8}{"n_OOS":>7}{"PF_OOS":>8}{"verdict":>22}')
flips_oos = 0; total_with_oos = 0
for d1ws, h4ws, h1ws, side, pf_orig in WEAK_SETUPS_SET:
    is_m = IS[(IS.d1_wave_state==d1ws)&(IS.h4_wave_state==h4ws)&(IS.h1_wave_state==h1ws)&(IS.side==side)]
    oos_m = OOS[(OOS.d1_wave_state==d1ws)&(OOS.h4_wave_state==h4ws)&(OOS.h1_wave_state==h1ws)&(OOS.side==side)]
    n_is = len(is_m); n_oos = len(oos_m)
    pf_is = pf(is_m.net_pnl) if n_is else 0
    pf_oos = pf(oos_m.net_pnl) if n_oos else 0
    if n_oos > 0:
        total_with_oos += 1
        if pf_oos > 1.87:
            verdict = '✗ FLIP (OOS PF>1.87)'
            flips_oos += 1
        else:
            verdict = '✓ stays weak'
    else:
        verdict = 'no OOS sample'
    print(f'{d1ws:<14}{h4ws:<14}{h1ws:<14}{side:<7}{pf_orig:>8.2f}{n_is:>6d}{pf_is:>8.3f}{n_oos:>7d}{pf_oos:>8.3f}{verdict:>22}')

if total_with_oos > 0:
    print(f'\n  → OOS 에서 약점 유지: {total_with_oos-flips_oos}/{total_with_oos}  ({(total_with_oos-flips_oos)/total_with_oos*100:.0f}%)')
    print(f'  → "약점이 더 이상 약점이 아님" 비율: {flips_oos}/{total_with_oos}  ({flips_oos/total_with_oos*100:.0f}%)')
    if flips_oos/total_with_oos > 0.4:
        print(f'  ⚠⚠ 절반 가까이 OOS 에서 강점으로 뒤집힘 → WEAK_SETUPS_SET 은 과최적화')

# ─────────────────────────────────────────────────────────
# E. Sentiment 패턴 — 주석에 명시된 PF 와 OOS PF
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[E] Sentiment 패턴 — 코드 주석 PF (전기간) vs OOS PF')
print('='*100)
SENT_ORIG = {
    'BOOST_TopReversal': 15.51,    # n=17
    'BOOST_BottomReversal': 7.31,  # n=24
    'BOOST_TrendStart_L': 8.77,    # n=12
    'BOOST_TrendStart_S': 5.22,    # n=18
    'CUT_NeutStable_S': 0.35,      # n=9
    'CUT_NeutFalling_S': 0.74,     # n=15
    'CUT_ShortStable_L': 0.47,     # n=9
}
print(f'\n{"sentiment":<25}{"orig_PF":>9}{"orig_n":>8}{"n_IS":>6}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}')
ORIG_N = {'BOOST_TopReversal':17,'BOOST_BottomReversal':24,'BOOST_TrendStart_L':12,'BOOST_TrendStart_S':18,'CUT_NeutStable_S':9,'CUT_NeutFalling_S':15,'CUT_ShortStable_L':9}
if 'sentiment_label' in df.columns:
    for s, orig_pf in SENT_ORIG.items():
        is_s = IS[IS.sentiment_label==s]; oos_s = OOS[OOS.sentiment_label==s]
        n_is = len(is_s); n_oos = len(oos_s)
        pf_is = pf(is_s.net_pnl) if n_is else 0
        pf_oos = pf(oos_s.net_pnl) if n_oos else 0
        d = ''
        if n_is>0 and n_oos>0:
            d = f'{(pf_oos-pf_is)/max(pf_is,0.01)*100:+.0f}%'
        print(f'{s:<25}{orig_pf:>9.2f}{ORIG_N[s]:>8d}{n_is:>6d}{pf_is:>9.3f}{n_oos:>7d}{pf_oos:>9.3f}{d:>10}')

# ─────────────────────────────────────────────────────────
# F. 샘플 크기 적신호
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[F] 샘플 크기 적신호 — 코드에 등장하는 n 값 vs 실제 데이터')
print('='*100)
print('  과최적화 신호: n < 30 인 패턴에 강한 가중치 부여')
print('  - strong_T2aligned_h1comp_short: n=16, PF 20.01, mult 1.5×  ⚠ n 너무 작음')
print('  - BOOST_TrendStart_L: n=12, mult 2.5×  ⚠')
print('  - CUT_ShortStable_L:  n=9,  mult 0.5×  ⚠⚠ 단일 샘플에 좌우')
print('  - CUT_NeutStable_S:   n=9,  mult 0.5×  ⚠⚠')
# 실제 검증
print('\n  강력 패턴 strong_T2aligned_h1comp_short 의 OOS 검증:')
mask_t2 = (df.d1_wave_state=='impulse_down') & (df.h4_wave_state=='impulse_down') & (df.h1_wave_state=='compression') & (df.side=='short')
is_t2 = IS[(IS.d1_wave_state=='impulse_down')&(IS.h4_wave_state=='impulse_down')&(IS.h1_wave_state=='compression')&(IS.side=='short')]
oos_t2 = OOS[(OOS.d1_wave_state=='impulse_down')&(OOS.h4_wave_state=='impulse_down')&(OOS.h1_wave_state=='compression')&(OOS.side=='short')]
print(fmt_row('IS', is_t2))
print(fmt_row('OOS', oos_t2))
if len(oos_t2) > 0 and pf(oos_t2.net_pnl) < 2:
    print('  ⚠⚠ OOS 에서 PF 폭락 — 코드 주석 "PF 20" 은 우연')

# ─────────────────────────────────────────────────────────
# G. 분기별 PF 안정성
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[G] 분기별 PF — 시간에 따른 일관성 (강건한 알파면 PF 가 안정적)')
print('='*100)
df['_q'] = df['entry_time'].dt.to_period('Q')
print(f'{"quarter":<12}{"trades":>8}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
for q, sub in df.groupby('_q'):
    n = len(sub)
    w = (sub['net_pnl']>0).mean()*100
    p = pf(sub['net_pnl'])
    s = sub['net_pnl'].sum()
    avg = sub['net_pnl'].mean()
    flag = ''
    if p < 1.5: flag = '  ←약'
    if p > 6: flag = '  ←폭발 (의심)'
    print(f'{str(q):<12}{n:>8d}{w:>8.1f}{p:>8.2f}${s:>13,.0f}${avg:>9,.0f}{flag}')

print('\n' + '='*100)
print('[요약]')
print('='*100)
print(f'  • IS PF: {is_pf:.3f} → OOS PF: {oos_pf:.3f}  ({decay:+.1f}%)')
print(f'  • WEAK_SETUPS 신뢰성: {(total_with_oos-flips_oos)}/{total_with_oos} 패턴 OOS 에서도 유지')
print(f'  • 결론은 위 [A]~[G] 종합으로 판단')
