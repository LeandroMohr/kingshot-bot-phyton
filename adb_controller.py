"""Emulator controller via ADB.

Every screen capture is done in memory (bytes -> OpenCV). No screenshot image
is written to disk, avoiding a history of screenshots.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

import config


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
    def screenshot(self) -> np.ndarray:
        """Capture the screen and return a BGR image (numpy). In memory only."""
        raw = self._run(
            [self.binary, "-s", self.serial, "exec-out", "screencap", "-p"]
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
    def _run(cmd: list[str]) -> bytes:
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n{result.stderr.decode(errors='ignore')}"
            )
        return result.stdout


def list_devices(binary: str = config.ADB_BINARY) -> list[str]:
    """Return the serials (e.g. '127.0.0.1:5605') of the connected devices."""
    out = subprocess.run(
        [binary, "devices"], capture_output=True
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
        )
    return list_devices(binary)

