"""Kingshot bot main loop.

Flow:
  1. Connect to the emulator via ADB.
  2. On each cycle, go through the mapped tasks.
  3. For each task: check if it is available (template on screen).
     - Available    -> execute.
     - Not available -> move on to the next.
  4. Wait CYCLE_INTERVAL and repeat.

No screenshot is written to disk: captures are done in memory.

Multiple emulators:
  Run one process per emulator, each with its own port:
      python main.py --port 5605
      python main.py --port 5615   (in another terminal)
  Or list the connected ports with:
      python main.py --list
"""
from __future__ import annotations

import argparse
import select
import sys
import time

import config
from adb_controller import ADBController, list_devices, discover_devices
from tasks import TASKS
from tasks.base import Outcome
from executor import ensure_game_ready, go_to_home_screen, read_player_profile


def format_duration(seconds: float) -> str:
    """Format a duration in a friendly way: seconds below 60s, minutes from 60s
    up to under an hour, and hours from 60min on (e.g. '45s', '10min', '2h 15min')."""
    total_min = int(seconds // 60)
    hours, minutes = divmod(total_min, 60)
    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return f"{int(seconds)}s"


def describe_task(task) -> str:
    """Friendly description of a task for the startup announcement."""
    if task.loop:
        return f"{task.name} (checks every {format_duration(task.interval)})"
    return f"{task.name} (runs once)"


def check_task(controller: ADBController, port: int, task, now: float) -> None:
    """Run a single task, print its outcome and end single-run tasks.

    The game connection can hiccup (frozen screen / reload), making a task FAIL
    just because the templates weren't on screen at that moment. So on a genuine
    failure we retry up to config.TASK_RETRY_ATTEMPTS times; before each retry we
    recover (bring the game to the foreground and back to the home screen), which
    also handles the game reloading mid-task. "Nothing to do" (ABSENT) is not a
    failure and is never retried."""
    task.mark_checked(now)
    max_attempts = 1 + config.TASK_RETRY_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            outcome = task.execute(controller)
        except Exception as exc:  # do not let a task take down the loop
            outcome = None
            print(f"[emulator {port}] {task.name}: unexpected error ({exc})")
        else:
            print(f"[emulator {port}] {task.name}: {outcome}")
            if outcome in (Outcome.SUCCESS, Outcome.RECOVERED):
                task.mark_done()  # single-run task ends here
                return
            if outcome == Outcome.ABSENT:
                return  # nothing to do is not a failure — don't retry

        # Reaching here means the task FAILED (or raised). Retry if we still can.
        if attempt < max_attempts:
            print(f"[emulator {port}] {task.name}: retrying "
                  f"({attempt}/{max_attempts - 1}) after recovering...")
            ensure_game_ready(controller)   # relaunch if the game reloaded/crashed
            go_to_home_screen(controller)   # wait out lag / clear popups
            time.sleep(config.TASK_RETRY_DELAY)
        else:
            print(f"[emulator {port}] {task.name}: giving up for now "
                  f"(will try again next cycle).")



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kingshot bot (BlueStacks + ADB)")
    parser.add_argument(
        "--host", default=config.ADB_HOST, help="ADB host (default: %(default)s)"
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=f"Emulator ADB port. If omitted, you pick from a menu "
             f"(config default: {config.ADB_PORT}).",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Just list the connected emulators and exit.",
    )
    return parser.parse_args()


def choose_emulator(host: str) -> tuple[str, int] | None:
    """Interactive menu to pick which emulator to start on when no --port was
    given. Keeps asking until a valid option is chosen. Returns None if the
    user chooses to quit."""
    while True:
        devices = discover_devices(host)
        print("\nSelect the emulator to start:")
        for i, serial in enumerate(devices, 1):
            dev_host, _, dev_port = serial.partition(":")
            print(f"  {i} - Start on emulator {dev_port or serial}")
        print("  0 - Enter a port manually")
        print("  q - Quit")

        choice = input("Option: ").strip()

        if choice.lower() == "q":
            return None

        if choice == "0":
            port_str = input("Emulator ADB port: ").strip()
            if port_str.isdigit():
                return host, int(port_str)
            print("Invalid port. Let's try again.")
            continue

        if choice.isdigit() and 1 <= int(choice) <= len(devices):
            serial = devices[int(choice) - 1]
            dev_host, _, dev_port = serial.partition(":")
            return (dev_host or host), int(dev_port)

        print("Invalid option. Let's try again.")


def select_active_tasks(tasks: list) -> list:
    """Ask whether to run all mapped tasks or just a single one.

    Runs ALL tasks if the operator picks option 1, presses Enter, gives no
    answer within config.TASK_MENU_TIMEOUT seconds, or when the bot is not
    attached to a real terminal (so it never blocks a headless run). Picking
    option 2 opens a numbered list to choose one task."""
    if not tasks:
        return tasks
    if not sys.stdin or not sys.stdin.isatty():
        return tasks  # non-interactive: run everything

    print("\nWhat do you want to run?")
    print("  1 - All mapped tasks (default)")
    print("  2 - Pick a single task")
    print(f"Option (auto 'all' in {int(config.TASK_MENU_TIMEOUT)}s): ",
          end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], config.TASK_MENU_TIMEOUT)
    if not ready:
        print("\nNo answer; running all tasks.")
        return tasks

    choice = sys.stdin.readline().strip()
    if choice != "2":
        return tasks  # '1', empty or anything else -> all

    # Single-task submenu.
    print("\nAvailable tasks:")
    for i, task in enumerate(tasks, 1):
        print(f"  {i} - {task.name}")
    line = input("Task number (blank = all): ").strip()
    if line.isdigit() and 1 <= int(line) <= len(tasks):
        chosen = tasks[int(line) - 1]
        print(f"Running only: {chosen.name}")
        return [chosen]
    print("Invalid choice; running all tasks.")
    return tasks


def main() -> None:
    args = parse_args()

    if args.list:
        devices = list_devices()
        if not devices:
            print("No emulator connected. Run: adb connect 127.0.0.1:PORT")
        else:
            print("Connected emulators:")
            for d in devices:
                print(f"  - {d}")
        return

    if args.port is None:
        selection = choose_emulator(args.host)
        if selection is None:
            print("See you next time!")
            return
        host, port = selection
    else:
        host, port = args.host, args.port

    controller = ADBController(host=host, port=port)
    run_loop(controller)


def run_loop(controller: ADBController) -> None:
    port = controller.port
    print("==============================================")
    print("            Kingshot Bot started")
    print("==============================================")
    print(f"Connecting to emulator {port}...")
    controller.connect()
    print(f"Connected to emulator {port}!")

    # Ask whether to run all tasks or just one (defaults to all after a timeout).
    active_tasks = select_active_tasks(TASKS)

    # Make sure the game is open before starting.
    ensure_game_ready(controller, announce_if_open=True)

    # Announce the tasks that will run.
    if active_tasks:
        print("\nStarting tasks:")
        for task in active_tasks:
            print(f"  - {describe_task(task)}")
    else:
        print("\nNo active tasks right now.")
    print("\nBot running. Press Ctrl+C to stop.\n")

    start = time.monotonic()
    try:
        # Initial pass: right after opening the game, check ALL tasks once.
        # If the player was away, things that were loading/running are likely
        # done now, so we collect them immediately before the timed loop.
        ensure_game_ready(controller)
        go_to_home_screen(controller)
        read_player_profile(controller)  # snapshot account info once at startup
        print("Checking all tasks now that the game is open...")
        now = time.monotonic()
        for task in active_tasks:
            check_task(controller, port, task, now)

        # From here on, each task runs again only when its own interval elapses.
        while True:
            ensure_game_ready(controller)  # relaunch the game if it closes/crashes
            go_to_home_screen(controller)  # close welcome/promo popups before tasks
            now = time.monotonic()
            for task in active_tasks:
                if not task.due(now):
                    continue
                check_task(controller, port, task, now)
            # sleep a short step and re-check which tasks have hit their interval
            time.sleep(config.TICK_INTERVAL)
    except KeyboardInterrupt:
        elapsed = format_duration(time.monotonic() - start)
        print(f"\nKingshot Bot stopped after working for {elapsed}. See you next time!")


if __name__ == "__main__":
    main()
