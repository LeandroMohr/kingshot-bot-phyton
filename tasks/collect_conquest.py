"""Task: Collect Conquest resources (idle).

Flow (all Conquest screens have a fixed layout, so we use template matching to
confirm each step before tapping):

  1. Be on the home screen (the Conquest button is on the bottom bar).
  2. Tap the Conquest button to enter the Conquest screen.
  3. If the reward is ready, a green "Claim" button shows next to the glowing
     chest. Tap it to open the "Idle Income" modal. If that button is not
     there, nothing has accumulated yet -> report "nothing to do".
  4. Tap the modal's big CLAIM to collect.
  5. Tap "tap anywhere to exit" to leave the rewards screen.
  6. Return to the home screen (back button).

Since the chest is only available from time to time, this task runs in a LOOP
with a large interval; when there is nothing to collect, it reports
"nothing to do right now" and returns home without collecting.

NOTE (future evolution): when a menu option has a red dot, it means there is
something to do. Mapping those dots will later let the bot react to UI changes
instead of relying only on a timer.
"""
from __future__ import annotations

import time
from pathlib import Path

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config


class ConquestTask(Task):
    """Collects the Conquest idle resources, with its own navigation."""

    def execute(self, controller: ADBController) -> str:
        # 1. Must be on the home screen (Conquest button visible).
        if not self.is_available(controller):
            return Outcome.ABSENT

        # 2. Open the Conquest screen.
        if not self._tap(controller, "conquest_button.png", wait=3.0):
            return Outcome.FAILED

        # 3. Reward ready? The green "Claim" button shows only when there is
        #    something to collect. If it is absent, there is nothing to do.
        if not self._tap(controller, "conquest_ready.png", wait=2.2, threshold=0.80):
            self._go_home(controller)
            return Outcome.ABSENT

        # 4. Collect from the "Idle Income" modal (big green CLAIM).
        collected = self._tap(controller, "conquest_claim.png", wait=2.0, threshold=0.80)
        if collected:
            # 5. Leave the rewards screen ("tap anywhere to exit").
            if not self._tap(controller, "conquest_exit.png", wait=1.5, threshold=0.80):
                self._tap_center(controller, wait=1.5)

        # 6. Return to the home screen.
        self._go_home(controller)
        return Outcome.SUCCESS if collected else Outcome.ABSENT

    # -- helpers -----------------------------------------------------------
    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        """Look for the template on the current screen and tap its center.
        Returns False if not found (or if the template file does not exist yet)."""
        if not (Path(config.TEMPLATES_DIR) / template).exists():
            return False  # template not captured yet; treat as absent
        screen = controller.screenshot()
        match = find_template(screen, template, threshold or self.detect_threshold)
        if not match.found:
            return False
        controller.tap(match.x, match.y)
        time.sleep(wait)
        return True

    def _tap_center(self, controller: ADBController, wait: float = 1.0) -> None:
        """Tap the center of the screen (for 'tap anywhere to exit' screens)."""
        screen = controller.screenshot()
        h, w = screen.shape[:2]
        controller.tap(w // 2, h // 2)
        time.sleep(wait)

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the home screen, pressing 'back' only when needed."""
        for _ in range(self.recover_max_tries + 1):
            if self._is_on_home_screen(controller):
                return True
            controller.back()
            time.sleep(1.2)
        return self._is_on_home_screen(controller)


TASK = ConquestTask(
    name="Collect Conquest",
    detect="conquest_button.png",          # available when on the home screen
    loop=True,                             # repeats from time to time
    interval=3600.0,                       # checks every 1h (adjust if you want)
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
