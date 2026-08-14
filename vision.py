"""On-screen element recognition via template matching (OpenCV)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

import config


@dataclass(frozen=True)
class Match:
    """Result of a template search."""
    found: bool
    confidence: float
    x: int = 0  # template center on the screen
    y: int = 0


@lru_cache(maxsize=None)
def _load_template(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Template not found or invalid: {path}")
    return img


def find_template(
    screen: np.ndarray,
    template_name: str,
    threshold: float = config.DEFAULT_THRESHOLD,
) -> Match:
    """Search for `template_name` (a file in templates/) inside `screen`.

    Returns a Match with the template center when confidence >= threshold.
    """
    template_path = Path(config.TEMPLATES_DIR) / template_name
    template = _load_template(str(template_path))

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return Match(found=False, confidence=float(max_val))

    th, tw = template.shape[:2]
    center_x = int(max_loc[0] + tw / 2)
    center_y = int(max_loc[1] + th / 2)
    return Match(found=True, confidence=float(max_val), x=center_x, y=center_y)


def find_all_templates(
    screen: np.ndarray,
    template_name: str,
    threshold: float = config.DEFAULT_THRESHOLD,
    min_distance: int = 20,
) -> list[Match]:
    """Return every occurrence of `template_name` in `screen`.

    Keeps each peak above `threshold`, suppressing peaks within `min_distance`
    pixels of an already-kept one (so a single element is not reported several
    times). Matches come back sorted by descending confidence.
    """
    template_path = Path(config.TEMPLATES_DIR) / template_name
    template = _load_template(str(template_path))
    th, tw = template.shape[:2]

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    peaks = sorted(zip(xs.tolist(), ys.tolist()),
                   key=lambda p: result[p[1], p[0]], reverse=True)

    kept: list[Match] = []
    for x, y in peaks:
        cx, cy = int(x + tw / 2), int(y + th / 2)
        if all(abs(cx - m.x) > min_distance or abs(cy - m.y) > min_distance
               for m in kept):
            kept.append(Match(found=True, confidence=float(result[y, x]),
                              x=cx, y=cy))
    return kept


def count_template(
    screen: np.ndarray,
    template_name: str,
    threshold: float = config.DEFAULT_THRESHOLD,
    min_distance: int = 20,
) -> int:
    """Count how many times `template_name` appears in `screen`.

    Convenience wrapper around find_all_templates. Useful for tallying repeated
    UI items such as the idle flags in the march-queue panel.
    """
    return len(find_all_templates(screen, template_name, threshold, min_distance))


def find_all_gray(
    screen: np.ndarray,
    template_name: str,
    threshold: float = config.DEFAULT_THRESHOLD,
    min_distance: int = 20,
) -> list[Match]:
    """Like find_all_templates, but matches on GRAYSCALE.

    Useful when the target has the SAME shape but VARYING color — e.g. the Intel
    Mission balloon pins, whose white glyph (lion / crossed swords / tent) is
    identical across every rarity while the pin body color changes (gold, purple,
    blue, ...). Color matching penalizes the differently-colored bodies and can
    drop a valid pin below threshold; matching the grayscale shape finds them all
    regardless of rarity color. Returns matches sorted by descending confidence,
    suppressing peaks within `min_distance` pixels of an already-kept one.
    """
    template_path = Path(config.TEMPLATES_DIR) / template_name
    template = cv2.cvtColor(_load_template(str(template_path)), cv2.COLOR_BGR2GRAY)
    screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]

    result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    peaks = sorted(zip(xs.tolist(), ys.tolist()),
                   key=lambda p: result[p[1], p[0]], reverse=True)

    kept: list[Match] = []
    for x, y in peaks:
        cx, cy = int(x + tw / 2), int(y + th / 2)
        if all(abs(cx - m.x) > min_distance or abs(cy - m.y) > min_distance
               for m in kept):
            kept.append(Match(found=True, confidence=float(result[y, x]),
                              x=cx, y=cy))
    return kept


def find_tutorial_glow(frames, min_area: float = None) -> Match:
    """Detect the pulsing highlight that forced tutorials place on the spot you
    must tap.

    The highlight PULSES (its glow fades in and out), which is what sets it apart
    from the many static yellow/gold elements in the game (buildings, coins,
    icons). Pass a sequence of frames (BGR images captured a fraction of a second
    apart) and this isolates the region whose highlight color oscillates the most
    over time — the tutorial glow — ignoring static decorations.

    For backward compatibility a single image is also accepted, in which case a
    plain color mask is used (less reliable, since it can't tell the pulse apart
    from static yellow art). Returns a Match with the glow center. Generic: works
    wherever each step points, no per-step template needed."""
    if isinstance(frames, np.ndarray):
        frames = [frames]
    frames = list(frames)
    if not frames:
        return Match(found=False, confidence=0.0)

    low = np.array(config.GLOW_HSV_LOW, dtype=np.uint8)
    high = np.array(config.GLOW_HSV_HIGH, dtype=np.uint8)
    masks = []
    for frame in frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        masks.append(cv2.inRange(hsv, low, high))

    if len(masks) >= 2:
        # Pulsing region = where the glow-color mask changes across frames.
        stack = np.stack(masks).astype(np.int16)
        signal = (stack.max(axis=0) - stack.min(axis=0)).astype(np.uint8)
    else:
        signal = masks[0]

    # Ignore the top status bar, where yellow coins/icons live.
    h = signal.shape[0]
    signal[: int(h * 0.10), :] = 0
    signal = cv2.morphologyEx(signal, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(signal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    threshold_area = config.GLOW_MIN_AREA if min_area is None else min_area
    max_area = getattr(config, "GLOW_MAX_AREA", float("inf"))
    best_area = 0.0
    best_center = (0, 0)
    for contour in contours:
        area = cv2.contourArea(contour)
        # Reject blobs that are too small (ambient shimmer) or far too big
        # (animated promo/cutscene art, not a compact tutorial ring).
        if threshold_area <= area <= max_area and area > best_area:
            (x, y), _ = cv2.minEnclosingCircle(contour)
            best_area = area
            best_center = (int(x), int(y))

    if best_area == 0.0:
        return Match(found=False, confidence=0.0)
    # confidence carries the blob area so callers can apply their own gate.
    return Match(found=True, confidence=float(best_area), x=best_center[0], y=best_center[1])
