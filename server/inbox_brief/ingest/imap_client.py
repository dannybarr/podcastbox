"""Read-only IMAP fetch for the last N hours."""

from __future__ import annotations

import imaplib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.parse import parse_eml_bytes


def fetch_imap(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    use_ssl: bool,
    since: datetime,
) -> list[ParsedMessage]:
    if not host or not user:
        raise RuntimeError("IMAP needs a host and a username.")
    client: imaplib.IMAP4
    if use_ssl:
        client = imaplib.IMAP4_SSL(host, port)
    else:
        client = imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        status, _ = client.select(folder or "INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open IMAP folder {folder!r}.")
        criterion = since.strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", criterion)
        if status != "OK" or not data or not data[0]:
            return []
        messages: list[ParsedMessage] = []
        for number in data[0].split():
            status, fetched = client.fetch(number, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue
            raw = _payload(fetched)
            if raw is None:
                continue
            parsed = parse_eml_bytes(raw, source="imap")
            if _within_window(parsed.date, since):
                messages.append(parsed)
        return messages
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _payload(fetched) -> bytes | None:
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def _within_window(value: str, since: datetime) -> bool:
    if not value:
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    start = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    return parsed >= start
