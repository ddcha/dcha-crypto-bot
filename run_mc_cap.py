#!/usr/bin/env python3
# ★몬테카를로 캡 스윕: "78억은 기대값이 아니라 복권 당첨분기다" 검증.
#   각 트레이드 risk%·taken·순서 고정, 결과 r15m 만 재추첨:
#     통계근거 조합(n≥30) → 자기 분포에서 / 소표본(n<30) → 시스템 전체 분포에서.
#   5000개 역사 × {리스크캡 무/2/3/5%} × {notional 3배(실제) / 무(웹클로드식)}.
#   메트릭: 파산확률·최종자본 중앙값·p5·p95·MDD중앙값.  ★15m fill(r15m) 기준.
import numpy as np, pandas as pd
import run_reconcile as R

NS = 5000; EXPIRY_H = 36.0; CD = 8.0; SEED = 12345
INIT = R.INIT; MON = R.MON; ND = R.ND; KRW = R.KRW; MAXN = R.MAXN; FEE = R.FEE
GROUND_N = 30                                   # 통계근거 최소표본
RUIN_ABS = 0.0                                  # 수학적 파산: 잔고<=0
RUIN_PRAC_FRAC = 0.10                           # 실무적 파산: 잔고 < 총투입×10%


def build(d, rp):
    d = d.copy(); d["expiry_blocked"] = (d["hours_to_expiry"] <= EXPIRY_H)
    _, _, _, _, taken, _ = R.equity(d, d["r"].values, rp, d["expiry_blocked"].values, d["pretp1"].values, CD)
    d["taken"] = taken; d["rp"] = rp
    # r 재추첨 풀: 조합 n>=30 → 자기, else 시스템 전체
    sys_pool = d["r"].values.astype(float)
    combo_pool = {}
    for s, g in d.groupby("setup"):
        v = g["r"].values.astype(float)
        combo_pool[s] = v if len(v) >= GROUND_N else None
    # 이벤트: taken 거래만 (entry/exit) + 월예치. pri: 예치0<청산1<진입2
    T = d[d["taken"]].reset_index(drop=True)
    P = len(T)
    ET = pd.to_datetime(T["entry_time"], utc=True).dt.tz_localize(None).values   # naive datetime64
    XT = pd.to_datetime(T["exit_time"], utc=True).dt.tz_localize(None).values
    ENT = T["entry"].astype(float).values; SL = T["sl"].astype(float).values
    PCT = T["rp"].astype(float).values; SETUP = T["setup"].values
    start = pd.Timestamp(ET.min()).normalize().replace(day=1)
    deps = []; mt = start
    for _ in range(ND):
        mt = mt + pd.offsets.MonthBegin(1); deps.append((np.datetime64(mt), 0, -1))
    ev = [(ET[p], 2, p) for p in range(P)] + [(XT[p], 1, p) for p in range(P)] + deps
    ev.sort(key=lambda x: (x[0], x[1]))
    # r 추첨 행렬 (NS, P)
    rng = np.random.default_rng(SEED)
    rdraw = np.empty((NS, P), dtype=float)
    for p in range(P):
        pool = combo_pool.get(SETUP[p]); pool = pool if pool is not None else sys_pool
        rdraw[:, p] = rng.choice(pool, size=NS)
    return ev, ENT, SL, PCT, rdraw, P, T


def simulate(ev, ENT, SL, PCT, rdraw, P, cap, use_notional, actual_r=None):
    NS_ = rdraw.shape[0] if actual_r is None else 1
    bal = np.full(NS_, float(INIT)); peak = bal.copy(); mdd = np.zeros(NS_); ruined = np.zeros(NS_, bool)
    pct = np.minimum(PCT, cap) if cap else PCT
    reserved = {}
    for ts, pri, p in ev:
        if pri == 0:
            bal = np.where(ruined, bal, bal + MON)
        elif pri == 2:
            rpu = abs(ENT[p] - SL[p])
            if rpu <= 0 or pct[p] <= 0:
                reserved[p] = np.zeros(NS_); continue
            risk = bal * pct[p]; qty = risk / (rpu * KRW)
            if use_notional:
                notl = qty * ENT[p] * KRW
                over = notl > bal * MAXN
                qty = np.where(over, bal * MAXN / (ENT[p] * KRW), qty)
            res = qty * rpu * KRW
            reserved[p] = np.where(ruined, 0.0, res)
        else:
            r = (np.full(NS_, actual_r[p]) if actual_r is not None else rdraw[:, p])
            pnl = r * reserved.get(p, np.zeros(NS_))
            bal = np.where(ruined, bal, bal + pnl)
            newly = (~ruined) & (bal <= 0); ruined |= newly
            bal = np.where(bal < 0, 0.0, bal)
            peak = np.maximum(peak, bal); mdd = np.minimum(mdd, (bal - peak) / peak)
    total_in = INIT + MON * ND
    return bal, mdd, ruined, total_in


def main():
    d, rp = R.load()
    ev, ENT, SL, PCT, rdraw, P, T = build(d, rp)
    # 재현 검증: 실제 r 로 replay → R.equity 최종과 비교
    b1, _, _, tin = simulate(ev, ENT, SL, PCT, rdraw, P, None, True, actual_r=T["r"].astype(float).values)
    dd = d.copy(); dd["expiry_blocked"] = (dd["hours_to_expiry"] <= EXPIRY_H)
    fin_ref, mdd_ref, _, _, _, _ = R.equity(dd, dd["r"].values, rp, dd["expiry_blocked"].values, dd["pretp1"].values, CD)
    print(f"[검증] replay 실제r 최종 {b1[0]/1e8:.2f}억  vs  R.equity {fin_ref/1e8:.2f}억  (일치≈{abs(b1[0]-fin_ref)/fin_ref*100:.1f}% 차)")
    print(f"[MC] {NS}개 역사 | 기준 V2(8h쿨다운)+만기컷{int(EXPIRY_H)}h | 15m fill | taken {P}거래 | n≥{GROUND_N} 조합=자기분포·나머지=시스템분포\n")

    for use_notional, ntag in [(True, "notional 3배(실제 백테/라이브)"), (False, "notional 무캡(웹클로드식 risk_pct 직접)")]:
        print(f"────── {ntag} ──────")
        print(f"  {'리스크캡':>7s} | {'파산(잔고0)':>9s} | {'실무파산(<10%)':>11s} | {'최종중앙값':>9s} | {'p5':>7s} | {'p95':>8s} | {'MDD중앙':>8s}")
        for cap, ctag in [(None, "무캡"), (0.02, "2%"), (0.03, "3%"), (0.05, "5%"), (0.10, "10%"), (0.15, "15%")]:
            bal, mdd, ruined, tin = simulate(ev, ENT, SL, PCT, rdraw, P, cap, use_notional)
            prac = (bal < tin * RUIN_PRAC_FRAC)
            med = np.median(bal); p5 = np.percentile(bal, 5); p95 = np.percentile(bal, 95)
            print(f"  {ctag:>7s} | {ruined.mean()*100:8.1f}% | {prac.mean()*100:10.1f}% | {med/1e8:7.2f}억 | {p5/1e8:5.2f}억 | {p95/1e8:6.2f}억 | {np.median(mdd):7.1f}%")
        print()


if __name__ == "__main__":
    main()
