"""The sample mailbox stays inside the review window after its original week."""

from datetime import datetime
from zoneinfo import ZoneInfo

from inbox_brief.curate import _in_period
from inbox_brief.domain import ParsedMessage
from inbox_brief.seed import place_in_review_window

LONDON = ZoneInfo("Europe/London")


def _message(message_id: str, date: str) -> ParsedMessage:
    return ParsedMessage(
        id=message_id,
        message_id=message_id,
        from_name="Mina Okonkwo",
        from_addr="mina.okonkwo@northline.example",
        to_addr="atlas@northline.example",
        subject="Sample",
        date=date,
        clean_body="The crates arrive Wednesday.",
        raw_body="The crates arrive Wednesday.",
    )


def test_sample_dates_slide_forward_into_the_current_week():
    now = datetime(2026, 10, 26, 12, tzinfo=LONDON)
    early = _message("early", "2026-10-16T09:05:00+00:00")
    latest = _message("latest", "2026-10-18T10:05:00+00:00")
    placed = place_in_review_window([early, latest], now)
    assert [item.id for item in placed] == ["early", "latest"]
    assert placed[1].date.startswith("2026-10-26")
    assert placed[0].date.startswith("2026-10-24")
    assert all(_in_period(item.date, now, "week") for item in placed)


def test_sample_dates_stay_put_during_their_own_week():
    now = datetime(2026, 10, 18, 12, tzinfo=LONDON)
    latest = _message("latest", "2026-10-18T10:05:00+00:00")
    placed = place_in_review_window([latest], now)
    assert placed[0].date == latest.date
