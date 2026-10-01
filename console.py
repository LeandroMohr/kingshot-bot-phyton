"""Cross-platform console input with a timeout.

``select.select`` on stdin only works on Unix (on Windows it accepts sockets
only), so a single background thread reads stdin and prompts wait on a queue.
"""
from __future__ import annotations

import queue
import sys
import threading

_lines: "queue.Queue[str]" = queue.Queue()
_reader: threading.Thread | None = None


def _read_stdin() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:  # EOF
            return
        _lines.put(line)


def timed_input(message: str, timeout: float | None) -> str | None:
    """Print ``message`` and return the typed line (stripped), or None if nothing
    is typed within ``timeout`` seconds (``None`` waits forever)."""
    global _reader
    if _reader is None:
        _reader = threading.Thread(target=_read_stdin, daemon=True)
        _reader.start()
    print(message, end="", flush=True)
    try:
        return _lines.get(timeout=timeout).strip()
    except queue.Empty:
        print()
        return None
