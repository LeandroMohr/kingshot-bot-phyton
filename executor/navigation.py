"""Navigation — getting the game to the city home screen.

This is the "make the screen usable before running tasks" layer. It handles:
  - waiting for the game to finish loading (wait_until_game_loaded),
  - making sure the game is the foreground app (ensure_game_ready),
  - clearing popups / forced tutorials until the home screen is clean
    (go_to_home_screen).

Naming (to end the old ensure_home / _on_home confusion):
  - is_on_home_screen(...)   -> a pure CHECK: are we on the home screen right now?
  - go_to_home_screen(...)   -> an ACTION: recover to the home screen (dismiss
                                popups, follow tutorial highlights, back key).
"""
from __future__ import annotations

import time

from adb_controller import ADBController
from vision import find_template
import config
from executor.tutorial import (
    detect_tutorial_highlight,
    screen_fingerprint,
    screens_similar,
)


def is_on_home_screen(controller: ADBController) -> bool:
    """True if the city home screen (bottom menu) is currently visible."""
    try:
        screen = controller.screenshot()
        return find_template(screen, config.HOME_MARKER).found
    except Exception:
        return False


def wait_until_game_loaded(controller: ADBController) -> bool:
    """After launching the game, poll frequently until it has left the loading
    screen. The game is considered loaded once the home screen OR a dismissable
    overlay (promo popup / tutorial) is visible (those are closed later by
    go_to_home_screen). Returns True if it loaded within the timeout."""
    deadline = time.monotonic() + config.GAME_LAUNCH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            screen = controller.screenshot()
            if find_template(screen, config.HOME_MARKER).found:
                return True
            if any(find_template(screen, m).found for m in config.DISMISS_MARKERS):
                return True  # loaded, but an overlay is covering the home
            # A "Connection lost" modal can pop up while loading (or repeatedly
            # if the network is still flaky). Tap Reconnect inline (no recursion)
            # and keep waiting for the reload.
            if find_template(screen, config.CONNECTION_LOST_MARKER).found:
                print("Connection lost while loading. Tapping Reconnect...")
                btn = find_template(screen, config.RECONNECT_BUTTON)
                controller.tap(btn.x, btn.y) if btn.found else controller.tap(*config.RECONNECT_TAP)
                time.sleep(2.0)
        except Exception:
            pass  # screen may not be ready right after launching
        time.sleep(config.GAME_READY_POLL)
    return False


def ensure_game_ready(controller: ADBController, announce_if_open: bool = False) -> None:
    """Make sure the game is on screen (foreground). Checking only the visuals
    is unreliable, so we ask the emulator which app is focused. If Kingshot is
    not the foreground app (closed, crashed or minimized to the BlueStacks
    launcher), we launch/bring it up and wait for the home screen."""
    if controller.is_app_foreground(config.GAME_PACKAGE):
        if announce_if_open:
            print("Kingshot is already open.")
        return
    print("Kingshot is not in the foreground. Opening the game...")
    controller.launch_app(config.GAME_PACKAGE)
    print("Waiting for Kingshot to load (may take a while if there is an update)...")
    if wait_until_game_loaded(controller):
        print("Game opened on the home screen!")
    else:
        print("The game took longer than expected to load; continuing anyway.")


def handle_connection_lost(controller: ADBController, screen=None) -> bool:
    """Handle the "Connection lost" modal caused by a network hiccup.

    When the internet oscillates the game shows a modal ("Unable to connect...")
    with two buttons: "Contact Us" and "Reconnect". We tap Reconnect and wait for
    the game to reload, so the caller can resume/restart its flow. Returns True if
    a modal was found and handled. `screen` may be a pre-captured frame.
    """
    if screen is None:
        try:
            screen = controller.screenshot()
        except Exception:
            return False
    if not find_template(screen, config.CONNECTION_LOST_MARKER).found:
        return False
    print("Connection lost. Tapping Reconnect and waiting for the game to reload...")
    btn = find_template(screen, config.RECONNECT_BUTTON)
    if btn.found:
        controller.tap(btn.x, btn.y)
    else:
        controller.tap(*config.RECONNECT_TAP)  # fallback if the template misses
    time.sleep(2.0)
    # After reconnecting the game goes back to the loading screen; wait it out.
    wait_until_game_loaded(controller)
    return True


def dismiss_blocking_popups(controller: ADBController, screen=None) -> bool:
    """Tap the first known 'close/skip' button on screen (an X or tutorial Skip).

    Tries config.DISMISS_MARKERS in order — safer than 'back' and it never
    touches a purchase button. Returns True if it tapped one. `screen` may be a
    pre-captured frame to avoid an extra screenshot.
    """
    if screen is None:
        try:
            screen = controller.screenshot()
        except Exception:
            return False
    for marker in config.DISMISS_MARKERS:
        match = find_template(screen, marker)
        if match.found:
            print("Popup/tutorial on screen. Dismissing it...")
            controller.tap(match.x, match.y)
            time.sleep(1.2)
            return True
    return False


def go_to_home_screen(controller: ADBController) -> bool:
    """Recover to the city home screen before running the tasks.

    When the game opens it often shows welcome-back / promo popups or a tutorial
    (sometimes several in a row). This dismisses them by tapping the close X
    (orange / blue / white / dark variants) or the tutorial "Skip" button — never
    a purchase button. Forced tutorials without a Skip put a pulsing highlight on
    the spot to tap, which we follow generically. If nothing is recognized it
    falls back to the 'back' key. A forced tutorial can chain many steps, so we
    keep going while we make progress; if the screen stops changing (we're stuck
    on a step we can't perform on our own) we ask the user to do it. Returns True
    if home was reached."""
    prev_fp = None
    stuck = 0
    for _ in range(config.HOME_RECOVER_TRIES):
        try:
            screen = controller.screenshot()
        except Exception:
            screen = None

        # Progress check: did the last action change anything?
        fp = screen_fingerprint(screen)
        if screens_similar(fp, prev_fp):
            stuck += 1
        else:
            stuck = 0
        prev_fp = fp

        # 0. Network hiccup: a "Connection lost" modal blocks everything. Tap
        #    Reconnect and wait for the reload, then re-evaluate from scratch.
        if screen is not None and handle_connection_lost(controller, screen):
            prev_fp = None
            stuck = 0
            continue

        # 1. Dismiss any overlay first (an X or Skip may sit on top of the home).
        if screen is not None and dismiss_blocking_popups(controller, screen):
            continue

        # 1b. On the WORLD map the home menu is not shown, and the map is full of
        #     animated glows (rally fires, event banners, balloons, gift icons)
        #     that would fool the tutorial-highlight detector into an endless
        #     "following the highlight" loop. Recognize the world map and return
        #     to the city with its Town button (never 'back', which would pop the
        #     "Quit game?" dialog).
        if screen is not None and find_template(screen, config.WORLD_MARKER,
                                                0.80).found:
            town = find_template(screen, config.WORLD_MARKER, 0.80)
            print("On the world map. Returning to the city...")
            controller.tap(town.x, town.y)
            time.sleep(2.0)
            continue

        # 2. Forced tutorial: follow the pulsing highlight (tap where it points).
        #    While the city home is already visible, its buildings shimmer, so
        #    require a clearly larger glow before treating it as a real step.
        on_home = screen is not None and find_template(screen, config.HOME_MARKER).found
        min_area = config.GLOW_STRONG_AREA if on_home else config.GLOW_MIN_AREA
        glow = detect_tutorial_highlight(controller, min_area=min_area)
        if glow is not None and glow.found:
            if stuck >= config.HOME_STUCK_LIMIT:
                print("I couldn't get past this tutorial step on my own. "
                      "Please complete the highlighted action in the game; "
                      "I'll continue automatically once it's done.")
                return False
            print("Tutorial step detected. Following the highlight...")
            controller.tap(glow.x, glow.y)
            time.sleep(1.5)
            continue

        # 3. Nothing to dismiss/tap: if the home menu is visible we are done.
        if on_home:
            return True

        # 4. Not home and no known overlay: fall back to the back key.
        if stuck >= config.HOME_STUCK_LIMIT:
            print("I'm stuck on a screen I don't recognize. Please close it or "
                  "return to the city; I'll continue automatically afterwards.")
            return False
        controller.back()
        time.sleep(1.0)

    # Ran out of recovery actions. If a highlight is still there, ask for help.
    try:
        highlight = detect_tutorial_highlight(controller)
        if highlight is not None and highlight.found:
            print("I couldn't get past this tutorial step on my own. "
                  "Please complete the highlighted action in the game; "
                  "I'll continue automatically once it's done.")
            return False
    except Exception:
        pass

    if is_on_home_screen(controller):
        return True
    print("Could not reach the home screen; will try again next cycle.")
    return False


def open_alliance(controller: ADBController) -> bool:
    """Open the Alliance screen from the city home screen.

    Recovers to the home screen first, then taps the "Alliance" button on the
    bottom menu (falling back to fixed coords if the template misses). Confirms
    success by looking for the "Chests" button, which only exists on the Alliance
    screen. Returns True once the Alliance screen is open.
    """
    if not go_to_home_screen(controller):
        return False
    for _ in range(3):
        screen = controller.screenshot()
        # Already on the Alliance screen? (Chests button visible.)
        if find_template(screen, config.ALLIANCE_CHESTS_BUTTON).found:
            return True
        btn = find_template(screen, config.ALLIANCE_HOME_BUTTON)
        if btn.found:
            controller.tap(btn.x, btn.y)
        else:
            controller.tap(*config.ALLIANCE_HOME_TAP)  # fallback coords
        time.sleep(1.8)
        if find_template(controller.screenshot(),
                         config.ALLIANCE_CHESTS_BUTTON).found:
            return True
    return False

