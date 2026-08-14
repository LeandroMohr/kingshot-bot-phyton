"""Read the player's Governor Profile and keep a snapshot of it.

Read ONCE when the script starts (the account info here doesn't change during a
run, so re-reading it every cycle would be wasted work). Flow:
  1. Open the profile by tapping the avatar at a FIXED top-left coordinate
     (the picture may change, the position does not — config.PROFILE_AVATAR_TAP).
  2. Confirm the Governor Profile screen is open (config.PROFILE_MARKER).
  3. OCR the info box at the bottom:
       - left column  : stamina (e.g. "647/200").
       - right column : name (with [TAG] if in an alliance), permanent ID,
                        combat power, kills, alliance tag, current kingdom.
  4. Close the screen (back) and save the snapshot to memory/player_state.json.

OCR notes:
  - Right-column text is dark on a light box -> grayscale + Otsu works well.
  - The stamina pill is white text on green -> we isolate white pixels by color
    first, otherwise Otsu can't separate text from the green background.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from adb_controller import ADBController
from vision import find_template
import config
import account_prefs

_STATE_FILE = config.BASE_DIR / "memory" / "player_state.json"


# -- OCR helpers ------------------------------------------------------------
def _ocr_dark_on_light(crop, whitelist: str | None = None) -> str:
    """OCR dark text on a light background (the profile info box)."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cfg = "--psm 7"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(binary, config=cfg).strip()


def _ocr_white_text(crop, whitelist: str | None = None) -> str:
    """OCR white text over a colored background (e.g. the green stamina pill)."""
    mask = cv2.inRange(crop, (170, 170, 170), (255, 255, 255))  # keep white pixels
    mask = cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    mask = cv2.bitwise_not(mask)  # tesseract prefers dark text on white
    cfg = "--psm 7"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(mask, config=cfg).strip()


# -- parsing ----------------------------------------------------------------
def _after_colon(text: str) -> str:
    """Return whatever follows the first ':' (labels like 'ID:', 'Kills:')."""
    return text.split(":", 1)[1].strip() if ":" in text else text.strip()


def _parse_name(text: str) -> tuple[str | None, str]:
    """Split '[TAG]Player Name' into (alliance_tag, name). Tag is optional."""
    text = text.strip()
    match = re.match(r"\[([A-Za-z0-9]{1,6})\]\s*(.+)", text)
    if match:
        return match.group(1), match.group(2).strip()
    return None, text


def _digits(text: str) -> str | None:
    digits = re.sub(r"\D", "", text)
    return digits or None


# -- screen navigation ------------------------------------------------------
def open_player_profile(controller: ADBController):
    """Tap the fixed avatar coordinate and return the profile screen capture,
    or None if the Governor Profile screen did not open."""
    x, y = config.PROFILE_AVATAR_TAP
    controller.tap(x, y)
    time.sleep(1.8)
    screen = controller.screenshot()
    if find_template(screen, config.PROFILE_MARKER).found:
        return screen
    return None


def _extract_from_screen(screen) -> dict:
    """OCR the info box on an already-captured profile screen into a dict."""
    r = config.PROFILE_REGIONS

    def crop(region):
        x1, y1, x2, y2 = region
        return screen[y1:y2, x1:x2]

    tag, name = _parse_name(_ocr_dark_on_light(crop(r["name"])))
    alliance = _after_colon(_ocr_dark_on_light(crop(r["alliance"])))
    kingdom = _after_colon(_ocr_dark_on_light(crop(r["kingdom"])))
    stamina = _ocr_white_text(crop(config.PROFILE_STAMINA_REGION), "0123456789/")

    return {
        "name": name or None,
        "alliance_tag": tag or (alliance or None),
        "id": _digits(_after_colon(_ocr_dark_on_light(crop(r["id"]), "ID:0123456789"))),
        "power": _ocr_dark_on_light(crop(r["power"])) or None,
        "kills": _after_colon(_ocr_dark_on_light(crop(r["kills"]))) or None,
        "alliance": alliance or None,
        "kingdom": (re.sub(r"[^0-9#]", "", kingdom) or None),
        "stamina": stamina or None,
    }


def _save_state(data: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": "Latest player profile snapshot (dynamic game state). "
                       "Read once when the script starts.",
        "last_read": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "player": data,
    }
    _STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def read_player_profile(controller: ADBController, save: bool = True) -> dict | None:
    """Open the profile, OCR the info box, close it and (optionally) persist the
    snapshot to memory/player_state.json. Returns the parsed dict, or None if the
    profile screen could not be opened. Never raises: any failure returns None so
    it can't take down the main loop."""
    try:
        screen = open_player_profile(controller)
        if screen is None:
            print("Could not open the player profile (skipping this read).")
            return None
        data = _extract_from_screen(screen)
        controller.back()  # leave the profile screen
        time.sleep(1.0)
        if save:
            _save_state(data)
        # Remember which account this run is playing and keep a per-account file
        # (preferences + reference profile) under memory/accounts/<id>.json.
        account_id = data.get("id")
        account_prefs.set_current_account(account_id)
        if save and account_id:
            account_prefs.record_profile(account_id, data)
        print(
            "Player profile read: "
            f"{data.get('name')} (ID {data.get('id')}), power {data.get('power')}, "
            f"alliance {data.get('alliance')}, kingdom {data.get('kingdom')}."
        )
        return data
    except Exception as exc:  # never break the loop over a profile read
        print(f"Player profile read failed ({exc}).")
        try:
            controller.back()
        except Exception:
            pass
        return None
