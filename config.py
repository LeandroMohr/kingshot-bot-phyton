"""Global bot configuration."""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# ADB connection
# ---------------------------------------------------------------------------
# Address of the device/emulator exposed via ADB.
# BlueStacks on macOS usually exposes ADB on 127.0.0.1 on one of these ports.
# Run `adb devices` after connecting to confirm. Adjust if needed.
ADB_HOST = "127.0.0.1"
ADB_PORT = 5605  # BlueStacks port (Settings → Advanced → ADB)

# Ports the emulator picker tries to auto-connect before showing the menu, so
# BlueStacks instances show up without a manual `adb connect`. Add yours here.
DISCOVERY_PORTS = [5555, 5565, 5575, 5585, 5595, 5605, 5615, 5625, 6608]

# Path to the adb binary. If it is on your PATH, "adb" is enough.
ADB_BINARY = "adb"

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

# ---------------------------------------------------------------------------
# Vision / template matching
# ---------------------------------------------------------------------------
# Minimum confidence (0..1) to consider a template as found.
DEFAULT_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Game (auto-launch)
# ---------------------------------------------------------------------------
# Kingshot Android package (obtained via ADB).
GAME_PACKAGE = "com.run.tower.defense"

# Template proving the game is on the home screen (bottom menu).
HOME_MARKER = "home_bottom_menu.png"
# Template proving the world map is showing (its "Town" button, bottom-right).
WORLD_MARKER = "world_town.png"

# When the game opens it often shows welcome-back / promo popups (sometimes
# several in a row) that cover the home screen. Before running the tasks the
# bot dismisses them (X buttons / tutorial Skip) and, as a fallback, presses
# 'back'. A forced tutorial can chain many steps, so we allow a generous number
# of recovery actions; the loop stops early once home is reached, and gives up
# (asking the user for help) if it makes no progress for a while.
HOME_RECOVER_TRIES = 25
# If the screen doesn't change for this many actions in a row, we're stuck.
HOME_STUCK_LIMIT = 4

# Buttons that dismiss overlays covering the home screen, tried in order:
#   - close_x.png       : white X on the orange promo popups
#   - close_x_blue.png  : white X on the blue "New Advancement" popups
#   - close_x_white.png : plain white X on event popups (e.g. "Field Triage")
#   - close_x_dark.png  : plain white X on dark promo/purchase popups
#                         (e.g. "Reward for first purchase" / "TOP UP NOW")
#   - skip_tutorial.png : the "Skip >" button on tutorial dialogs
# Tapping these is safer than 'back' and never touches a purchase button.
DISMISS_MARKERS = ["close_x.png", "close_x_blue.png", "close_x_white.png", "close_x_dark.png", "skip_tutorial.png"]

# Forced tutorials (e.g. Truegold Lv.5) don't always have a Skip button: they
# put a pulsing yellow-green glow on the exact spot you must tap. We detect that
# glow by color (generic, works wherever the step points) and tap its center.
GLOW_HSV_LOW = (15, 110, 170)   # lower HSV bound of the highlight (yellow-orange)
GLOW_HSV_HIGH = (45, 255, 255)  # upper HSV bound of the highlight (yellow-green)
GLOW_MIN_AREA = 900             # min pulsing-blob area to count as a real highlight
#   (real tutorial glow rings measure ~1500+; ambient gold/water shimmer stays
#    well below this, so it is ignored)
# When the city home is already visible its buildings shimmer (animated gold),
# which can spike near GLOW_MIN_AREA. So while home is on screen we require a
# clearly larger blob before treating it as a real tutorial highlight.
GLOW_STRONG_AREA = 1300
# Upper bound: a real tutorial highlight is a compact ring (~1500-2500). Anything
# much bigger is animated promo/cutscene art (e.g. a glowing hero splash), not a
# tutorial step, so we ignore it to avoid tapping purchase popups.
GLOW_MAX_AREA = 4000
# How many times to tap the glow trying to advance before asking for help.
TUTORIAL_MAX_TAPS = 6

# ---------------------------------------------------------------------------
# Player profile reading
# ---------------------------------------------------------------------------
# The player avatar sits at a FIXED spot in the top-left corner of the home
# screen (the picture itself can change, the position does not), so we open the
# Governor Profile by tapping that coordinate instead of matching a template.
PROFILE_AVATAR_TAP = (32, 26)
# Template proving the Governor Profile screen is open (the header text).
PROFILE_MARKER = "profile_header.png"
# Text regions on the profile screen (x1, y1, x2, y2) at the 540x960 capture.
# Right column = account info (dark text on the light box); stamina = white text
# on a green pill, so it needs a different OCR pass (see executor/player_profile).
PROFILE_REGIONS = {
    "name": (215, 660, 455, 698),      # "[TAG]Player Name" (tag only if in an alliance)
    "id": (215, 708, 455, 740),        # "ID: 256466296" (permanent, unique)
    "power": (238, 743, 360, 774),     # combat power, e.g. "78.7M"
    "kills": (215, 772, 360, 802),     # "Kills: 2.4M"
    "alliance": (215, 802, 400, 830),  # "Alliance: RGR"
    "kingdom": (215, 832, 400, 864),   # "Kingdom: #1708"
}
# Stamina pill in the left column (white text on green), OCR'd via a color mask.
PROFILE_STAMINA_REGION = (58, 818, 160, 852)  # e.g. "647/200"

# After launching the game, check every GAME_READY_POLL seconds whether it has
# left the loading screen (reached the home screen), up to GAME_LAUNCH_TIMEOUT.
# The timeout is generous because there is sometimes a mandatory update.
GAME_READY_POLL = 1.0
GAME_LAUNCH_TIMEOUT = 300.0

# Network hiccups pop a "Connection lost" modal ("Unable to connect...") over
# whatever was on screen, with two buttons: "Contact Us" and "Reconnect". The
# bot taps Reconnect and waits for the game to reload, then resumes its flow.
CONNECTION_LOST_MARKER = "connection_lost.png"  # the "Connection lost" header
RECONNECT_BUTTON = "reconnect_button.png"       # the blue "Reconnect" button
RECONNECT_TAP = (385, 593)                      # fallback coords if template misses

# ---------------------------------------------------------------------------
# Alliance navigation
# ---------------------------------------------------------------------------
# The "Alliance" button on the home bottom menu (flag icon + text). Tapping it
# opens the Alliance screen (a grid of War / Chests / Territory / ... buttons).
ALLIANCE_HOME_BUTTON = "alliance_home_button.png"
ALLIANCE_HOME_TAP = (403, 918)                  # fallback coords if template misses
# The "Chests" button on the Alliance screen (chest icon + text). Doubles as the
# proof that the Alliance screen is open.
ALLIANCE_CHESTS_BUTTON = "alliance_chests_button.png"

# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------
# Main loop step (seconds). The bot wakes up every TICK and runs the tasks
# whose own interval has elapsed (each Task has its own 'interval').
TICK_INTERVAL = 1.0

# On startup the bot asks whether to run ALL tasks or just one. If there is no
# answer within this many seconds (or when not running in a terminal), it runs
# all of them.
TASK_MENU_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Task retry (transient lag / game reload resilience)
# ---------------------------------------------------------------------------
# The connection to the game can hiccup: the screen freezes (only a loading
# spinner, or even a blank gray screen with no assets) or the game reloads in
# the middle of a task, so a task can FAIL just because the templates weren't on
# screen at that instant. Instead of skipping it until the next cycle, we retry
# it a few times. Between attempts we recover first (make sure the game is in the
# foreground and back on the home screen), which also covers a game reload.
# Only genuine failures are retried — "nothing to do" (ABSENT) is not a failure.
TASK_RETRY_ATTEMPTS = 2   # extra attempts after the first, on failure
TASK_RETRY_DELAY = 3.0    # seconds to let the game settle before retrying

# ---------------------------------------------------------------------------
# Terror Hunt (rally on the world map)
# ---------------------------------------------------------------------------
# Flow: World -> search (magnifier) -> Terror -> pick level -> Search -> Rally
#       -> 5 min arrival -> load the "HNT" formation -> Deploy -> back to Town.
# The hunt is SEQUENTIAL: after deploying we wait for the troops to return
# (TERROR_RALLY_DURATION) before checking stamina and launching the next one.
TERROR_LEVEL_DEFAULT = 8          # level hunted by default (the file overrides it)
TERROR_LEVEL_MIN = 3              # the search slider's floor for Terrors
TERROR_LEVEL_MAX = 8              # the search slider's ceiling for Terrors
# Stamina per rally. We NEVER estimate consumption (a lost rally does not cost
# stamina); instead we read the ACTUAL stamina before each launch and only fire
# when there is enough. The "hnt" mode uses the HNT/Diana preset (20), the
# "fill" mode uses whatever heroes the game auto-picks (25).
TERROR_RALLY_COST_HNT = 20        # stamina per rally WITH the HNT/Diana preset
TERROR_RALLY_COST_FILL = 25       # stamina per rally WITHOUT Diana ("fill" mode)
TERROR_RALLY_COST = 20            # legacy alias (kept for compatibility)
TERROR_MIN_STAMINA = 20           # deficit floor used when scheduling a recharge
TERROR_RECHARGE_TARGET = 100      # when out, wait until roughly this much accrues
STAMINA_MINUTES_PER_POINT = 5     # the game restores +1 stamina every 5 minutes
TERROR_RALLY_DURATION = 20 * 60   # seconds to let the troops go/fight/return
# File the operator can edit any time to change the hunted level (hot-reloaded
# before every hunt); the task also asks in the terminal (see the prompt below).
TERROR_LEVEL_FILE = BASE_DIR / "memory" / "hunt_config.json"
# Seconds the terminal prompt waits for a new level before keeping the current
# one. Only asked when running interactively (a real terminal / TTY).
TERROR_LEVEL_PROMPT_TIMEOUT = 10.0
# Fixed coordinates / regions on the search panel (at the 540x960 capture):
TERROR_LEVEL_MINUS = (37, 790)         # slider '-' button
TERROR_LEVEL_PLUS = (363, 790)         # slider '+' button
TERROR_LEVEL_BOX = (430, 772, 492, 808)  # value box (x1,y1,x2,y2) for OCR
RALLY_5MIN_TAP = (97, 441)             # the "5 min(s)" arrival-time checkbox

# Beast Hunt uses the same world-search panel, march tracking and HNT formation
# as Terror Hunt, but Beasts are direct attacks (no rally setup) and span Lv.1-30.
BEAST_LEVEL_DEFAULT = 30
BEAST_LEVEL_MIN = 1
BEAST_LEVEL_MAX = 30
BEAST_STAMINA_COST = 10
BEAST_LEVEL_FILE = BASE_DIR / "memory" / "beast_hunt_config.json"
BEAST_CATEGORY_OFFSET_X = -100         # Beasts tab is immediately left of Terror
BEAST_ATTACK_TAP = (270, 460)          # orange Attack button on the Beast card
BEAST_LEVEL_TAP_DELAY = 0.35           # lets the UI accept each required +/- tap
BEAST_LEVEL_SETTLE_DELAY = 0.6         # wait for the displayed value before OCR
BEAST_LEVEL_READ_TRIES = 3             # tolerate a transient OCR miss
BEAST_LEVEL_ADJUST_PASSES = 3          # correct taps dropped by the game UI
# Marching panel (used to detect when the troops are back). The bot stays on the
# world map between rallies, where the "Marching N/M" panel is ALWAYS OPEN on the
# left. It reads that N/M counter by OCR (no taps: tapping fixed points there
# collapsed the panel and mis-clicked cities on the map). "N" is how many marches
# are out; free slots = M - N. It only returns to the city once stamina runs out.
MARCH_COUNTER_REGION = (138, 150, 196, 180)  # "N/M" counter box (x1,y1,x2,y2)
MARCH_MAX_QUEUES = 6                   # most march queues a governor can have (M)
# The "Marching N/M" panel is NOT always on screen: it only appears while at
# least one march is out. When every queue is home the panel is ABSENT, and the
# N/M counter cannot be OCR'd. We detect the panel by its "Marching" header
# template; if it is missing we treat it as 0 marches out (all queues free),
# which is the common "start with everything idle" / "fill all 6 queues" case.
MARCHING_PANEL_TEMPLATE = "marching_panel.png"  # the "Marching" header word
MARCHING_PANEL_THRESHOLD = 0.85       # match >= this means the panel is on screen
# After a Deploy the "Marching N/M" counter can take a moment to reflect the new
# march. When tracking which slot a rally took we re-read the counter a few times
# until it drops, so a launch is never lost to counter lag.
TERROR_COUNTER_SETTLE_TRIES = 4       # how many times to re-read after a launch
TERROR_COUNTER_SETTLE_DELAY = 1.0     # seconds between those re-reads
# If EVERY march queue is already busy with the player's other activities
# (gathering, ...) there is no free queue to hunt with right now. That is not a
# failure: back off and check again after this delay instead of hammering retries.
TERROR_ALL_BUSY_RETRY = 15 * 60       # seconds to wait when all queues are busy
# Stamina is read from the Intel Mission screen (opened by the compass icon at
# the bottom-right of the world map). Its top-right "meat" counter is the
# current stamina — a big white number, easy and reliable to OCR, and it keeps
# the whole flow on the world map. 'back' closes it straight to the world map.
INTEL_MISSION_TEMPLATE = "intel_mission.png"  # the compass icon on the world map
INTEL_MISSION_TAP = (492, 648)         # fallback tap if the template is missing
INTEL_STAMINA_REGION = (446, 6, 508, 50)  # meat counter box (x1,y1,x2,y2) for OCR
# The "Quit game?" confirmation that pops up if 'back' is pressed on the world
# map. The hunt must NEVER confirm it; recovery taps Cancel instead. Fallback
# coordinate for the orange "Cancel" button (used if quit_cancel.png is missing).
QUIT_CANCEL_TAP = (156, 592)
TERROR_RETURN_POLL = 10.0              # seconds between "are the troops back?" checks
TERROR_RETURN_MIN_WAIT = 5 * 60        # ignore the queue until the rally can be back
TERROR_RETURN_MAX_WAIT = 30 * 60       # safety cap: relaunch even if detection fails
# Rally mode:
#   "hnt"  -> a single rally that loads the saved "HNT" preset (Diana + ratio).
#   "fill" -> keep EVERY free march queue busy with rallies. It never loads the
#             HNT preset (those heroes are individual); it relies on the heroes
#             the game auto-selects and taps "Equalize" so the troops are split
#             evenly and more marches fit. Slots taken by other activities are
#             left untouched.
TERROR_RALLY_MODE_DEFAULT = "hnt"
TERROR_RALLY_MODES = ("hnt", "fill")
# Diana preference (mode "hnt" only). The HNT preset only loads Diana when she is
# free; if she is out on a march the archer slot is empty and the rally costs the
# full 25 stamina (no discount). When require_diana is on, the hunt WAITS for her
# to return instead of deploying without her; when off, it hunts anyway (cost 25).
# Detected by matching her portrait in the rally's hero slots.
TERROR_REQUIRE_DIANA_DEFAULT = True
TERROR_DIANA_TEMPLATE = "diana_hero.png"   # Diana's portrait (archer slot crop)
TERROR_DIANA_THRESHOLD = 0.80              # match >= this means Diana is loaded
TERROR_DIANA_WAIT_RETRY = 5 * 60           # seconds to wait for Diana before re-checking

# ---------------------------------------------------------------------------
# Gather resources (tasks/gather_resources.py)
# ---------------------------------------------------------------------------
# Reuses the Terror SEARCH screen (world map -> magnifier). Instead of the
# Terror (beast) category it selects a RESOURCE category from the bottom row
# (horizontally scrollable): ... | Bread | Wood | Stone | Iron (Terror and Great
# Mill are further left). Each gather occupies ONE march queue; the task fills
# every FREE queue, distributing the resources round-robin in GATHER_RESOURCE_ORDER,
# always trying the highest level first and dropping a level only when no node is
# found OR the available troops cannot fill the node's capacity.
GATHER_RESOURCE_ORDER = ("iron", "stone", "wood", "bread")  # round-robin priority
GATHER_RESOURCE_ICONS = {                     # bottom-row category-icon templates
    "iron": "res_iron.png",
    "stone": "res_stone.png",
    "wood": "res_wood.png",
    "bread": "res_bread.png",
}
# The one BLUE gatherer the game auto-selects (slot 1) for each resource. We keep
# ONLY this hero and remove the generic gold heroes; if he is out on a march (not
# matched) we deploy with NO hero at all.
GATHER_RESOURCE_HEROES = {
    "iron": "hero_seth.png",
    "stone": "hero_edwin.png",
    "wood": "hero_forrest.png",
    "bread": "hero_olive.png",
}
GATHER_HERO_THRESHOLD = 0.85                  # match >= this = correct hero present
GATHER_ICON_THRESHOLD = 0.85                  # match >= this = category icon found
# The category row starts scrolled left (Terror/Great Mill visible). Swiping it
# left twice pins it to the right extent where all four resource icons show.
GATHER_CAT_ROW_SWIPE = (480, 675, 120, 675, 500)  # (x1, y1, x2, y2, duration_ms)
# Resource levels go 1..8 (floor is 1, NOT 3 like Terrors). The slider itself is
# the SAME control as the Terror one (reuses TERROR_LEVEL_MINUS/PLUS/BOX).
GATHER_LEVEL_MIN = 1
GATHER_LEVEL_MAX = 8
GATHER_LEVEL_START = 8                         # always try the highest level first
# The node CARD shown after Search carries the cyan "Gather" button: its presence
# means a node was found. Its ABSENCE after Search means "no suitable target"
# (we stay on the search screen) -> drop a level / move to the next resource.
GATHER_BUTTON_TEMPLATE = "gather_button.png"
GATHER_BUTTON_THRESHOLD = 0.80
GATHER_CARD_CAPACITY_REGION = (300, 333, 418, 353)  # node "Capacity" value (dark text)
# The DEPLOY/formation screen (after tapping Gather). Slot 1 holds the auto-picked
# blue gatherer; slots 2 and 3 hold generic gold heroes. Per-slot red "minus"
# buttons remove a hero (tapped RIGHT-to-LEFT so remaining cards do not reflow).
GATHER_HERO_SLOT_MINUS = ((179, 238), (320, 239), (462, 239))
GATHER_HERO_SLOT_CENTERS = (128, 270, 411)    # hero card centre x per slot
GATHER_CARRY_REGION = (405, 133, 510, 160)    # troops' carry capacity (white text)
GATHER_DEPLOY_BUTTON = "gather_deploy_button.png"  # the "Deploy" button (bottom-right)
GATHER_BACK_ARROW = (30, 28)                  # deploy-header back arrow (-> search)
# The point of gathering is the specialist hero's buff, so the task keeps exactly
# ONE active gather per resource (four marches max), each with its blue gatherer.
# A busy specialist means that resource is already being gathered, so it is
# skipped; a gather is never dispatched without its hero. While any gather is
# running the task re-checks every GATHER_ACTIVE_RETRY (queues stay tied up for
# hours); otherwise it retries sooner on GATHER_INTERVAL.
GATHER_INTERVAL = 20 * 60                      # seconds between gather sweeps
GATHER_ACTIVE_RETRY = 60 * 60                 # wait 1h while gathers are running
GATHER_ALL_BUSY_RETRY = 15 * 60               # seconds to wait when all queues busy

# ---------------------------------------------------------------------------
# Train troops (tasks/train_troops.py)
# ---------------------------------------------------------------------------
# The Barracks is reached DETERMINISTICALLY through the Power panel, which the
# game auto-centres for us (no fragile map navigation / camera anchor needed):
#   home -> tap combat power (top-left)  -> "Bonus Overview" modal
#        -> tap "Power"                  -> the Power ranking
#        -> tap "Enhance" next to "Troop Power"
#   The game then jumps straight to the Barracks with its radial menu open and
#   the "Train" button highlighted. Tapping "Train" opens the training screen,
#   whose bottom tabs switch between all three troop types without leaving it.
TRAIN_POWER_TAP = (120, 62)            # the combat power counter on the home HUD
TRAIN_BONUS_POWER_BTN = (270, 637)     # the "Power" button in the Bonus Overview modal
TRAIN_TROOP_POWER_ENHANCE = (454, 433)  # "Enhance" next to "Troop Power" -> jumps to Barracks
TRAIN_BARRACKS_BUILDING = (230, 390)   # the centred Barracks fort; tap to open its radial menu
TRAIN_RADIAL_TRAIN_TAP = (363, 565)    # the highlighted radial "Train" button after the jump
# On the training screen (fixed layout) these are reliable template markers:
TRAIN_SCREEN_MARKER = "train_screen_marker.png"  # the list icon (both states)
TRAIN_RADIAL_BUTTON = "radial_train.png"         # the "Train" button in the radial menu
TRAIN_START_BUTTON = "train_start_button.png"    # the cyan "Train" start button (idle)
TRAIN_SPEEDUPS_BUTTON = "train_speedups.png"     # the "Speedups" button (already training)
# A LOCKED tier (not yet unlocked by the building level) is shown greyed out;
# selecting it replaces the "Train" button with "Upgrade Now" and shows a
# "Reach ... to unlock" panel. This template detects that locked state so we can
# fall back to the highest UNLOCKED tier instead.
TRAIN_UPGRADE_NOW_BUTTON = "train_upgrade_now.png"
TRAIN_START_TAP = (385, 832)           # fallback tap for the "Train" start button
# The training screen has an animated glow (the selected tier pulses), which
# confuses the generic tutorial-highlight recovery in go_to_home_screen. So we
# close the screen explicitly with its own back arrow before returning home.
TRAIN_BACK_ARROW = (30, 27)            # the back arrow (top-left) of the training screen
# A troop-promotion / "your troops are getting stronger" celebration can pop up
# over the training screen (e.g. when a building levels up) and swallow the tap
# on "Train". Tapping this harmless neutral spot (over the troop preview)
# dismisses such a full-screen popup without affecting the idle training screen.
TRAIN_POPUP_DISMISS_TAP = (270, 250)
# After the training flow, re-validate that all three timers actually started,
# retrying any that did not, for at most this many passes before leaving.
TRAIN_VALIDATE_PASSES = 3
# The three troop-type tabs at the bottom of the training screen. Tapping one
# switches the trained troop type WITHOUT leaving the screen or navigating the
# map, so a single visit trains all three.
TRAIN_TABS = {
    "infantry": (97, 915),
    "cavalry": (270, 925),
    "archer": (443, 925),
}
# The tier selector: a horizontal row of hexagons (I..X) at this Y. It scrolls;
# swiping left reveals the HIGH tiers (…X at the right), swiping right reveals the
# LOW tiers (I… at the left). Each visible page shows five hexagons at these X's.
# So tiers 6-10 live on the right page, tiers 1-5 on the left page, both at the
# same five slots — pick the page, then the slot.
TRAIN_TIER_ROW_Y = 530
TRAIN_TIER_SLOTS_X = (57, 157, 255, 355, 455)
TRAIN_TIER_SCROLL_RIGHT = (100, 530, 460, 530)  # reveal LOW tiers (swipe content right)
TRAIN_TIER_SCROLL_LEFT = (460, 530, 100, 530)   # reveal HIGH tiers (swipe content left)
# The quantity slider: dragging it fully right maxes the batch to the building's
# training capacity; dragging fully left sets the minimum (1). While testing we
# keep the batch minimal to avoid burning resources/speedups (TRAIN_MAX_QUANTITY
# = False). Flip it to True for real training passes.
TRAIN_QTY_SLIDER_MAX = (85, 733, 320, 733)      # drag fully right to max the batch
TRAIN_QTY_SLIDER_MIN = (283, 733, 40, 733)      # drag fully left to the minimum (1)
TRAIN_MAX_QUANTITY = True                         # True = max batch; False = minimum (test-safe)
# Default tier to train and its bounds. Saved PER ACCOUNT (each account can pick
# a different tier); the shared file is the fallback for unknown accounts. The
# terminal prompt keeps the saved value if there is no answer within the timeout.
TRAIN_TIER_DEFAULT = 10                # X = Apex = strongest
TRAIN_TIER_MIN = 1
TRAIN_TIER_MAX = 10
TRAIN_TIER_FILE = BASE_DIR / "memory" / "train_config.json"
TRAIN_TIER_PROMPT_TIMEOUT = 5.0        # seconds to wait for a new tier before keeping
# Trained troop types, in the order the tabs are visited.
TRAIN_TROOP_TYPES = ("infantry", "cavalry", "archer")
# The task loops every 3 hours: it re-checks each troop type and, for any whose
# batch has finished (the "Train" button is back instead of "Speedups"), starts a
# new batch at the saved tier. Types still training (a countdown is shown) are
# skipped until the next pass.
TRAIN_INTERVAL = 3 * 60 * 60           # seconds between training passes

# ---------------------------------------------------------------------------
# Governor Order (the "scales"/balance icon). Opened from the city: on the right
# edge there is a vertical stack of icons (paw, scales, email). The paw may not
# exist yet on low-level accounts, so the EMAIL icon (always present) is the
# anchor: the scales sit one slot above it. The screen shows a 2x3 grid of
# "order" books; issuing an order spends stars (balance at the top-right) and
# activates a timed city buff. Three orders are issued in a strict sequence,
# needing 250,000 stars total; if the balance is lower, none are issued.
# ---------------------------------------------------------------------------
GOV_EMAIL_ICON = "gov_email_icon.png"   # the email envelope icon (anchor, always present)
GOV_BALANCE_ICON = "gov_balance_icon.png"  # the scales icon (secondary; fails under a red dot)
GOV_BALANCE_FROM_EMAIL_DY = 71          # the scales are this many px above the email icon
GOV_BALANCE_FALLBACK_TAP = (497, 721)   # fixed scales position if neither template is found
GOV_ISSUE_BUTTON = "gov_issue_button.png"  # the cyan "Issue" label on an order's book
GOV_ISSUE_TAP = (270, 692)              # the "Issue" button (fixed layout on the book)
# Star balance at the top-right of the Governor Order screen ("82.3M"). OCR region.
GOV_STARS_REGION = (435, 10, 505, 42)
# The three orders issued, in strict order, with their star cost and the OCR
# region (x1,y1,x2,y2) of the book's status banner on the 2x3 grid. A book shows
# "On cooldown HH:MM:SS" (already issued) or "Active HH:MM:SS" (running); an
# available book shows only its icon (no banner text). Book tap points on the
# grid: col1/col2 x, rows at these y's (centres).
GOV_ORDERS = (
    ("productivity", (163, 715), 50_000, (88, 688, 242, 748)),   # col1 row3: +100% output 24h (cd 12h)
    ("rush_job", (371, 265), 150_000, (300, 240, 445, 300)),     # col2 row1: 5 days of resources (Rewards modal)
    ("festivities", (371, 715), 50_000, (300, 688, 445, 748)),   # col2 row3: +50 Mood/+30 Comfort (cd 1 day)
)
# A book is UNAVAILABLE when its banner OCR contains any of these (case-insensitive):
# "cooldown" (already issued, waiting) or "active" (currently running).
GOV_UNAVAILABLE_KEYWORDS = ("cooldown", "active")
GOV_TOTAL_COST = 250_000                # sum of the three costs; need at least this to run
GOV_POST_ISSUE_DELAY = 6.0              # seconds of on-screen effects after issuing before reopening
GOV_REWARDS_DISMISS_TAP = (270, 500)    # neutral spot to dismiss the Rush Job "Rewards" modal
GOV_INTERVAL = 12 * 60 * 60             # loop every 12h (Productivity cooldown is the shortest)

# ---------------------------------------------------------------------------
# Arena of Glory (PVP). Reached like the Barracks: jump to the troop buildings
# through the Power panel, close the Barracks radial, then pan the view right
# until the crossed-swords Arena building marker is on screen. Tapping that
# marker opens the "Arena of Glory" ranking screen (with the "Challenge" button
# at the bottom). The Arena sits below the Stable and beside the Range.
# ---------------------------------------------------------------------------
ARENA_RADIAL_CLOSE_TAP = (40, 640)     # empty green spot to close the Barracks radial
# One SHORT pan (100 px) played SLOWLY: `adb input swipe` flings the map, so a
# long/fast swipe overshoots the Arena and the first tap lands on the wrong spot
# (the view is still drifting). 100 px over 900 ms moves the map ~140 px, which
# keeps the marker from jumping past the screen in a single step.
ARENA_PAN_RIGHT = (360, 500, 260, 500)  # one small "pan the view right" swipe
ARENA_PAN_DURATION = 900               # ms; slower swipe = less fling/inertia
ARENA_SETTLE_TRIES = 6                 # frames to compare while the map coasts
ARENA_SETTLE_DELAY = 0.5               # seconds between those frames
ARENA_MAX_STEPS = 10                   # give up after this many pan/tap iterations
ARENA_ICON_TEMPLATE = "arena_building_icon.png"    # the crossed-swords building marker
ARENA_ICON_THRESHOLD = 0.78            # the marker peaks ~0.83 when the Arena is on screen
ARENA_TITLE_TEMPLATE = "arena_of_glory_title.png"  # confirms the Arena of Glory screen is open
ARENA_CHALLENGE_TEMPLATE = "arena_challenge_button.png"  # the "Challenge" button at the bottom
ARENA_MARKER_THRESHOLD = 0.85
ARENA_BACK_ARROW = (30, 30)            # back arrow (top-left) of the Arena of Glory screen
ARENA_INTERVAL = 60 * 60               # seconds between Arena checks (loop)

# -- Arena challenge / fight flow -------------------------------------------
# The "Challenge" button opens the "Challenge List" modal: "My Power" at the top
# and up to five opponent rows (avatar, name, green power value with a fist
# icon, star rating, rank, and a crossed-swords fight button on the right).
# Powers are read by OCR (green HSV mask + Tesseract psm 13). The weakest
# opponent at or below ARENA_MAX_OPPONENT_RATIO * my_power is chosen (falling
# back to the weakest overall) — never fight someone stronger than us.
ARENA_CHALLENGE_TAP = (271, 912)       # the "Challenge" button on the Arena screen
ARENA_CHALLENGE_LIST_TITLE = "arena_challenge_list_title.png"  # confirms the modal is open
ARENA_MYPOWER_REGION = (286, 186, 412, 214)  # "My Power" number (fist icon excluded)
# Opponent rows are located by their GREEN power text rather than by fixed
# coordinates: the modal shifts vertically depending on what the footer shows
# (e.g. the "Free Refresh" button), which used to push the power values out of
# the fixed crop and make every reading fail.
ARENA_GREEN_HSV_LOW = (35, 50, 50)     # green power-text mask
ARENA_GREEN_HSV_HIGH = (85, 255, 255)
ARENA_ROW_SCAN_X = (100, 260)          # x band scanned for the power text
ARENA_ROW_SCAN_Y = (200, 740)          # y band holding the opponent list
ARENA_ROW_MIN_PIXELS = 5               # green pixels on a line to count as text
ARENA_ROW_MIN_HEIGHT = 6               # thinner bands are noise
ARENA_ROW_MAX_HEIGHT = 25              # taller ones are the green "Free Refresh" button
ARENA_ROW_MAX_WIDTH = 120              # wider ones are buttons, not a power value
ARENA_FIGHT_BTN_X = 468                # x of the crossed-swords fight button on each row
ARENA_FIGHT_BTN_DY = -22               # its centre, relative to the row's power text
ARENA_MAX_OPPONENT_RATIO = 0.85        # prefer opponents <= 85% of my power
ARENA_CHALLENGE_CLOSE_TAP = (498, 144)  # X to close the Challenge List modal
ARENA_FIGHT_TEMPLATE = "arena_fight_button.png"  # "Fight" button on the squad-selection screen
ARENA_MAX_CHALLENGES = 5               # daily challenge limit (fight this many per pass)
ARENA_PAUSE_TAP = (50, 722)            # pause button (bottom-left) during the battle
ARENA_RETREAT_TAP = (192, 477)         # "Retreat" in the pause dialog -> jumps to the result
ARENA_STEP_DELAY = 2.5                 # delay between fight/pause/retreat steps (needs 2-3s)
ARENA_RESULT_EXIT_TAP = (270, 830)     # tap to dismiss the result screen
ARENA_RESULT_MAX_WAIT = 30             # max seconds to wait for the result to clear
ARENA_RESULT_POLL = 2                  # seconds between result-screen polls

# ---------------------------------------------------------------------------
# Intel Missions (the "Intel Mission" panel, opened by the compass on the world
# map). Balloons scattered on a mini-map are dispatchable missions of three
# types, each with a rarity color. The task does them in priority order until
# resources run out, then claims the rewards. Runs BEFORE Hunt Terror so the
# missions get the stamina/food first (Hunt Terror is what drains it).
# ---------------------------------------------------------------------------
INTEL_PANEL_MARKER = "intel_panel_marker.png"   # the "Intel Mission" title
INTEL_PANEL_THRESHOLD = 0.80
# Balloon glyphs. The white glyph (lion / crossed swords / tent) is IDENTICAL
# across every rarity while the pin body color changes, so they are matched on
# GRAYSCALE (vision.find_all_gray) to find every pin regardless of its color.
INTEL_GLYPH_LION = "intel_lion.png"        # Monster Hunt
INTEL_GLYPH_SWORDS = "intel_swords.png"    # Battle
INTEL_GLYPH_TENT = "intel_tent.png"        # Refugee Rescue
# Queue-occupying "attack" missions show the TARGET's portrait, which varies per
# target. "hunt" (ordinary Monster Hunts) is matched against a LIST of glyph
# templates; add a new one here when a new monster target appears.
INTEL_GLYPH_HUNT = ("intel_lion.png",)
# Rebel Bounty ("Gilded Baron") is a SEPARATE, special mission handled last and
# looped (see below). Its balloon is the bigger bounty portrait.
INTEL_GLYPH_BOUNTY = ("intel_bounty.png",)
INTEL_GLYPH_THRESHOLD = 0.70
INTEL_GLYPH_MIN_DISTANCE = 25
# A pin whose mission is already done shows a small bright-green check badge at
# the top-right of its head; those are skipped. Detected by counting bright-green
# pixels in a tight box offset from the glyph center (dx1..dx2, dy1..dy2).
INTEL_CHECK_BOX = (6, 22, -24, -8)         # (dx1, dx2, dy1, dy2) around glyph center
INTEL_CHECK_HSV_LOW = (38, 140, 150)       # bright green (H,S,V) low
INTEL_CHECK_HSV_HIGH = (80, 255, 255)      # bright green (H,S,V) high
INTEL_CHECK_MIN_PIXELS = 10                # >= this many green px -> mission done
# Rarity is read from the pin body's dominant hue (sampled in a box around the
# glyph, saturated pixels only). Ordered best -> worst; lower rank = dispatched
# first. Gold and orange share the same hue band (top rarity).
INTEL_RARITY_BOX = 24                      # half-size of the hue-sampling box
INTEL_RARITY_MIN_S = 80                    # min saturation for a "colored" pixel
INTEL_RARITY_MIN_V = 60                    # min value for a "colored" pixel
# Hue bands (OpenCV H, 0-180) -> rarity rank. (low, high, rank, name).
INTEL_RARITY_BANDS = (
    (8, 30, 0, "gold"),     # gold/orange = best
    (118, 150, 1, "purple"),
    (90, 118, 2, "blue"),
    (35, 85, 3, "green"),
)
INTEL_RARITY_WHITE_RANK = 4                # low-saturation pin = white = worst
# Dispatch flow taps (all validated live). The preview "View" button is found by
# template (its Y varies a little per mission); the world-map action button
# (Attack / Conquer / Rescue) sits at the same spot for all three types.
INTEL_VIEW_BUTTON = "intel_view.png"       # cyan "View" on the preview dialog
INTEL_ACTION_TAP = (270, 472)              # Attack / Conquer / Rescue on the world dialog
INTEL_DEPLOY_BUTTON = "deploy_button.png"  # "Deploy" on the hunt formation screen
INTEL_FIGHT_BUTTON = "intel_fight.png"     # green "Fight" on the battle squad screen
INTEL_VICTORY_EXIT_TAP = (270, 830)        # "tap anywhere to exit" after a battle win
INTEL_CLAIM_ALL_TAP = (270, 845)           # "Claim All" at the bottom of the panel
# On a Monster Hunt's Deploy screen, tap "Equalize" to send the smallest army
# that still wins, then verify the green "you are likely to prevail" prediction
# before deploying (never deploy an army that is not predicted to win).
INTEL_EQUALIZE_BUTTON = "intel_equalize.png"   # "Equalize" button on the Deploy screen
INTEL_EQUALIZE_TAP = (148, 890)                # fallback tap if the template is missing
INTEL_WIN_MSG_REGION = (120, 395, 420, 425)     # (x1,y1,x2,y2) of the prediction text
INTEL_WIN_MSG_HSV_LOW = (40, 120, 120)         # green prediction text (H,S,V) low
INTEL_WIN_MSG_HSV_HIGH = (90, 255, 255)        # green prediction text (H,S,V) high
INTEL_WIN_MSG_MIN_PIXELS = 200                 # >= this many green px -> win predicted
# The green "Claim All" button; when present (finished missions exist, possibly
# hidden behind overlapping pins) tap it on panel entry so their pins clear and
# any overlapped missions become visible.
INTEL_CLAIM_BUTTON = "intel_claim.png"
INTEL_CLAIM_THRESHOLD = 0.85
# Some accounts (Master "Pan" trait) show an advisor-portrait icon at the panel's
# top-left. Tapping it reveals an EXTRA batch of missions (often more hunts). Not
# every account has it, so it is only tapped when its template is matched; the
# icon is consumed by the tap (disappears), and re-checked each wave in case a
# new batch appears.
INTEL_ADVISOR_ICON = "intel_advisor_icon.png"
INTEL_ADVISOR_THRESHOLD = 0.85
# Mission type priority (do all hunts, then battles, then refugees) and per-type
# waits. Only Monster Hunt occupies a march queue and has travel time; Battle and
# Refugee resolve without a queue.
INTEL_TYPE_ORDER = ("hunt", "battle", "refugee")
INTEL_BATTLE_ANIM_WAIT = 8.0               # seconds after "Fight" for the win/lose animation
                                           # to finish and the Victory screen to appear (>= 2s)
INTEL_MAX_DISPATCH = 50                    # absolute safety cap on missions per run
INTEL_MAX_RUNTIME = 20 * 60               # wall-clock budget (s) for one run, incl. queue waits
INTEL_QUEUE_WAIT_POLL = 45                # seconds between free-queue checks while waiting
INTEL_QUEUE_RETRY = 10 * 60               # when all queues are busy, re-run in 10 min (not block)
INTEL_DISPATCH_MAX_RETRY = 3              # give up on a spot after this many failed dispatches
INTEL_INTERVAL = 6 * 60 * 60               # seconds between runs (panel refreshes ~5-6h)
# Stamina cost per mission type (drawn from the meat counter at the panel's
# top-right, read via INTEL_STAMINA_REGION). Hunts get first claim on stamina —
# they are reserved before any battle/refugee is planned — so a wave never spends
# the food a pending hunt still needs. Diana's -20% discount is ignored on
# purpose (conservative: never over-commit stamina).
INTEL_STAMINA_COST = {"hunt": 10, "battle": 10, "refugee": 12, "bounty": 10}
INTEL_STAMINA_MASK_LO = 170              # white-mask low threshold for the meat OCR
                                         # (170 reads the "192" cleanly; 155 misread the 9)

# --- Rebel Bounty ("Gilded Baron") -----------------------------------------
# A special, LAST mission: run only after every other Intel mission is done.
# It repeats, getting harder each win, until we LOSE once (or run out of stamina
# / a queue). Win/loss is read from the mail: World -> Mail -> Reports tab ->
# open the most recent (unread) battle report -> the "Battle Overview" shows a
# golden "VICTORY!" banner on a win (its absence on a battle overview = defeat).
INTEL_MAIL_TAP = (497, 787)                # envelope on the world map
INTEL_MAIL_CLOSE_TAP = (512, 30)           # "X" to close the mail
INTEL_MAIL_BACK_TAP = (30, 30)             # back arrow inside a mail sub-screen
INTEL_REPORTS_TAB_TAP = (372, 89)          # "Reports" tab
INTEL_TOP_REPORT_TAP = (270, 178)          # first (most recent) report in the list
INTEL_REPORT_ROW1_TAP = (240, 255)         # first row inside a grouped report
INTEL_REPORT_UNREAD_REGION = (505, 130, 525, 150)  # red "unread" dot on the top report
INTEL_REPORT_UNREAD_MIN_PIXELS = 8         # >= this many red px -> top report is unread
INTEL_REPORT_OVERVIEW_MARKER = "report_battle_overview.png"  # "Battle Overview" title
INTEL_REPORT_VICTORY_MARKER = "report_victory.png"          # golden "VICTORY!" banner
INTEL_REPORT_MARKER_THRESHOLD = 0.80
# Instead of blindly polling the mail (open/close, open/close) waiting for the
# battle to resolve, we read the OUTBOUND march time straight off the Deploy
# screen ("HH:MM:SS" next to the clock icon above the Deploy button) and wait
# exactly that long PLUS a small buffer before opening the mail a single time.
# This keeps the bot from thrashing the mail windows and getting lost.
INTEL_DEPLOY_MARCH_TIME_REGION = (372, 858, 470, 880)  # outbound march "HH:MM:SS" on Deploy
INTEL_BOUNTY_MAIL_BUFFER = 5               # extra seconds after the march to let the report land
INTEL_BOUNTY_MARCH_FALLBACK = 90           # assumed march seconds if the time can't be read
INTEL_BOUNTY_RESULT_RETRY = 3              # a few short mail re-reads if the report is not up yet

# Rebel Bounty troop ratio. The bounty army is set through the Deploy screen's
# "Balance" dialog to a fixed composition (infantry/cavalry/archer). The dialog's
# +/- buttons change the selected type by 1% each and the total is capped at
# 100%, so we always apply every decrease first (to free headroom) then every
# increase. Reached via OCR of each row's percentage box.
INTEL_BOUNTY_RATIO = {"inf": 50, "cav": 20, "arc": 30}  # target percentages, must sum to 100
INTEL_BALANCE_BUTTON_TAP = (247, 890)      # "Balance" button on the Deploy screen
INTEL_BALANCE_ROWS = {"inf": 397, "cav": 507, "arc": 617}  # Y of each Balance row
INTEL_BALANCE_MINUS_X = 152                # X of every row's "-" button
INTEL_BALANCE_PLUS_X = 384                 # X of every row's "+" button
INTEL_BALANCE_PCT_REGION_X = (418, 478)    # X span of the "%" box (Y from the row +/-15)
INTEL_BALANCE_CONFIRM_TAP = (270, 735)     # "Confirm" button in the Balance dialog
INTEL_BALANCE_CLOSE_TAP = (497, 238)       # "X" to close the Balance dialog
INTEL_BALANCE_TAP_DELAY = 0.15             # pause after each +/- tap so the value updates

# ----------------------------------------------------------------------------
# Daily Missions (scroll / quest tracker on the home screen)
# ----------------------------------------------------------------------------
# The parchment icon on the bottom-left of the city view opens the daily-mission
# panel. Its "Daily" tab lists recurring objectives (help, train, contribute,
# ...) that are DONE by other bot tasks; this task only CLAIMS the rewards. The
# green "Claim All" button collects every completed mission at once, and the
# activity-point milestone chests on the top progress bar auto-open (chained
# reward popups) as the bar crosses each threshold. The per-mission "Go" buttons
# navigate away to perform a mission and must NEVER be tapped here.
DAILY_INTERVAL = 60 * 60                    # loop hourly; claims accumulate through the day
DAILY_SCROLL_ICON = "daily_scroll_icon.png"       # parchment icon on the home screen
DAILY_SCROLL_TAP = (32, 798)                # fallback tap if the icon is not matched
DAILY_PANEL_MARKER = "daily_refresh_marker.png"   # "Refreshes In:" pill (Daily tab, panel open)
DAILY_TAB_TAP = (357, 850)                  # "Daily" tab at the bottom of the panel
DAILY_CLAIM_ALL = "daily_claim_all.png"     # green "Claim All" (present only when there is something to claim)
DAILY_CLAIM_ALL_THRESHOLD = 0.85
DAILY_REWARDS_BANNER = "chest_rewards_banner.png"  # reused golden "Rewards" banner
DAILY_REWARDS_EXIT_TAP = (270, 160)         # neutral spot above the banner to dismiss rewards
DAILY_CLOSE_TAP = (517, 94)                 # "X" to close the panel
DAILY_MAX_CLAIM_PASSES = 5                  # safety cap on the claim/dismiss loop
DAILY_MAX_DISMISS = 8                       # safety cap on chained reward-popup dismissals

# After claiming, the task READS the still-pending daily missions (OCR of the
# list) and, for each one it recognises, runs the EXISTING bot task that makes
# progress on it (e.g. "Train 10 Infantry" -> train_troops). This actively
# drives the daily list instead of waiting for the main loop. Missions with no
# linked flow (recruit hero, upgrade building, research, gather, ...) are left
# for the player / other tasks.
DAILY_RUN_LINKED = True                     # master switch for the linked-flow execution
# Module names (under tasks/) allowed to be auto-run from the daily list. The
# heavy/slow ones (intel_missions, hunt_terror) are left OFF by default since
# they already run in the main loop and can take a long time / drain stamina;
# add them here to also drive them from the daily checker.
DAILY_LINKED_MODULES = ("help_alliance", "alliance_tech", "arena", "train_troops")
DAILY_LIST_REGION = (44, 368, 470, 800)     # x1,y1,x2,y2 OCR band over the mission list (y1=368 avoids clipping the top card title)
DAILY_LIST_SWIPE = (270, 700, 270, 430)     # one scroll-up step through the list
DAILY_LIST_MAX_SCROLLS = 6                  # safety cap while scanning the list

# Some missions have no linked flow but can be completed straight from the panel
# by tapping their in-panel "Go" button, which navigates NATIVELY to the right
# screen (e.g. "Recruit 1 Hero" -> Hero Recruitment, where a single free recruit
# finishes it). For those, the task taps "Go" and performs the small native
# action. Only missions with a registered handler (DAILY_GO_HANDLERS in
# tasks/daily_missions.py) are ever Go-tapped.
DAILY_USE_GO = True                         # master switch for Go-button completion
DAILY_GO_BUTTON = "daily_go_button.png"     # the blue per-mission "Go" button
DAILY_GO_THRESHOLD = 0.85
DAILY_GO_MAX_ACTIONS = 4                     # safety cap on how many Go missions to drive per run
DAILY_RECRUIT_FREE_TAP = (143, 635)         # "Recruit x1 Free" on the Hero Recruitment screen

# If True, saves an annotated screenshot ONLY when DEBUG is enabled.
# By default no image is written to disk — captures live only in memory.
DEBUG = False
