"""Multi-instance fish detection and frame-to-frame tracking; no game input."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class FishDetection:
    name: str
    box: tuple[float, float, float, float]
    confidence: float


def overlap(first, second) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union > 0 else 0.0


def fishing_hud_regions(frame_size: tuple[int, int]) -> tuple[tuple[float, ...], ...]:
    width, height = frame_size
    scale_x, scale_y = width / 540, height / 960
    return ((0, 0, 150 * scale_x, 140 * scale_y),
            (490 * scale_x, 0, 50 * scale_x, 55 * scale_y))


def visible_target(box, frame_size, excluded_regions=()) -> bool:
    width, height = frame_size
    return (box[0] + box[2] > 0 and box[1] + box[3] > 0
            and box[0] < width and box[1] < height
            and all(overlap(box, region) == 0 for region in excluded_regions))


def brighten_dark_frame(image, excluded_regions=(), gamma: float = .35):
    if not 0 < gamma <= 1:
        raise ValueError("Brightness gamma must be between zero and one.")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    selected = (value > 0) & (value < 180)
    for left, top, width, height in excluded_regions:
        selected[max(0, int(top)):int(top + height),
                 max(0, int(left)):int(left + width)] = False
    levels = np.arange(256, dtype=np.float32)
    lookup = np.where(levels < 180, 180 * (levels / 180) ** gamma, levels)
    hsv[:, :, 2] = cv2.LUT(value, np.rint(lookup).clip(0, 255).astype(np.uint8))
    enhanced = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    result = image.copy()
    result[selected] = np.maximum(image[selected], enhanced[selected])
    return result


def brightness_layer(original, enhanced):
    source = original.astype(np.float32)
    difference = np.maximum(enhanced.astype(np.float32) - source, 0)
    alpha = np.max(difference / np.maximum(255 - source, 1), axis=2)
    alpha = np.ceil(alpha * 255).clip(0, 255).astype(np.uint8)
    fraction = np.maximum(alpha.astype(np.float32) / 255, 1 / 255)
    color = source + difference / fraction[:, :, None]
    layer = np.zeros((*original.shape[:2], 4), np.uint8)
    layer[:, :, :3] = np.rint(color).clip(0, 255).astype(np.uint8)
    layer[:, :, 3] = alpha
    layer[alpha == 0] = 0
    return layer


def foreground_mask(sprite):
    hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)
    mask = np.where(((hsv[:, :, 0] < 60) | (hsv[:, :, 1] < 75))
                    & (hsv[:, :, 2] > 70), 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("Fish reference has no foreground.")
    mask[:] = 0
    cv2.drawContours(mask, [max(contours, key=cv2.contourArea)], -1, 255, cv2.FILLED)
    if cv2.countNonZero(mask) < 100:
        raise ValueError("Fish reference is too small.")
    return mask


class FishDetector:
    def __init__(self, references: dict[str, Path], threshold: float = .94,
                 scales: tuple[float, ...] = (.9, 1.0, 1.1)):
        if not 0 < threshold < 1 or not scales or any(scale <= 0 for scale in scales):
            raise ValueError("Invalid detector threshold or scales.")
        self.threshold = threshold
        self.templates = []
        for name, path in references.items():
            sprite = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if sprite is None:
                raise FileNotFoundError(f"Missing native ADB fish reference: {path}")
            mask = foreground_mask(sprite)
            for scale in scales:
                resized = cv2.resize(sprite, None, fx=scale, fy=scale)
                resized_mask = cv2.resize(mask, (resized.shape[1], resized.shape[0]),
                                          interpolation=cv2.INTER_NEAREST)
                for mirrored in (False, True):
                    self.templates.append((name, cv2.flip(resized, 1) if mirrored else resized,
                                           cv2.flip(resized_mask, 1) if mirrored else resized_mask))

    def detect(self, image, excluded_regions=()) -> list[FishDetection]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, (10, 85, 110), (45, 255, 255))
        yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        for left, top, region_width, region_height in excluded_regions:
            yellow[max(0, int(top)):int(top + region_height),
                   max(0, int(left)):int(left + region_width)] = 0
        contours, _ = cv2.findContours(yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        height, width = image.shape[:2]
        for contour in contours:
            if cv2.contourArea(contour) < 45:
                continue
            left, top, box_width, box_height = cv2.boundingRect(contour)
            crop_left, crop_top = max(0, left - 65), max(0, top - 35)
            crop_right = min(width, left + box_width + 65)
            crop_bottom = min(height, top + box_height + 110)
            crop = image[crop_top:crop_bottom, crop_left:crop_right]
            for name, sprite, mask in self.templates:
                sprite_height, sprite_width = sprite.shape[:2]
                if crop.shape[0] < sprite_height or crop.shape[1] < sprite_width:
                    continue
                error = cv2.matchTemplate(crop, sprite, cv2.TM_SQDIFF_NORMED, mask=mask)
                score = np.nan_to_num(1 - error, nan=-1, posinf=-1, neginf=-1)
                peaks = (score >= self.threshold) & (score >= cv2.dilate(score, np.ones((9, 9), np.uint8)))
                rows, columns = np.where(peaks)
                for row, column in zip(rows.tolist(), columns.tolist()):
                    candidates.append(FishDetection(name,
                        (crop_left + column, crop_top + row, sprite_width, sprite_height),
                        float(score[row, column])))
        kept = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if (visible_target(candidate.box, (width, height), excluded_regions)
                    and all(overlap(candidate.box, previous.box) < .25 for previous in kept)):
                kept.append(candidate)
        return kept


class CatalogDetector:
    def __init__(self, references: dict[str, Path], threshold: float = .94):
        if not 0 < threshold < 1:
            raise ValueError("Invalid detector threshold.")
        self.threshold = threshold
        self.features = cv2.SIFT_create(nfeatures=1200, contrastThreshold=.02)
        self.variants = []
        self.rejected = {}
        descriptors, owners, coordinates = [], [], []
        for name, path in references.items():
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise FileNotFoundError(f"Missing catalog reference: {path}")
            height, width = image.shape[:2]
            labels = np.zeros((height, width), np.uint8)
            rectangle = (round(width * .04), round(height * .02),
                         round(width * .92), round(height * .96))
            cv2.grabCut(image, labels, rectangle, np.zeros((1, 65), np.float64),
                        np.zeros((1, 65), np.float64), 3, cv2.GC_INIT_WITH_RECT)
            mask = np.where((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
            count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
            if count < 2:
                self.rejected[name] = "No isolated foreground"
                continue
            largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            mask = np.where(components == largest, 255, 0).astype(np.uint8)
            left, top, box_width, box_height = cv2.boundingRect(mask)
            image = image[top:top + box_height, left:left + box_width]
            mask = mask[top:top + box_height, left:left + box_width]
            usable = False
            for mirrored in (False, True):
                sprite = cv2.flip(image, 1) if mirrored else image
                foreground = cv2.flip(mask, 1) if mirrored else mask
                keypoints, descriptor = self.features.detectAndCompute(
                    cv2.cvtColor(sprite, cv2.COLOR_BGR2GRAY), foreground)
                if descriptor is None or len(keypoints) < 4:
                    continue
                variant = len(self.variants)
                self.variants.append((name, box_width, box_height))
                descriptors.append(descriptor)
                owners.extend([variant] * len(keypoints))
                coordinates.extend([point.pt for point in keypoints])
                usable = True
            if not usable:
                self.rejected[name] = "Insufficient distinctive visual features"
        if not descriptors:
            if references:
                raise ValueError("No usable catalog references.")
            self.matcher = None
            return
        self.owners = np.asarray(owners, np.int32)
        self.coordinates = np.asarray(coordinates, np.float32)
        self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=64))
        self.matcher.add([np.vstack(descriptors)])
        self.matcher.train()

    def detect(self, image, excluded_regions=()) -> list[FishDetection]:
        if self.matcher is None:
            return []
        height, width = image.shape[:2]
        mask = np.full((height, width), 255, np.uint8)
        for left, top, region_width, region_height in excluded_regions:
            mask[max(0, int(top)):int(top + region_height),
                 max(0, int(left)):int(left + region_width)] = 0
        keypoints, descriptors = self.features.detectAndCompute(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), mask)
        if descriptors is None:
            return []
        grouped = {}
        for matches in self.matcher.knnMatch(descriptors, k=2):
            if len(matches) == 2 and matches[0].distance < .75 * matches[1].distance:
                match = matches[0]
                grouped.setdefault(int(self.owners[match.trainIdx]), []).append(match)
        candidates = []
        for variant, matches in grouped.items():
            if len(matches) < 4:
                continue
            source = self.coordinates[[match.trainIdx for match in matches]]
            target = np.asarray([keypoints[match.queryIdx].pt for match in matches], np.float32)
            matrix, inliers = cv2.estimateAffinePartial2D(
                source, target, method=cv2.RANSAC, ransacReprojThreshold=3)
            if matrix is None or inliers is None:
                continue
            confidence = float(np.mean(inliers))
            scale = float(np.linalg.norm(matrix[:, 0]))
            if (np.count_nonzero(inliers) < 4 or confidence < self.threshold
                    or not .1 <= scale <= 2 or abs(matrix[1, 0]) > scale * .35):
                continue
            name, sprite_width, sprite_height = self.variants[variant]
            corners = np.asarray([[[0, 0], [sprite_width, 0],
                                   [sprite_width, sprite_height], [0, sprite_height]]], np.float32)
            transformed = cv2.transform(corners, matrix)[0]
            left, top = transformed.min(axis=0)
            right, bottom = transformed.max(axis=0)
            box = (float(left), float(top), float(right - left), float(bottom - top))
            if (min(box[2:]) >= 10 and max(box[2:]) <= 300
                    and visible_target(box, (width, height), excluded_regions)):
                candidates.append(FishDetection(name, box, confidence))
        kept = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if all(overlap(candidate.box, previous.box) < .25 for previous in kept):
                kept.append(candidate)
        return kept


@dataclass
class FishTrack:
    identifier: int
    name: str
    box: tuple[float, float, float, float]
    confidence: float
    points: np.ndarray | None = None
    velocity: tuple[float, float] = (0.0, 0.0)
    missed_frames: int = 0


class FishTracker:
    def __init__(self, max_missed_frames: int = 3):
        if type(max_missed_frames) is not int or max_missed_frames < 0:
            raise ValueError("Maximum missed frames must be a nonnegative integer.")
        self.max_missed_frames = max_missed_frames
        self.tracks: list[FishTrack] = []
        self.previous_gray = None
        self.next_id = 1

    def clear(self) -> None:
        self.tracks.clear()
        self.previous_gray = None

    def update(self, image, detections: list[FishDetection], excluded_regions=()) -> list[FishTrack]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        for track in self.tracks:
            delta_x, delta_y = track.velocity
            if self.previous_gray is not None and track.points is not None:
                moved, valid, _ = cv2.calcOpticalFlowPyrLK(self.previous_gray, gray, track.points, None)
                if moved is not None:
                    returned, reverse_valid, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous_gray, moved, None)
                    if returned is not None:
                        residual = np.linalg.norm(returned - track.points, axis=2).reshape(-1)
                        good = (valid.reshape(-1) > 0) & (reverse_valid.reshape(-1) > 0) & (residual < 1.5)
                        if np.count_nonzero(good) >= 3:
                            movement = moved[good] - track.points[good]
                            delta_x, delta_y = np.median(movement.reshape(-1, 2), axis=0)
            track.box = (track.box[0] + float(delta_x), track.box[1] + float(delta_y), *track.box[2:])
            track.velocity = (float(delta_x), float(delta_y))
        self.tracks = [track for track in self.tracks
                       if visible_target(track.box, (width, height), excluded_regions)]
        unmatched = [detection for detection in detections
                     if visible_target(detection.box, (width, height), excluded_regions)]
        for track in self.tracks:
            track.missed_frames += 1
            matches = [detection for detection in unmatched if detection.name == track.name
                       and overlap(detection.box, track.box) > .2]
            if matches:
                match = max(matches, key=lambda detection: overlap(detection.box, track.box))
                track.box, track.confidence = match.box, match.confidence
                track.missed_frames = 0
                unmatched.remove(match)
            self.tracks = [track for track in self.tracks if track.missed_frames <= self.max_missed_frames]
        for detection in unmatched:
            self.tracks.append(FishTrack(self.next_id, detection.name, detection.box, detection.confidence))
            self.next_id += 1
        for track in self.tracks:
            left, top, box_width, box_height = track.box
            mask = np.zeros_like(gray)
            mask[max(0, int(top)):min(height, int(top + box_height)),
                 max(0, int(left)):min(width, int(left + box_width))] = 255
            track.points = cv2.goodFeaturesToTrack(gray, maxCorners=24, qualityLevel=.02,
                                                   minDistance=4, mask=mask)
        self.previous_gray = gray
        return list(self.tracks)


def annotate_frame(image, tracks: list[FishTrack]):
    result = image.copy()
    for track in tracks:
        left, top, width, height = track.box
        center = (round(left + width / 2), round(top + height / 2))
        radius = round(max(width, height) * .36)
        cv2.circle(result, center, radius, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.circle(result, center, radius, (0, 55, 255), 3, cv2.LINE_AA)
    return result