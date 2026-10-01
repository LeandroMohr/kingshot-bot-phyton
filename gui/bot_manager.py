"""Runs each emulator's bot as its own ``main.py`` process and keeps its log.

One process per emulator keeps the bots isolated: tasks hold per-run state and
``account_prefs`` tracks the current account per process.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque

import config
from adb_controller import NO_WINDOW
from gui.i18n import UserError

LOG_LIMIT = 2000
STOP_TIMEOUT = 8.0


def bot_command(host: str, port: int, task_names: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):  # PyInstaller build: app.py dispatches --bot
        cmd = [sys.executable, "--bot"]
    else:
        cmd = [sys.executable, "-u", str(config.BASE_DIR / "main.py")]
    cmd += ["--host", host, "--port", str(port), "--control-stdin"]
    for name in task_names:
        cmd += ["--task", name]
    return cmd


class BotProcess:
    def __init__(self, host: str, port: int, task_names: list[str]):
        self.host = host
        self.port = port
        self.task_names = list(task_names)
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self.paused = False
        self._lines: deque[tuple[int, float, str]] = deque(maxlen=LOG_LIMIT)
        self._seq = 0
        self._lock = threading.Lock()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            bot_command(host, port, self.task_names),
            cwd=config.BASE_DIR,
            stdin=subprocess.PIPE,  # control channel (pause/resume); not a TTY -> no prompts
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for raw in self.proc.stdout:
            self._append(raw.decode("utf-8", errors="replace").rstrip())
        code = self.proc.wait()
        self.stopped_at = time.time()
        self._append(f"[panel] Bot exited (code {code}).")

    def _append(self, text: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, time.time(), text))

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def logs_since(self, cursor: int) -> tuple[list[dict], int]:
        with self._lock:
            lines = [{"seq": seq, "ts": ts, "text": text}
                     for seq, ts, text in self._lines if seq > cursor]
            return lines, self._seq

    def _send(self, command: str) -> None:
        if not self.running:
            raise UserError("bot_not_running", port=self.port)
        self.proc.stdin.write(f"{command}\n".encode())
        self.proc.stdin.flush()

    def pause(self) -> None:
        self._send("pause")
        self.paused = True

    def resume(self) -> None:
        self._send("resume")
        self.paused = False

    def stop(self) -> None:
        if not self.running:
            return
        self.paused = False
        if os.name == "nt":
            self.proc.terminate()
        else:
            self.proc.send_signal(signal.SIGINT)  # graceful: main.py prints its uptime
        try:
            self.proc.wait(STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "tasks": self.task_names,
            "running": self.running,
            "paused": self.paused and self.running,
            "pid": self.proc.pid,
            "exit_code": self.proc.poll(),
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
        }


class BotManager:
    def __init__(self):
        self._bots: dict[int, BotProcess] = {}
        self._lock = threading.Lock()

    def start(self, host: str, port: int, task_names: list[str] = ()) -> BotProcess:
        with self._lock:
            current = self._bots.get(port)
            if current and current.running:
                raise UserError("bot_already_running", port=port)
            bot = BotProcess(host, port, task_names)
            self._bots[port] = bot
            return bot

    def get(self, port: int) -> BotProcess | None:
        return self._bots.get(port)

    def require(self, port: int) -> BotProcess:
        bot = self._bots.get(port)
        if bot is None:
            raise UserError("no_bot", port=port)
        return bot

    def stop(self, port: int) -> None:
        bot = self._bots.get(port)
        if bot:
            bot.stop()

    def stop_all(self) -> None:
        for bot in list(self._bots.values()):
            bot.stop()

    def list(self) -> list[dict]:
        return [self._bots[port].to_dict() for port in sorted(self._bots)]
