"""승자가 어떤 '규칙'에 몰려있나 — 규칙별 PF/승률/avgR + 승자점유율 정렬 나열.
규칙 = 범주형컬럼 각 값(side/tier/grade/exit_reason/rp_action/expansion_state/...)
     + 12원자 True + 수치 임계(score>=, run_potential>=, hold_bars 구간).
PF/승률/avgR 은 '전체 거래' 기준(의미있게), winner_share 는 전체 승자 중 비중.
사용: python rank_winner_rules.py [trades_csv] [min_n]
"""
import os, sys, io
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
TRADES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage4d_honest", "atoms_doomcha_15m", "stage4d_trades.csv")
MIN_N = int(sys.argv[2]) if len(sys.argv) > 2 else 30

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

d = pd.read_csv(TRADES)
for a in ATOMS:
    d[a] = d[a].astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)
d["year"] = pd.to_datetime(d["entry_time"], utc=True, errors="coerce").dt.year
pnl = d["net_pnl"].to_numpy(float)
rmul = d["r_multiple"].to_numpy(float)
yr = d["year"].to_numpy()
N = len(d)
NW = int((pnl > 0).sum())
te = np.isin(yr, [2025, 2026])


def pf_of(mask):
    s = pnl[mask]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def metr(mask):
    n = int(mask.sum())
    if n == 0:
        return None
    win = 100 * (pnl[mask] > 0).mean()
    pf = pf_of(mask)
    ar = rmul[mask].mean()
    profit = pnl[mask & (pnl > 0)].sum()
    wn = int((mask & (pnl > 0)).sum())
    pf_te = pf_of(mask & te) if (mask & te).sum() else np.nan
    return dict(n=n, win=win, pf=pf, avgR=ar, profit=profit, win_n=wn,
                win_share=100 * wn / NW, pf_te=pf_te)


# ── 규칙 수집 ──
rules = []
for a in ATOMS:
    rules.append((a.replace("a_", "") + "=T", d[a].to_numpy(bool)))
for col in ["side", "tier", "grade", "exit_reason", "rp_action", "expansion_state",
            "result", "symbol", "phase_at_entry", "tp_plan_name"]:
    if col in d.columns:
        for v in d[col].dropna().unique():
            rules.append((f"{col}={v}", (d[col] == v).to_numpy(bool)))
for col, ths in [("score", [11, 13, 15]), ("run_potential", [1, 2, 3]),
                 ("pre_entry_total", [1, 4]), ("hold_bars", [5, 20])]:
    if col in d.columns:
        x = pd.to_numeric(d[col], errors="coerce").to_numpy(float)
        for t in ths:
            rules.append((f"{col}>={t}", (x >= t)))
for y in (2023, 2024, 2025, 2026):
    rules.append((f"year={y}", (yr == y)))

recs = []
for name, m in rules:
    r = metr(m)
    if r and r["n"] >= MIN_N:
        r["rule"] = name
        recs.append(r)
R = pd.DataFrame(recs)

base_pf = pf_of(np.ones(N, bool))
base_wr = 100 * (pnl > 0).mean()
L = "=" * 122
print(L)
print(f"승자가 몰린 규칙 랭킹 | {TRADES}")
print(f"전체 {N}거래 | 승 {NW} | baseline 승률 {base_wr:.1f}% PF {base_pf:.3f} avgR {rmul.mean():+.3f} | MIN_N={MIN_N} | 규칙 {len(R)}개")
print(L)

hdr = (f"  {'#':>2} {'rule':<26}{'n':>6}{'win%':>7}{'PF':>7}{'avgR':>8}{'PFte':>7}"
       f"{'이익합':>9}{'승자수':>6}{'승자점유%':>9}")


def fmt(v, p=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if np.isinf(v):
        return "inf"
    return f"{v:.{p}f}"


def show(title, col, asc=False):
    print("\n" + L); print(title); print(L); print(hdr)
    sub = R.sort_values(col, ascending=asc).head(30)
    for i, (_, r) in enumerate(sub.iterrows(), 1):
        print(f"  {i:>2} {r['rule']:<26}{int(r['n']):>6}{fmt(r['win'],1):>7}{fmt(r['pf']):>7}"
              f"{fmt(r['avgR'],3):>8}{fmt(r['pf_te']):>7}{r['profit']:>9.0f}{int(r['win_n']):>6}{fmt(r['win_share'],1):>9}")


show("[A] PF 높은 순", "pf")
show("[B] 승률 높은 순", "win")
show("[C] avgR 높은 순", "avgR")
show("[D] 승자점유율 높은 순 (전체 승자 중 이 규칙이 차지하는 비중)", "win_share")

print("\n" + L)
print("※ PF/승률/avgR=전체거래 기준. 승자점유%=전체 승자 중 이 규칙 포함 비중(겹침 가능).")
print("  PFte(2025-26)<1 이면 OOS 비생존 — '잘 벌어보여도' test 구간선 무너지는 규칙.")
print(L)
