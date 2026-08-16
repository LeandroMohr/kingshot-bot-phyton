"""Task: Intel Missions (the "Intel Mission" panel on the world map).

The Intel Mission panel (opened by the compass on the world map) shows a
mini-map dotted with balloon pins. Each pin is a dispatchable mission of one of
three TYPES, with a RARITY given by the pin's color:

  - LION glyph          -> Monster Hunt  (occupies a march queue, has travel time)
  - CROSSED-SWORDS glyph -> Battle        (instant, no queue)
  - TENT glyph          -> Refugee Rescue (short "Explore", no queue)

Rules (from the player):
  - Do the TYPES in order: every Monster Hunt first, then every Battle, then
    every Refugee Rescue.
  - Within a type, do the HIGHEST rarity first (gold/orange > purple > blue >
    green > white), so the best rewards are secured before resources run out.
  - Only Monster Hunt uses a march queue (max 6, shared with gathering) and has
    ida+volta travel time; when no queue is free, hunts are skipped this pass and
    the queue-less Battles / Refugees are done instead.
  - It runs BEFORE Hunt Terror, because the missions need the stamina/food and
    Hunt Terror is what drains it.
  - NEVER spends gems or real money.

Perception:
  - Pins are at NON-deterministic positions (they refresh every ~5-6h). They are
    found by GRAYSCALE template matching of the white glyph (vision.find_all_gray),
    which is color-independent, so every rarity of a type is found with one
    template. The pin color is then sampled to classify rarity, and a small
    bright-green check badge at the top-right of a pin marks it as already done
    (skipped).

Dispatch (each flow validated live):
  - Monster Hunt: tap pin -> "View" -> world "Attack" (INTEL_ACTION_TAP) ->
                  "Equalize" (trim to the smallest winning army) -> verify the
                  green "likely to prevail" prediction -> "Deploy" -> march sent.
  - Battle:       tap pin -> "View" -> world "Conquer" (INTEL_ACTION_TAP) ->
                  "Fight" (intel_fight) -> wait for the win/lose animation
                  (>= 2s) -> Victory -> tap to exit.
  - Refugee:      tap pin -> "View" -> world "Rescue" (INTEL_ACTION_TAP) -> done.

On entering the panel each pass, "Claim All" is tapped when finished missions are
waiting (their pins can overlap and hide pending missions, which only appear once
the rewards are collected). Some accounts also show an advisor-portrait icon at
the panel's top-left; when present it is tapped to reveal an EXTRA batch of
missions (often more hunts), which are then dispatched under the normal priority.
After dispatching, the balloon gains a green check on the next scan (so it is not
repeated). When there is nothing left to dispatch, "Claim All" collects any
remaining rewards and the bot returns to the city.

Templates (captured at 540x960):
  - intel_mission.png       : the compass on the world map that opens the panel.
  - intel_panel_marker.png  : the "Intel Mission" title (panel-open confirmation).
  - intel_advisor_icon.png  : the top-left advisor portrait (reveals extra
    missions when tapped; absent on accounts without the trait).
  - intel_lion/swords/tent.png : the three balloon glyphs (grayscale-matched).
  - intel_view.png          : the cyan "View" button on a mission preview.
  - deploy_button.png       : the "Deploy" button (reused from Hunt Terror).
  - intel_fight.png         : the green "Fight" button on a battle's squad screen.
  - world_town.png / quit_dialog.png / quit_cancel.png / home_bottom_menu.png :
    reused world/home navigation guards.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from tasks.base import Task, Outcome
from adb_controller import ADBController
from vision import find_template, find_all_gray
import config

# Map mission type -> its balloon-glyph template(s). "hunt" (queue-occupying
# attack missions) covers several target portraits, so it has a LIST of templates.
_GLYPHS = {
    "hunt": list(config.INTEL_GLYPH_HUNT),
    "battle": [config.INTEL_GLYPH_SWORDS],
    "refugee": [config.INTEL_GLYPH_TENT],
}
# Rebel Bounty is handled separately (last, looped), so it is NOT in _GLYPHS.
_BOUNTY_GLYPHS = list(config.INTEL_GLYPH_BOUNTY)


class IntelMissionsTask(Task):
    """Dispatch the Intel Mission balloons in priority order, then claim."""

    def execute(self, controller: ADBController) -> str:
        # Reset to the normal cadence; only a busy-queue run shortens it to 10 min.
        self.interval = config.INTEL_INTERVAL
        # 1. Start from a known state. The panel lives on the world map, so make
        #    sure we can reach it; recover to the city from any stray screen.
        if not self._ensure_world(controller):
            return Outcome.FAILED

        dispatched = 0
        # Hunts whose equalized army was not predicted to win are recorded here so
        # they are not re-picked this run (avoids looping on an unwinnable hunt).
        self._skipped: list[tuple[int, int]] = []
        # Spots already dispatched this run, so a not-yet-rendered done-check does
        # not cause the same pin to be re-planned within the same run.
        self._dispatched_spots: list[tuple[int, int]] = []
        # Marches already out before we dispatch anything (e.g. gathering). The
        # Rebel Bounty waits for the count to return to THIS baseline so only its
        # own battle report is fresh when we read the mail.
        self._baseline_marches = self._read_march_count(controller)
        # Per-spot dispatch-failure counts, to stop retrying a stuck pin.
        fails: dict[tuple[int, int], int] = {}
        # 2. WAVE loop. Each wave opens the panel at most once and dispatches
        #    everything it can start now, in priority order (all affordable hunts
        #    to fill the free march queues, then battles, then refugees) bounded by
        #    free queues and by STAMINA (the meat counter). Reading the free queues
        #    (world map) and the stamina (open panel) happens ONCE per wave — not
        #    per mission — which is what removes the old open/close churn. Each
        #    dispatch drops us on the world map, so the panel is reopened before the
        #    NEXT mission, but nothing is re-scanned/re-claimed/re-counted between
        #    missions of the same wave. Between waves the queues and stamina are
        #    re-read (marches return, stamina regenerates). A wall-clock budget
        #    bounds the total wait.
        deadline = time.time() + config.INTEL_MAX_RUNTIME
        while time.time() < deadline and dispatched < config.INTEL_MAX_DISPATCH:
            # Free march queues, read ONCE on the world map (no panel churn).
            free_q = self._free_queue_count(controller)

            if not self._open_panel(controller):
                return Outcome.FAILED if dispatched == 0 else Outcome.SUCCESS

            # Claim finished missions first (in place — no reopen): their pins may
            # overlap and hide pending missions that only appear once claimed.
            self._claim_if_available(controller)

            # If the advisor icon is present (some accounts), tap it to reveal the
            # extra batch of missions (often more hunts) before scanning, so they
            # are dispatched in this run under the normal type priority.
            self._reveal_advisor_missions(controller)

            # Current stamina (meat counter), read ONCE from the open panel.
            stamina = self._read_stamina(controller)
            missions = self._scan_missions(controller)
            if not missions:
                break  # every mission has been dispatched/claimed — done

            plan = self._plan_wave(missions, free_q, stamina)
            if not plan:
                # Nothing startable right now. Figure out WHY so we retry sensibly.
                budget = stamina if stamina is not None else 0
                hunts_pending = any(m[0] == "hunt" for m in missions)
                can_afford_hunt = budget >= config.INTEL_STAMINA_COST["hunt"]
                # Only blocker is busy queues (hunts remain, stamina is enough, but
                # no free queue) -> don't block the run; retry in 10 min until a
                # queue frees.
                if hunts_pending and can_afford_hunt and free_q <= 0:
                    print("[Intel Missions] All march queues busy; retrying in "
                          "10 min until one frees.")
                    self.interval = config.INTEL_QUEUE_RETRY
                    break
                # Otherwise there is no stamina left for anything startable.
                print("[Intel Missions] Not enough stamina for the remaining "
                      "missions this pass.")
                break

            # Dispatch the whole plan, reopening the panel only BETWEEN missions.
            for i, (kind, x, y, name) in enumerate(plan):
                if i > 0 and not self._open_panel(controller):
                    break
                if self._dispatch(controller, kind, x, y):
                    dispatched += 1
                    self._dispatched_spots.append((x, y))
                    print(f"[Intel Missions] Dispatched a {name} {kind} "
                          f"(#{dispatched}).")
                else:
                    # A dispatch can fail transiently (e.g. a just-sent pin has not
                    # yet shown its done-check). Retry a few times, then give up on
                    # that spot so we don't churn on a stuck pin. Break the wave to
                    # re-scan from a fresh state.
                    key = (x // 15, y // 15)
                    fails[key] = fails.get(key, 0) + 1
                    if fails[key] >= config.INTEL_DISPATCH_MAX_RETRY:
                        self._skipped.append((x, y))
                        print(f"[Intel Missions] Giving up on the {name} {kind} "
                              f"at ({x},{y}) after {fails[key]} tries.")
                    else:
                        print(f"[Intel Missions] Could not dispatch the {name} "
                              f"{kind}; will retry.")
                    self._go_home(controller)
                    self._ensure_world(controller)
                    break

        # 3. Every ordinary mission is dispatched. Now run the Rebel Bounty last:
        #    attack it repeatedly (it gets harder each win) until we lose once or
        #    run out of stamina / queue / time.
        bounties = self._run_bounty_loop(controller, deadline)
        dispatched += bounties

        # 4. Collect the rewards of everything that finished, then head home.
        if self._open_panel(controller):
            self._claim_all(controller)
        self._go_home(controller)

        if dispatched == 0:
            print("[Intel Missions] No missions to dispatch right now.")
            return Outcome.ABSENT
        print(f"[Intel Missions] Ran {dispatched} mission(s); rewards claimed.")
        return Outcome.SUCCESS

    # -- scanning / classification ----------------------------------------
    def _scan_missions(self, controller: ADBController) -> list[tuple]:
        """Return the pending missions on the panel as a list of
        (kind, x, y, rarity_rank, rarity_name). Balloons with a done check are
        left out. The panel must already be open."""
        screen = controller.screenshot()
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        out: list[tuple] = []
        md = config.INTEL_GLYPH_MIN_DISTANCE
        for kind, templates in _GLYPHS.items():
            seen: list[tuple[int, int]] = []
            for template in templates:
                for m in find_all_gray(screen, template,
                                       config.INTEL_GLYPH_THRESHOLD, md):
                    # A balloon can match more than one template of the same kind;
                    # keep only the first hit at a given spot.
                    if any(abs(m.x - px) <= md and abs(m.y - py) <= md
                           for px, py in seen):
                        continue
                    seen.append((m.x, m.y))
                    if self._is_done(hsv, m.x, m.y):
                        continue
                    if any(abs(m.x - sx) <= 20 and abs(m.y - sy) <= 20
                           for sx, sy in getattr(self, "_skipped", [])):
                        continue  # an unwinnable hunt already skipped this run
                    if any(abs(m.x - dx) <= 20 and abs(m.y - dy) <= 20
                           for dx, dy in getattr(self, "_dispatched_spots", [])):
                        continue  # already dispatched this run (check may lag)
                    rank, name = self._rarity(hsv, m.x, m.y)
                    out.append((kind, m.x, m.y, rank, name))
        return out

    def _is_done(self, hsv: np.ndarray, cx: int, cy: int) -> bool:
        """True if the pin at (cx, cy) carries the bright-green done check badge
        at the top-right of its head."""
        dx1, dx2, dy1, dy2 = config.INTEL_CHECK_BOX
        y1, y2 = cy + dy1, cy + dy2
        x1, x2 = cx + dx1, cx + dx2
        h, w = hsv.shape[:2]
        y1, y2 = max(0, y1), max(0, y2)
        x1, x2 = max(0, x1), min(w, x2)
        if y2 <= y1 or x2 <= x1:
            return False
        reg = hsv[y1:y2, x1:x2].reshape(-1, 3)
        lo = config.INTEL_CHECK_HSV_LOW
        hi = config.INTEL_CHECK_HSV_HIGH
        mask = ((reg[:, 0] >= lo[0]) & (reg[:, 0] <= hi[0]) &
                (reg[:, 1] >= lo[1]) & (reg[:, 2] >= lo[2]))
        return int(mask.sum()) >= config.INTEL_CHECK_MIN_PIXELS

    def _rarity(self, hsv: np.ndarray, cx: int, cy: int) -> tuple[int, str]:
        """Classify a pin's rarity from its body color: (rank, name). Lower rank
        = better = dispatched first. A low-saturation pin is treated as white
        (worst)."""
        half = config.INTEL_RARITY_BOX
        h, w = hsv.shape[:2]
        y1, y2 = max(0, cy - half), min(h, cy + half)
        x1, x2 = max(0, cx - half), min(w, cx + half)
        reg = hsv[y1:y2, x1:x2].reshape(-1, 3)
        colored = reg[(reg[:, 1] > config.INTEL_RARITY_MIN_S) &
                      (reg[:, 2] > config.INTEL_RARITY_MIN_V)]
        if len(colored) == 0:
            return config.INTEL_RARITY_WHITE_RANK, "white"
        med_h = int(np.median(colored[:, 0].astype(int)))
        for low, high, rank, name in config.INTEL_RARITY_BANDS:
            if low <= med_h <= high:
                return rank, name
        return config.INTEL_RARITY_WHITE_RANK, "white"

    def _plan_wave(self, missions: list[tuple], free_q: int,
                   stamina: int | None) -> list[tuple]:
        """Plan everything to dispatch THIS wave, in strict priority order and
        bounded by free march queues + stamina. Returns an ordered list of
        (kind, x, y, name).

        Priority of the shared stamina pool: HUNTS FIRST. All pending hunts have
        their stamina reserved before any battle/refugee is planned, so a wave
        never spends the food a still-pending hunt will need — this realises the
        rule "if there is not enough stamina for the battles + rescues in
        parallel, just do every possible hunt and wait for the marches". Within a
        type the best rarity (lowest rank) goes first, tie-broken topmost."""
        cost = config.INTEL_STAMINA_COST
        # Unreadable stamina -> treat as 0 (plan nothing) rather than "plenty", so
        # a mission is never dispatched on an unverified stamina reading.
        budget = stamina if stamina is not None else 0

        by_kind: dict[str, list[tuple]] = {}
        for kind in config.INTEL_TYPE_ORDER:
            cands = [m for m in missions if m[0] == kind]
            cands.sort(key=lambda m: (m[3], m[2], m[1]))  # rarity, then topmost
            by_kind[kind] = cands

        plan: list[tuple] = []
        # Hunts: limited by free queues AND by stamina; they get first claim.
        n_hunt = min(len(by_kind.get("hunt", [])), free_q, budget // cost["hunt"])
        for m in by_kind.get("hunt", [])[:n_hunt]:
            plan.append((m[0], m[1], m[2], m[4]))
        budget -= n_hunt * cost["hunt"]
        # Reserve stamina for the hunts we could NOT start yet (queues full), so a
        # surplus battle/refugee never eats a pending hunt's food.
        remaining_hunts = len(by_kind.get("hunt", [])) - n_hunt
        surplus = max(0, budget - remaining_hunts * cost["hunt"])
        # Battles (instant, no queue) from the surplus.
        n_batt = min(len(by_kind.get("battle", [])), surplus // cost["battle"])
        for m in by_kind.get("battle", [])[:n_batt]:
            plan.append((m[0], m[1], m[2], m[4]))
        surplus -= n_batt * cost["battle"]
        # Refugees last, from whatever surplus remains.
        n_ref = min(len(by_kind.get("refugee", [])), surplus // cost["refugee"])
        for m in by_kind.get("refugee", [])[:n_ref]:
            plan.append((m[0], m[1], m[2], m[4]))
        return plan

    # -- dispatch flows ----------------------------------------------------
    def _dispatch(self, controller: ADBController, kind: str, x: int,
                  y: int) -> bool:
        """Run the dispatch flow for one mission of `kind` at panel (x, y).
        Returns True if it was sent. Shared prefix: tap pin -> View -> action."""
        controller.tap(x, y)
        time.sleep(1.8)
        # Preview dialog: the cyan "View" button (its Y varies per mission).
        if not self._tap(controller, config.INTEL_VIEW_BUTTON, wait=2.0,
                         threshold=0.85):
            return False
        # World-map dialog: Attack / Conquer / Rescue all sit at the same spot.
        controller.tap(*config.INTEL_ACTION_TAP)
        time.sleep(2.2)

        if kind == "hunt":
            # Formation screen. Tap "Equalize" to trim the army to the smallest
            # set the game suggests, then deploy regardless of the win-prediction
            # text (per user request: always send troops).
            if not self._tap(controller, config.INTEL_EQUALIZE_BUTTON, wait=1.5,
                             threshold=0.85):
                controller.tap(*config.INTEL_EQUALIZE_TAP)
                time.sleep(1.5)
            # This occupies a march queue and starts the ida+volta travel;
            # nothing to confirm afterwards.
            return self._tap(controller, config.INTEL_DEPLOY_BUTTON, wait=3.0,
                             threshold=0.80)
        if kind == "bounty":
            # Rebel Bounty: send the DEFAULT (strongest) army — do NOT equalize
            # and do NOT check the win-prediction text; attack regardless (a loss
            # is the intended signal to stop the loop). Before committing, set the
            # troop composition via the Balance dialog, then read the OUTBOUND
            # march time off the Deploy screen so the caller can wait exactly that
            # long (+buffer) before reading the mail once.
            self._apply_bounty_ratio(controller)
            self._bounty_march_seconds = self._read_march_seconds(controller)
            return self._tap(controller, config.INTEL_DEPLOY_BUTTON, wait=3.0,
                             threshold=0.80)
        if kind == "battle":
            # Squad Settings -> Fight -> battle animation -> Victory (tap to exit).
            if not self._tap(controller, config.INTEL_FIGHT_BUTTON, wait=1.5,
                             threshold=0.85):
                return False
            # The win/lose animation plays for a few seconds; wait (>= 2s) for the
            # Victory screen before tapping to dismiss it.
            time.sleep(config.INTEL_BATTLE_ANIM_WAIT)
            controller.tap(*config.INTEL_VICTORY_EXIT_TAP)
            time.sleep(2.0)
            return True
        # refugee: the "Rescue" tap (INTEL_ACTION_TAP above) already started the
        # short Explore; nothing else to do.
        return True

    def _claim_all(self, controller: ADBController) -> None:
        """Tap "Claim All" if any finished mission's rewards are waiting, then
        dismiss the rewards screen. Harmless if there is nothing to claim."""
        controller.tap(*config.INTEL_CLAIM_ALL_TAP)
        time.sleep(1.8)
        # A rewards screen may open ("tap anywhere to exit"); dismiss it.
        controller.tap(*config.INTEL_VICTORY_EXIT_TAP)
        time.sleep(1.2)

    def _claim_if_available(self, controller: ADBController) -> bool:
        """If the green "Claim All" button is showing (finished missions exist,
        possibly hidden behind overlapping pins), claim them so their pins clear
        and any overlapped pending mission becomes visible. Returns True if it
        claimed. The panel must already be open; claiming stays ON the panel
        (dismissing the rewards overlay returns to it), so it is NOT reopened."""
        if not find_template(controller.screenshot(), config.INTEL_CLAIM_BUTTON,
                             config.INTEL_CLAIM_THRESHOLD).found:
            return False
        controller.tap(*config.INTEL_CLAIM_ALL_TAP)
        time.sleep(1.8)
        controller.tap(*config.INTEL_VICTORY_EXIT_TAP)  # dismiss rewards overlay
        time.sleep(1.2)
        return True

    def _reveal_advisor_missions(self, controller: ADBController) -> bool:
        """Some accounts show an advisor-portrait icon at the panel's top-left;
        tapping it reveals an extra batch of missions (often more hunts). Tap it
        when present (it is consumed by the tap); accounts without it just skip.
        Returns True if it was tapped. The panel must already be open."""
        match = find_template(controller.screenshot(), config.INTEL_ADVISOR_ICON,
                              config.INTEL_ADVISOR_THRESHOLD)
        if not match.found:
            return False
        print("[Intel Missions] Advisor icon present; revealing extra missions.")
        controller.tap(match.x, match.y)
        time.sleep(2.0)
        return True

    def _win_predicted(self, controller: ADBController) -> bool:
        """True if the green "you are likely to prevail" prediction is showing on
        the Deploy screen (enough green message pixels in the prediction band)."""
        screen = controller.screenshot()
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        x1, y1, x2, y2 = config.INTEL_WIN_MSG_REGION
        reg = hsv[y1:y2, x1:x2].reshape(-1, 3)
        lo = config.INTEL_WIN_MSG_HSV_LOW
        hi = config.INTEL_WIN_MSG_HSV_HIGH
        mask = ((reg[:, 0] >= lo[0]) & (reg[:, 0] <= hi[0]) &
                (reg[:, 1] >= lo[1]) & (reg[:, 2] >= lo[2]))
        return int(mask.sum()) >= config.INTEL_WIN_MSG_MIN_PIXELS

    # -- panel / queue helpers --------------------------------------------
    def _open_panel(self, controller: ADBController) -> bool:
        """Open the Intel Mission panel (compass on the world map) and confirm it
        is up by its title. Retries a couple of times."""
        for _ in range(3):
            if find_template(controller.screenshot(), config.INTEL_PANEL_MARKER,
                             config.INTEL_PANEL_THRESHOLD).found:
                return True
            if not self._ensure_world(controller):
                return False
            if not self._tap(controller, config.INTEL_MISSION_TEMPLATE, wait=1.8,
                             threshold=0.85):
                controller.tap(*config.INTEL_MISSION_TAP)
                time.sleep(1.8)
        return find_template(controller.screenshot(), config.INTEL_PANEL_MARKER,
                             config.INTEL_PANEL_THRESHOLD).found

    def _has_free_queue(self, controller: ADBController) -> bool:
        """True if at least one march queue is free (for Monster Hunts). Read
        from the world-map "Marching N/M" panel: absent panel = every queue free.
        Reading requires the world map, so we close the Intel panel with 'back'
        first (which returns straight to the world map) and reopen it after.
        Used by the Rebel Bounty loop (the main wave loop uses _free_queue_count,
        which reads the world map before the panel is opened)."""
        controller.back()  # Intel panel -> world map
        time.sleep(1.2)
        screen = controller.screenshot()
        if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                             config.MARCHING_PANEL_THRESHOLD).found:
            free = True  # no march out -> all queues free
        else:
            free = self._read_queue_free(screen)
        # Reopen the panel for the caller to keep scanning.
        self._open_panel(controller)
        return free

    def _free_queue_count(self, controller: ADBController) -> int:
        """Number of FREE march queues, read ONCE on the world map (no panel
        churn). An absent "Marching N/M" panel means every queue is free. When the
        panel IS present but the counter can't be OCR'd (after a few tries) we
        assume ZERO free — never attempt a hunt on an unverified queue."""
        self._ensure_world(controller)
        for _ in range(3):
            screen = controller.screenshot()
            if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                                 config.MARCHING_PANEL_THRESHOLD).found:
                return config.MARCH_MAX_QUEUES
            counts = self._read_queue_counts(screen)
            if counts is not None:
                busy, total = counts
                return max(0, total - busy)
            time.sleep(0.6)
        return 0  # panel present but unreadable -> assume all busy (conservative)

    def _read_queue_counts(self, screen: np.ndarray) -> tuple[int, int] | None:
        """OCR the world-map "N/M" marching counter -> (busy, total), or None on
        an OCR miss (the caller retries / assumes busy)."""
        import re
        import pytesseract
        x1, y1, x2, y2 = config.MARCH_COUNTER_REGION
        mask = cv2.inRange(screen[y1:y2, x1:x2], (180, 180, 180), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
        m = re.match(r"(\d+)\s*/\s*(\d+)", txt)
        if not m:
            return None
        return int(m.group(1)), max(1, int(m.group(2)))

    def _read_stamina(self, controller: ADBController) -> int | None:
        """OCR the panel's top-right meat counter (current stamina). The Intel
        panel must be open. Retries a few times; returns None only if every
        attempt missed (the caller then treats stamina as 0 = do nothing, so we
        never dispatch a mission on an unverified stamina reading)."""
        import re
        import pytesseract
        x1, y1, x2, y2 = config.INTEL_STAMINA_REGION
        lo = config.INTEL_STAMINA_MASK_LO
        for _ in range(3):
            screen = controller.screenshot()
            mask = cv2.inRange(screen[y1:y2, x1:x2], (lo, lo, lo), (255, 255, 255))
            mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            mask = cv2.bitwise_not(mask)
            txt = pytesseract.image_to_string(
                mask, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
            m = re.match(r"(\d+)", txt)
            if m:
                return int(m.group(1))
            time.sleep(0.5)
        return None

    def _wait_for_queue(self, controller: ADBController, deadline: float) -> bool:
        """Block (polling) until a march queue frees up so a remaining Monster
        Hunt can be dispatched. Closes the Intel panel first so the world-map
        marching counter is readable (the next wave reopens the panel). Returns
        True when one is free, False if the wall-clock `deadline` is reached."""
        if find_template(controller.screenshot(), config.INTEL_PANEL_MARKER,
                         config.INTEL_PANEL_THRESHOLD).found:
            controller.back()  # Intel panel -> world map
            time.sleep(1.2)
        while time.time() < deadline:
            if self._free_queue_count(controller) > 0:
                return True
            time.sleep(config.INTEL_QUEUE_WAIT_POLL)
        return self._free_queue_count(controller) > 0

    # -- Rebel Bounty (special, last, looped) -----------------------------
    def _scan_bounties(self, controller: ADBController) -> list[tuple]:
        """Return the pending Rebel Bounty pins as (x, y, rank, name). The panel
        must already be open."""
        screen = controller.screenshot()
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        md = config.INTEL_GLYPH_MIN_DISTANCE
        out: list[tuple] = []
        seen: list[tuple[int, int]] = []
        for template in _BOUNTY_GLYPHS:
            for m in find_all_gray(screen, template,
                                   config.INTEL_GLYPH_THRESHOLD, md):
                if any(abs(m.x - px) <= md and abs(m.y - py) <= md
                       for px, py in seen):
                    continue
                seen.append((m.x, m.y))
                if self._is_done(hsv, m.x, m.y):
                    continue
                rank, name = self._rarity(hsv, m.x, m.y)
                out.append((m.x, m.y, rank, name))
        return out

    def _run_bounty_loop(self, controller: ADBController,
                         deadline: float) -> int:
        """Attack the Rebel Bounty repeatedly (it gets harder each win) until we
        lose once, run out of stamina/queue, or the time budget ends. Returns the
        number of bounty attacks dispatched. A defeat (read from the mail battle
        report) ends the loop and the flow moves on.

        The bounty runs ONLY after every other Intel mission has concluded (its
        march is home) — never in parallel — so the battle report we read is
        unambiguously the bounty's and never another mission's."""
        if not self._wait_intel_marches_home(controller, deadline):
            print("[Intel Missions] Other Intel marches still out; skipping the "
                  "Rebel Bounty this pass to keep the mail check reliable.")
            return 0

        attacks = 0
        while time.time() < deadline and attacks < config.INTEL_MAX_DISPATCH:
            if not self._open_panel(controller):
                break
            self._claim_if_available(controller)
            bounties = self._scan_bounties(controller)
            if not bounties:
                break  # no bounty available
            if not self._has_free_queue(controller):
                if not self._wait_for_queue(controller, deadline):
                    break
                continue
            bounties.sort(key=lambda b: (b[1], b[0]))  # topmost first
            x, y, _rank, name = bounties[0]
            self._bounty_march_seconds = None
            if not self._dispatch(controller, "bounty", x, y):
                print("[Intel Missions] Bounty attack could not be sent "
                      "(no stamina/army?); ending bounty loop.")
                self._go_home(controller)
                self._ensure_world(controller)
                break
            attacks += 1
            march = self._bounty_march_seconds or config.INTEL_BOUNTY_MARCH_FALLBACK
            print(f"[Intel Missions] Rebel Bounty attack #{attacks} sent; "
                  f"march {march}s, waiting {march + config.INTEL_BOUNTY_MAIL_BUFFER}s "
                  "for the report.")
            result = self._resolve_bounty(controller, march, deadline)
            if result == "defeat":
                print("[Intel Missions] Rebel Bounty was a DEFEAT; ending the "
                      "bounty loop.")
                break
            if result is None:
                print("[Intel Missions] Could not read the bounty result; "
                      "ending the bounty loop to be safe.")
                break
            print("[Intel Missions] Rebel Bounty VICTORY; trying the next one.")
        return attacks

    def _resolve_bounty(self, controller: ADBController, march_seconds: int,
                        deadline: float) -> str | None:
        """Wait exactly the outbound march time plus a small buffer (so the battle
        report has landed), then read the mail ONCE. If the report is not up yet,
        do a few short re-reads rather than thrashing the mail. Returns
        'victory', 'defeat', or None."""
        wait = march_seconds + config.INTEL_BOUNTY_MAIL_BUFFER
        end = min(time.time() + wait, deadline)
        while time.time() < end:
            time.sleep(min(2.0, end - time.time()))
        result = self._read_top_report(controller)
        tries = 0
        while result is None and tries < config.INTEL_BOUNTY_RESULT_RETRY:
            if time.time() >= deadline:
                break
            time.sleep(config.INTEL_BOUNTY_MAIL_BUFFER)
            result = self._read_top_report(controller)
            tries += 1
        return result

    def _read_balance_pct(self, controller: ADBController) -> dict[str, int]:
        """OCR the three percentage boxes in the Balance dialog. Returns a dict
        {"inf": n, "cav": n, "arc": n}; a value is -1 if it could not be read."""
        import pytesseract
        img = controller.screenshot()
        x1, x2 = config.INTEL_BALANCE_PCT_REGION_X
        out: dict[str, int] = {}
        for key, y in config.INTEL_BALANCE_ROWS.items():
            g = cv2.cvtColor(img[y - 15:y + 15, x1:x2], cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            _, t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            s = pytesseract.image_to_string(
                t, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
            out[key] = int(s) if s.isdigit() else -1
        return out

    def _apply_bounty_ratio(self, controller: ADBController) -> None:
        """Set the Rebel Bounty troop composition through the Deploy screen's
        "Balance" dialog to config.INTEL_BOUNTY_RATIO. Each +/- tap changes a row
        by 1% and the total is capped at 100%, so every decrease is applied first
        (to free headroom) then every increase. Verifies once and corrects any
        small residual, then confirms."""
        target = config.INTEL_BOUNTY_RATIO
        controller.tap(*config.INTEL_BALANCE_BUTTON_TAP)
        time.sleep(1.5)
        cur = self._read_balance_pct(controller)
        if any(v < 0 for v in cur.values()):
            # OCR failed; abort the ratio change and fall back to the default army.
            print("[Intel Missions] Could not read the Balance dialog; keeping "
                  "the default troop ratio.")
            controller.tap(*config.INTEL_BALANCE_CLOSE_TAP)
            time.sleep(1.0)
            return
        self._nudge_balance(controller, cur, target)
        # Verify and correct a small residual (OCR/tap slippage).
        final = self._read_balance_pct(controller)
        if all(v >= 0 for v in final.values()):
            self._nudge_balance(controller, final, target)
        controller.tap(*config.INTEL_BALANCE_CONFIRM_TAP)
        time.sleep(1.2)

    def _nudge_balance(self, controller: ADBController, cur: dict[str, int],
                       target: dict[str, int]) -> None:
        """Tap the +/- buttons to move `cur` toward `target`. Decreases first so
        the 100% cap never blocks a needed increase."""
        for key in ("inf", "cav", "arc"):
            for _ in range(max(0, cur[key] - target[key])):
                controller.tap(config.INTEL_BALANCE_MINUS_X,
                               config.INTEL_BALANCE_ROWS[key])
                time.sleep(config.INTEL_BALANCE_TAP_DELAY)
        for key in ("inf", "cav", "arc"):
            for _ in range(max(0, target[key] - cur[key])):
                controller.tap(config.INTEL_BALANCE_PLUS_X,
                               config.INTEL_BALANCE_ROWS[key])
                time.sleep(config.INTEL_BALANCE_TAP_DELAY)

    def _read_march_seconds(self, controller: ADBController) -> int | None:
        """OCR the outbound march time ("HH:MM:SS" or "MM:SS") shown on the Deploy
        screen next to the clock icon. Returns the total seconds, or None if it
        could not be read."""
        import re
        import pytesseract
        x1, y1, x2, y2 = config.INTEL_DEPLOY_MARCH_TIME_REGION
        crop = controller.screenshot()[y1:y2, x1:x2]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        _, g = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(
            g, config="--psm 7 -c tessedit_char_whitelist=0123456789:").strip()
        m = re.findall(r"\d+", txt)
        if not m:
            return None
        parts = [int(p) for p in m][-3:]  # keep at most H, M, S
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs if 0 < secs < 6 * 3600 else None

    def _wait_intel_marches_home(self, controller: ADBController,
                                 deadline: float) -> bool:
        """Block until every Intel-mission march dispatched this run has returned
        (the marching count is back to the baseline captured before dispatching),
        so no other battle report can be mistaken for the bounty's. Returns True
        once all are home, False if the budget runs out first."""
        baseline = getattr(self, "_baseline_marches", 0)
        while time.time() < deadline:
            if self._read_march_count(controller) <= baseline:
                return True
            time.sleep(config.INTEL_QUEUE_WAIT_POLL)
        return self._read_march_count(controller) <= baseline

    def _read_march_count(self, controller: ADBController) -> int:
        """Number of marches currently out (N of the world-map "Marching N/M"
        panel); 0 when the panel is absent. Reads on the world map."""
        self._ensure_world(controller)
        screen = controller.screenshot()
        if not find_template(screen, config.MARCHING_PANEL_TEMPLATE,
                             config.MARCHING_PANEL_THRESHOLD).found:
            return 0
        import re
        import pytesseract
        x1, y1, x2, y2 = config.MARCH_COUNTER_REGION
        mask = cv2.inRange(screen[y1:y2, x1:x2], (180, 180, 180), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
        m = re.match(r"(\d+)", txt)
        return int(m.group(1)) if m else 0

    def _read_top_report(self, controller: ADBController) -> str | None:
        """Open Mail -> Reports and, IF the most recent report is unread (a fresh
        result), open it and read the Battle Overview: 'victory' if the golden
        VICTORY banner is present, else 'defeat'. Returns None when there is no
        fresh report yet (battle not resolved). Always closes the mail."""
        self._open_mail_reports(controller)
        if not self._top_report_unread(controller):
            self._close_mail(controller)
            return None
        controller.tap(*config.INTEL_TOP_REPORT_TAP)
        time.sleep(1.8)
        # Some reports open a grouped list instead of a single overview; drill in.
        if not self._overview_present(controller):
            controller.tap(*config.INTEL_REPORT_ROW1_TAP)
            time.sleep(1.8)
        result: str | None = None
        if self._overview_present(controller):
            result = "victory" if self._victory_present(controller) else "defeat"
        self._close_mail(controller)
        return result

    def _open_mail_reports(self, controller: ADBController) -> None:
        """From the world map, open the mail and select the Reports tab."""
        self._ensure_world(controller)
        controller.tap(*config.INTEL_MAIL_TAP)
        time.sleep(2.0)
        controller.tap(*config.INTEL_REPORTS_TAB_TAP)
        time.sleep(1.5)

    def _close_mail(self, controller: ADBController) -> None:
        """Return to the world map from anywhere inside the mail."""
        for _ in range(3):
            if self._current_screen(controller) == "world":
                return
            controller.tap(*config.INTEL_MAIL_CLOSE_TAP)
            time.sleep(1.2)
        self._ensure_world(controller)

    def _top_report_unread(self, controller: ADBController) -> bool:
        """True if the most recent report carries the red 'unread' dot (a fresh
        result we have not yet opened)."""
        screen = controller.screenshot()
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        x1, y1, x2, y2 = config.INTEL_REPORT_UNREAD_REGION
        reg = hsv[y1:y2, x1:x2].reshape(-1, 3)
        red = (((reg[:, 0] <= 10) | (reg[:, 0] >= 170)) &
               (reg[:, 1] > 120) & (reg[:, 2] > 120))
        return int(red.sum()) >= config.INTEL_REPORT_UNREAD_MIN_PIXELS

    def _overview_present(self, controller: ADBController) -> bool:
        """True if the 'Battle Overview' title is on screen."""
        return find_template(controller.screenshot(),
                             config.INTEL_REPORT_OVERVIEW_MARKER,
                             config.INTEL_REPORT_MARKER_THRESHOLD).found

    def _victory_present(self, controller: ADBController) -> bool:
        """True if the golden 'VICTORY!' banner is on the Battle Overview."""
        return find_template(controller.screenshot(),
                             config.INTEL_REPORT_VICTORY_MARKER,
                             config.INTEL_REPORT_MARKER_THRESHOLD).found

    def _read_queue_free(self, screen: np.ndarray) -> bool:
        """OCR the "N/M" marching counter; True if N < M (a queue is free). On an
        OCR miss, assume free (better to attempt a hunt than to stall)."""
        import re
        import pytesseract
        x1, y1, x2, y2 = config.MARCH_COUNTER_REGION
        crop = screen[y1:y2, x1:x2]
        mask = cv2.inRange(crop, (180, 180, 180), (255, 255, 255))
        mask = cv2.resize(mask, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        mask = cv2.bitwise_not(mask)
        txt = pytesseract.image_to_string(
            mask, config="--psm 7 -c tessedit_char_whitelist=0123456789/").strip()
        m = re.match(r"(\d+)\s*/\s*(\d+)", txt)
        if not m:
            return True
        busy, total = int(m.group(1)), max(1, int(m.group(2)))
        return busy < total

    # -- navigation (reused patterns from Hunt Terror) --------------------
    def _ensure_world(self, controller: ADBController) -> bool:
        """Make sure the world map is showing. From the city, tap World; from any
        stray screen, recover to the city first. Never 'back' on the world map."""
        where = self._current_screen(controller)
        if where == "world":
            return True
        if where != "home" and not self._go_home(controller):
            return False
        return self._tap(controller, "home_bottom_menu.png", wait=2.5)

    def _go_home(self, controller: ADBController) -> bool:
        """Return to the city safely, routing by screen (never 'back' on the
        world map, never confirm "Quit game?")."""
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
        """Classify the current screen: 'home' | 'world' | 'quit' | 'other'."""
        screen = controller.screenshot()
        if find_template(screen, "quit_dialog.png", 0.80).found:
            return "quit"
        if find_template(screen, "world_town.png", 0.80).found:
            return "world"
        if find_template(screen, self.home_marker, 0.80).found:
            return "home"
        return "other"

    def _dismiss_quit_dialog(self, controller: ADBController) -> bool:
        """Close "Quit game?" by tapping Cancel (never Confirm)."""
        if self._tap(controller, "quit_cancel.png", wait=1.2, threshold=0.85):
            return True
        if find_template(controller.screenshot(), "quit_dialog.png", 0.80).found:
            controller.tap(*config.QUIT_CANCEL_TAP)
            time.sleep(1.2)
            return True
        return False

    def _tap(self, controller: ADBController, template: str, wait: float = 1.0,
             threshold: float | None = None) -> bool:
        """Find a template and tap its center. False if missing / not on screen."""
        if not (Path(config.TEMPLATES_DIR) / template).exists():
            return False
        match = find_template(controller.screenshot(), template,
                              threshold or self.detect_threshold)
        if not match.found:
            return False
        controller.tap(match.x, match.y)
        time.sleep(wait)
        return True


TASK = IntelMissionsTask(
    name="Intel Missions",
    detect="home_bottom_menu.png",         # runs from the home screen
    loop=True,
    interval=config.INTEL_INTERVAL,
    home_marker="home_bottom_menu.png",
    recover_max_tries=4,
)
