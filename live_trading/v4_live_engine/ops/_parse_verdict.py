#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_today 출력파일을 인코딩-견고하게 읽어 ASCII 한줄요약 출력.
   usage: python _parse_verdict.py <verify_output.txt>
   stdout: verdict=PASS|FAIL|UNKNOWN live=<n> bt=<n> missing=<n>"""
import sys, re

p = sys.argv[1]
raw = open(p, "rb").read()
# BOM/인코딩 견고 디코드
if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
    t = raw.decode("utf-16", errors="replace")
else:
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        t = raw.decode("utf-8", errors="replace")

nlive = nbt = None
verdict = "UNKNOWN"
missing = 0
for l in t.splitlines():
    m = re.search(r"라이브\s+\S+\s+거래\s*:\s*(\d+)\s*건", l)
    if m:
        nlive = int(m.group(1))
    m = re.search(r"백테\s+거래.*?:\s*(\d+)\s*건", l)
    if m:
        nbt = int(m.group(1))
    if ("⊆" in l) or ("전부 백테" in l):          # ⊆
        verdict = "PASS"
    if ("파리티 위반" in l) or ("백테에 없는" in l) or ("백테에없음" in l):
        verdict = "FAIL"
        mm = re.search(r"거래:\s*\[(.*?)\]", l)
        if mm and mm.group(1).strip():
            missing = mm.group(1).count("(") or 1
print(f"verdict={verdict} live={nlive} bt={nbt} missing={missing}")
