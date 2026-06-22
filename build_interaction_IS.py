"""원자 상호작용 분석 (IS=2023-24 전용, OOS 손도 안 댐).
질문: "원자 X가 잡은 거래 안에서, 어떤 Y가 함께 있어야 양수로 뒤집히나?"
각 X에 대해: base(X단독) vs X∩Y. 두 신호를 같이 본다.
  - 레벨    : avgR(X∩Y), PF(X∩Y)  (X∩Y 자체가 양수냐)
  - 분리력  : avgR(X∩Y) - avgR(X∩~Y)  (X 안에서 Y가 승/패를 가르나 = 진짜 조건부효과)
  - 구제    : X단독 avgR<=0 인데 X∩Y avgR>0 으로 뒤집는 Y  (네가 찾던 그것)
OOS(2025-26)는 일절 미사용. 이건 가설생성(IS탐색)이지 검증 아님 → 동결 후 1회 OOS는 별도.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
OUT = os.path.join(CDIR, "atom_interaction_IS.xlsx")
MIN_N_XY = 20   # X∩Y IS 표본 하한
MIN_N_X = 30    # base X IS 표본 하한


def pf(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def m_stats(pnl_a, r_a):
    p = pnl_a[~np.isnan(pnl_a)]
    if len(p) == 0:
        return 0, 0.0, np.nan, 0.0
    r = r_a[~np.isnan(r_a)]
    return len(p), round(pf(p), 3), (round(float(r.mean()), 3) if len(r) else np.nan), round(100 * (p > 0).mean(), 1)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
B = {a: tb(d[a]).to_numpy() for a in acols}
pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
IS = np.isin(yr, [2023, 2024])
print(f"[상호작용 IS분석] IS거래 {int(IS.sum())} (2023-24) | OOS 미사용 | 원자 {len(acols)}")

# base: 각 X 단독 IS
base = {}
for X in acols:
    mX = B[X] & IS
    nX, pfX, rX, wX = m_stats(pnl[mX], rmul[mX])
    base[X] = dict(n=nX, pf=pfX, avgR=rX, win=wX)

rows = []
for X in acols:
    if base[X]["n"] < MIN_N_X:
        continue
    mX = B[X] & IS
    for Y in acols:
        if Y == X:
            continue
        mXY = mX & B[Y]
        mXnotY = mX & ~B[Y]
        nXY, pfXY, rXY, wXY = m_stats(pnl[mXY], rmul[mXY])
        if nXY < MIN_N_XY:
            continue
        _, _, rXnotY, _ = m_stats(pnl[mXnotY], rmul[mXnotY])
        sep = round(rXY - rXnotY, 3) if (rXY == rXY and rXnotY == rXnotY) else np.nan
        lift = round(rXY - base[X]["avgR"], 3) if (rXY == rXY and base[X]["avgR"] == base[X]["avgR"]) else np.nan
        rescue = int((base[X]["avgR"] <= 0) and (rXY is not np.nan) and (rXY > 0))
        rows.append(dict(
            X=X.replace("a_", ""), Y=Y.replace("a_", ""),
            baseX_n=base[X]["n"], baseX_PF=base[X]["pf"], baseX_avgR=base[X]["avgR"], baseX_win=base[X]["win"],
            XY_n=nXY, XY_PF=pfXY, XY_avgR=rXY, XY_win=wXY,
            lift_avgR=lift, sep_avgR=sep, rescue=rescue,
        ))

R = pd.DataFrame(rows)
print(f"평가된 (X,Y) 쌍: {len(R)} (X단독>={MIN_N_X}, X∩Y>={MIN_N_XY})\n")

# 시트1: 전체, XY_avgR 내림차순
allv = R.sort_values("XY_avgR", ascending=False).reset_index(drop=True)
# 시트2: 구제 케이스 (X단독 비양수 → X∩Y 양수)
rescue = R[R.rescue == 1].sort_values("XY_avgR", ascending=False).reset_index(drop=True)
# 시트3: 진짜 분리력 (Y가 X안에서 승/패 가름: sep_avgR 큰 + XY_avgR>0)
truesep = R[(R.sep_avgR > 0) & (R.XY_avgR > 0)].sort_values("sep_avgR", ascending=False).reset_index(drop=True)

notes = pd.DataFrame({"항목": [
    "생성일", "데이터", "스코프", "★OOS", "질문",
    "baseX_*", "XY_*", "lift_avgR", "sep_avgR", "rescue",
    "avgR 의미", "표본하한", "★위상",
], "내용": [
    "2026-06-15", f"stage4d_trades {len(d)}거래 중 IS(2023-24) {int(IS.sum())}", "IS 전용 — 2025-26 일절 미참조",
    "여기서 OOS 안 봄. 규칙 동결 후 2025-26에 '딱 한 번' 재는 건 별도 단계.",
    "X가 잡은 IS거래 안에서, 어떤 Y가 함께면 양수로 뒤집히나",
    "X 단독 IS 지표 (n/PF/avgR/win)",
    "X∩Y IS 지표 (n/PF/avgR/win)",
    "avgR(X∩Y) − avgR(X단독). X에 Y를 더해 얼마나 올랐나",
    "avgR(X∩Y) − avgR(X∩~Y). X 안에서 Y유무 차이 = Y의 진짜 조건부효과(표본축소 착시 방지)",
    "X단독 avgR<=0 인데 X∩Y avgR>0 으로 뒤집힌 쌍 = 1",
    "avgR = 거래당 평균 r_multiple = R단위 기대값. >0 이면 R기준 우위.",
    f"X단독>={MIN_N_X}, X∩Y>={MIN_N_XY}",
    "가설생성(IS탐색)일 뿐. lift/sep 큰 쌍도 다중비교 산물일 수 있음 → 소수만 추려 동결→OOS 1회로 확정.",
]})

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    notes.to_excel(xw, sheet_name="notes", index=False)
    allv.to_excel(xw, sheet_name="all_pairs", index=False)
    rescue.to_excel(xw, sheet_name="rescue_neg_to_pos", index=False)
    truesep.to_excel(xw, sheet_name="true_separation", index=False)
    pd.DataFrame([dict(atom=k.replace("a_", ""), **v) for k, v in base.items()]
                 ).sort_values("avgR", ascending=False).to_excel(xw, sheet_name="atom_base_IS", index=False)

print(f"저장 → {OUT}")
print(f"  all_pairs {len(allv)} / rescue {len(rescue)} / true_separation {len(truesep)}\n")

c = ["X", "Y", "baseX_avgR", "XY_n", "XY_PF", "XY_avgR", "XY_win", "lift_avgR", "sep_avgR"]
print("[구제: X단독 비양수 → X∩Y 양수, XY_avgR 상위 15]")
print(rescue[c].head(15).to_string(index=False) if len(rescue) else "  없음")
print("\n[진짜 분리력: Y가 X안에서 승/패 가름, sep_avgR 상위 15]")
print(truesep[c].head(15).to_string(index=False) if len(truesep) else "  없음")
