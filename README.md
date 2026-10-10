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

### Sorte de Quem Procura

Open the event on the emulator, then run:

```bash
.venv/bin/python main.py --port 5555 --event hidden-objects
```

This runs one round and exits, preserving the prepared screen (no city/profile
navigation or automatic retries). From the pre-event page it starts the free
**Nível de Prática**. For a live stage, open/start the stage yourself first;
the bot does not spend event currency or buy hints.

The mapped forest scene uses **540x960** captures. Names (including two-line
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
