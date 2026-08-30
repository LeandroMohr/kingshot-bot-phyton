"""Task: Arena of Glory (PVP).

Opens the Arena of Glory ranking screen and runs one Challenge battle. Reaching
the Arena building reuses the deterministic Barracks jump (through the Power
panel, which the game auto-centres), then a short map pan to the neighbouring
Arena:

Flow:
  1. Clear any connection-lost modal and start from the city (home).
  2. Jump to the troop buildings through the Power panel (same as Train Troops):
     combat power -> "Bonus Overview" -> "Power" -> "Enhance" next to
     "Troop Power". The game centres the Barracks with its radial menu open.
  3. Close the radial by tapping an empty spot, then pan the view RIGHT until the
     crossed-swords Arena building marker is on screen (it sits below the Stable,
     beside the Range). Each pan is short and slow, and the bot waits for the map
     to stop coasting before matching/tapping — `adb input swipe` flings the map,
     and tapping a marker spotted on a still-moving frame lands on the wrong
     building. Tapping that marker opens the Arena of Glory screen.
  4. Tap "Challenge" to open the Challenge List, OCR "My Power" and every
     opponent's power (rows are located by their green power text, since the
     modal shifts vertically with its footer), pick the weakest opponent at or
     below a percentage of our power (never someone stronger), tap that row's
     crossed-swords fight button, tap "Fight" on the squad-selection screen and
     wait for the result.

Templates (captured at the 540x960 ADB resolution):
  - arena_building_icon.png   : the crossed-swords marker floating over the Arena
                                building on the city map (used to locate/tap it).
  - arena_of_glory_title.png  : the "Arena of Glory" header, confirming the screen.
  - arena_challenge_button.png: the "Challenge" button at the bottom of the screen.
  - arena_fight_button.png     : the "Fight" button on the squad-selection screen.
"""
from __future__ import annotations

import re
import time

import cv2
import numpy as np
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
from executor import go_to_home_screen, handle_connection_lost
from executor.tutorial import screen_fingerprint, screens_similar
import config


class ArenaTask(Task):
    """Fights in the Arena of Glory (PVP): opens the ranking screen, reads the
    Challenge List, picks the weakest suitable opponent and runs one battle."""

    def execute(self, controller: ADBController) -> str:
        handle_connection_lost(controller)
        if not go_to_home_screen(controller):
            print("[Arena] Could not reach the city; will retry.")
            return Outcome.FAILED

        if not self._open_arena(controller):
            print("[Arena] Could not open the Arena of Glory screen; will retry.")
            self._go_home(controller)
            return Outcome.FAILED

        challenge = find_template(controller.screenshot(),
                                  config.ARENA_CHALLENGE_TEMPLATE,
                                  config.ARENA_MARKER_THRESHOLD).found
        if not challenge:
            print("[Arena] Challenge button not available; nothing to do.")
            self._go_home(controller)
            return Outcome.ABSENT

        outcome = self._run_challenges(controller)
        self._go_home(controller)
        return outcome

    # -- challenge / fight -------------------------------------------------
    def _run_challenges(self, controller: ADBController) -> str:
        """Open the Challenge List and fight up to the daily limit of challenges,
        each time picking the weakest suitable opponent. Stops early when no more
        challenges are available (the squad screen no longer opens). Returns
        SUCCESS if at least one battle ran, ABSENT otherwise."""
        controller.tap(*config.ARENA_CHALLENGE_TAP)
        time.sleep(1.8)

        fights = 0
        for n in range(config.ARENA_MAX_CHALLENGES):
            my_power = self._read_my_power(controller.screenshot())
            opponents = self._read_opponents(controller.screenshot())
            if not opponents:
                print("[Arena] Could not read any opponent power; stopping.")
                break

            idx, power, text_y = self._pick_opponent(opponents, my_power)
            readable = ", ".join(f"row{i}={p/1e6:.1f}M" for i, p, _ in opponents)
            print(f"[Arena] Challenge {n + 1}/{config.ARENA_MAX_CHALLENGES}: "
                  f"My Power {my_power/1e6:.1f}M; opponents [{readable}] -> "
                  f"row{idx} ({power/1e6:.1f}M).")

            controller.tap(config.ARENA_FIGHT_BTN_X,
                           text_y + config.ARENA_FIGHT_BTN_DY)  # crossed swords
            time.sleep(2.0)

            if not self._tap_fight(controller):
                # squad screen did not open -> out of challenges for today
                print("[Arena] No squad screen; no challenges left.")
                controller.back()  # dismiss any "no attempts" popup
                time.sleep(1.2)
                break

            self._wait_battle_result(controller)
            fights += 1
            print(f"[Arena] Battle {fights} completed.")

        self._close_challenge_list(controller)
        if fights:
            print(f"[Arena] Finished {fights} challenge battle(s).")
            return Outcome.SUCCESS
        return Outcome.ABSENT

    def _pick_opponent(self, opponents, my_power):
        """Return the (row_index, power, text_y) of the weakest opponent at or
        below ARENA_MAX_OPPONENT_RATIO * my_power; fall back to the weakest
        overall."""
        if my_power > 0:
            cap = my_power * config.ARENA_MAX_OPPONENT_RATIO
            eligible = [o for o in opponents if o[1] <= cap]
            if eligible:
                return min(eligible, key=lambda o: o[1])
            print("[Arena] No opponent below the power threshold; "
                  "picking the weakest available.")
        return min(opponents, key=lambda o: o[1])

    # -- OCR ---------------------------------------------------------------
    def _read_my_power(self, screen) -> int:
        """OCR the 'My Power' number at the top of the Challenge List modal."""
        x1, y1, x2, y2 = config.ARENA_MYPOWER_REGION
        gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        raw = pytesseract.image_to_string(
            thr, config="--psm 7 -c tessedit_char_whitelist=0123456789,").strip()
        digits = re.sub(r"[^0-9]", "", raw)
        return int(digits) if digits else 0

    def _read_opponents(self, screen):
        """OCR every opponent's green power value. Returns a list of
        (row_index, power, text_y), where text_y is the vertical centre of that
        row's power text (the fight button sits ARENA_FIGHT_BTN_DY from it).

        Rows are located by their green text instead of fixed coordinates: the
        modal shifts vertically with its footer (e.g. the "Free Refresh"
        button), which silently pushed the values out of the old fixed crops."""
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, config.ARENA_GREEN_HSV_LOW,
                           config.ARENA_GREEN_HSV_HIGH)
        results = []
        for top, bottom in self._power_text_rows(mask):
            xs = np.nonzero(mask[top:bottom + 1].sum(axis=0) > 0)[0]
            crop = mask[max(0, top - 6):bottom + 7,
                        max(0, xs.min() - 4):xs.max() + 5]
            crop = cv2.resize(crop, None, fx=6, fy=6,
                              interpolation=cv2.INTER_CUBIC)
            crop = cv2.copyMakeBorder(crop, 30, 30, 30, 30,
                                      cv2.BORDER_CONSTANT, value=0)
            raw = pytesseract.image_to_string(
                crop,
                config="--psm 13 -c tessedit_char_whitelist=0123456789.,MK").strip()
            power = self._parse_power(raw)
            if power is not None:
                results.append((len(results), power, (top + bottom) // 2))
        return results

    @staticmethod
    def _power_text_rows(mask):
        """Vertical (top, bottom) bands of the opponents' green power text."""
        x1, x2 = config.ARENA_ROW_SCAN_X
        y1, y2 = config.ARENA_ROW_SCAN_Y
        counts = mask[:, x1:x2].sum(axis=1) // 255
        bands, start = [], None
        for y in range(y1, min(y2, len(counts))):
            if counts[y] >= config.ARENA_ROW_MIN_PIXELS:
                start = y if start is None else start
                continue
            if start is not None:
                bands.append((start, y - 1))
                start = None
        if start is not None:
            bands.append((start, min(y2, len(counts)) - 1))
        rows = []
        for top, bottom in bands:
            height = bottom - top + 1
            if not (config.ARENA_ROW_MIN_HEIGHT <= height
                    <= config.ARENA_ROW_MAX_HEIGHT):
                continue  # noise, or the tall green "Free Refresh" button
            xs = np.nonzero(mask[top:bottom + 1].sum(axis=0) > 0)[0]
            if len(xs) and xs.max() - xs.min() <= config.ARENA_ROW_MAX_WIDTH:
                rows.append((top, bottom))
        return rows

    @staticmethod
    def _parse_power(raw: str) -> int | None:
        """Turn an on-screen power string into a number. Player opponents show an
        abbreviation ("5.6M", "980K"); the Guardsman NPCs show the plain value
        with thousands separators ("166,500"). An abbreviation whose decimal
        point the OCR dropped ("56M") carries one implied decimal digit."""
        text = raw.upper().replace(" ", "")
        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            return None
        suffix = "M" if "M" in text else ("K" if "K" in text else "")
        if not suffix:
            # A separator or four-plus digits means this is the exact value.
            if "," in text or len(digits) >= 4:
                return int(digits)
            # Two or three bare digits: an abbreviation whose suffix the OCR
            # missed (a real power is never that small).
            if len(digits) < 2:
                return None
            return int(int(digits) / 10.0 * 1_000_000)
        scale = 1_000_000 if suffix == "M" else 1_000
        if "." in text:
            return int(float(re.sub(r"[^0-9.]", "", text).strip(".")) * scale)
        if len(digits) < 2:
            return None  # a single digit means the OCR dropped part of the value
        return int(int(digits) / 10.0 * scale)

    def _tap_fight(self, controller: ADBController) -> bool:
        """Tap the 'Fight' button on the squad-selection screen. Returns False if
        the squad screen did not open (e.g. no challenges left)."""
        fight = find_template(controller.screenshot(),
                              config.ARENA_FIGHT_TEMPLATE,
                              config.ARENA_MARKER_THRESHOLD)
        if not fight.found:
            return False
        controller.tap(fight.x, fight.y)
        return True

    def _wait_battle_result(self, controller: ADBController) -> None:
        """Skip the battle animation: once the fight has started it can no longer
        be paused, so the outcome is already decided. Tapping pause -> "Retreat"
        jumps straight to the (predetermined) result screen. A short delay is
        needed between each step. Then dismiss the result until the Challenge
        List is back."""
        time.sleep(config.ARENA_STEP_DELAY)       # let the fight start
        controller.tap(*config.ARENA_PAUSE_TAP)   # pause
        time.sleep(config.ARENA_STEP_DELAY)
        controller.tap(*config.ARENA_RETREAT_TAP)  # retreat -> result screen
        time.sleep(config.ARENA_STEP_DELAY)
        deadline = time.time() + config.ARENA_RESULT_MAX_WAIT
        while time.time() < deadline:
            if find_template(controller.screenshot(),
                             config.ARENA_CHALLENGE_LIST_TITLE,
                             config.ARENA_MARKER_THRESHOLD).found:
                return  # back on the Challenge List -> result cleared
            controller.tap(*config.ARENA_RESULT_EXIT_TAP)  # dismiss result screen
            time.sleep(config.ARENA_RESULT_POLL)

    def _close_challenge_list(self, controller: ADBController) -> None:
        controller.tap(*config.ARENA_CHALLENGE_CLOSE_TAP)
        time.sleep(1.0)

    # -- reach the Arena screen --------------------------------------------
    def _reach_barracks(self, controller: ADBController) -> None:
        """Jump to the centred Barracks through the Power panel and close its
        radial menu, leaving the troop buildings in view."""
        controller.tap(*config.TRAIN_POWER_TAP)
        time.sleep(1.4)
        controller.tap(*config.TRAIN_BONUS_POWER_BTN)
        time.sleep(1.5)
        controller.tap(*config.TRAIN_TROOP_POWER_ENHANCE)
        time.sleep(2.5)
        controller.tap(*config.ARENA_RADIAL_CLOSE_TAP)  # dismiss the radial menu
        time.sleep(1.2)

    def _open_arena(self, controller: ADBController) -> bool:
        """From the city, reach the troop buildings and pan right until the Arena
        marker is found, then tap it to open the Arena of Glory screen. Returns
        True once that screen is confirmed open.

        Every pan is followed by _settle_view: the map keeps coasting for about a
        second after the swipe, and tapping a marker located on a still-moving
        frame misses it (which is what used to send the first attempt off to a
        random building)."""
        self._reach_barracks(controller)
        for _ in range(config.ARENA_MAX_STEPS):
            screen = self._settle_view(controller)
            if find_template(screen, config.ARENA_TITLE_TEMPLATE,
                             config.ARENA_MARKER_THRESHOLD).found:
                return True
            icon = find_template(screen, config.ARENA_ICON_TEMPLATE,
                                 config.ARENA_ICON_THRESHOLD)
            if icon.found:
                # Tapping the crossed-swords marker opens the Arena directly.
                controller.tap(icon.x, icon.y)
                time.sleep(2.0)
                continue
            controller.swipe(*config.ARENA_PAN_RIGHT,
                             config.ARENA_PAN_DURATION)  # move the view right
        return find_template(controller.screenshot(), config.ARENA_TITLE_TEMPLATE,
                             config.ARENA_MARKER_THRESHOLD).found

    def _settle_view(self, controller: ADBController):
        """Return a frame taken once the city view has stopped moving (two
        consecutive frames alike), so template positions are tappable."""
        screen = controller.screenshot()
        previous = screen_fingerprint(screen)
        for _ in range(config.ARENA_SETTLE_TRIES):
            time.sleep(config.ARENA_SETTLE_DELAY)
            screen = controller.screenshot()
            current = screen_fingerprint(screen)
            if screens_similar(previous, current):
                break
            previous = current
        return screen

    # -- helpers -----------------------------------------------------------
    def _exit_arena_screen(self, controller: ADBController) -> None:
        """Close the Arena of Glory screen with its back arrow while its title is
        still visible."""
        for _ in range(3):
            if not find_template(controller.screenshot(),
                                 config.ARENA_TITLE_TEMPLATE,
                                 config.ARENA_MARKER_THRESHOLD).found:
                return
            controller.tap(*config.ARENA_BACK_ARROW)
            time.sleep(1.2)

    def _go_home(self, controller: ADBController) -> bool:
        handle_connection_lost(controller)
        self._exit_arena_screen(controller)
        return go_to_home_screen(controller)


TASK = ArenaTask(
    name="Arena of Glory",
    detect="home_bottom_menu.png",   # available from the city
    loop=True,
    interval=config.ARENA_INTERVAL,
    home_marker="home_bottom_menu.png",
)
