"""Per-account planning data (heroes, gear, troop stock, event formations,
resource stock) edited in the control panel's Conta / Tropas / Eventos /
Coleta pages. Stored as memory/planning/<account_id>.json:

    {"snapshot": {...account snapshot...}, "formations": {...event formations...}}

The bot itself never reads it; it is the player's own planning sheet.
"""
from __future__ import annotations

import json
import shutil
from datetime import date

import config
from gui.i18n import UserError

PLANNING_DIR = config.BASE_DIR / "memory" / "planning"
BACKUP_DIR = PLANNING_DIR / "backups"


def _path(account_id: str):
    return PLANNING_DIR / f"{account_id}.json"


def load(account_id: str) -> dict | None:
    try:
        return json.loads(_path(account_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def save(account_id: str, data: dict) -> None:
    if not isinstance(data.get("snapshot"), dict) or not isinstance(data.get("formations"), dict):
        raise UserError("planning_shape")
    path = _path(account_id)
    PLANNING_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # One backup per account per day: autosave writes on every edit.
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"{account_id}.{date.today():%Y%m%d}.json"
        if not backup.exists():
            shutil.copy2(path, backup)
    path.write_text(json.dumps({"snapshot": data["snapshot"], "formations": data["formations"]},
                               indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
