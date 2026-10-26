"""Calendar days for podcasts and chain updates.

A podcast belongs to the local day it was generated. That day is read from
created_at each time the library is opened, so nothing has to run at midnight.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from inbox_brief.settings import now_in

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def zone_for(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("Europe/London")


def parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_day(value: str | None, timezone_name: str) -> date | None:
    instant = parse_instant(value)
    if instant is None:
        return None
    return instant.astimezone(zone_for(timezone_name)).date()


def day_label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def short_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def bucket_podcasts(episodes: list[dict], timezone_name: str, now: datetime | None = None) -> dict:
    """Split episodes into today and older library days, newest day first."""
    if now is None:
        current = now_in(timezone_name)
    else:
        zone = zone_for(timezone_name)
        current = now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)
    today = current.date()
    today_items: list[dict] = []
    groups: dict[date, list[dict]] = {}
    for episode in episodes:
        day = local_day(episode.get("created_at"), timezone_name)
        if day is None or day == today:
            today_items.append(episode)
        else:
            groups.setdefault(day, []).append(episode)
    library = []
    for day in sorted(groups, reverse=True):
        library.append(
            {
                "date": day.isoformat(),
                "label": day_label(day),
                "count": len(groups[day]),
                "podcasts": groups[day],
            }
        )
    return {"today": today_items, "library": library, "timezone": timezone_name}


def annotate_chain(chain: dict, records: list[dict], dates: dict[str, str], timezone_name: str) -> dict:
    """Mark a chain when later-day mail arrived after the last podcast."""
    own = set(chain.get("message_ids") or [])
    covered: set[str] = set()
    for record in records:
        recorded = set(record.get("message_ids") or [])
        if record.get("chain_id") == chain.get("id") or (recorded & own):
            covered |= recorded & own
    fresh: list[str] = []
    latest_day: date | None = None
    if covered:
        dated = [dates[item] for item in covered if dates.get(item)]
        if dated:
            latest_day = local_day(max(dated), timezone_name)
        for item in chain.get("message_ids") or []:
            if item in covered:
                continue
            day = local_day(dates.get(item), timezone_name)
            if latest_day is not None and day is not None and day > latest_day:
                fresh.append(item)
    label = ""
    new_since = ""
    if fresh and latest_day is not None:
        noun = "message" if len(fresh) == 1 else "messages"
        label = f"New since {short_date(latest_day)}: {len(fresh)} {noun}"
        new_since = latest_day.isoformat()
    annotated = dict(chain)
    annotated["covered"] = bool(covered)
    annotated["covered_ids"] = sorted(covered)
    annotated["new_count"] = len(fresh)
    annotated["new_since"] = new_since
    annotated["new_label"] = label
    annotated["fresh_ids"] = fresh
    return annotated
