"""Task: Alliance Tech (contribution points).

Spend the alliance-tech contribution points before they cap out. Points refill
1 every 10 minutes up to 25 (a full refill takes ~4h10). Running hourly means
there are usually ~6 points to spend, so the pool never sits maxed.

Flow (our kingdom has the whole tree maxed, so the only open node is the
infinite "Covenant-Making" on the Battle tab):

  1. Open the Alliance screen and tap "Tech" (the book button).
  2. Go to the Battle tab and scroll to the last node, "Covenant-Making"
     (an endless contribution that exists precisely so people can keep earning
     points after the tree is finished). It carries the green thumbs-up buff
     (+20% contribution) whenever the alliance admins enable it.
  3. In its window there are TWO buttons:
       - LEFT  "Contribute [gem] 10"      -> spends GEMS. NEVER use it.
       - RIGHT "Contribute [resource] N"  -> spends a resource (bread/wood/
         stone/iron, whatever the node asks). This is the one to use.
     The right side shows "Attempts: X/25" = points still available. We HOLD the
     right button (a long press auto-fires it ~7 points/second) until it reaches
     0/25; at 0/25 the right button greys out and stops responding.
  4. Close the window and return to the city home screen.

Note: if the tree is NOT finished yet, the node with the green thumbs-up may be
elsewhere (any of the Growth / Territory / Battle tabs). We target the maxed-out
case (Battle -> Covenant-Making); a generic thumbs-up search could be added later.

Runs in a LOOP every hour.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config


# On-screen coordinates (540x960 capture).
BATTLE_TAB_TAP = (440, 210)          # the "Battle" tab
CONTRIBUTE_RESOURCE_TAP = (383, 771)  # RIGHT button (resource) — the one to use
COVENANT_MODAL_CLOSE = (508, 151)     # X of the Covenant-Making window
# Scroll the tech tree down to reveal the terminal Covenant-Making node.
TREE_SCROLL_FROM = (270, 700)
TREE_SCROLL_TO = (270, 350)
# "Attempts: X/25" counter next to the right button (y1, y2, x1, x2).
ATTEMPTS_REGION = (706, 732, 300, 478)

# Holding the right button auto-fires ~7 contributions/second, so one 4s hold
# clears a full pool; the loop re-checks and holds again for any remainder.
CONTRIBUTE_HOLD_MS = 4000
MAX_HOLD_ROUNDS = 8                   # safety cap on hold rounds


class AllianceTechTask(Task):
    """Spends alliance-tech contribution points on the infinite Covenant node."""

    def execute(self, controller: ADBController) -> str:
        # 1. Alliance -> Tech.
        from executor.navigation import open_alliance
        if not open_alliance(controller):
            return Outcome.FAILED
        if not self._tap(controller, "alliance_tech_button.png", wait=2.0):
            return Outcome.FAILED
        if not find_template(controller.screenshot(), "tech_screen_marker.png").found:
            self._go_home(controller)
            return Outcome.FAILED

        # 2. Battle tab -> reach the Covenant-Making node.
        controller.tap(*BATTLE_TAB_TAP)
        time.sleep(1.3)
        if not self._reach_covenant(controller):
            self._go_home(controller)
            return Outcome.ABSENT  # node not found (tree still building?)

        # 3. Confirm the Covenant window and contribute until the pool is empty.
        if not find_template(controller.screenshot(), "covenant_modal_marker.png").found:
            self._go_home(controller)
            return Outcome.FAILED
        contributed = self._contribute_all(controller)

        # 4. Close the window and go home.
        controller.tap(*COVENANT_MODAL_CLOSE)
        time.sleep(1.0)
        self._go_home(controller)
        return Outcome.SUCCESS if contributed > 0 else Outcome.ABSENT

    # -- reaching the node -------------------------------------------------
    def _reach_covenant(self, controller: ADBController) -> bool:
        """Find the Covenant-Making node (scrolling the tree down if needed) and
        tap it to open its contribution window."""
        for _ in range(4):
            m = find_template(controller.screenshot(), "covenant_node.png", 0.85)
            if m.found:
                controller.tap(m.x, m.y)
                time.sleep(1.8)
                return True
            controller.swipe(*TREE_SCROLL_FROM, *TREE_SCROLL_TO, duration_ms=400)
            time.sleep(1.0)
        return False

    # -- contributing ------------------------------------------------------
    def _contribute_all(self, controller: ADBController) -> int:
        """HOLD the RIGHT (resource) Contribute button until "Attempts" hits 0.
        A long press auto-fires it, spending the whole pool in a couple of holds.
        Never touches the LEFT gem button. Returns how many hold rounds fired
        (0 means the pool was already empty / nothing was contributed)."""
        x, y = CONTRIBUTE_RESOURCE_TAP
        prev_n = None
        rounds = 0
        stall = 0
        for _ in range(MAX_HOLD_ROUNDS):
            n = self._read_attempts(controller)
            if n is None:      # OCR could not read the counter -> stop safely
                break
            if n <= 0:         # pool empty (right button greyed out)
                break
            # Guard against a stuck counter (e.g. out of the required resource):
            # if it did not drop after the last hold, give up.
            if prev_n is not None and n >= prev_n:
                stall += 1
                if stall >= 2:
                    break
            else:
                stall = 0
            prev_n = n
            controller.swipe(x, y, x, y, duration_ms=CONTRIBUTE_HOLD_MS)
            time.sleep(1.0)
            rounds += 1
        return rounds

    def _read_attempts(self, controller: ADBController) -> int | None:
        """OCR the "Attempts: X/25" counter and return X (the points left)."""
        y1, y2, x1, x2 = ATTEMPTS_REGION
        for _ in range(3):
            roi = controller.screenshot()[y1:y2, x1:x2]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            txt = pytesseract.image_to_string(
                thr, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
            left = txt.split("/")[0] if "/" in txt else ""
            if left.isdigit():
                return int(left)
            time.sleep(0.3)
        return None

    # -- shared helpers ----------------------------------------------------
    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        """Find the template on the current screen and tap its center. Returns
        False if not found (or if the template file does not exist yet)."""
        if not (Path(config.TEMPLATES_DIR) / template).exists():
            return False
        screen = controller.screenshot()
        match = find_template(screen, template, threshold or self.detect_threshold)
        if not match.found:
            return False
        controller.tap(match.x, match.y)
        time.sleep(wait)
        return True

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the home screen, pressing 'back' only when needed."""
        for _ in range(self.recover_max_tries + 1):
            if self._is_on_home_screen(controller):
                return True
            controller.back()
            time.sleep(1.2)
        return self._is_on_home_screen(controller)


TASK = AllianceTechTask(
    name="Alliance Tech",
    detect="home_bottom_menu.png",         # available whenever we can reach home
    loop=True,                             # points refill over time
    interval=3600.0,                       # hourly (~6 points per run)
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
