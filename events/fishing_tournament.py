"""Fishing inspection, tab navigation and explicit free-trial controls."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import re
import sys
import time
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

import cv2
import pytesseract

import config
import console
from adb_controller import ADBController, ContinuousCapture
from events.fishing_catalog import SEASONS, plan_collection


EVENT_TABS = {
    "fishing": {"name": "Fishing Tournament", "edge": "left", "tap": (102, 105)},
    "guild": {"name": "Fishing Guild", "edge": "left", "tap": (254, 105)},
    "leaderboard": {"name": "Master Fisher Leaderboard", "edge": "left", "tap": (405, 105)},
    "pro-set": {"name": "Fishing Pro Set", "edge": "right", "tap": (286, 105)},
    "handbook": {"name": "Guide", "edge": "right", "tap": (438, 105)},
}


def read_white_text(image, region: tuple[int, int, int, int], psm: int = 7,
                    whitelist: str | None = None, min_white: int = 200) -> str:
    left, top, right, bottom = region
    mask = cv2.inRange(image[top:bottom, left:right], (min_white,) * 3, (255, 255, 255))
    text = cv2.resize(cv2.bitwise_not(mask), None, fx=4, fy=4)
    options = f"--psm {psm}"
    if whitelist:
        options += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(text, config=options, timeout=3).strip()


def is_fishing_paused(image) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    retreat = read_white_text(image, (140, 530, 245, 565)).lower()
    resume = read_white_text(image, (300, 530, 405, 565)).lower()
    return "retreat" in retreat and "continue" in resume


def retreat_paused_round(controller: ADBController):
    with ContinuousCapture(controller) as capture:
        frame = capture.next_frame()
        if not is_fishing_paused(frame.image):
            raise RuntimeError("Fishing pause menu not confirmed; no Retreat tap sent.")
        controller.tap(192, 480)
        frame = capture.next_frame(not_before=time.monotonic() + .6)
        if is_fishing_paused(frame.image):
            raise RuntimeError("Fishing Retreat did not leave the pause menu.")
        return frame.image


def is_trial_entry(image) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    label = read_white_text(image, (175, 812, 365, 858)).lower()
    rules = read_white_text(image, (45, 208, 155, 247)).lower()
    return "trial stages" in label and "rules" in rules


def read_fishing_hud(image) -> dict | None:
    if image.shape[:2] != (960, 540):
        return None
    fractions = []
    for region in ((60, 49, 122, 82), (60, 89, 130, 124)):
        text = read_white_text(image, region, whitelist="0123456789/")
        match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
        if not match:
            return None
        current, maximum = map(int, match.groups())
        if maximum <= 0 or not 0 <= current <= maximum:
            return None
        fractions.append((current, maximum))
    return {"captured": fractions[0][0], "capacity": fractions[0][1],
            "depth": fractions[1][0], "max_depth": fractions[1][1]}


def has_pause_icon(image) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    icon = image[10:45, 494:529]
    white = cv2.countNonZero(cv2.inRange(icon, (200, 200, 200), (255, 255, 255)))
    gray = cv2.countNonZero(cv2.inRange(cv2.cvtColor(icon, cv2.COLOR_BGR2HSV),
                                     (0, 0, 100), (179, 70, 200)))
    return white >= 40 and gray >= 150


def start_trial_stage(controller: ADBController, timeout: float = 12.0) -> dict:
    if timeout <= 3:
        raise ValueError("Trial start timeout must exceed the 3-second countdown.")
    with ContinuousCapture(controller) as capture:
        frame = capture.next_frame()
        if is_event_screen(frame.image) and is_tab_selected(frame.image, "fishing"):
            controller.tap(496, 172)
            frame = capture.next_frame(not_before=time.monotonic() + .5)
        if not is_trial_entry(frame.image):
            raise RuntimeError("Trial Stages entry not confirmed; no start tap sent.")
        controller.tap(270, 835)
        started = time.monotonic()
        countdown = []
        while time.monotonic() - started < timeout:
            frame = capture.next_frame(frame.sequence, not_before=started)
            number = read_white_text(frame.image, (220, 405, 320, 515),
                                     psm=10, whitelist="123", min_white=235)
            if number in ("3", "2", "1") and number not in countdown:
                countdown.append(number)
            if frame.completed_at - started < 3 or not has_pause_icon(frame.image):
                continue
            hud = read_fishing_hud(frame.image)
            if hud and hud["depth"] > 0 and hud["capacity"] == 10 and hud["max_depth"] == 100:
                report = {"mode": "trial", "serial": controller.serial,
                          "countdown_seconds": 3, "observed_countdown": countdown,
                          "start_elapsed_seconds": round(frame.completed_at - started, 3),
                          "hud": hud}
                print(json.dumps(report), flush=True)
                return report
        raise RuntimeError("Trial did not reach a confirmed active round; no restart attempted.")


def reset_fishing_round(controller: ADBController, timeout: float = 8.0):
    if timeout <= 0:
        raise ValueError("Reset timeout must be positive.")
    with ContinuousCapture(controller) as capture:
        frame = capture.next_frame()
        if not is_fishing_paused(frame.image):
            if not has_pause_icon(frame.image) or read_fishing_hud(frame.image) is None:
                raise RuntimeError("Active fishing round not confirmed; no Pause tap sent.")
            controller.tap(510, 26)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                frame = capture.next_frame(frame.sequence)
                if is_fishing_paused(frame.image):
                    break
            else:
                raise RuntimeError("Fishing pause menu not confirmed; no Retreat tap sent.")
        controller.tap(192, 480)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = capture.next_frame(frame.sequence)
            if is_event_screen(frame.image) and is_tab_selected(frame.image, "fishing"):
                print("Fishing round reset: returned to the fishing menu.", flush=True)
                return frame.image
        raise RuntimeError("Retreat return to the fishing menu was not confirmed.")


def is_event_screen(image) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    title = cv2.inRange(image[10:52, 65:290], (235, 235, 235), (255, 255, 255))
    title = cv2.resize(cv2.bitwise_not(title), None, fx=4, fy=4)
    text = pytesseract.image_to_string(title, config="--psm 7", timeout=3).lower()
    return "fishing tournament" in text


def is_tab_selected(image, tab: str) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    center_x, _ = EVENT_TABS[tab]["tap"]
    borders = (image[88:132, center_x - 65:center_x - 53],
               image[88:132, center_x + 53:center_x + 65])
    return all(cv2.countNonZero(cv2.inRange(border, (215, 215, 215), (255, 255, 255)))
               / (border.shape[0] * border.shape[1]) >= .7 for border in borders)


def open_event_tab(controller: ADBController, tab: str):
    if tab not in EVENT_TABS:
        raise ValueError(f"Unknown fishing tab: {tab}")
    target = EVENT_TABS[tab]
    with ContinuousCapture(controller) as capture:
        frame = capture.next_frame()
        if not is_event_screen(frame.image):
            raise RuntimeError("Open the Fishing Tournament event with no modal before navigating.")
        if target["edge"] == "left":
            controller.swipe(90, 130, 450, 130, duration_ms=700)
        else:
            controller.swipe(450, 130, 90, 130, duration_ms=700)
        frame = capture.next_frame(not_before=time.monotonic() + .7)
        if not is_event_screen(frame.image):
            raise RuntimeError("Fishing event changed during tab alignment; no tab tap sent.")
        controller.tap(*target["tap"])
        frame = capture.next_frame(not_before=time.monotonic() + .5)
        if not is_tab_selected(frame.image, tab):
            raise RuntimeError(f"Could not confirm selected fishing tab: {tab}")
        print(f"Selected fishing tab: {target['name']}", flush=True)
        return frame.image


def read_handbook_card(image, entries: list[dict]) -> dict | None:
    if image.shape[:2] != (960, 540):
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    cream = cv2.inRange(hsv[320:335, 160:400], (15, 10, 180), (40, 120, 255))
    if cv2.countNonZero(cream) / cream.size < .65:
        return None
    title = cv2.inRange(image[325:375, 160:410], (235, 235, 235), (255, 255, 255))
    title = cv2.resize(cv2.bitwise_not(title), None, fx=4, fy=4)
    title = cv2.copyMakeBorder(title, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    text = pytesseract.image_to_string(title, config="--psm 6", timeout=3).strip()
    normalize = lambda value: "".join(character for character in value.lower() if character.isalnum())
    name = normalize(text)
    ranked = sorted(((SequenceMatcher(None, name, normalize(entry["name"])).ratio(), entry)
                     for entry in entries), key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] < .88:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .06:
        return None
    badge = hsv[383:410, 365:402]
    green = cv2.countNonZero(cv2.inRange(badge, (35, 120, 100), (90, 255, 255)))
    gray_stars = cv2.countNonZero(cv2.inRange(
        hsv[372:398, 220:325], (85, 20, 70), (110, 150, 200),
    ))
    silhouette = cv2.countNonZero(cv2.inRange(
        hsv[420:545, 170:370], (0, 0, 80), (179, 65, 190),
    ))
    captured = True if green >= 12 else False if gray_stars >= 50 and silhouette >= 60 else None
    entry = ranked[0][1]
    return {"id": entry["id"], "name": entry["name"], "captured": captured,
            "name_confidence": round(ranked[0][0], 3), "ocr_name": text,
            "points": entry["points"], "depth": entry["depth"]}


def scan_handbook(controller: ADBController, entries: list[dict], output: Path,
                  max_cards: int = 96, scope: str | None = None,
                  capture: ContinuousCapture | None = None) -> dict:
    if not 1 <= max_cards <= 230:
        raise ValueError("Handbook scan must be limited to 1..230 cards.")
    controller.connect()
    report = {"serial": controller.serial, "scope": scope or controller.serial,
              "updated_at": datetime.now(timezone.utc).isoformat(), "entries": {}}
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("scope") != report["scope"]:
            raise ValueError("Collection scope differs; use a separate output file.")
        report = {**previous, **report, "entries": previous["entries"]}
    seen = set()
    try:
        with (ContinuousCapture(controller) if capture is None else nullcontext(capture)) as capture:
            frame = capture.next_frame()
            for index in range(max_cards):
                card = read_handbook_card(frame.image, entries)
                if card is None:
                    print("Unrecognized handbook card; stopping without further taps.", flush=True)
                    break
                identifier = str(card["id"])
                if identifier in seen:
                    break
                seen.add(identifier)
                if card["captured"] is not None:
                    report["entries"][identifier] = card
                print(json.dumps(card), flush=True)
                if index + 1 < max_cards:
                    controller.tap(480, 480)
                    frame = capture.next_frame(not_before=time.monotonic() + .45)
    finally:
        report["scanned_this_run"] = len(seen)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def read_screen_text(image) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2)
    return pytesseract.image_to_string(
        enlarged, config="--psm 11", timeout=3,
    ).strip()


def observe(controller: ADBController, duration: float, output: Path,
            ocr_interval: float = 2.0) -> dict:
    if duration <= 0 or ocr_interval <= 0:
        raise ValueError("Observation duration and OCR interval must be positive.")
    controller.connect()
    started = time.monotonic()
    report = {
        "serial": controller.serial,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "observations": [],
    }
    sequence = 0
    next_ocr = started
    previous_text = None
    max_capture_seconds = 0.0
    try:
        with ContinuousCapture(controller) as capture:
            while time.monotonic() - started < duration:
                frame = capture.next_frame(sequence)
                sequence = frame.sequence
                max_capture_seconds = max(
                    max_capture_seconds, frame.completed_at - frame.started_at,
                )
                if time.monotonic() < next_ocr:
                    continue
                next_ocr = time.monotonic() + ocr_interval
                text = read_screen_text(frame.image)
                if text != previous_text:
                    elapsed = round(frame.completed_at - started, 2)
                    report["observations"].append({"elapsed": elapsed, "text": text})
                    print(f"[{elapsed:.2f}s] {text}", flush=True)
                    previous_text = text
    except KeyboardInterrupt:
        report["interrupted"] = True
    finally:
        elapsed = time.monotonic() - started
        report["elapsed_seconds"] = round(elapsed, 3)
        report["frames"] = capture.frames
        report["fps"] = round(capture.frames / max(elapsed, 0.001), 2)
        report["mean_capture_seconds"] = round(
            capture.capture_seconds / max(capture.frames, 1), 4,
        )
        report["max_consumed_capture_seconds"] = round(max_capture_seconds, 4)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Observation saved to {output}; {report['fps']} FPS.", flush=True)
    return report


HANDBOOK_CATEGORIES = {"Catches": 90, "Mermaids": 210, "Ocean Chests": 330, "Memorabilia": 450}


def is_handbook_grid(image) -> bool:
    return is_event_screen(image) and is_tab_selected(image, "handbook")


def is_handbook_category_selected(image, category: str) -> bool:
    if image.shape[:2] != (960, 540):
        return False
    center = HANDBOOK_CATEGORIES[category]
    region = cv2.cvtColor(image[272:305, center - 45:center + 45], cv2.COLOR_BGR2HSV)
    selected = cv2.inRange(region, (80, 70, 160), (115, 255, 255))
    return cv2.countNonZero(selected) / selected.size >= .35


def map_fishing_collection(controller: ADBController,
                           max_cards_per_category: int | None = None) -> dict:
    entries = json.loads((config.BASE_DIR / "knowledge/fishing_catalog.json").read_text(encoding="utf-8"))["entries"]
    output = config.BASE_DIR / "memory" / f"fishing_collection_{controller.port}.json"
    image = controller.screenshot()
    if read_handbook_card(image, entries) is not None:
        controller.back()
        with ContinuousCapture(controller) as capture:
            capture.next_frame(not_before=time.monotonic() + .45)
    open_event_tab(controller, "handbook")
    report = {}
    with ContinuousCapture(controller) as capture:
        frame = capture.next_frame()
        for category, center in HANDBOOK_CATEGORIES.items():
            if not is_handbook_grid(frame.image):
                raise RuntimeError("Guide grid not confirmed; collection mapping stopped.")
            controller.tap(center, 290)
            frame = capture.next_frame(not_before=time.monotonic() + .45)
            if not is_handbook_grid(frame.image) or not is_handbook_category_selected(frame.image, category):
                raise RuntimeError(f"Guide category not confirmed: {category}")
            controller.tap(86, 440)
            frame = capture.next_frame(not_before=time.monotonic() + .45)
            category_entries = [entry for entry in entries if entry["category"] == category]
            if read_handbook_card(frame.image, category_entries) is None:
                raise RuntimeError(f"Specimen card not confirmed: {category}")
            limit = max_cards_per_category or len(category_entries)
            report = scan_handbook(controller, category_entries, output, limit, capture=capture)
            controller.back()
            frame = capture.next_frame(not_before=time.monotonic() + .45)
    open_event_tab(controller, "fishing")
    return report


class FishingFlow:
    requires_profile = False
    update_collection = False

    name = "Fishing Tournament"

    def choose_options(self) -> str:
        self.update_collection = False
        if not sys.stdin or not sys.stdin.isatty():
            return "start"
        while True:
            print("\nFishing Tournament:")
            print("  1 - Use saved collection and start highlights (default)")
            print("  2 - Update collection from Guide, then start highlights")
            print("  0 - Back")
            print("  q - Quit")
            choice = console.timed_input(
                f"Option (auto 'saved collection' in {int(config.TASK_MENU_TIMEOUT)}s): ",
                config.TASK_MENU_TIMEOUT)
            if choice is None or choice.strip() in ("", "1"):
                return "start"
            choice = choice.strip().lower()
            if choice == "2":
                self.update_collection = True
                return "start"
            if choice == "0":
                return "back"
            if choice == "q":
                return "quit"
            print("Invalid option. Let's try again.")

    def execute(self, controller: ADBController) -> str:
        from tasks.base import Outcome
        from events.fishing_overlay import main as overlay_main
        if self.update_collection:
            map_fishing_collection(controller)
        arguments = ["--host", controller.host, "--port", str(controller.port)]
        overlay_main(arguments)
        return Outcome.SUCCESS


FISHING_EVENTS = {"fishing": FishingFlow()}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config.ADB_HOST)
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--ocr-interval", type=float, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tab", choices=EVENT_TABS, help="Navigate to an event tab, then exit")
    parser.add_argument("--trial-action", choices=("start", "reset", "cycle"),
                        help="Explicit free-trial start, active-round reset, or start/reset test cycle")
    parser.add_argument("--scan-handbook", action="store_true", help="Scan an already open specimen card")
    parser.add_argument("--max-cards", type=int, default=96)
    parser.add_argument("--scope", help="Verified account ID; otherwise collection is device-scoped")
    parser.add_argument("--catalog", type=Path, default=config.BASE_DIR / "knowledge/fishing_catalog.json")
    parser.add_argument("--season", choices=SEASONS,
                        help="Season displayed by the current event; required for handbook scans")
    parser.add_argument("--max-depth", type=int, default=250)
    args = parser.parse_args(argv)
    if sum(bool(value) for value in (args.tab, args.scan_handbook, args.trial_action)) > 1:
        parser.error("Choose only one of --tab, --scan-handbook or --trial-action")
    if args.trial_action:
        controller = ADBController(host=args.host, port=args.port)
        controller.connect()
        report = {"serial": controller.serial, "action": args.trial_action,
                  "recorded_at": datetime.now(timezone.utc).isoformat()}
        if args.trial_action in ("start", "cycle"):
            report["start"] = start_trial_stage(controller)
        if args.trial_action in ("reset", "cycle"):
            image = reset_fishing_round(controller)
            report["reset"] = {"returned_to": "fishing", "pause_tap": [510, 26],
                               "retreat_tap": [192, 480], "menu_text": read_screen_text(image)}
        output = args.output or config.BASE_DIR / "memory" / f"fishing_trial_{args.port}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return
    if args.tab:
        controller = ADBController(host=args.host, port=args.port)
        controller.connect()
        open_event_tab(controller, args.tab)
        return
    if args.scan_handbook:
        if not args.season:
            parser.error("--scan-handbook requires the current event's --season")
        entries = json.loads(args.catalog.read_text(encoding="utf-8"))["entries"]
        output = args.output or config.BASE_DIR / "memory" / f"fishing_collection_{args.port}.json"
        report = scan_handbook(ADBController(host=args.host, port=args.port), entries,
                               output, args.max_cards, args.scope)
        planned = plan_collection(entries, report["entries"], args.season, args.max_depth)
        for entry in planned:
            if entry["capture_status"] == "missing":
                reach = "reachable" if entry["reachable"] else "longer line required"
                print(f"MISSING: {entry['name']} | {entry['points']} pts | {entry['depth']}m | {reach}")
        return
    output = args.output or (
        config.BASE_DIR / "memory" / f"fishing_observation_{args.port}.json"
    )
    observe(ADBController(host=args.host, port=args.port), args.duration,
            output, args.ocr_interval)


if __name__ == "__main__":
    main()