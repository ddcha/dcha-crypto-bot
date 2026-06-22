#!/usr/bin/env python3
"""
yahoo_index_v26 → yahoo_commodity_v26 자동 변환 스크립트

사용법:
  python3 convert_index_to_commodity.py
  
입력:  yahoo_index_v26_stage4k_v19b.py (같은 폴더)
출력:  yahoo_commodity_v26_stage4k_v19b.py (같은 폴더)

변경:
  1. 헤더 주석 (INDEX → COMMODITY)
  2. INDEX_SYMBOLS dict (8 indices → 14 commodities)
  3. SYMBOL_TF_MAP (모두 2h/1h → dual-TF Slow 9 12h/4h + Fast 5 4h/1h)
  4. PHASE_A_RISK / PHASE_B_RISK (14자산용, v2.0 의 Avg R 차등 배분)
  5. resample_ohlcv (cumcount 방식 → floor 방식, 24/7 데이터 호환)
  6. OUTDIR (yahoo_commodity_v26_stage4k_v19b_outputs)
  7. MIN_SCORE (8.5 → 7.5 - 원자재 변동성 높음)
  8. (선택) USE_RTH_ONLY=False 명시
"""
from pathlib import Path
import re

INDEX_FILE = Path("yahoo_index_v26_stage4k_v19b.py")
COMMODITY_FILE = Path("yahoo_commodity_v26_stage4k_v19b.py")

# ─────────────────────────────────────
# [1] 자산 매핑
# ─────────────────────────────────────
COMMODITY_SYMBOLS_DICT = '''INDEX_SYMBOLS = {
    # 🐢 Slow Group (12h/4h) - 9 자산 (귀금속 4 + 에너지 3 + 소프트 2)
    "GC":  "GC=F",   # 금
    "SI":  "SI=F",   # 은
    "PL":  "PL=F",   # 백금
    "PA":  "PA=F",   # 팔라듐
    "CL":  "CL=F",   # WTI 원유
    "NG":  "NG=F",   # 천연가스
    "HO":  "HO=F",   # 난방유
    "SB":  "SB=F",   # 설탕
    "CC":  "CC=F",   # 코코아
    # 🐇 Fast Group (4h/1h) - 5 자산 (산업금속 2 + 곡물 2 + 소프트 1)
    "HG":  "HG=F",   # 구리
    "ALI": "ALI=F",  # 알루미늄
    "ZS":  "ZS=F",   # 대두
    "ZW":  "ZW=F",   # 밀
    "KC":  "KC=F",   # 커피
}'''

COMMODITY_TF_MAP = '''SYMBOL_TF_MAP = {
    # Slow: 12h HTF / 4h LTF (9자산)
    "GC":  ("12h", "4h"), "SI":  ("12h", "4h"),
    "PL":  ("12h", "4h"), "PA":  ("12h", "4h"),
    "CL":  ("12h", "4h"), "NG":  ("12h", "4h"),
    "HO":  ("12h", "4h"), "SB":  ("12h", "4h"),
    "CC":  ("12h", "4h"),
    # Fast: 4h HTF / 1h LTF (5자산)
    "HG":  ("4h", "1h"), "ALI": ("4h", "1h"),
    "ZS":  ("4h", "1h"), "ZW":  ("4h", "1h"),
    "KC":  ("4h", "1h"),
}'''

COMMODITY_PHASE_A = '''PHASE_A_RISK = {
    # 🐢 Slow Group (9자산) - v2.0 Avg R 차등 배분
    "GC":   0.020,   # 메인 (PF 14.72, Avg R 1.52)
    "SI":   0.010,
    "PL":   0.010,
    "PA":   0.005,   # 변동성 극심
    "CL":   0.015,   # Avg R 2.28 🏆
    "NG":   0.005,   # 변동성 극심
    "HO":   0.010,
    "SB":   0.010,
    "CC":   0.0075,  # Avg R 0.96
    # 🐇 Fast Group (5자산)
    "HG":   0.0075,  # MDD -2.62%
    "ALI":  0.0075,
    "ZS":   0.0075,  # MDD -2.33%
    "ZW":   0.010,   # 안정 (PF 8.60, MDD -1.10%)
    "KC":   0.010,
}
# 합: 13.25%'''

COMMODITY_PHASE_B = '''PHASE_B_RISK = {
    # Phase B: Phase A 의 50%
    "GC":   0.010, "SI":   0.005, "PL":   0.005, "PA":   0.0025,
    "CL":   0.0075, "NG":   0.0025, "HO":   0.005,
    "SB":   0.005, "CC":   0.00375,
    "HG":   0.00375, "ALI":  0.00375, "ZS":   0.00375,
    "ZW":   0.005, "KC":   0.005,
}'''

# 원자재 v2.0 의 resample_ohlcv (24/7 데이터, floor 방식)
COMMODITY_RESAMPLE = '''def resample_ohlcv(df_h1, rule):
    """
    원자재 24/7 데이터용 - floor 방식 (timezone-aware bin 경계).
    rule:
      - '4h'  → 4시간 블록
      - '12h' → 12시간 블록
      - '1D'  → 일단위
    """
    df = df_h1.copy().sort_values("timestamp").reset_index(drop=True)
    if rule.endswith("h"):
        hours = int(rule[:-1])
        df["block_ts"] = df["timestamp"].dt.floor(f"{hours}h")
    elif rule.endswith("D") or rule.endswith("d"):
        df["block_ts"] = df["timestamp"].dt.floor("1D")
    else:
        raise ValueError(f"Unsupported resample rule: {rule}")
    agg = (
        df.groupby("block_ts", as_index=False)
        .agg(
            timestamp=("timestamp", "last"),
            timestamp_ny=("timestamp_ny", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    )
    return agg.sort_values("timestamp").reset_index(drop=True)'''


def convert():
    if not INDEX_FILE.exists():
        print(f"ERROR: {INDEX_FILE} 가 같은 폴더에 없음")
        return False
    
    src = INDEX_FILE.read_text()
    
    # [1] 헤더 주석
    src = src.replace(
        "# YAHOO INDEX FUTURES BACKTEST — v2.6 STAGE 4K BOOST15 + v19b RP_BOOST",
        "# YAHOO COMMODITY FUTURES BACKTEST — v2.6 STAGE 4K BOOST15 + v19b RP_BOOST",
    )
    src = src.replace(
        "# [v25 유지 (vs v24_final)]",
        "# [v26 - 14자산 dual-TF (Slow 9 + Fast 5)]",
    )
    
    # [2] INDEX_SYMBOLS 교체
    pattern = re.compile(
        r'INDEX_SYMBOLS\s*=\s*\{[^}]+\}',
        flags=re.DOTALL,
    )
    src = pattern.sub(COMMODITY_SYMBOLS_DICT, src, count=1)
    
    # [3] SYMBOL_TF_MAP 교체
    pattern = re.compile(
        r'SYMBOL_TF_MAP\s*=\s*\{[^}]+\}',
        flags=re.DOTALL,
    )
    src = pattern.sub(COMMODITY_TF_MAP, src, count=1)
    
    # [4] PHASE_A_RISK 교체
    pattern = re.compile(
        r'PHASE_A_RISK\s*=\s*\{[^}]+\}',
        flags=re.DOTALL,
    )
    src = pattern.sub(COMMODITY_PHASE_A, src, count=1)
    
    # [5] PHASE_B_RISK 교체
    pattern = re.compile(
        r'PHASE_B_RISK\s*=\s*\{[^}]+\}',
        flags=re.DOTALL,
    )
    src = pattern.sub(COMMODITY_PHASE_B, src, count=1)
    
    # [6] resample_ohlcv 교체 (cumcount 방식 → floor 방식)
    pattern = re.compile(
        r'def resample_ohlcv\(df_h1, rule\):.*?return agg\.sort_values\("timestamp"\)\.reset_index\(drop=True\)',
        flags=re.DOTALL,
    )
    src = pattern.sub(COMMODITY_RESAMPLE, src, count=1)
    
    # [7] OUTDIR
    src = src.replace(
        'OUTDIR = Path("yahoo_index_v26_stage4k_v19b_outputs")',
        'OUTDIR = Path("yahoo_commodity_v26_stage4k_v19b_outputs")',
    )
    src = src.replace(
        'OUTDIR = Path("yahoo_index_v25_stage4k_outputs")',
        'OUTDIR = Path("yahoo_commodity_v26_stage4k_v19b_outputs")',
    )
    
    # [8] MIN_SCORE 8.5 → 7.5 (원자재 변동성 높음)
    src = src.replace("MIN_SCORE = 8.5", "MIN_SCORE = 7.5")
    
    # [9] MAX_TOTAL_RISK 0.08 → 0.1325 (14자산 합)
    src = re.sub(
        r'MAX_TOTAL_RISK\s*=\s*0\.0[0-9]+',
        'MAX_TOTAL_RISK = 0.1325',
        src,
    )
    
    # [10] 기타 텍스트
    src = src.replace("YAHOO INDEX", "YAHOO COMMODITY")
    src = src.replace("8 indices", "14 commodities (Slow 9 + Fast 5)")
    
    # 결과 저장
    COMMODITY_FILE.write_text(src)
    print(f"✓ {COMMODITY_FILE} 생성됨 ({len(src)} bytes)")
    print(f"  변경 항목: 자산 dict, TF map, PHASE risk, resample, OUTDIR, MIN_SCORE, MAX_TOTAL_RISK")
    print(f"  4K layer (atomic 12 + WIN69 + tier_4h + 4J + sentiment + v19b) 그대로 유지")
    return True


if __name__ == "__main__":
    convert()
