"""Drop newsletters and automated senders when the operator asks for that."""

from __future__ import annotations

import re

from inbox_brief.domain import ParsedMessage

_NOREPLY = re.compile(
    r"(no[-_.]?reply|noreply|do[-_.]?not[-_.]?reply|mailer-daemon|newsletter)",
    re.IGNORECASE,
)
_QUICK = re.compile(
    r"^(thanks|thank you|ok|okay|got it|sounds good|on my way|will do|noted|quick note)[.!\s]*$",
    re.IGNORECASE,
)
_RECEIPT = re.compile(r"\b(receipt|order confirmation|payment received|payment confirmation)\b", re.IGNORECASE)
_REMINDER = re.compile(r"\breminder\b", re.IGNORECASE)
_NOTIFICATION = re.compile(r"\bnotification\b", re.IGNORECASE)
_CALENDAR = re.compile(r"^(accepted|declined|tentative|invitation)\s*:", re.IGNORECASE)


def noise_reason(
    message: ParsedMessage,
    *,
    drop_newsletters: bool,
    drop_noreply: bool,
    extra_patterns: list[str],
) -> str | None:
    sender = f"{message.from_name} {message.from_addr}".lower()
    subject = message.subject.lower()
    haystack = f"{sender} {subject}"
    for pattern in extra_patterns:
        token = pattern.strip().lower()
        if token and token in haystack:
            return f"matched extra pattern {pattern!r}"
    if drop_newsletters:
        if message.list_unsubscribe.strip():
            return "list-unsubscribe header"
        if message.precedence.strip().lower() in {"bulk", "list", "junk"}:
            return f"precedence {message.precedence.strip().lower()}"
        if "newsletter" in sender:
            return "newsletter sender"
    if drop_noreply:
        auto = message.auto_submitted.strip().lower()
        if auto and auto != "no":
            return f"auto-submitted {auto}"
        if _NOREPLY.search(sender):
            return "no-reply sender"
    if _CALENDAR.search(message.subject) or ("calendar" in sender and _REMINDER.search(message.subject)):
        return "calendar"
    if _RECEIPT.search(message.subject) or _RECEIPT.search(message.clean_body[:180]):
        return "receipt"
    if _REMINDER.search(message.subject) or "reminder@" in sender:
        return "reminder"
    if _NOTIFICATION.search(message.subject) or "notifications@" in sender or "notification@" in sender:
        return "notification"
    if _is_quick_note(message):
        return "quick note"
    return None


def _is_quick_note(message: ParsedMessage) -> bool:
    body = re.sub(r"\s+", " ", message.clean_body or "").strip()
    if len(body) > 48:
        return False
    if _QUICK.match(body):
        return True
    subject = re.sub(r"^(re|fw|fwd)\s*:\s*", "", message.subject or "", flags=re.IGNORECASE).strip()
    return bool(_QUICK.match(subject) and len(body) <= 48)
