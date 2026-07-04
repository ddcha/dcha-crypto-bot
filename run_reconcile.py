#!/usr/bin/env python3
# ★라이브↔백테스트 재조정: ②전역2%캡  ③8h양방향쿨다운(TP1전 청산만) 영향 측정.
#   기준(run_baseline_g12) 로직 그대로 + 변형 스위치. 결과 4변형 비교표.
import os
import numpy as np, pandas as pd

SRC = "walkforward_result/trades_v4.csv"; MTF15 = "mtf15_result/trades_v4_15m.csv"
INIT = 5_000_000; MON = 2_500_000; ND = 5; KRW = 1540.0; MAXN = 3.0; FEE = 0.00055
CAP_TARGET = 0.035; EXPIRY_BLOCK_HOURS = 48; G = 1.2
HARD_CAP = 0.02            # ② 라이브 전역 하드캡
COOLDOWN_H = 8.0          # ③ 라이브 양방향 EXIT 쿨다운
REMOVE = {"a_mss+a_score_ge13+a_vol_expansion", "a_room+a_score_ge13+a_vol_expansion+a_volume"}
TARGETS = {"a_mss+a_room+a_score_ge13+a_trend_counter+a_vol_expansion+a_volume", "a_sweep+a_trend_counter+a_vol_expansion+a_volume"}


def _pf(p):
    p = np.asarray(p, float); g = p[p > 0].sum(); l = -p[p < 0].sum()
    return round(g / l, 3) if l > 0 else (np.inf if g > 0 else 0.0)


def compound_mdd(r, risk):
    cap = peak = 1.0; mdd = 0.0
    for x in r:
        cap *= (1 + x * risk)
        if cap <= 1e-9:
            return -1.0
        peak = max(peak, cap); mdd = min(mdd, (cap - peak) / peak)
    return mdd


def reverse_risk(r, target=-0.10, lo=1e-4, hi=1.0):
    if compound_mdd(r, lo) < target:
        return lo
    if compound_mdd(r, hi) > target:
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        if compound_mdd(r, mid) < target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def monthly_expiries():
    days = pd.date_range("2022-01-01", "2027-12-31", freq="D", tz="UTC"); fri = [d for d in days if d.weekday() == 4]
    last = {}
    for f in fri:
        last[(f.year, f.month)] = f
    return pd.DatetimeIndex(sorted(v.replace(hour=8) for v in last.values())).tz_localize(None).values


def equity(g, rvals, risk_pct, blocked, pretp1, cooldown_h=0.0):
    ET = list(g["entry_time"]); XT = list(g["exit_time"]); SYM = list(g["symbol"])
    ENT = list(g["entry"].astype(float)); SL = list(g["sl"].astype(float))
    start = pd.Timestamp(min(ET)).tz_convert("UTC").normalize().replace(day=1); deps = []; mt = start
    for _ in range(ND):
        mt = mt + pd.offsets.MonthBegin(1); deps.append((mt, MON))
    ev = []
    for i in range(len(ET)):
        ev.append((ET[i], 2, i)); ev.append((XT[i], 1, i))
    ev += [(dt, 0, -a) for dt, a in deps]; ev.sort(key=lambda x: (x[0], x[1]))
    bal = float(INIT); openp = {}; osym = set(); n = len(g); taken = np.zeros(n, bool); pnl = np.zeros(n)
    curve = [(start, bal)]
    last_exit_cd = {}   # sym -> exit_ts (TP1 전 청산만 기록; 쿨다운 발동원)
    for ts, pri, p in ev:
        if pri == 0:
            bal += (-p); curve.append((ts, bal))
        elif pri == 1:
            if p in openp:
                rk = openp.pop(p); bal += rvals[p] * rk; osym.discard(SYM[p]); pnl[p] = rvals[p] * rk; curve.append((ts, bal))
                if cooldown_h > 0 and pretp1[p]:                 # ③ TP1 전 청산 → 쿨다운 무장
                    last_exit_cd[SYM[p]] = XT[p]
        else:
            if blocked[p] or risk_pct[p] <= 0 or SYM[p] in osym:
                continue
            if cooldown_h > 0:                                    # ③ 양방향 8h 쿨다운
                lx = last_exit_cd.get(SYM[p])
                if lx is not None and (ET[p] - lx).total_seconds() / 3600.0 < cooldown_h:
                    continue
            risk = bal * risk_pct[p]; rpu = abs(ENT[p] - SL[p])
            if rpu <= 0:
                continue
            qty = risk / (rpu * KRW); notl = qty * ENT[p] * KRW
            if notl > bal * MAXN:
                qty = bal * MAXN / (ENT[p] * KRW)
            if qty * ENT[p] * KRW * FEE * 2 > risk * 0.35:
                continue
            openp[p] = qty * rpu * KRW; osym.add(SYM[p]); taken[p] = True; curve.append((ts, bal))
    for p, rk in list(openp.items()):
        bal += rvals[p] * rk; pnl[p] = rvals[p] * rk
    cc = pd.DataFrame(curve, columns=["t", "b"]).groupby("t")["b"].last().sort_index()
    dd = (cc - cc.cummax()) / cc.cummax() * 100
    return bal, float(dd.min()), str(cc.index[int(dd.values.argmin())].date()), cc, taken, pnl


def load():
    d = pd.read_csv(SRC); d = d[~d["exit_reason"].astype(str).str.contains("close_at_end", case=False, na=False)].copy()
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True); d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    d["setup"] = d["matched_rule"].astype(str).str.split(r"\|\|").str[0]
    mtf = pd.read_csv(MTF15); mtf["entry_time"] = pd.to_datetime(mtf["entry_time"], utc=True)
    d = d.merge(mtf[["symbol", "entry_time", "r15m", "exit_time_15m"]], on=["symbol", "entry_time"], how="left")
    d = d[d["r15m"].notna()].copy().sort_values("entry_time").reset_index(drop=True); d["r"] = d["r15m"].astype(float)
    # TP1(1R) 도달여부 — max_rr_seen>=1 이면 TP1 체결 → 라이브 쿨다운 미발동
    mrr = pd.to_numeric(d.get("max_rr_seen"), errors="coerce").fillna(0.0).values
    d["pretp1"] = mrr < 1.0
    risk_map = {}
    for s, gg in d.groupby("setup"):
        r = gg.sort_values("exit_time")["r"].values; risk_map[s] = 0.0 if r.sum() <= 0 else reverse_risk(r)
    mexp = monthly_expiries(); et = d["entry_time"].dt.tz_localize(None).values
    nxt = mexp[np.searchsorted(mexp, et, side="left").clip(0, len(mexp) - 1)]
    d["hours_to_expiry"] = (nxt - et) / np.timedelta64(1, "h"); d["expiry_blocked"] = d["hours_to_expiry"] <= EXPIRY_BLOCK_HOURS
    base = d["setup"].map(risk_map).values
    base = np.where(d["setup"].isin(REMOVE).values, 0.0, base) * G
    rp = np.where(d["setup"].isin(TARGETS).values, np.minimum(base, CAP_TARGET), base)
    return d, rp


def retire_month(d, taken, pnl):
    d = d.copy(); d["pnl_krw"] = np.round(pnl); d["taken"] = taken; d["em"] = d["exit_time"].dt.strftime("%Y-%m")
    depm = {(pd.Timestamp(d["entry_time"].min()).normalize().replace(day=1) + pd.offsets.MonthBegin(k + 1)).strftime("%Y-%m"): MON for k in range(ND)}
    mp = d[d["taken"]].groupby("em")["pnl_krw"].sum(); rows = []; run = INIT; tin = INIT
    for mo in sorted(mp.index):
        dep = depm.get(mo, 0); pl = float(mp[mo]); run += dep + pl; tin += dep
        rows.append({"pnl": round(pl), "balance": round(run)})
    m = pd.DataFrame(rows); m["ma3"] = m["pnl"].rolling(3).mean()
    h = np.where(m["ma3"] >= 10_000_000)[0]
    return (sorted(mp.index)[h[0]] if len(h) else "미도달")


def run_variant(name, d, rp, cap, cooldown):
    rp2 = np.minimum(rp, cap) if cap else rp
    fin, mdd, mw, cc, taken, pnl = equity(d, d["r"].values, rp2, d["expiry_blocked"].values, d["pretp1"].values, cooldown)
    ret = retire_month(d, taken, pnl)
    dd = d.copy(); dd["pnl_krw"] = np.round(pnl)
    maxrisk = rp2[rp2 > 0].max() * 100 if (rp2 > 0).any() else 0.0
    print(f"{name:28s} | 거래 {int(taken.sum()):4d} | 승률 {(pnl[taken]>0).mean()*100:4.1f}% | PF {_pf(pnl[taken]):5.3f} "
          f"| 최종 {fin/1e8:6.2f}억 | MDD {mdd:6.2f}% ({mw}) | 최대risk {maxrisk:5.1f}% | 은퇴 {ret}")
    return {"name": name, "fin": fin, "mdd": mdd, "taken": int(taken.sum()), "retire": ret}


def main():
    d, rp = load()
    print(f"\n=== 라이브↔백테스트 재조정 (입력 {len(d)}건, TP1전청산 {int(d['pretp1'].sum())}건) ===")
    print(f"{'변형':28s} | {'거래':>4s} | {'승률':>5s} | {'PF':>5s} | {'최종':>7s} | {'MDD':>7s}          | 최대risk | 은퇴")
    print("-" * 130)
    run_variant("V0 기준(baseline_g12)", d, rp, None, 0.0)
    run_variant("V1 +전역2%캡 (②)", d, rp, HARD_CAP, 0.0)
    run_variant("V2 +8h양방향쿨다운 (③)", d, rp, None, COOLDOWN_H)
    run_variant("V3 +둘다 (라이브일치)", d, rp, HARD_CAP, COOLDOWN_H)


if __name__ == "__main__":
    main()
