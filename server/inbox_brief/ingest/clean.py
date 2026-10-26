"""Turn a raw email body into the words the brief is allowed to use.

Quoted replies, signatures, and legal footers are dropped so a later message
is not summarised twice and so a disclaimer is never read aloud.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

REPLY_MARKERS = [
    re.compile(r"\nOn [^\n]{0,300} wrote:\s*\n", re.IGNORECASE),
    re.compile(r"\n-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"\n_{5,}\n"),
    re.compile(r"\nBegin forwarded message:\s*\n", re.IGNORECASE),
    re.compile(r"\nFrom:\s[^\n]+\nSent:\s[^\n]+\nTo:\s", re.IGNORECASE),
]

SIGNOFF = re.compile(
    r"\n(?:thanks|thank you|cheers|best regards|kind regards|best|regards|sincerely)[,!]?\s*\n[\s\S]*$",
    re.IGNORECASE,
)

FOOTER_MARKERS = (
    "this message and any attachments",
    "this email and any attachments",
    "confidentiality notice",
    "the information contained in this",
    "intended only for the recipient",
    "if you received it in error",
    "unsubscribe",
    "you are receiving this",
    "sent from my iphone",
    "sent from my ipad",
    "sent from my mobile",
    "get outlook for",
    "sent from mail for windows",
    "sent from outlook",
)


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        if tag in {"p", "br", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def clean_body(text: str) -> str:
    if not text:
        return ""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    cut = len(normalised)
    for pattern in REPLY_MARKERS:
        match = pattern.search(normalised)
        if match:
            cut = min(cut, match.start())
    body = normalised[:cut]
    lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    signature = re.search(r"\n-- \n", body)
    if signature:
        body = body[: signature.start()]
    else:
        bare = re.search(r"\n--\n", body)
        if bare:
            body = body[: bare.start()]
    lower_lines = body.split("\n")
    kept: list[str] = []
    for line in lower_lines:
        if any(marker in line.lower() for marker in FOOTER_MARKERS):
            break
        kept.append(line)
    body = SIGNOFF.sub("", "\n".join(kept))
    body = _drop_trailing_signoff(body)
    body = _drop_leading_greeting(body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _drop_leading_greeting(text: str) -> str:
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^(hi|hello|hey|dear)\b[^\n]{0,40}$", lines[0].strip(), re.IGNORECASE):
        lines.pop(0)
    return "\n".join(lines).strip()


def _drop_trailing_signoff(text: str) -> str:
    lines = text.split("\n")
    while lines:
        line = lines[-1].strip()
        if not line:
            lines.pop()
            continue
        words = line.split()
        looks_like_name = (
            len(words) <= 6
            and not re.search(r"[.!?]$", line)
            and not re.search(r"\d", line)
        )
        if looks_like_name:
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()
