"""Primitive on-screen actions: tap a template, tap the center, wait.

These are thin, reusable helpers built on ADBController + vision, so tasks and
navigation don't re-implement the same tap-if-found logic.
"""
from __future__ import annotations

import time
from pathlib import Path

from adb_controller import ADBController
from vision import find_template
import config


def wait(seconds: float) -> None:
    """Block for `seconds` (kept as a named action for readability in flows)."""
    time.sleep(seconds)


def tap_template(
    controller: ADBController,
    template: str,
    threshold: float | None = None,
    wait_after: float = 1.0,
) -> bool:
    """Look for `template` on the current screen and tap its center.

    Returns False (without tapping) if the template file does not exist yet or is
    not found on screen. `threshold` defaults to config.DEFAULT_THRESHOLD.
    """
    if not (Path(config.TEMPLATES_DIR) / template).exists():
        return False  # template not captured yet; treat as absent
    screen = controller.screenshot()
    match = find_template(screen, template, threshold or config.DEFAULT_THRESHOLD)
    if not match.found:
        return False
    controller.tap(match.x, match.y)
    time.sleep(wait_after)
    return True


def tap_center(controller: ADBController, wait_after: float = 1.0) -> None:
    """Tap the center of the screen (for 'tap anywhere to continue' screens)."""
    screen = controller.screenshot()
    h, w = screen.shape[:2]
    controller.tap(w // 2, h // 2)
    time.sleep(wait_after)
