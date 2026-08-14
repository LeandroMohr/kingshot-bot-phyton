"""Task: Help alliance.

Shortcut via the handshake balloon on the main screen. The balloon only shows
up when there are requests; tapping it helps everyone and it disappears. No
window is opened, so there is nothing to close afterwards.

This task runs in a LOOP (loop=True), checking the balloon every 1min.
"""
from __future__ import annotations

from tasks.base import Task, Step

TASK = Task(
    name="Help alliance",
    detect="help_balloon.png",
    loop=True,        # keeps repeating (set to False for a single run)
    interval=60.0,    # 60s = shown as "1min"
    home_marker="home_bottom_menu.png",  # if a tap opens a window by mistake, close it
    steps=[
        Step(template="help_balloon.png", wait_after=2.0),
    ],
)
