"""Fire the daily brief at the configured local time."""

from __future__ import annotations

import logging
import threading

from inbox_brief.db import get_settings
from inbox_brief.jobs import start_generate
from inbox_brief.settings import now_in, should_run
from inbox_brief.store import get_schedule_date, set_schedule_date

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="inbox-brief-schedule", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def _loop() -> None:
    while not _stop.wait(20):
        try:
            _tick()
        except Exception:
            logger.exception("Daily schedule tick failed.")


def _tick() -> None:
    settings = get_settings()
    current = now_in(settings["timezone"])
    if should_run(current, settings["schedule_time"], get_schedule_date(), settings["schedule_enabled"]):
        set_schedule_date(current.date().isoformat())
        start_generate("window")
