"""Events: explicit individual executions, never daily-loop tasks."""
from events.hidden_objects import EVENT as HIDDEN_OBJECTS
from events.castle_battle import EVENT as CASTLE_BATTLE
from events.fishing_tournament import FISHING_EVENTS

EVENTS = {"hidden-objects": HIDDEN_OBJECTS, "castle-battle": CASTLE_BATTLE, **FISHING_EVENTS}

__all__ = ["EVENTS"]
