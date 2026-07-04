#!/usr/bin/env python3
# combo_risk_table.json 재생성 — 현재 baseline 데이터(run_reconcile)의 reverse_risk 로.
#   applied = reversal(MDD-10%) x g1.2, 24/25=0, killer<=3.5%. ★expiry 무관(combo 전체 r 사용).
import json
import numpy as np
import run_reconcile as R

OUT = "live_trading/v4_integrated/combo_risk_table.json"
G = 1.2; KILLER = 0.035


def main():
    d, rp = R.load()
    combos = {}
    for s, g in d.groupby("setup"):
        r = g.sort_values("exit_time")["r"].values
        rev = 0.0 if r.sum() <= 0 else R.reverse_risk(r)
        base = 0.0 if s in R.REMOVE else rev * G
        applied = min(base, KILLER) if s in R.TARGETS else base
        combos[s] = {"reversal_risk_pct": round(rev * 100, 4),
                     "applied_risk_pct": round(applied * 100, 4), "n": int(len(r))}
    meta = {
        "config": "15m fill + 24/25_removed + global_g1.2 + killer_cap_3.5% + hard_cap_15%(live)",
        "G": G, "CAP_TARGET_killer": KILLER, "HARD_CAP_live": 0.15,
        "expiry_note": "reversal 은 만기컷 무관(combo 전체 r 로 역산) — 48h/36h 동일값. 운영 만기컷=36h.",
        "regenerated": "2026-07-04 baseline(cap15/36h) 데이터 재역산",
        "removed": sorted(R.REMOVE), "killer_capped": sorted(R.TARGETS),
        "note": "applied_risk_pct = combo reversal(MDD-10%) x g1.2, 24/25=0, killer<=3.5%. live 는 min(applied*rm, 15%).",
    }
    json.dump({"meta": meta, "combos": combos}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    over = sorted([(v["applied_risk_pct"], k) for k, v in combos.items()], reverse=True)
    print(f"[재생성] {OUT} | {len(combos)}조합")
    print(f"  applied 상위3: {[(round(v,1),k[:30]) for v,k in over[:3]]}")
    print(f"  >15%: {sum(1 for v,_ in over if v>15)} | 0.0(24/25등): {sum(1 for v,_ in over if v==0)}")


if __name__ == "__main__":
    main()
