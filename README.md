# Kingshot Bot (BlueStacks + ADB)

Automates Kingshot tasks by reading the emulator screen and tapping via ADB.
Screenshots are taken **in memory** — the bot never leaves a history of
screenshots on disk. Only the reference templates (button crops) are saved.

## How it works

1. Captures the emulator screen via ADB (in memory).
2. Looks for each mapped task using *template matching* (OpenCV).
3. If the task is available → taps and runs its steps. If not → skips it.
4. Repeats in a loop.

## Prerequisites (macOS)

### 1. Install ADB
```bash
brew install android-platform-tools
```
Confirm:
```bash
adb version
```

### 2. Enable ADB in BlueStacks
In BlueStacks: **Settings → Advanced → Android Debug Bridge (ADB)** and enable it.
Note the port shown (usually `127.0.0.1:5555`).

### 3. Connect and find the port
```bash
adb connect 127.0.0.1:5555
adb devices
```
If the device shows up with status `device`, you are ready.
If the port is different, adjust `ADB_PORT` in `config.py`.

## Project setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Create the templates

1. Leave the emulator on the desired game screen.
2. Run:
   ```bash
   python capture.py
   ```
3. Open `screen.png`, crop the buttons and save the PNGs into `templates/`
   with the names listed in `templates/README.md`.

## Run the bot

```bash
python main.py
```
Stop with `Ctrl+C`.

## Control panel (macOS / Windows / Linux)

```bash
python app.py            # opens the panel in its own window (pywebview)
python app.py --browser  # opens it in the default browser instead
```
From the panel you can find emulators, start/stop one bot per emulator and
follow each bot's log. The side menu (Resources, Hunt, Alliance, Troops,
Daily) turns each task on/off and edits its options PER ACCOUNT (gather levels
per resource, Beast/Terror level, Diana requirement, VIP target, training
tier...), with a "Como fazer" guide on every task. Changes apply while the bot
runs. The Conta / Tropas / Eventos / Coleta pages also hold the account's
planning sheet (heroes & gear, troop stock and training plan, team distribution
per event, resource stock), saved in `memory/planning/<account_id>.json`
(not versioned; one backup per day in `memory/planning/backups/`). The language
selector next to the panel name switches between English (default) and
Portuguese (BR). Closing the panel stops the
bots it started. Each bot still runs as its own `main.py` process, so the
terminal flow below keeps working (`python main.py --port 5605 --task "Hunt Beasts"`).

On Linux, pywebview needs a GUI backend (`pip install pywebview[qt]` or GTK);
without it, use `--browser`.

## Events (individual only)

Recurring and seasonal events live in `events/`, separate from daily tasks.
Menu option **3 — Events** offers **Sorte de Quem Procura** and **Castle Battle**.
Neither is included in "All mapped tasks", unattended startup, or the daily loop.
`--event` and the repeatable daily-task selector `--task` are mutually exclusive.
Both execution modes preserve `--control-stdin` pause/resume support.

### Fishing Tournament (experimental inspection)

The standalone fishing scripts are not registered in the daily loop or event
menu. Only explicit trial commands launch a free Trial Stage; they never launch
regular fishing, buy equipment, or select special items.

The reference catalog in `knowledge/fishing_catalog.json` contains 230 entries
from https://kingshotmastery.com/tools/fishing-handbook: 150 catches, 60
memorabilia, 10 mermaids and 10 ocean chests. It preserves source image URLs,
minimum depth, points, sell value and seasons. Unknown special-entry points stay
null; sell value is not substituted for tournament points.

The five event tabs are mapped at the native ADB resolution of 540x960:

| Tab | CLI ID | Bar Alignment | Tap (x, y) |
| --- | --- | --- | --- |
| Fishing Tournament | `fishing` | Left edge | (102, 105) |
| Fishing Guild | `guild` | Left edge | (254, 105) |
| Master Fisher Leaderboard | `leaderboard` | Left edge | (405, 105) |
| Fishing Pro Set | `pro-set` | Right edge | (286, 105) |
| Guide | `handbook` | Right edge | (438, 105) |

The selected tab hides its name. Navigation confirms its two white side borders
instead of reading the missing label. To reveal Guide, drag the tab bar left
from (450, 130) to (90, 130) over 700ms. The reverse drag restores the left edge.
Coordinates are only used after alignment and a fresh frame; dragging through
the icons at y=105 was unreliable, while the lower strip at y=130 was validated.
All five transitions were tested on emulator 5555 without starting a cast,
claiming rewards or buying anything. Open the event without a modal first.

```bash
.venv/bin/python -m events.fishing_tournament --port 5555 --tab handbook
.venv/bin/python -m events.fishing_tournament --port 5555 --tab fishing
```

Start and reset were mapped in the free Trial Stage on emulator 5555:

| Action | Confirmed Screen | Tap (x, y) |
| --- | --- | --- |
| Open Rules | Fishing Tournament tab | (496, 172) |
| Start Trial Stages | Rules and Trial Stages labels | (270, 835) |
| Pause | Active fishing HUD and pause icon | (510, 26) |
| Retreat | Both Retreat and Continue labels | (192, 480) |

Start runs the 3-2-1 countdown. The script does not act during it and confirms
moving depth in the trial HUD (10-catch capacity, 100m maximum). The full entry
transition took about 4.6 seconds in the live test, including the countdown.
Reset confirms Pause before tapping Retreat, then verifies the fishing menu.
If the round is already paused, it skips the Pause tap. It never automatically
starts another round. Pending score and catches are discarded by Retreat.

```bash
.venv/bin/python -m events.fishing_tournament --port 5555 --trial-action start
.venv/bin/python -m events.fishing_tournament --port 5555 --trial-action reset
.venv/bin/python -m events.fishing_tournament --port 5555 --trial-action cycle
```

`start` requires the fishing tab or the already-open Rules modal. `reset` only
accepts a confirmed active or paused fishing round. `cycle` starts the free
trial, waits for active fishing, and immediately resets it. Trial commands are
mutually exclusive with tab navigation and handbook scanning. Reports are saved
to `memory/fishing_trial_5555.json` (or `--output`). The live trial cycles returned
with 880 points and 10/10 regular baits unchanged. Refunds of entry keys and
special items in regular/paid modes were not tested by these free-trial cycles.

Monitor the emulator with one bounded latest-frame capture worker:

```bash
.venv/bin/python -m events.fishing_tournament --port 5555 --duration 60
```

For collection scanning, manually open a specimen detail card, then run:

```bash
.venv/bin/python -m events.fishing_tournament --port 5555 --scan-handbook --season autumn --max-cards 96
```

Scanning only taps the card's right arrow and stops on an unrecognized card or
repeated ID. It uses calibrated 540x960 card layouts, title OCR, green checks,
gray stars and silhouettes. Ambiguous states remain unknown. Select each of the
four tabs and open a card before scanning that category. Fish classification
was validated against the live Autumn counter (65 captured, 31 missing);
collection-state recognition for the other categories is not yet validated.
Default collection storage is device-scoped in
`memory/fishing_collection_5555.json`. When switching accounts, use a separate
`--output` and an explicitly verified account ID in `--scope`.

Generate a season-aware collection report:

```bash
.venv/bin/python -m events.fishing_catalog --collection memory/fishing_collection_5555.json --season autumn --max-depth 250 --output memory/fishing_plan_5555.json
```

There is no season calendar or predicted next season. Supply the season shown
when each event starts; no default season is assumed. The report keeps all
entries, including unavailable ones, with `available_seasons`, `event_season`,
`available_now`, `awaiting_seasons`, `capture_status` and `eligible_now`.
An uncaught Summer-only specimen stays missing during Winter but is not an
eligible target. Recompute the report when the next event announces its season.
Use `--current-season-only` to exclude unavailable entries from that report.

Missing and unknown specimens can be highlighted with an experimental native
macOS overlay. Its editable selection is
`memory/fishing_highlight_targets_5555.json`:

```bash
.venv/bin/python -m events.fishing_overlay --port 5555 --brighten
```

At startup, the list is rebuilt from `memory/fishing_collection_5555.json`.
Only entries not confirmed as captured are included, across all categories,
seasons, and depths. Set `enabled` to `false` to disable a candidate; that choice
is preserved on refresh. Red markers indicate confirmed missing entries;
amber markers and a question mark indicate unknown collection states.

Detection does not confirm capture and does not update the collection. After
an entry is verified as captured and its collection record has `captured: true`,
it is removed on the next startup or explicit list refresh:

```bash
.venv/bin/python -m events.fishing_overlay --port 5555 --update-targets
```

An already running overlay does not reload its selection; restart it after
updates. Once every entry is confirmed captured, the selection is empty and
the brightness layer can still run without highlighting captured specimens.
Stop a running process with `kill -TERM PID`, using the PID reported by
`pgrep -fl 'events.fishing_overlay'`; verify it stopped before restarting.

Add `--brighten` to compensate for recoverable darkness directly above the
emulator. A per-pixel translucent layer lifts shadow brightness, preserves the
HUD and already bright areas, and still ignores mouse input. Detection and
tracking use the enhanced frame. Fully black pixels contain no recoverable
detail and remain black: this does not remove the event's visibility mask.
The correction follows fresh ADB frames, so it can lag behind moving objects;
it hides with stale capture and outside active fishing like the markers.

This draws red circles above the BlueStacks game window, not into the game or
onto a separate video mirror. The transparent window ignores mouse events, so
the player can keep steering the hook. It never sends ADB game input. Markers
are updated from continuous capture, with optical-flow tracking between
detections and short motion prediction for drawing. Multiple instances and both
fish orientations are supported. Tracks remain while their boxes intersect the
frame and are cleared outside active fishing; temporary detector misses are
handled by tracking. Heavy occlusion and fish captures can still confuse this
experimental tracker, so disappearance and identity are not guaranteed in all
conditions.

Catalog mode isolates reference artwork with OpenCV GrabCut and uses SIFT
features with geometric verification. All 128 current candidate references
loaded successfully, but gameplay recognition is not yet validated. Similar
artwork, small specimens, darkness, and occlusion may prevent identification or
produce incorrect matches. This mode is not calibrated for gameplay.

The separate native ADB mode remains available explicitly with `--fish Blowfish`
and uses `templates/fishing_blowfish.png`. Its color gate is tuned for Blowfish;
only this native reference has been validated in live gameplay. It is never
restored as a fallback when the pending list becomes empty.

Keep BlueStacks in the foreground. The overlay follows its window position and
size, hides when another application is active, and hides stale captures after
0.5 seconds. If multiple emulator windows exist, choose `--window-id`. The
default viewport insets are `(0, 30, 32, 0)` in macOS points; override them with
`--insets LEFT TOP RIGHT BOTTOM` if emulator chrome differs. ADB frame pixels
are fitted into that viewport, including letterboxing. Native rendering runs at
30Hz, while fresh ADB captures target 10 FPS; this is not zero-latency tracking.

Stop with Ctrl+C. For a bounded test use `--duration 20`; `--snapshot PATH` writes
one transparent overlay-only PNG once at least two fish are tracked or the
brightness layer is active. Reports
default to `memory/fishing_highlight_5555.json`. On the live 5555 test, the
overlay tracked up to five simultaneous Blowfish with about 29ms processing per
frame and a maximum sampled frame age of 275ms. Transparency, click-through
configuration and native circle rendering were verified. Desktop screen capture
was not authorized by macOS, so pixel alignment over the actual desktop remains
a visual check by the player.

Head targeting and autonomous descent are not implemented. A successful
handbook scan or overlay test does not prove reliable real-time steering or
identical layouts after Retreat.

### Sorte de Quem Procura

Open the event on the emulator, then run:

```bash
.venv/bin/python main.py --port 5555 --event hidden-objects
```

This runs one round and exits, preserving the prepared screen (no city/profile
navigation or automatic retries). From the pre-event page it starts the free
**Nível de Prática**. From the live event page, an explicit individual execution
recognizes the **Start** / **Start Game** button by image and starts one stage (entry may consume
event currency). Start takes priority over practice. It waits for the entry page
to disappear, so that page's event countdown cannot be mistaken for the round
timer. It never retries entry, buys hints, or starts the next stage.
Live stages also display a **Tap anywhere to start** introduction absent from
practice. A language-independent stopwatch-card marker recognizes it; one tap
at `(270, 810)`, outside the landscape and hint, dismisses it. Repeated frames
never cause repeated taps. The event can also be launched from that already-open
introduction without paying entry again, and still waits for the real round
before using coordinates. Result screens are never dismissed.
Entry allows up to 20 seconds for loading and waits for a readable timer, not just
the clock icon: live stages can display an empty landscape/timer while loading.
It also waits for a recognized landscape before starting the solver: the live
timer can become readable while the scene is still rendering. No coordinates
are used during that intermediate state.

The mapped forest and live-event village scenes use **540x960** captures. Names (including two-line
labels) are read with Tesseract, matched to coordinates, and each click must
increase the yellow progress bar and cross out/replace the target label.
The number of objects is **level-dependent**, not fixed at nine. The bot keeps
processing requested groups until the explicit success or failure screen appears;
a full progress bar or nine confirmed clicks never implies success. The success
icon is language-independent; failure accepts the Portuguese/English timeout
screens. Other resolutions/landscapes are rejected rather than reusing unsafe
coordinates.

The visible timer supplies the action budget (training currently uses 60 seconds;
longer displayed timers are accepted). After it expires, the bot sends no further
taps but observes for up to five extra seconds for the result animation. If no
recognizable result arrives, it logs an explicit failure instead of hanging or
assuming success. Result screens are left untouched; no next stage is started.

Initial mappings live in `knowledge/hidden_objects.json`. Confirmed new
coordinates and pending unknown names persist in `memory/hidden_objects.json`,
keyed by scene and resolution. Targets are attempted left-to-right. For an
unknown name, the bot uses proposals extracted from the current landscape image,
so a missing coordinate database does not disable exploratory clicks. With a
configured clean background, only pixel-difference proposals are explored;
otherwise saved candidate locations and contrast proposals are interleaved.
It tries locations inside the landscape,
excluding known locations of other requested/found objects. It verifies each
hit before learning, never tapping the magnifying glass or buying hints.
If a candidate unexpectedly finds another requested object, it records the
actual crossed-out name, not the intended one. Unresolved names remain pending;
candidate exhaustion or the remaining round timer stops exploratory clicks, but
observation continues until a result screen or the bounded observation deadline.
Additional landscapes/resolutions need mapping before execution.

#### Manual assistance and previously missed locations

You can click a requested object manually while the bot runs. Changes in the
progress bar and crossed/replaced labels are reconciled before continuing with
the remaining names, including manual progress during OCR or after candidates
are exhausted. A skipped unknown name stays pending for a later round; the bot
tries other remaining names and resumes when manual input unlocks a new group.
The result-screen and timer safeguards still apply.

The bot does **not** receive coordinates of mouse/touch input. A successful guess
requires one localized scene change at the bot's click as well as the matching
label/progress change. Progress elsewhere, multiple changed objects, or a result
overlay alone cannot teach the last guessed position. Ambiguous hits are treated
as external progress and do not overwrite mappings. Simultaneous input at the
same object cannot be distinguished reliably from images alone.

Verified wrong guesses persist under `misses` in the learned scene/resolution
bucket, keyed by canonical PT/EN object name. Future exploratory clicks skip a
small **8-pixel radius** around each missed point, including image proposals.
This is item-specific: a miss for Heart does not exclude that point for Compass.
Only a complete 2.5-second confirmation window with unchanged active labels and
progress can create a miss; terminal/cooldown overlays and manual progress cannot.
Confirmed coordinates take priority and clear that item's miss history. Like
the positive map, exclusions assume fixed item locations within a mapped scene.

Tesseract must be installed (`brew install tesseract` on macOS); the game's
mapped object labels accept Portuguese and English aliases, including common
variants such as `Pinecone` / `Pine Cone`, `Clay Jar` / `Clay Pot`, and
`Cup of Water` / `Water Cup`. Both languages share the same confirmed coordinates
and Portuguese canonical names in memory, without duplicate mappings.
The practice entry also has an image-only marker independent of button text.
Timeout detection accepts both "Acabou o Tempo" and "Time's Up". Newly mapped
items also receive English aliases (for example `Patch` / `Remendo` and
`Brush` / `Pincel`); English OCR variants are resolved before exploring locations.

#### Continuous screen observation

During a Hidden Objects round, one local worker captures ADB frames continuously,
with a ceiling of 10 FPS (actual speed depends on the emulator). Only the latest
frame is retained in memory; there is no video file, screenshot history, frame
backlog, or remote AI/API processing. Other events and daily tasks keep their
existing capture behavior.

A second local worker analyzes those frames while capture, OCR and click
confirmation run. For the forest, OpenCV compares the landscape against
`templates/hidden_objects_forest_background.png`: an exact **450x735** BGR crop
of emulator region `[45, 60, 495, 795]` at **540x960** resolution. The reference
was captured with eight practice objects removed; the remaining heart's cloud
patch was taken from an exactly aligned real frame where that item was absent.
No generated/inpainted scenery is used.

Pixel changes greater than 12 in any color channel are grouped into connected
regions (at least six pixels), with interior click candidates ranked by change
strength. Requested names still come from OCR and hits still require game
confirmation: subtraction locates changes, not their names. Touching objects
may form one region and separate after a hit. Decorations/animations or a
changed landscape can also produce differences; the reference must match the
actual layout. Edit the PNG without resizing, shifting, or changing unchanged
scenery. Missing, corrupt, or incorrectly sized configured backgrounds raise an
explicit error, not a silent fallback.

Scenes without the optional `background` field retain multi-scale color
contrast, closed contours and contrast peaks. Only the newest scored
candidate list is retained; points outside the landscape (including hints)
are excluded. Analysis failures are surfaced and both workers are joined on exit.
This is class-agnostic visual search, **not semantic recognition of the requested
name**: changing scenery can also receive high scores, and items can be missed.
No backup coordinates, pretrained detector or remote service are needed.

The live chapter-1 village uses `hidden_objects_village_background.png`, captured
at native size **before the targets were rendered** in stage 1-3. Two manually
completed rounds confirmed the fixed scenery and successful terminal detection.
The cat was already present in that initial scene and is retained. A ball, rope
and wall ivy appeared afterward and remained in both final captures, although
none appeared in the recorded stage-1-3 target list. The early frame supplies
real pixels behind all three; no inpainting is needed. They can still produce
difference candidates, and those observations do not prove they can never be
requested in another stage.

Village coordinates/misses are scoped independently as `village:540x960`; the
30 training-forest coordinates are **not reused in the village**. Village now
has 12 confirmed reference coordinates from the untimed practice mode after a
stage-1-5 defeat: Pouch, Bell, Map, Starfish, Sunflower, Corn, Rubber Duck,
Watering Can, Barrel, Balloons, Scarf and Camera. All twelve were individually
verified by label strike-through, increasing progress and a localized change
at the click before saving. The blue object on the right tree is Scarf, not
Butterfly. New objects still require confirmed discovery. Observed new names
include Map, Rubber Duck, Balloons, Starfish, Corn, Camera and Butterfly, with
Portuguese canonical aliases. Autonomous village completion has not yet been
validated. A cold-start stage-1-5 run reached timeout after 19 exploratory taps,
learning Bell and Rubber Duck while other progress was reconciled without false
attribution. Practice mapping used visually identified candidates and confirmed
all 12 with 12 correct taps; that is not an autonomous cold-start measurement.
A subsequent mapped stage-1-5 validation reached **All items found** in
32.22 seconds of solver time (35.66 seconds including entry), with 16 scene
taps, one paid entry, one intro dismissal and no hint/result/next-stage taps.
Seven hits were uniquely attributed to the bot; other progress was reconciled
without learning ambiguous coordinates, so this does not establish 12 autonomous
hits. Butterfly and Feather remained pending, and OCR read Balloons as
`Ballecns`, causing unnecessary exploratory clicks despite its known coordinate.

Each frame carries a sequence number and capture start/end timestamps. After a
tap, confirmation accepts only frames whose capture **started after the tap
completed**, excluding stale/in-flight frames. Capture commands have a 2-second
timeout; failures are surfaced, and the worker is joined on completion, timeout,
error, or operator interruption.

Names are OCR'd once per group, then cached, including a final group with only
one or two names. Click confirmation uses an increase in yellow progress pixels
and crossed-out/replaced labels, independent of the number of progress blocks.
New groups are detected from stable, active label pixels in successive frames
instead of fixed sleeps. Success/failure detection also runs while confirming
clicks and waiting for groups, so result overlays cannot trigger stale taps or OCR.
Unknown candidates still require a confirmed hit before saving coordinates;
each guess has the same 2.5-second confirmation window as a mapped click, so a
delayed hit is not attributed to a subsequent guess. This limits how many wrong
locations can safely be tried in a 60-second round.
In-round attempts reset for the next trio because previously inactive objects
can become requested; persistent item-specific misses remain excluded. Visual proposals
are refreshed from post-action frames, excluding already confirmed points and
known positions of other requested objects. Only a uniquely confirmed target
name/progress change is persisted; image saliency alone never becomes a mapping.
Round logs also report proposal-worker frame count and analysis time.
Visual proposals do not guarantee finding nine previously unseen items in 60s;
each failed guess still consumes its confirmation window.

Broad rapid-click grid sweeps are not used: practice testing showed a blocking
3-second waiting penalty after repeated wrong clicks, even at approximately
0.4 seconds per attempt. Captures and visual analysis remain continuous, but
exploratory clicks are serial and individually confirmed.
Unmapped landscapes/resolutions remain rejected and no hints are consumed.

The round logs measured FPS, mean capture duration, OCR group count/time, tap
time, confirmation time, and fresh-frame waiting time. Timings overlap because
capture runs concurrently. On the 5555 training emulator, initial optimized
rounds confirmed 9/9 in about 9.6–9.7 seconds at roughly 4.7 FPS, with three OCR
group reads. These are training measurements, not a guarantee for live stages
with unknown objects.

With the visual worker enabled, an earlier mapped regression round confirmed
nine clicks in 9.74 seconds. After switching to explicit result-screen completion,
a live practice round confirmed nine items and recognized the success overlay
in 12.58 seconds (13.90 seconds including entry), with nine scene taps, no hints
and no taps on the result screen.

Before clean-background comparison, cold-start validation on the same emulator,
with **all coordinate sources empty**
and isolated learned memory, found 6/9 before refinement, then 5/9 and 2/9 on
different draws. The bot attempted 25, 25 and 23 scene clicks respectively;
no hints were used. The visual worker analyzed roughly 277–282 frames per round
in parallel with ~4.6–4.7 FPS capture. None completed 9/9 within the game timer.
Confirmed click points can differ from the manually mapped center while still
hitting the object's clickable area; exact coordinate equality is not an accuracy
metric for this class-agnostic proposal method. These results validate autonomous
attempts and confirmed learning, **not reliable cold-start completion in 60s**.

With the clean forest background enabled, one isolated cold-start practice draw
reached explicit success for **9/9 in 36.43 seconds** (**37.80 including entry**),
using **17 scene taps** and no hints. All named/generic coordinate sources were
empty; permanent maps were unchanged. Seven coordinate associations were learned;
two hits were deliberately left unattributed by the conservative confirmation
guards. On a captured draw, proposals fell from 160 contrast candidates to seven
change regions, and from 160 to one when only the heart remained. Local pixel
analysis averaged about 2.4ms per frame in that offline sample. A mapped regression
still completed with nine scene taps in 14.20 seconds including entry.
These measurements cover this fixed training landscape, not a guarantee for
different layouts or every live-event draw.

### Castle Battle

```bash
.venv/bin/python main.py --port 5555 --event castle-battle
```

Castle Battle keeps its attack/healing flow, infirmary safety limits, and
`CASTLE_MAX_RUNTIME` bound. It reads the account profile before starting, then
alternates attacks and healing until that execution ends. It no longer runs
every five minutes in the daily routine. Select it explicitly again when wanted.
There are no automatic whole-event retries.

## Multiple emulators

Each emulator has its own ADB port (see Settings → Advanced → ADB).
Find the connected ports:
```bash
python main.py --list
```
Connect the second emulator (if not already connected):
```bash
adb connect 127.0.0.1:5615
```
Run **one process per emulator**, each in its own terminal:
```bash
# Terminal 1
python main.py --port 5605

# Terminal 2
python main.py --port 5615
```
Each log line is prefixed with the emulator port (e.g. `[emulator 5615]`),
so you can follow both separately.

To capture templates from a specific emulator:
```bash
python capture.py help.png --port 5615
```

## Structure

| File                | Purpose                                                   |
|---------------------|-----------------------------------------------------------|
| `config.py`         | Configuration (ADB port, threshold, interval).            |
| `adb_controller.py` | Connection, in-memory capture and taps via ADB.           |
| `vision.py`         | Template matching (finds buttons on screen).              |
| `tasks/`            | Task definitions and their steps (one file per task).     |
| `events/`           | Recurring/seasonal events, explicitly selected.            |
| `capture.py`        | Utility to take 1 screenshot and crop templates.          |
| `main.py`           | Main loop.                                                |
| `app.py`, `gui/`    | Control panel (local web server + pywebview window).      |

## Add new tasks

In `tasks/`, create a file with a `Task` (its detection template and steps),
and register it in `tasks/__init__.py`. Included examples: "Help alliance" and
"Collect Conquest".

## Disclaimer

Use at your own risk. Automation may violate the game's terms of service.
