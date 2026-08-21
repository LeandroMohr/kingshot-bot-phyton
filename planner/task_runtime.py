"""Runtime data used to order tasks without hard-coding timings.

The file is intentionally kept under ``memory/``: it is local runtime state,
not part of the knowledge base.  Data is stored per account when the profile
reader has identified one, with a small global fallback for runs where OCR
could not read the account ID.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config


_FILE = config.BASE_DIR / "memory" / "task_runtime.json"


def _load() -> dict:
    try:
        data = json.loads(_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _bucket(account_id: str | None) -> str:
    return str(account_id) if account_id else "__default__"


def load_tasks(account_id: str | None) -> dict[str, dict]:
    data = _load().get("accounts", {})
    bucket = data.get(_bucket(account_id), {}) if isinstance(data, dict) else {}
    return bucket if isinstance(bucket, dict) else {}


def record_duration(account_id: str | None, task_name: str,
                    duration: float) -> dict:
    """Record a sample and return the updated task runtime record.

    ``order`` is assigned automatically only once.  Existing orders are never
    overwritten, so a user can safely adjust them manually later.
    """
    root = _load()
    accounts = root.setdefault("accounts", {})
    bucket = accounts.setdefault(_bucket(account_id), {})
    item = bucket.setdefault(task_name, {})
    samples = item.setdefault("duration_samples", [])
    if not isinstance(samples, list):
        samples = []
        item["duration_samples"] = samples
    samples.append(round(max(0.0, duration), 3))
    # Keep the runtime file small while retaining enough history for a stable
    # average.  The first observed duration determines the initial order; the
    # planner uses current durations to rank tasks that have no manual order.
    del samples[:-20]
    item["duration_seconds"] = round(sum(samples) / len(samples), 3)
    if not isinstance(item.get("order"), int):
        item["order"] = None
    item["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(root)
    return item


def set_order(account_id: str | None, task_name: str, order: int) -> None:
    root = _load()
    accounts = root.setdefault("accounts", {})
    bucket = accounts.setdefault(_bucket(account_id), {})
    item = bucket.setdefault(task_name, {})
    item["order"] = int(order)
    _save(root)


def task_sort_key(task, runtime: dict[str, dict]) -> tuple:
    """Return the default sort key for a task.

    Intel Missions is always before Hunting Terror because both compete for
    stamina, regardless of measured duration or manual order.
    """
    name = task.name.lower()
    # Hunting is placed in a later phase. Intel remains in the normal queue,
    # which lets quick tasks run first while still guaranteeing Intel before
    # any Terror hunt.
    phase = 1 if "hunt" in name and "terror" in name else 0

    item = runtime.get(task.name, {})
    order = item.get("order")
    if isinstance(order, int):
        return (phase, 0, float(order), name)
    duration = item.get("duration_seconds")
    # Unknown tasks go last until their first execution is measured.
    measured = float(duration) if isinstance(duration, (int, float)) else float("inf")
    return (phase, 1, measured, name)


def order_tasks(tasks: list, account_id: str | None) -> list:
    runtime = load_tasks(account_id)
    return sorted(tasks, key=lambda task: task_sort_key(task, runtime))
