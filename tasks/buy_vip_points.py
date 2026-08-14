"""Buy VIP XP in the Alliance Shop to level up the account's VIP.

WHY / WHEN
  Only the player decides to spend on VIP, so this task runs ONLY while the
  account is still below VIP 6 (i.e. current VIP level <= 5). Once the account
  reaches VIP 6 the task does nothing. The VIP level is read from the game and
  saved on the account profile (memory/accounts/<id>.json -> preferences.vip_level).

HOW THE VIP LEVEL IS READ
  On the home screen, the top-right corner has the gem shop cart and, just below
  it, the VIP badge showing "VIP N" (yellow when VIP is active). Tapping that
  badge opens the VIP screen which shows "Current Level: VIP N" as clean dark
  text -> we OCR that line (far more reliable than the busy home badge) and go
  back. N is the account's VIP level.

WHAT IT BUYS
  Alliance -> Shop. The shop has two tabs at the bottom: "Today" (refreshes every
  24h) and "Week" (every 7 days). Among the items, the VIP XP cards give VIP
  experience (two variants: "100 VIP XP" and "10 VIP XP"). Both share the same
  gold "V" gem icon on a blue card (only the small number on top differs), so one
  template (vip_xp_icon.png) finds both. We buy the MAXIMUM affordable amount of
  every VIP XP card in BOTH tabs, regardless of any discount (70/40/20% or full
  price), as long as the account has enough Alliance Tokens.

HOW A PURCHASE WORKS
  Tap the item's PRICE box (below the icon), NOT the icon (the icon opens a
  description tooltip). That opens the Buy modal with a quantity slider. Tap the
  up-arrow (top-right of the slider) to set the maximum available quantity; the
  orange button then shows the TOTAL token cost. If the total fits the tokens we
  have, tap that button to buy (the purchase is instant, no extra confirmation);
  otherwise we lower the quantity with the "-" button until it fits. After buying,
  the card shows "Sold out" (its coloured icon no longer matches the template, so
  it is skipped automatically). Finally we return to the home screen.

Runs in a LOOP (checked periodically) until the account reaches VIP 6.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template, find_all_templates
import config
import account_prefs


# -- gating ----------------------------------------------------------------
VIP_TARGET_LEVEL = 6                    # buy only while current level < this

# -- home VIP badge / VIP screen -------------------------------------------
VIP_BADGE_TAP = (497, 66)              # VIP badge on the home screen (top-right)
# "Current Level: VIP N" line on the VIP screen (y1, y2, x1, x2).
VIP_LEVEL_REGION = (100, 122, 158, 400)

# -- alliance shop ---------------------------------------------------------
ALLIANCE_SHOP_BUTTON = "alliance_shop_button.png"
SHOP_MARKER = "alliance_shop_marker.png"      # "Refreshes in:" banner (both tabs)
VIP_XP_ICON = "vip_xp_icon.png"               # gold "V" gem (both +10 and +100)
TODAY_TAB_TAP = (140, 932)
WEEK_TAB_TAP = (400, 932)
# Alliance-token counter, top-right of the shop (y1, y2, x1, x2), white text.
TOKENS_REGION = (10, 36, 438, 506)
# From a VIP XP icon centre, the price box sits this many pixels BELOW it.
PRICE_DY = 96
# Scroll the item grid to reveal more rows.
SHOP_SCROLL_FROM = (270, 700)
SHOP_SCROLL_TO = (270, 320)
MAX_SCROLLS = 8

# -- buy modal -------------------------------------------------------------
BUY_MODAL_MARKER = "buy_modal_marker.png"     # the "Buy" title
BUY_MAX_ARROW_TAP = (464, 520)                # up-arrow: set maximum quantity
BUY_MINUS_TAP = (81, 520)                     # "-": lower the quantity by one
BUY_QTY_REGION = (505, 538, 352, 420)         # quantity box (dark on light)
BUY_TOTAL_TAP = (270, 617)                    # orange total button = confirm buy
BUY_TOTAL_REGION = (600, 636, 196, 344)       # total cost (white on orange)
BUY_MODAL_CLOSE = (490, 314)                  # X of the Buy modal
MAX_PURCHASES = 20                            # safety cap on buys per run


class BuyVipPointsTask(Task):
    """Spends Alliance Tokens on VIP XP cards while the account is below VIP 6."""

    def execute(self, controller: ADBController) -> str:
        from executor.navigation import go_to_home_screen, open_alliance

        # 1. Make sure we start from the home screen and read the VIP level.
        if not go_to_home_screen(controller):
            return Outcome.FAILED
        level = self._read_vip_level(controller)
        if level is None:
            print("Could not read the VIP level; skipping VIP purchases.")
            return Outcome.ABSENT
        self._save_vip_level(level)
        print(f"Account VIP level: {level} (target < {VIP_TARGET_LEVEL}).")
        if level >= VIP_TARGET_LEVEL:
            return Outcome.ABSENT  # already VIP 6+, nothing to do

        # 2. Alliance -> Shop.
        if not open_alliance(controller):
            return Outcome.FAILED
        if not self._tap(controller, ALLIANCE_SHOP_BUTTON, wait=2.0):
            return Outcome.FAILED
        if not find_template(controller.screenshot(), SHOP_MARKER).found:
            self._go_home(controller)
            return Outcome.FAILED

        # 3. Buy every VIP XP card in both tabs.
        bought = 0
        for tab_tap in (TODAY_TAB_TAP, WEEK_TAB_TAP):
            controller.tap(*tab_tap)
            time.sleep(1.5)
            bought += self._buy_tab(controller)

        # 4. Back home.
        self._go_home(controller)
        return Outcome.SUCCESS if bought > 0 else Outcome.ABSENT

    # -- VIP level ---------------------------------------------------------
    def _read_vip_level(self, controller: ADBController) -> int | None:
        """Open the VIP screen from the home badge, OCR "Current Level: VIP N",
        go back and return N (or None if it could not be read)."""
        for _ in range(3):
            controller.tap(*VIP_BADGE_TAP)
            time.sleep(1.8)
            screen = controller.screenshot()
            if find_template(screen, "vip_screen_marker.png").found:
                y1, y2, x1, x2 = VIP_LEVEL_REGION
                gray = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, None, fx=3, fy=3,
                                  interpolation=cv2.INTER_CUBIC)
                _, thr = cv2.threshold(gray, 0, 255,
                                       cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                txt = pytesseract.image_to_string(thr, config="--psm 7").strip()
                controller.back()
                time.sleep(1.0)
                m = re.search(r"VIP\s*(\d+)", txt)
                return int(m.group(1)) if m else None
            controller.back()  # not the VIP screen -> undo and retry
            time.sleep(1.0)
        return None

    def _save_vip_level(self, level: int) -> None:
        """Persist the VIP level under the current account's preferences."""
        account_id = account_prefs.current_account_id()
        if account_id:
            account_prefs.set_pref(account_id, "vip_level", level)

    # -- buying ------------------------------------------------------------
    def _buy_tab(self, controller: ADBController) -> int:
        """Scan the current tab (scrolling down) and buy every VIP XP card that
        is affordable. Returns how many cards were purchased."""
        bought = 0
        prev_fp = None
        scrolls = 0
        while bought < MAX_PURCHASES:
            screen = controller.screenshot()
            matches = find_all_templates(screen, VIP_XP_ICON, 0.85, min_distance=40)
            if matches:
                # Buy the first one; the screen changes (sold out) so re-scan.
                m = matches[0]
                if self._buy_item(controller, m.x, m.y):
                    bought += 1
                    prev_fp = None  # screen changed; reset stall detection
                    time.sleep(1.0)
                    continue
                # Could not buy this card (unaffordable / modal glitch); to avoid
                # looping on it, scroll past the current view.
            # Nothing (more) buyable in view -> scroll for more rows.
            if scrolls >= MAX_SCROLLS:
                break
            fp = self._fingerprint(screen)
            if prev_fp is not None and fp == prev_fp:
                break  # reached the bottom (screen stopped changing)
            prev_fp = fp
            controller.swipe(*SHOP_SCROLL_FROM, *SHOP_SCROLL_TO, duration_ms=500)
            time.sleep(1.0)
            scrolls += 1
        return bought

    def _buy_item(self, controller: ADBController, icon_x: int, icon_y: int) -> bool:
        """Open the Buy modal for the VIP XP card at (icon_x, icon_y), set the
        maximum affordable quantity and confirm. Returns True if it purchased."""
        controller.tap(icon_x, icon_y + PRICE_DY)  # tap the PRICE box, not the icon
        time.sleep(1.2)
        if not find_template(controller.screenshot(), BUY_MODAL_MARKER).found:
            controller.back()  # description tooltip / nothing opened -> bail
            time.sleep(0.6)
            return False

        controller.tap(*BUY_MAX_ARROW_TAP)  # set maximum quantity
        time.sleep(0.7)
        tokens = self._ocr_int(controller.screenshot(), TOKENS_REGION)
        total = self._ocr_int(controller.screenshot(), BUY_TOTAL_REGION)
        if tokens is None or total is None:
            controller.tap(*BUY_MODAL_CLOSE)  # can't verify -> don't overspend
            time.sleep(0.6)
            return False

        # Lower the quantity until the total fits the tokens we have.
        guard = 0
        while total > tokens and guard < 30:
            qty = self._ocr_int(controller.screenshot(), BUY_QTY_REGION)
            if qty is not None and qty <= 1:
                break
            controller.tap(*BUY_MINUS_TAP)
            time.sleep(0.4)
            total = self._ocr_int(controller.screenshot(), BUY_TOTAL_REGION) or total
            guard += 1
        if total > tokens:
            controller.tap(*BUY_MODAL_CLOSE)  # can't afford even one
            time.sleep(0.6)
            return False

        controller.tap(*BUY_TOTAL_TAP)  # confirm (instant purchase)
        time.sleep(1.5)
        # If the modal is still up (e.g. a follow-up popup), close it.
        if find_template(controller.screenshot(), BUY_MODAL_MARKER).found:
            controller.tap(*BUY_MODAL_CLOSE)
            time.sleep(0.6)
        return True

    # -- OCR / helpers -----------------------------------------------------
    def _ocr_int(self, screen, region: tuple[int, int, int, int]) -> int | None:
        """OCR a white-on-dark number (tokens/total/qty) and return it as int."""
        y1, y2, x1, x2 = region
        crop = screen[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (200, 200, 200), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789,").strip()
        digits = txt.replace(",", "")
        return int(digits) if digits.isdigit() else None

    def _fingerprint(self, screen) -> bytes:
        """Tiny grayscale fingerprint to detect when scrolling stops moving."""
        small = cv2.resize(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY), (32, 32))
        return small.tobytes()

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
        for _ in range(self.recover_max_tries + 1):
            if self._is_on_home_screen(controller):
                return True
            controller.back()
            time.sleep(1.2)
        return self._is_on_home_screen(controller)


TASK = BuyVipPointsTask(
    name="Buy VIP Points",
    detect="home_bottom_menu.png",         # available whenever we can reach home
    loop=True,                             # keep checking until VIP 6 is reached
    interval=21600.0,                      # every 6h (shop refreshes daily/weekly)
    home_marker="home_bottom_menu.png",    # proof it returned to the city
    recover_max_tries=4,
)
