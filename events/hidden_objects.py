"""Hidden-object event; run explicitly from its event/round screen.

Reference coordinates are scoped to scene and exact resolution. Local image
analysis also proposes locations without a map. New names are queued locally;
candidate coordinates are saved only after the corresponding target is crossed
out and progress increases. No hint or purchase is tapped.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import pytesseract

import config
from adb_controller import ADBController, ContinuousCapture
from events.hidden_objects_vision import ImageCandidates, image_candidates
from tasks.base import Outcome
from vision import find_template


_REFERENCE = config.BASE_DIR / "knowledge" / "hidden_objects.json"
_LEARNED = config.BASE_DIR / "memory" / "hidden_objects.json"
_ROUND_MARKER = "hidden_objects_round_marker.png"
_EVENT_MARKER = "hidden_objects_event_icon.png"
_PRACTICE_BUTTON = "hidden_objects_practice_button.png"
_PRACTICE_CORNER = "hidden_objects_practice_corner.png"
_TIMEOUT_MARKERS = ("hidden_objects_timeout.png", "hidden_objects_timeout_en.png")
_SUCCESS_MARKER = "hidden_objects_success.png"
_CONFIRM_SECONDS = 2.5
_RESULT_GRACE_SECONDS = 5.0
_MISS_RADIUS = 8


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


class ObjectMap:
    def __init__(self, reference: Path = _REFERENCE, learned: Path = _LEARNED):
        self.reference = _read_json(reference)
        self.path = learned
        self.learned = _read_json(learned) if learned.exists() else {"scenes": {}}
        self._backgrounds: dict[str, np.ndarray | None] = {}
        if not isinstance(self.learned.get("scenes"), dict):
            raise ValueError(f"Invalid scenes in {learned}")

    def background(self, scene: str) -> np.ndarray | None:
        if scene not in self._backgrounds:
            filename = self.reference["scenes"][scene].get("background")
            image = None
            if filename is not None:
                path = config.TEMPLATES_DIR / filename
                if not path.is_file():
                    raise FileNotFoundError(f"Clean background not found: {path}")
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError(f"Could not decode clean background: {path}")
                x1, y1, x2, y2 = self.reference["scene_region"]
                if image.shape != (y2 - y1, x2 - x1, 3):
                    raise ValueError(f"Clean background has wrong crop dimensions: {path}")
                image.setflags(write=False)
            self._backgrounds[scene] = image
        return self._backgrounds[scene]

    def _bucket_key(self, scene: str) -> str:
        width, height = self.reference["resolution"]
        return f"{scene}:{width}x{height}"

    def canonical_name(self, name: str) -> str:
        return self.reference.get("name_aliases", {}).get(normalize_name(name), name)

    def coordinates(self, scene: str, name: str) -> tuple[int, int] | None:
        key = normalize_name(self.canonical_name(name))
        bucket = self.learned["scenes"].get(self._bucket_key(scene), {})
        learned = bucket.get("objects", {}).get(key)
        if learned is not None:
            return self._validate_point(learned["point"])
        for label, point in self.reference["scenes"][scene]["objects"].items():
            if normalize_name(label) == key:
                return self._validate_point(point)
        return None

    def _validate_point(self, point) -> tuple[int, int]:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(type(v) is not int for v in point)):
            raise ValueError(f"Invalid object coordinates: {point!r}")
        x, y = point
        x1, y1, x2, y2 = self.reference["scene_region"]
        if not (x1 <= x < x2 and y1 <= y < y2):
            raise ValueError(f"Object coordinates outside scene: {point!r}")
        return x, y

    def _bucket(self, scene: str) -> dict:
        return self.learned["scenes"].setdefault(
            self._bucket_key(scene), {"objects": {}, "pending": []})

    def candidates(self, scene: str, name: str) -> list[tuple[int, int]]:
        name = self.canonical_name(name)
        specific = self.reference.get("name_candidates", {}).get(name, [])
        bucket = self.learned["scenes"].get(self._bucket_key(scene), {})
        points = specific + self.reference.get("candidate_points", [])
        points += list(self.reference["scenes"][scene]["objects"].values())
        points += [value["point"] for value in bucket.get("objects", {}).values()]
        return list(dict.fromkeys(self._validate_point(p) for p in points))

    def queue(self, scene: str, name: str) -> None:
        name = self.canonical_name(name)
        pending = self._bucket(scene)["pending"]
        if not any(normalize_name(self.canonical_name(n)) == normalize_name(name)
                   for n in pending):
            pending.append(name)
            self._save()

    def was_missed(self, scene: str, name: str, point: tuple[int, int]) -> bool:
        key = normalize_name(self.canonical_name(name))
        bucket = self.learned["scenes"].get(self._bucket_key(scene), {})
        for old in bucket.get("misses", {}).get(key, []):
            x, y = self._validate_point(old)
            if (point[0] - x) ** 2 + (point[1] - y) ** 2 <= _MISS_RADIUS ** 2:
                return True
        return False

    def record_miss(self, scene: str, name: str, point: tuple[int, int]) -> None:
        name = self.canonical_name(name)
        point = self._validate_point(point)
        if self.was_missed(scene, name, point):
            return
        points = self._bucket(scene).setdefault("misses", {}).setdefault(
            normalize_name(name), [])
        points.append(list(point))
        self._save()

    def confirm(self, scene: str, name: str, point: tuple[int, int]) -> None:
        name = self.canonical_name(name)
        point = self._validate_point(point)
        bucket = self._bucket(scene)
        key = normalize_name(name)
        for old_key, value in list(bucket["objects"].items()):
            if old_key != key and normalize_name(self.canonical_name(value["name"])) == key:
                del bucket["objects"][old_key]
        bucket["objects"][key] = {"name": name, "point": list(point)}
        bucket.get("misses", {}).pop(key, None)
        bucket["pending"] = [
            n for n in bucket["pending"]
            if normalize_name(self.canonical_name(n)) != key
            and self.coordinates(scene, n) is None]
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.learned, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        temporary.replace(self.path)


@dataclass(frozen=True)
class Target:
    slot: int
    name: str


class ScreenController(Protocol):
    def screenshot(self) -> np.ndarray: ...
    def tap(self, x: int, y: int) -> None: ...


class RoundCapture:
    """Serial actions with concurrent frames; never reuse a pre-action capture."""

    def __init__(self, controller: ADBController, capture: ContinuousCapture):
        self.controller = controller
        self.capture = capture
        self.sequence = -1
        self.frame_started_at = 0.0
        self.shape: tuple[int, ...] | None = None
        self.not_before = 0.0
        self.deadline = float("inf")
        self.action_deadline = float("inf")
        self.taps = 0
        self.tap_seconds = 0.0
        self.frame_wait_seconds = 0.0
        self.confirmation_seconds = 0.0
        self.ocr_seconds = 0.0
        self.ocr_groups = 0
        self.candidates: ImageCandidates | None = None

    def screenshot(self) -> np.ndarray:
        if self.candidates is not None:
            self.candidates.raise_if_failed()
        started = time.monotonic()
        budget = min(2.5, self.deadline - started)
        if budget <= 0:
            raise TimeoutError("Hidden Objects round deadline reached.")
        try:
            frame = self.capture.next_frame(self.sequence, self.not_before, budget)
        except TimeoutError as exc:
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Hidden Objects round deadline reached.") from exc
            raise
        if self.shape is not None and frame.image.shape != self.shape:
            raise RuntimeError("Emulator resolution changed during Hidden Objects.")
        self.shape = frame.image.shape
        self.frame_wait_seconds += time.monotonic() - started
        self.sequence = frame.sequence
        self.frame_started_at = frame.started_at
        return frame.image

    def tap(self, x: int, y: int) -> None:
        if time.monotonic() >= min(self.deadline, self.action_deadline):
            raise TimeoutError("Hidden Objects round deadline reached before tap.")
        started = time.monotonic()
        self.controller.tap(x, y)
        self.not_before = time.monotonic()
        self.tap_seconds += self.not_before - started
        self.taps += 1

    def report(self) -> None:
        elapsed = max(.001, self.capture.stopped_at - self.capture.started_at)
        average = self.capture.capture_seconds / max(1, self.capture.frames)
        print(f"[Hidden Objects] Capture: {self.capture.frames / elapsed:.1f} FPS, "
              f"{average * 1000:.0f}ms/frame; "
              f"OCR: {self.ocr_groups} groups in {self.ocr_seconds:.2f}s; "
              f"taps: {self.taps} in {self.tap_seconds:.2f}s; "
              f"confirmation: {self.confirmation_seconds:.2f}s; "
              f"fresh-frame wait: {self.frame_wait_seconds:.2f}s "
              "(timings overlap while capture runs in parallel).")
        if self.candidates is not None:
            print(f"[Hidden Objects] Image proposals: {self.candidates.frames} frames "
                  f"in {self.candidates.analysis_seconds:.2f}s (parallel local analysis).")


def crop(screen: np.ndarray, region) -> np.ndarray:
    x1, y1, x2, y2 = region
    return screen[y1:y2, x1:x2]


def white_text(cropped: np.ndarray) -> np.ndarray:
    return cv2.inRange(cropped, (175, 175, 175), (255, 255, 255))


def read_targets(screen: np.ndarray, regions) -> list[Target]:
    targets = []
    for slot, region in enumerate(regions):
        mask = white_text(crop(screen, region))
        # Crossed-out labels turn dark. Avoid OCR hallucinations on empty pills.
        if cv2.countNonZero(mask) < 30:
            continue
        image = cv2.resize(255 - mask, None, fx=4, fy=4,
                           interpolation=cv2.INTER_CUBIC)
        raw = pytesseract.image_to_string(
            image, config="--psm 6", timeout=2).strip()
        name = " ".join(raw.split())
        if not normalize_name(name):
            raise ValueError(f"Could not read object name in slot {slot + 1}")
        targets.append(Target(slot, name))
    return targets


def _progress_mask(screen: np.ndarray, region) -> np.ndarray:
    hsv = cv2.cvtColor(crop(screen, region), cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (15, 100, 160), (40, 255, 255))


def progress_count(screen: np.ndarray, region) -> int:
    filled = np.mean(_progress_mask(screen, region) != 0, axis=0) > .5
    return int(np.count_nonzero(np.diff(np.r_[False, filled].astype(np.int8)) == 1))


def _progress_pixels(screen: np.ndarray, region) -> int:
    return cv2.countNonZero(_progress_mask(screen, region))


def _changed_at_click(before: np.ndarray, after: np.ndarray,
                      point: tuple[int, int], region) -> bool:
    x1, y1, x2, y2 = region
    delta = cv2.absdiff(before[y1:y2, x1:x2], after[y1:y2, x1:x2])
    mask = (np.max(delta, axis=2) > 25).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    changed = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= 12]
    if len(changed) != 1:
        return False
    x, y, width, height = changed[0]
    px, py = point[0] - x1, point[1] - y1
    local = mask[max(0, py - 2):py + 3, max(0, px - 2):px + 3]
    return (width <= 140 and height <= 140
            and x1 + x - 3 <= point[0] <= x1 + x + width + 3
            and y1 + y - 3 <= point[1] <= y1 + y + height + 3
            and cv2.countNonZero(local) >= 6)


def _target_confirmed(before: np.ndarray, after: np.ndarray, target: Target,
                      reference: dict, last_target: bool) -> bool:
    region = reference["target_regions"][target.slot]
    current = white_text(crop(after, region))
    return (cv2.countNonZero(current) < 30
            or (last_target and np.mean(cv2.absdiff(
                white_text(crop(before, region)), current)) > 5))


def remaining_seconds(screen: np.ndarray, region) -> int:
    cropped = crop(screen, region)
    mask = cv2.bitwise_or(white_text(cropped),
                         cv2.inRange(cropped, (0, 0, 160), (100, 100, 255)))
    image = cv2.resize(255 - mask, None, fx=4, fy=4,
                       interpolation=cv2.INTER_CUBIC)
    raw = pytesseract.image_to_string(
        image, config="--psm 7 -c tessedit_char_whitelist=0123456789s",
        timeout=2).strip()
    match = re.fullmatch(r"(\d{1,3})\s*s?", raw)
    if match is None:
        raise ValueError(f"Could not read round timer: {raw!r}")
    return int(match[1])


def is_timeout(screen: np.ndarray) -> bool:
    return any(find_template(screen, marker).found for marker in _TIMEOUT_MARKERS)


def round_result(screen: np.ndarray) -> str | None:
    if is_timeout(screen):
        return Outcome.FAILED
    if find_template(screen, _SUCCESS_MARKER).found:
        return Outcome.SUCCESS
    return None


class HiddenObjectsEvent:
    name = "Hidden Objects (Sorte de Quem Procura)"
    requires_profile = False

    def execute(self, controller: ADBController) -> str:
        object_map = ObjectMap()
        screen = controller.screenshot()
        width, height = object_map.reference["resolution"]
        if screen.shape[:2] != (height, width):
            print(f"[Hidden Objects] Unsupported resolution {screen.shape[1]}x"
                  f"{screen.shape[0]}; expected {width}x{height}. No taps sent.")
            return Outcome.FAILED
        result = round_result(screen)
        if result is not None:
            print(f"[Hidden Objects] Result screen detected: {result}.")
            return result

        if find_template(screen, _EVENT_MARKER).found:
            button = find_template(screen, _PRACTICE_BUTTON)
            if button.found:
                practice_tap = (button.x, button.y)
            else:
                corner = find_template(screen, _PRACTICE_CORNER, .95)
                practice_tap = (corner.x + 104, corner.y) if corner.found else None
            if practice_tap is None:
                print("[Hidden Objects] Open a stage manually; no practice button.")
                return Outcome.ABSENT
            controller.tap(*practice_tap)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                screen = controller.screenshot()
                if find_template(screen, _ROUND_MARKER).found:
                    break
                time.sleep(.15)
        if not find_template(screen, _ROUND_MARKER).found:
            print("[Hidden Objects] Open Sorte de Quem Procura or an active round "
                  "before selecting this individual task.")
            return Outcome.ABSENT

        scene = next((key for key, value in object_map.reference["scenes"].items()
                      if find_template(screen, value["marker"], .9).found), None)
        if scene is None:
            print("[Hidden Objects] Unmapped landscape; no coordinates reused.")
            return Outcome.FAILED
        background = object_map.background(scene)
        if background is not None:
            print("[Hidden Objects] Clean-background pixel comparison enabled.")
        capture = ContinuousCapture(controller)
        live = RoundCapture(controller, capture)
        live.shape = screen.shape
        try:
            with capture:
                screen = live.screenshot()
                with ImageCandidates(capture, object_map.reference["scene_region"],
                                     background) as candidates:
                    live.candidates = candidates
                    return self._solve(live, screen, scene, object_map)
        except TimeoutError as exc:
            print(f"[Hidden Objects] Stopped waiting for frames: {exc}")
            return Outcome.FAILED
        finally:
            live.report()

    def _solve(self, controller: ScreenController, screen: np.ndarray, scene: str,
               object_map: ObjectMap) -> str:
        started = time.monotonic()
        reference = object_map.reference
        result = round_result(screen)
        if result is not None:
            print(f"[Hidden Objects] Result screen detected: {result}.")
            return result
        seconds = remaining_seconds(screen, reference["timer_region"])
        timer_started = (controller.frame_started_at
                         if isinstance(controller, RoundCapture) else started)
        deadline = timer_started + seconds
        result_deadline = deadline + _RESULT_GRACE_SECONDS
        if isinstance(controller, RoundCapture):
            controller.action_deadline = deadline
            controller.deadline = result_deadline
        found_points: list[tuple[int, int]] = []
        attempted_points: list[tuple[int, int]] = []
        targets: list[Target] = []
        tracked_screen = screen
        blocked: set[int] = set()
        actions_paused = False
        while time.monotonic() < result_deadline:
            result = round_result(screen)
            if result is not None:
                print(f"[Hidden Objects] Result screen detected after "
                      f"{len(found_points)} confirmed items in "
                      f"{time.monotonic() - started:.2f}s: {result}.")
                return result
            if (time.monotonic() >= deadline
                    or not find_template(screen, _ROUND_MARKER).found):
                screen = controller.screenshot()
                continue
            progress = _progress_pixels(screen, reference["progress_region"])
            if progress != _progress_pixels(tracked_screen, reference["progress_region"]):
                screen, targets = self._reconcile_progress(
                    controller, tracked_screen, screen, targets, reference, result_deadline)
                tracked_screen = screen
                actions_paused = False
                if not targets:
                    blocked.clear()
                    attempted_points.clear()
                continue
            if actions_paused:
                screen = controller.screenshot()
                continue
            if not targets:
                ocr_started = time.monotonic()
                targets = read_targets(screen, reference["target_regions"])
                if isinstance(controller, RoundCapture):
                    controller.ocr_seconds += time.monotonic() - ocr_started
                    controller.ocr_groups += 1
                if not targets:
                    screen = self._settle_group(controller, screen, reference, result_deadline)
                    tracked_screen = screen
                    continue
                for target in targets:
                    if object_map.coordinates(scene, target.name) is None:
                        object_map.queue(scene, target.name)
                        print(f"[Hidden Objects] Unmapped target saved: {target.name}")
                # OCR runs in parallel with capture. Do not act on its old frame.
                screen = controller.screenshot()
                if round_result(screen) is not None:
                    continue
                if _progress_pixels(screen, reference["progress_region"]) != progress:
                    print("[Hidden Objects] Progress changed during OCR; reconciling manual input.")
                    continue
                tracked_screen = screen
            actionable = [t for t in targets if t.slot not in blocked]
            if not actionable:
                actions_paused = True
                screen = controller.screenshot()
                continue
            target = actionable[0]
            point = object_map.coordinates(scene, target.name)
            if point is None:
                ordered = [target] + [t for t in targets if t.slot != target.slot]
                explored = self._explore(controller, screen, ordered, progress,
                                         object_map, scene, found_points, deadline,
                                         attempted_points)
                if explored is None:
                    print(f"[Hidden Objects] No confirmed candidate for {target.name}; "
                          "pending name saved. Trying remaining names; no hints used.")
                    blocked.add(target.slot)
                    screen = controller.screenshot()
                    continue
                if isinstance(explored, np.ndarray):
                    screen = explored
                    continue
                screen, found, point = explored
                object_map.confirm(scene, found.name, point)
                targets = [t for t in targets if t.slot != found.slot]
                found_points.append(point)
                print(f"[Hidden Objects] Learned {found.name} -> {point}; "
                      f"{len(found_points)} items confirmed.")
                if not targets:
                    screen = self._settle_group(controller, screen, reference, result_deadline)
                    attempted_points.clear()
                    blocked.clear()
                tracked_screen = screen
                continue
            if time.monotonic() >= deadline:
                screen = controller.screenshot()
                continue
            controller.tap(*point)
            confirmation_started = time.monotonic()
            before = screen
            screen = self._wait_confirmation(controller, screen, target, progress,
                                             reference, result_deadline,
                                             last_target=len(targets) == 1)
            if isinstance(controller, RoundCapture):
                controller.confirmation_seconds += time.monotonic() - confirmation_started
            if screen is None:
                object_map.queue(scene, target.name)
                print(f"[Hidden Objects] Click not confirmed: {target.name} at {point}.")
                blocked.add(target.slot)
                screen = controller.screenshot()
                continue
            result = round_result(screen)
            if result is not None:
                continue
            if (not _target_confirmed(before, screen, target, reference, len(targets) == 1)
                    or not _changed_at_click(before, screen, point, reference["scene_region"])):
                print("[Hidden Objects] Progress without a unique change at the bot's click; "
                      "no coordinates attributed. Reconciling remaining names.")
                continue
            object_map.confirm(scene, target.name, point)
            targets = [t for t in targets if t.slot != target.slot]
            found_points.append(point)
            print(f"[Hidden Objects] {target.name} -> {point}; "
                  f"{len(found_points)} items confirmed.")
            if not targets:
                screen = self._settle_group(controller, screen, reference, result_deadline)
                attempted_points.clear()
                blocked.clear()
            tracked_screen = screen
        result = round_result(screen)
        if result is not None:
            print(f"[Hidden Objects] Result screen detected at observation deadline: {result}.")
            return result
        print("[Hidden Objects] No success/failure screen within the timer plus "
              f"{_RESULT_GRACE_SECONDS:.0f}s grace; stopping without assuming success.")
        return Outcome.FAILED

    @staticmethod
    def _reconcile_progress(controller: ScreenController, before: np.ndarray,
                            screen: np.ndarray, targets: list[Target], reference: dict,
                            deadline: float) -> tuple[np.ndarray, list[Target]]:
        until = min(deadline, time.monotonic() + _CONFIRM_SECONDS)
        previous = None
        while time.monotonic() < until:
            if round_result(screen) is not None:
                return screen, targets
            masks = [white_text(crop(screen, reference["target_regions"][t.slot]))
                     for t in targets]
            old = [white_text(crop(before, reference["target_regions"][t.slot]))
                   for t in targets]
            changed = not targets or any(np.mean(cv2.absdiff(a, b)) > 1
                                         for a, b in zip(old, masks))
            if (find_template(screen, _ROUND_MARKER).found and changed
                    and previous is not None
                    and all(np.mean(cv2.absdiff(a, b)) < 1
                            for a, b in zip(previous, masks))):
                replaced = any(cv2.countNonZero(b) >= 30
                               and np.mean(cv2.absdiff(a, b)) > 5
                               for a, b in zip(old, masks))
                remaining = [] if replaced else [
                    target for target, mask in zip(targets, masks)
                    if cv2.countNonZero(mask) >= 30]
                resolved = [t.name for t in targets if t not in remaining]
                print(f"[Hidden Objects] External/unattributed progress: {resolved}; "
                      "unmapped names remain pending, no guessed coordinates saved.")
                return screen, remaining
            previous = masks if changed else None
            screen = controller.screenshot()
        raise TimeoutError("Progress changed but requested labels did not settle for reconciliation.")

    @staticmethod
    def _settle_group(controller: ScreenController, screen: np.ndarray,
                      reference: dict, deadline: float) -> np.ndarray:
        previous = None
        while time.monotonic() < deadline:
            if round_result(screen) is not None:
                return screen
            masks = [white_text(crop(screen, region))
                     for region in reference["target_regions"]]
            ready = (find_template(screen, _ROUND_MARKER).found
                     and any(cv2.countNonZero(mask) >= 30 for mask in masks))
            if ready and previous is not None and all(
                    np.mean(cv2.absdiff(old, new)) < 1
                    for old, new in zip(previous, masks)):
                return screen
            previous = masks if ready else None
            screen = controller.screenshot()
        raise TimeoutError("No stable next group or result screen before the observation deadline.")

    def _explore(self, controller: ScreenController, screen: np.ndarray,
                 targets: list[Target], progress: int, object_map: ObjectMap,
                 scene: str, found_points: list[tuple[int, int]],
                 deadline: float, attempted_points: list[tuple[int, int]] | None = None
                 ) -> tuple[np.ndarray, Target, tuple[int, int]] | np.ndarray | None:
        reference = object_map.reference
        target = targets[0]
        other_points = [object_map.coordinates(scene, t.name) for t in targets[1:]]
        excluded = found_points + [p for p in other_points if p is not None]
        attempted = attempted_points if attempted_points is not None else []
        while time.monotonic() < deadline:
            if round_result(screen) is not None:
                return screen
            if isinstance(controller, RoundCapture) and controller.candidates is not None:
                budget = min(2.5, deadline - time.monotonic())
                if budget <= 0:
                    return None
                proposals = controller.candidates.latest(
                    controller.sequence, controller.not_before, budget).proposals
            else:
                proposals = image_candidates(screen, reference["scene_region"],
                                             object_map.background(scene))
            # A clean reference isolates present objects; old generic points
            # would reintroduce guesses at scenery and absent objects.
            mapped = (object_map.candidates(scene, target.name)
                      if object_map.background(scene) is None else [])
            visual = [proposal.point for proposal in proposals]
            points = []
            for index in range(max(len(mapped), len(visual))):
                if index < len(mapped):
                    points.append(mapped[index])
                if index < len(visual):
                    points.append(visual[index])
            candidates = [p for p in points
                          if not object_map.was_missed(scene, target.name, p)
                          and all(abs(p[0] - x) > 18 or abs(p[1] - y) > 18
                                 for x, y in excluded)
                          and all((p[0] - x) ** 2 + (p[1] - y) ** 2 > _MISS_RADIUS ** 2
                                  for x, y in attempted)]
            if not candidates:
                print(f"[Hidden Objects] No remaining image/map candidates for {target.name}.")
                return None
            point = candidates[0]
            if time.monotonic() >= deadline:
                return None
            if (is_timeout(screen)
                    or not find_template(screen, _ROUND_MARKER).found):
                print("[Hidden Objects] Round marker disappeared during exploration.")
                return None
            if _progress_pixels(screen, reference["progress_region"]) != progress:
                print("[Hidden Objects] Unattributed progress; reconciling without another guess.")
                return screen
            print(f"[Hidden Objects] Exploring {target.name} at {point}: "
                  f"{len(proposals)} image proposals, {len(candidates)} remaining; no hints.")
            controller.tap(*point)
            attempted.append(point)
            confirmation_started = time.monotonic()
            # Do not issue the next guess before the preceding hit can settle.
            # A short window misattributes delayed progress to the next location.
            until = min(deadline, time.monotonic() + _CONFIRM_SECONDS)
            after = screen
            while time.monotonic() < until:
                after = controller.screenshot()
                result = round_result(after)
                if result is not None:
                    return after
                if not find_template(after, _ROUND_MARKER).found:
                    print("[Hidden Objects] Exploration interrupted by an overlay; "
                          "no miss or coordinate saved.")
                    return after
                if _progress_pixels(after, reference["progress_region"]) > progress:
                    # The bar advances before the label's strike-through fades.
                    # Stop tapping and wait to identify which name actually changed.
                    confirmation_until = min(deadline, time.monotonic() + _CONFIRM_SECONDS)
                    while time.monotonic() < confirmation_until:
                        result = round_result(after)
                        if result is not None:
                            return after
                        crossed = [
                            t for t in targets if cv2.countNonZero(white_text(
                                crop(after, reference["target_regions"][t.slot]))) < 30]
                        if len(crossed) == 1:
                            found = crossed[0]
                            if not _changed_at_click(
                                    screen, after, point, reference["scene_region"]):
                                after = controller.screenshot()
                                continue
                            if found != target:
                                print(f"[Hidden Objects] Candidate matched {found.name}, "
                                      f"not {target.name}; recording the actual target.")
                            if isinstance(controller, RoundCapture):
                                controller.confirmation_seconds += (
                                    time.monotonic() - confirmation_started)
                            return after, found, point
                        if len(targets) == 1:
                            confirmed = self._wait_confirmation(
                                controller, screen, target, progress, reference, deadline,
                                last_target=True)
                            if confirmed is not None:
                                if round_result(confirmed) == Outcome.FAILED:
                                    return confirmed
                                if round_result(confirmed) == Outcome.SUCCESS:
                                    return confirmed
                                if not _changed_at_click(
                                        screen, confirmed, point, reference["scene_region"]):
                                    return confirmed
                                if isinstance(controller, RoundCapture):
                                    controller.confirmation_seconds += (
                                        time.monotonic() - confirmation_started)
                                return confirmed, target, point
                            break
                        after = controller.screenshot()
                    print("[Hidden Objects] Manual/ambiguous candidate hit; no coordinates saved.")
                    return after
            if isinstance(controller, RoundCapture):
                controller.confirmation_seconds += time.monotonic() - confirmation_started
            if (time.monotonic() >= confirmation_started + _CONFIRM_SECONDS
                    and round_result(after) is None
                    and find_template(after, _ROUND_MARKER).found
                    and _progress_pixels(after, reference["progress_region"]) == progress
                    and all(cv2.countNonZero(white_text(crop(
                        after, reference["target_regions"][t.slot]))) >= 30
                        and np.mean(cv2.absdiff(
                            white_text(crop(screen, reference["target_regions"][t.slot])),
                            white_text(crop(after, reference["target_regions"][t.slot])))) < 1
                        for t in targets)):
                object_map.record_miss(scene, target.name, point)
                print(f"[Hidden Objects] Verified miss for {target.name} at {point}; "
                      f"excluding {_MISS_RADIUS}px radius in future attempts.")
            screen = after
        return None

    @staticmethod
    def _wait_confirmation(controller: ScreenController, before: np.ndarray,
                           target: Target, progress: int, reference: dict,
                           deadline: float, last_target: bool = False) -> np.ndarray | None:
        until = min(deadline, time.monotonic() + _CONFIRM_SECONDS)
        while time.monotonic() < until:
            screen = controller.screenshot()
            if round_result(screen) is not None:
                return screen
            if _progress_pixels(screen, reference["progress_region"]) > progress:
                if not last_target:
                    crossed_other = any(
                        slot != target.slot
                        and cv2.countNonZero(white_text(crop(before, other))) >= 30
                        and cv2.countNonZero(white_text(crop(screen, other))) < 30
                        for slot, other in enumerate(reference["target_regions"]))
                    if crossed_other:
                        return screen
                # Either this name is crossed out or a completed trio was replaced.
                if _target_confirmed(before, screen, target, reference, last_target):
                    return screen
        return None


EVENT = HiddenObjectsEvent()
