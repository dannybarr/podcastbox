"""A podcast that walks the whole review-period inbox, one chain at a time.

Noise is the same filter as All emails. Each chain is spoken once, most
significant first. A later refresh can read only mail the last overview
did not already cover.
"""

from __future__ import annotations

import re

from inbox_brief.domain import ParsedMessage, Script, SegmentDraft

OVERVIEW_CHAIN_ID = "overview"

_ASK = re.compile(
    r"\b(please|can we|can you|could you|i need|need the|need you|before|deadline|due|"
    r"by friday|by monday|by tuesday|by wednesday|by thursday|by saturday|by sunday|"
    r"asked)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def period_label(period: str) -> str:
    return {"day": "today", "week": "this week", "month": "this month"}.get(period, "this week")


def significance_key(chain: dict) -> tuple:
    """Recommended chains lead. Longer chains, then more people, then newer mail."""
    return (
        1 if chain.get("recommended") else 0,
        int(chain.get("message_count") or len(chain.get("message_ids") or [])),
        len(chain.get("participants") or []),
        chain.get("date_end") or "",
        chain.get("id") or "",
    )


def order_overview(chains: list[dict]) -> list[dict]:
    """Most significant first. A chain id, and a message id, appear once."""
    ranked = sorted(chains, key=significance_key, reverse=True)
    seen_chains: set[str] = set()
    seen_messages: set[str] = set()
    ordered: list[dict] = []
    for chain in ranked:
        identity = str(chain.get("id") or "")
        if not identity or identity in seen_chains:
            continue
        seen_chains.add(identity)
        ids = []
        for message_id in chain.get("message_ids") or []:
            if message_id in seen_messages:
                continue
            seen_messages.add(message_id)
            ids.append(message_id)
        if not ids:
            continue
        item = dict(chain)
        item["message_ids"] = ids
        item["message_count"] = len(ids)
        ordered.append(item)
    return ordered


def focus_question(chains: list[dict], question: str) -> list[dict]:
    """Pull matching chains forward. Everything else still follows, in the same order."""
    tokens = [token for token in re.findall(r"[a-z0-9']{3,}", (question or "").lower())]
    if not tokens:
        return list(chains)
    matched = []
    rest = []
    for chain in chains:
        text = f"{chain.get('title') or ''} {chain.get('search_text') or ''}".lower()
        if any(token in text for token in tokens):
            matched.append(chain)
        else:
            rest.append(chain)
    return matched + rest


def overview_selection(
    chains: list[dict],
    *,
    covered_ids: set[str] | None = None,
    scope: str = "full",
    question: str = "",
) -> list[dict]:
    ordered = focus_question(order_overview(chains), question)
    if scope != "changed" or not covered_ids:
        return ordered
    covered = set(covered_ids)
    fresh: list[dict] = []
    for chain in ordered:
        ids = [message_id for message_id in chain["message_ids"] if message_id not in covered]
        if not ids:
            continue
        item = dict(chain)
        item["message_ids"] = ids
        item["message_count"] = len(ids)
        fresh.append(item)
    return fresh


def overview_status(settings: dict) -> dict:
    """What the Home card shows: today's overview, and mail not yet covered."""
    from inbox_brief.days import local_day
    from inbox_brief.settings import now_in
    from inbox_brief.store import inbox_chains, overview_records

    zone = settings.get("timezone") or "Europe/London"
    period = settings.get("review_period") or "week"
    chains = inbox_chains(settings, "")
    selected = overview_selection(chains, scope="full")
    email_ids = [message_id for chain in selected for message_id in chain["message_ids"]]
    records = overview_records()
    covered: set[str] = set()
    for record in records:
        covered.update(record["message_ids"])
    today = now_in(zone).date()
    todays = [record for record in records if local_day(record["created_at"], zone) == today]
    fresh = [message_id for message_id in email_ids if message_id not in covered]
    return {
        "email_count": len(email_ids),
        "chain_count": len(selected),
        "generated": bool(todays),
        "episode_id": todays[0]["id"] if todays else None,
        "new_count": len(fresh) if covered else 0,
        "period_label": period_label(period),
        "has_prior": bool(records),
    }


def covered_overview_ids() -> set[str]:
    from inbox_brief.store import overview_records

    covered: set[str] = set()
    for record in overview_records():
        covered.update(record["message_ids"])
    return covered


def overview_chains(
    messages: list[ParsedMessage],
    *,
    now,
    period: str = "week",
    drop_newsletters: bool = True,
    drop_noreply: bool = True,
    extra_patterns: list[str] | None = None,
) -> list[dict]:
    """All non-noise chains in the review period, in overview order."""
    from inbox_brief.curate import build_chains

    built = build_chains(
        messages,
        now=now,
        period=period,
        drop_newsletters=drop_newsletters,
        drop_noreply=drop_noreply,
        extra_patterns=extra_patterns or [],
    )
    return order_overview(built)


def compose_overview(
    chains: list[dict],
    messages: dict[str, ParsedMessage],
    *,
    email_count: int,
    period: str,
    style: str = "full",
    fresh: bool = False,
) -> Script:
    """One sourced segment per email. Full reads every substantive sentence, with no cap."""
    if style not in {"full", "deep", "quick", "action"}:
        style = "full"
    segments: list[SegmentDraft] = []
    seen: set[str] = set()
    started = False
    for chain in chains:
        group = _chain_messages(chain, messages)
        if not group:
            continue
        for index, message in enumerate(group):
            sentences = _choose(_substantive(message.clean_body, seen), style)
            if not sentences:
                continue
            given = _given_name(message.sender_label)
            about = _subject(message)
            if not started:
                noun = "email" if email_count == 1 else "emails"
                new = "new " if fresh else ""
                lead = f"{email_count} {new}{noun} {period_label(period)}, first from {given}, about {about}."
                started = True
            elif index == 0:
                lead = f"Next, from {given}, about {about}."
            else:
                lead = ""
            body = " ".join(sentences)
            text = f"{lead} {message.sender_label} wrote: {body}".strip()
            segments.append(
                SegmentDraft(
                    speaker="S1" if len(segments) % 2 == 0 else "S2",
                    text=text,
                    source_ids=[message.id],
                    delivery="emphasis" if any(_ASK.search(sentence) for sentence in sentences) else "steady",
                )
            )
    return Script(title="Full inbox overview", segments=segments)


def _chain_messages(chain: dict, messages: dict[str, ParsedMessage]) -> list[ParsedMessage]:
    group = [messages[item] for item in chain.get("message_ids") or [] if item in messages]
    group = [message for message in group if (message.clean_body or "").strip()]
    group.sort(key=lambda message: (message.date or "", message.id))
    return group


def _given_name(label: str) -> str:
    parts = [part for part in (label or "").replace(",", " ").split() if part]
    if not parts:
        return "them"
    if "@" in parts[0]:
        return parts[0].split("@", 1)[0]
    return parts[0]


def _subject(message: ParsedMessage) -> str:
    subject = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", message.subject or "", flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", subject) or "this email"


_PLEASANTRY = re.compile(
    r"^(?:hi|hello|hey|dear)\b|"
    r"^(?:thanks|thank you|cheers|best regards|kind regards|regards|sincerely)\b|"
    r"^hope you(?:'re| are) (?:well|doing well)\b",
    re.IGNORECASE,
)
_FILLER = (
    "confidentiality notice",
    "this email and any attachments",
    "this message and any attachments",
    "intended only for the recipient",
    "if you received it in error",
    "sent from my iphone",
    "sent from my ipad",
    "sent from my mobile",
)
_DECISION = re.compile(
    r"\b(confirmed|decided|agreed|holding|booked|signed off|stays|will send|will publish)\b",
    re.IGNORECASE,
)
_FIGURE = re.compile(r"\d")


def _substantive(body: str, seen: set[str]) -> list[str]:
    """Sentences worth reading. Greetings, sign-offs, disclaimers, and repeated quotes stay out."""
    text = re.sub(r"\s+", " ", body or "").strip()
    kept: list[str] = []
    for part in _SENTENCE.split(text):
        sentence = part.strip()
        sentence = re.sub(r"^(?:hi|hello|hey|dear)\b[^,]{0,40},\s*", "", sentence, flags=re.IGNORECASE).strip()
        if not sentence or _PLEASANTRY.match(sentence):
            continue
        lowered = sentence.lower()
        if any(marker in lowered for marker in _FILLER):
            continue
        if len(sentence.split()) <= 2 and not _FIGURE.search(sentence):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return kept


def _choose(sentences: list[str], style: str) -> list[str]:
    """Full and deep keep every sentence. Quick and action are the shorter choices, still uncapped."""
    if style in {"full", "deep"}:
        return sentences
    if style == "action":
        chosen = [sentence for sentence in sentences if _ASK.search(sentence) or _DECISION.search(sentence)]
    else:
        chosen = [
            sentence
            for sentence in sentences
            if _ASK.search(sentence) or _DECISION.search(sentence) or _FIGURE.search(sentence)
        ]
    return chosen or sentences
