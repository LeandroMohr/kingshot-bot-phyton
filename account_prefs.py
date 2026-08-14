"""Per-account preferences (keyed by the in-game account ID).

Each account has a different level, power, research, troops and heroes, so a
setting that works for account A may not work for account B (for example, the
highest Terror level it can safely farm). To avoid re-entering these values every
time — and to keep a saved history you can update or use as a reference — we store
ONE file per account under ``memory/accounts/<account_id>.json``.

Layout of each file::

    {
      "account_id": "259415100",
      "updated": "2026-07-29T13:33:23+00:00",
      "profile": { ...last-known Governor Profile snapshot... },
      "preferences": { "terror_level": 8, "rally_mode": "hnt", ... }
    }

The "current account" is set once per run, right after the Governor Profile is
read at startup (see ``executor.player_profile.read_player_profile``). It is kept
in memory (not read from a shared file) so two bot processes — one per emulator /
account — never step on each other's value. Callers that don't carry the ID
around can just use :func:`current_account_id`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_ACCOUNTS_DIR = config.BASE_DIR / "memory" / "accounts"

# Set once per run (per process) after the profile is read; None until then.
_current_account_id: str | None = None


# -- current account (in-memory, per process) ------------------------------
def set_current_account(account_id: str | int | None) -> None:
    """Remember which account this run/process is playing. Called once, right
    after the Governor Profile is read at startup."""
    global _current_account_id
    _current_account_id = str(account_id) if account_id else None


def current_account_id() -> str | None:
    """The account ID this run is playing, or None if it wasn't read."""
    return _current_account_id


# -- file persistence -------------------------------------------------------
def _account_file(account_id: str) -> Path:
    return _ACCOUNTS_DIR / f"{account_id}.json"


def load_prefs(account_id: str | None) -> dict:
    """Load the saved preferences for an account (empty dict if none yet)."""
    if not account_id:
        return {}
    try:
        data = json.loads(_account_file(str(account_id)).read_text())
        return data.get("preferences", {}) or {}
    except Exception:
        return {}


def save_prefs(account_id: str | None, prefs: dict,
               profile: dict | None = None) -> None:
    """Write the account file with ``prefs`` (and an optional profile snapshot).

    If ``profile`` is None any previously stored snapshot is preserved, so saving
    preferences never wipes the reference profile and vice-versa."""
    if not account_id:
        return
    account_id = str(account_id)
    _ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _account_file(account_id)
    existing = {}
    try:
        existing = json.loads(path.read_text())
    except Exception:
        pass
    payload = {
        "description": "Per-account preferences and last-known profile, keyed by "
                       "the in-game account ID. Settings that suit THIS account "
                       "(e.g. the Terror level it can farm) live under "
                       "'preferences'; 'profile' is a reference snapshot.",
        "account_id": account_id,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile if profile is not None else existing.get("profile"),
        "preferences": prefs,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def update_prefs(account_id: str | None, changes: dict) -> None:
    """Merge ``changes`` into the account's preferences and save."""
    if not account_id:
        return
    prefs = load_prefs(account_id)
    prefs.update(changes)
    save_prefs(account_id, prefs)


def get_pref(account_id: str | None, key: str, default: Any = None) -> Any:
    return load_prefs(account_id).get(key, default)


def set_pref(account_id: str | None, key: str, value: Any) -> None:
    update_prefs(account_id, {key: value})


def record_profile(account_id: str | int | None, profile: dict) -> None:
    """Store/refresh the account's reference profile snapshot, keeping its
    preferences. Creates the account file on first read."""
    if not account_id:
        return
    save_prefs(str(account_id), load_prefs(str(account_id)), profile=profile)
