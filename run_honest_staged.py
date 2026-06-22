"""가드레일3: HONEST_STAGE 0..5 단계별 분리측정 러너.
모든 스테이지가 STAGE4D_DLCACHE 공유 → 동일 데이터로 before/after 정합성 보장.
각 스테이지 결과는 stage4d_honest/sN/ 에, 로그는 sN.log 에 저장.
누적 토글: 0=원본(누수포함) 1=S0 zone당봉배제 2=+S1 3=+S2 4=+S3 5=+S4."""
import os, sys, subprocess, time, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "smc_crypto_stage4d_atomic_decomposition.py")
DLCACHE = os.path.join(ROOT, "stage4d_honest", "_dlcache")
BASE_OUT = os.path.join(ROOT, "stage4d_honest")
os.makedirs(DLCACHE, exist_ok=True)

LABEL = {0: "원본(누수)", 1: "S0 zone당봉배제", 2: "+S1 rp/trend/atr",
         3: "+S2 confl/wick", 4: "+S3 mstate/h1choch", 5: "+S4 trade_tags"}

STAGES = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [0, 1, 2, 3, 4, 5]

for st in STAGES:
    outdir = os.path.join(BASE_OUT, f"s{st}")
    os.makedirs(outdir, exist_ok=True)
    env = dict(os.environ)
    env["HONEST_STAGE"] = str(st)
    env["STAGE4D_OUTDIR"] = outdir
    env["STAGE4D_DLCACHE"] = DLCACHE
    env["PYTHONIOENCODING"] = "utf-8"
    logfp = os.path.join(BASE_OUT, f"s{st}.log")
    t0 = time.time()
    print(f"\n{'='*70}\n[STAGE {st}] {LABEL[st]}  → {outdir}\n{'='*70}", flush=True)
    with open(logfp, "w", encoding="utf-8") as lf:
        p = subprocess.run([sys.executable, SCRIPT], env=env,
                           stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"[STAGE {st}] rc={p.returncode}  {time.time()-t0:.0f}s  log={logfp}", flush=True)

print("\nALL DONE", flush=True)
