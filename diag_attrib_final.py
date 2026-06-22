"""FINAL 런: 패치①이 라이브의 '정직한 같은-봉 진입'을 정말 버렸는지 검증.
핵심 질문: BEFORE Δ=0(같은봉) zone 들이 AFTER 에서
  (A) 더 늦은 봉(Δ≥1)에 재진입했나(=패치①이 살림) vs (B) 소멸했나.
라이브는 zone 생성 후 current_price 가 zone 재진입할 때만 잡으므로,
B(소멸=재진입 없음)는 라이브도 못 잡는다 → 패치①이 라이브를 과소모델링 안 함."""
import pandas as pd, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

b = pd.read_parquet("diag_candidates_full_before.parquet")
a = pd.read_parquet("diag_candidates_full_after.parquet")
b["zid"] = list(zip(b.symbol, b.zone_created_idx))
a["zid"] = list(zip(a.symbol, a.zone_created_idx))

b0 = b[b.delta == 0]                      # BEFORE 같은-봉(누수) 거래
b0_zids = set(b0.zid); a_zids = set(a.zid)
survived = b0_zids & a_zids               # AFTER 재진입 (패치①이 더 늦은봉에 살림)
vanished = b0_zids - a_zids               # AFTER 진입 없음 (재진입 자체가 없던 zone)

def met(df):
    rp = df.loc[df.r_multiple>0,"r_multiple"].sum(); rn = df.loc[df.r_multiple<0,"r_multiple"].sum()
    pf = rp/abs(rn) if rn else float('inf')
    return len(df), pf, 100*(df.r_multiple>0).mean(), df.r_multiple.sum()

print("="*72)
print(f"BEFORE 같은-봉(Δ=0) zone: {len(b0_zids)}")
print(f"  A 재진입(survived, 패치①이 honest 진입으로 살림): {len(survived)}  ({100*len(survived)/max(len(b0_zids),1):.1f}%)")
print(f"  B 소멸(vanished, 재진입 자체 없음 → 라이브도 못 잡음): {len(vanished)}  ({100*len(vanished)/max(len(b0_zids),1):.1f}%)")

van_b = b0[b0.zid.isin(vanished)]
sur_b = b0[b0.zid.isin(survived)]
print("\n[B 소멸 zone] BEFORE 성과 = 순수 룩어헤드 (라이브/패치② 모두 못 잡는 가짜):")
n,pf,wr,sr = met(van_b); print(f"  n={n} sumR={sr:.1f} R-PF={pf:.2f} win={wr:.1f}%")
print("[A 재진입 zone] BEFORE(같은봉가) 성과:")
n,pf,wr,sr = met(sur_b); print(f"  n={n} sumR={sr:.1f} R-PF={pf:.2f} win={wr:.1f}%")

sur_a = a[a.zid.isin(survived)]
print("\n[A 재진입 zone] AFTER 새 Δ분포 (몇 봉 뒤에 정직하게 잡혔나):")
print(sur_a.delta.value_counts().sort_index().head(8).to_string())

# 같은 zone: BEFORE(같은봉 누수가) vs AFTER(정직 진입) 성과
m = sur_b[["zid","r_multiple"]].rename(columns={"r_multiple":"r_b"}).merge(
    sur_a.groupby("zid",as_index=False).r_multiple.first().rename(columns={"r_multiple":"r_a"}),
    on="zid", how="inner")
print(f"\n[A zone] 같은 zone BEFORE→AFTER:  sumR {m.r_b.sum():.1f} → {m.r_a.sum():.1f}   평균R {m.r_b.mean():.3f} → {m.r_a.mean():.3f}")
print("="*72)
print("해석: B(소멸)는 라이브 current_price 도 재진입 없으면 못 잡음 → 패치②로도 회복 불가.")
print("      A(재진입)는 패치①이 이미 더 늦은 정직 봉에 살려둠 → 이게 0.98 안에 이미 포함.")
print("      => 패치②(intrabar)는 A의 '진입가'만 미세조정, 거래집합은 거의 동일 예상.")
