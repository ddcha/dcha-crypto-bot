import pandas as pd
import numpy as np

b = pd.read_parquet("diag_candidates_before.parquet")
a = pd.read_parquet("diag_candidates_after.parquet")

def metrics(df):
    rpos = df.loc[df.r_multiple > 0, "r_multiple"].sum()
    rneg = df.loc[df.r_multiple < 0, "r_multiple"].sum()
    pf = rpos / abs(rneg) if rneg != 0 else float("inf")
    wr = 100.0 * (df.r_multiple > 0).mean()
    return len(df), pf, wr, df.r_multiple.sum()

nb, pfb, wrb, srb = metrics(b)
na, pfa, wra, sra = metrics(a)

print("=" * 70)
print("PATCH① BEFORE vs AFTER (candidates 단계, R기반)")
print("=" * 70)
print(f"{'metric':<14}{'BEFORE':>14}{'AFTER':>14}{'Δ':>14}")
print(f"{'n_trades':<14}{nb:>14}{na:>14}{na-nb:>14}")
print(f"{'R-PF':<14}{pfb:>14.3f}{pfa:>14.3f}{pfa-pfb:>14.3f}")
print(f"{'winrate%':<14}{wrb:>14.1f}{wra:>14.1f}{wra-wrb:>14.1f}")
print(f"{'sumR':<14}{srb:>14.1f}{sra:>14.1f}{sra-srb:>14.1f}")

# Δ 분포 검증: AFTER 에 Δ=0 이 사라졌는지
print("\n[검증] AFTER Δ분포 (Δ=0 이 0 이어야 패치 정상):")
print(a.delta.value_counts().sort_index().head(8).to_string())

# A/B/C 추적: zone (symbol, zone_created_idx) 단위
b["zid"] = list(zip(b.symbol, b.zone_created_idx))
a["zid"] = list(zip(a.symbol, a.zone_created_idx))
b0 = b[b.delta == 0]              # 원래 Δ=0 이던 1408건
b0_zids = set(b0.zid)
a_zids = set(a.zid)

survived = b0_zids & a_zids       # 같은 zone 이 AFTER 에도 진입 (A: 이동)
vanished = b0_zids - a_zids       # AFTER 에 진입 없음 (B/C: 소멸)

print("\n" + "=" * 70)
print(f"원래 Δ=0 이던 zone: {len(b0_zids)}")
print(f"  A (이동, AFTER 재진입): {len(survived)}  ({100*len(survived)/max(len(b0_zids),1):.1f}%)")
print(f"  B/C (소멸):            {len(vanished)}  ({100*len(vanished)/max(len(b0_zids),1):.1f}%)")

# 이동한 zone 들의 새 Δ 분포
surv_a = a[a.zid.isin(survived)]
print(f"\n[A=이동] 재진입 zone 의 새 Δ 분포:")
print(surv_a.delta.value_counts().sort_index().head(10).to_string())

# 소멸한 zone 들이 BEFORE 에서 얼마나 벌던 거였나 (가짜 수익 크기)
van_b = b0[b0.zid.isin(vanished)]
surv_b0 = b0[b0.zid.isin(survived)]
print("\n" + "=" * 70)
print("소멸한(B/C) zone 의 BEFORE 성과 = '룩어헤드 수익'의 크기:")
print(f"  소멸 거래수: {len(van_b)}  sumR={van_b.r_multiple.sum():.1f}  "
      f"R-PF={van_b.loc[van_b.r_multiple>0,'r_multiple'].sum()/abs(van_b.loc[van_b.r_multiple<0,'r_multiple'].sum()):.3f}  "
      f"wr={100*(van_b.r_multiple>0).mean():.1f}%")
print(f"  (이동한 zone 의 BEFORE Δ=0 성과: sumR={surv_b0.r_multiple.sum():.1f} "
      f"wr={100*(surv_b0.r_multiple>0).mean():.1f}%)")

# 이동한 zone: BEFORE(Δ=0, 룩어헤드가) vs AFTER(Δ≥1, 정직가) 같은 zone 성과 비교
m = surv_b0[["zid","r_multiple"]].rename(columns={"r_multiple":"r_before"}).merge(
    surv_a.groupby("zid", as_index=False).r_multiple.first().rename(columns={"r_multiple":"r_after"}),
    on="zid", how="inner")
print("\n[이동 zone] 같은 zone, BEFORE(룩어헤드가) vs AFTER(정직가) 성과:")
print(f"  sumR: {m.r_before.sum():.1f} -> {m.r_after.sum():.1f}  (Δ={m.r_after.sum()-m.r_before.sum():.1f})")
print(f"  평균R: {m.r_before.mean():.3f} -> {m.r_after.mean():.3f}")
print("=" * 70)
