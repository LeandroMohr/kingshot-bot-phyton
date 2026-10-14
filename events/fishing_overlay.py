"""Click-through macOS fish highlights drawn above the emulator window."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import cv2

import config
from adb_controller import ADBController, ContinuousCapture
from events.fishing_highlight import (CatalogDetector, FishDetector, FishTracker, fishing_hud_regions,
                                     brighten_dark_frame, brightness_layer)
from events.fishing_tournament import has_pause_icon


def pending_entries(entries: list[dict], collection: dict) -> list[dict]:
    result = []
    for entry in entries:
        captured = collection.get(str(entry["id"]), {}).get("captured")
        if captured is not None and type(captured) is not bool:
            raise ValueError("Captured state must be true, false or null.")
        if captured is not True:
            result.append({**entry, "capture_status": "missing" if captured is False else "unknown"})
    return result


def update_target_list(entries: list[dict], collection: dict, references: dict,
                       destination: Path) -> dict:
    indexed = {entry["id"]: entry for entry in references["entries"]}
    previous = (json.loads(destination.read_text(encoding="utf-8"))
                if destination.exists() else {"entries": []})
    enabled = {entry["id"]: entry.get("enabled", True) for entry in previous["entries"]}
    targets = []
    for entry in pending_entries(entries, collection):
        reference = indexed[entry["id"]]
        targets.append({"id": entry["id"], "name": entry["name"],
                        "category": entry["category"], "enabled": enabled.get(entry["id"], True),
                        "capture_status": entry["capture_status"], "points": entry["points"],
                        "depth": entry["depth"], "available_seasons": reference["available_seasons"],
                        "reference": "templates/fishing_references/" + reference["file"]})
    result = {"reference_type": "experimental_handbook", "calibrated_for_gameplay": False,
              "includes_unknown": True, "entries": targets}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def load_target_references(path: Path, base_dir: Path) -> tuple[dict[str, Path], dict[str, str]]:
    targets = json.loads(path.read_text(encoding="utf-8"))["entries"]
    references, statuses = {}, {}
    for target in targets:
        enabled = target.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError("Target enabled state must be true or false.")
        if not enabled:
            continue
        status = target["capture_status"]
        if status not in ("missing", "unknown"):
            raise ValueError("Highlight target must be missing or unknown.")
        if target["name"] in references:
            raise ValueError(f"Duplicate target name: {target['name']}")
        reference = base_dir / target["reference"]
        if not reference.is_file():
            raise FileNotFoundError(f"Missing target reference: {reference}")
        references[target["name"]] = reference
        statuses[target["name"]] = status
    return references, statuses


def game_bounds(bounds: dict, frame_size: tuple[int, int], insets: tuple[float, ...]) -> dict:
    left, top, right, bottom = insets
    frame_width, frame_height = frame_size
    width = bounds["Width"] - left - right
    height = bounds["Height"] - top - bottom
    if min(width, height, frame_width, frame_height) <= 0 or min(insets) < 0:
        raise ValueError("Invalid game viewport or window insets.")
    scale = min(width / frame_width, height / frame_height)
    return {"X": bounds["X"] + left + (width - frame_width * scale) / 2,
            "Y": bounds["Y"] + top + (height - frame_height * scale) / 2,
            "Width": frame_width * scale, "Height": frame_height * scale}


def choose_window(windows: list[dict], identifier: int | None = None) -> dict:
    candidates = [window for window in windows
                  if "bluestacks" in window.get("kCGWindowOwnerName", "").lower()
                  and window.get("kCGWindowLayer", 0) == 0
                  and window.get("kCGWindowBounds", {}).get("Width", 0) > 200
                  and window.get("kCGWindowBounds", {}).get("Height", 0) > 300]
    if identifier is not None:
        candidates = [window for window in candidates if window["kCGWindowNumber"] == identifier]
    if len(candidates) != 1:
        identifiers = [window["kCGWindowNumber"] for window in candidates]
        raise RuntimeError(f"Choose one visible BlueStacks window with --window-id; candidates: {identifiers}")
    return candidates[0]


class HighlightWorker:
    def __init__(self, controller: ADBController, detector: FishDetector,
                 brighten: bool = False):
        self.controller, self.detector = controller, detector
        self.brighten = brighten
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.state = {"tracks": [], "frame_size": (540, 960), "completed_at": 0.0}
        self.frames = 0
        self.maximum_instances = 0
        self.maximum_frame_age = 0.0
        self.processing_seconds = 0.0
        self.error = None
        self.thread = threading.Thread(target=self.run, name="fish-highlight", daemon=True)

    def run(self) -> None:
        tracker = FishTracker()
        previous_time = 0.0
        try:
            with ContinuousCapture(self.controller, max_timeout_retries=2) as capture:
                sequence = 0
                while not self.stop.is_set():
                    try:
                        frame = capture.next_frame(sequence)
                    except TimeoutError:
                        tracker.clear()
                        previous_time = 0.0
                        with self.lock:
                            self.state = {**self.state, "tracks": [], "completed_at": 0.0,
                                          "brightness_png": None}
                        continue
                    sequence = frame.sequence
                    if previous_time and frame.started_at - previous_time > .5:
                        tracker.clear()
                        previous_time = 0.0
                    started = time.monotonic()
                    brightness_png = None
                    if has_pause_icon(frame.image):
                        excluded = fishing_hud_regions((frame.image.shape[1], frame.image.shape[0]))
                        image = frame.image
                        if self.brighten:
                            image = brighten_dark_frame(frame.image, excluded)
                            layer = brightness_layer(frame.image, image)
                            success, encoded = cv2.imencode(".png", layer, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                            if not success:
                                raise RuntimeError("Could not encode brightness overlay.")
                            brightness_png = encoded.tobytes()
                        detections = self.detector.detect(image, excluded_regions=excluded)
                        tracks = tracker.update(image, detections, excluded_regions=excluded)
                    else:
                        tracker.clear()
                        tracks = []
                    interval = frame.completed_at - previous_time if previous_time else .1
                    previous_time = frame.completed_at
                    snapshot = [{"id": track.identifier, "name": track.name, "box": track.box,
                                 "velocity": (track.velocity[0] / max(interval, .001),
                                              track.velocity[1] / max(interval, .001))}
                                for track in tracks]
                    with self.lock:
                        self.state = {"tracks": snapshot,
                                      "frame_size": (frame.image.shape[1], frame.image.shape[0]),
                                      "completed_at": frame.completed_at,
                                      "brightness_png": brightness_png}
                    self.frames += 1
                    self.maximum_instances = max(self.maximum_instances, len(tracks))
                    self.processing_seconds += time.monotonic() - started
        except Exception as exc:
            self.error = str(exc)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("Fish highlight worker did not stop.")


def run_overlay(controller: ADBController, detector: FishDetector,
                window_id: int | None = None, insets: tuple[float, ...] = (0, 30, 32, 0),
                duration: float | None = None, snapshot: Path | None = None,
                report_path: Path | None = None, brighten: bool = False,
                target_statuses: dict[str, str] | None = None) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("The click-through overlay currently requires macOS.")
    if duration is not None and duration <= 0:
        raise ValueError("Overlay duration must be positive.")
    import AppKit
    import Quartz
    import objc
    from Foundation import NSData

    def visible_windows():
        return Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,
                                                Quartz.kCGNullWindowID)

    target = choose_window(visible_windows(), window_id)
    identifier = target["kCGWindowNumber"]
    controller.connect()
    worker = HighlightWorker(controller, detector, brighten=brighten)
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (100, 100)), AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered, False)
    window.setReleasedWhenClosed_(False)
    window.setOpaque_(False)
    window.setBackgroundColor_(AppKit.NSColor.clearColor())
    window.setIgnoresMouseEvents_(True)
    window.setHasShadow_(False)
    window.setLevel_(AppKit.NSFloatingWindowLevel)
    window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                  | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)

    class FishHighlightView(AppKit.NSView):
        def isFlipped(self):
            return True

        def drawRect_(self, rect):
            AppKit.NSColor.clearColor().set()
            AppKit.NSRectFillUsingOperation(rect, AppKit.NSCompositingOperationCopy)
            if self.brightness_image is not None:
                self.brightness_image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                    self.bounds(), AppKit.NSZeroRect, AppKit.NSCompositingOperationSourceOver,
                    1.0, True, None)
            frame_width, frame_height = self.frame_size
            scale_x = self.bounds().size.width / frame_width
            scale_y = self.bounds().size.height / frame_height
            age = min(.15, max(0, time.monotonic() - self.completed_at))
            for track in self.tracks:
                left, top, width, height = track["box"]
                delta_x, delta_y = track["velocity"]
                center_x = (left + width / 2 + delta_x * age) * scale_x
                center_y = (top + height / 2 + delta_y * age) * scale_y
                radius = max(width, height) * .36 * min(scale_x, scale_y)
                path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    ((center_x - radius, center_y - radius), (radius * 2, radius * 2)))
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, .85).setStroke()
                path.setLineWidth_(5)
                path.stroke()
                unknown = self.target_statuses.get(track["name"]) == "unknown"
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1, .7 if unknown else .16, .1, 1).setStroke()
                path.setLineWidth_(3)
                path.stroke()
                if self.target_statuses:
                    text = track["name"] + (" ?" if unknown else "")
                    AppKit.NSString.stringWithString_(text).drawAtPoint_withAttributes_(
                        (max(0, min(center_x - radius, self.bounds().size.width - 180)),
                         max(0, center_y - radius - 16)),
                        {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(10),
                         AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
                         AppKit.NSBackgroundColorAttributeName: AppKit.NSColor.blackColor()})

    view = FishHighlightView.alloc().initWithFrame_(((0, 0), (100, 100)))
    view.tracks = []
    view.frame_size = (540, 960)
    view.completed_at = 0.0
    view.brightness_image = None
    view.target_statuses = target_statuses or {}
    window.setContentView_(view)
    started = time.monotonic()
    report = {"serial": controller.serial, "window_id": identifier,
              "click_through": bool(window.ignoresMouseEvents()), "insets": list(insets),
              "brighten": brighten, "targets": target_statuses or {},
              "experimental_catalog": isinstance(detector, CatalogDetector),
              "unusable_references": getattr(detector, "rejected", {})}

    class OverlayTimer(AppKit.NSObject):
        @objc.typedSelector(b"v@:@")
        def tick_(self, timer):
            if worker.error or (duration is not None and time.monotonic() - started >= duration):
                application.stop_(None)
                return
            with worker.lock:
                state = worker.state
            age = time.monotonic() - state["completed_at"]
            if state["completed_at"]:
                worker.maximum_frame_age = max(worker.maximum_frame_age, age)
            if time.monotonic() >= self.next_window_check:
                self.next_window_check = time.monotonic() + .25
                candidates = [item for item in visible_windows() if item.get("kCGWindowNumber") == identifier]
                self.target_window = candidates[0] if candidates else None
            target_window = self.target_window
            active = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if (target_window is None or active.processIdentifier() != target_window["kCGWindowOwnerPID"]
                    or age > .5):
                window.orderOut_(None)
                return
            viewport = game_bounds(target_window["kCGWindowBounds"], state["frame_size"], insets)
            primary_height = AppKit.NSScreen.screens()[0].frame().size.height
            window.setFrame_display_(((viewport["X"], primary_height - viewport["Y"] - viewport["Height"]),
                                      (viewport["Width"], viewport["Height"])), False)
            view.frame_size, view.tracks = state["frame_size"], state["tracks"]
            view.completed_at = state["completed_at"]
            if state["completed_at"] != self.brightness_frame_time:
                self.brightness_frame_time = state["completed_at"]
                content = state.get("brightness_png")
                view.brightness_image = (AppKit.NSImage.alloc().initWithData_(
                    NSData.dataWithBytes_length_(content, len(content))) if content else None)
            view.setNeedsDisplay_(True)
            window.orderFrontRegardless()
            if (snapshot and not self.snapshot_saved
                    and (len(view.tracks) >= 2 or view.brightness_image is not None)):
                view.displayIfNeeded()
                bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
                view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
                bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(str(snapshot), True)
                self.snapshot_saved = True
            report["viewport"] = viewport

    timer_target = OverlayTimer.alloc().init()
    timer_target.next_window_check = 0.0
    timer_target.target_window = target
    timer_target.snapshot_saved = False
    timer_target.brightness_frame_time = 0.0
    timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1 / 30, timer_target, "tick:", None, True)
    target_application = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(target["kCGWindowOwnerPID"])
    target_application.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    worker.thread.start()
    print(f"Fish overlay active above BlueStacks window {identifier}; mouse events pass through.", flush=True)
    try:
        application.run()
    except KeyboardInterrupt:
        pass
    finally:
        timer.invalidate()
        window.orderOut_(None)
        worker.close()
        report.update({"frames": worker.frames, "maximum_instances": worker.maximum_instances,
                       "elapsed_seconds": round(time.monotonic() - started, 3),
                       "mean_processing_ms": round(worker.processing_seconds / max(worker.frames, 1) * 1000, 2),
                       "maximum_frame_age_ms": round(worker.maximum_frame_age * 1000, 2),
                       "snapshot_saved": timer_target.snapshot_saved, "error": worker.error})
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)
    if worker.error:
        raise RuntimeError(worker.error)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--host", default=config.ADB_HOST)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--fish", nargs="+", help="Use explicitly named native ADB templates")
    selection.add_argument("--targets", type=Path, help="Editable experimental catalog target list")
    parser.add_argument("--update-targets", action="store_true",
                        help="Refresh the editable list from collection state and exit")
    parser.add_argument("--window-id", type=int)
    parser.add_argument("--insets", type=float, nargs=4, default=(0, 30, 32, 0),
                        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--threshold", type=float, default=.94)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--brighten", action="store_true",
                        help="Brighten recoverable dark pixels in the click-through overlay")
    args = parser.parse_args()
    entries = json.loads((config.BASE_DIR / "knowledge/fishing_catalog.json").read_text(encoding="utf-8"))["entries"]
    target_path = args.targets or config.BASE_DIR / "memory" / f"fishing_highlight_targets_{args.port}.json"
    if args.update_targets or args.fish is None:
        collection_path = config.BASE_DIR / "memory" / f"fishing_collection_{args.port}.json"
        collection = json.loads(collection_path.read_text(encoding="utf-8"))["entries"]
        index = json.loads((config.BASE_DIR / "templates/fishing_references/index.json").read_text(encoding="utf-8"))
        result = update_target_list(entries, collection, index, target_path)
        print(f"Updated {len(result['entries'])} missing or unknown targets: {target_path}")
        if args.update_targets:
            return
    target_statuses = None
    references = {}
    if args.fish is None:
        references, target_statuses = load_target_references(target_path, config.BASE_DIR)
        detector = CatalogDetector(references, threshold=args.threshold)
        print(f"Experimental catalog mode: {len(references)} enabled targets; "
              f"{len(detector.rejected)} references lack usable visual features.", flush=True)
    else:
        for name in args.fish:
            entry = next((entry for entry in entries if entry["name"].lower() == name.lower()), None)
            if entry is None:
                parser.error(f"Unknown fish: {name}")
            references[entry["name"]] = config.BASE_DIR / "templates" / f"fishing_{entry['slug'].replace('-', '_')}.png"
        detector = FishDetector(references, threshold=args.threshold)
    run_overlay(ADBController(host=args.host, port=args.port), detector, args.window_id,
                tuple(args.insets), args.duration, args.snapshot,
                args.report or config.BASE_DIR / "memory" / f"fishing_highlight_{args.port}.json",
                brighten=args.brighten, target_statuses=target_statuses)


if __name__ == "__main__":
    main()