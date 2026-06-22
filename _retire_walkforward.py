"""
========================================================================
시작 시점별 은퇴 시점 walk-forward 분석
========================================================================

[핵심 가정]
  v3 trades.csv 의 entry_time / r_multiple 은 그대로 두고,
  자본 시뮬레이션만 시작 날짜를 바꿔가며 새로 돌림.
  → 시그널은 시점 무관 (이미 인과적 indicator로 검증), 자본 흐름만 변경.

[방법]
  1. 시작 날짜 D 마다:
     - trades 중 entry_time >= D 인 것만 선택
     - 자본 = INITIAL_BALANCE_USDT 부터 새로 시작
     - MONTHLY_DEPOSIT_USDT × NUM_MONTHLY_DEPOSITS 입금 스케줄도 D 이후로 재배치
     - r_multiple 기반 자본 시뮬 (각 trade: balance × risk_pct × r_multiple)
     - 월별 KRW 손익 → rolling 3개월 평균 → 1000만원 도달 시점 = 은퇴
  2. D 를 매월 1일씩 슬라이드 (2023-06 ~ 2025-09)
  3. BOOST15/25/35 각각 측정 → 비교

[한계]
  - balance-aware 처방 (weak skip 임계 $50K 등) 은 자본 흐름 다르면 다르게 작동해야 하지만
    여기선 trades.csv 가 이미 한 번의 자본 흐름 가정 하에 만들어진 것이라 이 효과는 못 잡음.
  - 그래도 시작 시점 변경의 1차 영향 (entry timing, monthly deposit 시점) 은 정확히 측정.

[사용]
  D:\\smc_bot\\venv\\Scripts\\python.exe D:\\smc_bot\\_retire_walkforward.py
========================================================================
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import pandas as pd
import numpy as np
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print('[WARN] matplotlib 없음 — 시각화 생략')

# ─────────────────────────────────────────────────────────
# v3 백테스트의 자본 설정값 (코드와 동일)
# ─────────────────────────────────────────────────────────
INITIAL_CAPITAL_KRW   = 3_000_000
MONTHLY_DEPOSIT_KRW   = 2_000_000
NUM_MONTHLY_DEPOSITS  = 5
KRW_PER_USDT          = 1350.0
INITIAL_BALANCE_USDT  = INITIAL_CAPITAL_KRW / KRW_PER_USDT
MONTHLY_DEPOSIT_USDT  = MONTHLY_DEPOSIT_KRW / KRW_PER_USDT
RETIREMENT_MONTHLY_TARGET_KRW = 10_000_000
RETIREMENT_WINDOW_MONTHS = 3

# ⭐ 수정: trade 시점의 실제 risk_pct_requested 사용 (tier/rp/sentiment/scenario mult 모두 반영됨)
# 이전 fixed 1% 는 v3 실제 risk 평균 (~1.3%, max 13.2%) 대비 너무 보수적이라 retire 12m 나왔음.
USE_TRADE_RISK_PCT = True  # True = trades.csv 의 risk_pct_requested 사용 (정확)
                            # False = fixed 1% (단순)
FIXED_RISK_PCT = 0.01

V3_DIR = Path('D:/smc_bot/stage4l_redist_outputs_v3_conservative')
OUT_DIR = Path('D:/smc_bot/retire_walkforward_results')
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCENARIOS = ['BOOST15', 'BOOST25', 'BOOST35']

# ─────────────────────────────────────────────────────────
# 자본 시뮬 (시작 D 부터)
# ─────────────────────────────────────────────────────────
def simulate_from_start(trades, start_date, krw_per_usdt=KRW_PER_USDT):
    """
    Returns:
      months_to_retire : 시작 후 N개월에 retire 도달 (3개월 평균 1000만원/월)
      final_balance_usdt
      monthly_df       : 월별 손익 KRW
    """
    sub = trades[trades.entry_time >= start_date].copy().sort_values('entry_time').reset_index(drop=True)
    if len(sub) < 30:
        return None

    # 입금 스케줄: 시작 시점부터 매월 1일씩 5개월
    first_ts = pd.Timestamp(start_date).tz_convert('UTC')
    first_month_start = pd.Timestamp(year=first_ts.year, month=first_ts.month, day=1, tz='UTC')
    deposit_times = []
    cur = first_month_start + pd.offsets.MonthBegin(1)
    for _ in range(NUM_MONTHLY_DEPOSITS):
        deposit_times.append(cur)
        cur = cur + pd.offsets.MonthBegin(1)

    balance = INITIAL_BALANCE_USDT
    deposit_idx = 0
    pnls = []

    for _, row in sub.iterrows():
        # 이 trade entry 시점 전까지의 입금 처리
        et = row['entry_time']
        while deposit_idx < len(deposit_times) and deposit_times[deposit_idx] <= et:
            balance += MONTHLY_DEPOSIT_USDT
            deposit_idx += 1

        # ⭐ trade 시점의 실제 risk_pct (tier/rp/sentiment/scenario mult 모두 반영) 사용
        if USE_TRADE_RISK_PCT and 'risk_pct_requested' in row.index and pd.notna(row['risk_pct_requested']):
            risk_pct = float(row['risk_pct_requested'])
        else:
            risk_pct = FIXED_RISK_PCT

        risk_amt = balance * risk_pct
        pnl = risk_amt * row['r_multiple']
        balance += pnl
        pnls.append({
            'entry_time': et,
            'exit_time':  row['exit_time'],
            'pnl_usdt':   pnl,
            'balance':    balance,
        })

    # 남은 입금
    while deposit_idx < len(deposit_times):
        balance += MONTHLY_DEPOSIT_USDT
        deposit_idx += 1

    df = pd.DataFrame(pnls)
    df['exit_time'] = pd.to_datetime(df['exit_time'], utc=True)
    df['exit_month'] = df['exit_time'].dt.to_period('M')
    monthly = df.groupby('exit_month').agg(month_pnl_usdt=('pnl_usdt', 'sum')).reset_index()
    monthly['month_pnl_krw'] = monthly['month_pnl_usdt'] * krw_per_usdt
    monthly['rolling_3m_krw'] = monthly['month_pnl_krw'].rolling(RETIREMENT_WINDOW_MONTHS, min_periods=RETIREMENT_WINDOW_MONTHS).mean()

    qualified = monthly[monthly['rolling_3m_krw'] >= RETIREMENT_MONTHLY_TARGET_KRW]
    if len(qualified) == 0:
        retire_month = None
        months_to_retire = None
    else:
        retire_month = str(qualified.iloc[0]['exit_month'])
        retire_idx = qualified.index[0]
        months_to_retire = retire_idx + 1   # 1-indexed (1개월차 = 첫 달)

    # MDD (출금 효과 무시 — 단순 자본 흐름 기준)
    bal_arr = np.array([INITIAL_BALANCE_USDT] + df['balance'].tolist())
    cummax = np.maximum.accumulate(bal_arr)
    dd_pct = (bal_arr - cummax) / np.maximum(cummax, 1e-9) * 100
    mdd_pct = float(dd_pct.min())

    return {
        'months_to_retire': months_to_retire,
        'retire_month':     retire_month,
        'final_balance_usdt': balance,
        'final_balance_krw':  balance * krw_per_usdt,
        'mdd_pct':          mdd_pct,
        'n_trades':         len(df),
        'monthly':          monthly,
    }


# ─────────────────────────────────────────────────────────
# trades 로드
# ─────────────────────────────────────────────────────────
trades_by_sc = {}
for sc in SCENARIOS:
    f = V3_DIR / f'stage4l_{sc.lower()}_out_skip_trades.csv'
    if not f.exists():
        print(f'[ERROR] {f} 없음')
        sys.exit(1)
    t = pd.read_csv(f)
    t['entry_time'] = pd.to_datetime(t['entry_time'], utc=True)
    t['exit_time']  = pd.to_datetime(t['exit_time'], utc=True)
    trades_by_sc[sc] = t.sort_values('entry_time').reset_index(drop=True)
    print(f'[{sc}] trades = {len(t)}, 기간 {t.entry_time.min().date()} ~ {t.entry_time.max().date()}')

# ─────────────────────────────────────────────────────────
# 시작 날짜 grid 생성
# ─────────────────────────────────────────────────────────
all_min = max(t.entry_time.min() for t in trades_by_sc.values())
all_max = min(t.entry_time.max() for t in trades_by_sc.values())
# 시작점 = 매월 1일, 끝점은 max - 12개월 (최소 12개월 데이터 필요)
grid_end = all_max - pd.Timedelta(days=365)
start_dates_monthly = pd.date_range(
    pd.Timestamp(year=all_min.year, month=all_min.month+1, day=1, tz='UTC'),
    grid_end,
    freq='MS',
).tolist()
# ⭐ v3 백테스트의 실제 첫 entry 시점도 추가 (v3 결과와 직접 비교 가능)
v3_first_ts = pd.Timestamp(all_min)  # 첫 trade 시점
start_dates = [v3_first_ts] + start_dates_monthly
start_dates = sorted(set(start_dates))
print(f'\n시작 날짜 grid: {start_dates[0].date()} ~ {start_dates[-1].date()}, n={len(start_dates)}')
print(f'  (첫 점 = v3 첫 entry: {v3_first_ts}, v3 결과는 이 시점 기준 6m 은퇴)')

# ─────────────────────────────────────────────────────────
# 모든 (시나리오, 시작 날짜) 조합 시뮬
# ─────────────────────────────────────────────────────────
results = []
for sc in SCENARIOS:
    for sd in start_dates:
        r = simulate_from_start(trades_by_sc[sc], sd)
        if r is None:
            continue
        results.append({
            'scenario': sc,
            'start_date': sd,
            'months_to_retire': r['months_to_retire'],
            'retire_month': r['retire_month'],
            'final_balance_usdt': r['final_balance_usdt'],
            'final_balance_krw': r['final_balance_krw'],
            'mdd_pct': r['mdd_pct'],
            'n_trades': r['n_trades'],
        })

df = pd.DataFrame(results)
df.to_csv(OUT_DIR / 'retire_walkforward_results.csv', index=False)
print(f'\n결과 저장: {OUT_DIR / "retire_walkforward_results.csv"}')

# ─────────────────────────────────────────────────────────
# 시나리오별 요약
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[A] 시나리오별 은퇴 시점 통계 (시작 날짜 변경 시)')
print('='*100)
print(f'{"sc":<10}{"n_runs":>8}{"retire_OK":>10}{"min(m)":>8}{"median(m)":>10}{"mean(m)":>9}{"max(m)":>8}{"std(m)":>8}{"MDD mean":>10}{"MDD worst":>11}')
for sc in SCENARIOS:
    sub = df[df.scenario==sc]
    sub_ok = sub[sub.months_to_retire.notna()]
    if len(sub_ok) == 0:
        print(f'{sc:<10}{len(sub):>8d}{"0":>10}')
        continue
    print(f'{sc:<10}{len(sub):>8d}{len(sub_ok):>10d}{int(sub_ok.months_to_retire.min()):>8d}{int(sub_ok.months_to_retire.median()):>10d}{sub_ok.months_to_retire.mean():>9.1f}{int(sub_ok.months_to_retire.max()):>8d}{sub_ok.months_to_retire.std():>8.2f}{sub.mdd_pct.mean():>9.2f}%{sub.mdd_pct.min():>10.2f}%')

# ─────────────────────────────────────────────────────────
# 시작 날짜별 비교 표 (전체)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[B] 시작 날짜별 은퇴 도달 개월 수 (시나리오 비교)')
print('='*100)
pivot = df.pivot(index='start_date', columns='scenario', values='months_to_retire')
pivot['Δ(35-15)'] = pivot.get('BOOST35', np.nan) - pivot.get('BOOST15', np.nan)
print(pivot.to_string(float_format=lambda x: f'{x:.0f}' if pd.notna(x) else 'X'))

# ─────────────────────────────────────────────────────────
# MDD 비교 (시작 날짜별)
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[C] 시작 날짜별 MDD% 비교')
print('='*100)
mdd_pivot = df.pivot(index='start_date', columns='scenario', values='mdd_pct')
print(mdd_pivot.round(2).to_string())

# ─────────────────────────────────────────────────────────
# 시각화
# ─────────────────────────────────────────────────────────
if HAS_MPL:
    fig, axs = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    colors = {'BOOST15': 'steelblue', 'BOOST25': 'darkorange', 'BOOST35': 'crimson'}
    for sc in SCENARIOS:
        sub = df[(df.scenario==sc) & (df.months_to_retire.notna())]
        axs[0].plot(sub.start_date, sub.months_to_retire, 'o-', label=sc, color=colors[sc], markersize=5)
        axs[1].plot(sub.start_date, sub.mdd_pct, 'o-', label=sc, color=colors[sc], markersize=5)

    axs[0].set_ylabel('Months to Retire')
    axs[0].set_title(f'시작 날짜별 은퇴 도달 시점 (3개 시나리오, n={len(start_dates)} starts)')
    axs[0].legend(loc='upper right')
    axs[0].grid(alpha=0.3)
    axs[0].axhline(y=df[df.months_to_retire.notna()].months_to_retire.median(), color='gray', linestyle=':', alpha=0.5)

    axs[1].set_ylabel('MDD %')
    axs[1].set_title('시작 날짜별 MDD%')
    axs[1].set_xlabel('Start Date')
    axs[1].legend(loc='lower right')
    axs[1].grid(alpha=0.3)
    axs[1].axhline(y=0, color='black', alpha=0.3)

    plt.tight_layout()
    out_png = OUT_DIR / 'retire_walkforward_timeline.png'
    plt.savefig(out_png, dpi=120)
    plt.close()
    print(f'\n그래프 저장: {out_png}')

    # 추가 시각화: BOOST15 vs BOOST35 trade-off
    fig2, ax = plt.subplots(figsize=(10, 7))
    for sc in SCENARIOS:
        sub = df[(df.scenario==sc) & (df.months_to_retire.notna())]
        ax.scatter(sub.mdd_pct, sub.months_to_retire, s=80, alpha=0.7, label=sc, color=colors[sc])
    ax.set_xlabel('MDD %')
    ax.set_ylabel('Months to Retire')
    ax.set_title('Risk-Reward: MDD vs Months to Retire (각 점 = 시작 날짜)')
    ax.legend()
    ax.grid(alpha=0.3)
    out_png2 = OUT_DIR / 'retire_walkforward_scatter.png'
    plt.savefig(out_png2, dpi=120)
    plt.close()
    print(f'산점도 저장: {out_png2}')

# ─────────────────────────────────────────────────────────
# 종합 평가
# ─────────────────────────────────────────────────────────
print('\n' + '='*100)
print('[D] 종합 평가 — 어느 시나리오가 시작 시점에 가장 강건한가?')
print('='*100)
for sc in SCENARIOS:
    sub = df[(df.scenario==sc) & (df.months_to_retire.notna())]
    if len(sub) == 0: continue
    pct_under_8m  = (sub.months_to_retire <= 8).mean() * 100
    pct_under_12m = (sub.months_to_retire <= 12).mean() * 100
    print(f'\n  {sc}:')
    print(f'    은퇴 도달율    : {len(sub)}/{(df.scenario==sc).sum()} ({len(sub)/(df.scenario==sc).sum()*100:.0f}%)')
    print(f'    8개월 이내 은퇴: {pct_under_8m:.0f}%')
    print(f'    12개월 이내 은퇴: {pct_under_12m:.0f}%')
    print(f'    평균/표준편차  : {sub.months_to_retire.mean():.1f}m ± {sub.months_to_retire.std():.2f}')
    print(f'    MDD 평균/최악  : {sub.mdd_pct.mean():.2f}% / {sub.mdd_pct.min():.2f}%')

print('\n[해석 가이드]')
print('  - 은퇴 시점 std 작음 = 시작 시점 강건')
print('  - 은퇴 도달율 높음 = 더 많은 시작 시점에서 은퇴 가능')
print('  - 평균 은퇴 시점이 비슷하면 MDD 낮은 시나리오가 합리적 선택')
