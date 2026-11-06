"""In-memory, bounded Codex device-login flow. Never expose raw CLI output."""
import os
import re
import signal
import subprocess
import threading

LOCK = threading.RLock()
PROCESS = None
STATE = {"state": "idle", "message": "Choose Connect Codex to sign in.", "code": None, "url": None}


def parse_device_code(output):
    """Read completed lines only: streaming prefixes are not complete codes."""
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    if "https://auth.openai.com/codex/device" not in plain:
        return None
    for line in plain.splitlines(keepends=True):
        if not line.endswith(("\n", "\r")):
            continue
        match = re.fullmatch(
            r"\s*(?:(?:your\s+)?(?:one-time\s+|device\s+|temporary\s+)?code\s*:\s*)?"
            r"([A-Z0-9]{3,6}-[A-Z0-9]{3,6}|[A-Z0-9]{8,12})\s*", line, re.I)
        if match:
            return match[1]
    return None


def snapshot():
    with LOCK:
        return dict(STATE)


def stop_process(process):
    if process.poll() is None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass


def cancel():
    global PROCESS
    with LOCK:
        process, PROCESS = PROCESS, None
        STATE.update(state="cancelled", message="Sign-in cancelled.", code=None, url=None)
        if process:
            stop_process(process)


def start(command, cwd, verify, timeout=600):
    global PROCESS
    with LOCK:
        if PROCESS is not None:
            raise ValueError("A Codex sign-in is already in progress.")
        try:
            process = subprocess.Popen([command, "login", "--device-auth"], cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", start_new_session=True, bufsize=1)
        except OSError:
            STATE.update(state="failed", message="Could not start Codex. Check the CLI installation.", code=None, url=None)
            return snapshot()
        PROCESS = process
        STATE.update(state="starting", message="Contacting OpenAI for a sign-in code…", code=None, url=None)

    def expire():
        global PROCESS
        with LOCK:
            if PROCESS is process:
                PROCESS = None
                STATE.update(state="expired", message="Sign-in expired. Choose Retry.", code=None, url=None)
                stop_process(process)

    def watch():
        global PROCESS
        output = ""
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            while True:
                char = process.stdout.read(1)
                if not char:
                    break
                output = (output + char)[-16000:]
                code = parse_device_code(output)
                if code:
                    with LOCK:
                        if PROCESS is process:
                            STATE.update(state="waiting", message="Open OpenAI sign-in and enter the code. Keep this page open.",
                                         code=code, url="https://auth.openai.com/codex/device")
            returncode = process.wait()
            ready = returncode == 0 and verify()
            with LOCK:
                if PROCESS is process:
                    PROCESS = None
                    message = "Codex is connected." if ready else "Sign-in failed. Retry, or check device login permissions."
                    if not ready and any(term in output.lower() for term in ("error sending request", "connect", "dns", "certificate", "530")):
                        message = "Cannot reach OpenAI sign-in. Check Docker network, proxy, and TLS settings, then retry."
                    STATE.update(state="connected" if ready else "failed", message=message, code=None, url=None)
        except Exception:
            with LOCK:
                if PROCESS is process:
                    PROCESS = None
                    stop_process(process)
                    STATE.update(state="failed", message="Sign-in stopped unexpectedly. Choose Retry.", code=None, url=None)
        finally:
            timer.cancel()
            process.stdout.close()
    threading.Thread(target=watch, daemon=True).start()
    return snapshot()
