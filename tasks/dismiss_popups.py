"""Task: Dismiss purchase/promo popups.

NOTE: During navigation, popup dismissal is already handled generically by
executor.navigation.go_to_home_screen (it taps the known close-X / Skip markers
before every task pass). This standalone task is kept as a disabled placeholder
for cases where we want a dedicated, timed popup-watcher.

Project rule (free-to-play): NEVER tap real-money purchase buttons (e.g.
"$61.90", "TOP UP NOW", monthly cards). Only close them with the X.

By default it runs once; to close popups continuously, use loop=True.
Uncomment and adjust once a dedicated template is needed.
"""
from __future__ import annotations

from tasks.base import Task, Step

TASK = None  # disabled: popup dismissal is handled by executor.navigation

# TASK = Task(
#     name="Dismiss popups",
#     detect="close_x_promo.png",
#     loop=True,        # popups may reappear; keep watching
#     interval=5.0,
#     steps=[Step(template="close_x_promo.png", wait_after=1.0)],
# )
