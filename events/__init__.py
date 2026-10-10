"""Events: explicit individual executions, never daily-loop tasks."""
from events.hidden_objects import EVENT as HIDDEN_OBJECTS
from events.castle_battle import EVENT as CASTLE_BATTLE

EVENTS = {"hidden-objects": HIDDEN_OBJECTS, "castle-battle": CASTLE_BATTLE}

__all__ = ["EVENTS"]
