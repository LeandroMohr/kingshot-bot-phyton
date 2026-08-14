"""Task: Rebel Conquest (Rebel Assault event).

On the home screen (city view), a rebel figure with a weapon over a red glowing
background and a countdown timer shows on the TOP-LEFT, just below the player's
profile photo. It is the "Rebel Assault" event: rebels/barbarians are about to
raid the city and we must defend it. The flow is:

  1. Be on the home screen (city view).
  2. Find the Rebel Assault icon on the top-left. If it is absent, the event is
     on cooldown (already defended) -> "nothing to do".
  3. Tap the icon to open the "Rebel Assault" modal (event name, countdown,
     rewards and two buttons at the bottom).
  4. Tap "Quick Challenge". This second button only appears once your power is
     high enough that the game guarantees the win, and it resolves the battle
     automatically (no need to enter the battle screen and move troops). If it
     is not there (power too low), we close the modal without doing the manual
     "Battle" and report "nothing to do".
  5. The result screen shows "Victory!". Tap "Claim Rewards" to finish.
  6. Claiming returns straight to the home screen.

Since the assault only shows up from time to time, this task runs in a LOOP with
a moderate interval; when the icon is absent it reports "nothing to do right
now" and returns home without doing anything.
"""
from __future__ import annotations

import time
from pathlib import Path

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config


class RebelConquestTask(Task):
    """Resolves the Rebel Assault event via Quick Challenge, with its own nav."""

    def execute(self, controller: ADBController) -> str:
        # 1. Must be on the home screen (bottom menu visible).
        if not self.is_available(controller):
            return Outcome.ABSENT

        # 2. Rebel Assault icon present? Only shows when there is a wave to fight.
        if not self._tap(controller, "rebel_assault_icon.png", wait=1.5, threshold=0.85):
            return Outcome.ABSENT  # on cooldown / nothing to defend

        # 3. The modal is open. Tap "Quick Challenge" (auto-resolves the battle).
        #    It only exists when power is high enough; otherwise skip the manual
        #    Battle and just close the modal.
        if not self._tap(controller, "rebel_quick_challenge.png", wait=2.5, threshold=0.85):
            self._go_home(controller)
            return Outcome.ABSENT

        # 4. "Victory!" screen -> claim the rewards.
        claimed = self._tap(controller, "rebel_claim_rewards.png", wait=2.5, threshold=0.85)
        if not claimed:
            # Fallback: tap the center to dismiss the rewards screen.
            self._tap_center(controller, wait=2.0)

        # 5. Back to the home screen.
        self._go_home(controller)
        return Outcome.SUCCESS

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


TASK = RebelConquestTask(
    name="Rebel Conquest",
    detect="home_bottom_menu.png",         # available when on the home screen
    loop=True,                             # the assault reappears over time
    interval=600.0,                        # re-check every 10 min
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
