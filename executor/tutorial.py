"""Detecting and following forced-tutorial highlights (the pulsing glow).

Some tutorials are forced (no 'Skip'): they put a pulsing highlight on the exact
spot you must tap. We follow it generically instead of scripting each step.

The glow PULSES, so a single frame is unreliable; we capture a short burst and
let vision.find_tutorial_glow isolate the region that oscillates from static
yellow art. See memory/mistakes_learned.json ('glow-single-frame',
'glow-false-positive-static-gold') for the reasoning behind the thresholds.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from adb_controller import ADBController
from vision import find_tutorial_glow


def detect_tutorial_highlight(
    controller: ADBController,
    samples: int = 6,
    delay: float = 0.18,
    min_area: float | None = None,
):
    """Detect the pulsing tutorial highlight.

    Captures a burst of `samples` frames and lets find_tutorial_glow isolate the
    region that oscillates (the highlight) from static yellow art. `min_area`
    overrides the size gate (stricter while the city home is already on screen).
    Returns the Match (found flag, center, and blob area in .confidence), or None
    if no frame could be captured.
    """
    frames = []
    for i in range(max(2, samples)):
        try:
            frames.append(controller.screenshot())
        except Exception:
            pass
        if i < samples - 1:
            time.sleep(delay)
    if not frames:
        return None
    return find_tutorial_glow(frames, min_area=min_area)


def screen_fingerprint(screen):
    """Small, cheap signature of a frame so we can tell if the screen changed
    between recovery actions (i.e. whether we made progress or are stuck)."""
    if screen is None:
        return None
    try:
        small = cv2.resize(screen, (32, 32), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    except Exception:
        return None


def screens_similar(a, b, tol: float = 4.0) -> bool:
    """True if two fingerprints are almost identical (nothing changed)."""
    if a is None or b is None:
        return False
    return float(np.mean(cv2.absdiff(a, b))) < tol
