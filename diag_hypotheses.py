# 가설 A/B/C 정량 검증 — 진단 전용 (코드/데이터 수정 없음)
import json, numpy as np, pandas as pd

BAR_H = 4.0  # H4 = 4시간/봉
def pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return float(g / l) if l > 0 else float('inf')

base = "combo_files_result"
runs = ["pf10", "pf12", "pf13", "pf14"]
RAW = {r: pd.read_csv(f"{base}/trades_{r}.csv") for r in runs}
T = {}
for r in runs:
    d = RAW[r].copy()
    d["exit_reason"] = d["exit_reason"].astype(str)
    d = d[~d["exit_reason"].str.contains("close_at_end", case=False, na=False)].copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    T[r] = d.sort_values(["symbol", "entry_time"]).reset_index(drop=True)

SYMS = sorted(T["pf10"]["symbol"].unique())

print("=" * 78)
print("가설 A: 단일포지션+봉전진 엔진이 빈 슬롯을 다음 후보로 즉시 메우나?")
print("  지표1 in-market% = Σhold / 전체봉span (1.0 근접=항상투자)")
print("  지표2 즉시재진입% = 직전 같은심볼 청산 후 ≤1봉(4h) 내 재진입 비율")
print("=" * 78)
print(f"{'run':<6}{'거래':>6}{'in-market%':>12}{'즉시재진입%':>14}{'중앙갭(봉)':>12}{'PF':>8}")
for r in runs:
    d = T[r]
    im_ratios = []; gaps_all = []
    for s in SYMS:
        g = d[d["symbol"] == s].sort_values("entry_time")
        if len(g) < 2:
            continue
        hold_h = (g["exit_time"] - g["entry_time"]).dt.total_seconds().values / 3600.0
        span_h = (g["exit_time"].max() - g["entry_time"].min()).total_seconds() / 3600.0
        im_ratios.append(hold_h.sum() / span_h if span_h > 0 else np.nan)
        # 갭 = 이번 진입 - 직전 청산 (시간) → 봉
        prev_exit = g["exit_time"].shift(1)
        gap_bars = (g["entry_time"] - prev_exit).dt.total_seconds().values[1:] / 3600.0 / BAR_H
        gaps_all.extend(gap_bars.tolist())
    gaps_all = np.array(gaps_all)
    im = np.nanmean(im_ratios) * 100
    immediate = (gaps_all <= 1.0).mean() * 100
    medgap = np.median(gaps_all)
    print(f"{r:<6}{len(d):>6}{im:>11.1f}%{immediate:>13.1f}%{medgap:>12.2f}{pf(d['net_pnl']):>8.3f}")

print("\n" + "=" * 78)
print("가설 B: 셋업은 pf14⊂pf10 인데, 거래(entry)도 부분집합인가?")
print("  부분집합 아니면(다른 거래 섞이면) → 4개 직접비교 무의미(B 참)")
print("=" * 78)
def kset(r):
    return set((T[r]["symbol"] + "|" + T[r]["entry_time"].astype(str)).tolist())
K = {r: kset(r) for r in runs}
for a, b in [("pf12", "pf10"), ("pf13", "pf10"), ("pf14", "pf10"), ("pf14", "pf12"), ("pf14", "pf13")]:
    inter = len(K[a] & K[b]); sub = K[a].issubset(K[b])
    print(f"  {a} 거래 {len(K[a])} | ∩{b}={inter} ({inter/len(K[a])*100:.1f}%) | {a}⊆{b}? {sub} | {a}전용={len(K[a]-K[b])}")

print("\n" + "=" * 78)
print("가설 C: REF(사후기대값)가 '30union 결과를 사후 라벨로 쪼갠 값'인가?")
print("  검증: setups_30 실행 trades 를 pf10/12/13/14 셋업으로 사후필터 → n·PF 가 REF 와 일치?")
print("=" * 78)
REF = {"pf10": (1165, 1.51), "pf12": (1088, 1.54), "pf13": (783, 1.65), "pf14": (302, 2.13)}
try:
    s30 = pd.read_csv("setups30_union_result/trades.csv")
    s30["exit_reason"] = s30["exit_reason"].astype(str)
    s30 = s30[~s30["exit_reason"].str.contains("close_at_end", case=False, na=False)].copy()
    print(f"  setups_30 실행 realized 거래수 = {len(s30)}  PF={pf(s30['net_pnl']):.4f}")
    print(f"  {'file':<6}{'사후필터 n':>12}{'사후필터 PF':>14}{'REF n':>8}{'REF PF':>8}{'독립실행 n/PF':>18}")
    for r in runs:
        setups = json.load(open(f"combination backtest/setups_{r}.json", encoding="utf-8"))
        atomsets = [s["atoms"] for s in setups]
        def match_any(row):
            return any(all(bool(row.get(a, False)) for a in ats) for ats in atomsets)
        mask = s30.apply(match_any, axis=1)
        sub = s30[mask]
        n_ref, pf_ref = REF[r]
        ind = f"{len(T[r])}/{pf(T[r]['net_pnl']):.2f}"
        print(f"  {r:<6}{len(sub):>12}{pf(sub['net_pnl']):>14.4f}{n_ref:>8}{pf_ref:>8}{ind:>18}")
except FileNotFoundError:
    print("  [skip] setups30_union_result/trades.csv 없음 — REF 출처 재현 불가")
