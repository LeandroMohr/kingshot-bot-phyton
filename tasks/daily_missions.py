"""Task: Daily Missions (the parchment / quest tracker on the home screen).

The city view shows a rolled-parchment icon on the bottom-left (a red badge with
a number when there is something to collect) next to the currently tracked
objective, e.g. "Clear Conquest Stage 400". Tapping it opens the daily-mission
panel.

The panel has two tabs at the bottom, "Growth" and "Daily". The "Daily" tab is
where the recurring rewards live:

  * A list of daily objectives (Help alliance, Train troops, Make contributions,
    Recruit heroes, ...). Each completed mission shows a green "Claim" button;
    incomplete ones show a "Go" button that NAVIGATES AWAY to perform the
    mission. The bot performs those missions through its OTHER tasks
    (help_alliance, train_troops, alliance_tech, arena, intel_missions, ...), so
    here we only COLLECT the rewards and never tap "Go".
  * A green "Claim All" button at the bottom collects every completed mission at
    once. It is present ONLY when at least one mission is claimable.
  * A top progress bar of activity points with milestone chests (40, 80, 120,
    160, 215, 270, 325 ...). Claiming missions raises the activity points and
    the reached milestone chests AUTO-OPEN as chained "Rewards" popups — no
    explicit tapping needed; we just dismiss the popups.

Flow (all validated live on emu 5605):
  1. Be on the home screen.
  2. Tap the parchment icon -> the panel opens on the "Daily" tab.
  3. While a green "Claim All" is present: tap it, then dismiss every chained
     "Rewards" popup (Claim-All rewards + auto-opened milestone chests) by
     tapping a neutral spot above the banner until the panel reappears.
  4. Read the STILL-PENDING missions (OCR of the list, scrolling through it) and,
     for each one that maps to an existing bot flow, run that flow to make
     progress (e.g. "Train 10 Infantry" -> train_troops, "Fight in Arena" ->
     arena, "... Alliance Contribution" -> alliance_tech, "Help ..." ->
     help_alliance). Missions with no linked flow (recruit hero, upgrade
     building, research, gather, ...) are left alone. The heavy/slow flows
     (intel_missions, hunt_terror) are OFF by default (config.DAILY_LINKED_MODULES)
     because they already run in the main loop.
  5. Close the panel (X), return to the city, run the linked flows, then reopen
     and Claim All again to collect anything that completed instantly.

Runs in a LOOP with an hourly interval: missions complete throughout the day as
the other tasks run, so we re-check and claim what became available.
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path

import cv2
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template, find_all_templates
import config


# Keyword (lowercased substring found in a mission title) -> module under tasks/
# whose TASK.execute() makes progress on that mission. Order within the scan is
# normalised by DAILY_RUN_ORDER below.
DAILY_LINKS = [
    ("infantry", "train_troops"),
    ("cavalry", "train_troops"),
    ("archer", "train_troops"),
    ("marksman", "train_troops"),
    ("contribution", "alliance_tech"),
    ("arena", "arena"),
    ("help", "help_alliance"),
    ("intel", "intel_missions"),
    ("terror", "hunt_terror"),
]

# Order in which linked flows are run (quick ones first).
DAILY_RUN_ORDER = [
    "help_alliance",
    "alliance_tech",
    "arena",
    "train_troops",
    "intel_missions",
    "hunt_terror",
]

# Missions that have NO linked flow but can be completed by tapping their
# in-panel "Go" button and doing a small native action. Keyword (lowercased
# substring in the mission title) -> handler method on the task. Only titles
# matched here are ever Go-tapped.
DAILY_GO_HANDLERS = [
    ("recruit", "_go_recruit_hero"),
]


class DailyMissionsTask(Task):
    """Opens the daily-mission panel and claims completed missions + milestones."""

    def execute(self, controller: ADBController) -> str:
        # 1. Must be on the home screen (bottom menu visible).
        if not self.is_available(controller):
            return Outcome.ABSENT

        # 2. Open the panel via the parchment icon (template, fixed-tap fallback).
        if not self._open_panel(controller):
            self._go_home(controller)
            return Outcome.ABSENT

        # 3. Make sure we are on the "Daily" tab (it opens there by default).
        controller.tap(*config.DAILY_TAB_TAP)
        time.sleep(1.0)

        # 4. First claim pass: collect whatever is already completed.
        claimed = self._claim_pass(controller)

        # 5. Read the still-pending missions and map them to existing bot flows.
        pending = self._scan_pending(controller) if config.DAILY_RUN_LINKED else []

        # 6. Close the panel and return home before running the linked flows.
        controller.tap(*config.DAILY_CLOSE_TAP)
        time.sleep(1.2)
        self._go_home(controller)

        # 7. Drive each pending mission through its linked flow (each returns home).
        ran = self._run_linked(controller, pending)

        # 8. If we ran anything, reopen the panel and claim what completed instantly.
        if ran:
            if self._open_panel(controller):
                controller.tap(*config.DAILY_TAB_TAP)
                time.sleep(1.0)
                claimed += self._claim_pass(controller)
                controller.tap(*config.DAILY_CLOSE_TAP)
                time.sleep(1.2)
                self._go_home(controller)

        return Outcome.SUCCESS if (claimed or ran) else Outcome.ABSENT

    # -- claiming ----------------------------------------------------------
    def _claim_pass(self, controller: ADBController) -> int:
        """Tap 'Claim All' (and dismiss the chained reward popups) until there is
        nothing left to claim. Returns how many Claim-All taps happened."""
        claimed = 0
        for _ in range(config.DAILY_MAX_CLAIM_PASSES):
            match = self._claim_all_match(controller)
            if not match.found:
                break
            controller.tap(match.x, match.y)  # tap the detected "Claim All" button
            time.sleep(1.5)
            self._dismiss_rewards(controller)
            claimed += 1
        return claimed

    # -- pending-mission scan ---------------------------------------------
    def _scan_pending(self, controller: ADBController) -> list[str]:
        """Scroll through the Daily list, OCR the mission titles and return the
        ordered, de-duplicated list of linked module names still pending."""
        x1, y1, x2, y2 = config.DAILY_LIST_REGION
        found: set[str] = set()
        prev_fp = None
        # The panel can remember its previous scroll position, so force the list
        # to the top before scanning downward.
        sx1, sy1, sx2, sy2 = config.DAILY_LIST_SWIPE
        for _ in range(config.DAILY_LIST_MAX_SCROLLS):
            controller.swipe(sx1, sy2, sx2, sy1, 300)  # reversed = scroll up (toward top)
            time.sleep(0.4)
        for _ in range(config.DAILY_LIST_MAX_SCROLLS):
            screen = controller.screenshot()
            band = screen[y1:y2, x1:x2]
            text = self._ocr_block(band).lower()
            for keyword, module in DAILY_LINKS:
                if keyword in text:
                    found.add(module)
            # Stop when the list stops moving (reached the bottom).
            fp = cv2.resize(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY),
                            (16, 16)).tobytes()
            if fp == prev_fp:
                break
            prev_fp = fp
            controller.swipe(sx1, sy1, sx2, sy2, 400)
            time.sleep(1.0)
        return [m for m in DAILY_RUN_ORDER if m in found]

    @staticmethod
    def _ocr_block(band) -> str:
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=1.6, fy=1.6)
        _, thr = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return pytesseract.image_to_string(thr, config="--psm 6")

    # -- linked flows ------------------------------------------------------
    def _run_linked(self, controller: ADBController, pending: list[str]) -> int:
        """Run the linked flow for each pending mission that is allowed. Returns
        how many flows were run."""
        ran = 0
        for module in pending:
            if module not in config.DAILY_LINKED_MODULES:
                continue
            try:
                mod = importlib.import_module(f"tasks.{module}")
                task = getattr(mod, "TASK", None)
                if task is None:
                    continue
                outcome = task.execute(controller)
                print(f"[Daily] linked '{module}': {outcome}")
                ran += 1
            except Exception as exc:  # a linked flow must never crash the checker
                print(f"[Daily] linked '{module}' failed: {exc}")
            # Make sure we are back home before the next flow.
            self._go_home(controller)
        return ran

    # -- panel navigation --------------------------------------------------
    def _open_panel(self, controller: ADBController) -> bool:
        """Tap the parchment icon, switch to the Daily tab and confirm the panel
        opened. True on success. (The 'Refreshes In:' marker only shows on the
        Daily tab, so we must select it before confirming.)"""
        for _ in range(3):
            if not self._tap(controller, config.DAILY_SCROLL_ICON, wait=1.8,
                              threshold=0.80):
                controller.tap(*config.DAILY_SCROLL_TAP)
                time.sleep(1.8)
            controller.tap(*config.DAILY_TAB_TAP)
            time.sleep(1.0)
            if self._panel_open(controller):
                return True
        return False

    def _panel_open(self, controller: ADBController) -> bool:
        screen = controller.screenshot()
        return find_template(screen, config.DAILY_PANEL_MARKER, 0.85).found

    def _claim_all_match(self, controller: ADBController):
        screen = controller.screenshot()
        return find_template(screen, config.DAILY_CLAIM_ALL,
                             config.DAILY_CLAIM_ALL_THRESHOLD)

    def _claim_all_present(self, controller: ADBController) -> bool:
        return self._claim_all_match(controller).found

    def _dismiss_rewards(self, controller: ADBController) -> None:
        """Dismiss the chained golden 'Rewards' popups (Claim All + milestone
        chests) by tapping a neutral spot above the banner until they are gone."""
        for _ in range(config.DAILY_MAX_DISMISS):
            screen = controller.screenshot()
            if not find_template(screen, config.DAILY_REWARDS_BANNER, 0.75).found:
                return
            controller.tap(*config.DAILY_REWARDS_EXIT_TAP)
            time.sleep(1.4)

    # -- helpers -----------------------------------------------------------
    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        """Look for the template and tap its center. False if not found (or the
        template file does not exist yet)."""
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


TASK = DailyMissionsTask(
    name="Daily Missions",
    detect="home_bottom_menu.png",         # available when on the home screen
    loop=True,                             # missions complete through the day
    interval=config.DAILY_INTERVAL,        # re-check hourly
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
