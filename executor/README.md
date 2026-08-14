# Executor

The **"how to act"** layer: small, reusable routines the bot runs on screen,
built on top of `ADBController` (tap/swipe) and `vision` (template matching).
Higher levels (`tasks/`, and later `planner/`) reuse these instead of
re-implementing tap/wait/recover logic.

| Module          | Responsibility                                                      |
| --------------- | ------------------------------------------------------------------- |
| `actions.py`    | Primitives: `tap_template`, `tap_center`, `wait`.                   |
| `tutorial.py`   | `detect_tutorial_highlight` — find/follow the pulsing tutorial glow.|
| `navigation.py` | Get to the city home screen: loading, popups, tutorial, back key.   |

## Naming (ends the old `ensure_home` / `_on_home` confusion)

- `is_on_home_screen(controller)` — a **check**: are we on the home screen now?
- `go_to_home_screen(controller)` — an **action**: recover to the home screen
  (dismiss popups, follow tutorial highlights, press back).
- `wait_until_game_loaded(controller)` — poll until the game leaves the loading
  screen (was `wait_for_home`).
- `ensure_game_ready(controller)` — make Kingshot the foreground app.
- `detect_tutorial_highlight(controller)` — burst-capture and find the glow
  (was `_detect_glow`).
