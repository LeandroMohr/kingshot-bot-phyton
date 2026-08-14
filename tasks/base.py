"""Base task structures (Task and Step).

Default behavior: each task runs ONCE (as soon as the condition is available).
To keep a task repeating in a loop, set `loop=True` and adjust `interval`
(seconds between repetitions).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from adb_controller import ADBController
from vision import find_template
import config


# Possible outcomes of a task execution (for terminal feedback).
class Outcome:
    SUCCESS = "completed successfully"
    ABSENT = "nothing to do right now"
    FAILED = "could not complete (will try again)"
    RECOVERED = "tapped by mistake, already back in the city"


@dataclass
class Step:
    """A step: look for a template and tap it.

    - threshold: minimum confidence (0..1) to consider it found.
    - wait_after: seconds to wait after the tap.
    - optional: if True, the task does not fail when the template is not found.
    """
    template: str
    threshold: float = config.DEFAULT_THRESHOLD
    wait_after: float = 1.0
    optional: bool = False


@dataclass
class Task:
    """An automated task.

    Main fields:
    - detect: template that signals the task is AVAILABLE on screen.
    - steps: steps (taps) run when available.
    - loop: if False (default) the task runs ONLY once. Set to True only if
            you want it to keep repeating.
    - interval: seconds between checks. While the task has not run, it is the
            spacing between attempts; with loop=True, it is the time between
            each repetition.
    - home_marker: template proving we are on the home screen (bottom menu).
            If set, after running the steps the task checks it is still on the
            home screen; if a tap opened a window by mistake (misclick), it
            closes it with the back key. It only acts right after its own tap
            — it never closes windows you opened yourself.
    - recover_max_tries: how many times it presses 'back' to return to the
            home screen during a recovery.
    """
    name: str
    detect: str
    steps: list[Step] = field(default_factory=list)
    detect_threshold: float = config.DEFAULT_THRESHOLD
    loop: bool = False           # default: runs only once
    interval: float = 30.0       # seconds between checks/repetitions
    home_marker: str | None = None
    recover_max_tries: int = 3

    _last_check: float = field(default=0.0, repr=False)
    _done: bool = field(default=False, repr=False)

    # -- scheduling --------------------------------------------------------
    def due(self, now: float) -> bool:
        """True if the task should be evaluated now."""
        if self._done:
            return False
        return (now - self._last_check) >= self.interval

    def mark_checked(self, now: float) -> None:
        self._last_check = now

    def mark_done(self) -> None:
        """End single-run tasks (loop=False)."""
        if not self.loop:
            self._done = True

    # -- detection / execution ---------------------------------------------
    def is_available(self, controller: ADBController) -> bool:
        screen = controller.screenshot()
        return find_template(screen, self.detect, self.detect_threshold).found

    def _is_on_home_screen(self, controller: ADBController) -> bool:
        """True if the home screen (bottom menu) is visible."""
        screen = controller.screenshot()
        return find_template(screen, self.home_marker, self.detect_threshold).found

    def _recover_home(self, controller: ADBController) -> bool:
        """Try to return to the home screen by pressing 'back'. True if it worked."""
        for _ in range(self.recover_max_tries):
            controller.back()
            time.sleep(1.0)
            if self._is_on_home_screen(controller):
                return True
        return False

    def run(self, controller: ADBController) -> bool:
        """Run the steps. Returns True if it completed; False if a required step
        was not found (e.g. the request vanished when tapped)."""
        for step in self.steps:
            screen = controller.screenshot()
            match = find_template(screen, step.template, step.threshold)
            if not match.found:
                if step.optional:
                    continue
                return False
            controller.tap(match.x, match.y)
            time.sleep(step.wait_after)
        return True

    def execute(self, controller: ADBController) -> str:
        """Evaluate and run the task, returning an Outcome for the feedback."""
        if not self.is_available(controller):
            return Outcome.ABSENT
        if not self.run(controller):
            return Outcome.FAILED
        # Misclick check: if a tap opened a window by mistake, recover.
        if self.home_marker and not self._is_on_home_screen(controller):
            return Outcome.RECOVERED if self._recover_home(controller) else Outcome.FAILED
        return Outcome.SUCCESS
