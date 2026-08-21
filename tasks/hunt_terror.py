"""Task: Terror Hunt (rally on the world map).

A continuous hunt that keeps rallying as long as there is stamina. Instead of
returning to the city after every rally, the bot STAYS ON THE WORLD MAP and
watches the march-queue panel: the moment one of ITS OWN rally slots frees up
(the troops came back) it launches the next hunt on that slot. It only goes back
to the city once stamina runs out, and schedules the next run for when stamina
has recharged.

It is queue-aware: it detects WHICH slot each rally took (e.g. "2/6") and only
ever relaunches on the slots it owns, so the player's other activities
(gathering, ...) that occupy the remaining slots are never disturbed.

Two rally modes (memory/hunt_config.json -> "rally_mode", also asked in the
terminal at start):
  - "hnt"  : a SINGLE rally that loads the saved "HNT" preset (Diana + ratio).
  - "fill" : keep EVERY free march queue busy with rallies. It never loads the
             HNT preset (those heroes are individual and can only be in one
             march); it keeps the heroes the game auto-selects and taps
             "Equalize" so the troops are split evenly and more marches fit.

In "hnt" mode a "require_diana" preference (also asked at start) controls what
happens when Diana is out on a march (the HNT preset then leaves the archer slot
empty and the rally costs the full 25): when ON (default) the hunt WAITS for her
to return instead of deploying without her; when OFF it deploys anyway (cost 25).
Diana's presence is detected by matching her portrait in the rally's hero slots.

  1. Detect where we are and follow the right flow: the hunt can start from the
     TOWER (city / home) or from the WORLD map. On any other screen (a leftover
     modal, the "Quit game?" dialog, ...) it recovers to the city first. It
     NEVER presses 'back' on the world map, because that pops the "Quit game?"
     confirmation and would strand the bot.
  2. Read the governor's stamina from the Intel Mission screen (the "meat"
     counter, top-right). A rally needs 20 stamina with the HNT/Diana preset,
     25 otherwise. Stamina is read from the ACTUAL game value (never estimated),
     since a LOST rally does not consume stamina.
     - If there is not enough stamina, back off: schedule the next attempt far
       enough in the future to accrue ~config.TERROR_RECHARGE_TARGET stamina
       (the game restores +1 every config.STAMINA_MINUTES_PER_POINT minutes).
  3. Resolve the level and mode (file + optional terminal prompt).
  4. Loop while there is stamina: launch on the free slot(s) we may use, note
     which slot each rally took, then poll the queue every
     config.TERROR_RETURN_POLL seconds and relaunch on each owned slot as it
     returns.
  5. Out of stamina: return to Town (city) and schedule the recharge wait.

Templates (captured at the 540x960 ADB resolution):
  - home_bottom_menu.png : the World button (bottom-right on home). Reused.
  - world_search.png     : the magnifier (search) on the left of the world map.
  - terror_icon.png      : the "Terror" tab LABEL (the white text) in the search
                           panel. Matched by text, not by the animated beast
                           icon, so it works wherever the tab row scrolls it.
  - marching_panel.png   : the "Marching" header of the world-map march-queue
                           panel. Used only to tell whether the panel is on
                           screen (i.e. whether any march is out) — absent means
                           every queue is free.
  - search_button.png    : the blue "Search" button.
  - rally_button.png     : the orange "Rally" button on a Terror's card.
  - rally_5min.png       : the "5 min(s)" arrival-time option (detection).
  - rally_confirm.png    : the "Hold a rally" button.
  - formation_hnt.png    : the "HNT" formation preset tab ("hnt" mode).
  - equalize_button.png  : the "Equalize" button on the deploy screen ("fill").
  - deploy_button.png    : the "Deploy" button.
  - world_town.png       : the Town button (bottom-right on the world map).
  - quit_dialog.png      : the "Quit game?" confirmation (world-map back guard).
  - quit_cancel.png      : the orange "Cancel" button on that dialog.
  - intel_mission.png    : the compass icon (bottom-right on the world map) that
                           opens the Intel Mission screen used to read stamina.
  - help_balloon.png     : the alliance "help" handshake balloon (same spot on
                           the world map as on the city); tapped opportunistically
                           between rallies to help the alliance while we wait.

The number of marches currently out is read from the world-map "Marching N/M"
panel on the left. That panel only appears while at least one march is out: when
every queue is home it is ABSENT, which the bot detects via the marching_panel
template and reads as 0 marches (all queues free) — the common "everything idle"
/ "fill all 6 queues" case. When it is present the "N/M" counter is OCR'd
(config MARCH_COUNTER_REGION) — no panel is opened and nothing on the map is
tapped. Stamina is read by OCR of the Intel Mission "meat" counter (config
INTEL_STAMINA_REGION); 'back' closes that screen straight to the world map.
"""
from __future__ import annotations

import json
import re
import select
import sys
import time
from pathlib import Path

import cv2
import pytesseract

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template
import config
import account_prefs


class HuntTerrorTask(Task):
    """Launches Terror rallies back-to-back, staying on the world map, until
    stamina runs out."""

    log_label = "Terror Hunt"

    def execute(self, controller: ADBController) -> str:
        # 1. Figure out WHERE we are and follow the right flow. The hunt can run
        #    from the TOWER (city / home) or from the WORLD map, but if we land
        #    on anything else (a leftover modal, the "Quit game?" dialog, ...) we
        #    recover to the city first so the flow always starts from a known
        #    state. This also protects against the world-map trap where pressing
        #    'back' pops the "Quit game?" dialog and the bot gets lost.
        where = self._current_screen(controller)
        if where == "home":
            print(f"[{self.log_label}] On the TOWER (city); starting from home.")
        elif where == "world":
            print(f"[{self.log_label}] On the WORLD map; starting from there.")
        else:
            print(f"[{self.log_label}] On a '{where}' screen; returning to the city "
                  f"first so the hunt starts from a known state.")
            if not self._go_home(controller):
                return Outcome.FAILED

        # 2. Which level to hunt and which rally mode to use (file + optional
        #    one-off terminal prompt). The mode fixes how much stamina each rally
        #    needs (20 with the HNT/Diana preset, 25 otherwise).
        level, mode = self._resolve_settings()
        required = self._required_stamina(mode)
        print(f"[{self.log_label}] Mode '{mode}', hunting Lv.{level} "
              f"(needs {required} stamina/rally).")

        # 3. Check stamina up front (read from the Intel Mission "meat" counter).
        stamina = self._read_stamina(controller)
        if stamina is None:
            return Outcome.FAILED  # transient OCR/nav issue -> retried/backed off
        if stamina < required:
            self._schedule_recharge(stamina)
            print(f"[{self.log_label}] Stamina {stamina} < {required}; "
                  f"waiting ~{self.interval / 60:.0f} min to recharge.")
            return Outcome.ABSENT

        # 4. Hunt in a loop, staying on the world map, until stamina runs out.
        #    Free slots come from the always-open "Marching N/M" panel on the
        #    world map; stamina comes from the Intel Mission "meat" counter. Both
        #    modes ("hnt" keeps one HNT rally going, "fill" keeps every free queue
        #    busy) share this. We NEVER estimate the stamina cost — a LOST rally
        #    does not consume stamina — so before every launch we read the ACTUAL
        #    stamina (after the previous troops have returned) and only fire when
        #    it is >= the per-mode cost. We only touch the queues WE launched, so
        #    the player's other activities (gathering, ...) are never disturbed.
        tracked: set[int] = set()
        launched_at: dict[int, float] = {}
        hunts = 0
        out_of_stamina = False
        self._diana_busy = False
        while not out_of_stamina:
            # How many march queues are free right now? _idle_slots reads the
            # world-map "Marching N/M" panel; it returns None only when the panel
            # is on screen but the counter could not be read this instant (a
            # transient OCR miss), and an EMPTY set when every queue is busy.
            # When no march is out at all the panel is absent and this reports
            # ALL queues free — the common "everything idle" / "fill all 6" case.
            free = self._idle_slots(controller)
            if free is None:
                # Transient read miss. If nothing of ours is out yet, report a
                # first-attempt failure so main retries after recovering; if a
                # hunt is already flying, just wait and re-read.
                if not tracked and hunts == 0:
                    self._go_town(controller)
                    self.interval = 60.0
                    return Outcome.FAILED
                self._help_alliance_if_balloon(controller)
                time.sleep(config.TERROR_RETURN_POLL)
                continue
            free_slots = sorted(free)
            # In "hnt" mode launch a single rally (only when none is out); in
            # "fill" mode launch on every currently free slot.
            targets = free_slots if mode == "fill" else (
                free_slots[:1] if not tracked else [])

            for _ in targets:
                # Read the ACTUAL stamina right before launching. A single OCR
                # miss must not end the hunt (we skip this pass and retry); only
                # a confirmed low reading stops it.
                stamina = self._read_stamina_retry(controller)
                if stamina is None:
                    break
                if stamina < required:
                    out_of_stamina = True
                    break
                got = self._launch_and_track(controller, level, mode)
                if not got:
                    break
                for slot in got:
                    launched_at[slot] = time.monotonic()
                tracked |= got
                hunts += 1
                print(f"[{self.log_label}] Launched hunt #{hunts} on slot {sorted(got)} "
                      f"(Lv.{level}, mode '{mode}', stamina was {stamina}).")

            if out_of_stamina:
                break

            if self._diana_busy and not tracked:
                # A launch was aborted because Diana is out (require_diana on) and
                # nothing of ours is flying. Go back to the city and re-check after
                # she has had time to return, instead of spinning.
                self._go_town(controller)
                self.interval = config.TERROR_DIANA_WAIT_RETRY
                print(f"[{self.log_label}] Diana is out on a march; waiting "
                      f"~{self.interval / 60:.0f} min for her to return before "
                      "hunting (require_diana on).")
                return Outcome.ABSENT

            if not tracked:
                # Nothing of OURS is out. Either every queue is already busy with
                # the player's other activities (gathering, ...) or a launch
                # could not be confirmed. Neither is a hard failure.
                if hunts == 0:
                    self._go_town(controller)
                    if not free_slots:
                        # No free queue to hunt with right now (all busy
                        # elsewhere). Back off and try again later; don't spin.
                        self.interval = config.TERROR_ALL_BUSY_RETRY
                        print(f"[{self.log_label}] No free march queue right now (all "
                              "queues busy with other activities); retrying in "
                              f"~{self.interval / 60:.0f} min.")
                        return Outcome.ABSENT
                    # There were free queues but the launch didn't register.
                    self.interval = 60.0
                    return Outcome.FAILED
                self._help_alliance_if_balloon(controller)
                time.sleep(config.TERROR_RETURN_POLL)
                continue

            # Wait until at least one of OUR rallies comes home, then loop to
            # relaunch on the freed slot(s). Stamina is re-read at the top of the
            # next pass, AFTER the troops have returned (so a defeat, which does
            # not cost stamina, is reflected correctly).
            returned = self._wait_any_returned(controller, tracked, launched_at)
            tracked -= returned
            level, mode = self._resolve_settings(prompt=False)
            required = self._required_stamina(mode)

        # 5. Out of stamina: go back to the city and wait for it to recharge.
        self._go_town(controller)
        self._schedule_recharge(stamina if stamina is not None else 0)
        print(f"[{self.log_label}] Ran {hunts} hunt(s); stamina low, back to the city. "
              f"Next check in ~{self.interval / 60:.0f} min.")
        return Outcome.SUCCESS

    def _schedule_recharge(self, stamina: int) -> None:
        """Set self.interval to wait long enough to accrue a healthy buffer."""
        deficit = max(config.TERROR_RECHARGE_TARGET - stamina,
                      config.TERROR_MIN_STAMINA)
        self.interval = deficit * config.STAMINA_MINUTES_PER_POINT * 60

    @staticmethod
    def _required_stamina(mode: str) -> int:
        """Stamina a single rally needs in this mode: the HNT/Diana preset costs
        less than the auto-picked heroes used by "fill"."""
        return (config.TERROR_RALLY_COST_HNT if mode == "hnt"
                else config.TERROR_RALLY_COST_FILL)


    # -- hunt flow ---------------------------------------------------------
    def _launch_and_track(self, controller: ADBController, level: int,
                          mode: str) -> set[int]:
        """Launch one rally and return the queue slot(s) it took (the slots that
        went from idle to busy). Empty set if the launch did not complete.

        The "Marching N/M" counter can lag a beat behind the Deploy, so after a
        successful launch we re-read it a few times until it shows the extra
        march — otherwise a real launch could be lost to counter lag and the
        hunt would stop early."""
        before = self._idle_slots(controller) or set()
        if not self._launch_hunt(controller, level, mode):
            return set()
        for _ in range(config.TERROR_COUNTER_SETTLE_TRIES):
            after = self._idle_slots(controller)
            if after is not None:
                got = before - after
                if got:
                    return got  # a slot went busy -> that's our new rally
            time.sleep(config.TERROR_COUNTER_SETTLE_DELAY)
        return set()

    def _launch_hunt(self, controller: ADBController, level: int,
                     mode: str) -> bool:
        """Run the full navigation to deploy one Terror rally. Returns True on
        success, False if any required screen did not appear.

        mode "hnt"  -> loads the saved HNT preset (Diana + ratio) and deploys.
        mode "fill" -> keeps the heroes the game auto-selects, taps "Equalize"
                       to split the troops evenly (so more marches fit) and
                       deploys. It never loads the HNT preset (individual team)."""
        # Open the search panel (magnifier) whether we are on home or the world.
        if not self._open_search(controller):
            return False
        # Select the Terror category (lion).
        if not self._tap(controller, "terror_icon.png", wait=1.5, threshold=0.80):
            return False
        # Set the level on the slider.
        self._set_level(controller, level)
        # Search (the game centers on a Terror and shows its card).
        if not self._tap(controller, "search_button.png", wait=3.0, threshold=0.80):
            return False
        # Rally.
        if not self._tap(controller, "rally_button.png", wait=2.5, threshold=0.80):
            return False
        # Arrival time: 5 minutes, then confirm.
        controller.tap(*config.RALLY_5MIN_TAP)
        time.sleep(0.6)
        if not self._tap(controller, "rally_confirm.png", wait=3.0, threshold=0.80):
            return False

        if mode == "fill":
            # Do NOT load the HNT preset (its heroes are individual and may
            # already be out). Keep the auto-selected heroes and split the troops
            # evenly across marches so more rallies fit.
            self._tap(controller, "equalize_button.png", wait=1.0, threshold=0.85)
        else:
            # Load the pre-saved "HNT" formation. The template is the "HNT" text
            # label itself (the flag icon is identical on every preset), so it is
            # matched wherever the player saved it. If there is no HNT preset on
            # screen we abort instead of deploying the wrong formation.
            if not self._tap(controller, "formation_hnt.png", wait=2.0,
                             threshold=0.80):
                return False
            # Diana gives the -20% stamina discount (cost 20 vs 25), but the HNT
            # preset only loads her when she is free; if she is out on a march the
            # archer slot is empty. When require_diana is on, do NOT deploy
            # without her — cancel and wait for her to return. When off, deploy
            # anyway (cost 25).
            if getattr(self, "_require_diana", True) and \
                    not self._diana_loaded(controller):
                print(f"[{self.log_label}] Diana is out on a march (not in the rally); "
                      "not deploying — waiting for her to return.")
                self._diana_busy = True
                self._go_home(controller)  # cancel the pending rally
                return False
        # Deploy.
        if not self._tap(controller, "deploy_button.png", wait=3.0, threshold=0.80):
            return False
        return True

    def _diana_loaded(self, controller: ADBController) -> bool:
        """True if Diana's portrait is in the rally's hero slots (the HNT preset
        loaded her). When she is out on a march the slot is empty and this is
        False. Only meaningful on the rally formation screen."""
        return find_template(controller.screenshot(),
                             config.TERROR_DIANA_TEMPLATE,
                             config.TERROR_DIANA_THRESHOLD).found


    def _open_search(self, controller: ADBController) -> bool:
        """Open the search panel (magnifier). Works whether we are on the home
        base (open the world first) or already on the world map."""
        # Already on the world map? The magnifier is visible there. Give it a
        # couple of tries, since we may land here right after a Deploy.
        for _ in range(3):
            if find_template(controller.screenshot(), "world_search.png",
                             0.80).found:
                return self._tap(controller, "world_search.png", wait=2.0,
                                 threshold=0.80)
            time.sleep(1.0)
        # On the home base: open the world, then the magnifier.
        if not self._tap(controller, "home_bottom_menu.png", wait=2.5):
            return False
        return self._tap(controller, "world_search.png", wait=2.0, threshold=0.80)

    # -- march queue / troop return ---------------------------------------
    def _wait_any_returned(self, controller: ADBController, tracked: set[int],
                           launched_at: dict[int, float]) -> set[int]:
        """Stay on the world map and poll the marching list until at least one of
        OUR tracked slots is idle again (its troops returned). A rally cannot be
        back before TERROR_RETURN_MIN_WAIT, so a slot is only trusted after that;
        a per-slot TERROR_RETURN_MAX_WAIT cap guarantees progress even if
        detection ever fails. Returns the set of slots that came back."""
        while True:
            self._help_alliance_if_balloon(controller)
            now = time.monotonic()
            idle = self._idle_slots(controller) or set()
            returned: set[int] = set()
            for slot in tracked:
                age = now - launched_at.get(slot, now)
                if age >= config.TERROR_RETURN_MAX_WAIT:
                    returned.add(slot)
                elif age >= config.TERROR_RETURN_MIN_WAIT and slot in idle:
                    returned.add(slot)
            if returned:
                print(f"[{self.log_label}] Slot(s) {sorted(returned)} back; relaunching.")
                return returned
            time.sleep(config.TERROR_RETURN_POLL)

    def _help_alliance_if_balloon(self, controller: ADBController) -> bool:
        """Opportunistically help the alliance while we wait for the troops to
        march, fight and return. The handshake "help" balloon shows up at the
        SAME spot on the world map as on the city screen whenever alliance
        members request help; tapping it helps everyone at once and it then
        disappears (it also vanishes once the help limit is reached — that is
        normal, there is simply nothing to do then).

        If the balloon disappears at the exact instant we tap, the tap can fall
        through to the chat behind it, so afterwards we make sure we are back on
        the world map: a single 'back' closes the chat. We never back-spam on the
        world map (that would pop the "Quit game?" dialog). Returns True if a
        balloon was tapped."""
        if not self._tap(controller, "help_balloon.png", wait=1.5, threshold=0.88):
            return False
        print(f"[{self.log_label}] Helped the alliance (tapped the help balloon).")
        # Usually the balloon just disappears and we are still on the world map.
        # Only if a window clearly opened (the Town button is gone across a few
        # frames — a misclick onto the chat when the balloon vanished under our
        # finger) do we close it. We require several frames so a transient
        # animation never triggers a stray 'back' on the world map, which would
        # pop the "Quit game?" dialog.
        for _ in range(3):
            if find_template(controller.screenshot(), "world_town.png", 0.85).found:
                return True  # still on the world map -> nothing to close
            time.sleep(0.6)
        controller.back()  # a chat/window is open -> close it (single back only)
        time.sleep(1.2)
        if self._current_screen(controller) == "quit":
            self._dismiss_quit_dialog(controller)  # safety: never confirm Quit
        return True

    def _idle_slots(self, controller: ADBController) -> set[int] | None:
        """Return the set of free march-queue slot indices, derived from the
        "Marching N/M" panel on the world map. Returns an EMPTY set when every
        queue is busy, and None when the count could not be read this instant
        (so callers can tell "all busy" apart from "read failed").

        We only know HOW MANY slots are busy (the N of "N/M"), not which physical
        rows they are, so we report the highest-numbered slots as free
        (e.g. 5/6 busy -> {6}; 4/6 -> {5, 6}; 0 -> {1..M}). That is all the
        launch/return tracking needs, since it works on the COUNT changing, not
        on real rows."""
        status = self._read_march_status(controller)
        if status is None:
            return None
        busy, total = status
        return set(range(busy + 1, total + 1))

    def _read_march_status(self, controller: ADBController) -> tuple[int, int] | None:
        """Read the world-map march queues as (busy, total).

        The "Marching N/M" panel is only on screen while at least one march is
        out. When every queue is home the panel is ABSENT — there is no counter
        to OCR — so we report (0, MARCH_MAX_QUEUES): all queues free. This is the
        very common "everything idle" / "fill all 6 queues" starting state, and
        NOT reading it as 0 was why a "fill" hunt could loop forever looking for
        a free queue.

        When the panel IS on screen we OCR the "N/M" counter and return (N, M),
        using the real M as the ceiling (accounts may have fewer than 6 queues
        unlocked). None means the panel is up but the number could not be read
        this instant (transient) — callers retry. Makes sure we are on the world
        map first (the counter only shows there)."""
        if not self._ensure_world(controller):
            return None
        screen = controller.screenshot()
        # No "Marching" header on screen -> no march is out -> every queue free.
        if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                             config.MARCHING_PANEL_THRESHOLD).found:
            return (0, config.MARCH_MAX_QUEUES)
        x1, y1, x2, y2 = config.MARCH_COUNTER_REGION
        crop = screen[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (180, 180, 180), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
        match = re.match(r"(\d+)\s*/\s*(\d+)", txt)
        if not match:
            return None
        busy, total = int(match.group(1)), int(match.group(2))
        total = max(1, min(total, config.MARCH_MAX_QUEUES))
        busy = max(0, min(busy, total))
        return (busy, total)

    def _ensure_world(self, controller: ADBController) -> bool:
        """Make sure the world map is showing (where the marching panel lives).
        From the city, tap the World button; from anywhere else, recover to the
        city first and then open the world. Never presses 'back' on the world
        map (that opens the "Quit game?" dialog)."""
        where = self._current_screen(controller)
        if where == "world":
            return True
        if where != "home" and not self._go_home(controller):
            return False
        return self._tap(controller, "home_bottom_menu.png", wait=2.5)

    def _set_level(self, controller: ADBController, target: int) -> None:
        """Set the Terror level slider to `target` deterministically: drive it to
        the floor with '-', then climb with '+' using OCR of the value box."""
        target = max(config.TERROR_LEVEL_MIN, min(config.TERROR_LEVEL_MAX, target))
        for _ in range(config.TERROR_LEVEL_MAX + 1):  # reach the floor
            controller.tap(*config.TERROR_LEVEL_MINUS)
            time.sleep(0.2)
        for _ in range(config.TERROR_LEVEL_MAX + 1):  # climb to target
            current = self._read_level(controller)
            if current is not None and current >= target:
                break
            controller.tap(*config.TERROR_LEVEL_PLUS)
            time.sleep(0.3)

    def _read_level(self, controller: ADBController) -> int | None:
        """OCR the slider's value box (white digit on a tan pill)."""
        x1, y1, x2, y2 = config.TERROR_LEVEL_BOX
        crop = controller.screenshot()[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (140, 140, 140), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
        return int(txt) if txt.isdigit() else None

    # -- stamina -----------------------------------------------------------
    def _read_stamina_retry(self, controller: ADBController,
                            attempts: int = 3) -> int | None:
        """Read stamina, retrying a few times so a single OCR miss does not abort
        the hunt. Returns None only if every attempt failed."""
        for i in range(attempts):
            value = self._read_stamina(controller)
            if value is not None:
                return value
            if i < attempts - 1:
                time.sleep(1.0)
        return None

    def _read_stamina(self, controller: ADBController) -> int | None:
        """Open the Intel Mission screen (compass on the world map), OCR the
        "meat" stamina counter at the top-right, then go back to the world map.
        Returns the current stamina, or None on failure.

        Reading here (instead of the Governor Profile) keeps the whole flow on
        the world map and reads a big, clean white number. 'back' closes the
        Intel Mission straight to the world map (no "Quit game?" trap)."""
        if not self._ensure_world(controller):
            return None
        opened = self._tap(controller, config.INTEL_MISSION_TEMPLATE,
                            wait=1.5, threshold=0.85)
        if not opened:
            controller.tap(*config.INTEL_MISSION_TAP)
            time.sleep(1.5)
        try:
            screen = controller.screenshot()
            x1, y1, x2, y2 = config.INTEL_STAMINA_REGION
            crop = screen[y1:y2, x1:x2]
            mask = cv2.inRange(crop, (155, 155, 155), (255, 255, 255))
            mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            mask = cv2.bitwise_not(mask)
            txt = pytesseract.image_to_string(
                mask, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
            match = re.match(r"(\d+)", txt)
            return int(match.group(1)) if match else None
        finally:
            controller.back()  # closes Intel Mission -> back to the world map
            time.sleep(1.2)

    # -- settings (file + prompt) ------------------------------------------
    def _resolve_settings(self, prompt: bool = True) -> tuple[int, str]:
        """Return (level, mode). Values come from the hunt-config file and, on
        the first call of a run (prompt=True), an optional terminal prompt. The
        Diana preference is stored on self._require_diana as a side effect."""
        level, mode, require_diana = self._load_settings()
        if prompt:
            level, mode, require_diana = self._maybe_prompt_settings(
                level, mode, require_diana)
        self._require_diana = require_diana
        return level, mode

    def _load_settings(self) -> tuple[int, str, bool]:
        # Prefer this account's own preferences (each account can farm a
        # different Terror level); fall back to the shared file / defaults when
        # the account isn't known yet or has no saved values.
        account_id = account_prefs.current_account_id()
        src = account_prefs.load_prefs(account_id)
        if "terror_level" not in src and "rally_mode" not in src:
            src = self._load_global_settings()
        try:
            level = int(src.get("terror_level", config.TERROR_LEVEL_DEFAULT))
            mode = str(src.get("rally_mode", config.TERROR_RALLY_MODE_DEFAULT))
            require_diana = bool(src.get("require_diana",
                                         config.TERROR_REQUIRE_DIANA_DEFAULT))
        except Exception:
            level, mode = config.TERROR_LEVEL_DEFAULT, config.TERROR_RALLY_MODE_DEFAULT
            require_diana = config.TERROR_REQUIRE_DIANA_DEFAULT
        level = max(config.TERROR_LEVEL_MIN, min(config.TERROR_LEVEL_MAX, level))
        if mode not in config.TERROR_RALLY_MODES:
            mode = config.TERROR_RALLY_MODE_DEFAULT
        return level, mode, require_diana

    def _load_global_settings(self) -> dict:
        """Read the shared (non per-account) hunt-config file. Used as a fallback
        and for migrating accounts that have no saved preferences yet."""
        try:
            return json.loads(Path(config.TERROR_LEVEL_FILE).read_text())
        except Exception:
            return {}

    def _save_settings(self, level: int, mode: str,
                       require_diana: bool) -> None:
        # Save under this account's preferences when we know which account it is;
        # otherwise fall back to the shared file so nothing is lost.
        account_id = account_prefs.current_account_id()
        if account_id:
            account_prefs.update_prefs(
                account_id, {"terror_level": level, "rally_mode": mode,
                             "require_diana": require_diana})
            return
        path = Path(config.TERROR_LEVEL_FILE)
        payload = {
            "description": "Terror Hunt settings. 'terror_level' (3-8) is which "
                           "Terror level to hunt. 'rally_mode' is 'hnt' (one "
                           "rally with the HNT preset) or 'fill' (keep every "
                           "free march queue busy, Equalize, no preset). "
                           "'require_diana' waits for Diana (hnt mode) instead "
                           "of deploying without her. All are re-read before "
                           "every hunt.",
            "terror_level": level,
            "rally_mode": mode,
            "require_diana": require_diana,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _maybe_prompt_settings(self, level: int, mode: str,
                               require_diana: bool) -> tuple[int, str, bool]:
        """Ask the operator for the level, the rally mode and the Diana
        preference, keeping the current values if there is no valid answer within
        the timeout. Only prompts when running in an interactive terminal."""
        if not sys.stdin or not sys.stdin.isatty():
            return level, mode, require_diana
        answer = self._prompt(
            f"[Terror Hunt] Level Lv.{level}. Type {config.TERROR_LEVEL_MIN}-"
            f"{config.TERROR_LEVEL_MAX} to change (or wait to keep): ")
        if answer.isdigit():
            value = int(answer)
            if config.TERROR_LEVEL_MIN <= value <= config.TERROR_LEVEL_MAX:
                level = value
        answer = self._prompt(
            f"[Terror Hunt] Mode '{mode}'. Type 1 = hnt (single HNT rally), "
            f"2 = fill (all free queues, Equalize) (or wait to keep): ")
        if answer == "1":
            mode = "hnt"
        elif answer == "2":
            mode = "fill"
        answer = self._prompt(
            f"[Terror Hunt] Require Diana? currently "
            f"{'yes' if require_diana else 'no'}. Type 1 = yes (wait for her), "
            f"2 = no (hunt without her, cost 25) (or wait to keep): ")
        if answer == "1":
            require_diana = True
        elif answer == "2":
            require_diana = False
        self._save_settings(level, mode, require_diana)
        print(f"[Terror Hunt] Using Lv.{level}, mode '{mode}', "
              f"require_diana={require_diana}.")
        return level, mode, require_diana

    def _prompt(self, message: str) -> str:
        """Print a prompt and return the typed line, or "" if the operator does
        not answer within config.TERROR_LEVEL_PROMPT_TIMEOUT seconds."""
        print(message, end="", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [],
                                    config.TERROR_LEVEL_PROMPT_TIMEOUT)
        if not ready:
            print()
            return ""
        return sys.stdin.readline().strip()

    # -- helpers -----------------------------------------------------------
    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        """Find a template on the current screen and tap its center. Returns
        False if the template file is missing or the image is not on screen."""
        if not (Path(config.TEMPLATES_DIR) / template).exists():
            return False
        match = find_template(controller.screenshot(), template,
                              threshold or self.detect_threshold)
        if not match.found:
            return False
        controller.tap(match.x, match.y)
        time.sleep(wait)
        return True

    def _go_town(self, controller: ADBController) -> bool:
        """Return to the city. Delegates to the world-aware _go_home so it never
        presses 'back' on the world map (which would pop the "Quit game?"
        dialog)."""
        return self._go_home(controller)

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the TOWER (city / home) from wherever we are, safely.

        Routing by screen:
          - home  : done.
          - world : tap the Town button (NEVER 'back' — on the world map 'back'
                    opens the "Quit game?" dialog).
          - quit  : the "Quit game?" dialog is up; tap Cancel (never Confirm).
          - other : a sub-screen/modal (e.g. the rally formation); 'back' is safe
                    here (it returns to the previous screen / cancels the rally).
        """
        for _ in range(self.recover_max_tries + 4):
            where = self._current_screen(controller)
            if where == "home":
                return True
            if where == "quit":
                self._dismiss_quit_dialog(controller)
            elif where == "world":
                self._tap(controller, "world_town.png", wait=2.0, threshold=0.80)
            else:
                controller.back()
                time.sleep(1.2)
        return self._is_on_home_screen(controller)

    def _current_screen(self, controller: ADBController) -> str:
        """Classify the current screen as 'home' (TOWER/city), 'world' (world
        map), 'quit' (the "Quit game?" confirmation) or 'other' (anything else,
        e.g. a modal or the rally formation). The three main screens are mutually
        exclusive: the Town button only shows on the world map and the bottom
        World menu only shows in the city."""
        screen = controller.screenshot()
        if find_template(screen, "quit_dialog.png", 0.80).found:
            return "quit"
        if find_template(screen, "world_town.png", 0.80).found:
            return "world"
        if find_template(screen, self.home_marker, 0.80).found:
            return "home"
        return "other"

    def _dismiss_quit_dialog(self, controller: ADBController) -> bool:
        """Close the "Quit game?" confirmation by tapping Cancel (never Confirm).
        Falls back to a fixed coordinate if the template file is missing."""
        if self._tap(controller, "quit_cancel.png", wait=1.2, threshold=0.85):
            return True
        if find_template(controller.screenshot(), "quit_dialog.png", 0.80).found:
            controller.tap(*config.QUIT_CANCEL_TAP)
            time.sleep(1.2)
            return True
        return False



TASK = HuntTerrorTask(
    name="Hunt Terror",
    detect="home_bottom_menu.png",         # runs from the home screen
    loop=True,                             # keeps hunting each interval
    interval=5.0,                          # first check soon after start
    home_marker="home_bottom_menu.png",
    recover_max_tries=4,
)
