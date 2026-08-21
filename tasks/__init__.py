"""Central task registry.

To ADD a new task:
  1. Create a file under tasks/ with a descriptive name (e.g. collect_resources.py).
  2. In it, define a variable TASK = Task(...).
  3. Import it here and add it to the _MODULES list below, in the desired order.

ORDER matters: popup-closing tasks should come first, to clear the screen
before the others.

Reminder: by default each task runs ONCE. To repeat in a loop, set loop=True
(and adjust interval) in the task file.
"""
from __future__ import annotations

from tasks.base import Task, Step  # re-exported for use in the task files
from tasks import (
    dismiss_popups,
    help_alliance,
    collect_conquest,
    collect_vip,
    daily_missions,
    governor_order,
    rebel_conquest,
    alliance_chests,
    alliance_tech,
    buy_vip_points,
    hunt_beasts,
    hunt_terror,
    gather_resources,
    train_troops,
    intel_missions,
    arena,
)

# Evaluation order each cycle: popups first, then from the SIMPLEST/quickest
# tasks to the most complex or long-running ones (Terror hunting last, since it
# has many delays and drains stamina). To change the order, just move the lines
# below — this list is the single source of truth used by main.py.
_MODULES = [
    dismiss_popups,        # closes purchase/offer promos (must run first: clears the screen)
    help_alliance,         # one tap on the help balloon (loop 1min) — simplest
    collect_conquest,      # collects Conquest resources, quick idle claim (loop 1h)
    collect_vip,           # collects daily VIP points + free bundle (once per run)
    daily_missions,        # claims completed daily missions + milestone chests (loop 1h)
    governor_order,        # issues the 3 Governor Orders in sequence (loop 12h)
    rebel_conquest,        # resolves the Rebel Assault via Quick Challenge (loop 10min)
    alliance_tech,         # spends Alliance tech contribution points (loop 1h)
    alliance_chests,       # collects Alliance honor chest + Loot/Gift tabs (loop 30min)
    buy_vip_points,        # buys VIP XP in the Alliance Shop while below VIP 6 (loop 6h)
    train_troops,          # trains infantry/cavalry/archer at a chosen tier (loop 3h)
    arena,                 # opens the Arena of Glory ranking screen (PVP entry point) (loop 1h)
    intel_missions,        # dispatches Intel Mission balloons (hunt/battle/refugee), then Claim All (loop 6h) — BEFORE Hunt Terror
    gather_resources,      # fills free march queues with resource-gathering marches (loop 20min)
    hunt_beasts,           # directly attacks Lv.30 Beasts with HNT, before Terror drains stamina
    hunt_terror,           # launches Terror rallies, gated by stamina, many delays — ALWAYS LAST (slow)
]

# Collect only the active tasks (TASK != None).
TASKS: list[Task] = [m.TASK for m in _MODULES if getattr(m, "TASK", None)]

__all__ = ["TASKS", "Task", "Step"]
