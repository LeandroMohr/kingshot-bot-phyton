"""Event: Castle Battle — attack the King's Castle and keep the infirmary clear.

While the Castle Battle event is in its Battle Phase, the King's Castle can be
attacked over and over. Each attack sends ONE march (the game only allows a
single attack on the castle at a time) and comes back with wounded troops, so
the event alternates between attacking and emptying the infirmary.

Flow of one attack (all of it validated live):
  1. City/world map: tap the gold-rimmed CASTLE icon in the right-hand icon
     column (same column as the paw / scales / mail buttons). That column grows
     upwards as event icons appear, so the icon is always found by template.
  2. The Events window opens on the "Castle Battle" tab -> tap "Go" at the
     bottom; the game flies the camera to the castle.
  3. Tap the white "King's Castle" label on the map. A modal opens with
     King Perks / Battle Record / Rally / Scout / Attack.
  4. SAFETY: the modal title must read "King's Castle". If it does not, we hit
     another player's city or a wilderness tile and the flow is aborted without
     tapping anything — the event only ever attacks the castle.
  5. Tap "Attack" -> the Deploy screen opens with the default heroes and troop
     ratio. Nothing is adjusted (player's rule) -> tap "Deploy".
  6. Wait for that march to resolve before sending the next one.

Infirmary rules (player's rules, enforced here):
  - Stop attacking when the severely injured reach config.CASTLE_INJURED_LIMIT
    or config.CASTLE_INFIRMARY_PCT_LIMIT of the infirmary capacity — a full
    infirmary starts losing troops for good.
  - Heal at most config.HEAL_BATCH_SIZE troops of a SINGLE type per batch: set
    that row's quantity box, zero the other rows, tap "Heal" and then "Help".
    With an active alliance the help finishes the batch instantly, so the cycle
    repeats until there is nothing left to heal.
  - NEVER tap "Finish": it pays gems.

Quantities are typed into the Android input bar that the game opens when the
quantity box is tapped, and read back from it before confirming (that bar uses
the plain system font and OCRs perfectly, unlike the stylised in-game numbers).

Templates (captured at the 540x960 ADB resolution):
  - castle_event_icon.png   : gold-rimmed castle icon (event entry point)
  - castle_go_button.png    : cyan "Go" at the bottom of the event panel
  - castle_map_label.png    : white "King's Castle" label on the world map
  - castle_modal_title.png  : "King's Castle" title inside the action modal
  - castle_attack_button.png: orange "Attack" button of that modal
  - castle_deploy_marker.png: "Deploy" header of the troop selection screen
  - castle_deploy_button.png: cyan "Deploy" button
  - infirmary_button.png    : green "+" infirmary button (with the usage %)
  - heal_modal_title.png    : "Heal Injured" title
  - heal_start_button.png   : cyan "Heal" button (idle state)
  - heal_help_button.png    : cyan "Help" button (healing in progress)
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from tasks.base import Outcome
from adb_controller import ADBController
from vision import find_template
import account_prefs
import config

_TROOP_KEYWORDS = ("infantry", "cavalry", "archer")


class CastleBattleEvent:
    """Attacks the King's Castle in a loop, healing the wounded in between."""

    name = "Castle Battle"
    requires_profile = True
    detect_threshold = config.DEFAULT_THRESHOLD
    home_marker = config.HOME_MARKER
    recover_max_tries = 4
    log_label = "Castle Battle"

    def execute(self, controller: ADBController) -> str:
        deadline = time.time() + config.CASTLE_MAX_RUNTIME
        # A Heal Injured modal left open by a previous run sits on top of the
        # city and hides the event icon, so clear it before looking around.
        self._close_heal_modal(controller)
        if self._current_screen(controller) not in ("home", "world"):
            if not self._go_home(controller):
                return Outcome.FAILED

        if not self._event_available(controller):
            print(f"[{self.log_label}] Castle Battle icon not on screen; "
                  f"the event is not running.")
            return Outcome.ABSENT

        attacks = 0
        # How many troops one attack sends to the infirmary. Seeded from the
        # value learned on previous runs and used to stop BEFORE the next attack
        # would cross the limit (checking only the current count lets a single
        # attack blow straight past it — one attack wounds tens of thousands).
        account = account_prefs.current_account_id()
        wounds_per_attack = account_prefs.get_pref(
            account, "castle_wounds_per_attack", config.CASTLE_WOUNDS_PER_ATTACK)
        while time.time() < deadline:
            injured = self._read_injured(controller)
            if injured is not None and self._over_limit(injured[0] + wounds_per_attack,
                                                        injured[1]):
                print(f"[{self.log_label}] Infirmary at {injured[0]:,}/{injured[1]:,} "
                      f"— pausing attacks to heal.")
                self._heal_everything(controller)
                injured = self._read_injured(controller)
                if injured is not None and self._over_limit(injured[0] + wounds_per_attack,
                                                            injured[1]):
                    print(f"[{self.log_label}] Still {injured[0]:,} wounded after "
                          f"healing; stopping until the infirmary drains.")
                    self._go_home(controller)
                    return Outcome.SUCCESS if attacks else Outcome.ABSENT

            wounded_before = injured[0] if injured else None
            before = self._read_march_status(controller)
            march_seconds = self._attack_castle(controller)
            if march_seconds is None:
                print(f"[{self.log_label}] Could not launch the attack this pass.")
                break
            attacks += 1
            print(f"[{self.log_label}] Attack #{attacks} launched "
                  f"({march_seconds}s of marching).")
            self._wait_for_march(controller, before, march_seconds)

            injured = self._read_injured(controller)
            if wounded_before is not None and injured is not None:
                measured = injured[0] - wounded_before
                if measured > wounds_per_attack:
                    wounds_per_attack = measured
                    account_prefs.set_pref(account, "castle_wounds_per_attack",
                                           measured)

        # One last drain so the run never ends with a loaded infirmary.
        injured = self._read_injured(controller)
        if injured is not None and injured[0] > 0:
            self._heal_everything(controller)
        self._go_home(controller)
        return Outcome.SUCCESS if attacks else Outcome.ABSENT

    # -- event / attack ----------------------------------------------------
    def _event_available(self, controller: ADBController) -> bool:
        return find_template(controller.screenshot(), config.CASTLE_EVENT_ICON,
                             config.CASTLE_EVENT_ICON_THRESHOLD).found

    def _attack_castle(self, controller: ADBController) -> int | None:
        """Run the whole attack flow. Returns the one-way march time in seconds
        (used to time the wait) or None if any step could not be completed."""
        if not self._tap(controller, config.CASTLE_EVENT_ICON, wait=2.5,
                         threshold=config.CASTLE_EVENT_ICON_THRESHOLD):
            return None
        if not self._tap(controller, config.CASTLE_GO_BUTTON, wait=4.5):
            return None
        if not self._tap(controller, config.CASTLE_MAP_LABEL, wait=2.5):
            return None

        # SAFETY GATE: only ever attack the King's Castle, never a player city.
        if not find_template(controller.screenshot(), config.CASTLE_MODAL_TITLE,
                             self.detect_threshold).found:
            print(f"[{self.log_label}] The modal is not the King's Castle; aborting.")
            controller.back()
            time.sleep(1.2)
            return None

        if not self._tap(controller, config.CASTLE_ATTACK_BUTTON, wait=3.0):
            return None
        screen = controller.screenshot()
        if not find_template(screen, config.CASTLE_DEPLOY_MARKER,
                             self.detect_threshold).found:
            print(f"[{self.log_label}] The Deploy screen did not open; aborting.")
            controller.back()
            time.sleep(1.2)
            return None

        march_seconds = self._read_march_seconds(screen) or 60
        if not self._tap(controller, config.CASTLE_DEPLOY_BUTTON, wait=3.0):
            return None
        return march_seconds

    def _read_march_seconds(self, screen: np.ndarray) -> int | None:
        """OCR the "HH:MM:SS" clock shown above the Deploy button."""
        x1, y1, x2, y2 = config.CASTLE_MARCH_TIME_REGION
        crop = screen[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        _, mask = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789:").strip()
        parts = re.findall(r"\d+", txt)[-3:]
        if len(parts) != 3:
            return None
        hours, minutes, seconds = (int(p) for p in parts)
        return hours * 3600 + minutes * 60 + seconds

    def _wait_for_march(self, controller: ADBController,
                        before: tuple[int, int] | None, march_seconds: int) -> None:
        """Block until the attack march is home again.

        The trip is there + fight + back, so we sleep through the round trip
        first and only then poll the world-map "Marching N/M" counter for it to
        drop back to what it was before the Deploy."""
        time.sleep(min(2 * march_seconds + config.CASTLE_BATTLE_BUFFER,
                       config.CASTLE_MARCH_MAX_WAIT))
        if before is None:
            return
        baseline = before[0]
        deadline = time.time() + config.CASTLE_MARCH_MAX_WAIT
        while time.time() < deadline:
            status = self._read_march_status(controller)
            if status is not None and status[0] <= baseline:
                return
            time.sleep(config.CASTLE_MARCH_POLL)
        print(f"[{self.log_label}] Gave up waiting for the march; continuing.")

    # -- infirmary ---------------------------------------------------------
    def _over_limit(self, injured: int, capacity: int) -> bool:
        if injured >= config.CASTLE_INJURED_LIMIT:
            return True
        return bool(capacity) and injured * 100.0 / capacity >= config.CASTLE_INFIRMARY_PCT_LIMIT

    def _open_heal_modal(self, controller: ADBController) -> bool:
        """Open the "Heal Injured" modal from the green infirmary button. That
        button only exists while there ARE wounded troops, so a False here also
        means "nothing to heal"."""
        if find_template(controller.screenshot(), config.HEAL_MODAL_TITLE,
                         self.detect_threshold).found:
            return True
        for _ in range(3):
            if self._tap(controller, config.INFIRMARY_BUTTON, wait=2.5,
                         threshold=config.INFIRMARY_BUTTON_THRESHOLD):
                if find_template(controller.screenshot(), config.HEAL_MODAL_TITLE,
                                 self.detect_threshold).found:
                    return True
            else:
                return False
        return False

    def _close_heal_modal(self, controller: ADBController) -> None:
        for _ in range(3):
            if not find_template(controller.screenshot(), config.HEAL_MODAL_TITLE,
                                 self.detect_threshold).found:
                return
            controller.tap(*config.HEAL_CLOSE_TAP)
            time.sleep(1.2)

    def _read_injured(self, controller: ADBController) -> tuple[int, int] | None:
        """Return (severely injured, infirmary capacity). (0, 0) when there is
        no infirmary button at all, i.e. nothing is wounded."""
        if not self._open_heal_modal(controller):
            return (0, 0)
        value = self._read_injured_counter(controller.screenshot())
        self._close_heal_modal(controller)
        return value

    def _read_injured_counter(self, screen: np.ndarray) -> tuple[int, int] | None:
        x1, y1, x2, y2 = config.HEAL_INJURED_REGION
        txt = self._ocr_dark(screen[y1:y2, x1:x2], "0123456789,/")
        match = re.match(r"([\d,]+)\s*/\s*([\d,]+)", txt)
        if not match:
            return None
        return (int(match.group(1).replace(",", "")),
                int(match.group(2).replace(",", "")))

    def _read_rows(self, screen: np.ndarray) -> list[tuple[str, int, int]]:
        """Read the troop rows of the modal as (type, wounded, label y).

        Rows disappear as a troop type is fully healed, so they are re-read on
        every batch and located by their index among the rows still present."""
        rows: list[tuple[str, int, int]] = []
        x1, x2 = config.HEAL_ROW_LABEL_X
        for index in range(len(_TROOP_KEYWORDS)):
            y = config.HEAL_ROW_FIRST_Y + index * config.HEAL_ROW_PITCH
            txt = self._ocr_dark(
                screen[y - 15:y + 14, x1:x2],
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789, "
            ).lower()
            kind = next((k for k in _TROOP_KEYWORDS if k in txt), None)
            if kind is None:
                continue
            numbers = re.findall(r"[\d,]+", txt)
            if not numbers:
                continue
            rows.append((kind, int(numbers[-1].replace(",", "")), y))
        return rows

    def _heal_everything(self, controller: ADBController) -> None:
        """Drain the infirmary in batches of at most HEAL_BATCH_SIZE troops of a
        single type, tapping "Help" after each one so the alliance finishes it.

        The modal KEEPS the quantities between batches, so they are only typed
        again when the target row (or the set of rows) changes — that turns a
        ~15s batch into a ~6s one, which matters when there are 100k wounded.
        Each batch checks how much the counter actually dropped: a drop far
        bigger than the batch size means the quantities were not the ones we
        set, so they get retyped before the next one."""
        if not self._open_heal_modal(controller):
            print(f"[{self.log_label}] No wounded troops to heal.")
            return

        applied: tuple[str, int, tuple[str, ...]] | None = None
        last_total: int | None = None
        stalled = 0
        healed = 0
        batch = -1
        for batch in range(config.HEAL_MAX_BATCHES):
            if not self._finish_pending_heal(controller):
                print(f"[{self.log_label}] A heal is still running; leaving it "
                      f"to finish on its own.")
                break
            screen = controller.screenshot()
            total = self._read_injured_counter(screen)
            if total is None:
                break
            if total[0] <= 0:
                print(f"[{self.log_label}] Infirmary empty.")
                break
            if last_total is not None:
                drop = last_total - total[0]
                if drop <= 0:
                    stalled += 1
                    if stalled >= 2:
                        print(f"[{self.log_label}] Healing is not progressing "
                              f"({total[0]:,} wounded left); stopping.")
                        break
                else:
                    stalled = 0
                    healed += drop
                    if applied is not None and drop > applied[1] * 1.5:
                        print(f"[{self.log_label}] Healed {drop} in one batch "
                              f"(expected {applied[1]}); resetting the amounts.")
                        applied = None
            last_total = total[0]

            rows = self._read_rows(screen)
            target = next((r for r in rows if r[1] > 0), None)
            if target is None:
                break
            kind = target[0]
            amount = min(config.HEAL_BATCH_SIZE, target[1])
            wanted = (kind, amount, tuple(r[0] for r in rows))
            if applied != wanted:
                if not self._select_only(controller, rows, target, amount):
                    print(f"[{self.log_label}] Could not set the heal quantities; "
                          f"stopping to avoid healing an unintended amount.")
                    break
                applied = wanted
                print(f"[{self.log_label}] Healing {amount} {kind} per batch "
                      f"({total[0]:,} wounded left).")
            if not self._tap(controller, config.HEAL_START_BUTTON, wait=2.0):
                break
            self._finish_pending_heal(controller)

        print(f"[{self.log_label}] Healed about {healed:,} troops in "
              f"{batch + 1} batches.")
        self._close_heal_modal(controller)

    def _finish_pending_heal(self, controller: ADBController) -> bool:
        """While a heal is in progress the modal shows "Help" instead of "Heal".
        Tap it until the alliance finishes the batch. Returns True once the modal
        is back in its idle state (or was never busy)."""
        for _ in range(config.HEAL_HELP_MAX_TAPS):
            screen = controller.screenshot()
            if find_template(screen, config.HEAL_START_BUTTON,
                             self.detect_threshold).found:
                return True
            if not self._tap(controller, config.HEAL_HELP_BUTTON, wait=3.0):
                return False
        return find_template(controller.screenshot(), config.HEAL_START_BUTTON,
                             self.detect_threshold).found

    def _select_only(self, controller: ADBController,
                     rows: list[tuple[str, int, int]],
                     target: tuple[str, int, int], amount: int) -> bool:
        """Set the target row to `amount` and every other row to 0."""
        for kind, _, y in rows:
            value = amount if kind == target[0] else 0
            if not self._set_quantity(controller, y + config.HEAL_QTY_BOX_DY, value):
                return False
        return True

    def _set_quantity(self, controller: ADBController, box_y: int, value: int) -> bool:
        """Type `value` into the quantity box at `box_y`.

        Tapping the box pops the Android input bar; the value is typed there and
        READ BACK before confirming, because the in-game stylised digits OCR
        badly and confirming a wrong number would heal thousands of troops."""
        wanted = str(value)
        for _ in range(3):
            controller.tap(config.HEAL_QTY_BOX_X, box_y)
            time.sleep(1.0)
            controller.key_event(123)            # move caret to the end
            controller.key_event(*([67] * 12))   # delete the current value
            controller.input_text(wanted)
            time.sleep(0.8)
            if self._read_input_field(controller) == wanted:
                controller.tap(*config.HEAL_INPUT_OK_TAP)
                time.sleep(0.8)
                return True
            controller.back()                    # close the input bar and retry
            time.sleep(0.8)
        return False

    def _read_input_field(self, controller: ADBController) -> str:
        x1, y1, x2, y2 = config.HEAL_INPUT_REGION
        return self._ocr_dark(controller.screenshot()[y1:y2, x1:x2], "0123456789")

    @staticmethod
    def _ocr_dark(crop: np.ndarray, whitelist: str) -> str:
        """OCR dark text on a light background (the whole Heal modal)."""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return pytesseract.image_to_string(
            mask, config=f"--psm 7 -c tessedit_char_whitelist={whitelist}").strip()

    # -- navigation (same conventions as the hunt tasks) -------------------
    def _read_march_status(self, controller: ADBController) -> tuple[int, int] | None:
        """Read the world-map march queues as (busy, total). The "Marching N/M"
        panel only exists while a march is out; absent means every queue is
        free."""
        screen = controller.screenshot()
        if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                             config.MARCHING_PANEL_THRESHOLD).found:
            return (0, config.MARCH_MAX_QUEUES)
        x1, y1, x2, y2 = config.MARCH_COUNTER_REGION
        crop = screen[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (180, 180, 180), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
        match = re.match(r"(\d+)\s*/\s*(\d+)", txt)
        if not match:
            return None
        total = max(1, min(int(match.group(2)), config.MARCH_MAX_QUEUES))
        return (max(0, min(int(match.group(1)), total)), total)

    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        if not (Path(config.TEMPLATES_DIR) / template).exists():
            return False
        match = find_template(controller.screenshot(), template,
                              threshold or self.detect_threshold)
        if not match.found:
            return False
        controller.tap(match.x, match.y)
        time.sleep(wait)
        return True

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the city safely. 'back' is NEVER used on the world map
        (there it pops the "Quit game?" dialog)."""
        for _ in range(self.recover_max_tries + 4):
            where = self._current_screen(controller)
            if where == "home":
                return True
            if where == "quit":
                self._dismiss_quit_dialog(controller)
            elif where == "world":
                self._tap(controller, "world_town.png", wait=2.0, threshold=0.80)
            else:
                controller.back()
                time.sleep(1.2)
        return find_template(controller.screenshot(), self.home_marker,
                             self.detect_threshold).found

    def _current_screen(self, controller: ADBController) -> str:
        screen = controller.screenshot()
        if find_template(screen, "quit_dialog.png", 0.80).found:
            return "quit"
        if find_template(screen, "world_town.png", 0.80).found:
            return "world"
        if find_template(screen, self.home_marker, 0.80).found:
            return "home"
        return "other"

    def _dismiss_quit_dialog(self, controller: ADBController) -> bool:
        if self._tap(controller, "quit_cancel.png", wait=1.2, threshold=0.85):
            return True
        if find_template(controller.screenshot(), "quit_dialog.png", 0.80).found:
            controller.tap(*config.QUIT_CANCEL_TAP)
            time.sleep(1.2)
            return True
        return False


EVENT = CastleBattleEvent()
