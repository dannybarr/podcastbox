"""Parse .eml and .mbox files with the standard library."""

from __future__ import annotations

import email
import hashlib
import mailbox
import os
import tempfile
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr

from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.clean import clean_body, html_to_text


def parse_eml_bytes(data: bytes, source: str = "upload") -> ParsedMessage:
    message = email.message_from_bytes(data)
    return message_to_parsed(message, source)


def parse_mbox_bytes(data: bytes, source: str = "upload") -> list[ParsedMessage]:
    handle = tempfile.NamedTemporaryFile(suffix=".mbox", delete=False)
    try:
        handle.write(data)
        handle.close()
        box = mailbox.mbox(handle.name)
        try:
            return [message_to_parsed(message, source) for message in box]
        finally:
            box.close()
    finally:
        os.unlink(handle.name)


def parse_path(path: str, source: str = "upload") -> list[ParsedMessage]:
    with open(path, "rb") as handle:
        data = handle.read()
    if path.lower().endswith(".mbox"):
        return parse_mbox_bytes(data, source)
    return [parse_eml_bytes(data, source)]


def message_to_parsed(message: Message, source: str) -> ParsedMessage:
    from_name, from_addr = parseaddr(_header(message, "From"))
    _, to_addr = parseaddr(_header(message, "To"))
    subject = _header(message, "Subject")
    message_id = _message_id(_header(message, "Message-ID"))
    in_reply_to = _message_id(_header(message, "In-Reply-To"))
    references = [_message_id(part) for part in _header(message, "References").split() if part.strip()]
    references = [part for part in references if part]
    raw_body = _extract_body(message)
    clean = clean_body(raw_body)
    date = _date(message)
    identity = message_id or f"{from_addr}|{date}|{subject}|{raw_body[:400]}"
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return ParsedMessage(
        id=digest,
        message_id=message_id,
        from_name=from_name.strip(),
        from_addr=from_addr.strip(),
        to_addr=to_addr.strip(),
        subject=subject.strip(),
        date=date,
        clean_body=clean,
        raw_body=raw_body.strip(),
        in_reply_to=in_reply_to,
        references=references,
        list_unsubscribe=_header(message, "List-Unsubscribe"),
        precedence=_header(message, "Precedence"),
        auto_submitted=_header(message, "Auto-Submitted"),
        source=source,
        provider_thread_id=_header(message, "X-Provider-Thread").strip(),
    )


def _header(message: Message, name: str) -> str:
    raw = message.get(name)
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(str(raw))))
    except Exception:
        return str(raw)


def _message_id(value: str) -> str:
    text = value.strip()
    if text.startswith("<") and text.endswith(">"):
        return text[1:-1].strip()
    return text


def _date(message: Message) -> str:
    raw = message.get("Date")
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        return ""
    if parsed.tzinfo is None:
        return parsed.isoformat() + "Z"
    return parsed.isoformat()


def _extract_body(message: Message) -> str:
    plain: str | None = None
    html: str | None = None
    if message.is_multipart():
        for part in message.walk():
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain" and plain is None:
                plain = _decode_part(part)
            elif content_type == "text/html" and html is None:
                html = _decode_part(part)
    else:
        content_type = message.get_content_type()
        decoded = _decode_part(message)
        if content_type == "text/html":
            html = decoded
        else:
            plain = decoded
    if plain and plain.strip():
        return plain
    if html and html.strip():
        return html_to_text(html)
    return ""


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    if not isinstance(payload, (bytes, bytearray)):
        return str(payload)
    charset = part.get_content_charset() or "utf-8"
    try:
        return bytes(payload).decode(charset, errors="replace")
    except LookupError:
        return bytes(payload).decode("utf-8", errors="replace")
