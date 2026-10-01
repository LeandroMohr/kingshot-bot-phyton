"""Pause/resume for a running bot, driven by the control panel over stdin.

The panel writes "pause" / "resume" lines to the bot's stdin. Every ADB call
waits here while paused, so the bot freezes right before its next action
(tap, swipe, screenshot...) and continues from the same spot on resume.
"""
from __future__ import annotations

import sys
import threading

_running = threading.Event()
_running.set()


def _listen() -> None:
    for line in sys.stdin:
        command = line.strip().lower()
        if command == "pause" and _running.is_set():
            _running.clear()
            print("[control] Paused: the bot stops before its next action.", flush=True)
        elif command == "resume" and not _running.is_set():
            _running.set()
            print("[control] Resumed.", flush=True)


def listen_stdin() -> None:
    threading.Thread(target=_listen, daemon=True).start()


def wait_if_paused() -> None:
    # Short timeouts keep the wait interruptible, so Stop (Ctrl+C) still works while paused.
    while not _running.wait(0.5):
        pass
