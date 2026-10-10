"""Local object proposals from a clean background or class-agnostic contrast."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from adb_controller import ContinuousCapture


@dataclass(frozen=True)
class Proposal:
    point: tuple[int, int]
    score: float


def _difference_candidates(image: np.ndarray, background: np.ndarray,
                           offset: tuple[int, int]) -> tuple[Proposal, ...]:
    if background.shape != image.shape or background.dtype != np.uint8:
        raise ValueError("Clean background must match the scene crop and be uint8 BGR.")
    difference = np.max(cv2.absdiff(image, background), axis=2)
    mask = (difference > 12).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    proposals = []
    for label in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[label])
        if area < 6:
            continue
        component = (labels[y:y + height, x:x + width] == label).astype(np.uint8)
        padded = cv2.copyMakeBorder(component, 1, 1, 1, 1, cv2.BORDER_CONSTANT)
        distance = cv2.distanceTransform(padded, cv2.DIST_L2, 3)[1:-1, 1:-1]
        _, _, _, center = cv2.minMaxLoc(distance)
        px, py = x + center[0], y + center[1]
        score = float(np.mean(difference[y:y + height, x:x + width][component != 0]))
        proposals.append(Proposal((px + offset[0], py + offset[1]), score))
    return tuple(sorted(proposals, key=lambda p: p.score, reverse=True)[:160])


def image_candidates(screen: np.ndarray, region,
                     background: np.ndarray | None = None) -> tuple[Proposal, ...]:
    x1, y1, x2, y2 = region
    if not (0 <= x1 < x2 <= screen.shape[1]
            and 0 <= y1 < y2 <= screen.shape[0]):
        raise ValueError("Candidate region is outside the captured image.")
    image = screen[y1:y2, x1:x2]
    if background is not None:
        return _difference_candidates(image, background, (x1, y1))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    color = image.astype(np.float32)
    contrast = np.zeros(gray.shape, np.float32)
    for sigma in (3, 7, 14):
        background = cv2.GaussianBlur(color, (0, 0), sigma)
        deviation = np.sqrt(np.mean((color - background) ** 2, axis=2))
        contrast = np.maximum(contrast, cv2.GaussianBlur(deviation, (0, 0), 2))

    edges = cv2.Canny(gray, 45, 110)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    proposals = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if not (6 <= width <= 100 and 6 <= height <= 100
                and 25 <= area <= 6000 and area / (width * height) >= .15):
            continue
        # An interior point is safer than a bounding-box center for curved items.
        mask = np.zeros((height + 2, width + 2), np.uint8)
        cv2.drawContours(mask, [contour - (x - 1, y - 1)], -1, 255, cv2.FILLED)
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
        _, _, _, center = cv2.minMaxLoc(distance)
        px, py = x + center[0] - 1, y + center[1] - 1
        score = float(np.mean(contrast[y:y + height, x:x + width]))
        score *= min(1.0, area / 100) * (1 + area / (width * height))
        # Cropped landscape edges otherwise outrank complete small objects.
        margin = min(x, y, image.shape[1] - x - width, image.shape[0] - y - height)
        score *= min(1.0, .15 + margin / 24)
        proposals.append(Proposal((px + x1, py + y1), score))

    # Color-contrast peaks also cover open/thin shapes without closed contours.
    response = cv2.GaussianBlur(contrast, (0, 0), 4)
    maxima = cv2.dilate(response, np.ones((17, 17), np.uint8))
    ys, xs = np.where((response == maxima) & (response >= 8))
    proposals.extend(Proposal((int(x) + x1, int(y) + y1), float(response[y, x]))
                     for y, x in zip(ys, xs))
    kept = []
    for proposal in sorted(proposals, key=lambda p: p.score, reverse=True):
        px, py = proposal.point
        if (x1 + 4 <= px < x2 - 4 and y1 + 4 <= py < y2 - 4
                and all((px - p.point[0]) ** 2 + (py - p.point[1]) ** 2 >= 18 ** 2
                        for p in kept)):
            kept.append(proposal)
            if len(kept) == 160:
                break
    return tuple(kept)


@dataclass(frozen=True)
class CandidateFrame:
    sequence: int
    started_at: float
    proposals: tuple[Proposal, ...]


class ImageCandidates:
    """Analyze the newest ADB frames independently of OCR and serial actions."""

    def __init__(self, capture: ContinuousCapture, region,
                 background: np.ndarray | None = None):
        self.capture = capture
        self.region = tuple(region)
        self.background = background
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._analyze,
                                        name="hidden-object-proposals")
        self._latest: CandidateFrame | None = None
        self._error: Exception | None = None
        self.frames = 0
        self.analysis_seconds = 0.0

    def __enter__(self) -> ImageCandidates:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
        if exc_type is None:
            self.raise_if_failed()

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread.ident is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError("Hidden Objects image analysis did not stop.")

    def raise_if_failed(self) -> None:
        with self._condition:
            if self._error is not None:
                raise RuntimeError(
                    f"Hidden Objects image analysis failed: {self._error}"
                ) from self._error

    def latest(self, after_sequence: int = -1, not_before: float = 0,
               timeout: float = 2.5) -> CandidateFrame:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                self.raise_if_failed()
                if self._stop.is_set():
                    raise RuntimeError("Hidden Objects image analysis is closed.")
                latest = self._latest
                if (latest is not None and latest.sequence >= after_sequence
                        and latest.started_at >= not_before):
                    return latest
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("No fresh Hidden Objects image candidates.")
                self._condition.wait(remaining)

    def _analyze(self) -> None:
        sequence = -1
        try:
            while not self._stop.is_set():
                try:
                    frame = self.capture.next_frame(sequence, timeout=.25)
                except TimeoutError:
                    continue
                sequence = frame.sequence
                started = time.monotonic()
                proposals = image_candidates(frame.image, self.region, self.background)
                with self._condition:
                    self.frames += 1
                    self.analysis_seconds += time.monotonic() - started
                    self._latest = CandidateFrame(sequence, frame.started_at, proposals)
                    self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._error = exc
                self._condition.notify_all()
