"""Task: Train troops (infantry, cavalry and archer).

Trains a batch of each of the three troop types at a chosen tier. Entering ANY
of the three troop buildings (Barracks/infantry, Stable/cavalry, Range/archer)
opens a training screen whose bottom tabs switch between all three types, so a
SINGLE visit trains all of them without navigating the map again.

Which tier to train works like the Terror Hunt level: a default (X = Apex, the
strongest) is kept PER ACCOUNT (each account can pick its own), saved after every
change, and the terminal asks once at the start with a short timeout — if the
operator does not answer in time the saved tier is kept.

Flow:
  1. Go to the city (home).
  2. Reach the Barracks DETERMINISTICALLY through the Power panel (the game
     auto-centres it for us, so no fragile map navigation is needed): tap the
     combat power -> "Bonus Overview" -> "Power" -> "Enhance" next to "Troop
     Power". The game jumps to the Barracks with the radial "Train" highlighted.
  3. Tap the highlighted "Train" to open the training screen.
  4. For each troop type (via the bottom tabs): if that type is already training
     (the "Speedups" button and a progress bar are shown) skip it; otherwise
     select the tier, set the batch quantity (config.TRAIN_MAX_QUANTITY: max, or
     the minimum while testing) and tap "Train" to start it. It NEVER taps
     "Finish" (that spends gems), per the player's rule.
  5. Return to the city.

Templates (captured at the 540x960 ADB resolution):
  - train_screen_marker.png : the list icon on the training screen (both states),
                              used to confirm the training screen is open.
  - train_start_button.png  : the cyan "Train" start button (idle state).
  - train_speedups.png      : the "Speedups" button (shown only while training),
                              used to tell that a troop type is already training.
"""
from __future__ import annotations

import json
import select
import sys
import time
from pathlib import Path

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
from executor import go_to_home_screen, handle_connection_lost
import config
import account_prefs


class TrainTroopsTask(Task):
    """Starts a training batch for infantry, cavalry and archer at a chosen
    tier, skipping any type that is already training."""

    def execute(self, controller: ADBController) -> str:
        # Clear any connection-lost modal, then start from a known state (city).
        # If we happen to start on the training screen, close it with its own
        # back arrow first (its animated glow confuses the generic recovery).
        handle_connection_lost(controller)
        self._exit_training_screen(controller)
        if not go_to_home_screen(controller):
            print("[Train] Could not reach the city; will retry.")
            return Outcome.FAILED

        tier = self._resolve_tier()
        print(f"[Train] Training tier {tier} (I..{config.TRAIN_TIER_MAX}).")

        # Reach a troop building and open its training screen.
        if not self._open_training_screen(controller):
            print("[Train] Could not open the training screen; will retry.")
            self._go_home(controller)
            return Outcome.FAILED

        # Train each troop type via the bottom tabs (no map navigation needed),
        # then RE-VALIDATE that every timer actually started, retrying the ones
        # that did not. Only leave once all three are training (or we run out of
        # passes). _train_one returns "training" when a timer is already running,
        # so re-running it on a later pass confirms the batch we just started.
        pending = list(config.TRAIN_TROOP_TYPES)
        training: set[str] = set()
        for _ in range(config.TRAIN_VALIDATE_PASSES):
            still: list[str] = []
            for troop in pending:
                state = self._train_one(controller, troop, tier)
                if state in ("started", "training"):
                    training.add(troop)
                else:
                    still.append(troop)
            pending = still
            if not pending:
                break

        self._go_home(controller)

        total = len(config.TRAIN_TROOP_TYPES)
        if len(training) == total:
            print(f"[Train] All {total} troop timers running "
                  f"({', '.join(sorted(training))}).")
            return Outcome.SUCCESS
        if training:
            print(f"[Train] Timers running for {', '.join(sorted(training))}; "
                  f"could not confirm {', '.join(pending)}.")
            return Outcome.SUCCESS
        return Outcome.FAILED

    # -- reach the training screen -----------------------------------------
    def _open_training_screen(self, controller: ADBController) -> bool:
        """Reach the Barracks through the Power panel (the game auto-centres it)
        and tap the highlighted radial "Train". Returns True once the training
        screen is open."""
        # home -> combat power -> "Bonus Overview" -> "Power" -> "Enhance" next to
        # "Troop Power", which makes the game jump straight to the Barracks.
        controller.tap(*config.TRAIN_POWER_TAP)
        time.sleep(1.4)
        controller.tap(*config.TRAIN_BONUS_POWER_BTN)
        time.sleep(1.5)
        controller.tap(*config.TRAIN_TROOP_POWER_ENHANCE)
        # The camera flies to the Barracks; then either its radial menu opens on
        # its own or only the building is highlighted. Tapping the (centred)
        # building opens the radial in both cases, so tap the building and then
        # its "Train" button, retrying until the training screen appears.
        time.sleep(2.5)
        for _ in range(4):
            controller.tap(*config.TRAIN_BARRACKS_BUILDING)
            time.sleep(1.2)
            controller.tap(*config.TRAIN_RADIAL_TRAIN_TAP)
            time.sleep(1.2)
            if find_template(controller.screenshot(), config.TRAIN_SCREEN_MARKER,
                             0.85).found:
                return True
            time.sleep(0.8)
        return False

    # -- train one troop type ----------------------------------------------
    def _train_one(self, controller: ADBController, troop: str, tier: int) -> str:
        """Switch to the troop's tab and start its training. Returns "started",
        "training" (already busy) or "failed"."""
        controller.tap(*config.TRAIN_TABS[troop])
        time.sleep(1.2)
        # A troop-promotion celebration popup can cover the screen and swallow
        # taps; clear it before reading/acting.
        self._dismiss_blocking_popup(controller)
        screen = controller.screenshot()
        # Already training? The "Speedups" button only shows while a batch runs.
        if find_template(screen, config.TRAIN_SPEEDUPS_BUTTON, 0.85).found:
            print(f"[Train] {troop}: already training, skipping.")
            return "training"
        # Idle: the cyan "Train" start button must be present.
        if not find_template(screen, config.TRAIN_START_BUTTON, 0.85).found:
            print(f"[Train] {troop}: training screen not idle as expected.")
            return "failed"

        tier = self._select_tier(controller, tier)
        # Set the batch quantity: max the capacity, or the minimum while testing.
        slider = (config.TRAIN_QTY_SLIDER_MAX if config.TRAIN_MAX_QUANTITY
                  else config.TRAIN_QTY_SLIDER_MIN)
        controller.swipe(*slider, 400)
        time.sleep(0.5)
        # Start the timed training. NEVER the "Finish" (gems) button.
        if not self._tap(controller, config.TRAIN_START_BUTTON, wait=1.5,
                         threshold=0.85):
            controller.tap(*config.TRAIN_START_TAP)
            time.sleep(1.5)
        # Starting a batch can trigger the "getting stronger" popup; clear it,
        # then confirm the timer started ("Speedups" now replaces "Train").
        self._dismiss_blocking_popup(controller)
        if find_template(controller.screenshot(), config.TRAIN_SPEEDUPS_BUTTON,
                         0.85).found:
            print(f"[Train] {troop}: started tier {tier}.")
            return "started"
        print(f"[Train] {troop}: could not confirm the batch started.")
        return "failed"

    def _dismiss_blocking_popup(self, controller: ADBController) -> None:
        """Dismiss a full-screen troop-promotion / "getting stronger" celebration
        that covers the training screen. While the training-screen marker is NOT
        visible (something is covering it), tap a harmless neutral spot to close
        the popup; stop as soon as the training screen is visible again."""
        for _ in range(3):
            if find_template(controller.screenshot(), config.TRAIN_SCREEN_MARKER,
                             0.85).found:
                return
            controller.tap(*config.TRAIN_POPUP_DISMISS_TAP)
            time.sleep(1.0)

    def _select_tier(self, controller: ADBController, tier: int) -> int:
        """Select the requested tier, falling back to the highest UNLOCKED tier
        when it is locked. A locked tier is greyed out and, once tapped, replaces
        the "Train" button with "Upgrade Now" (a "Reach ... to unlock" panel).
        Walk down from the requested tier until an unlocked one is selected and
        return the tier actually chosen."""
        tier = max(config.TRAIN_TIER_MIN, min(config.TRAIN_TIER_MAX, tier))
        for candidate in range(tier, config.TRAIN_TIER_MIN - 1, -1):
            self._tap_tier(controller, candidate)
            if self._tier_unlocked(controller):
                if candidate != tier:
                    print(f"[Train] tier {tier} locked; using highest unlocked "
                          f"tier {candidate}.")
                return candidate
            print(f"[Train] tier {candidate} locked; trying {candidate - 1}.")
        return config.TRAIN_TIER_MIN

    def _tap_tier(self, controller: ADBController, tier: int) -> None:
        """Scroll the tier row to the right page and tap the tier's hexagon.
        Tiers 6-10 live on the right page, 1-5 on the left page, both laid out on
        the same five slots."""
        tier = max(config.TRAIN_TIER_MIN, min(config.TRAIN_TIER_MAX, tier))
        if tier >= 6:
            scroll, slot = config.TRAIN_TIER_SCROLL_LEFT, tier - 6
        else:
            scroll, slot = config.TRAIN_TIER_SCROLL_RIGHT, tier - 1
        # Two swipes reach (and stay at) the end of the row deterministically.
        for _ in range(2):
            controller.swipe(*scroll, 400)
            time.sleep(0.6)
        controller.tap(config.TRAIN_TIER_SLOTS_X[slot], config.TRAIN_TIER_ROW_Y)
        time.sleep(0.6)

    def _tier_unlocked(self, controller: ADBController) -> bool:
        """True if the currently selected tier is unlocked: the cyan "Train"
        button is shown and the locked "Upgrade Now" button is not."""
        screen = controller.screenshot()
        if find_template(screen, config.TRAIN_UPGRADE_NOW_BUTTON, 0.85).found:
            return False
        return find_template(screen, config.TRAIN_START_BUTTON, 0.85).found

    # -- settings (tier) ---------------------------------------------------
    def _resolve_tier(self) -> int:
        tier = self._load_tier()
        if sys.stdin and sys.stdin.isatty():
            answer = self._prompt(
                f"[Train] Tier {tier}. Type {config.TRAIN_TIER_MIN}-"
                f"{config.TRAIN_TIER_MAX} to change (or wait to keep): ")
            if answer.isdigit():
                value = int(answer)
                if config.TRAIN_TIER_MIN <= value <= config.TRAIN_TIER_MAX:
                    tier = value
            self._save_tier(tier)
            print(f"[Train] Using tier {tier}.")
        return tier

    def _load_tier(self) -> int:
        # Prefer this account's saved tier; fall back to the shared file / default.
        account_id = account_prefs.current_account_id()
        src = account_prefs.load_prefs(account_id)
        if "train_tier" not in src:
            src = self._load_global_tier()
        try:
            tier = int(src.get("train_tier", config.TRAIN_TIER_DEFAULT))
        except Exception:
            tier = config.TRAIN_TIER_DEFAULT
        return max(config.TRAIN_TIER_MIN, min(config.TRAIN_TIER_MAX, tier))

    def _load_global_tier(self) -> dict:
        try:
            return json.loads(Path(config.TRAIN_TIER_FILE).read_text())
        except Exception:
            return {}

    def _save_tier(self, tier: int) -> None:
        account_id = account_prefs.current_account_id()
        if account_id:
            account_prefs.update_prefs(account_id, {"train_tier": tier})
            return
        path = Path(config.TRAIN_TIER_FILE)
        payload = {
            "description": "Train Troops settings. 'train_tier' (1-10) is which "
                           "troop tier to train; 10 = Apex (strongest). Re-read "
                           "before every training pass.",
            "train_tier": tier,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _prompt(self, message: str) -> str:
        """Print a prompt and return the typed line, or "" if the operator does
        not answer within config.TRAIN_TIER_PROMPT_TIMEOUT seconds."""
        print(message, end="", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [],
                                    config.TRAIN_TIER_PROMPT_TIMEOUT)
        if not ready:
            print()
            return ""
        return sys.stdin.readline().strip()

    # -- helpers -----------------------------------------------------------
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

    def _exit_training_screen(self, controller: ADBController) -> None:
        """Close the training screen with its own back arrow while its marker is
        visible. Its animated glow would otherwise trip the generic
        tutorial-highlight recovery in go_to_home_screen."""
        for _ in range(3):
            if not find_template(controller.screenshot(),
                                 config.TRAIN_SCREEN_MARKER, 0.85).found:
                return
            controller.tap(*config.TRAIN_BACK_ARROW)
            time.sleep(1.0)

    def _go_home(self, controller: ADBController) -> bool:
        handle_connection_lost(controller)
        self._exit_training_screen(controller)
        return go_to_home_screen(controller)


TASK = TrainTroopsTask(
    name="Train troops",
    detect="home_bottom_menu.png",   # available from the city
    loop=True,
    interval=config.TRAIN_INTERVAL,
    home_marker="home_bottom_menu.png",
)
