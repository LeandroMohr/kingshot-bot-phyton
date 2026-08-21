"""Task: Beast Hunt (direct monster attacks on the world map).

This task reuses the queue, stamina, return tracking and recovery machinery from
Terror Hunt. The navigation after Search differs: Beasts use a direct Attack,
then load the HNT preset (Diana with the saved 50/20/30 troop ratio) and Deploy.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import cv2
import pytesseract

from adb_controller import ADBController
from vision import find_template
from tasks.hunt_terror import HuntTerrorTask
import account_prefs
import config


class HuntBeastsTask(HuntTerrorTask):
    """Continuously attack Beasts with the HNT formation until stamina is low."""

    log_label = "Beast Hunt"

    @staticmethod
    def _required_stamina(mode: str) -> int:
        return config.BEAST_STAMINA_COST

    def _launch_hunt(self, controller: ADBController, level: int,
                     mode: str) -> bool:
        if not self._open_search(controller):
            return self._fail("could not open the world search panel")

        screen = controller.screenshot()
        terror = find_template(screen, "terror_icon.png", 0.80)
        if not terror.found:
            return self._fail("could not locate the Terror tab used to anchor Beasts")
        controller.tap(terror.x + config.BEAST_CATEGORY_OFFSET_X, terror.y)
        time.sleep(1.5)

        if not self._set_level(controller, level):
            return False
        if not self._tap(controller, "search_button.png", wait=3.0,
                         threshold=0.80):
            return self._fail("could not tap Search")

        controller.tap(*config.BEAST_ATTACK_TAP)
        time.sleep(2.5)
        if not find_template(controller.screenshot(), "formation_hnt.png",
                             0.80).found:
            return self._fail("Attack did not open the formation screen")

        if not self._tap(controller, "formation_hnt.png", wait=2.0,
                         threshold=0.80):
            return self._fail("could not load the HNT preset")
        if not self._diana_loaded(controller):
            print(f"[{self.log_label}] Diana is unavailable; not deploying "
                  "without the HNT formation.")
            self._diana_busy = True
            self._go_home(controller)
            return False

        if not self._tap(controller, "deploy_button.png", wait=3.0,
                         threshold=0.80):
            return self._fail("could not tap Deploy")
        return True

    def _set_level(self, controller: ADBController, target: int) -> bool:
        """Move directly from the displayed level to target and verify it.

        A fresh OCR read is used after each batch, so a dropped tap is corrected
        without resetting the selector to Lv.1 or searching at the wrong level.
        """
        target = max(config.BEAST_LEVEL_MIN,
                     min(config.BEAST_LEVEL_MAX, target))
        initial = self._read_level_retry(controller)
        if initial is None:
            return self._fail("could not read the current Beast level")

        current = initial
        if current == target:
            print(f"[{self.log_label}] Beast level already Lv.{target}.")
            return True
        for _ in range(config.BEAST_LEVEL_ADJUST_PASSES):
            delta = target - current
            coordinate = (config.TERROR_LEVEL_PLUS if delta > 0
                          else config.TERROR_LEVEL_MINUS)
            for _ in range(abs(delta)):
                controller.tap(*coordinate)
                time.sleep(config.BEAST_LEVEL_TAP_DELAY)
            time.sleep(config.BEAST_LEVEL_SETTLE_DELAY)
            current = self._read_level_retry(controller)
            if current is None:
                return self._fail("could not verify the Beast level after adjustment")
            if current == target:
                print(f"[{self.log_label}] Beast level Lv.{initial} -> Lv.{target}.")
                return True

        return self._fail(
            f"Beast level remained Lv.{current}; expected Lv.{target}")

    def _read_level(self, controller: ADBController) -> int | None:
        """Read the Beast selector's white number from its tan value box."""
        x1, y1, x2, y2 = config.TERROR_LEVEL_BOX
        crop = controller.screenshot()[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (200, 200, 200), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6,
                          interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        text = pytesseract.image_to_string(
            mask,
            config="--psm 13 -c tessedit_char_whitelist=0123456789",
        ).strip()
        match = re.search(r"\d+", text)
        if not match:
            return None
        level = int(match.group())
        if config.BEAST_LEVEL_MIN <= level <= config.BEAST_LEVEL_MAX:
            return level
        return None

    def _read_level_retry(self, controller: ADBController) -> int | None:
        for attempt in range(config.BEAST_LEVEL_READ_TRIES):
            level = self._read_level(controller)
            if level is not None:
                return level
            if attempt < config.BEAST_LEVEL_READ_TRIES - 1:
                time.sleep(0.25)
        return None

    def _fail(self, reason: str) -> bool:
        print(f"[{self.log_label}] Failed: {reason}.")
        return False

    def _resolve_settings(self, prompt: bool = True) -> tuple[int, str]:
        level = self._load_beast_level()
        if prompt and sys.stdin and sys.stdin.isatty():
            answer = self._prompt(
                f"[{self.log_label}] Level Lv.{level}. Type "
                f"{config.BEAST_LEVEL_MIN}-{config.BEAST_LEVEL_MAX} to change "
                "(or wait to keep): ")
            if answer.isdigit():
                requested = int(answer)
                if config.BEAST_LEVEL_MIN <= requested <= config.BEAST_LEVEL_MAX:
                    level = requested
            self._save_beast_level(level)
        self._require_diana = True
        return level, "hnt"

    def _load_beast_level(self) -> int:
        account_id = account_prefs.current_account_id()
        source = account_prefs.load_prefs(account_id)
        if "beast_level" not in source:
            try:
                source = json.loads(Path(config.BEAST_LEVEL_FILE).read_text())
            except Exception:
                source = {}
        try:
            level = int(source.get("beast_level", config.BEAST_LEVEL_DEFAULT))
        except (TypeError, ValueError):
            level = config.BEAST_LEVEL_DEFAULT
        return max(config.BEAST_LEVEL_MIN, min(config.BEAST_LEVEL_MAX, level))

    def _save_beast_level(self, level: int) -> None:
        account_id = account_prefs.current_account_id()
        if account_id:
            account_prefs.update_prefs(account_id, {"beast_level": level})
            return
        payload = {
            "description": "Beast Hunt settings. beast_level (1-30) is the "
                           "Beast level attacked with the HNT preset.",
            "beast_level": level,
        }
        Path(config.BEAST_LEVEL_FILE).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False))


TASK = HuntBeastsTask(
    name="Hunt Beasts",
    detect="home_bottom_menu.png",
    loop=True,
    interval=5.0,
    home_marker="home_bottom_menu.png",
    recover_max_tries=4,
)
