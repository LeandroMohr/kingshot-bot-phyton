"""Emulator controller via ADB.

Every screen capture is done in memory (bytes -> OpenCV). No screenshot image
is written to disk, avoiding a history of screenshots.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

import config
from bot_control import wait_if_paused

# Without this, every adb call flashes a console window when run from the GUI on Windows.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class ADBController:
    host: str = config.ADB_HOST
    port: int = config.ADB_PORT
    binary: str = config.ADB_BINARY

    @property
    def serial(self) -> str:
        return f"{self.host}:{self.port}"

    # -- connection --------------------------------------------------------
    def connect(self) -> None:
        """Connect to the emulator. Raises RuntimeError on failure."""
        self._run([self.binary, "connect", self.serial])
        devices = self._run([self.binary, "devices"]).decode(errors="ignore")
        if self.serial not in devices or "device" not in devices:
            raise RuntimeError(
                f"Could not connect to {self.serial}.\n"
                f"Output of 'adb devices':\n{devices}\n"
                "Check that BlueStacks ADB is enabled and the port is correct."
            )

    # -- capture -----------------------------------------------------------
    def screenshot(self, timeout: float | None = None) -> np.ndarray:
        """Capture the screen and return a BGR image (numpy). In memory only."""
        raw = self._run(
            [self.binary, "-s", self.serial, "exec-out", "screencap", "-p"],
            timeout=timeout,
        )
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Failed to decode the screenshot from ADB.")
        return img

    # -- interaction -------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        """Tap the coordinate (x, y) on the emulator screen."""
        self._run(
            [self.binary, "-s", self.serial, "shell", "input", "tap", str(x), str(y)]
        )

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(
            [
                self.binary, "-s", self.serial, "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration_ms),
            ]
        )

    def back(self) -> None:
        """Send the Android 'back' key (closes dialogs/windows)."""
        self._run(
            [self.binary, "-s", self.serial, "shell", "input", "keyevent", "4"]
        )

    def key_event(self, *keycodes: int) -> None:
        """Send one or more Android key events (e.g. 67 = DEL, 123 = MOVE_END)."""
        self._run(
            [self.binary, "-s", self.serial, "shell", "input", "keyevent",
             *[str(k) for k in keycodes]]
        )

    def input_text(self, text: str) -> None:
        """Type `text` into the input field that currently has focus."""
        self._run(
            [self.binary, "-s", self.serial, "shell", "input", "text", text]
        )

    # -- app / game --------------------------------------------------------
    def is_app_running(self, package: str) -> bool:
        """True if the app process is active on the emulator (may be in the
        background). For "is the game actually on screen?" use is_app_foreground."""
        out = self._run(
            [
                self.binary, "-s", self.serial, "shell",
                f"pidof {package} >/dev/null 2>&1 && echo RUNNING || echo STOPPED",
            ]
        ).decode(errors="ignore")
        return "RUNNING" in out

    def foreground_app(self) -> str:
        """Return the package name of the app currently in the foreground
        (the focused window), or '' if it cannot be determined."""
        out = self._run(
            [
                self.binary, "-s", self.serial, "shell",
                "dumpsys window | grep mCurrentFocus || true",
            ]
        ).decode(errors="ignore")
        # e.g. "mCurrentFocus=Window{hash u0 com.run.tower.defense/com...Activity}"
        match = re.search(r"mCurrentFocus=Window\{\S+\s+\S+\s+([a-zA-Z0-9_.]+)/", out)
        return match.group(1) if match else ""

    def is_app_foreground(self, package: str) -> bool:
        """True only if the given app is the one currently on screen."""
        return self.foreground_app() == package

    def launch_app(self, package: str) -> None:
        """Launch the app via the launcher intent (like tapping its icon)."""
        self._run(
            [
                self.binary, "-s", self.serial, "shell", "monkey",
                "-p", package, "-c", "android.intent.category.LAUNCHER", "1",
            ]
        )

    # -- internal ----------------------------------------------------------
    @staticmethod
    def _run(cmd: list[str], timeout: float | None = None) -> bytes:
        wait_if_paused()
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n{result.stderr.decode(errors='ignore')}"
            )
        return result.stdout


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    started_at: float
    completed_at: float
    image: np.ndarray


class ContinuousCapture:
    """One bounded ADB worker, retaining only the latest immutable frame."""

    def __init__(self, controller: ADBController, max_fps: float = 10.0,
                 max_timeout_retries: int = 0):
        if max_fps <= 0:
            raise ValueError("Capture frame rate must be positive.")
        if type(max_timeout_retries) is not int or max_timeout_retries < 0:
            raise ValueError("Maximum timeout retries must be a nonnegative integer.")
        self.controller = controller
        self.max_timeout_retries = max_timeout_retries
        self.timeouts = 0
        self.interval = 1.0 / max_fps
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._capture, name="adb-capture")
        self._latest: CapturedFrame | None = None
        self._error: Exception | None = None
        self.frames = 0
        self.capture_seconds = 0.0
        self.started_at = 0.0
        self.stopped_at = 0.0

    def __enter__(self) -> ContinuousCapture:
        self.started_at = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread.ident is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise RuntimeError("ADB capture worker did not stop within 3 seconds.")
        self.stopped_at = time.monotonic()

    def next_frame(self, after_sequence: int = -1, not_before: float = 0.0,
                   timeout: float = 2.5) -> CapturedFrame:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._error is not None:
                    raise RuntimeError(f"Continuous ADB capture failed: {self._error}") from self._error
                if self._stop.is_set():
                    raise RuntimeError("Continuous ADB capture is closed.")
                frame = self._latest
                # started_at, not completed_at, excludes captures in flight at tap time.
                if (frame is not None and frame.sequence > after_sequence
                        and frame.started_at >= not_before):
                    return frame
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("No fresh ADB frame within the requested timeout.")
                self._condition.wait(remaining)

    def _capture(self) -> None:
        consecutive_timeouts = 0
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    image = self.controller.screenshot(timeout=2.0)
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    is_timeout = (isinstance(exc, subprocess.TimeoutExpired)
                                  or isinstance(exc.__cause__, subprocess.TimeoutExpired))
                    if not is_timeout:
                        raise
                    self.timeouts += 1
                    with self._condition:
                        self._latest = None
                        self._condition.notify_all()
                    if consecutive_timeouts >= self.max_timeout_retries:
                        raise
                    consecutive_timeouts += 1
                    self._stop.wait(self.interval)
                    continue
                consecutive_timeouts = 0
                completed = time.monotonic()
                image.setflags(write=False)
                with self._condition:
                    self.frames += 1
                    self.capture_seconds += completed - started
                    self._latest = CapturedFrame(self.frames, started, completed, image)
                    self._condition.notify_all()
                self._stop.wait(max(0.0, self.interval - (completed - started)))
        except Exception as exc:  # transfer worker failures to the consuming thread
            with self._condition:
                self._error = exc
                self._condition.notify_all()


def list_devices(binary: str = config.ADB_BINARY) -> list[str]:
    """Return the serials (e.g. '127.0.0.1:5605') of the connected devices."""
    out = subprocess.run(
        [binary, "devices"], capture_output=True, creationflags=NO_WINDOW
    ).stdout.decode(errors="ignore")
    devices: list[str] = []
    for line in out.splitlines()[1:]:  # skip the header
        line = line.strip()
        if line and "\tdevice" in line:
            devices.append(line.split("\t")[0])
    return devices


def discover_devices(
    host: str = config.ADB_HOST,
    ports: list[int] | None = None,
    binary: str = config.ADB_BINARY,
) -> list[str]:
    """Try to `adb connect` to the candidate ports so BlueStacks instances show
    up without a manual connect, then return the connected serials."""
    for port in ports if ports is not None else config.DISCOVERY_PORTS:
        subprocess.run(
            [binary, "connect", f"{host}:{port}"],
            capture_output=True,
            timeout=5,
            creationflags=NO_WINDOW,
        )
    return list_devices(binary)
