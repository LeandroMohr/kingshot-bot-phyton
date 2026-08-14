"""Executor — reusable, low-level actions the bot performs on screen.

This package is the "how to do it" layer: small, generic routines built on top
of ADBController (tap / swipe / wait) and vision, that higher levels (tasks,
planner) reuse. Split by concern so files stay small:

- actions.py    : primitive helpers (tap a template, tap center, wait).
- tutorial.py   : detect and follow forced-tutorial highlights (the pulsing glow).
- navigation.py : get the game to the city home screen (loading, popups, tutorial).
- player_profile.py : open the Governor Profile and OCR the account info box.
"""
from __future__ import annotations

from executor.actions import tap_template, tap_center, wait
from executor.tutorial import detect_tutorial_highlight
from executor.navigation import (
    wait_until_game_loaded,
    ensure_game_ready,
    is_on_home_screen,
    dismiss_blocking_popups,
    handle_connection_lost,
    go_to_home_screen,
    open_alliance,
)
from executor.player_profile import read_player_profile, open_player_profile

__all__ = [
    "tap_template",
    "tap_center",
    "wait",
    "detect_tutorial_highlight",
    "wait_until_game_loaded",
    "ensure_game_ready",
    "is_on_home_screen",
    "dismiss_blocking_popups",
    "handle_connection_lost",
    "go_to_home_screen",
    "open_alliance",
    "read_player_profile",
    "open_player_profile",
]
