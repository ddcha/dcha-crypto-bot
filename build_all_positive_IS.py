"""16원자 전 부분집합(k=2..16) IS(2023-24) 전수 → '양수' 조합 전부.
제약 없음: 설정/국면 혼합 자유, k 제한 없음. OOS(2025-26) 일절 미사용.
양수 정의: PF>1 (net_pnl 기준). avgR(r_multiple 평균)·rPF·승률 동봉.
IS 내부 분리: 2023·2024 각각 PF/avgR → both_years_pos = 두 해 다 PF>1 (IS-CV, OOS 미사용).
다중코어 병렬(k 단위). 이건 시작점(가설집합)이지 검증 아님.
"""
import os, itertools, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "stage4d_honest", "atoms_corr")
TR = os.path.join(CDIR, "stage4d_trades.csv")
OUT_CSV = os.path.join(CDIR, "all_positive_IS.csv")
OUT_XLSX = os.path.join(CDIR, "all_positive_IS.xlsx")
MIN_N = 15   # IS 표본 하한(이하 PF는 노이즈) — 컬럼 n으로 더 올려 필터 가능

_G = {}


def pf(s):
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return pos / neg if neg > 1e-9 else (np.inf if pos > 0 else 0.0)


def tb(c):
    return c.astype(str).str.strip().str.lower().map({"true": True, "false": False}).fillna(False)


def _init(Bmat, pnl, rmul, y23, y24, names):
    _G["B"] = Bmat; _G["pnl"] = pnl; _G["rmul"] = rmul
    _G["y23"] = y23; _G["y24"] = y24; _G["names"] = names


def _work(k):
    B = _G["B"]; pnl = _G["pnl"]; rmul = _G["rmul"]
    y23 = _G["y23"]; y24 = _G["y24"]; names = _G["names"]
    na = B.shape[0]
    out = []
    for combo in itertools.combinations(range(na), k):
        m = B[combo[0]].copy()
        for j in combo[1:]:
            m &= B[j]
        n = int(m.sum())
        if n < MIN_N:
            continue
        p = pnl[m]
        PF = pf(p)
        if PF <= 1.0:           # 양수 정의: net PF>1
            continue
        r = rmul[m]; r = r[~np.isnan(r)]
        m23 = m & y23; m24 = m & y24
        p23 = pnl[m23]; p24 = pnl[m24]
        r23 = rmul[m23]; r23 = r23[~np.isnan(r23)]
        r24 = rmul[m24]; r24 = r24[~np.isnan(r24)]
        out.append((
            "∩".join(names[i] for i in combo), k, n,
            round(PF, 3), round(float(r.mean()), 3) if len(r) else np.nan,
            round(100 * (p > 0).mean(), 1), round(pf(r), 3) if len(r) else np.nan,
            int(m23.sum()), int(m24.sum()),
            round(pf(p23), 3), round(pf(p24), 3),
            round(float(r23.mean()), 3) if len(r23) else np.nan,
            round(float(r24.mean()), 3) if len(r24) else np.nan,
        ))
    return out


def main():
    d = pd.read_csv(TR)
    acols = [c for c in d.columns if c.startswith("a_")]
    names = [c.replace("a_", "") for c in acols]
    Bmat = np.stack([tb(d[a]).to_numpy() for a in acols])
    pnl = pd.to_numeric(d["net_pnl"], errors="coerce").to_numpy(float)
    rmul = pd.to_numeric(d.get("r_multiple"), errors="coerce").to_numpy(float)
    yr = pd.to_datetime(d["entry_time"], errors="coerce").dt.year.to_numpy()
    IS = np.isin(yr, [2023, 2024])
    # IS로 마스크 한정
    Bmat = Bmat & IS
    y23 = (yr == 2023); y24 = (yr == 2024)
    tot = sum(1 for k in range(2, len(acols) + 1) for _ in itertools.combinations(range(len(acols)), k))
    print(f"[전 부분집합 IS 양수스캔] IS거래 {int(IS.sum())} (2023-24) | 원자 {len(acols)} | 조합 {tot} (k=2..16)")
    print(f"  양수=net PF>1, 표본 n>={MIN_N} | OOS 미사용\n")

    t0 = time.time()
    ncpu = max(1, (os.cpu_count() or 2))
    rows = []
    with ProcessPoolExecutor(max_workers=ncpu,
                             initializer=_init,
                             initargs=(Bmat, pnl, rmul, y23, y24, names)) as ex:
        for part in ex.map(_work, range(2, len(acols) + 1)):
            rows.extend(part)
    print(f"  스캔 {time.time()-t0:.1f}s ({ncpu}코어) → 양수 조합 {len(rows)}개\n")

    cols = ["combo", "k", "n", "PF", "avgR", "win", "rPF",
            "n23", "n24", "pf23", "pf24", "avgR23", "avgR24"]
    R = pd.DataFrame(rows, columns=cols)
    R["both_years_pos"] = ((R.pf23 > 1) & (R.pf24 > 1)).astype(int)
    R = R.sort_values(["n", "PF"], ascending=False).reset_index(drop=True)
    R.to_csv(OUT_CSV, index=False)

    print("차수별 양수 조합 수:")
    for k in range(2, len(acols) + 1):
        sub = R[R.k == k]
        if len(sub):
            print(f"  k={k:>2}: 양수 {len(sub):>4} | 두해다양수 {int(sub.both_years_pos.sum()):>4} | n최대 {int(sub.n.max())}")
    print(f"\n표본 하한별 양수 수: " + " ".join(f"n>={t}:{int((R.n>=t).sum())}" for t in (15, 20, 30, 50)))
    print(f"두 해 다 양수(IS-CV통과): {int(R.both_years_pos.sum())}개\n")

    both = R[R.both_years_pos == 1].sort_values(["n", "PF"], ascending=False)
    notes = pd.DataFrame({"항목": [
        "생성일", "스코프", "★OOS", "양수정의", "표본하한", "both_years_pos", "차수", "위상", "다음단계",
    ], "내용": [
        "2026-06-15", f"IS=2023-24, {int(IS.sum())}거래. 전 부분집합 k=2..16 전수.",
        "2025-26 일절 미참조. 여기서 OOS 안 봄.",
        "net_pnl PF>1. avgR=r_multiple 평균(R기대값). rPF=r기준 PF.",
        f"n>={MIN_N} (컬럼 n으로 상향필터 가능)",
        "2023 PF>1 AND 2024 PF>1 (IS 내부 교차검증, OOS 미사용). 한해운발 컷.",
        "k=조합 원자수(2~16). combo는 ∩ 구분.",
        "시작점(가설집합)일 뿐. 다중비교 큼 → 검증 아님.",
        "여기서 소수 후보 추려 동결 → 그때 처음 2025-26 1회 조회.",
    ]})
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
        notes.to_excel(xw, sheet_name="notes", index=False)
        R.to_excel(xw, sheet_name="all_positive_IS", index=False)
        both.to_excel(xw, sheet_name="both_years_pos_IS_CV", index=False)
    print(f"저장 → {OUT_CSV}\n       {OUT_XLSX}")
    print(f"  all_positive_IS {len(R)} / both_years_pos_IS_CV {len(both)}")
    print("\n[양수 + 두해다양수 중 표본 큰 상위 15]")
    show = ["combo", "k", "n", "PF", "avgR", "win", "n23", "n24", "pf23", "pf24"]
    print(both[show].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
