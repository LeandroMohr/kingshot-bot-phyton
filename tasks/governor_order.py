"""Task: issue the daily Governor Orders (the "scales"/balance icon).

From the city, the right-edge stack of icons holds the Governor Order "scales"
just above the email icon (the paw above it may be missing on low-level
accounts, so the email is the anchor). The screen is a 2x3 grid of order books.
This task issues three orders in a STRICT sequence, needing 250,000 stars total:

  1. Productivity Day (column 1, last row) — 50,000 stars.
  2. Rush Job          (column 2, first row) — 150,000 stars (gives resources,
                        then a "Rewards" modal appears a few seconds later).
  3. Festivities       (column 2, last row) — 50,000 stars.

Issuing an order takes a single tap on "Issue" (no confirmation), closes the
screen and returns to the city with a few seconds of on-screen effects, so the
scales are reopened for each order. If the star balance is below 250,000 nothing
is issued (a partial sequence is not worth it). Orders already on cooldown show
no "Issue" button and are skipped.
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
import config


class GovernorOrderTask(Task):
    """Issues the three Governor Orders in sequence when the balance allows."""

    def execute(self, controller: ADBController) -> str:
        handle_connection_lost(controller)
        if not go_to_home_screen(controller):
            print("[Governor] Could not reach the city; will retry.")
            return Outcome.FAILED

        # Open the Governor Order screen once to read the star balance up front.
        if not self._open_governor(controller):
            print("[Governor] Could not open the Governor Order screen.")
            self._go_home(controller)
            return Outcome.FAILED

        stars = self._read_stars(controller)
        print(f"[Governor] Star balance: {stars:,}.")
        if stars < config.GOV_TOTAL_COST:
            print(f"[Governor] Need {config.GOV_TOTAL_COST:,} stars for the full "
                  f"sequence; skipping.")
            self._go_home(controller)
            return Outcome.ABSENT

        # All three orders must be available (none on cooldown / active). If any
        # is unavailable, issue NOTHING this run (partial sequences are skipped).
        blocked = self._blocked_orders(controller)
        if blocked:
            print(f"[Governor] On cooldown/active: {', '.join(blocked)}; issuing "
                  f"nothing until all three are available.")
            self._go_home(controller)
            return Outcome.ABSENT

        issued: list[str] = []
        for i, (name, tap, cost, _region) in enumerate(config.GOV_ORDERS):
            # The screen is already open for the first order; reopen for the rest
            # (each issue returns to the city).
            if i > 0 and not self._open_governor(controller):
                print(f"[Governor] Could not reopen for {name}; stopping.")
                break
            state = self._issue_order(controller, name, tap, cost)
            if state == "issued":
                issued.append(name)
            elif state == "cooldown" and i == 0:
                # The book stayed open (no Issue button): leave that screen.
                self._back_to_city(controller)

        self._go_home(controller)

        if issued:
            print(f"[Governor] Issued: {', '.join(issued)}.")
            return Outcome.SUCCESS
        print("[Governor] No order issued (all on cooldown).")
        return Outcome.ABSENT

    # -- availability ------------------------------------------------------
    def _blocked_orders(self, controller: ADBController) -> list[str]:
        """Return the names of orders whose grid banner reads "On cooldown" or
        "Active" (i.e. NOT available to issue). Empty list = all three ready."""
        screen = controller.screenshot()
        blocked: list[str] = []
        for name, _tap, _cost, region in config.GOV_ORDERS:
            if not self._order_available(screen, region):
                blocked.append(name)
        return blocked

    @staticmethod
    def _order_available(screen, region: tuple[int, int, int, int]) -> bool:
        """True when a book's status-banner region has no cooldown/active text."""
        x1, y1, x2, y2 = region
        gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(thr, config="--psm 6").lower()
        return not any(kw in text for kw in config.GOV_UNAVAILABLE_KEYWORDS)

    # -- open / navigate ---------------------------------------------------
    def _open_governor(self, controller: ADBController) -> bool:
        """Tap the scales icon (anchored to the email icon) and confirm the
        Governor Order screen opened by reading a star balance."""
        for _ in range(3):
            x, y = self._balance_point(controller)
            controller.tap(x, y)
            time.sleep(2.5)
            if self._read_stars(controller) > 0:
                return True
            # A speech bubble may have covered the icon; let it clear and retry.
            time.sleep(1.5)
        return False

    def _balance_point(self, controller: ADBController) -> tuple[int, int]:
        """Locate the scales icon. Prefer the email anchor (always present, the
        scales sit GOV_BALANCE_FROM_EMAIL_DY px above it); fall back to the
        scales template, then a fixed position."""
        screen = controller.screenshot()
        email = find_template(screen, config.GOV_EMAIL_ICON, 0.85)
        if email.found:
            return email.x, email.y - config.GOV_BALANCE_FROM_EMAIL_DY
        scales = find_template(screen, config.GOV_BALANCE_ICON, 0.85)
        if scales.found:
            return scales.x, scales.y
        return config.GOV_BALANCE_FALLBACK_TAP

    def _issue_order(self, controller: ADBController, name: str,
                     book_tap: tuple[int, int], cost: int) -> str:
        """Open an order's book and issue it. Returns "issued", "cooldown" (no
        Issue button — already active) or "failed"."""
        controller.tap(*book_tap)
        time.sleep(1.8)
        if not find_template(controller.screenshot(), config.GOV_ISSUE_BUTTON,
                             0.8).found:
            print(f"[Governor] {name}: no Issue button (on cooldown); skipping.")
            return "cooldown"
        controller.tap(*config.GOV_ISSUE_TAP)
        # Issuing closes the screen and returns to the city with effects; the
        # Rush Job order also shows a "Rewards" modal a few seconds later.
        time.sleep(config.GOV_POST_ISSUE_DELAY)
        self._dismiss_rewards(controller)
        print(f"[Governor] {name}: issued (-{cost:,} stars).")
        return "issued"

    def _dismiss_rewards(self, controller: ADBController) -> None:
        """Dismiss any modal (e.g. the Rush Job "Rewards" screen) covering the
        city by tapping a neutral spot until the home bottom menu is visible."""
        for _ in range(3):
            if find_template(controller.screenshot(), config.HOME_MARKER,
                             self.detect_threshold).found:
                return
            controller.tap(*config.GOV_REWARDS_DISMISS_TAP)
            time.sleep(1.2)

    # -- OCR ---------------------------------------------------------------
    def _read_stars(self, controller: ADBController) -> int:
        """OCR the star balance at the top-right of the Governor Order screen,
        parsing the abbreviated "82.3M" / "250K" / "180,000" formats into units.
        Returns 0 if it cannot be read (e.g. the screen is not open)."""
        x1, y1, x2, y2 = config.GOV_STARS_REGION
        gray = cv2.cvtColor(controller.screenshot()[y1:y2, x1:x2],
                            cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        raw = pytesseract.image_to_string(
            thr, config="--psm 7 -c "
            "tessedit_char_whitelist=0123456789.,MKmk").strip()
        return self._parse_amount(raw)

    def _parse_amount(self, raw: str) -> int:
        """Parse "82.3M" -> 82_300_000, "250K" -> 250_000, "180,000" -> 180000."""
        text = raw.upper().replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*([MK]?)", text)
        if not match:
            return 0
        value = float(match.group(1))
        suffix = match.group(2)
        if suffix == "M":
            value *= 1_000_000
        elif suffix == "K":
            value *= 1_000
        return int(value)

    # -- helpers -----------------------------------------------------------
    def _back_to_city(self, controller: ADBController) -> None:
        """Leave an open Governor Order/book screen with the back key."""
        for _ in range(3):
            if find_template(controller.screenshot(), config.HOME_MARKER,
                             self.detect_threshold).found:
                return
            controller.back()
            time.sleep(1.0)

    def _go_home(self, controller: ADBController) -> bool:
        handle_connection_lost(controller)
        self._back_to_city(controller)
        return go_to_home_screen(controller)


TASK = GovernorOrderTask(
    name="Governor Order",
    detect="home_bottom_menu.png",   # available from the city
    loop=True,
    interval=config.GOV_INTERVAL,
    home_marker="home_bottom_menu.png",
)
