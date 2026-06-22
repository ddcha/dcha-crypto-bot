"""
v3 conservative vs v3 no-hardgate 비교
  - hard gate 제거가 결과에 미친 영향
  - 추가된 trade (align=False) 분석
  - tier 분포 변화, PF/Return/MDD 변화
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path('D:/smc_bot')
PATHS = {
    'v3':           ROOT / 'stage4l_redist_outputs_v3_conservative',
    'v3_no_hardgate': ROOT / 'stage4l_redist_outputs_v3_no_hardgate',
}
CUTOFF = '2025-01-01'

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return float(g/max(l,1e-9))

# ─────────────────────────────────────────────────────────
# [A] 시나리오 비교
# ─────────────────────────────────────────────────────────
print('='*100)
print('[A] 시나리오 비교 — v3 conservative vs v3 no-hardgate')
print('='*100)

for sc in ['BOOST15','BOOST25','BOOST35']:
    print(f'\n● {sc}')
    print(f'  {"version":<20}{"trades":>8}{"win%":>7}{"PF":>8}{"MDD%":>8}{"Return%":>10}{"retire":>10}{"final$":>14}')
    base_pf = None
    for ver, path in PATHS.items():
        f = path / 'stage4l_comparison_summary.csv'
        if not f.exists():
            print(f'  {ver:<20}  (file 없음 — 백테스트 미완료?)')
            continue
        s = pd.read_csv(f)
        row = s[s.scenario==sc]
        if len(row)==0: continue
        r = row.iloc[0]
        diff = '' if base_pf is None else f' ({(r.PF-base_pf)/base_pf*100:+.1f}% PF)'
        if base_pf is None: base_pf = r.PF
        print(f'  {ver:<20}{int(r.trades):>8d}{r["win%"]:>7.2f}{r.PF:>8.3f}{r["MDD%"]:>8.2f}{r["Return_%"]:>10.0f}{r.retirement:>10}${r.total_assets_end:>13,.0f}{diff}')

# ─────────────────────────────────────────────────────────
# [B] 추가된 trade 분석 (BOOST25)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[B] 추가된 trade 분석 (BOOST25 기준)')
print('='*100)

t_v3 = pd.read_csv(PATHS['v3'] / 'stage4l_boost25_out_skip_trades.csv')
t_nh_f = PATHS['v3_no_hardgate'] / 'stage4l_boost25_out_skip_trades.csv'
if not t_nh_f.exists():
    print('no-hardgate trades.csv 없음 — 백테스트 완료 안 됨')
else:
    t_nh = pd.read_csv(t_nh_f)
    print(f'\nv3:             {len(t_v3)} trades, align=True {int(t_v3["a_trend_align"].sum())} ({t_v3["a_trend_align"].mean()*100:.1f}%)')
    print(f'v3 no_hardgate: {len(t_nh)} trades, align=True {int(t_nh["a_trend_align"].sum())} ({t_nh["a_trend_align"].mean()*100:.1f}%)')
    print(f'\n추가된 trade 수: +{len(t_nh) - len(t_v3)} ({(len(t_nh)-len(t_v3))/len(t_v3)*100:+.1f}%)')

    # align=False trade 분석 (no-hardgate에서만 가능)
    align_t = t_nh[t_nh['a_trend_align']==True]
    align_f = t_nh[t_nh['a_trend_align']==False]
    print(f'\nv3 no-hardgate trades 분류:')
    print(f'  {"category":<20}{"n":>6}{"win%":>8}{"PF":>8}{"pnl":>14}{"avg":>10}')
    for label, sub in [('align=True', align_t), ('align=False (NEW)', align_f)]:
        if len(sub)==0: continue
        w = (sub.net_pnl>0).mean()*100
        print(f'  {label:<20}{len(sub):>6d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}${sub.net_pnl.mean():>9,.0f}')

    # align=False 의 tier 분포
    if len(align_f) > 0:
        print(f'\n[B2] align=False (= hard gate가 차단했을 trade) 의 tier 분포:')
        print(f'  {"tier":<18}{"n":>6}{"win%":>8}{"PF":>8}{"pnl":>14}')
        for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
            sub = align_f[align_f.tier==tier]
            if len(sub)==0: continue
            w = (sub.net_pnl>0).mean()*100
            print(f'  {tier:<18}{len(sub):>6d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

        # side 별
        print(f'\n[B3] align=False 의 side 별:')
        print(f'  {"side":<10}{"n":>6}{"win%":>8}{"PF":>8}{"pnl":>14}')
        for s in ['long','short']:
            sub = align_f[align_f.side==s]
            if len(sub)==0: continue
            w = (sub.net_pnl>0).mean()*100
            print(f'  {s:<10}{len(sub):>6d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')

    # ─────────────────────────────────────────────────────────
    # [C] OOS 검증
    # ─────────────────────────────────────────────────────────
    print('\n' + '='*100)
    print('[C] OOS PF (2025-01 split)')
    print('='*100)
    print(f'  {"version":<20}{"n_IS":>7}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}')
    for ver, path in PATHS.items():
        t = pd.read_csv(path / 'stage4l_boost25_out_skip_trades.csv')
        t['entry_time'] = pd.to_datetime(t['entry_time'], utc=True)
        is_ = t[t.entry_time<CUTOFF]; oos = t[t.entry_time>=CUTOFF]
        pf_is = pf(is_.net_pnl); pf_oos = pf(oos.net_pnl)
        decay = (pf_oos-pf_is)/pf_is*100 if pf_is>0 else 0
        print(f'  {ver:<20}{len(is_):>7d}{pf_is:>9.3f}{len(oos):>7d}{pf_oos:>9.3f}{decay:>9.1f}%')

    # ─────────────────────────────────────────────────────────
    # [D] tier 별 PF 변화
    # ─────────────────────────────────────────────────────────
    print('\n' + '='*100)
    print('[D] Tier 별 PF/거래수 변화 (BOOST25)')
    print('='*100)
    print(f'  {"tier":<18}{"v3 n":>8}{"v3 PF":>10}{"NH n":>8}{"NH PF":>10}{"Δn":>8}{"ΔPF":>10}')
    for tier in ['ALPHA_MAX','ALPHA_HIGH','ALPHA_MED','SWEEP_GEM','SWEEP_ROOM_FVG','SWEEP_ROOM_ONLY']:
        v3_sub = t_v3[t_v3.tier==tier]
        nh_sub = t_nh[t_nh.tier==tier]
        v3_pf = pf(v3_sub.net_pnl) if len(v3_sub) else 0
        nh_pf = pf(nh_sub.net_pnl) if len(nh_sub) else 0
        print(f'  {tier:<18}{len(v3_sub):>8d}{v3_pf:>10.3f}{len(nh_sub):>8d}{nh_pf:>10.3f}{len(nh_sub)-len(v3_sub):>+8d}{nh_pf-v3_pf:>+10.3f}')

    # ─────────────────────────────────────────────────────────
    # [E] 최종 판정
    # ─────────────────────────────────────────────────────────
    print('\n' + '='*100)
    print('[E] 최종 판정')
    print('='*100)
    s_v3 = pd.read_csv(PATHS['v3'] / 'stage4l_comparison_summary.csv')
    s_nh = pd.read_csv(PATHS['v3_no_hardgate'] / 'stage4l_comparison_summary.csv')
    v3_b25 = s_v3[s_v3.scenario=='BOOST25'].iloc[0]
    nh_b25 = s_nh[s_nh.scenario=='BOOST25'].iloc[0]
    pf_diff_pct = (nh_b25.PF - v3_b25.PF) / v3_b25.PF * 100
    print(f'  BOOST25 PF       : {v3_b25.PF:.3f} → {nh_b25.PF:.3f}  ({pf_diff_pct:+.2f}%)')
    print(f'  BOOST25 Return%  : {v3_b25["Return_%"]:.0f} → {nh_b25["Return_%"]:.0f}  ({(nh_b25["Return_%"]-v3_b25["Return_%"])/v3_b25["Return_%"]*100:+.1f}%)')
    print(f'  BOOST25 MDD%     : {v3_b25["MDD%"]:.2f} → {nh_b25["MDD%"]:.2f}  ({nh_b25["MDD%"]-v3_b25["MDD%"]:+.2f}%p)')
    print(f'  BOOST25 trades   : {int(v3_b25.trades)} → {int(nh_b25.trades)}  ({int(nh_b25.trades)-int(v3_b25.trades):+d})')
    print()
    if pf_diff_pct > 3:
        print('  ✅ Hard gate 제거가 효과적 — 알파 추가됨')
    elif pf_diff_pct > -3:
        print('  ~ Hard gate 제거 영향 미미 — 둘 다 비슷')
    elif pf_diff_pct > -10:
        print('  ⚠ Hard gate 제거가 결과 악화 — 유지가 좋음')
    else:
        print('  ⚠⚠ Hard gate 제거가 결과 크게 악화 — 반드시 유지')
