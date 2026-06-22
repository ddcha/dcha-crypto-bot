import re, hashlib, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

files = {
    'mtf':  'smc_crypto_stage4l_redist_h1choch_v3_conservative_mtf_fill.py',
    'am40': 'smc_crypto_stage4l_conservative_AM40_15m.py',
    'lb5':  'smc_crypto_stage4l_FINAL_LB5.py',
}
PATCH = re.compile(r'_PATCH1_ON|_leak1|PATCH①|_d_leak1|_os_p1|RUN_TAG|DIAG_STOP|diag_candidates|_dump_|_sys_diag|_os_diag|build_structures\._printed|\[PHASE 1-1\]|\[LEAK-1|ZONE-PARAM')

bodies = {}
for k, fp in files.items():
    src = open(fp, encoding='utf-8', errors='replace').read().splitlines()
    out = []; inside = False
    for l in src:
        if l.startswith('def generate_candidates_from_prepared'):
            inside = True
        elif inside and l.startswith('def '):
            break
        if inside:
            out.append(l)
    clean = [l for l in out if not PATCH.search(l)]
    bodies[k] = '\n'.join(clean)
    print(f"{k:5s}: 원본 {len(out):4d}줄, 내패치제외 {len(clean):4d}줄, md5={hashlib.md5(bodies[k].encode()).hexdigest()}")

print("---")
print("mtf == am40 :", bodies['mtf'] == bodies['am40'])
print("mtf == lb5  :", bodies['mtf'] == bodies['lb5'])
print("am40== lb5  :", bodies['am40'] == bodies['lb5'])

# 다르면 실제 차이 라인 출력
import difflib
for a, b in [('mtf','am40'), ('mtf','lb5')]:
    if bodies[a] != bodies[b]:
        print(f"\n### {a} vs {b} 함수내 실제 차이 ###")
        for line in difflib.unified_diff(bodies[a].splitlines(), bodies[b].splitlines(), lineterm='', n=0):
            if line.startswith(('+','-')) and not line.startswith(('+++','---')):
                print(line)
