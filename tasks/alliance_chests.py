"""Task: Alliance Chests.

Collect everything on the Alliance -> Chests screen:

  1. Open the Alliance screen (bottom menu) and tap "Chests".
  2. TOP honor chest (the big glowing chest with the key bar): when a wave of
     keys completes it lights up with a red count badge and can be opened.
       - Openable  -> tapping it shows a "Rewards" screen; dismiss it (tap an
                      empty area, "tap anywhere to exit").
       - Not ready -> tapping it only shows the "Honor Chest Reward" info modal
                      (a rewards PREVIEW with a "Send Alliance Gift" button we
                      must NEVER touch); close it with its X.
  3. Two tabs, each collected the same way — "Loot Chest" and "Alliance Gift":
       - If a green "Claim All" button is present, tap it; a "Rewards" screen
         appears -> dismiss it. The game only shows this button with 15+ items
         (that is also when the tab shows a red count badge), so its presence IS
         the "15 or more" signal — one tap claims the whole list at once. The
         Loot and Gift tabs put the button in different places, so each tab has
         its own template. (When there is nothing to claim the button is absent
         or greyed out, so we also verify it is actually green before tapping.)
       - Otherwise claim each gift individually: every card has a green "Claim"
         button that turns into "Claimed" in place (no modal, the card stays in
         the list). We tap every visible one, then scroll down by LESS than a
         screenful so nothing is jumped over, and repeat until the list stops
         moving. Because claimed cards no longer match the "Claim" template, the
         overlap is harmless. Expired gifts drop off the list on their own.
         This per-card scan is ONLY used on the Alliance Gift tab, and only when
         there is an unclaimed gift (a card with the green "Claim"/red-dot) and
         no "Claim All" button. The Loot tab is Claim-All-only and never scans.
  4. Return to the city home screen.

Runs in a LOOP with a long interval: chests/gifts trickle in over the day.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template, find_all_templates
from executor.navigation import open_alliance
import config


# On-screen coordinates (540x960 capture) that have no reliable template.
TOP_CHEST_TAP = (270, 150)       # the big honor chest at the top
HONOR_MODAL_CLOSE = (477, 191)   # X of the "Honor Chest Reward" info modal
REWARDS_EXIT_TAP = (270, 160)    # empty area above the "Rewards" banner
LOOT_TAB_TAP = (146, 301)        # fallback coords for the "Loot Chest" tab
GIFT_TAB_TAP = (395, 301)        # fallback coords for the "Alliance Gift" tab
# Swipe used to scroll the list down. Kept SHORTER than the visible run of
# cards (~3 cards, ~224px) so the drag overlaps the previous view and never
# jumps over an unclaimed card (the old 290px drag skipped 2-3 gifts).
SCROLL_FROM = (270, 720)
SCROLL_TO = (270, 540)

# Green "Claim All" button templates (Loot and Gift tabs place it differently).
CLAIM_ALL_TEMPLATES = ("chest_claim_all.png", "gift_claim_all.png")

# "Daily Loot Chest Limit: N/500" footer on the Loot Chest tab. Once N reaches
# the cap (500/500) the daily limit is hit: no more loot chests can be claimed
# today, so there is no point scrolling the list — we skip it and move on to the
# Alliance Gift tab.
LOOT_LIMIT_REGION = (100, 840, 440, 868)

MAX_SCROLLS = 20                 # safety cap while claiming a tab card by card
CLAIM_ALL_THRESHOLD = 0.90       # green and grey both match ~0.91+, so also...
CLAIM_ALL_MIN_GREEN = 40         # ...require green dominance (mean G-R) to tap


class AllianceChestsTask(Task):
    """Opens the Alliance Chests screen and collects the honor chest + both tabs."""

    def execute(self, controller: ADBController) -> str:
        # 1. Alliance -> Chests.
        if not open_alliance(controller):
            return Outcome.FAILED
        if not self._tap(controller, config.ALLIANCE_CHESTS_BUTTON, wait=2.0):
            return Outcome.FAILED
        # Confirm the Chests screen is open.
        if not find_template(controller.screenshot(),
                             "chests_screen_marker.png").found:
            self._go_home(controller)
            return Outcome.FAILED

        # 2. Top honor chest (claim if ready, otherwise just close the preview).
        self._open_top_chest(controller)

        # 3. Both tabs.
        self._claim_tab(controller, LOOT_TAB_TAP, "loot_chest_tab.png",
                        check_limit=True)
        self._claim_tab(controller, GIFT_TAB_TAP, "alliance_gift_tab.png",
                        is_gift=True)

        # 4. Back to the city.
        self._go_home(controller)
        return Outcome.SUCCESS

    # -- top honor chest ---------------------------------------------------
    def _open_top_chest(self, controller: ADBController) -> None:
        """Tap the big honor chest and handle whichever screen it opens."""
        controller.tap(*TOP_CHEST_TAP)
        time.sleep(1.8)
        screen = controller.screenshot()
        if find_template(screen, "chest_rewards_banner.png").found:
            # It was ready: a Rewards screen opened -> dismiss it.
            self._dismiss_rewards(controller)
        elif find_template(screen, "honor_chest_modal.png").found:
            # Not ready: only the info preview opened -> close it with its X.
            # (Never tap "Send Alliance Gift".)
            controller.tap(*HONOR_MODAL_CLOSE)
            time.sleep(1.2)

    # -- per-tab claiming --------------------------------------------------
    def _claim_tab(self, controller: ADBController, tab_tap: tuple[int, int],
                   tab_template: str, is_gift: bool = False,
                   check_limit: bool = False) -> None:
        """Select a tab and collect all its rewards.

        Per the user's rule, the expensive card-by-card list scan only runs for
        the Alliance Gift tab when there is an unclaimed gift AND no "Claim All"
        button in the footer. If "Claim All" is present it collects everything in
        one tap, so we skip the scan. The Loot tab never scans card by card.
        """
        # Select the tab (prefer the template, fall back to fixed coords).
        if not self._tap(controller, tab_template, wait=1.5):
            controller.tap(*tab_tap)
            time.sleep(1.5)

        # Loot tab only: if the daily loot-chest cap (500/500) is reached there is
        # nothing left to claim today, so skip the list entirely and move on.
        if check_limit and self._loot_limit_reached(controller):
            print("[Alliance Chests] Daily loot chest limit reached (500/500); "
                  "skipping the list and moving to Alliance Gift.")
            return

        # Fast path: with 15+ items a green "Claim All" collects the whole list
        # at once. Loop in case a fresh batch keeps the button around.
        claimed_all = False
        for _ in range(3):
            if not self._claim_all_if_active(controller):
                break
            claimed_all = True

        # If "Claim All" handled the list there is nothing left to scan. The Loot
        # tab is Claim-All-only, so it never falls through to the card scan.
        if claimed_all or not is_gift:
            return

        # Alliance Gift, no active "Claim All": only scan the list card by card
        # when there is actually an unclaimed gift (red-dot / green "Claim" card).
        if not self._has_unclaimed_gift(controller):
            print("[Alliance Chests] No unclaimed Alliance Gift; skipping scan.")
            return

        # Slow path: claim each remaining card, scrolling down in small
        # overlapping steps so no unclaimed gift is skipped. Claimed cards stay
        # in the list but no longer match "Claim", so re-seeing them is safe;
        # we stop once the list no longer moves (reached the bottom).
        prev_fp = None
        stale = 0
        for _ in range(MAX_SCROLLS):
            screen = controller.screenshot()
            for m in find_all_templates(screen, "chest_claim.png", 0.85):
                controller.tap(m.x, m.y)
                time.sleep(0.5)
            controller.swipe(*SCROLL_FROM, *SCROLL_TO, duration_ms=500)
            time.sleep(1.0)
            fp = self._list_fingerprint(controller.screenshot())
            if prev_fp is not None and fp == prev_fp:
                stale += 1
            else:
                stale = 0
            prev_fp = fp
            if stale >= 2:
                break

    def _has_unclaimed_gift(self, controller: ADBController) -> bool:
        """True when the Alliance Gift list shows at least one unclaimed gift.

        An unclaimed card carries a green "Claim" button (the red-dot / "presente
        não resgatado" indicator); claimed cards show grey "Claimed" text and no
        longer match the template. So any visible "chest_claim.png" match means
        there is still something to collect and the list is worth scanning.
        """
        screen = controller.screenshot()
        return bool(find_all_templates(screen, "chest_claim.png", 0.85))

    @staticmethod
    def _list_fingerprint(screen) -> bytes:
        """Small hash of the scrollable list area to detect when it stops
        moving (i.e. we have reached the bottom)."""
        roi = screen[400:860, 40:500]
        return cv2.resize(roi, (16, 16)).tobytes()

    def _loot_limit_reached(self, controller: ADBController) -> bool:
        """Read the "Daily Loot Chest Limit: N/500" footer; True when N >= the
        cap (the daily limit is reached). If it cannot be read, return False so
        claiming proceeds normally."""
        import re
        import pytesseract
        x1, y1, x2, y2 = LOOT_LIMIT_REGION
        crop = controller.screenshot()[y1:y2, x1:x2]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        _, t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(t, config="--psm 7").strip()
        m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
        if not m:
            return False
        current, cap = int(m.group(1)), int(m.group(2))
        return current >= cap

    def _claim_all_if_active(self, controller: ADBController) -> bool:
        """Tap a green "Claim All" button (Loot or Gift tab) if one is present
        and actually active. Returns True if it claimed (and dismissed the
        resulting Rewards screen)."""
        screen = controller.screenshot()
        for template in CLAIM_ALL_TEMPLATES:
            if not (Path(config.TEMPLATES_DIR) / template).exists():
                continue
            m = find_template(screen, template, CLAIM_ALL_THRESHOLD)
            if not m.found:
                continue
            # The disabled button matches the green template too, so verify
            # colour: the active button is clearly green (mean G >> R).
            roi = screen[max(0, m.y - 15):m.y + 15, max(0, m.x - 60):m.x + 60]
            if roi.size == 0:
                continue
            if float(roi[:, :, 1].mean() - roi[:, :, 2].mean()) < CLAIM_ALL_MIN_GREEN:
                continue  # greyed out -> nothing to claim here
            controller.tap(m.x, m.y)
            time.sleep(2.0)
            self._dismiss_rewards(controller)
            return True
        return False

    def _dismiss_rewards(self, controller: ADBController) -> None:
        """Close a "Rewards" screen ("tap anywhere to exit"). Tapping a reward
        icon does nothing, so we tap an empty area above the banner."""
        for _ in range(3):
            screen = controller.screenshot()
            if not find_template(screen, "chest_rewards_banner.png").found:
                return
            controller.tap(*REWARDS_EXIT_TAP)
            time.sleep(1.5)

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


TASK = AllianceChestsTask(
    name="Alliance Chests",
    detect="home_bottom_menu.png",         # available whenever we can reach home
    loop=True,                             # chests/gifts trickle in over time
    interval=1800.0,                       # re-check every 30 min
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
