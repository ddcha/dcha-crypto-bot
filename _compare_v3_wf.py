"""
========================================================================
v3_wf 결과 비교 분석기
========================================================================

[목적]
  사용자가 v3_wf.py 를 여러 BAR_STEP 옵션으로 돌린 후,
  결과 폴더들 (stage4l_redist_outputs_v3_wf_step{N}/) 을 자동 감지하고
  v3 conservative 원본 결과와 비교.

[사용법]
  D:\smc_bot\venv\Scripts\python.exe D:\smc_bot\_compare_v3_wf.py

[출력]
  1. 콘솔: 시나리오 × BAR_STEP 비교 표
  2. 파일: D:\smc_bot\wf_comparison_report.md  (마크다운, 사용자가 Claude에 복붙)

[기능]
  - 자동 감지: stage4l_redist_outputs_v3_wf_step* 폴더 모두 찾음
  - v3 baseline (stage4l_redist_outputs_v3_conservative) 와 자동 비교
  - 시나리오별 PF/Return/MDD/trades 비교 표
  - OOS PF decay 비교 (2025-01-01 기준 split)
  - ALPHA_MED SHORT, T2 패턴 등 핵심 룰 안정성
  - 마크다운 파일 자동 생성
========================================================================
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
from pathlib import Path
import re

ROOT = Path('D:/smc_bot')
V3_BASE = ROOT / 'stage4l_redist_outputs_v3_conservative'
CUTOFF = '2025-01-01'

def pf(s):
    g = s[s>0].sum(); l = abs(s[s<0].sum()); return float(g/max(l,1e-9))

def find_wf_dirs():
    """stage4l_redist_outputs_v3_wf_step{N} 폴더 모두 찾기, step 숫자 순 정렬"""
    dirs = []
    for d in ROOT.iterdir():
        m = re.match(r'^stage4l_redist_outputs_v3_wf_step(\d+)$', d.name)
        if d.is_dir() and m:
            dirs.append((int(m.group(1)), d))
    dirs.sort()
    return dirs

def load_summary(path):
    f = path / 'stage4l_comparison_summary.csv'
    if not f.exists():
        return None
    return pd.read_csv(f)

def load_trades(path, scenario):
    f = path / f'stage4l_{scenario.lower()}_out_skip_trades.csv'
    if not f.exists():
        return None
    d = pd.read_csv(f)
    d['entry_time'] = pd.to_datetime(d['entry_time'], utc=True)
    return d

def calc_oos(df):
    is_  = df[df.entry_time <  CUTOFF]
    oos  = df[df.entry_time >= CUTOFF]
    pf_is  = pf(is_.net_pnl) if len(is_)>0 else 0
    pf_oos = pf(oos.net_pnl) if len(oos)>0 else 0
    decay = (pf_oos - pf_is)/pf_is*100 if pf_is>0 else 0
    return len(is_), pf_is, len(oos), pf_oos, decay

# ─────────────────────────────────────────────────────────
# 1) 폴더 감지
# ─────────────────────────────────────────────────────────
print('='*100)
print('v3_wf 결과 비교 분석')
print('='*100)

wf_dirs = find_wf_dirs()
if not wf_dirs:
    print('[ERROR] stage4l_redist_outputs_v3_wf_step* 폴더 없음.')
    print('먼저 v3_wf.py 를 실행하세요:')
    print('  D:\\smc_bot\\venv\\Scripts\\python.exe D:\\smc_bot\\smc_crypto_stage4l_redist_h1choch_v3_wf.py')
    sys.exit(1)

print(f'\n발견된 v3_wf 결과 폴더 ({len(wf_dirs)}개):')
for step, d in wf_dirs:
    print(f'  step={step:>3d}  →  {d.name}')

has_v3_base = V3_BASE.exists()
print(f'\nv3 baseline ({V3_BASE.name}): {"✓ 존재" if has_v3_base else "✗ 없음 (v3_wf끼리만 비교)"}')

# 모든 데이터 로드
runs = {}
if has_v3_base:
    runs['v3'] = {'path': V3_BASE, 'summary': load_summary(V3_BASE), 'step': 1}
for step, d in wf_dirs:
    runs[f'wf_step{step}'] = {'path': d, 'summary': load_summary(d), 'step': step}

# 출력 markdown 동시 작성
md_lines = ['# v3_wf 결과 비교 보고서', '']
md_lines.append(f'**분석 시각**: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}')
md_lines.append('')
md_lines.append(f'**비교 대상**: v3 baseline + v3_wf 결과 {len(wf_dirs)}개')
md_lines.append('')

# ─────────────────────────────────────────────────────────
# 2) 시나리오 × run 비교 표
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[A] 시나리오별 비교 (3 시나리오 × 모든 run)')
print('='*100)
md_lines.append('## [A] 시나리오별 비교')
md_lines.append('')

scenarios = ['BOOST15', 'BOOST25', 'BOOST35']
for sc in scenarios:
    print(f'\n● {sc}')
    print(f'  {"run":<14}{"step":>5}{"trades":>8}{"win%":>7}{"PF":>8}{"MDD%":>8}{"Return%":>11}{"retire":>10}{"final$":>14}')
    md_lines.append(f'### {sc}')
    md_lines.append('')
    md_lines.append('| run | step | trades | win% | PF | MDD% | Return% | retire | final$ |')
    md_lines.append('|---|---:|---:|---:|---:|---:|---:|---|---:|')
    baseline_pf = None
    for run_name, info in runs.items():
        s = info['summary']
        if s is None:
            continue
        row = s[s.scenario==sc]
        if len(row)==0: continue
        r = row.iloc[0]
        diff_str = ''
        if baseline_pf is None:
            baseline_pf = r.PF
            diff_str = '(baseline)'
        else:
            diff = (r.PF - baseline_pf)/baseline_pf*100
            diff_str = f'({diff:+.1f}% vs v3)'
        print(f'  {run_name:<14}{info["step"]:>5}{int(r.trades):>8d}{r["win%"]:>7.2f}{r.PF:>8.3f}{r["MDD%"]:>8.2f}{r["Return_%"]:>11.0f}{r.retirement:>10}${r.total_assets_end:>13,.0f}  {diff_str}')
        md_lines.append(f'| {run_name} | {info["step"]} | {int(r.trades)} | {r["win%"]:.2f} | **{r.PF:.3f}** {diff_str} | {r["MDD%"]:.2f} | {r["Return_%"]:.0f} | {r.retirement} | ${r.total_assets_end:,.0f} |')
    md_lines.append('')

# ─────────────────────────────────────────────────────────
# 3) OOS decay 비교 (BOOST25 기준)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[B] OOS PF decay 비교 (BOOST25 기준, 2025-01-01 split)')
print('='*100)
md_lines.append('## [B] OOS PF decay 비교 (BOOST25)')
md_lines.append('')
md_lines.append('| run | step | n_IS | PF_IS | n_OOS | PF_OOS | decay |')
md_lines.append('|---|---:|---:|---:|---:|---:|---:|')
print(f'{"run":<14}{"step":>5}{"n_IS":>7}{"PF_IS":>9}{"n_OOS":>7}{"PF_OOS":>9}{"decay%":>10}')

for run_name, info in runs.items():
    t = load_trades(info['path'], 'BOOST25')
    if t is None:
        continue
    n_is, pf_is, n_oos, pf_oos, decay = calc_oos(t)
    print(f'{run_name:<14}{info["step"]:>5}{n_is:>7d}{pf_is:>9.3f}{n_oos:>7d}{pf_oos:>9.3f}{decay:>9.1f}%')
    md_lines.append(f'| {run_name} | {info["step"]} | {n_is} | {pf_is:.3f} | {n_oos} | **{pf_oos:.3f}** | {decay:+.1f}% |')
md_lines.append('')

# ─────────────────────────────────────────────────────────
# 4) 핵심 룰별 비교 (BOOST25)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[C] 핵심 룰별 비교 (BOOST25)')
print('='*100)
md_lines.append('## [C] 핵심 룰별 (BOOST25)')
md_lines.append('')

for rule_name, rule_filter in [
    ('ALPHA_MED SHORT (v3 핵심패치)', lambda d: d[(d.tier=='ALPHA_MED') & (d.side=='short')]),
    ('T2 aligned (D1=H4=down, H1=comp, SHORT)', lambda d: d[(d.d1_wave_state=='impulse_down') & (d.h4_wave_state=='impulse_down') & (d.h1_wave_state=='compression') & (d.side=='short')]),
    ('ALPHA_MAX (top tier)', lambda d: d[d.tier=='ALPHA_MAX']),
    ('ALPHA_HIGH (workhorse)', lambda d: d[d.tier=='ALPHA_HIGH']),
]:
    print(f'\n● {rule_name}')
    print(f'  {"run":<14}{"step":>5}{"n":>5}{"win%":>8}{"PF":>8}{"pnl":>14}')
    md_lines.append(f'### {rule_name}')
    md_lines.append('')
    md_lines.append('| run | step | n | win% | PF | pnl |')
    md_lines.append('|---|---:|---:|---:|---:|---:|')
    for run_name, info in runs.items():
        t = load_trades(info['path'], 'BOOST25')
        if t is None: continue
        sub = rule_filter(t)
        if len(sub)==0:
            print(f'  {run_name:<14}{info["step"]:>5}{"0":>5}')
            md_lines.append(f'| {run_name} | {info["step"]} | 0 | - | - | - |')
            continue
        w = (sub.net_pnl>0).mean()*100
        print(f'  {run_name:<14}{info["step"]:>5}{len(sub):>5d}{w:>8.1f}{pf(sub.net_pnl):>8.3f}${sub.net_pnl.sum():>13,.0f}')
        md_lines.append(f'| {run_name} | {info["step"]} | {len(sub)} | {w:.1f} | {pf(sub.net_pnl):.3f} | ${sub.net_pnl.sum():,.0f} |')
    md_lines.append('')

# ─────────────────────────────────────────────────────────
# 5) 종합 평가
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[D] 종합 평가')
print('='*100)
md_lines.append('## [D] 종합 평가')
md_lines.append('')

# BAR_STEP 별 v3 와의 거리 측정 (BOOST25 PF 기준)
b25_pfs = {}
for run_name, info in runs.items():
    s = info['summary']
    if s is None: continue
    r = s[s.scenario=='BOOST25']
    if len(r)==0: continue
    b25_pfs[run_name] = (info['step'], r['PF'].iloc[0], r['Return_%'].iloc[0])

if 'v3' in b25_pfs:
    v3_pf = b25_pfs['v3'][1]
    v3_ret = b25_pfs['v3'][2]
    print(f'\nv3 baseline BOOST25: PF={v3_pf:.3f}, Return={v3_ret:.0f}%')
    print(f'\n각 BAR_STEP의 v3 대비 손실/유사도:')
    print(f'  {"run":<14}{"step":>5}{"PF":>8}{"PF Δ%":>10}{"Return Δ%":>12}{"평가":>20}')
    md_lines.append(f'v3 baseline BOOST25: PF={v3_pf:.3f}, Return={v3_ret:.0f}%')
    md_lines.append('')
    md_lines.append('| run | step | PF | PF Δ% vs v3 | Return Δ% | 평가 |')
    md_lines.append('|---|---:|---:|---:|---:|---|')
    for run_name, (step, pf_v, ret_v) in b25_pfs.items():
        if run_name == 'v3': continue
        pf_d = (pf_v - v3_pf)/v3_pf*100
        ret_d = (ret_v - v3_ret)/v3_ret*100
        if abs(pf_d) < 3:
            eval_label = '✓ v3와 거의 동일'
        elif abs(pf_d) < 8:
            eval_label = '~ 약간 차이'
        elif abs(pf_d) < 15:
            eval_label = '⚠ 차이 큼'
        else:
            eval_label = '⚠⚠ 크게 다름'
        print(f'  {run_name:<14}{step:>5}{pf_v:>8.3f}{pf_d:>+9.1f}%{ret_d:>+11.1f}%   {eval_label}')
        md_lines.append(f'| {run_name} | {step} | {pf_v:.3f} | {pf_d:+.1f}% | {ret_d:+.1f}% | {eval_label} |')
    md_lines.append('')
    md_lines.append('### 해석')
    md_lines.append('- **v3와 거의 동일**: BAR_STEP 의존성 낮음 → 시스템 강건. sparse 평가도 신뢰 가능.')
    md_lines.append('- **차이 큼**: BAR_STEP 의존성 높음 → 진입 timing 민감. 작은 BAR_STEP 사용 권장.')
    md_lines.append('- **크게 다름**: BAR_STEP=1 (정밀)과 sparse 결과의 alpha 가 다름. 미세 timing 의존 알파일 수 있음.')

md_lines.append('')
md_lines.append('---')
md_lines.append('## 권장 다음 단계')
md_lines.append('')
md_lines.append('1. v3 baseline PF/Return 과 step 별 결과 차이가 ±3% 이내라면 → 시스템 강건성 입증, BAR_STEP=6 (1일) 충분.')
md_lines.append('2. ±10% 이상 차이 나면 → BAR_STEP=1 (매 bar) 으로 정밀 실행 필수.')
md_lines.append('3. 분기별 시계열 분석 추가 시 → walk_forward_v3.py 사용.')

# markdown 파일 저장
report_path = ROOT / 'wf_comparison_report.md'
report_path.write_text('\n'.join(md_lines), encoding='utf-8')

print('\n' + '='*100)
print(f'[DONE] 마크다운 보고서 저장: {report_path}')
print('이 파일 내용을 그대로 Claude 에 복사해서 붙여넣으세요.')
print('='*100)
