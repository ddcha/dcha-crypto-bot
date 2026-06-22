"""
========================================================================
Walk-forward 백테스트 분석기 — v3 conservative 결과 기반
========================================================================

[목적]
  v3 백테스트의 trades.csv 를 시간 슬라이딩 윈도우로 분석.
  각 윈도우마다 train (룰 평가) + test (자본 시뮬) 으로 walk-forward 진단.

[방식]
  - 백테스트를 다시 돌리지 않음. v3 trades.csv 만 사용.
  - 자본 흐름은 r_multiple 기반으로 시뮬 (각 trade마다 balance × risk × R)
  - 매 test 윈도우는 start_capital ($10,000 default) 부터 새로 시작
  - bar 단위로 슬라이드 (H4 봉 기준, 1 bar = 4시간)

[병렬화]
  - multiprocessing.Pool 로 시나리오 × 윈도우 모두 병렬 실행
  - 기본 worker = (CPU 코어 - 1)

[사용법]
  # 기본 실행 (모든 시나리오, 6개월 train / 1개월 test / 5일 slide)
  python walk_forward_v3.py

  # 옵션 조절
  python walk_forward_v3.py --train_bars 540 --test_bars 90 --slide_bars 18 --workers 8

  # 단일 시나리오만
  python walk_forward_v3.py --scenarios BOOST25

  # 윈도우 크기 옵션 (H4 봉 단위, 1 bar = 4시간)
  --train_bars 1080  → 180일 (6개월)
  --train_bars 540   → 90일  (3개월)
  --train_bars 360   → 60일  (2개월)
  --test_bars 180    → 30일  (1개월)
  --test_bars 90     → 15일  (반달)
  --slide_bars 30    → 5일
  --slide_bars 6     → 1일
  --slide_bars 1     → 4시간 (가장 정밀)

[출력] walk_forward_results_v3/
  wf_results_BOOST{15,25,35}.csv  - 윈도우별 메트릭 (train/test PF/Win/MDD/Return + 패턴별)
  wf_timeline_BOOST{15,25,35}.png - 4-panel 시계열 (PF, Return, MDD, trades)
  wf_pattern_stability.csv         - 룰별 시간 안정성 점수
  wf_summary.md                    - 종합 요약 보고서
========================================================================
"""

import argparse
import os
import sys
import time
from pathlib import Path
import multiprocessing as mp
import pandas as pd
import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# matplotlib 은 선택적 (없으면 plot 생략)
try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print('[WARN] matplotlib 미설치 — 시각화 생략')


# ─────────────────────────────────────────────────────────
# 메트릭 계산 (벡터화)
# ─────────────────────────────────────────────────────────
def calc_pf(net_pnl):
    """Profit Factor — gross_profit / gross_loss"""
    if len(net_pnl) == 0:
        return 0.0
    g = net_pnl[net_pnl > 0].sum()
    l = abs(net_pnl[net_pnl < 0].sum())
    return float(g / max(l, 1e-9))


def simulate_capital(window_trades, start_capital, fixed_risk_pct):
    """
    자본 흐름 시뮬:
      각 trade 마다 risk_amount = balance × fixed_risk_pct
      pnl = risk_amount × r_multiple  (r_multiple은 fee 반영된 수치)
      balance += pnl

    이는 v3 백테스트의 자본 흐름 로직과 동일한 구조.
    fixed_risk_pct = 0.01 (1%) 가 일반적 default. v3는 sentiment/tier mult 등으로 가변이지만,
    그 효과는 이미 r_multiple 안에 녹아있음 (실제 risk × r = 실제 pnl).

    여기선 단순화를 위해 fixed risk 사용 — walk-forward 진단 목적엔 충분.
    """
    n = len(window_trades)
    if n == 0:
        return {
            'n': 0, 'win_pct': 0.0, 'pf': 0.0, 'mdd_pct': 0.0,
            'return_pct': 0.0, 'final_balance': float(start_capital),
            'avg_R': 0.0, 'cagr_pct': 0.0,
        }

    r_mults = window_trades['r_multiple'].values
    balance = float(start_capital)
    balances = np.zeros(n + 1, dtype=np.float64)
    balances[0] = balance
    pnls = np.zeros(n, dtype=np.float64)

    for i, r in enumerate(r_mults):
        risk_amt = balance * fixed_risk_pct
        pnl = risk_amt * r
        balance += pnl
        balances[i + 1] = balance
        pnls[i] = pnl

    cummax = np.maximum.accumulate(balances)
    dd_pct = (balances - cummax) / np.maximum(cummax, 1e-9) * 100.0
    mdd = float(dd_pct.min())

    win_pct = float((pnls > 0).mean() * 100.0)
    pf = calc_pf(pd.Series(pnls))
    return_pct = float((balance - start_capital) / start_capital * 100.0)

    # CAGR (annualized) — 윈도우 길이 기반
    t0 = window_trades['entry_time'].iloc[0]
    t1 = window_trades['entry_time'].iloc[-1]
    days = max((t1 - t0).total_seconds() / 86400.0, 1.0)
    years = days / 365.25
    cagr = float(((balance / start_capital) ** (1 / max(years, 1/365)) - 1) * 100) if balance > 0 else -100.0

    return {
        'n': int(n),
        'win_pct': win_pct,
        'pf': pf,
        'mdd_pct': mdd,
        'return_pct': return_pct,
        'final_balance': float(balance),
        'avg_R': float(np.mean(r_mults)),
        'cagr_pct': cagr,
    }


def calc_simple_metrics(window_trades):
    """net_pnl 기반 단순 메트릭 — train 윈도우 평가용 (자본 시뮬 없음)"""
    if len(window_trades) == 0:
        return {'n': 0, 'win_pct': 0.0, 'pf': 0.0, 'avg_R': 0.0, 'pnl_sum': 0.0}
    return {
        'n': int(len(window_trades)),
        'win_pct': float((window_trades['net_pnl'] > 0).mean() * 100.0),
        'pf': calc_pf(window_trades['net_pnl']),
        'avg_R': float(window_trades['r_multiple'].mean()),
        'pnl_sum': float(window_trades['net_pnl'].sum()),
    }


# ─────────────────────────────────────────────────────────
# 윈도우 생성 (bar 단위 슬라이드)
# ─────────────────────────────────────────────────────────
def make_bar_windows(t_min, t_max, train_bars, test_bars, slide_bars, bar_hours=4):
    """
    bar 단위 슬라이딩 윈도우 생성.
      train_bars: train 윈도우 크기
      test_bars:  test 윈도우 크기 (train 직후)
      slide_bars: 다음 윈도우로 이동하는 step

    각 bar = 4시간 (H4 기준).
    """
    train_td = pd.Timedelta(hours=train_bars * bar_hours)
    test_td = pd.Timedelta(hours=test_bars * bar_hours)
    slide_td = pd.Timedelta(hours=slide_bars * bar_hours)

    windows = []
    cursor = t_min
    while cursor + train_td + test_td <= t_max:
        windows.append({
            'idx': len(windows),
            'train_start': cursor,
            'train_end': cursor + train_td,
            'test_start': cursor + train_td,
            'test_end': cursor + train_td + test_td,
        })
        cursor = cursor + slide_td
    return windows


# ─────────────────────────────────────────────────────────
# 패턴별 메트릭 (test 윈도우 기준)
# ─────────────────────────────────────────────────────────
PATTERN_DEFS = {
    # sentiment 라벨 (h1choch 와 v3 양쪽 라벨 모두 체크)
    'CUT_ShortStable_L':           {'col': 'sentiment_label', 'val': 'CUT_ShortStable_L'},
    'CUT_ShortStable_L_DISABLED':  {'col': 'sentiment_label', 'val': 'CUT_ShortStable_L_DISABLED'},
    'BOOST_TopReversal':           {'col': 'sentiment_label', 'val': 'BOOST_TopReversal'},
    'BOOST_BottomReversal':        {'col': 'sentiment_label', 'val': 'BOOST_BottomReversal'},
    'BOOST_TrendStart_S':          {'col': 'sentiment_label', 'val': 'BOOST_TrendStart_S'},
    'BOOST_TrendStart_L':          {'col': 'sentiment_label', 'val': 'BOOST_TrendStart_L'},
    'CUT_NeutStable_S':            {'col': 'sentiment_label', 'val': 'CUT_NeutStable_S'},
    'CUT_NeutFalling_S':           {'col': 'sentiment_label', 'val': 'CUT_NeutFalling_S'},
}


def calc_pattern_metrics(test_trades):
    """패턴별 PF/n 계산 (test 윈도우)"""
    out = {}
    if len(test_trades) == 0:
        return out

    # sentiment 패턴들
    for name, defn in PATTERN_DEFS.items():
        col = defn['col']
        if col not in test_trades.columns:
            continue
        sub = test_trades[test_trades[col] == defn['val']]
        out[f'pat_{name}_n'] = int(len(sub))
        out[f'pat_{name}_pf'] = calc_pf(sub['net_pnl']) if len(sub) else 0.0

    # T2 패턴 (D1=H4=down + H1=compression + SHORT)
    if all(c in test_trades.columns for c in ['d1_wave_state', 'h4_wave_state', 'h1_wave_state', 'side']):
        t2 = test_trades[
            (test_trades.d1_wave_state == 'impulse_down') &
            (test_trades.h4_wave_state == 'impulse_down') &
            (test_trades.h1_wave_state == 'compression') &
            (test_trades.side == 'short')
        ]
        out['pat_T2aligned_n'] = int(len(t2))
        out['pat_T2aligned_pf'] = calc_pf(t2['net_pnl']) if len(t2) else 0.0

    # ALPHA_MED SHORT (v3 핵심 패치)
    if 'tier' in test_trades.columns and 'side' in test_trades.columns:
        am_s = test_trades[(test_trades.tier == 'ALPHA_MED') & (test_trades.side == 'short')]
        am_l = test_trades[(test_trades.tier == 'ALPHA_MED') & (test_trades.side == 'long')]
        out['amed_short_n'] = int(len(am_s))
        out['amed_short_pf'] = calc_pf(am_s['net_pnl']) if len(am_s) else 0.0
        out['amed_short_pnl'] = float(am_s['net_pnl'].sum()) if len(am_s) else 0.0
        out['amed_long_n'] = int(len(am_l))
        out['amed_long_pf'] = calc_pf(am_l['net_pnl']) if len(am_l) else 0.0

        # ALPHA_MAX, ALPHA_HIGH PF (시간별 안정성 추적용)
        for tier in ['ALPHA_MAX', 'ALPHA_HIGH', 'SWEEP_ROOM_FVG']:
            sub = test_trades[test_trades.tier == tier]
            out[f'tier_{tier}_n'] = int(len(sub))
            out[f'tier_{tier}_pf'] = calc_pf(sub['net_pnl']) if len(sub) else 0.0

    return out


# ─────────────────────────────────────────────────────────
# 단일 윈도우 처리 (multiprocessing worker)
# ─────────────────────────────────────────────────────────
def process_window(args):
    """
    별도 프로세스에서 실행.
    각 worker는 독립적이라 trades 를 다시 로드 (Pool initializer 안 쓰고 단순화).
    """
    window, trades_path, start_capital, fixed_risk_pct = args

    trades = pd.read_csv(trades_path)
    trades['entry_time'] = pd.to_datetime(trades['entry_time'], utc=True)
    trades = trades.sort_values('entry_time').reset_index(drop=True)

    train = trades[
        (trades.entry_time >= window['train_start']) &
        (trades.entry_time < window['train_end'])
    ]
    test = trades[
        (trades.entry_time >= window['test_start']) &
        (trades.entry_time < window['test_end'])
    ]

    train_metrics = calc_simple_metrics(train)
    test_metrics = simulate_capital(test, start_capital, fixed_risk_pct)
    pattern_metrics = calc_pattern_metrics(test)

    result = {
        'window_idx': window['idx'],
        'train_start': window['train_start'].isoformat(),
        'train_end': window['train_end'].isoformat(),
        'test_start': window['test_start'].isoformat(),
        'test_end': window['test_end'].isoformat(),
    }
    for k, v in train_metrics.items():
        result[f'train_{k}'] = v
    for k, v in test_metrics.items():
        result[f'test_{k}'] = v
    for k, v in pattern_metrics.items():
        result[f'test_{k}'] = v

    return result


# ─────────────────────────────────────────────────────────
# 시나리오별 walk-forward 실행
# ─────────────────────────────────────────────────────────
def run_scenario(scenario, src_dir, output_dir, train_bars, test_bars, slide_bars,
                 workers, start_capital, fixed_risk_pct):
    trades_path = src_dir / f'stage4l_{scenario.lower()}_out_skip_trades.csv'
    if not trades_path.exists():
        print(f'[SKIP {scenario}] trades.csv 없음: {trades_path}')
        return None

    trades = pd.read_csv(trades_path)
    trades['entry_time'] = pd.to_datetime(trades['entry_time'], utc=True)
    trades = trades.sort_values('entry_time').reset_index(drop=True)

    if len(trades) == 0:
        print(f'[SKIP {scenario}] trades 비어있음')
        return None

    t_min = trades['entry_time'].min()
    t_max = trades['entry_time'].max()
    print(f'[{scenario}] 데이터 기간: {t_min.date()} ~ {t_max.date()}, total trades = {len(trades)}')

    windows = make_bar_windows(t_min, t_max, train_bars, test_bars, slide_bars)
    if not windows:
        print(f'[SKIP {scenario}] 윈도우 생성 실패 (데이터 너무 짧음)')
        return None

    print(f'[{scenario}] 생성된 windows = {len(windows)}, workers = {workers}')

    # multiprocessing
    args_list = [
        (w, str(trades_path), start_capital, fixed_risk_pct)
        for w in windows
    ]

    t_start = time.time()
    results = []
    with mp.Pool(workers) as pool:
        # imap_unordered 로 진행 상황 출력
        for i, r in enumerate(pool.imap_unordered(process_window, args_list)):
            results.append(r)
            if (i + 1) % max(1, len(windows) // 10) == 0 or (i + 1) == len(windows):
                elapsed = time.time() - t_start
                print(f'  [{scenario}] {i+1}/{len(windows)} windows done ({elapsed:.1f}s)')

    # window_idx 순으로 정렬
    results.sort(key=lambda x: x['window_idx'])
    df = pd.DataFrame(results)

    out_csv = output_dir / f'wf_results_{scenario}.csv'
    df.to_csv(out_csv, index=False)
    print(f'[{scenario}] 저장 완료: {out_csv}')
    return df


# ─────────────────────────────────────────────────────────
# 시각화 — 4-panel 시계열
# ─────────────────────────────────────────────────────────
def plot_scenario(df, scenario, output_dir):
    if not HAS_MPL or df is None or len(df) == 0:
        return
    df = df.copy()
    df['test_start'] = pd.to_datetime(df['test_start'])

    fig, axs = plt.subplots(4, 1, figsize=(14, 12), sharex=True)

    # [1] Test PF
    axs[0].plot(df['test_start'], df['test_pf'], 'o-', color='steelblue', label='Test PF')
    axs[0].plot(df['test_start'], df['train_pf'], 's--', color='gray', alpha=0.5, label='Train PF (참고)')
    axs[0].axhline(y=1.0, color='red', linestyle='--', alpha=0.5, label='break-even')
    pf_mean = df['test_pf'].mean()
    axs[0].axhline(y=pf_mean, color='green', linestyle=':', alpha=0.7, label=f'Test PF mean={pf_mean:.2f}')
    axs[0].set_ylabel('PF')
    axs[0].set_title(f'{scenario} — Walk-forward (Train→Test) | windows={len(df)}')
    axs[0].legend(loc='upper right')
    axs[0].grid(alpha=0.3)

    # [2] Test Return %
    axs[1].plot(df['test_start'], df['test_return_pct'], 'o-', color='darkgreen')
    axs[1].axhline(y=0, color='red', linestyle='--', alpha=0.5)
    ret_mean = df['test_return_pct'].mean()
    axs[1].axhline(y=ret_mean, color='blue', linestyle=':', alpha=0.7, label=f'mean={ret_mean:.2f}%')
    axs[1].set_ylabel('Test Return %')
    axs[1].legend(loc='upper right')
    axs[1].grid(alpha=0.3)

    # [3] Test MDD %
    axs[2].plot(df['test_start'], df['test_mdd_pct'], 'o-', color='darkred')
    axs[2].axhline(y=df['test_mdd_pct'].mean(), color='black', linestyle=':', alpha=0.5,
                   label=f'mean={df["test_mdd_pct"].mean():.2f}%')
    axs[2].set_ylabel('Test MDD %')
    axs[2].legend(loc='lower right')
    axs[2].grid(alpha=0.3)

    # [4] trade count
    axs[3].plot(df['test_start'], df['test_n'], 'o-', color='purple', label='test trades')
    axs[3].plot(df['test_start'], df['train_n'], 's--', color='gray', alpha=0.5, label='train trades')
    axs[3].set_ylabel('# trades')
    axs[3].set_xlabel('Test window start')
    axs[3].legend(loc='upper right')
    axs[3].grid(alpha=0.3)

    plt.tight_layout()
    out_png = output_dir / f'wf_timeline_{scenario}.png'
    plt.savefig(out_png, dpi=120)
    plt.close()
    print(f'[{scenario}] plot 저장: {out_png}')


def plot_pattern_stability_combined(scenario_results, output_dir):
    """모든 시나리오의 룰별 PF 시계열 — 단일 PNG"""
    if not HAS_MPL:
        return
    valid = {sc: df for sc, df in scenario_results.items() if df is not None and len(df) > 0}
    if not valid:
        return

    # 추적할 룰
    rules = [
        ('test_amed_short_pf', 'ALPHA_MED SHORT', 'red'),
        ('test_pat_T2aligned_pf', 'T2 (D1=H4=down, H1=comp, SHORT)', 'green'),
        ('test_pat_BOOST_BottomReversal_pf', 'BOOST_BottomReversal', 'blue'),
        ('test_pat_BOOST_TrendStart_S_pf', 'BOOST_TrendStart_S', 'orange'),
        ('test_tier_ALPHA_MAX_pf', 'ALPHA_MAX', 'darkviolet'),
        ('test_tier_ALPHA_HIGH_pf', 'ALPHA_HIGH', 'brown'),
    ]

    fig, axs = plt.subplots(len(valid), 1, figsize=(14, 3.5 * len(valid)), sharex=True)
    if len(valid) == 1:
        axs = [axs]

    for ax, (sc, df) in zip(axs, valid.items()):
        df = df.copy()
        df['test_start'] = pd.to_datetime(df['test_start'])
        for col, label, color in rules:
            if col in df.columns:
                ax.plot(df['test_start'], df[col].clip(upper=15), 'o-', label=label, color=color, markersize=4, alpha=0.8)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
        ax.set_ylabel('Test PF (clipped at 15)')
        ax.set_title(f'{sc} — 룰별 시간 안정성')
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(alpha=0.3)
    axs[-1].set_xlabel('Test window start')
    plt.tight_layout()
    out_png = output_dir / 'wf_pattern_stability.png'
    plt.savefig(out_png, dpi=120)
    plt.close()
    print(f'룰 안정성 plot 저장: {out_png}')


# ─────────────────────────────────────────────────────────
# 종합 요약 보고서 (markdown)
# ─────────────────────────────────────────────────────────
def write_summary(scenario_results, output_dir, params):
    md_path = output_dir / 'wf_summary.md'
    lines = ['# Walk-forward 분석 요약', '']

    lines.append('## 설정')
    for k, v in params.items():
        lines.append(f'- **{k}**: {v}')
    lines.append('')

    lines.append('## 시나리오별 안정성 (test 윈도우 기준)')
    lines.append('')
    lines.append('| 시나리오 | windows | PF mean | PF std | PF >1.5 % | Return mean % | Return std % | MDD mean | MDD worst | Stability* |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')

    for sc, df in scenario_results.items():
        if df is None or len(df) == 0:
            continue
        pf_mean = df['test_pf'].mean()
        pf_std = df['test_pf'].std()
        pf_above = (df['test_pf'] > 1.5).mean() * 100
        ret_mean = df['test_return_pct'].mean()
        ret_std = df['test_return_pct'].std()
        mdd_mean = df['test_mdd_pct'].mean()
        mdd_worst = df['test_mdd_pct'].min()
        stability = pf_mean / max(pf_std, 0.01)  # Sharpe-like
        lines.append(
            f'| {sc} | {len(df)} | {pf_mean:.3f} | {pf_std:.3f} | {pf_above:.1f}% | '
            f'{ret_mean:.2f} | {ret_std:.2f} | {mdd_mean:.2f} | {mdd_worst:.2f} | {stability:.2f} |'
        )
    lines.append('')
    lines.append('*Stability = PF mean / PF std — 클수록 시간 안정성 좋음 (Sharpe-like)')
    lines.append('')

    # 룰 안정성 (BOOST25 기준)
    if 'BOOST25' in scenario_results and scenario_results['BOOST25'] is not None:
        df = scenario_results['BOOST25']
        lines.append('## 룰별 시간 안정성 (BOOST25 기준)')
        lines.append('')
        lines.append('| 룰 | windows w/ data | mean PF | std PF | windows PF<0.7 | windows PF>2 | 안정성 평가 |')
        lines.append('|---|---:|---:|---:|---:|---:|---|')

        rule_cols = [
            ('test_amed_short_pf', 'ALPHA_MED SHORT'),
            ('test_pat_T2aligned_pf', 'T2 aligned'),
            ('test_pat_BOOST_BottomReversal_pf', 'BOOST_BottomReversal'),
            ('test_pat_BOOST_TopReversal_pf', 'BOOST_TopReversal'),
            ('test_pat_BOOST_TrendStart_S_pf', 'BOOST_TrendStart_S'),
            ('test_pat_BOOST_TrendStart_L_pf', 'BOOST_TrendStart_L'),
            ('test_pat_CUT_NeutStable_S_pf', 'CUT_NeutStable_S'),
            ('test_pat_CUT_NeutFalling_S_pf', 'CUT_NeutFalling_S'),
            ('test_pat_CUT_ShortStable_L_DISABLED_pf', 'CUT_ShortStable_L (DISABLED)'),
            ('test_tier_ALPHA_MAX_pf', 'ALPHA_MAX tier'),
            ('test_tier_ALPHA_HIGH_pf', 'ALPHA_HIGH tier'),
        ]
        for col, label in rule_cols:
            if col not in df.columns:
                continue
            valid = df[df[col] > 0][col]  # 데이터 있는 윈도우만
            if len(valid) == 0:
                continue
            mean_pf = valid.mean()
            std_pf = valid.std() if len(valid) > 1 else 0
            n_low = (valid < 0.7).sum()
            n_high = (valid > 2.0).sum()
            cv = std_pf / max(mean_pf, 0.01)
            if cv < 0.3:
                eval_label = '✅ 매우 안정'
            elif cv < 0.6:
                eval_label = '✓ 안정'
            elif cv < 1.0:
                eval_label = '⚠ 변동 큼'
            else:
                eval_label = '⚠⚠ 매우 불안정'
            lines.append(
                f'| {label} | {len(valid)} | {mean_pf:.3f} | {std_pf:.3f} | {n_low} | {n_high} | {eval_label} |'
            )
        lines.append('')

    # 시기별 worst/best
    if 'BOOST25' in scenario_results and scenario_results['BOOST25'] is not None:
        df = scenario_results['BOOST25'].copy()
        df['test_start'] = pd.to_datetime(df['test_start'])
        worst = df.nsmallest(3, 'test_pf')
        best = df.nlargest(3, 'test_pf')
        lines.append('## BOOST25 — 최악 / 최고 윈도우 Top 3')
        lines.append('')
        lines.append('### 최악 윈도우 (Test PF 낮은 순)')
        lines.append('| test_start | test_end | test_n | test_PF | test_Return% | test_MDD% |')
        lines.append('|---|---|---:|---:|---:|---:|')
        for _, r in worst.iterrows():
            lines.append(
                f'| {r["test_start"].date()} | {pd.to_datetime(r["test_end"]).date()} | '
                f'{int(r["test_n"])} | {r["test_pf"]:.3f} | {r["test_return_pct"]:.2f} | {r["test_mdd_pct"]:.2f} |'
            )
        lines.append('')
        lines.append('### 최고 윈도우 (Test PF 높은 순)')
        lines.append('| test_start | test_end | test_n | test_PF | test_Return% | test_MDD% |')
        lines.append('|---|---|---:|---:|---:|---:|')
        for _, r in best.iterrows():
            lines.append(
                f'| {r["test_start"].date()} | {pd.to_datetime(r["test_end"]).date()} | '
                f'{int(r["test_n"])} | {r["test_pf"]:.3f} | {r["test_return_pct"]:.2f} | {r["test_mdd_pct"]:.2f} |'
            )
        lines.append('')

    lines.append('## 해석 가이드')
    lines.append('- **PF mean**: 시간 평균 PF. >2.0 강한 알파, 1.5~2.0 양호, 1.0~1.5 약한 알파, <1.0 손실')
    lines.append('- **PF std**: PF 변동성. 작을수록 안정 (regime 의존성 낮음)')
    lines.append('- **PF >1.5 비율**: 양호 윈도우 비율. >70% 면 강건한 시스템')
    lines.append('- **Stability**: PF mean / std. >2.0 매우 안정, 1.0~2.0 안정, <1.0 불안정')
    lines.append('- **룰 평가**: CV < 0.3 매우 안정, < 0.6 안정, < 1.0 변동 큼, >= 1.0 매우 불안정')
    lines.append('')
    lines.append('## 다음 단계 추천')
    lines.append('- ⚠⚠ 매우 불안정 룰 → 비활성 또는 적용 강도 줄이기 검토')
    lines.append('- 최악 윈도우 시기 분석 → regime/이벤트 식별 (예: 특정 분기에 시스템 약함)')
    lines.append('- 시나리오별 stability 비교 → boost mult 선택 (안정성 vs 수익성 trade-off)')

    md_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'요약 보고서 저장: {md_path}')


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Walk-forward 백테스트 분석기 (v3 trades.csv 기반)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--train_bars', type=int, default=1080,
                        help='train 윈도우 크기 (H4 봉 단위, default 1080 = 180일)')
    parser.add_argument('--test_bars', type=int, default=180,
                        help='test 윈도우 크기 (default 180 = 30일)')
    parser.add_argument('--slide_bars', type=int, default=30,
                        help='슬라이드 step (default 30 = 5일)')
    parser.add_argument('--workers', type=int, default=max(1, mp.cpu_count() - 1),
                        help=f'병렬 worker 수 (default {max(1, mp.cpu_count() - 1)} = CPU-1)')
    parser.add_argument('--scenarios', default='BOOST15,BOOST25,BOOST35',
                        help='분석할 시나리오 (콤마구분, default BOOST15,BOOST25,BOOST35)')
    parser.add_argument('--src_dir', default='stage4l_redist_outputs_v3_conservative',
                        help='v3 백테스트 출력 폴더 경로 (default v3_conservative)')
    parser.add_argument('--output_dir', default='walk_forward_results_v3',
                        help='walk-forward 결과 저장 폴더')
    parser.add_argument('--start_capital', type=float, default=10000.0,
                        help='각 test 윈도우 시작 자본 USDT (default 10000)')
    parser.add_argument('--fixed_risk_pct', type=float, default=0.01,
                        help='trade당 risk 비율 (default 0.01 = 1%%)')
    parser.add_argument('--no_plot', action='store_true', help='시각화 PNG 생성 비활성')
    args = parser.parse_args()

    src_dir = Path(args.src_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print('=' * 80)
    print('Walk-forward 백테스트 분석 (v3 trades 기반)')
    print('=' * 80)
    print(f'  CPU cores 감지            = {mp.cpu_count()}')
    print(f'  사용 workers              = {args.workers}')
    print(f'  train_bars                = {args.train_bars} ({args.train_bars*4/24:.0f}일)')
    print(f'  test_bars                 = {args.test_bars}  ({args.test_bars*4/24:.0f}일)')
    print(f'  slide_bars                = {args.slide_bars} ({args.slide_bars*4/24:.0f}일)')
    print(f'  scenarios                 = {args.scenarios}')
    print(f'  src_dir                   = {src_dir.absolute()}')
    print(f'  output_dir                = {output_dir.absolute()}')
    print(f'  start_capital             = ${args.start_capital:,.0f}')
    print(f'  fixed_risk_pct            = {args.fixed_risk_pct*100:.2f}%')
    print(f'  matplotlib 사용           = {HAS_MPL}')
    print('=' * 80)

    if not src_dir.exists():
        print(f'\n[ERROR] src_dir 없음: {src_dir.absolute()}')
        print('v3 백테스트 (smc_crypto_stage4l_redist_h1choch_v3_conservative.py) 를 먼저 실행하거나')
        print('--src_dir 옵션으로 trades.csv 가 있는 다른 폴더를 지정하세요.')
        sys.exit(1)

    scenarios = [s.strip() for s in args.scenarios.split(',')]
    scenario_results = {}

    overall_start = time.time()
    for sc in scenarios:
        print()
        df = run_scenario(
            sc, src_dir, output_dir,
            args.train_bars, args.test_bars, args.slide_bars,
            args.workers, args.start_capital, args.fixed_risk_pct,
        )
        scenario_results[sc] = df
        if df is not None and not args.no_plot:
            plot_scenario(df, sc, output_dir)

    if not args.no_plot:
        plot_pattern_stability_combined(scenario_results, output_dir)

    params = {
        'train_bars': f'{args.train_bars} ({args.train_bars*4/24:.0f}일)',
        'test_bars': f'{args.test_bars} ({args.test_bars*4/24:.0f}일)',
        'slide_bars': f'{args.slide_bars} ({args.slide_bars*4/24:.0f}일)',
        'workers': args.workers,
        'scenarios': args.scenarios,
        'src_dir': str(src_dir),
        'start_capital': f'${args.start_capital:,.0f}',
        'fixed_risk_pct': f'{args.fixed_risk_pct*100:.2f}%',
    }
    write_summary(scenario_results, output_dir, params)

    elapsed = time.time() - overall_start
    print()
    print('=' * 80)
    print(f'[DONE] walk-forward 완료 ({elapsed:.1f}s)')
    print(f'결과: {output_dir.absolute()}')
    print('=' * 80)


if __name__ == '__main__':
    # Windows 에서 multiprocessing 사용 시 필수
    mp.freeze_support()
    main()
