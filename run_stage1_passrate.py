# 단계1: 원자 임계 OLD/NEW 통과율 측정 (런타임 패치, 파일 무수정)
#   - config.py/filters.py 는 AUTO-EXTRACTED(직접수정금지) → filters 모듈 글로벌을 런타임 패치
#   - 게이트 없음(ATOM_AND_LIST=""): 9심볼 base candidate 전수에서 각 원자 True% 측정
#   - a_pre_total_ge1 은 로직(pt>=1) 하드코딩 → 변경 안 함. pt 정수분포 + >=1/>=2/>=3 통과율만 보고.
import os, json, time
os.environ.setdefault("OB_MODE", "engulf")
os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1")
os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""        # 게이트 없음
os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)

import numpy as np, pandas as pd
from smc_stage4d.config import SCENARIO_MULTI
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.filters as F
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared, simulate_scenario_v19b_rpboost

SYMBOLS = sorted(SCENARIO_MULTI["assets"].keys())
sim.USE_COMBO_UNION = False

# 7개 config 상수 (a_pre_total_ge1 은 로직이라 제외)
OLD = {"BROAD_WICK_MAX": 0.35, "BROAD_ROOM_RR_MIN": 1.5, "BROAD_VOL_RELVOL_MIN": 1.5,
       "BROAD_FVG_SIZE_ATR": 0.10, "REG_EFF_MIN": 0.30, "REG_VOL_PCTL": 0.50, "REG_BB_SQUEEZE_PCTL": 0.30}
NEW = {"BROAD_WICK_MAX": 0.20, "BROAD_ROOM_RR_MIN": 2.8, "BROAD_VOL_RELVOL_MIN": 2.8,
       "BROAD_FVG_SIZE_ATR": 0.30, "REG_EFF_MIN": 0.48, "REG_VOL_PCTL": 0.70, "REG_BB_SQUEEZE_PCTL": 0.20}
# 상수→영향원자
CONST_ATOM = {"BROAD_WICK_MAX": "a_wick_le_q1", "BROAD_ROOM_RR_MIN": "a_room",
              "BROAD_VOL_RELVOL_MIN": "a_volume", "BROAD_FVG_SIZE_ATR": "a_fvg",
              "REG_EFF_MIN": "a_efficiency", "REG_VOL_PCTL": "a_vol_expansion",
              "REG_BB_SQUEEZE_PCTL": "a_bb_squeeze"}

def patch(d):
    for k, v in d.items():
        setattr(F, k, v)

def cur_consts():
    return {k: getattr(F, k) for k in OLD}

def reset_prepared(prepared):
    # ⚠️ advance_zone_lifespan 이 structure dict 에 _ls_* 증분상태를 캐시(structures.py:79-111).
    #    generate_candidates 의 리셋은 'used' 만 → 재실행 시 _ls_pos 가 시리즈끝까지 전진해 있어
    #    2번째+ 실행이 오염됨(모든 존이 끝시점 역할로 판정=룩어헤드성). 매 패스 전 이 상태를 제거.
    for sym in prepared:
        for s in prepared[sym]["structures"]:
            for k in ("_ls_orig", "_ls_role", "_ls_broken", "_ls_pos"):
                s.pop(k, None)
            s["used"] = False

def run_once(prepared):
    reset_prepared(prepared)   # 멱등성 복원
    cand = {s: generate_candidates_from_prepared(prepared[s]) for s in SYMBOLS}
    res = simulate_scenario_v19b_rpboost(scenario=SCENARIO_MULTI, candidates_dict=cand, risk_multiplier=1.0)
    return res["trades"].copy()

def main():
    print(f"[INFO] baseline OB_MODE={os.environ['OB_MODE']} DISP_ATR_MULT={os.environ['DISP_ATR_MULT']} "
          f"USE_H1_REFINE={os.environ['USE_H1_REFINE']} HONEST_STAGE={os.environ['HONEST_STAGE']} | 게이트 없음")
    print(f"[확인] filters 기본 상수(=OLD?): {cur_consts()}")

    print("\n[STEP1] indicators 9심볼 1회")
    t0 = time.time(); prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMBOLS}
    print(f"[STEP1] 완료 {time.time()-t0:.0f}s")

    print("\n[PASS-OLD] 조정 전 임계로 candidate+simulate")
    patch(OLD); t1 = time.time(); tr_old = run_once(prepared)
    print(f"  완료 {time.time()-t1:.0f}s | 거래 {len(tr_old)}")
    print("\n[PASS-NEW] 조정 후 임계로 candidate+simulate")
    patch(NEW); t2 = time.time(); tr_new = run_once(prepared)
    print(f"  완료 {time.time()-t2:.0f}s | 거래 {len(tr_new)}")

    os.makedirs("stage1_passrate_result", exist_ok=True)
    tr_old.to_csv("stage1_passrate_result/trades_old.csv", index=False)
    tr_new.to_csv("stage1_passrate_result/trades_new.csv", index=False)

    # ── 멱등성 검증: 원자상수는 candidate 생성에 영향X(게이트OFF) → 두 패스 candidate 모집단 동일해야 ──
    k_old = set(tr_old["symbol"].astype(str) + "|" + tr_old["entry_time"].astype(str))
    k_new = set(tr_new["symbol"].astype(str) + "|" + tr_new["entry_time"].astype(str))
    print(f"\n[멱등성 검증] OLD {len(tr_old)} / NEW {len(tr_new)} | 키교집합 {len(k_old & k_new)} | 대칭차 {len(k_old ^ k_new)}")
    assert len(tr_old) == len(tr_new) and k_old == k_new, \
        f"population 불일치 {len(tr_old)}!={len(tr_new)} 또는 키 다름 — 리셋 불완전(추가 잔존상태 존재)"
    N = len(tr_old)
    print(f"  → 동일 모집단 {N}건 (멱등성 복원 확인)")

    # ── 표: 7개 config 원자 ──
    print("\n" + "=" * 78)
    print("단계1 통과율 — 7개 config 상수 원자 (목표 15~25%)")
    print("=" * 78)
    print(f"{'원자':<18}{'상수':<22}{'조정전→후':>14}{'조정전%':>9}{'조정후%':>9}{'15~25?':>9}{'플래그':>10}")
    rows = []
    for c in OLD:
        a = CONST_ATOM[c]
        b = float(tr_old[a].astype(bool).mean() * 100) if a in tr_old else float("nan")
        af = float(tr_new[a].astype(bool).mean() * 100) if a in tr_new else float("nan")
        ok = "✓" if 15 <= af <= 25 else "✗"
        flag = "HIGH>30" if af > 30 else ("LOW<8" if af < 8 else "")
        print(f"{a:<18}{c:<22}{f'{OLD[c]}→{NEW[c]}':>14}{b:>9.1f}{af:>9.1f}{ok:>9}{flag:>10}")
        rows.append({"atom": a, "const": c, "old_thr": OLD[c], "new_thr": NEW[c],
                     "before_pct": round(b, 2), "after_pct": round(af, 2),
                     "in_band": (15 <= af <= 25), "flag": flag})

    # ── a_pre_total_ge1: pt 정수분포 (로직, 변경 안 함) ──
    print("\n" + "=" * 78)
    print("a_pre_total_ge1 — ⚠️ config 상수 아님(filters.py:291 로직 pt>=1). 측정만.")
    print("=" * 78)
    pt = pd.to_numeric(tr_old["pre_entry_total"], errors="coerce").fillna(0).astype(int)
    dist = pt.value_counts().sort_index()
    print("  pre_total 정수분포:")
    for v in sorted(set([0, 1, 2, 3]) | set(dist.index.tolist())):
        cnt = int(dist.get(v, 0)); print(f"    pt={v}: {cnt:5d}건 ({cnt/N*100:5.1f}%)")
    for thr in (1, 2, 3):
        pct = float((pt >= thr).mean() * 100)
        tag = "(현행 ge1)" if thr == 1 else ("(제안 ge2)" if thr == 2 else "(=ge4실효)")
        ok = "✓" if 15 <= pct <= 25 else "✗"
        print(f"  pt>={thr} {tag:<12}: {pct:5.1f}%  목표15~25 {ok}")
    print("  ※ a_pre_total_ge4 = (pt>=3) 이므로 ge2(=pt>=2)가 ge4와 가장 구분되는 후보.")

    # ── 참고: 미조정 원자들 통과율(조정후 기준, 맥락) ──
    other = ["a_sweep", "a_mss", "a_ob", "a_sweep_count_2_4", "a_score_ge13", "a_trend_align", "a_overlap"]
    print("\n[참고] 미조정 원자 통과율(조정후): " +
          ", ".join(f"{a}={tr_new[a].astype(bool).mean()*100:.1f}%" for a in other if a in tr_new))

    pd.DataFrame(rows).to_csv("stage1_passrate_result/passrate.csv", index=False)
    print("\n[저장] stage1_passrate_result/ (trades_old.csv, trades_new.csv, passrate.csv)")

    flags = [r for r in rows if r["flag"]]
    if flags:
        print("\n⚠️ [플래그] 목표대역 크게 벗어난 원자 — 분포기반 권장임계는 보고 후 측정(임의 재조정 안 함):")
        for r in flags:
            print(f"   {r['atom']}({r['const']}): 조정후 {r['after_pct']}% [{r['flag']}]")
    else:
        print("\n[OK] 7개 모두 대역 내(또는 경미) — 단계2 진행 가능")


if __name__ == "__main__":
    main()
