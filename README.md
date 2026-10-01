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
| `capture.py`        | Utility to take 1 screenshot and crop templates.          |
| `main.py`           | Main loop.                                                |
| `app.py`, `gui/`    | Control panel (local web server + pywebview window).      |

## Add new tasks

In `tasks/`, create a file with a `Task` (its detection template and steps),
and register it in `tasks/__init__.py`. Included examples: "Help alliance" and
"Collect Conquest".

## Disclaimer

Use at your own risk. Automation may violate the game's terms of service.
