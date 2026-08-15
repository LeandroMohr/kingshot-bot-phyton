"""Task: Gather resources (bread / wood / stone / iron) on the world map.

Starting from the city (or the world map) the bot opens the same SEARCH screen
used for Terror hunting (world map -> magnifier), but instead of the Terror
(beast) category it selects a RESOURCE category from the scrollable bottom row
(Bread | Wood | Stone | Iron). The point of gathering is the specialist hero's
buff, so the task keeps exactly ONE active gather per resource (four marches at
most), each with its blue gatherer. They need not all be dispatched at once — the
task launches whichever specialists are free and picks up the rest on a later
sweep.

Per resource it tries the HIGHEST level first (config.GATHER_LEVEL_START, 8) and
only drops a level when:
  - the search finds NO node of that level ("No suitable targets..."), detected
    by the absence of the "Gather" card after Search; or
  - the troops the game can field cannot fill the node's Capacity (the deploy
    screen's carry number is lower than the card's Capacity).
If a resource yields no fillable node at ANY level it is left for the next sweep.

Heroes: the game auto-selects the correct blue gatherer in slot 1 WHENEVER that
hero is free (idle in the city); the other two slots hold generic gold heroes.
A gather is ALWAYS launched WITH its specialist (the buff is the whole point), so
we keep ONLY that blue hero and remove the two gold ones. When the gatherer is
NOT auto-selected he is out on a march (a hero on a march is removed from the
roster entirely, so the hero-selection modal could not pick him either) — which
means that resource is ALREADY being gathered, so the task skips it (it never
deploys hero-less). Detection is a template match of the gatherer's slot-1
portrait: present -> keep him and remove the others (no modal needed); absent ->
busy -> skip. Heroes are removed RIGHT-to-LEFT so the remaining cards do not
reflow under the minus buttons. We never touch the troop sliders (the game
auto-fills them to the node capacity) and never press "Clear All" (that zeroes
the troops and disables Deploy).

Cadence: while any gather is running (queues stay tied up for hours) the task
re-checks on config.GATHER_ACTIVE_RETRY (1h); with nothing gathering it retries
sooner on config.GATHER_INTERVAL.

Safety: like the Terror hunt, it NEVER presses 'back' on the world map (that pops
the "Quit game?" dialog); navigation goes through the Town button. It reuses the
world/home/quit screen classification and the Terror level-slider control (same
+/- buttons; only the floor differs: resources go down to Lv.1, Terrors to 3).

Templates (captured at the 540x960 ADB resolution):
  - res_iron/res_stone/res_wood/res_bread.png : the bottom-row category icons.
  - gather_button.png : the cyan "Gather" button on a found node's card.
  - hero_seth/hero_edwin/hero_forrest/hero_olive.png : the correct blue gatherer
    portrait in deploy slot 1 (iron/stone/wood/bread respectively).
  - deploy_button.png : the "Deploy" button (reused from the hunt formation).
  - search_button.png / world_search.png / world_town.png / home_bottom_menu.png
    / marching_panel.png : reused from the Terror search flow.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config


class GatherResourcesTask(Task):
    """Keeps one active gather per resource (four marches max), each with its
    specialist hero, for the gathering buff."""

    # _gather_one outcomes.
    _DISPATCHED = "dispatched"   # a new gather march was launched (hero kept)
    _GATHERING = "gathering"     # specialist is busy -> already being gathered
    _NO_NODE = "no_node"         # no fillable node found at any level

    def execute(self, controller: ADBController) -> str:
        # Start from a known state (never 'back' on the world map).
        where = self._current_screen(controller)
        if where not in ("home", "world"):
            if not self._go_home(controller):
                return Outcome.FAILED

        free = self._free_queue_count(controller)
        if free is None:
            return Outcome.FAILED
        if free <= 0:
            # Queues are full (very likely gathers already running) -> wait 1h.
            print("[Gather] Every march queue is busy; re-checking in 1h.")
            self.interval = config.GATHER_ACTIVE_RETRY
            self._go_home(controller)
            return Outcome.ABSENT

        print(f"[Gather] {free} free march queue(s) available.")
        dispatched = 0
        gathering = 0
        # One gather per resource: dispatch it (with hero) only if its specialist
        # is free; a busy specialist means that resource is already being gathered.
        for resource in config.GATHER_RESOURCE_ORDER:
            if free <= 0:
                break
            result = self._gather_one(controller, resource)
            if result == self._DISPATCHED:
                dispatched += 1
                free -= 1
            elif result == self._GATHERING:
                gathering += 1

        self._go_home(controller)
        if dispatched or gathering:
            # A collection is in progress -> re-check in 1h.
            self.interval = config.GATHER_ACTIVE_RETRY
            return Outcome.SUCCESS if dispatched else Outcome.ABSENT
        self.interval = config.GATHER_INTERVAL
        return Outcome.ABSENT

    # -- one gather (one queue) -------------------------------------------
    def _gather_one(self, controller: ADBController, resource: str) -> str:
        """Search the given resource from the highest level down and try to launch
        ONE gather with its specialist hero. Returns:
          _DISPATCHED  - a march was launched with the correct blue gatherer;
          _GATHERING   - the specialist is out on a march (busy) so this resource
                         is already being gathered -> skip it (no deploy);
          _NO_NODE     - no fillable node exists at any level.

        Each level attempt re-establishes the search screen: after a fruitless
        search the node CARD overlays the still-open search panel (so re-opening
        is a no-op), but after backing out of the DEPLOY screen we are dropped
        back on the world map with the panel closed — so we always re-select the
        category and reset the level before searching again."""
        level = config.GATHER_LEVEL_START
        while level >= config.GATHER_LEVEL_MIN:
            if not self._select_category(controller, resource):
                return self._NO_NODE
            self._set_level(controller, level)
            if not self._tap(controller, "search_button.png", wait=2.0,
                             threshold=0.80):
                return self._NO_NODE
            time.sleep(1.5)
            card = find_template(controller.screenshot(),
                                 config.GATHER_BUTTON_TEMPLATE,
                                 config.GATHER_BUTTON_THRESHOLD)
            if not card.found:
                # "No suitable targets" at this level -> try one level lower.
                level -= 1
                continue
            capacity = self._read_capacity(controller)
            controller.tap(card.x, card.y)   # open the deploy/formation screen
            time.sleep(2.2)
            if not self._keep_specialist(controller, resource):
                # Specialist busy -> this resource is already being gathered.
                print(f"[Gather] {resource}: specialist busy; already being "
                      f"gathered, skipping.")
                controller.tap(*config.GATHER_BACK_ARROW)  # deploy -> world map
                time.sleep(1.5)
                return self._GATHERING
            carry = self._read_carry(controller)
            if capacity is not None and carry is not None and carry < capacity:
                # Not enough troops for this level -> drop a level and retry.
                print(f"[Gather] {resource} Lv{level}: carry {carry} < capacity "
                      f"{capacity}; dropping a level.")
                controller.tap(*config.GATHER_BACK_ARROW)  # deploy -> world map
                time.sleep(1.5)
                level -= 1
                continue
            if not self._tap(controller, config.GATHER_DEPLOY_BUTTON, wait=2.5,
                             threshold=0.80):
                print(f"[Gather] {resource} Lv{level}: Deploy button not found.")
                controller.tap(*config.GATHER_BACK_ARROW)
                time.sleep(1.5)
                return self._NO_NODE
            print(f"[Gather] Dispatched {resource} Lv{level} with its hero.")
            return self._DISPATCHED
        return self._NO_NODE

    # -- category selection -----------------------------------------------
    def _select_category(self, controller: ADBController, resource: str) -> bool:
        """Open the search screen and select the resource's category icon. The
        bottom category row is scrolled to its right extent (two left swipes) so
        all four resource icons are visible, then the icon is matched and tapped."""
        if not self._open_search(controller):
            return False
        for _ in range(2):
            controller.swipe(*config.GATHER_CAT_ROW_SWIPE)
            time.sleep(0.6)
        icon = config.GATHER_RESOURCE_ICONS[resource]
        match = find_template(controller.screenshot(), icon,
                              config.GATHER_ICON_THRESHOLD)
        if not match.found:
            print(f"[Gather] Category icon for {resource} not found.")
            return False
        controller.tap(match.x, match.y)
        time.sleep(0.8)
        return True

    # -- heroes ------------------------------------------------------------
    def _keep_specialist(self, controller: ADBController, resource: str) -> bool:
        """If the correct blue gatherer is auto-selected (i.e. free), keep ONLY
        him and remove the two generic gold heroes (right-to-left, to avoid the
        remaining cards reflowing under the minus buttons); return True. If he is
        not on screen he is out on a march (busy) -> return False without touching
        the slots, so the caller can skip this resource (never deploy hero-less)."""
        hero = config.GATHER_RESOURCE_HEROES[resource]
        match = find_template(controller.screenshot(), hero,
                              config.GATHER_HERO_THRESHOLD)
        if not match.found:
            return False
        centers = config.GATHER_HERO_SLOT_CENTERS
        minus = config.GATHER_HERO_SLOT_MINUS
        keep = min(range(len(centers)),
                   key=lambda i: abs(centers[i] - match.x))
        print(f"[Gather] {resource}: keeping the correct gatherer (slot "
              f"{keep + 1}); removing the others.")
        remove = [i for i in range(len(minus)) if i != keep]
        for i in sorted(remove, reverse=True):   # right-to-left
            controller.tap(*minus[i])
            time.sleep(0.5)
        return True

    # -- OCR ---------------------------------------------------------------
    def _read_capacity(self, controller: ADBController) -> int | None:
        """OCR the node card's 'Capacity' value (dark text on the light card)."""
        x1, y1, x2, y2 = config.GATHER_CARD_CAPACITY_REGION
        crop = controller.screenshot()[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789,").strip()
        return self._to_int(txt)

    def _read_carry(self, controller: ADBController) -> int | None:
        """OCR the deploy screen's carry capacity (white text on a brown bar)."""
        x1, y1, x2, y2 = config.GATHER_CARRY_REGION
        crop = controller.screenshot()[y1:y2, x1:x2]
        # High threshold isolates the bright white glyph fill from the grey
        # resource icon that sits just left of the number (else it misreads).
        mask = cv2.inRange(crop, (220, 220, 220), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789,").strip()
        return self._to_int(txt)

    @staticmethod
    def _to_int(txt: str) -> int | None:
        digits = txt.replace(",", "").strip()
        return int(digits) if digits.isdigit() else None

    # -- level slider (resource floor is 1, not the Terror's 3) ------------
    def _set_level(self, controller: ADBController, target: int) -> None:
        """Drive the shared level slider to `target`: push to the floor with '-',
        then climb with '+' using OCR of the value box. Resources go down to 1."""
        target = max(config.GATHER_LEVEL_MIN,
                     min(config.GATHER_LEVEL_MAX, target))
        for _ in range(config.GATHER_LEVEL_MAX + 1):     # reach the floor
            controller.tap(*config.TERROR_LEVEL_MINUS)
            time.sleep(0.15)
        for _ in range(config.GATHER_LEVEL_MAX + 1):     # climb to target
            current = self._read_level(controller)
            if current is not None and current >= target:
                break
            controller.tap(*config.TERROR_LEVEL_PLUS)
            time.sleep(0.25)

    def _read_level(self, controller: ADBController) -> int | None:
        x1, y1, x2, y2 = config.TERROR_LEVEL_BOX
        crop = controller.screenshot()[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (140, 140, 140), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
        return int(txt) if txt.isdigit() else None

    # -- march queues ------------------------------------------------------
    def _free_queue_count(self, controller: ADBController) -> int | None:
        """How many march queues are free, retrying to ride out a transient OCR
        miss on the 'Marching N/M' panel. Returns None only if every attempt
        failed."""
        for i in range(4):
            value = self._read_free_queues(controller)
            if value is not None:
                return value
            if i < 3:
                time.sleep(1.0)
        return None

    def _read_free_queues(self, controller: ADBController) -> int | None:
        """One read of the free-queue count from the world-map 'Marching N/M'
        panel. The panel is ABSENT when every queue is home -> all free. Returns
        None if the panel is up but the counter could not be read this instant."""
        if not self._ensure_world(controller):
            return None
        screen = controller.screenshot()
        if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                             config.MARCHING_PANEL_THRESHOLD).found:
            return config.MARCH_MAX_QUEUES
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
        busy, total = int(match.group(1)), max(int(match.group(2)), 1)
        return max(0, total - busy)

    # -- navigation (shared logic with the Terror hunt) --------------------
    def _open_search(self, controller: ADBController) -> bool:
        # Already on the search panel (its "Search" button is showing)? Done.
        if find_template(controller.screenshot(), "search_button.png",
                         0.80).found:
            return True
        for _ in range(3):
            if find_template(controller.screenshot(), "world_search.png",
                             0.80).found:
                return self._tap(controller, "world_search.png", wait=2.0,
                                 threshold=0.80)
            time.sleep(1.0)
        if not self._tap(controller, "home_bottom_menu.png", wait=2.5):
            return False
        return self._tap(controller, "world_search.png", wait=2.0, threshold=0.80)

    def _ensure_world(self, controller: ADBController) -> bool:
        where = self._current_screen(controller)
        if where == "world":
            return True
        if where != "home" and not self._go_home(controller):
            return False
        return self._tap(controller, "home_bottom_menu.png", wait=2.5)

    def _go_home(self, controller: ADBController) -> bool:
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
        return self._is_on_home_screen(controller)

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


TASK = GatherResourcesTask(
    name="Gather Resources",
    detect="home_bottom_menu.png",         # runs from the home screen
    loop=True,                             # keeps filling queues each interval
    interval=config.GATHER_INTERVAL,
    home_marker="home_bottom_menu.png",
    recover_max_tries=4,
)
