from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("runtime_state.json")
WATCHDOG_SLEEP_SECONDS = 10
ENGINE_STALL_SECONDS = 90

STARTUP_STDOUT_FILE = Path("watchdog_main_stdout.log")
STARTUP_STDERR_FILE = Path("watchdog_main_stderr.log")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def kill_engine_if_exists(system: dict) -> None:
    pid = system.get("engine_pid")
    if is_pid_alive(pid):
        try:
            os.kill(int(pid), 9)
        except Exception:
            pass


def start_engine() -> int | None:
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
        return proc.pid

    except Exception as e:
        print(f"watchdog start_engine error: {e}")
        return None


def main() -> None:
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

            if is_engine_stalled(system):
                kill_engine_if_exists(system)
                time.sleep(2)

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
                else:
                    system["engine_running"] = False
                    system["engine_pid"] = None
                    system["last_error"] = "watchdog_failed_to_start_main"
                    system["last_action"] = "WATCHDOG FAILED TO RESTART MAIN"

                system["watchdog_running"] = True
                system["watchdog_pid"] = os.getpid()
                system["watchdog_last_check"] = utc_now_iso()
                save_state(state)

        except Exception:
            pass

        time.sleep(WATCHDOG_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
