"""Task: Collect the daily VIP rewards (VIP points + VIP daily free bundle).

Runs ONCE per bot run (loop=False), on the initial pass right after the game
opens. If nothing is collectable (already claimed today, or templates not
captured yet) it reports "nothing to do" and keeps re-checking on its interval
until it manages to collect once, then stops for the rest of the run.

Flow (all VIP screens have a fixed layout, so we confirm each step with a
template before tapping):

  1. Be on the home screen.
  2. Open the VIP screen from the "VIP X" badge in the top-right corner (the X
     is the current VIP level; when there is something to collect it shows a
     red dot). We match the constant V-diamond icon, not the changing number.
  3. On the VIP screen a chest in the top-right blinks with a red dot. Tapping
     it collects the daily VIP points.
  4. A "Rewards" modal appears (VIP XP, sign-in streak, tomorrow's points).
     Close it with the "Click to continue" button.
  5. Below the benefits list, if VIP is ACTIVE (bought with gems), the "VIP X
     Daily Free Bundle" has a green "Claim" button. Tap it to claim. If VIP is
     inactive the button is absent/greyed, so this step is optional and simply
     skipped.
  6. Claiming the bundle opens a "Rewards" modal closed by the footer text
     ("Tap anywhere to exit").
  7. Return to the home screen.

Note: whether VIP is active can also be read from the blue button at the bottom
of the VIP screen showing the remaining days/hours. We don't rely on it — we
just try the bundle's green Claim and skip it when it is not there.

Templates to capture (at the 540x960 ADB resolution):
  - vip_button.png        : the V-diamond VIP badge on the home top-right.
  - vip_daily_chest.png   : the blinking chest (red dot) on the VIP screen.
  - vip_continue.png      : the "Click to continue" button of the points modal.
  - vip_bundle_claim.png  : the green "Claim" of the VIP Daily Free Bundle.
  - vip_rewards_exit.png  : the "Tap anywhere to exit" footer of the bundle modal.
Until they exist, each tap is treated as "not found" and the task no-ops safely.
"""
from __future__ import annotations

import time
from pathlib import Path

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config


class VipDailyTask(Task):
    """Collects the daily VIP points and (if VIP is active) the free bundle."""

    def execute(self, controller: ADBController) -> str:
        # 1. Must be on the home screen.
        if not self.is_available(controller):
            return Outcome.ABSENT

        # 2. Open the VIP screen from the top-right badge.
        if not self._tap(controller, "vip_button.png", wait=2.5):
            # VIP entry not found (template not captured yet) -> nothing to do.
            return Outcome.ABSENT

        collected_points = False
        collected_bundle = False

        # 3. Collect the daily VIP points (blinking chest, top-right). Once
        #    collected it turns into a cooldown timer, so a match means it is
        #    still claimable today.
        if self._tap(controller, "vip_daily_chest.png", wait=2.0, threshold=0.80):
            # 4. Close the points "Rewards" modal. Its footer button sits in a
            #    bottom dead zone that ignores taps, so we dismiss it by tapping
            #    the center ("tap anywhere to continue").
            self._dismiss_modal(controller, "vip_continue.png")
            collected_points = True

        # 5. Claim the VIP Daily Free Bundle (only present/green when VIP is
        #    active; otherwise the template is not found and we skip it).
        if self._tap(controller, "vip_bundle_claim.png", wait=2.0, threshold=0.80):
            # 6. Close the bundle "Rewards" modal ("Tap anywhere to exit") the
            #    same way, by tapping the center.
            self._dismiss_modal(controller, "vip_rewards_exit.png")
            collected_bundle = True

        # 7. Return to the home screen.
        self._go_home(controller)
        return Outcome.SUCCESS if (collected_points or collected_bundle) else Outcome.ABSENT

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

    def _dismiss_modal(self, controller: ADBController, marker: str,
                       tries: int = 4) -> None:
        """Close a full-screen 'Rewards' modal by tapping the center.

        These modals close on a tap anywhere; their footer button is in a bottom
        zone the emulator ignores, so we tap the center. If the marker template
        exists we keep tapping until it disappears; otherwise we tap once."""
        if not (Path(config.TEMPLATES_DIR) / marker).exists():
            self._tap_center(controller, wait=1.5)
            return
        for _ in range(tries):
            screen = controller.screenshot()
            if not find_template(screen, marker, 0.80).found:
                return
            h, w = screen.shape[:2]
            controller.tap(w // 2, h // 2)
            time.sleep(1.5)

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the home screen, pressing 'back' only when needed."""
        for _ in range(self.recover_max_tries + 1):
            if self._is_on_home_screen(controller):
                return True
            controller.back()
            time.sleep(1.2)
        return self._is_on_home_screen(controller)


TASK = VipDailyTask(
    name="Collect VIP daily",
    detect="home_bottom_menu.png",         # available when on the home screen
    loop=False,                            # once per run (retries until it collects once)
    interval=1800.0,                       # spacing between attempts until it succeeds
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
