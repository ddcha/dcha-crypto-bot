"""213개 유효(OOS PF>1) 조합을 PF/OOS/avg R/win rate 등 전지표로 재계산 → 엑셀.
all_orders_valid.csv 의 combo 문자열을 원자집합으로 복원, stage4d_trades.csv 에서 마스크 재생성.
전기간/train(23-24)/OOS(25-26) 각각: 거래수·PF·rPF·avgR·승률·평균손익·기대값.
주의: 전부 POST-HOC(슬롯재배치 미반영) → 실전과 괴리 가능. 실전확정은 run_and_sweep 필요.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
VAL = os.path.join(CDIR, "all_orders_valid.csv")
OUT = os.path.join(CDIR, "valid_213_combos_metrics.xlsx")


def pf(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def stats(pnl_a, r_a):
    """pnl/r 배열 묶음 → 지표 dict."""
    p = pnl_a[~np.isnan(pnl_a)]
    n = len(p)
    if n == 0:
        return dict(n=0, pf=0.0, win=0.0, avg_pnl=0.0, avg_r=0.0, expectancy=0.0, rpf=0.0)
    wins = p > 0
    r = r_a[~np.isnan(r_a)]
    return dict(
        n=n,
        pf=round(pf(p), 3),
        win=round(100.0 * wins.mean(), 1),
        avg_pnl=round(float(p.mean()), 2),
        avg_r=round(float(r.mean()), 3) if len(r) else np.nan,
        expectancy=round(float(r.mean()), 3) if len(r) else np.nan,  # avg R = R-단위 기대값
        rpf=round(pf(r), 3) if len(r) else np.nan,
    )


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
B = {a: tb(d[a]).to_numpy() for a in acols}
pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
tr = np.isin(yr, [2023, 2024]); te = np.isin(yr, [2025, 2026])

# combo 문자열("name1∩name2") → 원자컬럼 리스트 복원
name2col = {c.replace("a_", ""): c for c in acols}

V = pd.read_csv(VAL)
rows = []
for _, rr in V.iterrows():
    names = rr["combo"].split("∩")
    cols = [name2col[nm] for nm in names]
    m = np.logical_and.reduce([B[c] for c in cols])

    allp = stats(pnl[m], rmul[m])
    trp = stats(pnl[m & tr], rmul[m & tr])
    oop = stats(pnl[m & te], rmul[m & te])

    rows.append(dict(
        combo=rr["combo"], k=int(rr["k"]),
        # 전기간
        n=allp["n"], PF=allp["pf"], win_pct=allp["win"], avg_R=allp["avg_r"],
        avg_pnl=allp["avg_pnl"], rPF=allp["rpf"],
        # train 23-24
        n_tr=trp["n"], PF_tr=trp["pf"], win_tr=trp["win"], avgR_tr=trp["avg_r"],
        # OOS 25-26
        n_oos=oop["n"], PF_oos=oop["pf"], win_oos=oop["win"], avgR_oos=oop["avg_r"], rPF_oos=oop["rpf"],
        # 연도 분산
        n23=int(rr["n23"]), n24=int(rr["n24"]), n25=int(rr["n25"]), n26=int(rr["n26"]),
        pf23=rr["pf23"], pf24=rr["pf24"], pf25=rr["pf25"], pf26=rr["pf26"],
        yrs_present=int(rr["yrs"]), max_year_share=rr["maxshare"],
    ))

M = pd.DataFrame(rows).sort_values(["n_oos", "PF_oos"], ascending=False).reset_index(drop=True)

# 안정성 플래그
M["both_oos_pf>1"] = ((M.pf25 > 1) & (M.pf26 > 1)).astype(int)
M["all4yr_pf>1"] = ((M.pf23 > 1) & (M.pf24 > 1) & (M.pf25 > 1) & (M.pf26 > 1)).astype(int)
M["tiny2026_infl"] = ((M.n26 < 10) & (M.pf26 > 3)).astype(int)

notes = pd.DataFrame({"항목": [
    "생성일", "조합 수", "원천 거래수", "유효 정의", "지표 정의", "avg_R 의미",
    "train / OOS", "분산 칼럼", "안정성 플래그", "★경고1", "★경고2",
], "내용": [
    "2026-06-15",
    f"{len(M)} (k=4..16 전수 64839 중 OOS PF>1 통과)",
    f"{len(d)} (stage4d_honest, HONEST_STAGE=5 무게이트)",
    "OOS(2025-26) net PF > 1",
    "PF=sum(이익)/abs(sum(손실)) net_pnl기준. rPF=r_multiple기준(경로독립). win=승률%. avg_R=평균 r_multiple(R단위 기대값).",
    "avg_R = 거래당 평균 R배수 = 기대값(expectancy). 0보다 크면 R기준 우위.",
    "train=2023,2024 진입 / OOS=2025,2026 진입",
    "n23~n26=연도별 거래수, pf23~pf26=연도별 PF, yrs_present=PF계산가능 연도수, max_year_share=최다연도 거래비중",
    "both_oos_pf>1: 25·26 둘다>1 / all4yr_pf>1: 4연도 전부>1 / tiny2026_infl: 26년 소표본 인플레(n26<10 & pf26>3) 가짜의심",
    "전부 POST-HOC(슬롯 재배치 미반영). killzone∩atr∩volume_strict post-hoc OOS 1.746 → 실전 0.757 로 붕괴 실증됨.",
    "6.4만 조합 다중비교 산물 → OOS>1 는 우연/소표본/특정연도(주로2024)집중일 가능성 높음. 실전확정은 run_and_sweep 필수.",
]})

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    notes.to_excel(xw, sheet_name="notes", index=False)
    M.to_excel(xw, sheet_name="valid_213_combos", index=False)
    M[M["all4yr_pf>1"] == 1].to_excel(xw, sheet_name="all4yr_pf_gt1", index=False)
    M[(M.PF_tr > 1) & (M.pf25 > 1) & (M.pf26 > 1)].to_excel(xw, sheet_name="train_plus_both_oos", index=False)

print(f"저장 → {OUT}")
print(f"  valid_213_combos: {len(M)}행")
print(f"  all4yr_pf_gt1: {int((M['all4yr_pf>1']==1).sum())}행")
print(f"  train_plus_both_oos: {int(((M.PF_tr>1)&(M.pf25>1)&(M.pf26>1)).sum())}행")
print(f"  tiny2026_infl 플래그: {int(M['tiny2026_infl'].sum())}개")
print("\n[OOS 표본 큰 상위 10]")
c = ["combo", "k", "n", "PF", "win_pct", "avg_R", "n_oos", "PF_oos", "win_oos", "avgR_oos"]
print(M[c].head(10).to_string(index=False))
