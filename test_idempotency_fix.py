# 엔진 멱등성 검증: 하베스트 리셋 없이 같은 prepared 2번 호출 → 동일해야 (픽스 확인)
import os
os.environ.setdefault("OB_MODE", "engulf"); os.environ.setdefault("DISP_ATR_MULT", "1.3")
os.environ.setdefault("USE_H1_REFINE", "1"); os.environ.setdefault("HONEST_STAGE", "5")
os.environ["ATOM_AND_LIST"] = ""; os.environ["ATOM_OR_LIST"] = ""
for _k in ("ATOM_ANYOTHER_LIST", "COMBO_KEY", "ATOM_GATE_RULE", "COMBO_UNION_JSON", "USE_COMBO_UNION"):
    os.environ.pop(_k, None)
import pandas as pd
from smc_stage4d.data import download_symbol_data
from smc_stage4d.structures import apply_indicators_and_build
import smc_stage4d.simulation as sim
from smc_stage4d.simulation import generate_candidates_from_prepared

SYMS = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]   # 멱등성은 심볼별 독립 → 3개로 증명 충분
sim.USE_COMBO_UNION = False
prepared = {s: apply_indicators_and_build(download_symbol_data(s)) for s in SYMS}

def cand_keys(p):
    c = generate_candidates_from_prepared(p)["candidates"]
    if len(c) == 0:
        return 0, set()
    et = pd.to_datetime(c["entry_time"], utc=True).astype(str)
    return len(c), set(et.tolist())

print("\n=== 엔진 멱등성 (리셋 없이 2회 호출) ===")
ok = True
for s in SYMS:
    n1, k1 = cand_keys(prepared[s])   # 1st
    n2, k2 = cand_keys(prepared[s])   # 2nd (리셋 없음)
    same = (n1 == n2) and (k1 == k2)
    ok &= same
    print(f"  {s}: 1차 {n1} / 2차 {n2} | 키 대칭차 {len(k1 ^ k2)} → {'OK(멱등)' if same else 'FAIL(비멱등)'}")
print("\n[결과]", "✅ 엔진 멱등성 복원 — 픽스 작동" if ok else "❌ 여전히 비멱등 — 추가 잔존상태 존재")
