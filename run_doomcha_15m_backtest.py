"""둠챠 현재봉 정밀화(15m 재구성) 백테스트 — a_trend_align / a_room 만 정밀화.

- run_12atoms_one_backtest.py 와 동일 구성(12원자 OR, HONEST_STAGE=5)에
  DOOMCHA_15M=1 만 추가 → 진입봉 i 의 '진행중' 상태를 15m 누적으로 복원.
  · i-1(직전 종가확정봉)까지는 그대로, 현재봉 i 는 '진입가 첫 터치 15m봉(t)'까지만 누적.
  · t 이후 데이터는 일절 안 읽음 → 미래참조 0.
  · 오직 a_trend_align(trend_now) / a_room(pd_high/low_now) 만 override. 나머지 10원자 불변.
- 출력 폴더를 baseline(atoms_one_bt)과 분리 → verify_doomcha_15m.py 로 before/after 비교.

VS Code 에서 그대로 Run. (최초 1회 15m 데이터 다운로드 발생 — 시간 더 걸림)
"""
import os
import sys
import runpy

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "smc_crypto_stage4d_atomic_decomposition.py")

ATOMS = ["a_sweep", "a_volume", "a_pre_total_ge4", "a_sweep_count_2_4", "a_score_ge13",
         "a_wick_le_q1", "a_pre_total_ge1", "a_trend_align", "a_mss", "a_fvg", "a_overlap", "a_room"]

OUTDIR = os.path.join(ROOT, "stage4d_honest", "atoms_doomcha_15m")

os.environ["HONEST_STAGE"] = "5"                                  # 미래참조 제거(정직봉 i-1)
os.environ["DOOMCHA_15M"] = "1"                                   # ★ 현재봉 15m 재구성 ON
os.environ["ATOM_OR_LIST"] = ",".join(ATOMS)                      # 12원자 OR = baseline 과 동일 진입집합
os.environ["STAGE4D_DLCACHE"] = os.path.join(ROOT, "stage4d_honest", "_dlcache")
os.environ["STAGE4D_OUTDIR"] = OUTDIR
os.environ["PYTHONIOENCODING"] = "utf-8"

print("=" * 90)
print("둠챠 현재봉 정밀화 | 15m 재구성 | HONEST_STAGE=5 | DOOMCHA_15M=1")
print("정밀화 대상: a_trend_align(trend_now), a_room(pd_high/low_now) - 나머지 10원자 불변")
print("진입조건(OR, baseline 과 동일):")
for a in ATOMS:
    print("   -", a)
print("출력 폴더:", OUTDIR)
print("=" * 90)

runpy.run_path(SCRIPT, run_name="__main__")

print("\n완료 → 트레이드 로그:", os.path.join(OUTDIR, "stage4d_trades.csv"))
print("      baseline(atoms_one_bt) 과 verify_doomcha_15m.py 로 before/after 비교하세요.")
