"""12원자를 '하나의 백테스트' 안에서 각각 독립 진입조건(OR)으로 사용.

- 진입 후보가 잡히면 12원자 중 하나라도 True면 진입 통과
  = 서로 섞지 않은 12개 단독 조건의 합집합(OR).
- 체결된 모든 trade 에 12원자 상태가 컬럼으로 기록됨
  → 이후 trade 로그로 원자 시너지 분석용 데이터셋.
- HONEST_STAGE=5 : 미래참조 제거된 정직봉(i-1) 기준.

VS Code 에서 이 파일을 그대로 Run.
"""
import os
import runpy

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "smc_crypto_stage4d_atomic_decomposition.py")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

OUTDIR = os.path.join(ROOT, "stage4d_honest", "atoms_one_bt")

os.environ["HONEST_STAGE"] = "5"                                   # 미래참조 제거(정직봉 i-1)
os.environ["ATOM_OR_LIST"] = ",".join(ATOMS)                       # 12원자 OR = 12개 단독 진입조건
os.environ["STAGE4D_DLCACHE"] = os.path.join(ROOT, "stage4d_honest", "_dlcache")
os.environ["STAGE4D_OUTDIR"] = OUTDIR
os.environ["PYTHONIOENCODING"] = "utf-8"

print("=" * 90)
print("12원자 OR 진입조건 | 단일 백테스트 | HONEST_STAGE=5(정직봉)")
print("진입조건(OR, 하나라도 True면 통과):")
for a in ATOMS:
    print("   -", a)
print("출력 폴더:", OUTDIR)
print("=" * 90)

runpy.run_path(SCRIPT, run_name="__main__")

print("\n완료 → 트레이드 로그:", os.path.join(OUTDIR, "stage4d_trades.csv"))
print("      (각 행에 12원자 컬럼이 모두 기록되어 있음 — 원자 시너지 분석에 바로 사용)")
