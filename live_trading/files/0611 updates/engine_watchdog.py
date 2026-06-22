from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("runtime_state.json")
WATCHDOG_SLEEP_SECONDS = 10

# ★★★ Stage 4L 패치 (May 03) ★★★
# 90 → 900 (15분)
# 이유: 9코인 zone cache 첫 빌드 ~ 10분 소요 (590s 측정).
# 90초 timeout 이면 zone cache 빌드 중 watchdog 가 main 을 SIGKILL.
# 4월 어제 4L SIGKILL 4번의 진짜 원인 = 이 timeout (메모리/4L 코드 무관).
ENGINE_STALL_SECONDS = 1800

# ★★★ 좀비 누적 방지 패치 (May 19) ★★★
# 5/15~5/19 좀비 100개+ 누적 사고 원인:
#   1) kill_engine_if_exists() 가 SIGKILL 만 보내고 silent fail
#   2) D 상태 (uninterruptible sleep) 프로세스가 안 죽음
#   3) 안 죽었는데도 새 main.py spawn → 좀비 누적
#   4) waitpid 없음 → reaping 실패 → defunct
#   5) RAM/swap 폭증 → 전체 시스템 마비
#
# 추가 패치 4가지:
#   B-1) kill_engine_if_exists() : SIGTERM → 대기 → SIGKILL fallback + waitpid
#   B-2) start_engine() : spawn 후 PID 검증 강화
#   D-1) 1시간 내 5회 spawn 시 watchdog 자동 중단 (run-away halt)
#   D-2) 모든 실패에 명시적 로깅 (silent 제거)
KILL_SIGTERM_WAIT_SECONDS  = 5.0   # SIGTERM 후 대기 시간
KILL_CHECK_INTERVAL        = 0.5
SPAWN_GUARD_WINDOW_SECONDS = 3600  # 1시간 window
SPAWN_GUARD_MAX_COUNT      = 5     # window 내 5회 spawn 허용
LOG_FILE                   = Path("logs") / "watchdog.log"

STARTUP_STDOUT_FILE = Path("watchdog_main_stdout.log")
STARTUP_STDERR_FILE = Path("watchdog_main_stderr.log")

# ★★★ 단일 인스턴스 보장 패치 (Jun 11) ★★★
# 6/10 watchdog 이중 실행 사고 원인:
#   - systemd watchdog(절대경로) + 수동/control_panel watchdog(상대경로) 공존
#   - KillMode=control-group 은 systemd 자기 cgroup 만 정리 → 외부 실행분은 못 잡음
#   - 두 watchdog 이 같은 state 파일 보면서 각자 main.py spawn
#     → spawn count 가 서로 따로(5/5 vs 4/5) → 중복 spawn → RUNAWAY 연쇄
#     → systemd restart counter 22회 누적
# 해결:
#   E-1) flock 기반 단일 인스턴스 lock — 두 번째 watchdog 은 즉시 종료
#   E-2) spawn 직전 떠돌이(stray) main.py 전부 정리 — 중복 main 원천 차단
WATCHDOG_LOCK_FILE = Path("watchdog.lock")
_lock_fd = None  # lock 파일 핸들 (프로세스 살아있는 동안 유지해야 lock 유지됨)

try:
    import fcntl  # Linux 전용 (서버는 Ubuntu)
except Exception:
    fcntl = None


# Telegram alert (실패 시에도 watchdog 영향 X)
try:
    from telegram_utils import send_telegram_message as _tg_send  # type: ignore
except Exception:
    def _tg_send(*args, **kwargs):  # type: ignore
        return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    """watchdog 전용 로그 + stdout 동시 출력. 절대 raise 안 함."""
    line = f"[{utc_now_iso()}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _tg_alert(msg: str) -> None:
    """Telegram 알림. 실패해도 watchdog 영향 X."""
    try:
        _tg_send(f"⚠️ WATCHDOG: {msg}")
    except Exception:
        pass


def acquire_single_instance_lock() -> bool:
    """
    [PATCHED Jun 11 / E-1]
    flock 으로 watchdog 단일 인스턴스 보장.
    반환: True = lock 획득 (내가 유일한 watchdog).
          False = 이미 다른 watchdog 이 lock 보유 중 → 호출측에서 즉시 종료해야 함.
    fcntl 미지원(윈도우 등) 환경에서는 lock 없이 True (서버는 Linux 라 항상 작동).
    """
    global _lock_fd
    if fcntl is None:
        _log("single-instance lock: fcntl unavailable — skipping (non-Linux?)")
        return True
    try:
        base_dir = Path(__file__).resolve().parent
        lock_path = base_dir / WATCHDOG_LOCK_FILE
        _lock_fd = open(lock_path, "w")
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # lock 획득 성공 — 내 pid 기록 (디버깅용, lock 자체는 flock 이 보장)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except BlockingIOError:
        return False
    except Exception as e:
        # lock 시스템 자체가 실패하면 — 안전하게 lock 없이 진행하되 크게 로그
        _log(f"single-instance lock: unexpected error err={e} — proceeding WITHOUT lock")
        _tg_alert(f"watchdog lock 시스템 오류 (lock 없이 가동): {e}")
        return True


def _kill_pid_graceful(pid: int, label: str) -> bool:
    """SIGTERM → 대기 → SIGKILL. True = 죽음/원래없음."""
    if not is_pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
        _log(f"{label}: SIGTERM sent to pid={pid}")
    except ProcessLookupError:
        _try_reap(pid)
        return True
    except Exception as e:
        _log(f"{label}: SIGTERM error pid={pid} err={e}")

    elapsed = 0.0
    while elapsed < KILL_SIGTERM_WAIT_SECONDS:
        time.sleep(KILL_CHECK_INTERVAL)
        elapsed += KILL_CHECK_INTERVAL
        if not is_pid_alive(pid):
            _try_reap(pid)
            return True

    try:
        os.kill(pid, signal.SIGKILL)
        _log(f"{label}: SIGKILL sent to pid={pid}")
    except ProcessLookupError:
        _try_reap(pid)
        return True
    except Exception as e:
        _log(f"{label}: SIGKILL failed pid={pid} err={e}")
        return False

    time.sleep(1.0)
    _try_reap(pid)
    return not is_pid_alive(pid)


def _kill_stray_main_processes(exclude_pid: int | None = None) -> None:
    """
    [PATCHED Jun 11 / E-2]
    떠돌이 main.py 프로세스 전부 정리 (exclude_pid 제외).
    watchdog 이중 실행 등으로 추적 안 되는 main 이 남아
    중복 주문을 낼 위험을 원천 차단한다.
    """
    try:
        out = subprocess.run(
            ["pgrep", "-f", r"bybit_bot/main\.py"],
            capture_output=True, text=True,
        )
        pids = []
        for tok in out.stdout.split():
            try:
                p = int(tok)
                if p != os.getpid():
                    pids.append(p)
            except Exception:
                continue
    except Exception as e:
        _log(f"stray-main sweep: pgrep failed err={e}")
        return

    for p in pids:
        if exclude_pid is not None and p == int(exclude_pid):
            continue
        _log(f"stray-main sweep: found untracked main.py pid={p} — killing")
        _tg_alert(f"떠돌이 main.py 발견 pid={p} — 정리합니다 (중복 주문 방지)")
        _kill_pid_graceful(p, "stray-main sweep")


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def ensure_system_state(state: dict) -> dict:
    if "system" not in state or not isinstance(state["system"], dict):
        state["system"] = {}
    system = state["system"]
    system.setdefault("watchdog_enabled", True)
    system.setdefault("watchdog_running", False)
    system.setdefault("watchdog_pid", None)
    system.setdefault("watchdog_last_check", None)
    system.setdefault("engine_running", False)
    system.setdefault("engine_pid", None)
    system.setdefault("engine_started_at", None)
    system.setdefault("engine_stopped_at", None)
    system.setdefault("last_loop_time", None)
    system.setdefault("stop_requested", False)
    system.setdefault("last_action", None)
    system.setdefault("last_error", None)
    return system


def is_pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def is_engine_stalled(system: dict) -> bool:
    if not system.get("engine_running", False):
        return True

    pid = system.get("engine_pid")
    if not is_pid_alive(pid):
        return True

    last_loop = parse_iso(system.get("last_loop_time"))
    if last_loop is None:
        return False

    delta = (datetime.now(timezone.utc) - last_loop).total_seconds()
    return delta > ENGINE_STALL_SECONDS


def _try_reap(pid: int) -> None:
    """좀비 reaping. ECHILD 또는 자식 아님은 정상."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def kill_engine_if_exists(system: dict) -> bool:
    """
    [PATCHED May 19]
    engine 강제 종료 - SIGTERM 우선, 안 죽으면 SIGKILL.
    반환: True = 죽었거나 원래 없었음. False = 죽이기 실패.
    silent 아님. 모든 실패는 로그 + 텔레그램 알림.
    """
    raw_pid = system.get("engine_pid")
    if not is_pid_alive(raw_pid):
        return True

    try:
        pid = int(raw_pid)
    except Exception:
        _log(f"kill_engine: invalid pid={raw_pid!r}")
        return True

    # 1단계: SIGTERM (graceful)
    try:
        os.kill(pid, signal.SIGTERM)
        _log(f"kill_engine: SIGTERM sent to pid={pid}")
    except ProcessLookupError:
        _log(f"kill_engine: pid={pid} not found at SIGTERM (already dead)")
        _try_reap(pid)
        return True
    except PermissionError as e:
        _log(f"kill_engine: PermissionError on SIGTERM pid={pid} err={e}")
        _tg_alert(f"권한 부족으로 engine kill 불가 pid={pid}")
        return False
    except Exception as e:
        _log(f"kill_engine: unexpected error on SIGTERM pid={pid} err={e}")

    # 2단계: 죽었는지 polling 대기
    elapsed = 0.0
    while elapsed < KILL_SIGTERM_WAIT_SECONDS:
        time.sleep(KILL_CHECK_INTERVAL)
        elapsed += KILL_CHECK_INTERVAL
        if not is_pid_alive(pid):
            _log(f"kill_engine: pid={pid} died after SIGTERM in {elapsed:.1f}s")
            _try_reap(pid)
            return True

    # 3단계: 그래도 살아있으면 SIGKILL
    _log(f"kill_engine: pid={pid} survived SIGTERM after {elapsed:.1f}s, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        _try_reap(pid)
        return True
    except Exception as e:
        _log(f"kill_engine: SIGKILL failed pid={pid} err={e}")
        _tg_alert(f"engine SIGKILL 실패 pid={pid} err={e}")
        return False

    # SIGKILL 후 짧게 대기
    time.sleep(1.0)
    _try_reap(pid)

    if is_pid_alive(pid):
        _log(f"kill_engine: pid={pid} STILL ALIVE after SIGKILL (D state?)")
        _tg_alert(f"engine pid={pid} 가 SIGKILL 후에도 살아있음 (D state 의심)")
        return False

    _log(f"kill_engine: pid={pid} killed via SIGKILL")
    return True


def start_engine() -> int | None:
    """
    [PATCHED May 19]
    main.py spawn. 검증 + 명시 로그.
    """
    try:
        creationflags = 0
        base_dir = Path(__file__).resolve().parent

        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        stdout_f = open(base_dir / STARTUP_STDOUT_FILE, "a", encoding="utf-8")
        stderr_f = open(base_dir / STARTUP_STDERR_FILE, "a", encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, str(base_dir / "main.py")],
            cwd=str(base_dir),
            creationflags=creationflags,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
        )
        _log(f"start_engine: spawned pid={proc.pid}")
        return proc.pid

    except Exception as e:
        _log(f"start_engine: FAILED err={e}")
        _tg_alert(f"engine 시작 실패: {e}")
        return None


def _prune_spawn_history(history: deque, now_ts: float) -> None:
    """SPAWN_GUARD_WINDOW_SECONDS 보다 오래된 항목 제거."""
    cutoff = now_ts - SPAWN_GUARD_WINDOW_SECONDS
    while history and history[0] < cutoff:
        history.popleft()


def main() -> None:
    # ★ E-1 패치: 단일 인스턴스 lock — 두 번째 watchdog 은 즉시 종료
    if not acquire_single_instance_lock():
        _log(f"another watchdog already holds the lock — exiting (pid={os.getpid()})")
        _tg_alert(f"watchdog 중복 실행 시도 감지 (pid={os.getpid()}) — 기존 인스턴스 유지, 신규는 종료")
        sys.exit(0)  # 정상 종료 (Restart=on-failure 라 systemd 도 재시도 안 함)

    _log(f"watchdog started pid={os.getpid()} stall_threshold={ENGINE_STALL_SECONDS}s "
         f"spawn_guard={SPAWN_GUARD_MAX_COUNT}/{SPAWN_GUARD_WINDOW_SECONDS}s "
         f"single_instance_lock=acquired")

    # ★ E-2 패치: 시작 시 떠돌이 main 정리 (현재 추적 중인 engine_pid 는 보존)
    try:
        _state0 = load_state()
        _sys0 = ensure_system_state(_state0)
        _tracked = _sys0.get("engine_pid")
        _kill_stray_main_processes(exclude_pid=int(_tracked) if _tracked else None)
    except Exception as e:
        _log(f"startup stray sweep error: {e}")

    # ★ D 패치: spawn 이력 추적 (1시간 window)
    spawn_history: deque[float] = deque()
    halted_due_to_runaway = False

    while True:
        try:
            state = load_state()
            system = ensure_system_state(state)

            system["watchdog_running"] = True
            system["watchdog_pid"] = os.getpid()
            system["watchdog_last_check"] = utc_now_iso()
            save_state(state)

            if not bool(system.get("watchdog_enabled", True)):
                time.sleep(WATCHDOG_SLEEP_SECONDS)
                continue

            if bool(system.get("stop_requested", False)):
                time.sleep(WATCHDOG_SLEEP_SECONDS)
                continue

            # ★ D 패치: runaway 상태면 spawn 멈춤
            if halted_due_to_runaway:
                time.sleep(WATCHDOG_SLEEP_SECONDS)
                continue

            if is_engine_stalled(system):
                # ★ D 패치: spawn 이력 정리
                now_ts = time.time()
                _prune_spawn_history(spawn_history, now_ts)

                # ★ D 패치: 1시간 5회 초과면 watchdog 자체 중단
                if len(spawn_history) >= SPAWN_GUARD_MAX_COUNT:
                    _log(f"RUNAWAY DETECTED: {len(spawn_history)} spawns in last "
                         f"{SPAWN_GUARD_WINDOW_SECONDS}s — halting auto-spawn")
                    _tg_alert(
                        f"watchdog runaway 감지 — 1시간 내 spawn {len(spawn_history)}회. "
                        f"자동 spawn 중단. 수동 점검 필요."
                    )
                    state = load_state()
                    system = ensure_system_state(state)
                    system["last_error"] = "watchdog_runaway_halt"
                    system["last_action"] = "WATCHDOG RUNAWAY HALT"
                    save_state(state)
                    halted_due_to_runaway = True
                    time.sleep(WATCHDOG_SLEEP_SECONDS)
                    continue

                # ★ B 패치: 강화된 kill
                kill_ok = kill_engine_if_exists(system)
                if not kill_ok:
                    _log("engine kill failed — skipping spawn this cycle")
                    state = load_state()
                    system = ensure_system_state(state)
                    system["last_error"] = "engine_kill_failed_skip_spawn"
                    save_state(state)
                    time.sleep(WATCHDOG_SLEEP_SECONDS)
                    continue

                # ★ E-2 패치: spawn 직전 떠돌이 main 전부 정리 (중복 주문 원천 차단)
                _kill_stray_main_processes(exclude_pid=None)

                # ★ D 패치: spawn 기록 + 새 engine 시작
                spawn_history.append(now_ts)
                _log(f"spawn count in last {SPAWN_GUARD_WINDOW_SECONDS}s = "
                     f"{len(spawn_history)}/{SPAWN_GUARD_MAX_COUNT}")

                new_pid = start_engine()

                # Give main.py a moment to start and update runtime_state itself
                time.sleep(2)

                state = load_state()
                system = ensure_system_state(state)

                if new_pid and is_pid_alive(new_pid):
                    system["engine_running"] = True
                    system["engine_pid"] = new_pid
                    system["engine_started_at"] = system.get("engine_started_at") or utc_now_iso()
                    system["engine_stopped_at"] = None
                    system["last_action"] = "WATCHDOG RESTARTED MAIN"
                    system["last_error"] = None
                else:
                    system["engine_running"] = False
                    system["engine_pid"] = None
                    system["last_error"] = "watchdog_failed_to_start_main"
                    system["last_action"] = "WATCHDOG FAILED TO RESTART MAIN"
                    _log(f"engine spawn verification FAILED new_pid={new_pid}")

                system["watchdog_running"] = True
                system["watchdog_pid"] = os.getpid()
                system["watchdog_last_check"] = utc_now_iso()
                save_state(state)

        except Exception as e:
            _log(f"watchdog main loop error: {e}")

        time.sleep(WATCHDOG_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
