"""Turn messages into one card per topic for the current review period.

Header threading and provider thread ids run first. Embeddings then join
separate threads that are about the same topic. When a model is configured,
it can add a link the embeddings left undecided. Low-value mail never becomes
a card.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.noise import noise_reason
from inbox_brief.ingest.thread import normalize_subject, thread_messages

_STOP = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "but", "can", "for", "from", "have", "her", "here", "his", "into", "just",
    "mail", "message", "more", "not", "once", "our", "out", "she", "that", "the",
    "their", "them", "then", "there", "they", "this", "update", "was", "were",
    "what", "when", "with", "you", "your", "communications", "still", "until",
    "works", "would", "could", "should", "which", "where", "other", "every",
    "being", "under", "never", "always", "first", "those", "these", "going",
    "having", "doing", "afternoon", "morning",
}
_PROJECT = re.compile(r"\bProject\s+([A-Z][A-Za-z0-9]+)")
_TOKEN = re.compile(r"[a-z][a-z0-9']{2,}")
_DIM = 64


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def build_chains(
    messages: list[ParsedMessage],
    *,
    now: datetime,
    period: str = "week",
    drop_newsletters: bool = True,
    drop_noreply: bool = True,
    extra_patterns: list[str] | None = None,
    extra_links: list[tuple[str, str]] | None = None,
    linker=None,
) -> list[dict]:
    """Return recommended and askable chains. Each topic appears once."""
    kept: list[ParsedMessage] = []
    for message in messages:
        reason = noise_reason(
            message,
            drop_newsletters=drop_newsletters,
            drop_noreply=drop_noreply,
            extra_patterns=extra_patterns or [],
        )
        if reason or not _in_period(message.date, now, period):
            continue
        if not (message.clean_body or "").strip():
            continue
        kept.append(message)
    threads = thread_messages(kept)
    linked = list(extra_links or [])
    if linker is not None:
        linked.extend(linker(threads) or [])
    groups = _cluster(threads, linked)
    chains = [_chain(members, threads) for members in groups if members]
    chains.sort(key=lambda item: item["date_end"] or "", reverse=True)
    chains.sort(key=lambda item: 0 if item["recommended"] else 1)
    return chains


def ask_chains(chains: list[dict], query: str) -> list[dict]:
    """Rank chains for a plain-language question. Blank returns the recommended set."""
    text = (query or "").strip()
    if not text:
        return [chain for chain in chains if chain["recommended"]]
    lowered = text.lower()
    query_tokens = [token for token in _tokens(lowered) if token not in _STOP]
    ranked: list[tuple[float, dict]] = []
    for chain in chains:
        cosine = _cosine(_embed(" ".join(query_tokens)), _embed(chain.get("search_text") or ""))
        people = " ".join(person["name"].lower() for person in chain["participants"])
        addresses = " ".join(person["addr"].lower() for person in chain["participants"])
        lexical = bool(query_tokens) and all(token in (chain.get("search_text") or "").lower() for token in query_tokens)
        named = any(person["name"].lower() in lowered and len(person["name"]) > 2 for person in chain["participants"])
        address_hit = any(token and token in addresses for token in query_tokens)
        # A chain with none of the query words is returned only when it is as close
        # as two threads the curator would merge.
        if not (lexical or named or address_hit or cosine >= 0.62):
            continue
        score = cosine
        if named:
            score += 0.45
        if address_hit:
            score += 0.35
        if lexical:
            score += 0.25
        if "communication" in lowered and any(part in people or part in addresses for part in query_tokens):
            score += 0.2
        ranked.append((score, chain))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chain for _score, chain in ranked]


def suggest_links(threads: dict[str, list[ParsedMessage]], settings: dict) -> list[tuple[str, str]]:
    """Ask the configured model which undecided threads share a topic.

    A missing key or an unreachable model leaves the embedding links as they are.
    """
    from inbox_brief.ai import chat

    if len(threads) < 2:
        return []
    lines = []
    for members in threads.values():
        head = members[0]
        lines.append(f"{head.id}\t{head.subject}\t{head.clean_body[:220].replace(chr(10), ' ')}")
    raw = chat(
        settings,
        "You link email threads that are the same topic. Reply with JSON only: "
        '{"link":[["message id","message id"]]}. Link threads only when the text is about the same effort. '
        "Do not link news, receipts, or unrelated work.",
        "\n".join(lines),
        timeout=4,
    )
    if not raw:
        return []
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    pairs = []
    for pair in payload.get("link") or []:
        if isinstance(pair, list) and len(pair) == 2:
            pairs.append((str(pair[0]), str(pair[1])))
    return pairs


def public_chain(chain: dict) -> dict:
    hidden = dict(chain)
    hidden.pop("search_text", None)
    return hidden


def period_start(now: datetime, period: str) -> datetime:
    days = {"day": 1, "week": 7, "month": 31}.get(period, 7)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(days=days)


def _cluster(threads: dict[str, list[ParsedMessage]], extra_links: list[tuple[str, str]]) -> list[list[str]]:
    ids = list(threads)
    if not ids:
        return []
    blobs = {thread_id: _blob(threads[thread_id]) for thread_id in ids}
    vectors = {thread_id: _embed(blobs[thread_id]) for thread_id in ids}
    token_sets = {thread_id: set(_tokens(blobs[thread_id])) for thread_id in ids}
    counts: Counter[str] = Counter()
    for tokens in token_sets.values():
        counts.update(tokens)
    cap = max(2, int(len(ids) * 0.5))
    salient = {
        thread_id: {token for token in tokens if len(token) >= 5 and counts[token] <= cap}
        for thread_id, tokens in token_sets.items()
    }
    union = _Union()
    for thread_id in ids:
        union.add(thread_id)
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            shared = {token for token in salient[left] & salient[right] if token not in _STOP and len(token) >= 5}
            score = _cosine(vectors[left], vectors[right])
            rare = any(counts[token] <= 2 for token in shared)
            if score >= 0.62 or (len(shared) >= 2 and score >= 0.32) or (rare and score >= 0.2):
                union.union(left, right)
    id_by_message = {message.id: thread_id for thread_id, members in threads.items() for message in members}
    for left_id, right_id in extra_links:
        left = id_by_message.get(left_id)
        right = id_by_message.get(right_id)
        if left and right:
            union.union(left, right)
    grouped: dict[str, list[str]] = defaultdict(list)
    for thread_id in ids:
        grouped[union.find(thread_id)].append(thread_id)
    return list(grouped.values())


def _chain(thread_ids: list[str], threads: dict[str, list[ParsedMessage]]) -> dict:
    messages: list[ParsedMessage] = []
    for thread_id in thread_ids:
        messages.extend(threads[thread_id])
    messages.sort(key=lambda item: (item.date or "9999", item.id))
    people: dict[str, tuple[str, str]] = {}
    for message in messages:
        key = (message.from_addr or message.from_name or message.id).lower()
        people.setdefault(key, (message.sender_label, message.from_addr))
    project = _project(messages)
    topic = _topic(messages)
    title = f"Project {project}" if project else topic or "Untitled chain"
    reason_bits = [
        f"{len(people)} {'person' if len(people) == 1 else 'people'}",
        f"{len(messages)} {'message' if len(messages) == 1 else 'messages'}",
    ]
    if project:
        reason_bits.append(f"Project {project}")
    elif topic:
        reason_bits.append(topic)
    recommended = _recommended(len(people), len(messages), bool(project))
    # The earliest message keeps the id stable when a later reply arrives.
    root = messages[0].id if messages else ""
    identity = hashlib.sha256(root.encode()).hexdigest()[:12]
    search = " ".join(
        [title, topic or "", project or ""]
        + [message.subject for message in messages]
        + [message.clean_body for message in messages]
        + [name for name, _addr in people.values()]
    )
    return {
        "id": identity,
        "title": title,
        "reason": ", ".join(reason_bits),
        "recommended": recommended,
        "participants": [{"name": name, "addr": addr} for name, addr in people.values()],
        "message_ids": [message.id for message in messages],
        "message_count": len(messages),
        "date_start": messages[0].date if messages else "",
        "date_end": messages[-1].date if messages else "",
        "project": project or "",
        "search_text": search,
    }


def _recommended(people: int, messages: int, project: bool) -> bool:
    if people >= 3 and messages >= 4:
        return True
    if messages >= 6:
        return True
    return bool(project and messages >= 3 and people >= 2)


def _project(messages: list[ParsedMessage]) -> str:
    found: Counter[str] = Counter()
    for message in messages:
        for match in _PROJECT.findall(f"{message.subject}\n{message.clean_body}"):
            found[match] += 1
    if not found:
        return ""
    name, count = found.most_common(1)[0]
    return name if count >= 1 else ""


def _topic(messages: list[ParsedMessage]) -> str:
    subjects = [normalize_subject(message.subject) for message in messages if message.subject]
    if not subjects:
        return ""
    chosen = Counter(subjects).most_common(1)[0][0]
    for message in messages:
        if normalize_subject(message.subject) == chosen:
            text = re.sub(r"^(?:re|fw|fwd|aw|sv)\s*:\s*", "", message.subject.strip(), flags=re.IGNORECASE)
            return re.sub(r"\s+", " ", text).strip()
    return chosen


def _blob(messages: list[ParsedMessage]) -> str:
    return "\n".join(f"{message.subject}\n{message.clean_body}" for message in messages)


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOP]


def _embed(text: str) -> list[float]:
    vector = [0.0] * _DIM
    tokens = _tokens(text)
    grams = tokens + [f"{left} {right}" for left, right in zip(tokens, tokens[1:])]
    for token in grams:
        digest = hashlib.sha256(token.encode()).digest()
        vector[digest[0] % _DIM] += 1 if digest[1] % 2 == 0 else -1
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if not any(left) or not any(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _in_period(value: str, now: datetime, period: str) -> bool:
    if not value:
        return True
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return period_start(now, period) <= when <= now + timedelta(days=1)


def chain_to_row(chain: dict, period_key: str) -> tuple:
    return (
        chain["id"],
        chain["title"],
        chain["reason"],
        1 if chain["recommended"] else 0,
        json.dumps(chain["participants"]),
        json.dumps(chain["message_ids"]),
        chain["message_count"],
        chain["date_start"],
        chain["date_end"],
        chain["project"],
        period_key,
        chain.get("search_text") or "",
    )
