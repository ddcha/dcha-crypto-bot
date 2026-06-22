"""교차검증용 통합 엑셀 + 원천 거래내역 정리.
시트: notes / trades_16atoms / atom_solo / corr_matrix / pairs_triples / high_order_k456 / real_and_sweep
출력: stage4d_honest/atoms_corr/atom_intersections_export.xlsx
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
OUT = os.path.join(CDIR, "atom_intersections_export.xlsx")

OLD12 = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]
NEW4 = ["a_killzone", "a_atr_expansion", "a_disp_strength", "a_volume_strict"]
CORE = ["symbol", "side", "entry_time", "exit_time", "year", "net_pnl", "r_multiple",
        "result", "exit_reason", "hold_bars", "tier", "grade", "score", "run_potential"]


def pf(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


d = pd.read_csv(TR)
acols = [c for c in d.columns if c.startswith("a_")]
if "year" not in d.columns:
    d["year"] = pd.to_datetime(d["entry_time"], errors="coerce").dt.year
pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
yr = d["year"].to_numpy()
te = np.isin(yr, [2025, 2026]); tr = np.isin(yr, [2023, 2024])

# trades 시트: 핵심컬럼 + 16원자(O/.)
present_core = [c for c in CORE if c in d.columns]
tdf = d[present_core].copy()
for a in acols:
    tdf[a] = np.where(tb(d[a]), "O", ".")

# atom_solo 시트
solo = []
for a in acols:
    m = tb(d[a]).to_numpy()
    if m.sum() == 0:
        continue
    solo.append(dict(atom=a, is_new=int(a in NEW4), freq_pct=round(100 * m.mean(), 1),
                     n=int(m.sum()), nOOS=int((m & te).sum()),
                     PF=round(pf(pnl[m]), 3), PF_off=round(pf(pnl[~m]), 3),
                     PF_train2324=round(pf(pnl[m & tr]), 3), PF_oos2526=round(pf(pnl[m & te]), 3),
                     rPF_oos2526=round(pf(rmul[m & te]), 3)))
solo_df = pd.DataFrame(solo).sort_values("PF_oos2526", ascending=False)

# corr matrix
B = pd.DataFrame({a: tb(d[a]).astype(int) for a in acols})
corr = B.corr().round(3)
corr.index.name = "atom"

# notes
notes = pd.DataFrame({"항목": [
    "생성일", "데이터", "거래수", "원자수(기존12+신규4)",
    "base 전체PF", "base OOS(2025-26)PF", "base train(2023-24)PF",
    "신규원자", "PF정의", "OOS정의",
    "룩어헤드검증", "주의1", "주의2", "주의3", "주의4(중요)",
], "내용": [
    "2026-06-15", "9코인 H4, 2022~2026, HONEST_STAGE=5(무게이트)", str(len(d)), str(len(acols)),
    round(pf(pnl), 3), round(pf(pnl[te]), 3), round(pf(pnl[tr]), 3),
    ", ".join(NEW4),
    "PF=sum(이익)/abs(sum(손실)). net_pnl기준. rPF=r_multiple기준(경로독립).",
    "OOS=2025,2026 진입거래 / train=2023,2024",
    "신규4원자 정적인덱스감사+i-1정직봉+격리 before/after(거래셋·기존12원자 100%동일) 3중통과",
    "교집합표는 POST-HOC(슬롯재배치 미반영) → 실전과 다를 수 있음. 실전확정은 real_and_sweep 시트 참고.",
    "고차(4+)교집합 OOS>1 다수는 14196조합 다중비교+소표본(nOOS 14~50) 과적합 가능성 높음.",
    "base OOS PF<1(0.615): 이 구성(USE_*필터 off, 원자 로그) 자체가 OOS 손실. 라이브/FINAL.py와 직접비교 금지.",
    "POST-HOC vs 실전 괴리 실증: killzone∩atr_expansion∩volume_strict = post-hoc OOS 1.746(n65) → 실전 0.757(n236). "
    "post-hoc 소표본 OOS>1은 실전 슬롯재배치시 붕괴. real_and_sweep 시트가 진짜 수치. 실전 OOS 최고 0.825(여전히<1).",
]})

# pairs_triples / high_order
ptp = os.path.join(CDIR, "intersections_scan.csv")
hip = os.path.join(CDIR, "intersections_hi_scan.csv")
pt_df = pd.read_csv(ptp) if os.path.exists(ptp) else pd.DataFrame()
hi_df = pd.read_csv(hip) if os.path.exists(hip) else pd.DataFrame()

# real AND sweep (있으면)
real_df = pd.DataFrame()
rp = os.path.join(ROOT, "stage4d_honest", "and_sweep", "sweep_file_and_combos_batch1.txt.csv")
if os.path.exists(rp):
    real_df = pd.read_csv(rp)

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    notes.to_excel(xw, sheet_name="notes", index=False)
    tdf.to_excel(xw, sheet_name="trades_16atoms", index=False)
    solo_df.to_excel(xw, sheet_name="atom_solo", index=False)
    corr.to_excel(xw, sheet_name="corr_matrix")
    if len(pt_df):
        pt_df.to_excel(xw, sheet_name="pairs_triples", index=False)
    if len(hi_df):
        hi_df.to_excel(xw, sheet_name="high_order_k456", index=False)
    if len(real_df):
        real_df.to_excel(xw, sheet_name="real_and_sweep", index=False)

print(f"엑셀 저장 → {OUT}")
print(f"  시트: notes / trades_16atoms({len(tdf)}) / atom_solo({len(solo_df)}) / corr_matrix({len(corr)}) "
      f"/ pairs_triples({len(pt_df)}) / high_order_k456({len(hi_df)}) / real_and_sweep({len(real_df)})")
